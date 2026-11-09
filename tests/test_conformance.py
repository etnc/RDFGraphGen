"""
Conformance tests: data generated from SHACL shapes must conform to those shapes.

Every shapes graph used here is satisfiable, so a non-conforming result is a generator bug. Known bugs are
marked with `known_bug(item, ...)`, referring to the item of the v1.3 fix plan that addresses them.
"""
from pathlib import Path

import pytest
from rdflib import URIRef

from support import REPO_ROOT, assert_conforms, generate, generate_and_validate, known_bug, load_shapes

from rdf_graph_gen.value_generators import dataset_dictionary


# --- The shapes shipped with the repository: experiment suite (paper, Table 1) and examples -------------------------

SHIPPED_SHAPES = [
    pytest.param("experiment_suite/shape-single-simple.ttl"),
    pytest.param("experiment_suite/shape-single-complex.ttl"),
    pytest.param("experiment_suite/shape-three-simple.ttl",
                 marks=known_bug(4, "sh:minLength/sh:maxLength are ignored for xsd:integer values")),
    pytest.param("experiment_suite/shape-three-complex.ttl"),
    pytest.param("generated_examples/shape_examples/book_shape.ttl"),
    pytest.param("generated_examples/shape_examples/example_product_shape.ttl"),
    pytest.param("generated_examples/shape_examples/movie_shape.ttl"),
    pytest.param("generated_examples/shape_examples/random_shape.ttl"),
    pytest.param("generated_examples/shape_examples/person_shape.ttl",
                 marks=known_bug("7, 9", "the example's sh:xone is unsatisfiable as written (no branch has a "
                                         "sh:minCount); sh:or picks a string branch for postalCode although the "
                                         "property also has sh:minInclusive/sh:maxInclusive; the provenance triple "
                                         "breaks sh:closed")),
    pytest.param("generated_examples/shape_examples/test_value_generation.ttl",
                 marks=known_bug("4, 5", "xsd:decimal values are typed xsd:double; sh:pattern ignores "
                                         "sh:minLength/sh:maxLength")),
    pytest.param("generated_examples/shape_examples/tv_series_shape.ttl",
                 marks=known_bug(5, "sh:lessThan pairs are violated")),
]


@pytest.mark.parametrize("relative_path", SHIPPED_SHAPES, ids=lambda p: Path(p).stem)
def test_shipped_shapes(relative_path):
    assert_conforms(generate_and_validate(path=REPO_ROOT / relative_path))


# --- sh:datatype ----------------------------------------------------------------------------------------------------

