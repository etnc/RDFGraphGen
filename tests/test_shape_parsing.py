"""Tests of how SHACL shapes are parsed into the generator's shape dictionaries (rdf_graph_gen.shacl_mapping_generator)."""
from rdflib import Literal, SH, URIRef

from support import parse_turtle

from rdf_graph_gen.shacl_mapping_generator import generate_dictionary_from_shapes_graph

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
