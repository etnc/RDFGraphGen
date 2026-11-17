# RDFGraphGen: A Synthetic RDF Graph Generator based on SHACL Shapes

This is a Python package which can be used to generate synthetic RDF knowledge graphs, based on SHACL shapes. 

The Shapes Constraint Language (SHACL) is a W3C standard which specifies ways to validate data in RDF graphs, by defining constraining shapes. However, even though the main purpose of SHACL is validation of existing RDF data, in order to solve the problem with the lack of available RDF datasets in multiple RDF-based application development processes, we envisioned and implemented a reverse role for SHACL: we use SHACL shape definitions as a starting point to generate synthetic data for an RDF graph. 

The generation process involves extracting the constraints from the SHACL shapes, converting the specified constraints into rules, and then generating artificial data for a predefined number of RDF entities, based on these rules. The purpose of RDFGraphGen is the generation of small, medium or large RDF knowledge graphs for the purpose of benchmarking, testing, quality control, training and other similar purposes for applications from the RDF, Linked Data and Semantic Web domain.

## Usage

The following functions from `rdf_graph_gen.rdf_graph_generator` can be used to generate RDF data:

__generate_rdf(input-shape.ttl, output-graph.ttl, scale-factor)__
- input-shape.ttl is a Turtle file that contains SHACL shapes
- output-graph.ttl is a Turtle file that will store the generated RDF entities
- scale-factor determines the size of the generated RDF graph
- optional: `batch_size`, `seed` (the same seed always produces the same graph), `processes`, `provenance`, `base_iri` and `output_format` (see the command line options below)

__generate_graph(shapes, scale-factor, seed=None)__ returns the generated RDF graph as an rdflib `Graph`, instead of writing it to a file (optional: `provenance` and `base_iri`).

## Installation

RDFGraphGen is available on PyPi: https://pypi.org/project/rdf-graph-gen/

To install it, use:

```pip install rdf-graph-gen```

After installation, this package can be used as a command line tool:

```rdfgen input-shape.ttl output-graph.ttl scale-factor```

There are also some optional parameters. You can find out more by using the:

```rdfgen --help```

For reproducible graphs, e.g. for benchmarks, use `--seed`: the same seed always produces the same graph, regardless of the number of worker processes (`--processes`).

The output file starts with a comment that records how it was generated: the RDFGraphGen version, the shapes file and its SHA-256 hash, the scale factor, the batch size, the seed and the options. With the same values, the same graph is generated again.

The IRIs of the generated entities start with `http://example.org/ns#`; use `--base-iri` to choose another namespace, e.g. `--base-iri https://data.example.com/`.

The output is written in Turtle, or in N-Triples with `--format ntriples` (the default for an output file ending in `.nt`).

## Checking Conformance

RDFGraphGen can check whether a generated RDF graph conforms to the input SHACL shapes. This requires the optional validation dependencies:

```pip install "rdf-graph-gen[validate]"```

To check the graph right after it is generated, add the `--validate` flag:

```rdfgen input-shape.ttl output-graph.ttl scale-factor --validate```

To check any existing RDF graph against SHACL shapes, use the `validate` command:

```rdfgen validate input-shape.ttl output-graph.ttl```

A generated graph conforms if every generated entity conforms to the shape it was generated from (the generator links each entity to its shape with `sh:description`), and every focus node selected by the target declarations of the shapes conforms to its shape. This makes the check meaningful even for shapes without target declarations. The command prints a summary of the validation results per constraint, distinguishing entities that fail only because a nested entity fails; `--report FILE` writes the full SHACL validation report. The exit status is `0` if the graph conforms, `1` if it does not, and `3` if nothing was checked.

With `--validate`, each batch is checked right after it is generated, so the check scales with the generation. The `validate` command loads the whole graph into memory, so it is intended for small and medium-sized graphs.

Entities of closed shapes (`sh:closed true`) are not linked to their shape, since the link would break the shape, and `--no-provenance` leaves out all links. `--validate` still checks every entity against its shape; the `validate` command checks such entities only through the target declarations of the shapes and the shapes that refer to them (`sh:node`).

## Examples

Examples of SHACL shapes based on Schema.org and other types, along with generated synthetic RDF graphs based on these shapes, can be found in the [generated examples](generated_examples/) directory in this repo. The [conference example](generated_examples/shape_examples/conference_shape.ttl) uses most of the supported SHACL features in one file.

## Publications

* Milos Jovanovik, Marija Vecovska, Maxime Jakubowski, Katja Hose. "[RDFGraphGen: An RDF Graph Generator based on SHACL Shapes](https://link.springer.com/chapter/10.1007/978-981-95-5009-8_8)". Knowledge Graphs. IJCKG 2025. Lecture Notes in Computer Science, Volume 16297, pp. 111-125, 2026.
* (preprint) Milos Jovanovik, Marija Vecovska, Maxime Jakubowski, Katja Hose. "[RDFGraphGen: An RDF Graph Generator based on SHACL Shapes](https://arxiv.org/abs/2407.17941)". arXiv:2407.17941.

