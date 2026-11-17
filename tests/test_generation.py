"""Tests of the generation process: reproducibility, batching and parallelism, and per-batch validation."""
import pytest
from rdflib import RDF, Graph, Literal, SH, URIRef

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


def test_entities_of_closed_shapes_are_not_linked_to_their_shape_but_validated(tmp_path):
    shapes = tmp_path / "shapes.ttl"
    shapes.write_text("""
        @prefix sh: <http://www.w3.org/ns/shacl#> . @prefix ex: <http://example.org/> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        ex:S a sh:NodeShape ; sh:property [ sh:path ex:address ; sh:node ex:A ; sh:minCount 1 ; sh:maxCount 1 ] .
        ex:A a sh:NodeShape ; sh:closed true ; sh:property [ sh:path ex:street ; sh:minCount 1 ] .
    """, encoding="utf-8")
    output = tmp_path / "out.ttl"
    summary = MultiprocessGenerator(str(shapes), str(output), 10, 4, processes=1, seed=1, validate=True).generate()
    # every entity is validated against its shape, also the ones of the closed shape (the addresses)
    assert summary.conforms and summary.provenance_focus_nodes == 20
    data = Graph().parse(output)
    assert set(data.objects(None, SH.description)) == {URIRef("http://example.org/S")}
    # the written data conforms (the addresses are validated through the sh:node constraint of ex:S)
    assert validate_generated(load_shapes(path=shapes), data).conforms


def test_failed_attempts_for_xone_leave_no_data():
    # entities that are generated again for sh:xone: the nodes of the failed attempts are removed
    shapes = parse_turtle("""
        ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:member ; sh:minCount 1 ; sh:maxCount 1 ;
                          sh:property [ sh:path ex:name ; sh:minCount 1 ] ] ;
            sh:xone ( [ sh:property [ sh:path ex:a ; sh:minCount 1 ] ] [ sh:property [ sh:path ex:b ; sh:maxCount 1 ] ] ) .
    """)
    graph = generate_graph(shapes, 30, seed=1)
    entities = set(graph.subjects(SH.description, URIRef("http://example.org/S")))
    assert len(entities) == 30
    # every node is an entity or a value of a property of another node (no leftovers of failed attempts)
    assert all(subject in entities or subject in set(graph.objects()) for subject in graph.subjects())
    assert len(set(graph.subjects(URIRef("http://example.org/name"), None))) == 30
    # the record of the shapes of the entities has no entities of failed attempts either
    assert {entity for entity, _ in graph.entity_shapes} == entities


def test_failed_attempts_for_xone_leave_no_iris_from_patterns():
    # values whose IRIs are generated from a pattern, in entities that are generated again for sh:xone
    shapes = parse_turtle("""
        ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:member ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "^https://m[.]example[.]com/[a-z]{8}$" ;
                          sh:property [ sh:path ex:name ; sh:minCount 1 ] ] ;
            sh:xone ( [ sh:property [ sh:path ex:a ; sh:minCount 1 ] ] [ sh:property [ sh:path ex:b ; sh:maxCount 1 ] ] ) .
    """)
    graph = generate_graph(shapes, 30, seed=1)
    members = set(graph.objects(None, URIRef("http://example.org/member")))
    assert len(members) == 30 and all(str(m).startswith("https://m.example.com/") for m in members)
    # the members of failed attempts are removed: every node with a name is the member of an entity
    assert set(graph.subjects(URIRef("http://example.org/name"), None)) == members


def test_every_instance_of_a_class_is_used():
    # the classes of a property are added to its values, not to nodes that are then not used
    shapes = parse_turtle("""
        ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:a ; sh:class ex:A ; sh:minCount 1 ] ;
            sh:property [ sh:path ex:b ; sh:node ex:T ; sh:class ex:B ; sh:minCount 1 ] ;
            sh:property [ sh:path ex:c ; sh:in ( ex:c1 ex:c2 ) ; sh:class ex:C ; sh:minCount 1 ] ;
            sh:property [ sh:path ex:d ; sh:class ex:D ; sh:lessThan ex:e ] ;
            sh:property [ sh:path ex:e ; sh:datatype xsd:integer ] .
        ex:T a sh:NodeShape ; sh:property [ sh:path ex:name ; sh:minCount 1 ] .
    """)
    graph = generate_graph(shapes, 10, seed=1)
    top_level = set(graph.subjects(SH.description, URIRef("http://example.org/S")))
    used = set(graph.objects())
    for instance in graph.subjects(RDF.type, None):
        assert instance in top_level or instance in used, f"{instance} is typed but not the value of any property"
    for cls in "ABC":
        assert len(set(graph.subjects(RDF.type, URIRef("http://example.org/" + cls)))) >= 1


