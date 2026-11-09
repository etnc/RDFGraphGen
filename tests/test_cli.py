"""Tests of the rdfgen command-line interface."""
import pytest
from rdflib import Graph, RDF, SH

from support import PREFIXES, REPO_ROOT

from rdf_graph_gen import __version__
from rdf_graph_gen.script import EXIT_ERROR, EXIT_NONCONFORMING, EXIT_OK, main

SHAPES = PREFIXES + """
ex:ValueShape a sh:NodeShape ;
    sh:property [ sh:path ex:value ; sh:datatype xsd:integer ; sh:minCount 1 ] .
"""
# A shape that no graph can satisfy: generation can never produce conforming data for it.
UNSATISFIABLE_SHAPES = PREFIXES + """
ex:ImpossibleShape a sh:NodeShape ;
    sh:property [ sh:path ex:value ; sh:minCount 3 ; sh:maxCount 2 ] .
"""


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_validate_command_conforming_graph(tmp_path, capsys):
    shapes = write(tmp_path, "shapes.ttl", SHAPES)
    data = write(tmp_path, "data.ttl", PREFIXES + "ex:n1 sh:description ex:ValueShape ; ex:value 7 .")
    assert main(["validate", shapes, data]) == EXIT_OK
    assert "Conformance check: CONFORMS" in capsys.readouterr().out


def test_validate_command_nonconforming_graph_writes_report(tmp_path, capsys):
    shapes = write(tmp_path, "shapes.ttl", SHAPES)
    data = write(tmp_path, "data.ttl", PREFIXES + 'ex:n1 sh:description ex:ValueShape ; ex:value "seven" .')
    report = tmp_path / "report.ttl"
    assert main(["validate", shapes, data, "--report", str(report)]) == EXIT_NONCONFORMING
    assert "DOES NOT CONFORM" in capsys.readouterr().out
    assert (None, RDF.type, SH.ValidationReport) in Graph().parse(report)


def test_validate_command_declared_targets_only(tmp_path, capsys):
    shapes = write(tmp_path, "shapes.ttl", SHAPES)
    data = write(tmp_path, "data.ttl", PREFIXES + 'ex:n1 sh:description ex:ValueShape ; ex:value "seven" .')
    assert main(["validate", shapes, data, "--declared-targets-only"]) == EXIT_OK
    assert "NOTHING CHECKED" in capsys.readouterr().out


def test_validate_command_missing_file(tmp_path, capsys):
    shapes = write(tmp_path, "shapes.ttl", SHAPES)
    assert main(["validate", shapes, str(tmp_path / "missing.ttl")]) == EXIT_ERROR
    assert "cannot read" in capsys.readouterr().err


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


@pytest.mark.parametrize("scale_factor", ["0", "-5", "ten"])
def test_scale_factor_must_be_a_positive_integer(tmp_path, scale_factor):
    with pytest.raises(SystemExit) as exit_info:
        main([write(tmp_path, "shapes.ttl", SHAPES), str(tmp_path / "out.ttl"), scale_factor])
    assert exit_info.value.code == EXIT_ERROR


def test_batch_size_must_be_a_positive_integer(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        main([write(tmp_path, "shapes.ttl", SHAPES), str(tmp_path / "out.ttl"), "10", "-b", "0"])
    assert exit_info.value.code == EXIT_ERROR


def test_report_requires_validate(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        main([write(tmp_path, "shapes.ttl", SHAPES), str(tmp_path / "out.ttl"), "10", "--report", "r.ttl"])
    assert exit_info.value.code == EXIT_ERROR


def test_generate_with_validate_conforming(tmp_path, capsys):
    shapes = str(REPO_ROOT / "experiment_suite" / "shape-single-simple.ttl")
    output = tmp_path / "out.ttl"
    assert main([shapes, str(output), "25", "-b", "10", "--validate"]) == EXIT_OK
    assert "Conformance check: CONFORMS" in capsys.readouterr().out
    assert len(set(Graph().parse(output).subjects(SH.description, None))) == 25


def test_generate_with_validate_nonconforming(tmp_path, capsys):
    shapes = write(tmp_path, "shapes.ttl", UNSATISFIABLE_SHAPES)
    assert main([shapes, str(tmp_path / "out.ttl"), "5", "--validate"]) == EXIT_NONCONFORMING
    assert "DOES NOT CONFORM" in capsys.readouterr().out
