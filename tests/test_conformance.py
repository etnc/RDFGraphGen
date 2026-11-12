"""
Conformance tests: data generated from SHACL shapes must conform to those shapes.

Every shapes graph used here is satisfiable, so a non-conforming result is a generator bug. Known bugs are
marked with `known_bug(...)`, which describes the bug.
"""
from pathlib import Path

import pytest
from rdflib import URIRef

from support import (REPO_ROOT, assert_conforms, generate, generate_and_validate, known_bug, load_shapes,
                     validator_bug)

from rdf_graph_gen.value_generators import dataset_dictionary


# --- The shapes shipped with the repository: experiment suite (paper, Table 1) and examples -------------------------

SHIPPED_SHAPES = [
    pytest.param("experiment_suite/shape-single-simple.ttl"),
    pytest.param("experiment_suite/shape-single-complex.ttl"),
    pytest.param("experiment_suite/shape-three-simple.ttl"),
    pytest.param("experiment_suite/shape-three-complex.ttl"),
    pytest.param("generated_examples/shape_examples/book_shape.ttl"),
    pytest.param("generated_examples/shape_examples/example_product_shape.ttl"),
    pytest.param("generated_examples/shape_examples/movie_shape.ttl"),
    pytest.param("generated_examples/shape_examples/random_shape.ttl"),
    pytest.param("generated_examples/shape_examples/person_shape.ttl",
                 marks=known_bug("the provenance triple (sh:description) is not allowed by the closed AddressShape")),
    pytest.param("generated_examples/shape_examples/test_value_generation.ttl"),
    pytest.param("generated_examples/shape_examples/tv_series_shape.ttl"),
]


@pytest.mark.parametrize("relative_path", SHIPPED_SHAPES, ids=lambda p: Path(p).stem)
def test_shipped_shapes(relative_path):
    assert_conforms(generate_and_validate(path=REPO_ROOT / relative_path))


# --- sh:datatype ----------------------------------------------------------------------------------------------------

DATATYPES = [
    "xsd:string", "xsd:boolean",
    # numbers; a value outside the value range of the datatype (e.g. 300 for xsd:byte) does not conform
    "xsd:integer", "xsd:decimal", "xsd:double", "xsd:float",
    "xsd:long", "xsd:int", "xsd:short", "xsd:byte",
    "xsd:nonNegativeInteger", "xsd:positiveInteger", "xsd:nonPositiveInteger", "xsd:negativeInteger",
    "xsd:unsignedLong", "xsd:unsignedInt", "xsd:unsignedShort", "xsd:unsignedByte",
    # dates, times and durations
    "xsd:date", "xsd:dateTime", "xsd:dateTimeStamp", "xsd:time",
    "xsd:gYear", "xsd:gYearMonth", "xsd:gMonth", "xsd:gDay", "xsd:gMonthDay",
    "xsd:duration", "xsd:dayTimeDuration", "xsd:yearMonthDuration",
    # strings of a certain form (pySHACL does not check the form of most of them, see test_values.py), binary data
    "xsd:normalizedString", "xsd:token", "xsd:language", "xsd:Name", "xsd:NCName", "xsd:NMTOKEN", "xsd:NMTOKENS",
    "xsd:ID", "xsd:IDREF", "xsd:IDREFS", "xsd:ENTITY", "xsd:ENTITIES", "xsd:anyURI",
    "rdf:XMLLiteral", "rdf:HTML", "rdf:JSON",
    "xsd:hexBinary", "xsd:base64Binary",
    # strings with a language tag
    "rdf:langString",
]


@pytest.mark.parametrize("datatype", DATATYPES)
def test_datatype(datatype):
    assert_conforms(generate_and_validate(f"""
        ex:S a sh:NodeShape ; sh:property [ sh:path ex:value ; sh:datatype {datatype} ; sh:minCount 1 ; sh:maxCount 3 ] .
    """))


# --- Individual constraint components and combinations -------------------------------------------------------------

def case(name, shapes, *marks):
    return pytest.param(shapes, id=name, marks=marks)