@pytest.mark.parametrize("schema", ["http://schema.org/", "https://schema.org/"])
def test_person_heuristics_also_apply_to_shapes_with_sh_class(schema):
    # Shapes used via sh:node typically declare their class with sh:class instead of sh:targetClass; schema.org terms
    # can be written with http:// or https://
    shapes = parse_turtle(f"""
        @prefix s: <{schema}> .
        ex:AuthorShape a sh:NodeShape ; sh:class s:Person ;
            sh:property [ sh:path s:givenName ; sh:minCount 1 ; sh:maxCount 1 ] ;
            sh:property [ sh:path s:familyName ; sh:minCount 1 ; sh:maxCount 1 ] ;
            sh:property [ sh:path s:email ; sh:minCount 1 ; sh:maxCount 1 ] .
    """)
    graph = generate_graph(shapes, 10, seed=1)
    people = set(graph.subjects(URIRef(schema + "email"), None))
    assert len(people) == 10
    for person in people:
        given = str(graph.value(person, URIRef(schema + "givenName")))
        family = str(graph.value(person, URIRef(schema + "familyName")))
        # the e-mail address is built from the generated name
        assert str(graph.value(person, URIRef(schema + "email"))) == f"{given.lower()}_{family.lower()}@example.com"


@pytest.mark.parametrize("schema", ["http://schema.org/", "https://schema.org/"])
def test_realistic_iris_are_in_the_schema_org_namespace_of_the_shape(schema):
    shapes = parse_turtle(f"""
        @prefix s: <{schema}> .
        ex:BookShape a sh:NodeShape ; sh:targetClass s:Book ; sh:property [ sh:path s:bookEdition ; sh:minCount 1 ] .
    """)
    formats = set(generate_graph(shapes, 20, seed=1).objects(None, URIRef(schema + "bookEdition")))
    assert formats and all(str(f).startswith(schema) for f in formats)
    assert {str(f)[len(schema):] for f in formats} <= {"AudiobookFormat", "EBook", "GraphicNovel", "Hardcover",
                                                       "Paperback"}


def test_realistic_values_that_fit_the_constraints_are_still_used():
    # names from the name lists that satisfy the constraints of the property are used (not random strings)
    from rdf_graph_gen.value_generators import dataset_dictionary
    known = set(dataset_dictionary["givenNameMale"]) | set(dataset_dictionary["givenNameFemale"])
    shapes = parse_turtle("""
        ex:S a sh:NodeShape ; sh:targetClass schema:Person ;
            sh:property [ sh:path schema:givenName ; sh:maxLength 5 ; sh:minCount 1 ; sh:maxCount 1 ] .
    """)
    names = [str(o) for o in generate_graph(shapes, 100, seed=1).objects(None, URIRef("http://schema.org/givenName"))]
    assert len(names) == 100 and all(len(name) <= 5 for name in names)
    assert sum(name in known for name in names) >= 90


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


def test_the_base_iri_changes_only_the_iris_of_the_entities():
    shapes = load_shapes(path=THREE_COMPLEX)
    default = generate_graph(shapes, 10, seed=3).serialize(format="nt")
    based = generate_graph(shapes, 10, seed=3, base_iri="https://data.example.com/").serialize(format="nt")
    assert "https://data.example.com/NodeB1_100" in based and "http://example.org/ns#" not in based
    assert sorted(based.replace("https://data.example.com/", "http://example.org/ns#").splitlines()) == \
        sorted(default.splitlines())


def test_the_output_file_records_how_it_was_generated(tmp_path):
    output = tmp_path / "out.ttl"
    MultiprocessGenerator(THREE_COMPLEX, str(output), 40, 7, processes=1, seed=11,
                          base_iri="https://data.example.com/", provenance=False).generate()
    text = output.read_text(encoding="utf-8")
    header = text[:text.index("\n\n")].splitlines()
    import hashlib
    from rdf_graph_gen import __version__
    digest = hashlib.sha256(open(THREE_COMPLEX, "rb").read()).hexdigest()
    assert header[0].startswith(f"# Generated by RDFGraphGen {__version__} (rdflib ")
    assert header[1:] == [
        f"# Shapes: shape-three-complex.ttl (SHA-256: {digest})",
        "# Scale factor: 40, batch size: 7, seed: 11",
        "# Base IRI: https://data.example.com/, links of entities to their shapes (sh:description): no",
    ]
    assert len(Graph().parse(output)) > 0  # the comment is not part of the graph


def test_ntriples_output_does_not_depend_on_the_number_of_processes(tmp_path):
    outputs = []
    for processes in (1, 3):
        output = tmp_path / f"out-{processes}.txt"
        MultiprocessGenerator(THREE_COMPLEX, str(output), 40, 7, processes=processes, seed=11,
                              output_format="ntriples").generate()
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]
    graph = Graph().parse(data=outputs[0].decode("utf-8"), format="nt")  # with the comment at the top
    assert len(set(graph.subjects(SH.description, None))) == 120


def test_the_output_format_follows_the_file_name(tmp_path):
    from rdf_graph_gen.multiprocess_generate import output_format_of
    assert output_format_of(tmp_path / "out.nt") == "ntriples"
    assert output_format_of(tmp_path / "out.ttl") == "turtle"
    assert output_format_of(tmp_path / "out.nt", "turtle") == "turtle"
    with pytest.raises(ValueError, match="unknown output format"):
        output_format_of(tmp_path / "out.xml", "xml")
    output = tmp_path / "out.nt"
    MultiprocessGenerator(THREE_COMPLEX, str(output), 5, 5, processes=1, seed=1).generate()
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    assert lines and all(line.endswith(" .") and not line.startswith("@prefix") for line in lines)
