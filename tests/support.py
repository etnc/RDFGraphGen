"""Shared helpers for the test suite: generate data from shapes and check its conformance."""
from pathlib import Path

import pytest
from rdflib import Graph

from rdf_graph_gen.rdf_graph_generator import generate_graph
from rdf_graph_gen.validation import validate_generated

REPO_ROOT = Path(__file__).resolve().parent.parent

PREFIXES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <http://schema.org/> .
@prefix ex: <http://example.org/> .
"""

# All test data is generated with a fixed seed, so test runs are reproducible
SEED = 20241108


def parse_turtle(text):
    """Parse a Turtle snippet; the common prefixes (sh, xsd, rdf, rdfs, schema, ex) are predeclared."""
    # bind_namespaces="core": the prefixes declared in the data win over rdflib's defaults (e.g. schema: -> https)
    return Graph(bind_namespaces="core").parse(data=PREFIXES + text, format="turtle")


def load_shapes(ttl=None, path=None):
    return Graph(bind_namespaces="core").parse(path) if path is not None else parse_turtle(ttl)


def generate(shapes_graph, scale=30, seed=SEED):
    """Generate `scale` entities per top-level node shape, in memory."""
    return generate_graph(shapes_graph, scale, seed=seed)


def generate_and_validate(ttl=None, path=None, scale=30):
    shapes_graph = load_shapes(ttl, path)
    return validate_generated(shapes_graph, generate(shapes_graph, scale))


def assert_conforms(summary):
    assert not summary.vacuous, "nothing was checked: the generator produced no entities for the shapes"
    assert summary.conforms, "\n" + summary.format()


def known_bug(item, description, raises=AssertionError):
    """
    Mark a test as an expected failure caused by a known generator bug, tracked under the given item of the
    v1.3 fix plan. The test must fail with the given exception (by default: a failed assertion, i.e. the
    generated data does not conform); a failure of any other kind is reported as an error. The marker is
    strict: once the bug is fixed, the test reports XPASS and fails, as a reminder to remove the marker.
    """
    return pytest.mark.xfail(strict=True, raises=raises, reason=f"known bug (v1.3 plan item {item}): {description}")
