"""Tests of the generation process: reproducibility, batching and parallelism, and per-batch validation."""
import pytest
from rdflib import Graph, Literal, SH, URIRef

from support import REPO_ROOT, load_shapes, parse_turtle

from rdf_graph_gen.multiprocess_generate import MultiprocessGenerator
from rdf_graph_gen.rdf_graph_generator import generate_graph
from rdf_graph_gen.shacl_mapping_generator import define_dependencies, generate_dictionary_from_shapes_graph
from rdf_graph_gen.validation import validate_generated

# Nested node shapes, several datatypes, cardinality ranges and a sh:lessThan pair
THREE_COMPLEX = str(REPO_ROOT / "experiment_suite" / "shape-three-complex.ttl")
# Shapes that no data can conform to (two distinct values, but sh:in allows only one), so the generated data has
# validation results, including results of nested entities (ex:A) that propagate to their parents (ex:S)
UNSATISFIABLE = """
    @prefix sh: <http://www.w3.org/ns/shacl#> . @prefix ex: <http://example.org/> .
    ex:S a sh:NodeShape ; sh:property [ sh:path ex:name ; sh:in ("a") ; sh:minCount 2 ] ;
        sh:property [ sh:path ex:address ; sh:node ex:A ; sh:minCount 1 ; sh:maxCount 1 ] .
    ex:A a sh:NodeShape ; sh:property [ sh:path ex:code ; sh:in ("x") ; sh:minCount 2 ] .
"""


def test_same_seed_same_graph():
    shapes = load_shapes(path=THREE_COMPLEX)
    first = generate_graph(shapes, 20, seed=5).serialize(format="nt")
    second = generate_graph(shapes, 20, seed=5).serialize(format="nt")
    assert first == second


def test_different_seeds_different_graphs():
    shapes = load_shapes(path=THREE_COMPLEX)
    assert generate_graph(shapes, 20, seed=5).serialize(format="nt") != \
        generate_graph(shapes, 20, seed=6).serialize(format="nt")


def test_output_does_not_depend_on_the_number_of_processes(tmp_path):
    outputs = []
    for processes in (1, 3):
        output = tmp_path / f"out-{processes}.ttl"
        MultiprocessGenerator(THREE_COMPLEX, str(output), 40, 7, processes=processes, seed=11).generate()
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]


def test_entity_identifiers_are_unique_across_batches(tmp_path):
    output = tmp_path / "out.ttl"
    MultiprocessGenerator(THREE_COMPLEX, str(output), 40, 7, processes=1, seed=11).generate()
    graph = Graph().parse(output)
    # 40 top-level entities, each with one address and one date entity: 120 distinct generated entities
    assert len(set(graph.subjects(SH.description, None))) == 120


def test_per_batch_validation_equals_whole_graph_validation(tmp_path):
    shapes, output = tmp_path / "shapes.ttl", tmp_path / "out.ttl"
    shapes.write_text(UNSATISFIABLE, encoding="utf-8")
    per_batch = MultiprocessGenerator(str(shapes), str(output), 40, 7, processes=2, seed=3, validate=True).generate()
    whole = validate_generated(load_shapes(path=shapes), Graph().parse(output))
    assert not whole.conforms and whole.propagated_results
    for name in ("conforms", "focus_nodes", "provenance_focus_nodes", "violating_focus_nodes",
                 "root_cause_focus_nodes", "results_by_constraint", "propagated_results"):
        assert getattr(per_batch, name) == getattr(whole, name), name


def test_per_batch_validation_checks_declared_target_nodes_once(tmp_path):
    shapes = tmp_path / "shapes.ttl"
    shapes.write_text("""
        @prefix sh: <http://www.w3.org/ns/shacl#> . @prefix ex: <http://example.org/> .
        ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:minCount 1 ] .
        ex:Constant a sh:NodeShape ; sh:targetNode ex:alice ; sh:property [ sh:path ex:name ; sh:minCount 1 ] .
    """, encoding="utf-8")
    summary = MultiprocessGenerator(str(shapes), str(tmp_path / "out.ttl"), 10, 3, processes=1, seed=1,
                                    validate=True).generate()
    # ex:alice (no ex:name in the generated data) is reported once, not once per batch (4 batches)
    assert summary.results_by_constraint[("sh:minCount", "ex:name")] == 1


def test_complex_property_paths_never_produce_invalid_rdf():
    shapes = parse_turtle("""
        ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:name ; sh:minCount 1 ] ;
            sh:property [ sh:path ( ex:a ex:b ) ; sh:minCount 1 ] ;
            sh:property [ sh:path [ sh:inversePath ex:c ] ; sh:minCount 1 ] ;
            sh:xone ( [ sh:path [ sh:zeroOrMorePath ex:d ] ; sh:minCount 1 ] [ sh:path ex:e ; sh:minCount 1 ] ) .
    """)
    with pytest.warns(UserWarning, match="is not supported yet"):
        graph = generate_graph(shapes, 20, seed=1)
    # complex paths used to be written as (blank node) predicates, which is not valid RDF
    assert all(isinstance(predicate, URIRef) for predicate in graph.predicates())
    assert len(set(graph.subjects(URIRef("http://example.org/name"), None))) == 20  # other properties: generated


