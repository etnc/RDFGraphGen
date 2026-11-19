# Changelog

All notable changes to RDFGraphGen are documented in this file.

## [1.3.0] - 2026-11-18

### Added

- Conformance checking: `rdfgen validate SHAPES DATA` checks whether a graph conforms to SHACL shapes, and `--validate` (with `--report FILE`) checks a graph while it is generated. A generated graph conforms if every generated entity conforms to the shape it was generated from (via its `sh:description` link) and every focus node selected by the target declarations conforms to its shape, so the check is meaningful even for shapes without target declarations. The summary lists the validation results per constraint and distinguishes entities that only fail because a nested entity fails. With `--validate`, each batch is checked in its worker process right after it is generated, so the check scales with the generation. Requires the optional `validate` extra (pySHACL): `pip install "rdf-graph-gen[validate]"`.
- Reproducible generation: `--seed` (and the `seed` parameter of the Python functions). The same seed always produces the same output file, regardless of the number of processes.
- `--processes` sets the number of worker processes (default: the number of CPUs).
- `generate_graph(shapes, scale_factor, seed=None)` returns a generated graph as an rdflib `Graph`.
- `rdfgen --version`, and `python -m rdf_graph_gen` to run the command-line tool from a source checkout.
- Exit status: `0` success (with validation: the graph conforms), `1` the graph does not conform, `2` error, `3` nothing was checked.
- `--base-iri` (`base_iri`) sets the start of the IRIs of generated entities, e.g. `https://data.example.com/` (default: `http://example.org/ns#`).
- `--format ntriples` (`output_format`) writes the output in N-Triples; it is the default for an output file ending in `.nt`, and Turtle otherwise. The output is the same for any number of processes in both formats.
- `--no-provenance` (`provenance=False`) leaves out the links of the generated entities to their shapes (`sh:description`). `--validate` still checks every entity against its shape.
- The output file starts with a comment that records how it was generated: the versions of RDFGraphGen and rdflib, the shapes file and the SHA-256 hash of its content, the scale factor, the batch size, the seed and the options.
- `sh:qualifiedValueShape`, with `sh:qualifiedMinCount`, `sh:qualifiedMaxCount` and `sh:qualifiedValueShapesDisjoint`: the required number of values conforms to the qualified shape, and no more than the maximum.
- Values of all XSD datatypes. Previously, only `xsd:string`, `xsd:integer`, `xsd:boolean` and `xsd:date` values had their datatype; values of all other datatypes were plain strings, which do not conform to `sh:datatype`. Now:
  - numbers: `xsd:decimal`, `xsd:double`, `xsd:float`, and all integer datatypes, within their value range (e.g. -128 to 127 for `xsd:byte`);
  - dates, times and durations: `xsd:dateTime`, `xsd:dateTimeStamp`, `xsd:time`, `xsd:gYear`, `xsd:gYearMonth`, `xsd:gMonth`, `xsd:gDay`, `xsd:gMonthDay`, `xsd:duration`, `xsd:dayTimeDuration` and `xsd:yearMonthDuration`, with value ranges and time zones;
  - strings of a certain form (e.g. `xsd:token`, `xsd:language`, `xsd:NCName`, `xsd:anyURI`), binary data (`xsd:hexBinary`, `xsd:base64Binary`), `rdf:XMLLiteral`, `rdf:HTML` and `rdf:JSON`;
  - any other datatype (e.g. a custom one): random words typed with the datatype, with a warning that they may not be valid values of it.
- Language-tagged strings: values of `rdf:langString`, and of properties with `sh:languageIn`, get a language tag (one of `sh:languageIn`, or else a common one). With `sh:uniqueLang`, every value of a property gets a different tag.
- `sh:minLength`, `sh:maxLength` and `sh:pattern` apply to values of every datatype, since they constrain the lexical form of any value: e.g. an `xsd:integer` with a length of 6 to 12 gets numbers with 6 to 12 digits, and one with the pattern `^[0-9]{5}$` gets five-digit numbers. Previously, they applied only to strings, and `sh:pattern` ignored `sh:minLength` and `sh:maxLength`. When no value can satisfy these constraints, a warning is shown and no value is generated.
- Sequence paths (e.g. `sh:path ( ex:address ex:postalCode )`) and inverse paths (e.g. `sh:path [ sh:inversePath ex:author ]`), and their combinations. A sequence path is generated through intermediate nodes (`entity ex:address [ ex:postalCode value ]`), and an inverse path as a triple in the other direction (`value ex:author entity`). The values of a path that ends with an inverse step are never literals, since they are subjects of triples; shapes that require literal values for such a path produce a warning.
- Test suite (pytest) with conformance tests for the experiment-suite shapes, the example shapes, the example from the paper, and individual SHACL constraint components; known generator bugs are tracked as expected failures. Continuous integration runs the tests on Python 3.9 to 3.14, and a lint check, for every push and pull request.
- An example of conferences, with their talks, speakers, venues and tickets, that uses most of the supported SHACL features in one shapes file.
- The README describes the supported SHACL features, the datatypes, the realistic values and the known limitations.

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
- The heuristics for realistic values recognise schema.org terms with `https://schema.org/` as well as `http://schema.org/`, and the data they generate uses the namespace of the shape.
- Generated e-mail addresses use the domain `example.com` instead of `gmail.com`. It is reserved for examples (RFC 2606), so an address built from a realistic name never belongs to a real person.
- The example shapes are named in the `ex:` namespace instead of the schema.org namespace, since the generated data links each entity to the shape it was generated from.
- Dates are drawn uniformly from the days of their range, and decimal numbers have two decimal places (more if the range requires it), so the generated values differ from those of earlier versions with the same shapes.
- `python-dateutil` is no longer a dependency.
- `sh:or` uses one of its shapes, instead of combining a random number of them: shapes can contradict each other (e.g. two datatypes), and then the combined constraints satisfied none of them. Shapes with a property path that is not supported are not used.
- The generated output uses the prefixes of the shapes file (e.g. `ex:` and `schema:`), instead of the ones rdflib makes up (e.g. `ns1:`) or its own defaults (which turned `schema:` for `http://schema.org/` into `schemaorg:` or `schema1:`).
- The example outputs are generated with a seed and checked with `--validate`; all of them conform.
- The measurement script of the experiment suite (`measure.sh`) writes the CSV header only to a new results file, does not record failed runs, and passes further options to `rdfgen` (e.g. `--seed` or `--processes`).

