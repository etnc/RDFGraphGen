"""
Tests of the built-in conformance check (rdf_graph_gen.checker): it must agree with pySHACL wherever it gives an
answer, and give no answer (None) for what it does not check.
"""
import warnings

import pyshacl
import pytest
from rdflib import Graph, URIRef

from support import PREFIXES, parse_turtle

from rdf_graph_gen.checker import conforms
from rdf_graph_gen.shacl_mapping_generator import generate_dictionary_from_shapes_graph

EX = "http://example.org/"

# (name, the constraints of the shape ex:S, data in which ex:x conforms, data in which it does not)
COMPONENTS = [
    ("minCount", "sh:property [ sh:path ex:p ; sh:minCount 2 ]", "ex:x ex:p 1, 2 .", "ex:x ex:p 1 ."),
    ("maxCount", "sh:property [ sh:path ex:p ; sh:maxCount 1 ]", "ex:x ex:p 1 .", "ex:x ex:p 1, 2 ."),
    ("datatype", "sh:property [ sh:path ex:p ; sh:datatype xsd:integer ]", "ex:x ex:p 5 .", 'ex:x ex:p "5" .'),
    ("datatype-string", "sh:property [ sh:path ex:p ; sh:datatype xsd:string ]", 'ex:x ex:p "a" .',
     'ex:x ex:p "a"@en .'),
    ("datatype-langString", "sh:property [ sh:path ex:p ; sh:datatype rdf:langString ]", 'ex:x ex:p "a"@en .',
     'ex:x ex:p "a" .'),
    ("datatype-ill-typed", "sh:property [ sh:path ex:p ; sh:datatype xsd:byte ]", 'ex:x ex:p "5"^^xsd:byte .',
     'ex:x ex:p "300"^^xsd:byte .'),
    ("class-with-subclass", "sh:property [ sh:path ex:p ; sh:class ex:C ]",
     "ex:x ex:p ex:y . ex:y a ex:D . ex:D rdfs:subClassOf ex:C .", "ex:x ex:p ex:y . ex:y a ex:E ."),
    ("class-of-a-literal", "sh:property [ sh:path ex:p ; sh:class ex:C ]", "ex:x ex:q 1 .", 'ex:x ex:p "C" .'),
    ("nodeKind", "sh:property [ sh:path ex:p ; sh:nodeKind sh:IRI ]", "ex:x ex:p ex:y .", "ex:x ex:p [] ."),
    ("in", 'sh:property [ sh:path ex:p ; sh:in ("a" "b") ]', 'ex:x ex:p "a" .', 'ex:x ex:p "z" .'),
    ("hasValue", "sh:property [ sh:path ex:p ; sh:hasValue 5 ]", "ex:x ex:p 5, 6 .", "ex:x ex:p 6 ."),
    ("range", "sh:property [ sh:path ex:p ; sh:minInclusive 1 ; sh:maxExclusive 10 ]", "ex:x ex:p 5 .",
     "ex:x ex:p 10 ."),
    ("range-of-a-string", "sh:property [ sh:path ex:p ; sh:minInclusive 1 ]", "ex:x ex:p 1 .", 'ex:x ex:p "a" .'),
    ("range-of-dates", 'sh:property [ sh:path ex:p ; sh:minInclusive "2020-01-01"^^xsd:date ]',
     'ex:x ex:p "2020-05-01"^^xsd:date .', 'ex:x ex:p "2019-01-01"^^xsd:date .'),
    ("length", "sh:property [ sh:path ex:p ; sh:minLength 2 ; sh:maxLength 3 ]", 'ex:x ex:p "ab" .',
     'ex:x ex:p "abcd" .'),
    ("length-of-a-blank-node", "sh:property [ sh:path ex:p ; sh:maxLength 30 ]", "ex:x ex:p ex:y .",
     "ex:x ex:p [] ."),
    ("pattern-with-flags", 'sh:property [ sh:path ex:p ; sh:pattern "^ab" ; sh:flags "i" ]', 'ex:x ex:p "ABc" .',
     'ex:x ex:p "cab" .'),
    ("languageIn", 'sh:property [ sh:path ex:p ; sh:languageIn ("en") ]', 'ex:x ex:p "a"@en-US .',
     'ex:x ex:p "a"@de .'),
    ("uniqueLang", "sh:property [ sh:path ex:p ; sh:uniqueLang true ]", 'ex:x ex:p "a"@en, "b"@de .',
     'ex:x ex:p "a"@en, "b"@en .'),
    ("equals", "sh:property [ sh:path ex:p ; sh:equals ex:q ]", "ex:x ex:p 1 ; ex:q 1 .", "ex:x ex:p 1 ; ex:q 2 ."),
    ("disjoint", "sh:property [ sh:path ex:p ; sh:disjoint ex:q ]", "ex:x ex:p 1 ; ex:q 2 .",
     "ex:x ex:p 1 ; ex:q 1 ."),
    ("lessThan", "sh:property [ sh:path ex:p ; sh:lessThan ex:q ]", "ex:x ex:p 1 ; ex:q 2 .",
     "ex:x ex:p 2 ; ex:q 2 ."),
    ("lessThanOrEquals", "sh:property [ sh:path ex:p ; sh:lessThanOrEquals ex:q ]", "ex:x ex:p 2 ; ex:q 2 .",
     "ex:x ex:p 3 ; ex:q 2 ."),
    ("node", "sh:property [ sh:path ex:p ; sh:node ex:T ]", 'ex:x ex:p ex:y . ex:y ex:name "n" .',
     "ex:x ex:p ex:y ."),
    ("nested-property-shape", "sh:property [ sh:path ex:p ; sh:property [ sh:path ex:name ; sh:minCount 1 ] ]",
     'ex:x ex:p ex:y . ex:y ex:name "n" .', "ex:x ex:p ex:y ."),
    ("and", "sh:and ( [ sh:property [ sh:path ex:a ; sh:minCount 1 ] ] [ sh:property [ sh:path ex:b ; sh:minCount 1 ] ] )",
     "ex:x ex:a 1 ; ex:b 1 .", "ex:x ex:a 1 ."),
    ("or", "sh:or ( [ sh:property [ sh:path ex:a ; sh:minCount 1 ] ] [ sh:property [ sh:path ex:b ; sh:minCount 1 ] ] )",
     "ex:x ex:a 1 .", "ex:x ex:c 1 ."),
    ("xone", "sh:xone ( [ sh:property [ sh:path ex:a ; sh:minCount 1 ] ] [ sh:property [ sh:path ex:b ; sh:minCount 1 ] ] )",
     "ex:x ex:a 1 .", "ex:x ex:a 1 ; ex:b 1 ."),
    ("not", "sh:not [ sh:property [ sh:path ex:a ; sh:minCount 1 ] ]", "ex:x ex:b 1 .", "ex:x ex:a 1 ."),
    ("not-on-values", "sh:property [ sh:path ex:p ; sh:not [ sh:in (1 2) ] ]", "ex:x ex:p 3 .", "ex:x ex:p 1 ."),
    ("or-on-values", "sh:property [ sh:path ex:p ; sh:or ( [ sh:datatype xsd:integer ] [ sh:datatype xsd:string ] ) ]",
     'ex:x ex:p 1, "a" .', "ex:x ex:p true ."),
    ("sequence-path", "sh:property [ sh:path ( ex:a ex:b ) ; sh:minCount 1 ]", "ex:x ex:a [ ex:b 1 ] .",
     "ex:x ex:a 1 ."),
    ("inverse-path", "sh:property [ sh:path [ sh:inversePath ex:p ] ; sh:minCount 1 ]", "ex:y ex:p ex:x .",
     "ex:x ex:p ex:y ."),
    ("class-of-the-node", "sh:class ex:C", "ex:x a ex:C .", "ex:x a ex:D ."),
    ("property-shapes-with-the-same-path",
     "sh:property [ sh:path ex:p ; sh:minInclusive 1 ] ; sh:property [ sh:path ex:p ; sh:maxInclusive 5 ]",
     "ex:x ex:p 3 .", "ex:x ex:p 7 ."),
    # the parser passes the lower bound of ex:p on to ex:q as a hint for the generator; it is not a constraint
    ("lessThan-without-the-generator-hints", "sh:property [ sh:path ex:p ; sh:minInclusive 0 ; sh:lessThan ex:q ]",
     "ex:x ex:q -5 .", "ex:x ex:p -1 ."),
]

