"""Tests of how SHACL shapes are parsed into the generator's shape dictionaries (rdf_graph_gen.shacl_mapping_generator)."""
import re
import warnings

import pytest
from rdflib import Literal, SH, URIRef

from support import parse_turtle

from rdf_graph_gen.shacl_mapping_generator import (find_independent_node_shapes, generate_dictionary_from_shapes_graph,
                                                   parameter_values)

EX = "http://example.org/"


def parse_shape(ttl, shape="S"):
    return generate_dictionary_from_shapes_graph(parse_turtle(ttl))[URIRef(EX + shape)]


def test_not_is_parsed_as_a_list_of_negated_shapes():
    shape = parse_shape("""
        ex:S a sh:NodeShape ;
            sh:not [ sh:property [ sh:path ex:forbidden ; sh:minCount 1 ] ] ;
            sh:property [ sh:path ex:p ; sh:not [ sh:in (1 2) ] ; sh:not [ sh:hasValue 5 ] ] .
    """)
    # sh:not on the node shape: one negated shape
    negated = shape[SH["not"]]
    assert len(negated) == 1 and URIRef(EX + "forbidden") in negated[0]["properties"]
    # sh:not on a property shape, twice: both negated shapes are kept
    property_negations = shape["properties"][URIRef(EX + "p")][SH["not"]]
    assert [Literal(1), Literal(2)] in [n.get(SH["in"]) for n in property_negations]
    assert Literal(5) in [n.get(SH.hasValue) for n in property_negations]


def test_repeated_values_are_all_kept():
    shape = parse_shape("""
        ex:S a sh:NodeShape ; sh:class ex:A, ex:B ;
            sh:or ( [ sh:property [ sh:path ex:a ] ] ) ; sh:or ( [ sh:property [ sh:path ex:b ] ] ) ;
            sh:property [ sh:path ex:p ; sh:node ex:T, ex:U ; sh:hasValue 1, 2 ] .
    """)
    assert set(parameter_values(shape, SH["class"])) == {URIRef(EX + "A"), URIRef(EX + "B")}
    assert len(parameter_values(shape, SH["or"])) == 2
    p = shape["properties"][URIRef(EX + "p")]
    assert set(parameter_values(p, SH.node)) == {URIRef(EX + "T"), URIRef(EX + "U")}
    assert set(parameter_values(p, SH.hasValue)) == {Literal(1), Literal(2)}


def test_property_shapes_with_the_same_path_are_combined():
    # each property shape is a separate constraint, so all of them must hold
    shape = parse_shape("""
        ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:p ; sh:minCount 1 ; sh:maxCount 5 ; sh:datatype xsd:integer ;
                          sh:minInclusive 10 ; sh:in (1 12 15 18) ; sh:hasValue 12 ] ;
            sh:property [ sh:path ex:p ; sh:minCount 2 ; sh:maxCount 3 ; sh:minInclusive 5 ; sh:maxInclusive 20 ;
                          sh:in (12 15 30) ; sh:hasValue 15 ] .
    """)
    p = shape["properties"][URIRef(EX + "p")]
    assert (p[SH.minCount], p[SH.maxCount]) == (Literal(2), Literal(3))  # the strictest bounds
    assert (p[SH.minInclusive], p[SH.maxInclusive]) == (Literal(10), Literal(20))
    assert p[SH["in"]] == [Literal(12), Literal(15)]  # the values that both lists allow
    assert set(parameter_values(p, SH.hasValue)) == {Literal(12), Literal(15)}
    assert p[SH.datatype] == URIRef("http://www.w3.org/2001/XMLSchema#integer")  # given in only one of them


@pytest.mark.parametrize("path, steps", [
    ("( ex:a ex:b ex:c )", [("a", False), ("b", False), ("c", False)]),
    ("[ sh:inversePath ex:p ]", [("p", True)]),
    ("( ex:a [ sh:inversePath ex:b ] )", [("a", False), ("b", True)]),
    ("[ sh:inversePath ( ex:a ex:b ) ]", [("b", True), ("a", True)]),  # the inverse of a/b is ^b/^a
])
def test_sequence_and_inverse_paths_are_supported(path, steps):
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no "not supported" warning
        shape = parse_shape(f"ex:S a sh:NodeShape ; sh:property [ sh:path {path} ; sh:minCount 1 ] .")
    (property_dictionary,) = shape["properties"].values()
    assert property_dictionary["path_steps"] == [(URIRef(EX + p), inverse) for p, inverse in steps]


@pytest.mark.parametrize("constraint", ["sh:datatype xsd:string", 'sh:in ("a" "b")', 'sh:hasValue "a"',
                                        "sh:nodeKind sh:Literal"])
def test_literal_values_through_an_inverse_path_produce_a_warning(constraint):
    # the values of an inverse path are subjects of triples, so they cannot be literals
    with pytest.warns(UserWarning, match="cannot be literals"):
        parse_shape(f"ex:S a sh:NodeShape ; sh:property [ sh:path [ sh:inversePath ex:p ] ; {constraint} ] .")