### Fixed

- The name/gender/email heuristics for `schema:Person` added their dependencies again for every generated entity, which slowed generation down as more entities were generated.
- `sh:not` crashed the shape parser, and was not enforced. The generated data is now checked, and generated again until no negated shape holds; values of `sh:in` and `sh:hasValue` in a negated shape are avoided directly. A negated shape that holds for the values the generator always gives (e.g. that all values of a property are strings) cannot be avoided yet.
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
- `sh:equals` copied only the first value of the other property, and nothing when that value was `0`; a property with `sh:in` or `sh:node` ignored `sh:equals`. The property now gets all values of the other property.
- With `sh:lessThan` or `sh:lessThanOrEquals`, the other property could get a value that left the property no valid value (e.g. `0`, when the property is at least `0`). The lower bound of the property now applies to the other property as well (exclusive for `sh:lessThan`), also when the shape declares the other property, and along chains (`a < b < c`); the other property gets the datatype of the property if it has none. In a chain between integers with tight ranges, values can still run out.
- `sh:class` on a property generated a literal instead of an instance of the class, also together with `sh:node` or `sh:in`, and left unused typed nodes in the data. The values are now instances of the class.
- `sh:nodeKind` was ignored. The values of a property shape, and the entities of a node shape, are now IRIs, blank nodes or literals as the node kind requires.
- `sh:node` on a node shape was skipped when the shape had properties, and otherwise produced a separate entity. The shapes of `sh:node` are now combined with the node shape, so its entities conform to them (also transitively, and in the shapes of `sh:and`, `sh:or` and `sh:xone`).
- With several `sh:node` shapes on a property, or `sh:node` together with nested property shapes, only one of them was used. Each value now conforms to all of them, and is linked to each shape of `sh:node`.
- Instances of a class did not conform to the other shapes that target the class (`sh:targetClass`), e.g. the entities of two shapes with the same target class, or the values of a property with `sh:class`. The shapes that target a class are now combined with the shape of every instance of the class that is generated. `sh:targetSubjectsOf` and `sh:targetObjectsOf` are not supported yet.
- An entity of a node shape without properties was replaced by a literal, and classes given in the shapes of `sh:and`, `sh:or` and `sh:xone` were not added to the entity.
- With `sh:xone`, the generated data could satisfy more than one shape, e.g. when a shape only limits a property (`sh:maxCount 1`) and holds for a node without it. The data is now checked, and generated again until exactly one shape of each list holds (up to 20 attempts, with a warning if none succeeds). A property generated after another one (e.g. with `sh:lessThan`) no longer combines two choices of `sh:or` or `sh:xone`.
- Realistic values (e.g. names from the name lists, e-mail addresses built from them) ignored the constraints of the property, such as `sh:maxLength`, `sh:pattern` or `sh:not`. They are now used only if they satisfy them, and otherwise a value is generated from the constraints. A datatype is no longer guessed from the name of a property (e.g. an integer for `phoneNumber`) when the shape gives a pattern for its values.
- The default patterns for properties named like an e-mail address or a telephone number produced malformed values (e.g. `n@gmailucom`, `339217-3216`).
- Entities of closed shapes (`sh:closed true`) did not conform, because of their link to the shape (`sh:description`). They are no longer linked in the data (unless the shape lists `sh:description` in `sh:ignoredProperties`); `--validate` still checks them against their shape, and `rdfgen validate` through the shapes that refer to them and the target declarations.
- IRIs with `sh:pattern`, `sh:minLength` or `sh:maxLength` (e.g. `sh:nodeKind sh:IRI` with a pattern for Wikidata IRIs) did not conform, since generated IRIs were always numbered and some values were blank nodes. Such IRIs are now generated from these constraints.
- `rdfgen` crashed with a traceback and exit status `1` (which means that the graph does not conform) when the shapes file was missing or not valid RDF, or when the output file could not be written. It now prints an error message and exits with status `2`, and writes nothing if the shapes cannot be read.