NOT_CHECKED = [
    ("closed", "sh:closed true ; sh:property [ sh:path ex:p ]", "ex:x ex:p 1 ."),
    ("qualifiedValueShape", "sh:property [ sh:path ex:p ; sh:qualifiedValueShape [ sh:datatype xsd:integer ] ; "
                            "sh:qualifiedMinCount 1 ]", "ex:x ex:p 1 ."),
    ("unsupported-path", "sh:property [ sh:path [ sh:alternativePath ( ex:a ex:b ) ] ; sh:minCount 1 ]",
     "ex:x ex:a 1 ."),
    ("unknown-shape-of-sh-node", "sh:property [ sh:path ex:p ; sh:node ex:Unknown ]", "ex:x ex:p ex:y ."),
]

T_SHAPE = "ex:T a sh:NodeShape ; sh:property [ sh:path ex:name ; sh:minCount 1 ] ."


def check(constraints, data):
    """The result of the checker and of pySHACL for ex:x and the shape ex:S."""
    shapes = parse_turtle(f"ex:S a sh:NodeShape ; sh:targetNode ex:x ; {constraints} . {T_SHAPE}")
    graph = Graph().parse(data=PREFIXES + data, format="turtle")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # unsupported paths
        dictionary = generate_dictionary_from_shapes_graph(shapes)
    result = conforms(graph, URIRef(EX + "x"), dictionary[URIRef(EX + "S")], dictionary)
    return result, pyshacl.validate(graph, shacl_graph=shapes)[0]


