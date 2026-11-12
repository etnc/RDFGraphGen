"""
Checks of generated values that validation with pySHACL cannot make: the lexical forms of datatypes that pySHACL
does not check, and value ranges of datatypes whose values SPARQL (and pySHACL) cannot compare.
"""
import re

import pytest
from rdflib import Literal, URIRef

from support import parse_turtle

from rdf_graph_gen.rdf_graph_generator import generate_graph

P = URIRef("http://example.org/p")


def generated_values(datatype, constraints="", count=3, scale=20):
    shapes = parse_turtle(f"""ex:S a sh:NodeShape ; sh:property [ sh:path ex:p ; sh:datatype {datatype} ; {constraints}
        sh:minCount {count} ; sh:maxCount {count} ] .""")
    return list(generate_graph(shapes, scale, seed=1).objects(None, P))


NAME = r"[A-Za-z_:][\w.:-]*"
NC_NAME = r"[A-Za-z_][\w.-]*"
NMTOKEN = r"[\w.:-]+"


@pytest.mark.parametrize("datatype, lexical_form", [
    ("xsd:normalizedString", r"[^\r\n\t]*"),
    ("xsd:token", r"(\S+( \S+)*)?"),
    ("xsd:language", r"[a-zA-Z]{1,8}(-[a-zA-Z0-9]{1,8})*"),
    ("xsd:Name", NAME),
    ("xsd:NCName", NC_NAME), ("xsd:ID", NC_NAME), ("xsd:IDREF", NC_NAME), ("xsd:ENTITY", NC_NAME),
    ("xsd:IDREFS", f"{NC_NAME}( {NC_NAME})*"), ("xsd:ENTITIES", f"{NC_NAME}( {NC_NAME})*"),
    ("xsd:NMTOKEN", NMTOKEN), ("xsd:NMTOKENS", f"{NMTOKEN}( {NMTOKEN})*"),
    ("xsd:anyURI", r"[a-zA-Z][a-zA-Z0-9+.-]*:\S+"),
    ("xsd:dayTimeDuration", r"-?P(?=\d|T\d)(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+S)?)?"),
    ("xsd:yearMonthDuration", r"-?P(?=\d)(\d+Y)?(\d+M)?"),
])
def test_values_have_the_lexical_form_of_their_datatype(datatype, lexical_form):
    values = generated_values(datatype)
    assert len(values) == 3 * 20
    for value in values:
        assert value.datatype == URIRef("http://www.w3.org/2001/XMLSchema#" + datatype[len("xsd:"):])
        assert re.fullmatch(lexical_form, str(value)), f"{value!r} is not a valid {datatype}"


def test_values_of_unknown_datatypes_are_typed_strings_with_a_warning():
    with pytest.warns(UserWarning, match="The datatype http://example.org/myType is not supported yet"):
        values = generated_values("ex:myType")
    assert values and all(isinstance(value, Literal) and value.datatype == URIRef("http://example.org/myType")
                          for value in values)


@pytest.mark.parametrize("datatype, constraints, warning", [
    ("xsd:string", 'sh:pattern "^[0-9]{6}$" ; sh:maxLength 3 ;', "No value of the pattern"),
    ("xsd:integer", "sh:minInclusive 1 ; sh:maxInclusive 99 ; sh:minLength 3 ;", "No new integer with a length"),
    ("xsd:anyURI", "sh:maxLength 10 ;", "No http://www.w3.org/2001/XMLSchema#anyURI value with a length"),
    ("xsd:date", "sh:maxLength 8 ;", "No http://www.w3.org/2001/XMLSchema#date value with a length"),
])
def test_lengths_that_no_value_can_have_produce_a_warning_and_no_value(datatype, constraints, warning):
    with pytest.warns(UserWarning, match=warning):
        assert generated_values(datatype, constraints, count=1, scale=1) == []


@pytest.mark.parametrize("datatype, minimum, maximum", [
    ("gYear", "1999", "2001"),
    ("gYearMonth", "1999-11", "2000-02"),
    ("gMonth", "--11", "--12"),
    ("gDay", "---29", "---31"),
    ("gMonthDay", "--02-28", "--03-01"),
])
def test_gregorian_values_are_within_their_bounds(datatype, minimum, maximum):
    # SPARQL (and pySHACL) cannot compare values of these datatypes, so no value conforms to a range of them. Their
    # lexical forms have a fixed width, so they compare as strings.
    values = generated_values(f"xsd:{datatype}", f"""sh:minInclusive "{minimum}"^^xsd:{datatype} ;
        sh:maxInclusive "{maximum}"^^xsd:{datatype} ;""", count=2)
    assert values and all(minimum <= str(value) <= maximum for value in values), values