# pySHACL warns when it validates recursive shapes (their semantics is not defined by the SHACL specification)
IGNORE_RECURSION_WARNING = pytest.mark.filterwarnings("ignore:Warning, A Recursive Shape")

CASES = [
    # cardinality, value ranges, strings
    case("cardinality", "ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:minCount 2 ; sh:maxCount 4 ] ."),
    case("string-length", "ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:minLength 5 ; sh:maxLength 8 ] ."),
    case("pattern", 'ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:pattern "^[A-Z]{3}-[0-9]{4}$" ] .'),
    case("integer-range", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:integer ;
            sh:minInclusive 10 ; sh:maxExclusive 20 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("date-range", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:date ;
            sh:minInclusive "2020-01-01"^^xsd:date ; sh:maxInclusive "2020-12-31"^^xsd:date ] ."""),
    case("date-range-exclusive", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:date ;
            sh:minExclusive "2020-02-27"^^xsd:date ; sh:maxExclusive "2020-03-02"^^xsd:date ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("dateTime-range", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:dateTime ;
            sh:minExclusive "2024-03-01T12:00:00"^^xsd:dateTime ; sh:maxInclusive "2024-03-01T12:00:03"^^xsd:dateTime ;
            sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("dateTime-range-with-time-zones", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:dateTime ;
            sh:minInclusive "2024-03-01T12:00:00+01:00"^^xsd:dateTime ; sh:maxInclusive "2024-03-01T11:00:02Z"^^xsd:dateTime ;
            sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("time-range", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:time ;
            sh:minInclusive "23:59:57"^^xsd:time ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("dayTimeDuration-range", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:dayTimeDuration ;
            sh:minInclusive "PT1H"^^xsd:dayTimeDuration ; sh:maxExclusive "PT1H0M3S"^^xsd:dayTimeDuration ;
            sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("yearMonthDuration-range", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:yearMonthDuration ;
            sh:minExclusive "P1Y"^^xsd:yearMonthDuration ; sh:maxInclusive "P1Y3M"^^xsd:yearMonthDuration ;
            sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("negative-duration-range", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:duration ;
            sh:maxInclusive "-P1D"^^xsd:duration ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("anyURI-with-pattern", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:anyURI ;
            sh:pattern "^https://example[.]org/[a-z]{5}$" ; sh:minCount 2 ; sh:maxCount 2 ] ."""),
    case("in", 'ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:in ("a" "b" "c") ; sh:minCount 1 ; sh:maxCount 2 ] .'),
    case("hasValue", "ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:hasValue ex:v ; sh:minCount 1 ] ."),
    case("hasValue-with-several-values", "ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:hasValue ex:v1, ex:v2 ] ."),

    # sh:minLength and sh:maxLength: the length of the lexical form of any value
    case("pattern-with-length", 'ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:pattern "^[a-z]+$" ; sh:maxLength 3 ] .'),
    case("pattern-with-minimum-and-maximum-length", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:string ;
            sh:pattern "^[a-z]*$" ; sh:minLength 4 ; sh:maxLength 5 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("string-with-maximum-length-zero", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:string ;
            sh:maxLength 0 ; sh:minCount 1 ; sh:maxCount 1 ] ."""),
    case("integer-with-length", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:integer ;
            sh:minLength 6 ; sh:maxLength 12 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("negative-integer-with-length", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:integer ;
            sh:minInclusive -50 ; sh:maxInclusive -5 ; sh:maxLength 2 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("decimal-with-length", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:decimal ;
            sh:maxLength 4 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("boolean-with-length", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:boolean ;
            sh:maxLength 4 ; sh:minCount 1 ; sh:maxCount 1 ] ."""),
    case("anyURI-with-length", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:anyURI ;
            sh:maxLength 24 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("language-with-length", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:language ;
            sh:minLength 5 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("hexBinary-with-length", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:hexBinary ;
            sh:minLength 4 ; sh:maxLength 6 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("base64Binary-with-length", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:base64Binary ;
            sh:maxLength 8 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),

    # sh:pattern: the lexical form of any value matches it
    case("integer-with-pattern", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:integer ;
            sh:pattern "^[0-9]{5}$" ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("integer-with-a-loose-pattern", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:integer ;
            sh:pattern "^[0-9]+$" ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("integer-with-pattern-and-range", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:integer ;
            sh:pattern "^[1-9][0-9]{4}$" ; sh:minInclusive 10000 ; sh:maxInclusive 19999 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("byte-with-pattern", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:byte ;
            sh:pattern "^[0-9]{3}$" ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("decimal-with-pattern", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:decimal ;
            sh:pattern "^[0-9]{3}[.]5$" ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("date-with-pattern", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:date ;
            sh:pattern "^2021-0[1-6]-1[0-9]$" ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("gYear-with-pattern", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:gYear ;
            sh:pattern "^19[0-9]{2}$" ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("boolean-with-pattern", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:boolean ;
            sh:pattern "^t" ; sh:minCount 1 ; sh:maxCount 1 ] ."""),

    case("decimal-range-with-zero-bound", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:decimal ;
            sh:minInclusive -5 ; sh:maxInclusive 0 ] ."""),
    case("decimal-range-exclusive", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:decimal ;
            sh:minExclusive 0.1 ; sh:maxExclusive 0.2 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("decimal-range-narrower-than-two-decimal-places", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ;
            sh:datatype xsd:decimal ; sh:minExclusive 0.001 ; sh:maxExclusive 0.002 ; sh:minCount 2 ; sh:maxCount 2 ] ."""),
    case("double-range", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:double ;
            sh:minInclusive -1.5 ; sh:maxInclusive 1.5 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("integer-range-with-decimal-bounds", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:integer ;
            sh:minInclusive 1.5 ; sh:maxInclusive 3.5 ; sh:minCount 2 ; sh:maxCount 2 ] ."""),
    case("byte-with-a-lower-bound", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:byte ;
            sh:minInclusive 100 ; sh:minCount 3 ; sh:maxCount 3 ] ."""),

    # language-tagged strings
    case("languageIn-uniqueLang", 'ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:languageIn ("en" "de") ; sh:uniqueLang true ; sh:minCount 1 ] .'),
    case("languageIn-uniqueLang-with-as-many-values-as-tags", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ;
            sh:languageIn ("en" "de" "fr") ; sh:uniqueLang true ; sh:minCount 3 ; sh:maxCount 3 ] ."""),
    case("languageIn-uniqueLang-with-more-values-allowed-than-tags", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ;
            sh:languageIn ("en" "de") ; sh:uniqueLang true ; sh:minCount 1 ; sh:maxCount 5 ] ."""),
    case("langString-uniqueLang", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype rdf:langString ;
            sh:uniqueLang true ; sh:minCount 4 ; sh:maxCount 4 ] ."""),
    case("langString-with-length", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype rdf:langString ;
            sh:minLength 3 ; sh:maxLength 6 ; sh:minCount 2 ; sh:maxCount 2 ] ."""),
    case("languageIn-on-a-realistic-value", """ex:S a sh:NodeShape ; sh:targetClass schema:Person ;
            sh:property [ sh:path schema:givenName ; sh:languageIn ("de") ; sh:minCount 1 ; sh:maxCount 1 ] ."""),
    case("languageIn-of-two-property-shapes", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:p ; sh:languageIn ("en" "de") ; sh:minCount 1 ] ;
            sh:property [ sh:path ex:p ; sh:languageIn ("en-US" "fr") ] ."""),

    # property pairs
    case("lessThan-integers", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:lo ; sh:datatype xsd:integer ; sh:lessThan ex:hi ] ;
            sh:property [ sh:path ex:hi ; sh:datatype xsd:integer ] ."""),
    case("lessThan-with-a-maximum", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:lo ; sh:datatype xsd:integer ; sh:maxInclusive 10 ; sh:lessThan ex:hi ] ;
            sh:property [ sh:path ex:hi ; sh:datatype xsd:integer ; sh:minInclusive 100 ; sh:maxInclusive 200 ] ."""),
    case("lessThanOrEquals-integers","""ex:S a sh:NodeShape ; sh:property [ sh:path ex:lo ; sh:datatype xsd:integer ; sh:lessThanOrEquals ex:hi ] ;
            sh:property [ sh:path ex:hi ; sh:datatype xsd:integer ] ."""),
    case("lessThan-dates-is-strict", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:lo ; sh:datatype xsd:date ; sh:minInclusive "2020-01-01"^^xsd:date ; sh:lessThan ex:hi ;
                          sh:minCount 2 ; sh:maxCount 2 ] ;
            sh:property [ sh:path ex:hi ; sh:datatype xsd:date ; sh:minInclusive "2020-01-03"^^xsd:date ;
                          sh:maxInclusive "2020-01-03"^^xsd:date ; sh:minCount 1 ; sh:maxCount 1 ] ."""),
    case("lessThan-dates-with-a-maximum", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:lo ; sh:datatype xsd:date ; sh:maxInclusive "2000-01-01"^^xsd:date ; sh:lessThan ex:hi ] ;
            sh:property [ sh:path ex:hi ; sh:datatype xsd:date ; sh:minInclusive "2020-01-01"^^xsd:date ] ."""),
    case("disjoint", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ; sh:datatype xsd:string ; sh:disjoint ex:b ] ;
            sh:property [ sh:path ex:b ; sh:datatype xsd:string ] ."""),
    case("equals-keeps-constraints-of-other-property", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ; sh:equals ex:b ] ;
            sh:property [ sh:path ex:b ; sh:datatype xsd:integer ; sh:minInclusive 5 ; sh:maxInclusive 9 ] ."""),
    case("equals-other-property-declared-first", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:b ; sh:datatype xsd:integer ; sh:minInclusive 5 ; sh:maxInclusive 9 ] ;
            sh:property [ sh:path ex:a ; sh:equals ex:b ] ."""),
    case("equals-with-several-values", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ; sh:equals ex:b ] ;
            sh:property [ sh:path ex:b ; sh:datatype xsd:integer ; sh:minCount 2 ; sh:maxCount 2 ] .""",
         known_bug("sh:equals copies only the first value of the other property")),
    case("equals-copies-zero", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ; sh:equals ex:b ] ;
            sh:property [ sh:path ex:b ; sh:datatype xsd:integer ; sh:minInclusive 0 ; sh:maxInclusive 0 ] .""",
         known_bug("a value of 0 is treated as missing, so sh:equals does not copy it")),
    case("lessThan-leaves-a-valid-range", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:lo ; sh:datatype xsd:integer ; sh:minInclusive 0 ; sh:lessThan ex:hi ] ;
            sh:property [ sh:path ex:hi ; sh:datatype xsd:integer ; sh:minInclusive 0 ; sh:maxInclusive 1 ] .""",
         known_bug("the other value of sh:lessThan is chosen without regard to it, which can leave no valid range "
                   "(here: ex:hi = 0)"),
         pytest.mark.filterwarnings("ignore:Invalid int range")),
    case("disjoint-keeps-constraints-of-other-property", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ; sh:disjoint ex:b ] ;
            sh:property [ sh:path ex:b ; sh:datatype xsd:integer ; sh:minInclusive 5 ; sh:maxInclusive 9 ] ."""),
    # a property that needs the values of another one is generated after it; generation must always end
    case("disjoint-other-property-declared-first", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:b ; sh:datatype xsd:integer ; sh:minInclusive 1 ; sh:maxInclusive 3 ] ;
            sh:property [ sh:path ex:a ; sh:datatype xsd:integer ; sh:minInclusive 1 ; sh:maxInclusive 3 ; sh:disjoint ex:b ] ."""),
    case("equals-other-property-may-be-empty", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ; sh:equals ex:b ] ;
            sh:property [ sh:path ex:b ; sh:minCount 0 ; sh:maxCount 1 ] ."""),
    case("lessThan-other-property-may-be-empty", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:a ; sh:datatype xsd:integer ; sh:lessThan ex:b ] ;
            sh:property [ sh:path ex:b ; sh:datatype xsd:integer ; sh:minCount 0 ; sh:maxCount 1 ] ."""),
    case("postponed-property-keeps-its-cardinality", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:a ; sh:datatype xsd:integer ; sh:lessThan ex:b ; sh:minCount 2 ; sh:maxCount 2 ] ;
            sh:property [ sh:path ex:b ; sh:datatype xsd:integer ; sh:minInclusive 100 ; sh:maxInclusive 200 ] ."""),
    case("person-dependency-may-be-empty", """ex:S a sh:NodeShape ; sh:targetClass schema:Person ;
            sh:property [ sh:path schema:givenName ; sh:minCount 1 ] ;
            sh:property [ sh:path schema:gender ; sh:minCount 0 ; sh:maxCount 1 ] ."""),

    # shape references and node values
    case("node", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:node ex:T ; sh:minCount 1 ] .
            ex:T a sh:NodeShape ; sh:property [ sh:path ex:q ; sh:datatype xsd:integer ; sh:minCount 1 ] ."""),
    case("nested-property-shape", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:address ; sh:property [ sh:path ex:street ; sh:minCount 1 ] ] ."""),
    case("node-on-node-shape", """ex:S a sh:NodeShape ; sh:node ex:T ; sh:property [ sh:path ex:p ; sh:datatype xsd:string ] .
            ex:T a sh:NodeShape ; sh:property [ sh:path ex:q ; sh:datatype xsd:integer ; sh:minCount 1 ] .""",
         known_bug("sh:node on a node shape that also has properties is skipped")),
    case("two-nodes-on-one-property", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:node ex:T, ex:U ; sh:minCount 2 ; sh:maxCount 2 ] .
            ex:T a sh:NodeShape ; sh:property [ sh:path ex:t ; sh:minCount 1 ] .
            ex:U a sh:NodeShape ; sh:property [ sh:path ex:u ; sh:minCount 1 ] .""",
         known_bug("only one of several sh:node shapes is applied; values must conform to all of them")),
    case("several-classes-on-node-shape", """ex:S a sh:NodeShape ; sh:targetClass ex:Thing ; sh:class ex:A, ex:B ;
            sh:property [ sh:path ex:p ] ."""),
    case("class-on-property", "ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:class ex:Person ; sh:minCount 1 ] .",
         known_bug("a literal is generated instead of an instance of the class")),
    case("nodeKind-IRI", "ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:nodeKind sh:IRI ; sh:minCount 1 ] .",
         known_bug("sh:nodeKind is ignored")),
    case("two-shapes-targeting-one-class", """ex:A a sh:NodeShape ; sh:targetClass ex:C ; sh:property [ sh:path ex:p ; sh:datatype xsd:integer ] .
            ex:B a sh:NodeShape ; sh:targetClass ex:C ; sh:property [ sh:path ex:q ; sh:minCount 1 ] .""",
         known_bug("entities of class C must conform to every shape that targets C")),
    case("optional-recursion", """ex:A a sh:NodeShape ; sh:property [ sh:path ex:toB ; sh:node ex:B ; sh:minCount 0 ; sh:maxCount 1 ] .
            ex:B a sh:NodeShape ; sh:property [ sh:path ex:toA ; sh:node ex:A ; sh:minCount 0 ; sh:maxCount 1 ] .
            ex:Root a sh:NodeShape ; sh:property [ sh:path ex:r ; sh:node ex:A ] .""",
         IGNORE_RECURSION_WARNING),
    case("required-recursion", """ex:A a sh:NodeShape ; sh:property [ sh:path ex:toB ; sh:node ex:B ; sh:minCount 1 ] .
            ex:B a sh:NodeShape ; sh:property [ sh:path ex:toA ; sh:node ex:A ; sh:minCount 1 ] .
            ex:Root a sh:NodeShape ; sh:property [ sh:path ex:r ; sh:node ex:A ] .""",
         IGNORE_RECURSION_WARNING),
    case("optional-self-recursion", """ex:Root a sh:NodeShape ; sh:property [ sh:path ex:person ; sh:node ex:P ; sh:minCount 1 ] .
            ex:P a sh:NodeShape ; sh:property [ sh:path ex:name ; sh:minCount 1 ; sh:maxCount 1 ] ;
                sh:property [ sh:path ex:knows ; sh:node ex:P ; sh:minCount 0 ; sh:maxCount 2 ] .""",
         IGNORE_RECURSION_WARNING),
    case("required-self-recursion", """ex:Root a sh:NodeShape ; sh:property [ sh:path ex:person ; sh:node ex:P ; sh:minCount 1 ] .
            ex:P a sh:NodeShape ; sh:property [ sh:path ex:name ; sh:minCount 1 ; sh:maxCount 1 ] ;
                sh:property [ sh:path ex:knows ; sh:node ex:P ; sh:minCount 1 ; sh:maxCount 2 ] .""",
         IGNORE_RECURSION_WARNING),
    case("required-self-recursion-with-more-values-than-earlier-entities", """ex:Root a sh:NodeShape ;
                sh:property [ sh:path ex:person ; sh:node ex:P ; sh:minCount 1 ] .
            ex:P a sh:NodeShape ; sh:property [ sh:path ex:knows ; sh:node ex:P ; sh:minCount 3 ; sh:maxCount 3 ] .""",
         IGNORE_RECURSION_WARNING),
    case("self-recursive-shape", """ex:P a sh:NodeShape ; sh:property [ sh:path ex:name ; sh:datatype xsd:string ] ;
            sh:property [ sh:path ex:knows ; sh:node ex:P ; sh:minCount 0 ; sh:maxCount 2 ] .""",
         IGNORE_RECURSION_WARNING),
    case("required-self-recursive-shape", """ex:P a sh:NodeShape ; sh:property [ sh:path ex:name ; sh:minCount 1 ] ;
            sh:property [ sh:path ex:knows ; sh:node ex:P ; sh:minCount 1 ; sh:maxCount 2 ] .""",
         IGNORE_RECURSION_WARNING),
    case("recursion-without-a-top-level-shape", """ex:A a sh:NodeShape ; sh:property [ sh:path ex:toB ; sh:node ex:B ; sh:minCount 1 ] .
            ex:B a sh:NodeShape ; sh:property [ sh:path ex:toA ; sh:node ex:A ; sh:minCount 0 ; sh:maxCount 1 ] .""",
         IGNORE_RECURSION_WARNING),

    # property paths
    case("sequence-path", "ex:S a sh:NodeShape ; sh:property [ sh:path ( ex:a ex:b ) ; sh:minCount 1 ] ."),
    case("sequence-path-of-three-predicates", "ex:S a sh:NodeShape ; sh:property [ sh:path ( ex:a ex:b ex:c ) ; sh:minCount 1 ] ."),
    case("sequence-path-with-value-constraints", """ex:S a sh:NodeShape ; sh:property [ sh:path ( ex:address ex:postalCode ) ;
            sh:datatype xsd:integer ; sh:minInclusive 1000 ; sh:maxInclusive 9999 ; sh:minCount 2 ; sh:maxCount 2 ] ."""),
    case("sequence-path-with-distinct-values", """ex:S a sh:NodeShape ; sh:property [ sh:path ( ex:a ex:b ) ;
            sh:in ("x" "y") ; sh:minCount 2 ; sh:maxCount 2 ] ."""),
    case("sequence-path-to-a-node-shape", """ex:S a sh:NodeShape ; sh:property [ sh:path ( ex:a ex:b ) ; sh:node ex:T ; sh:minCount 1 ] .
            ex:T a sh:NodeShape ; sh:property [ sh:path ex:q ; sh:datatype xsd:integer ; sh:minCount 1 ] ."""),
    case("sequence-path-in-a-branch", """ex:S a sh:NodeShape ;
            sh:xone ( [ sh:path ( ex:a ex:b ) ; sh:minCount 1 ] [ sh:path ex:c ; sh:minCount 1 ] ) ."""),
    case("inverse-path", "ex:S a sh:NodeShape ; sh:property [ sh:path [ sh:inversePath ex:p ] ; sh:minCount 1 ] ."),
    case("inverse-path-to-a-node-shape", """ex:PersonShape a sh:NodeShape ;
            sh:property [ sh:path [ sh:inversePath ex:author ] ; sh:node ex:BookShape ; sh:minCount 1 ; sh:maxCount 3 ] .
            ex:BookShape a sh:NodeShape ; sh:property [ sh:path ex:title ; sh:datatype xsd:string ; sh:minCount 1 ] ."""),
    case("inverse-path-with-sh-in", """ex:S a sh:NodeShape ; sh:property [ sh:path [ sh:inversePath ex:member ] ;
            sh:in ( ex:groupA ex:groupB "a literal cannot be a subject" ) ; sh:minCount 1 ; sh:maxCount 2 ] ."""),
    case("inverse-path-with-sh-class", """ex:S a sh:NodeShape ; sh:property [ sh:path [ sh:inversePath ex:memberOf ] ;
            sh:class ex:Group ; sh:minCount 1 ] ."""),
    case("inverse-path-with-nested-properties", """ex:S a sh:NodeShape ; sh:property [ sh:path [ sh:inversePath ex:p ] ;
            sh:minCount 1 ; sh:property [ sh:path ex:name ; sh:datatype xsd:string ; sh:minCount 1 ] ] ."""),
    case("sequence-path-with-an-inverse-step", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ( ex:a [ sh:inversePath ex:b ] ) ; sh:minCount 1 ] ."""),
    case("inverse-of-a-sequence-path", """ex:S a sh:NodeShape ;
            sh:property [ sh:path [ sh:inversePath ( ex:a ex:b ) ] ; sh:minCount 1 ] .""",
         validator_bug("the inverse of the sequence path ex:a/ex:b is evaluated as ^ex:a/^ex:b instead of ^ex:b/^ex:a "
                       "(checked with SPARQL in test_generation.py)")),

    # logical constraints
    case("or-of-datatypes", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:postalCode ; sh:minCount 1 ;
            sh:or ( [ sh:datatype xsd:integer ; sh:minInclusive 10100 ; sh:maxInclusive 10999 ] [ sh:datatype xsd:string ] ) ] ."""),
    case("xone-of-property-groups", """ex:S a sh:NodeShape ; sh:xone (
            [ sh:property [ sh:path ex:givenName ; sh:minCount 1 ] ; sh:property [ sh:path ex:familyName ; sh:minCount 1 ] ]
            [ sh:path ex:fullName ; sh:minCount 1 ] ) ."""),
    # several property shapes with the same path, and branches combined with a shape: all of them must hold
    case("two-property-shapes-with-the-same-path", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:p ; sh:datatype xsd:integer ; sh:minInclusive 40 ; sh:minCount 3 ] ;
            sh:property [ sh:path ex:p ; sh:minInclusive 1 ; sh:maxInclusive 45 ; sh:maxCount 3 ] ."""),
    case("two-property-shapes-with-the-same-path-and-sh-in", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:p ; sh:in ("a" "b" "c") ] ; sh:property [ sh:path ex:p ; sh:in ("b" "c" "d") ] ."""),
    case("and-keeps-the-stricter-bound", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:p ; sh:datatype xsd:integer ; sh:minInclusive 40 ; sh:maxInclusive 45 ] ;
            sh:and ( [ sh:property [ sh:path ex:p ; sh:minInclusive 1 ] ] ) ."""),
    case("and", """ex:S a sh:NodeShape ; sh:and (
            [ sh:property [ sh:path ex:a ; sh:minCount 1 ] ] [ sh:property [ sh:path ex:b ; sh:minCount 1 ] ] ) ."""),
    # a shape can have several sh:and / sh:or / sh:xone lists, and each of them must hold
    case("two-and-lists", """ex:S a sh:NodeShape ;
            sh:and ( [ sh:property [ sh:path ex:a ; sh:minCount 1 ] ] ) ;
            sh:and ( [ sh:property [ sh:path ex:b ; sh:minCount 1 ] ] ) ."""),
    case("two-or-lists", """ex:S a sh:NodeShape ;
            sh:or ( [ sh:property [ sh:path ex:a ; sh:minCount 1 ] ] [ sh:property [ sh:path ex:b ; sh:minCount 1 ] ] ) ;
            sh:or ( [ sh:property [ sh:path ex:c ; sh:minCount 1 ] ] [ sh:property [ sh:path ex:d ; sh:minCount 1 ] ] ) ."""),
    case("two-xone-lists", """ex:S a sh:NodeShape ;
            sh:xone ( [ sh:property [ sh:path ex:a ; sh:minCount 1 ] ] [ sh:property [ sh:path ex:b ; sh:minCount 1 ] ] ) ;
            sh:xone ( [ sh:property [ sh:path ex:c ; sh:minCount 1 ] ] [ sh:property [ sh:path ex:d ; sh:minCount 1 ] ] ) ."""),
    case("not", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:integer ;
            sh:minInclusive 1 ; sh:maxInclusive 3 ; sh:not [ sh:in (1 2) ] ] .""",
         known_bug("sh:not is not enforced")),

    # other
    case("closed", """ex:S a sh:NodeShape ; sh:targetClass ex:C ; sh:closed true ; sh:ignoredProperties ( rdf:type ) ;
            sh:property [ sh:path ex:p ] .""",
         known_bug("the provenance triple (sh:description) is not allowed by closed shapes")),
    case("qualifiedValueShape", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ;
            sh:qualifiedValueShape [ sh:datatype xsd:integer ] ; sh:qualifiedMinCount 2 ] .""",
         known_bug("sh:qualifiedValueShape is not supported")),
]


@pytest.mark.parametrize("shapes", CASES)
def test_constraint(shapes):
    assert_conforms(generate_and_validate(shapes))


# --- The example from the paper (IJCKG 2025, Listing 1) -------------------------------------------------------------

PAPER_LISTING_1 = """
ex:PersonShape a sh:NodeShape ;
    sh:targetClass schema:Person ;
    sh:xone ( [ sh:property [ sh:path schema:givenName ; sh:datatype xsd:string ; sh:minCount 1 ] ;
                sh:property [ sh:path schema:familyName ; sh:datatype xsd:string ; sh:minCount 1 ] ]
              [ sh:path schema:name ; sh:datatype xsd:string ; sh:minCount 1 ] ) ;
    sh:property [ sh:path schema:birthDate ; sh:lessThan schema:deathDate ; sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path schema:gender ; sh:in ( "female" "male" ) ; sh:maxCount 1 ] ;
    sh:property [ sh:path ex:workMail ; sh:pattern "^[a-z0-9]+\\\\.[a-z0-9]+@work\\\\.[a-z]{2,3}$" ] ;
    sh:property [ sh:path schema:email ; sh:maxCount 1 ] ;
    sh:property [ sh:path schema:telephone ] ;
    sh:property [ sh:path schema:jobTitle ] ;
    sh:property [ sh:path schema:address ; sh:node ex:AddressShape ; sh:minCount 1 ] .

