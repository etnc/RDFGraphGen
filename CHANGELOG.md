# Changelog

All notable changes to RDFGraphGen are documented in this file.

## [Unreleased] - 1.3.0

### Added

- Conformance checking: `rdfgen validate SHAPES DATA` checks whether a graph conforms to SHACL shapes, and `--validate` (with `--report FILE`) checks a graph while it is generated. A generated graph conforms if every generated entity conforms to the shape it was generated from (via its `sh:description` link) and every focus node selected by the target declarations conforms to its shape, so the check is meaningful even for shapes without target declarations. The summary lists the validation results per constraint and distinguishes entities that only fail because a nested entity fails. With `--validate`, each batch is checked in its worker process right after it is generated, so the check scales with the generation. Requires the optional `validate` extra (pySHACL): `pip install "rdf-graph-gen[validate]"`.
- Reproducible generation: `--seed` (and the `seed` parameter of the Python functions). The same seed always produces the same output file, regardless of the number of processes.
- `--processes` sets the number of worker processes (default: the number of CPUs).
- `generate_graph(shapes, scale_factor, seed=None)` returns a generated graph as an rdflib `Graph`.
- `rdfgen --version`, and `python -m rdf_graph_gen` to run the command-line tool from a source checkout.
- Exit status: `0` success (with validation: the graph conforms), `1` the graph does not conform, `2` error, `3` nothing was checked.
- Test suite (pytest) with conformance tests for the experiment-suite shapes, the example shapes, the example from the paper, and individual SHACL constraint components; known generator bugs are tracked as expected failures. Continuous integration runs the tests on Python 3.9 to 3.14, and a lint check, for every push and pull request.

### Changed

- The batches of a generation run are written in batch order, and only a few batches are held in memory at a time; previously, the main process kept every generated batch in memory until the end of the run. Each worker process receives the shapes once, instead of once per batch.
- Generated IRIs and blank nodes are numbered per batch, so they do not depend on which process generates a batch.
- `generate_rdf` overwrites the output file instead of appending to it, and `batch_size` is optional.
- Packaging moved from `setup.py` to `pyproject.toml`. The bundled datasets are loaded with `importlib.resources`; `setuptools` / `pkg_resources` is no longer needed at runtime.
- New versions are published on PyPI only when a version tag (e.g. `v1.3.0`) is pushed, instead of on every push to `main`. The tag must match the package version.
- `scale_factor`, `--batch_size` and `--processes` must be positive integers (a batch size of `0` previously caused an endless loop).

### Fixed

- The name/gender/email heuristics for `schema:Person` added their dependencies again for every generated entity, which slowed generation down as more entities were generated.
