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
- Values of all XSD datatypes. Previously, only `xsd:string`, `xsd:integer`, `xsd:boolean` and `xsd:date` values had their datatype; values of all other datatypes were plain strings, which do not conform to `sh:datatype`. Now:
  - numbers: `xsd:decimal`, `xsd:double`, `xsd:float`, and all integer datatypes, within their value range (e.g. -128 to 127 for `xsd:byte`);
  - dates, times and durations: `xsd:dateTime`, `xsd:dateTimeStamp`, `xsd:time`, `xsd:gYear`, `xsd:gYearMonth`, `xsd:gMonth`, `xsd:gDay`, `xsd:gMonthDay`, `xsd:duration`, `xsd:dayTimeDuration` and `xsd:yearMonthDuration`, with value ranges and time zones;
  - strings of a certain form (e.g. `xsd:token`, `xsd:language`, `xsd:NCName`, `xsd:anyURI`), binary data (`xsd:hexBinary`, `xsd:base64Binary`), `rdf:XMLLiteral`, `rdf:HTML` and `rdf:JSON`;
  - any other datatype (e.g. a custom one): random words typed with the datatype, with a warning that they may not be valid values of it.
- Language-tagged strings: values of `rdf:langString`, and of properties with `sh:languageIn`, get a language tag (one of `sh:languageIn`, or else a common one). With `sh:uniqueLang`, every value of a property gets a different tag.
- `sh:minLength`, `sh:maxLength` and `sh:pattern` apply to values of every datatype, since they constrain the lexical form of any value: e.g. an `xsd:integer` with a length of 6 to 12 gets numbers with 6 to 12 digits, and one with the pattern `^[0-9]{5}$` gets five-digit numbers. Previously, they applied only to strings, and `sh:pattern` ignored `sh:minLength` and `sh:maxLength`. When no value can satisfy these constraints, a warning is shown and no value is generated.
- Sequence paths (e.g. `sh:path ( ex:address ex:postalCode )`) and inverse paths (e.g. `sh:path [ sh:inversePath ex:author ]`), and their combinations. A sequence path is generated through intermediate nodes (`entity ex:address [ ex:postalCode value ]`), and an inverse path as a triple in the other direction (`value ex:author entity`). The values of a path that ends with an inverse step are never literals, since they are subjects of triples; shapes that require literal values for such a path produce a warning.
- Test suite (pytest) with conformance tests for the experiment-suite shapes, the example shapes, the example from the paper, and individual SHACL constraint components; known generator bugs are tracked as expected failures. Continuous integration runs the tests on Python 3.9 to 3.14, and a lint check, for every push and pull request.

### Changed

- The batches of a generation run are written in batch order, and only a few batches are held in memory at a time; previously, the main process kept every generated batch in memory until the end of the run. Each worker process receives the shapes once, instead of once per batch.
- Generated IRIs and blank nodes are numbered per batch, so they do not depend on which process generates a batch.
- `generate_rdf` overwrites the output file instead of appending to it, and `batch_size` is optional.
- Packaging moved from `setup.py` to `pyproject.toml`. The bundled datasets are loaded with `importlib.resources`; `setuptools` / `pkg_resources` is no longer needed at runtime.
- New versions are published on PyPI only when a version tag (e.g. `v1.3.0`) is pushed, instead of on every push to `main`. The tag must match the package version.
- `scale_factor`, `--batch_size` and `--processes` must be positive integers (a batch size of `0` previously caused an endless loop).
- A parameter that SHACL allows only once per shape (e.g. `sh:maxCount`, `sh:datatype`, `sh:pattern`) produces a warning when a shape repeats it, and the first value is used.
- Shapes used through `sh:qualifiedValueShape`, `sh:not`, the lists of `sh:and`, `sh:or` and `sh:xone`, or a named property shape count as used by another shape, like shapes used through `sh:node`, so they no longer get separate top-level entities.
- The `schema:Person` heuristics (names, e-mail address) also apply to shapes that declare the class with `sh:class` instead of `sh:targetClass`.
- The example shapes are named in the `ex:` namespace instead of the schema.org namespace, since the generated data links each entity to the shape it was generated from.
- Dates are drawn uniformly from the days of their range, and decimal numbers have two decimal places (more if the range requires it), so the generated values differ from those of earlier versions with the same shapes.
- `python-dateutil` is no longer a dependency.

### Fixed

- The name/gender/email heuristics for `schema:Person` added their dependencies again for every generated entity, which slowed generation down as more entities were generated.
- `sh:not` crashed the shape parser. It is now parsed, but not yet enforced during generation.
- With `sh:equals` or `sh:disjoint`, the declaration of the other property was replaced by a bare one, so its constraints (e.g. its datatype and value range) were lost.
- Generation never ended when a property waited for the values of another property (`sh:equals`, `sh:disjoint`, `sh:lessThan`, `sh:lessThanOrEquals`, or the `schema:Person` heuristics) that got no values, and `sh:disjoint` never ended once the other property had values. Such properties also got too many values.
- A repeated parameter (e.g. `sh:class ex:A, ex:B`, several `sh:hasValue` values or several `sh:or` lists) kept only its last value; all values are now used. `sh:class` was ignored on a shape that also had `sh:targetClass`.
- Several property shapes with the same path, and the shapes of `sh:and`, `sh:or` and `sh:xone` that are combined with a shape, were merged so that the last value of each parameter won. They are now combined so that all of them hold: the strictest bounds, the values that every `sh:in` list allows, and nested property shapes combined per path.
- Complex property paths were written as predicates, which produced invalid RDF (blank nodes as predicates). Alternative, zero-or-more, one-or-more and zero-or-one paths are not supported yet; such properties are skipped with a warning.
- Recursive shapes (e.g. a person who knows other persons) nested new entities without limit, which produced thousands of entities or a `RecursionError` with an optional property, and never ended with a required one. A shape now occurs at most three times on the path from a top-level entity to a generated entity; beyond that, only the required number of values is generated, using earlier entities of that shape where possible (e.g. two people who know each other).
- A shape that uses itself, and shapes that use each other in a cycle that no other shape uses, got no entities (and their validation passed only because nothing was checked). Such a shape, and one shape of each such cycle, now gets top-level entities.
- Example shapes that no data could conform to, or with invalid patterns or language tags (person, TV series, value generation, book).
- `xsd:decimal` values were floating-point numbers typed `xsd:double`.
- A bound of `0` was ignored for decimal numbers, and so was `sh:maxLength 0`.
- `sh:lessThan` and `sh:lessThanOrEquals` replaced `sh:maxInclusive` and `sh:maxExclusive` instead of both applying, and `sh:lessThan` allowed the other value itself for dates. A bound with a fractional part for integers (e.g. `sh:minInclusive 1.5`) was truncated instead of rounded up.
- `sh:languageIn` was not parsed as a list, so it was ignored.
