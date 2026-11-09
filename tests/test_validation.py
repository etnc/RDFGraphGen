"""Tests of the conformance checker itself (rdf_graph_gen.validation)."""
from rdflib import SH, URIRef

from support import parse_turtle

from rdf_graph_gen.validation import build_validation_shapes, validate_generated

SHAPES = """
ex:ValueShape a sh:NodeShape ;
    sh:property [ sh:path ex:value ; sh:datatype xsd:integer ; sh:minCount 1 ] .
"""


def test_shapes_without_targets_and_data_without_provenance_is_vacuous():
    summary = validate_generated(parse_turtle(SHAPES), parse_turtle('ex:n1 ex:value "not an integer" .'))
    assert summary.vacuous
    assert summary.conforms  # what plain SHACL validation reports, although nothing was checked
    assert "NOTHING CHECKED" in summary.format()


def test_provenance_link_makes_the_entity_a_focus_node():
    data = parse_turtle('ex:n1 sh:description ex:ValueShape ; ex:value "not an integer" .')
    summary = validate_generated(parse_turtle(SHAPES), data)
    assert not summary.vacuous
    assert summary.provenance_focus_nodes == 1
    assert not summary.conforms
    assert summary.violating_focus_nodes == 1
    assert summary.results_by_constraint == {("sh:datatype", "ex:value"): 1}
    assert "DOES NOT CONFORM" in summary.format()


def test_conforming_generated_entity():
    data = parse_turtle("ex:n1 sh:description ex:ValueShape ; ex:value 42 .")
    summary = validate_generated(parse_turtle(SHAPES), data)
    assert summary.conforms and not summary.vacuous
    assert summary.violating_focus_nodes == 0


def test_declared_targets_only_ignores_provenance_links():
    data = parse_turtle('ex:n1 sh:description ex:ValueShape ; ex:value "not an integer" .')
    summary = validate_generated(parse_turtle(SHAPES), data, use_provenance=False)
    assert summary.vacuous
    assert "provenance links were ignored" in summary.format()


def test_provenance_link_to_an_unknown_shape_is_ignored():
    data = parse_turtle('ex:n1 sh:description ex:SomethingElse ; ex:value "not an integer" .')
    assert validate_generated(parse_turtle(SHAPES), data).vacuous


def test_declared_target_class_selects_instances_including_subclasses():
    shapes = parse_turtle(SHAPES + "ex:ValueShape sh:targetClass ex:Thing .")
    data = parse_turtle("""
        ex:SpecialThing rdfs:subClassOf ex:Thing .
        ex:n1 a ex:Thing ; ex:value 1 .
        ex:n2 a ex:SpecialThing .
    """)
    summary = validate_generated(shapes, data)
    assert summary.declared_focus_nodes == 2
    assert not summary.conforms
    assert summary.results_by_constraint == {("sh:minCount", "ex:value"): 1}


def test_entity_selected_by_both_provenance_and_targets_is_checked_once():
    shapes = parse_turtle(SHAPES + "ex:ValueShape sh:targetClass ex:Thing .")
    data = parse_turtle('ex:n1 a ex:Thing ; sh:description ex:ValueShape ; ex:value "not an integer" .')
    summary = validate_generated(shapes, data)
    assert summary.focus_nodes == 1
    assert summary.results_by_constraint == {("sh:datatype", "ex:value"): 1}


NESTED_SHAPES = """
ex:ParentShape a sh:NodeShape ; sh:property [ sh:path ex:child ; sh:node ex:ChildShape ] .
ex:ChildShape a sh:NodeShape ; sh:property [ sh:path ex:value ; sh:datatype xsd:integer ] .
"""


def test_results_propagated_from_nested_entities_are_distinguished():
    data = parse_turtle("""
        ex:parent sh:description ex:ParentShape ; ex:child ex:kid .
        ex:kid sh:description ex:ChildShape ; ex:value "not an integer" .
    """)
    summary = validate_generated(parse_turtle(NESTED_SHAPES), data)
    assert summary.violating_focus_nodes == 2
    assert summary.root_cause_focus_nodes == 1  # the parent only fails because its child does
    assert summary.results_by_constraint == {("sh:datatype", "ex:value"): 1, ("sh:node", "ex:child"): 1}
    assert summary.propagated_results == {("sh:node", "ex:child"): 1}
    assert "of which 1 only because a nested entity does not conform" in summary.format()


def test_node_constraint_on_the_focus_node_itself_is_a_root_cause():
    shapes = parse_turtle(NESTED_SHAPES + "ex:WrapperShape a sh:NodeShape ; sh:node ex:ChildShape .")
    data = parse_turtle('ex:n1 sh:description ex:WrapperShape ; ex:value "not an integer" .')
    summary = validate_generated(shapes, data)
    assert summary.root_cause_focus_nodes == 1
    assert not summary.propagated_results


def test_validation_does_not_add_targets_to_the_original_shapes():
    # Adding one target per entity to the original shapes made validation quadratic (sh:node re-reads the shape)
    shapes = parse_turtle(NESTED_SHAPES)
    data = parse_turtle("""
        ex:parent sh:description ex:ParentShape ; ex:child ex:child .
        ex:child sh:description ex:ChildShape ; ex:value 1 .
    """)
    validation_shapes, provenance_nodes, _ = build_validation_shapes(shapes, data)
    for shape in ("ParentShape", "ChildShape"):
        assert (URIRef("http://example.org/" + shape), SH.targetNode, None) not in validation_shapes
    assert set(validation_shapes.objects(None, SH.targetNode)) == provenance_nodes
    assert len(shapes) < len(validation_shapes) and (None, SH.targetNode, None) not in shapes


def test_declared_target_nodes_can_be_excluded():
    shapes = parse_turtle(SHAPES + "ex:ValueShape sh:targetNode ex:absent .")
    data = parse_turtle("ex:n1 ex:value 1 .")
    assert not validate_generated(shapes, data).conforms  # ex:absent has no ex:value
    assert validate_generated(shapes, data, declared_target_nodes=False).vacuous


def test_node_level_violation_is_reported_without_a_path():
    shapes = parse_turtle("""
        ex:ClosedShape a sh:NodeShape ; sh:closed true ; sh:property [ sh:path ex:value ] .
    """)
    data = parse_turtle("ex:n1 sh:description ex:ClosedShape ; ex:value 1 ; ex:other 2 .")
    summary = validate_generated(shapes, data)
    assert not summary.conforms
    # the generator's own provenance triple is not allowed by a closed shape either
    assert summary.results_by_constraint == {("sh:closed", "ex:other"): 1, ("sh:closed", "sh:description"): 1}