@pytest.mark.parametrize("constraints, data, expected", [
    pytest.param(constraints, data, expected, id=f"{name}-{'conforms' if expected else 'does-not-conform'}")
    for name, constraints, conforming, violating in COMPONENTS
    for data, expected in ((conforming, True), (violating, False))
])
def test_the_checker_agrees_with_pyshacl(constraints, data, expected):
    result, pyshacl_result = check(constraints, data)
    assert pyshacl_result == expected, "the test case itself is wrong"
    assert result == expected


@pytest.mark.parametrize("constraints, data", [pytest.param(c, d, id=name) for name, c, d in NOT_CHECKED])
def test_what_the_checker_does_not_check_is_unknown(constraints, data):
    assert check(constraints, data)[0] is None


def test_the_checker_agrees_with_pyshacl_on_generated_data():
    # generated entities of shapes with logical constraints, some of which do not conform (sh:xone, sh:not)
    from rdf_graph_gen.rdf_graph_generator import generate_graph
    from rdflib import SH
    shapes = parse_turtle("""
        ex:S a sh:NodeShape ;
            sh:xone ( [ sh:property [ sh:path ex:a ; sh:minCount 1 ] ] [ sh:property [ sh:path ex:b ; sh:maxCount 1 ] ] ) ;
            sh:property [ sh:path ex:p ; sh:minCount 1 ; sh:maxCount 1 ;
                          sh:xone ( [ sh:datatype xsd:integer ; sh:maxInclusive 5 ] [ sh:in (1 2 3 "x") ] ) ] ;
            sh:not [ sh:property [ sh:path ex:c ; sh:minCount 1 ] ] .
    """)
    dictionary = generate_dictionary_from_shapes_graph(shapes)
    graph = generate_graph(shapes, 30, seed=1)
    shape = dictionary[URIRef(EX + "S")]
    results = {}
    for entity in graph.subjects(SH.description, URIRef(EX + "S")):
        targeted = Graph()
        for triple in shapes:
            targeted.add(triple)
        targeted.add((URIRef(EX + "S"), SH.targetNode, entity))
        results[entity] = (conforms(graph, entity, shape, dictionary), pyshacl.validate(graph, shacl_graph=targeted)[0])
    assert len(results) == 30
    assert {checked for checked, _ in results.values()} == {True, False}  # both kinds of entities are checked
    assert all(checked == validated for checked, validated in results.values())