@pytest.mark.parametrize("shacl_path, sparql_path", [
    ("( ex:a ex:b )", "ex:a/ex:b"),
    ("[ sh:inversePath ex:p ]", "^ex:p"),
    ("( ex:a [ sh:inversePath ex:b ] )", "ex:a/^ex:b"),
    ("[ sh:inversePath ( ex:a ex:b ) ]", "^(ex:a/ex:b)"),
])
def test_values_are_reachable_through_the_path(shacl_path, sparql_path):
    # An independent check of the generated structure with SPARQL property paths (pySHACL evaluates the inverse of a
    # sequence path incorrectly, see test_conformance.py)
    shapes = parse_turtle(f"ex:S a sh:NodeShape ; sh:property [ sh:path {shacl_path} ; sh:minCount 2 ; sh:maxCount 2 ] .")
    graph = generate_graph(shapes, 10, seed=1)
    entities = set(graph.subjects(SH.description, None))
    assert len(entities) == 10
    query = f"PREFIX ex: <http://example.org/> SELECT (COUNT(DISTINCT ?v) AS ?n) WHERE {{ ?entity {sparql_path} ?v }}"
    for entity in entities:
        (row,) = graph.query(query, initBindings={"entity": entity})
        assert row.n.toPython() == 2, f"{entity} has {row.n} values through {sparql_path}"


@pytest.mark.parametrize("min_count", [0, 1])
def test_recursion_is_limited_and_reuses_earlier_entities(min_count):
    shapes = parse_turtle(f"""
        ex:Root a sh:NodeShape ; sh:property [ sh:path ex:person ; sh:node ex:P ; sh:minCount 1 ; sh:maxCount 1 ] .
        ex:P a sh:NodeShape ;
            sh:property [ sh:path ex:knows ; sh:node ex:P ; sh:minCount {min_count} ; sh:maxCount 2 ] .
    """)
    knows = URIRef("http://example.org/knows")
    for seed in range(1, 6):
        graph = generate_graph(shapes, 20, seed=seed)
        people = set(graph.subjects(SH.description, URIRef("http://example.org/P")))
        # per root entity: its Person, at most 2 new acquaintances, and at most 2 new acquaintances of each of
        # them; at that point, the shape occurs RECURSION_LIMIT (3) times on the path, so no new Persons follow
        assert 20 <= len(people) <= 20 * (1 + 2 + 4)
        if min_count == 1:
            # the Persons at the limit know an earlier Person on their path (here: the one that knows them)
            assert any((b, knows, a) in graph for a, b in graph.subject_objects(knows))


def test_inverse_paths_never_make_a_literal_the_subject_of_a_triple():
    shapes = parse_turtle("""
        ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:name ; sh:minCount 1 ] ;
            sh:property [ sh:path [ sh:inversePath ex:p ] ; sh:datatype xsd:string ; sh:minCount 1 ] ;
            sh:property [ sh:path [ sh:inversePath ex:q ] ; sh:hasValue "a literal" ] .
    """)
    with pytest.warns(UserWarning, match="cannot be literals"):
        graph = generate_graph(shapes, 10, seed=1)
    assert not any(isinstance(subject, Literal) for subject in graph.subjects())
    assert len(set(graph.subjects(URIRef("http://example.org/name"), None))) == 10  # other properties: generated


def test_person_heuristics_also_apply_to_shapes_with_sh_class():
    # Shapes used via sh:node typically declare their class with sh:class instead of sh:targetClass
    shapes = parse_turtle("""
        ex:AuthorShape a sh:NodeShape ; sh:class schema:Person ;
            sh:property [ sh:path schema:givenName ; sh:minCount 1 ; sh:maxCount 1 ] ;
            sh:property [ sh:path schema:familyName ; sh:minCount 1 ; sh:maxCount 1 ] ;
            sh:property [ sh:path schema:email ; sh:minCount 1 ; sh:maxCount 1 ] .
    """)
    graph = generate_graph(shapes, 10, seed=1)
    schema = "http://schema.org/"
    people = set(graph.subjects(URIRef(schema + "email"), None))
    assert len(people) == 10
    for person in people:
        given = str(graph.value(person, URIRef(schema + "givenName")))
        family = str(graph.value(person, URIRef(schema + "familyName")))
        # the e-mail address is built from the generated name
        assert str(graph.value(person, URIRef(schema + "email"))) == f"{given.lower()}_{family.lower()}@gmail.com"


def test_person_dependencies_are_added_once():
    shapes = parse_turtle("""
        ex:PersonShape a sh:NodeShape ; sh:targetClass schema:Person ;
            sh:property [ sh:path schema:gender ] ; sh:property [ sh:path schema:givenName ] ;
            sh:property [ sh:path schema:familyName ] ; sh:property [ sh:path schema:email ] .
    """)
    person = generate_dictionary_from_shapes_graph(shapes)[URIRef("http://example.org/PersonShape")]
    for _ in range(3):  # called once per generated entity
        define_dependencies(person)
    properties = person["properties"]
    assert properties[URIRef("http://schema.org/givenName")]["depends_on"] == [URIRef("http://schema.org/gender")]
    assert properties[URIRef("http://schema.org/email")]["depends_on"] == [
        URIRef("http://schema.org/givenName"), URIRef("http://schema.org/familyName")]