@pytest.mark.parametrize("path, text", [
    ("[ sh:alternativePath ( ex:a ex:b ) ]", "ex:a|ex:b"),
    ("[ sh:zeroOrMorePath ex:p ]", "ex:p*"),
    ("[ sh:oneOrMorePath ex:p ]", "ex:p+"),
    ("[ sh:zeroOrOnePath ex:p ]", "ex:p?"),
    ("( ex:a [ sh:zeroOrMorePath ex:b ] )", "ex:a/(ex:b*)"),
    ("[ sh:inversePath [ sh:alternativePath ( ex:a ex:b ) ] ]", "^(ex:a|ex:b)"),
])
def test_complex_property_paths_are_skipped_with_a_warning(path, text):
    with pytest.warns(UserWarning, match=re.escape(f"The property path {text} is not supported yet")):
        shape = parse_shape(f"""
            ex:S a sh:NodeShape ; sh:property [ sh:path ex:q ] ; sh:property [ sh:path {path} ; sh:minCount 1 ] .
        """)
    assert list(shape["properties"]) == [URIRef(EX + "q")]


def test_languageIn_is_parsed_as_a_list_and_combined_with_the_tags_both_lists_allow():
    shape = parse_shape("""
        ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:p ; sh:languageIn ("en" "de" "fr-CA") ] ;
            sh:property [ sh:path ex:p ; sh:languageIn ("en-US" "de" "fr") ] .
    """)
    # en-US is allowed by en, and fr-CA by fr
    assert sorted(shape["properties"][URIRef(EX + "p")][SH.languageIn]) == ["de", "en-US", "fr-CA"]


def test_a_repeated_single_valued_parameter_warns_and_uses_the_first_value():
    # SHACL allows at most one value for parameters such as sh:maxCount, sh:datatype or sh:pattern
    with pytest.warns(UserWarning, match="several values in one shape, which SHACL does not allow"):
        shape = parse_shape("ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:maxCount 3, 5 ] .")
    assert shape["properties"][URIRef(EX + "p")][SH.maxCount] == Literal(3)


def top_level_shapes(ttl):
    return {str(shape)[len(EX):] for shape in find_independent_node_shapes(parse_turtle(ttl))}


def test_shapes_used_by_other_shapes_are_not_top_level():
    assert top_level_shapes("""
        ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:a ; sh:node ex:Node ] ;
            sh:property [ sh:path ex:b ; sh:qualifiedValueShape ex:Qualified ; sh:qualifiedMinCount 1 ] ;
            sh:property ex:NamedPropertyShape ;
            sh:or ( ex:InOr [ sh:property [ sh:path ex:c ; sh:xone ( ex:InNestedXone ) ] ] ) ;
            sh:not ex:Negated .
        ex:NamedPropertyShape a sh:PropertyShape ; sh:path ex:d ; sh:node ex:ViaPropertyShape .
        ex:Node a sh:NodeShape . ex:Qualified a sh:NodeShape . ex:InOr a sh:NodeShape .
        ex:InNestedXone a sh:NodeShape . ex:Negated a sh:NodeShape . ex:ViaPropertyShape a sh:NodeShape .
    """) == {"S"}


def test_a_shape_that_uses_only_itself_is_top_level():
    assert top_level_shapes("""
        ex:Person a sh:NodeShape ; sh:property [ sh:path ex:knows ; sh:node ex:Person ] .
        ex:Address a sh:NodeShape ; sh:or ( [ sh:property [ sh:path ex:partOf ; sh:node ex:Address ] ] ) .
    """) == {"Person", "Address"}


def test_one_shape_of_a_cycle_without_a_top_level_shape_is_top_level():
    # each entity of the top-level shape includes entities of the other shapes of the cycle
    assert top_level_shapes("""
        ex:A a sh:NodeShape ; sh:property [ sh:path ex:toB ; sh:node ex:B ] .
        ex:B a sh:NodeShape ; sh:property [ sh:path ex:toA ; sh:node ex:A ] .
    """) == {"A"}
    # a shape that a cycle uses is not top-level, and neither is a cycle used by a top-level shape
    assert top_level_shapes("""
        ex:A a sh:NodeShape .
        ex:Y a sh:NodeShape ; sh:property [ sh:path ex:toZ ; sh:node ex:Z ] ; sh:property [ sh:path ex:a ; sh:node ex:A ] .
        ex:Z a sh:NodeShape ; sh:property [ sh:path ex:toY ; sh:node ex:Y ] .
        ex:Root a sh:NodeShape ; sh:property [ sh:path ex:c ; sh:node ex:C ] .
        ex:C a sh:NodeShape ; sh:property [ sh:path ex:toD ; sh:node ex:D ] .
        ex:D a sh:NodeShape ; sh:property [ sh:path ex:toC ; sh:node ex:C ] .
    """) == {"Y", "Root"}


def test_equals_and_disjoint_keep_the_constraints_of_the_other_property():
    from rdflib import XSD  # imported here: pytest probes module-level objects, and rdflib's XSD warns about that
    shape = parse_shape("""
        ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:a ; sh:equals ex:b ; sh:disjoint ex:c ] ;
            sh:property [ sh:path ex:b ; sh:datatype xsd:integer ] ;
            sh:property [ sh:path ex:c ; sh:datatype xsd:date ] .
    """)
    assert shape["properties"][URIRef(EX + "b")][SH.datatype] == XSD.integer
    assert shape["properties"][URIRef(EX + "c")][SH.datatype] == XSD.date


def test_equals_and_disjoint_add_the_other_property_if_it_is_not_declared():
    shape = parse_shape("ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ; sh:equals ex:b ; sh:disjoint ex:c ] .")
    assert shape["properties"][URIRef(EX + "b")] == {SH.path: URIRef(EX + "b")}
    assert shape["properties"][URIRef(EX + "c")] == {SH.path: URIRef(EX + "c")}
