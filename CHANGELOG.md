# Changelog

All notable changes to RDFGraphGen are documented in this file.

## [Unreleased] - 1.3.0

### Added

- `rdfgen validate SHAPES DATA` command, and `--validate` / `--report FILE` options for generation, which check whether a graph conforms to the input SHACL shapes and print a summary of the validation results per constraint. Each generated entity is checked against the shape it was generated from (via its `sh:description` link), so the check is meaningful even for shapes without target declarations. The exit status is `0` if the graph conforms and `1` if it does not. Requires the optional `validate` extra (pySHACL): `pip install "rdf-graph-gen[validate]"`.
- `rdfgen --version`, and `python -m rdf_graph_gen` to run the command-line tool from a source checkout.
- Test suite (pytest) with conformance tests for the experiment-suite shapes, the example shapes, the example from the paper, and individual SHACL constraint components. Known generator bugs are tracked as expected failures.
- Continuous integration: the test suite runs on Python 3.9 to 3.14 for every push and pull request.

### Changed

- Packaging moved from `setup.py` to `pyproject.toml`. The bundled datasets are loaded with `importlib.resources`; `setuptools` / `pkg_resources` is no longer needed at runtime.
- New versions are published on PyPI only when a version tag (e.g. `v1.3.0`) is pushed, instead of on every push to `main`. The tag must match the package version.
- `rdfgen` now returns an exit status. `scale_factor` and `--batch_size` must be positive integers (a batch size of `0` previously caused an endless loop).
