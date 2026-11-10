"""Tests of how SHACL shapes are parsed into the generator's shape dictionaries (rdf_graph_gen.shacl_mapping_generator)."""
import re
import warnings

import pytest
from rdflib import Literal, SH, URIRef

from support import parse_turtle

from rdf_graph_gen.shacl_mapping_generator import generate_dictionary_from_shapes_graph, parameter_values

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


def test_a_sequence_path_of_predicates_is_supported():
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no "not supported" warning
        shape = parse_shape("ex:S a sh:NodeShape ; sh:property [ sh:path ( ex:a ex:b ex:c ) ; sh:minCount 1 ] .")
    (property_dictionary,) = shape["properties"].values()
    assert property_dictionary["path_sequence"] == [URIRef(EX + name) for name in ("a", "b", "c")]


@pytest.mark.parametrize("path, text", [
    ("[ sh:inversePath ex:p ]", "^ex:p"),
    ("[ sh:alternativePath ( ex:a ex:b ) ]", "ex:a|ex:b"),
    ("[ sh:zeroOrMorePath ex:p ]", "ex:p*"),
    ("[ sh:oneOrMorePath ex:p ]", "ex:p+"),
    ("[ sh:zeroOrOnePath ex:p ]", "ex:p?"),
    ("( ex:a [ sh:inversePath ex:b ] )", "ex:a/(^ex:b)"),
])
def test_complex_property_paths_are_skipped_with_a_warning(path, text):
    with pytest.warns(UserWarning, match=re.escape(f"The property path {text} is not supported yet")):
        shape = parse_shape(f"""
            ex:S a sh:NodeShape ; sh:property [ sh:path ex:q ] ; sh:property [ sh:path {path} ; sh:minCount 1 ] .
        """)
    assert list(shape["properties"]) == [URIRef(EX + "q")]


def test_a_repeated_single_valued_parameter_warns_and_uses_the_first_value():
    # SHACL allows at most one value for parameters such as sh:maxCount, sh:datatype or sh:pattern
    with pytest.warns(UserWarning, match="several values in one shape, which SHACL does not allow"):
        shape = parse_shape("ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:maxCount 3, 5 ] .")
    assert shape["properties"][URIRef(EX + "p")][SH.maxCount] == Literal(3)


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