## Supported SHACL Features

RDFGraphGen generates data for the constraints of SHACL Core, except for those listed as not supported below.

| Feature | Support |
|---|---|
| Node shapes | Shapes declared with `a sh:NodeShape`. Entities are generated for each top-level node shape, i.e. a shape that no other shape uses; the other shapes are generated as parts of these entities. |
| Targets | `sh:targetClass`: the generated entities are instances of the class. `sh:targetNode`, `sh:targetSubjectsOf` and `sh:targetObjectsOf` are not used for generation (the conformance check still checks the nodes they select). |
| Property paths | Predicate, sequence and inverse paths, also nested. Not supported: alternative paths, `sh:zeroOrMorePath`, `sh:oneOrMorePath` and `sh:zeroOrOnePath` (such a property is skipped, with a warning). |
| Value type | `sh:class`, `sh:datatype` (see below), `sh:nodeKind` |
| Cardinality | `sh:minCount`, `sh:maxCount` |
| Value range | `sh:minInclusive`, `sh:minExclusive`, `sh:maxInclusive`, `sh:maxExclusive`, for numbers, dates and times, and durations |
| String-based | `sh:minLength`, `sh:maxLength`, `sh:pattern`, `sh:languageIn`, `sh:uniqueLang`; lengths and patterns also apply to IRIs (which are then generated from the pattern) and to values of other datatypes |
| Property pairs | `sh:equals`, `sh:disjoint`, `sh:lessThan`, `sh:lessThanOrEquals` |
| Logical | `sh:and`, `sh:or`, `sh:xone`, `sh:not` (see the limitations below) |
| Shape-based | `sh:node`, `sh:property`, `sh:qualifiedValueShape` with `sh:qualifiedMinCount`, `sh:qualifiedMaxCount` and `sh:qualifiedValueShapesDisjoint` |
| Other | `sh:closed` with `sh:ignoredProperties`, `sh:hasValue`, `sh:in` |
| Not used | `sh:name`, `sh:description`, `sh:order`, `sh:group`, `sh:defaultValue`, `sh:severity`, `sh:message`, `sh:deactivated` (the data follows deactivated shapes too) |
| Not supported | SHACL-SPARQL (`sh:sparql`), SHACL Advanced Features, SHACL 1.2 |

Datatypes:
- `xsd:string`, `rdf:langString` (with language tags), `xsd:boolean`
- all XSD integer types (`xsd:integer`, `xsd:int`, `xsd:positiveInteger`, `xsd:unsignedByte`, ...), within their value ranges; `xsd:decimal`, `xsd:float`, `xsd:double`
- dates and times (`xsd:date`, `xsd:dateTime`, `xsd:dateTimeStamp`, `xsd:time`, `xsd:gYear`, `xsd:gYearMonth`, `xsd:gMonth`, `xsd:gMonthDay`, `xsd:gDay`), with the time zone of their bounds; durations (`xsd:duration`, `xsd:dayTimeDuration`, `xsd:yearMonthDuration`)
- string-based types (`xsd:anyURI`, `xsd:language`, `xsd:token`, `xsd:NCName`, ...), `xsd:hexBinary`, `xsd:base64Binary`, `rdf:HTML`, `rdf:XMLLiteral`
- other datatypes (e.g. custom ones): random words typed with the datatype, with a warning

For some Schema.org properties of persons, books, movies and TV series (e.g. names, e-mail addresses, genres), realistic values are taken from lists, if they satisfy the constraints of the property. Without `sh:datatype` and `sh:pattern`, a property whose name contains `date` or `number` gets dates or integers, and without `sh:pattern`, a property whose name contains `email` or `telephone` gets values in the form of e-mail addresses or telephone numbers.

Known limitations:
- The constraints are satisfied one value at a time, not solved together, so combinations that leave very few possible values can fail, e.g. a chain of `sh:lessThan` between integers with tight bounds.
- `sh:not` is satisfied by avoiding the values of `sh:in` and `sh:hasValue` in the negated shape, and otherwise by generating again until the negated shape does not hold. Data that must break a shape that the generated values usually satisfy (e.g. `sh:not [ sh:datatype xsd:string ]` for a property without a datatype) is not generated.
- A shape that uses itself, directly or through other shapes, is generated up to three levels deep; deeper values reuse entities generated before.
- `sh:flags` is not used for generation: the values match the pattern without flags, which is enough for the flags `i`, `m` and `s`.
- pySHACL evaluates the inverse of a sequence path (`[ sh:inversePath ( ex:a ex:b ) ]`) incorrectly, so `--validate` can report violations of such paths that are not there.

When the generated data does not conform because of one of these limitations, `--validate` reports it.
