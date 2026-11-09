"""Tests of the conformance checker itself (rdf_graph_gen.validation)."""
from support import parse_turtle

from rdf_graph_gen.validation import validate_generated

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


def test_node_level_violation_is_reported_without_a_path():
    shapes = parse_turtle("""
        ex:ClosedShape a sh:NodeShape ; sh:closed true ; sh:property [ sh:path ex:value ] .
    """)
    data = parse_turtle("ex:n1 sh:description ex:ClosedShape ; ex:value 1 ; ex:other 2 .")
    summary = validate_generated(shapes, data)
    assert not summary.conforms
    # the generator's own provenance triple is not allowed by a closed shape either
    assert summary.results_by_constraint == {("sh:closed", "ex:other"): 1, ("sh:closed", "sh:description"): 1}
