# RDFGraphGen: A Synthetic RDF Graph Generator based on SHACL Shapes

This is a Python package which can be used to generate synthetic RDF knowledge graphs, based on SHACL shapes. 

The Shapes Constraint Language (SHACL) is a W3C standard which specifies ways to validate data in RDF graphs, by defining constraining shapes. However, even though the main purpose of SHACL is validation of existing RDF data, in order to solve the problem with the lack of available RDF datasets in multiple RDF-based application development processes, we envisioned and implemented a reverse role for SHACL: we use SHACL shape definitions as a starting point to generate synthetic data for an RDF graph. 

The generation process involves extracting the constraints from the SHACL shapes, converting the specified constraints into rules, and then generating artificial data for a predefined number of RDF entities, based on these rules. The purpose of RDFGraphGen is the generation of small, medium or large RDF knowledge graphs for the purpose of benchmarking, testing, quality control, training and other similar purposes for applications from the RDF, Linked Data and Semantic Web domain.

## Usage

The following function can be used to generate RDF data:

__generate_rdf(input-shape.ttl, output-graph.ttl, scale-factor)__
- input-shape.ttl is a Turtle file that contains SHACL shapes
- output-graph.ttl is a Turtle file that will store the generated RDF entities
- scale-factor determines the size of the generated RDF graph

## Installation

RDFGraphGen is available on PyPi: https://pypi.org/project/rdf-graph-gen/

To install it, use:

```pip install rdf-graph-gen```

After installation, this package can be used as a command line tool:

```rdfgen input-shape.ttl output-graph.ttl scale-factor```

There are also some optional parameters. You can find out more by using the:

```rdfgen --help```

## Examples

Examples of SHACL shapes based on Schema.org and other types, along with generated synthetic RDF graphs based on these shapes, can be found in the [generated examples](generated_examples/) directory in this repo.

## Publications

* (preprint) Marija Vecovska, Milos Jovanovik. "[RDFGraphGen: A Synthetic RDF Graph Generator based on SHACL Constraints](https://arxiv.org/abs/2407.17941)". arXiv:2407.17941.

## Remarks

- A SHACL shape has to have a 'a sh:NodeShape' property and object in order to be recognized as a Node Shape.
- ``sh:severity`` is ignored because it has no useful info.
- Only predicate paths are supported at this time.
- Most common ``sh:datatype`` scenarios are supported.
- Currently ``sh:nodeKind`` is ignored. 