ex:AddressShape a sh:NodeShape ;
    sh:class schema:PostalAddress ;
    sh:property [ sh:path schema:streetAddress ; sh:datatype xsd:string ] ;
    sh:property [ sh:path schema:postalCode ;
                  sh:or ( [ sh:datatype xsd:integer ; sh:minInclusive 10100 ; sh:maxInclusive 10999 ]
                          [ sh:datatype xsd:string ] ) ] .
"""


def test_paper_listing_1():
    assert_conforms(generate_and_validate(PAPER_LISTING_1))


# --- Realistic values ------------------------------------------------------------------------------------------------

def _generated_given_names(schema_namespace):
    shapes = load_shapes(f"""
        @prefix s: <{schema_namespace}> .
        ex:PersonShape a sh:NodeShape ; sh:targetClass s:Person ; sh:property [ sh:path s:givenName ; sh:minCount 1 ] .
    """)
    data = generate(shapes)
    return {str(o) for o in data.objects(None, URIRef(schema_namespace + "givenName"))}


KNOWN_GIVEN_NAMES = set(dataset_dictionary["givenNameMale"]) | set(dataset_dictionary["givenNameFemale"])


def test_schema_org_given_names_come_from_the_name_lists():
    names = _generated_given_names("http://schema.org/")
    assert names and names <= KNOWN_GIVEN_NAMES


@known_bug("the realistic-value heuristics only recognise http://schema.org/, not https://schema.org/")
def test_https_schema_org_given_names_come_from_the_name_lists():
    names = _generated_given_names("https://schema.org/")
    assert names and names <= KNOWN_GIVEN_NAMES