NOT_GENERATED_AS_TYPED_LITERAL = "generated as a plain xsd:string literal"
DATATYPES = [
    pytest.param("xsd:string"),
    pytest.param("xsd:integer"),
    pytest.param("xsd:boolean"),
    pytest.param("xsd:date"),
    pytest.param("xsd:decimal", marks=known_bug(4, "generated as xsd:double")),
] + [
    pytest.param(datatype, marks=known_bug(4, NOT_GENERATED_AS_TYPED_LITERAL))
    for datatype in ["xsd:double", "xsd:float", "xsd:int", "xsd:long", "xsd:nonNegativeInteger",
                     "xsd:positiveInteger", "xsd:dateTime", "xsd:time", "xsd:gYear", "xsd:anyURI", "rdf:langString"]
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
    case("in", 'ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:in ("a" "b" "c") ; sh:minCount 1 ; sh:maxCount 2 ] .'),
    case("hasValue", "ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:hasValue ex:v ; sh:minCount 1 ] ."),
    case("pattern-with-length", 'ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:pattern "^[a-z]+$" ; sh:maxLength 3 ] .',
         known_bug(5, "sh:pattern ignores sh:minLength/sh:maxLength")),
    case("decimal-range-with-zero-bound", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:decimal ;
            sh:minInclusive -5 ; sh:maxInclusive 0 ] .""",
         known_bug("4, 5", "a bound of 0 is treated as 'no bound'; xsd:decimal generated as xsd:double")),
    case("languageIn-uniqueLang", 'ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:languageIn ("en" "de") ; sh:uniqueLang true ; sh:minCount 1 ] .',
         known_bug(5, "language tags are not generated")),

    # property pairs
    case("lessThan-integers", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:lo ; sh:datatype xsd:integer ; sh:lessThan ex:hi ] ;
            sh:property [ sh:path ex:hi ; sh:datatype xsd:integer ] ."""),
    case("lessThanOrEquals-integers", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:lo ; sh:datatype xsd:integer ; sh:lessThanOrEquals ex:hi ] ;
            sh:property [ sh:path ex:hi ; sh:datatype xsd:integer ] ."""),
    case("lessThan-dates-is-strict", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:lo ; sh:datatype xsd:date ; sh:minInclusive "2020-01-02"^^xsd:date ; sh:lessThan ex:hi ] ;
            sh:property [ sh:path ex:hi ; sh:datatype xsd:date ; sh:minInclusive "2020-01-02"^^xsd:date ; sh:maxInclusive "2020-01-03"^^xsd:date ] .""",
         known_bug(5, "the upper bound from sh:lessThan is inclusive for dates")),
    case("disjoint", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ; sh:datatype xsd:string ; sh:disjoint ex:b ] ;
            sh:property [ sh:path ex:b ; sh:datatype xsd:string ] ."""),
    case("equals-keeps-constraints-of-other-property", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ; sh:equals ex:b ] ;
            sh:property [ sh:path ex:b ; sh:datatype xsd:integer ; sh:minInclusive 5 ; sh:maxInclusive 9 ] .""",
         known_bug(3, "sh:equals overwrites the constraints of the other property")),

    # shape references and node values
    case("node", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:node ex:T ; sh:minCount 1 ] .
            ex:T a sh:NodeShape ; sh:property [ sh:path ex:q ; sh:datatype xsd:integer ; sh:minCount 1 ] ."""),
    case("nested-property-shape", """ex:S a sh:NodeShape ;
            sh:property [ sh:path ex:address ; sh:property [ sh:path ex:street ; sh:minCount 1 ] ] ."""),
    case("node-on-node-shape", """ex:S a sh:NodeShape ; sh:node ex:T ; sh:property [ sh:path ex:p ; sh:datatype xsd:string ] .
            ex:T a sh:NodeShape ; sh:property [ sh:path ex:q ; sh:datatype xsd:integer ; sh:minCount 1 ] .""",
         known_bug(6, "sh:node on a node shape that also has properties is skipped")),
    case("two-nodes-on-one-property", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:node ex:T, ex:U ; sh:minCount 2 ; sh:maxCount 2 ] .
            ex:T a sh:NodeShape ; sh:property [ sh:path ex:t ; sh:minCount 1 ] .
            ex:U a sh:NodeShape ; sh:property [ sh:path ex:u ; sh:minCount 1 ] .""",
         known_bug(6, "only one of several sh:node shapes is applied; values must conform to all of them")),
    case("class-on-property", "ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:class ex:Person ; sh:minCount 1 ] .",
         known_bug(6, "a literal is generated instead of an instance of the class")),
    case("nodeKind-IRI", "ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:nodeKind sh:IRI ; sh:minCount 1 ] .",
         known_bug(6, "sh:nodeKind is ignored")),
    case("two-shapes-targeting-one-class", """ex:A a sh:NodeShape ; sh:targetClass ex:C ; sh:property [ sh:path ex:p ; sh:datatype xsd:integer ] .
            ex:B a sh:NodeShape ; sh:targetClass ex:C ; sh:property [ sh:path ex:q ; sh:minCount 1 ] .""",
         known_bug(6, "entities of class C must conform to every shape that targets C")),
    case("optional-recursion", """ex:A a sh:NodeShape ; sh:property [ sh:path ex:toB ; sh:node ex:B ; sh:minCount 0 ; sh:maxCount 1 ] .
            ex:B a sh:NodeShape ; sh:property [ sh:path ex:toA ; sh:node ex:A ; sh:minCount 0 ; sh:maxCount 1 ] .
            ex:Root a sh:NodeShape ; sh:property [ sh:path ex:r ; sh:node ex:A ] .""",
         IGNORE_RECURSION_WARNING),
    case("required-recursion", """ex:A a sh:NodeShape ; sh:property [ sh:path ex:toB ; sh:node ex:B ; sh:minCount 1 ] .
            ex:B a sh:NodeShape ; sh:property [ sh:path ex:toA ; sh:node ex:A ; sh:minCount 1 ] .
            ex:Root a sh:NodeShape ; sh:property [ sh:path ex:r ; sh:node ex:A ] .""",
         known_bug(6, "endless recursion; needs a depth limit with links back to earlier entities",
                   raises=RecursionError)),
    case("self-recursive-shape", """ex:P a sh:NodeShape ; sh:property [ sh:path ex:name ; sh:datatype xsd:string ] ;
            sh:property [ sh:path ex:knows ; sh:node ex:P ; sh:minCount 0 ; sh:maxCount 2 ] .""",
         known_bug(3, "a shape that references itself is not treated as top-level, so no entities are generated")),

    # property paths
    case("sequence-path", "ex:S a sh:NodeShape ; sh:property [ sh:path ( ex:a ex:b ) ; sh:minCount 1 ] .",
         known_bug(3, "non-predicate paths produce blank nodes in predicate position")),
    case("inverse-path", "ex:S a sh:NodeShape ; sh:property [ sh:path [ sh:inversePath ex:p ] ; sh:minCount 1 ] .",
         known_bug(3, "non-predicate paths produce blank nodes in predicate position")),

    # logical constraints
    case("or-of-datatypes", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:postalCode ; sh:minCount 1 ;
            sh:or ( [ sh:datatype xsd:integer ; sh:minInclusive 10100 ; sh:maxInclusive 10999 ] [ sh:datatype xsd:string ] ) ] ."""),
    case("xone-of-property-groups", """ex:S a sh:NodeShape ; sh:xone (
            [ sh:property [ sh:path ex:givenName ; sh:minCount 1 ] ; sh:property [ sh:path ex:familyName ; sh:minCount 1 ] ]
            [ sh:path ex:fullName ; sh:minCount 1 ] ) ."""),
    case("and", """ex:S a sh:NodeShape ; sh:and (
            [ sh:property [ sh:path ex:a ; sh:minCount 1 ] ] [ sh:property [ sh:path ex:b ; sh:minCount 1 ] ] ) ."""),
    case("not", 'ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype xsd:integer ; sh:not [ sh:in (1 2 3) ] ] .',
         known_bug("3, 7", "sh:not crashes the shape parser", raises=StopIteration)),

    # other
    case("closed", """ex:S a sh:NodeShape ; sh:targetClass ex:C ; sh:closed true ; sh:ignoredProperties ( rdf:type ) ;
            sh:property [ sh:path ex:p ] .""",
         known_bug(9, "the provenance triple (sh:description) is not allowed by closed shapes")),
    case("qualifiedValueShape", """ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ;
            sh:qualifiedValueShape [ sh:datatype xsd:integer ] ; sh:qualifiedMinCount 2 ] .""",
         known_bug(9, "sh:qualifiedValueShape is not supported")),
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


@known_bug(8, "the realistic-value heuristics only recognise http://schema.org/, not https://schema.org/")
def test_https_schema_org_given_names_come_from_the_name_lists():
    names = _generated_given_names("https://schema.org/")
    assert names and names <= KNOWN_GIVEN_NAMES
