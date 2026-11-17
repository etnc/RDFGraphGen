"""
Generation of (large) RDF graphs in batches, optionally in parallel worker processes.

Each batch is generated independently: its entities never reference entities of other batches, and with a
seed, its content depends only on (seed, batch index). The batches are written to the output file in batch
order, so the output is the same regardless of the number of processes. Optionally, each batch is validated
right after it is generated (in its worker process), which is exact because the batches are disjoint, and
keeps validation as scalable as generation.
"""
import hashlib
import multiprocessing as mp
import os
from collections import deque
from itertools import islice

import rdflib
from rdflib import Graph

from rdf_graph_gen import __version__

from rdf_graph_gen.rdf_graph_generator import DEFAULT_BASE_IRI, checked_base_iri, generate_batch
from rdf_graph_gen.shacl_mapping_generator import generate_dictionary_from_shapes_graph

REPOSITORY_URL = "https://github.com/etnc/RDFGraphGen"

# The output formats: they can be written batch by batch (formats such as RDF/XML or JSON-LD cannot, since two of
# their documents cannot simply be joined), with their names in rdflib
OUTPUT_FORMATS = {"turtle": "turtle", "ntriples": "nt"}


def output_format_of(output_file, output_format=None):
    """The output format: the given one, or else the one of the file name (ntriples for .nt files, else turtle)."""
    if output_format is None:
        return "ntriples" if str(output_file).lower().endswith(".nt") else "turtle"
    if output_format not in OUTPUT_FORMATS:
        raise ValueError(f"unknown output format {output_format!r} (use one of: {', '.join(OUTPUT_FORMATS)})")
    return output_format


def serialize_batch(graph, output_format):
    """
    The text of a batch in the output format. N-Triples lines are sorted, since rdflib writes them in an order that
    varies between processes, and the output must not depend on the number of processes.
    """
    text = graph.serialize(format=OUTPUT_FORMATS[output_format])
    if output_format == "ntriples":
        lines = sorted(line for line in text.splitlines() if line.strip())
        return "".join(line + "\n" for line in lines)
    return text

# State of a worker process, set once per process by _init_worker
_worker_state = {}


def _init_worker(shapes_graph, dictionary, seed, validate, collect_report, provenance=True,
                 base_iri=DEFAULT_BASE_IRI, output_format="turtle"):
    _worker_state.update(shapes_graph=shapes_graph, dictionary=dictionary, seed=seed, validate=validate,
                         collect_report=collect_report, provenance=provenance, base_iri=base_iri,
                         output_format=output_format)


def _generate_batch(batch_index, size):
    """Generate one batch; return its text in the output format and, if requested, its validation results."""
    state = _worker_state
    graph = generate_batch(state["shapes_graph"], state["dictionary"], size, batch_index, state["seed"],
                           state["provenance"], state["base_iri"])
    validation = None
    if state["validate"]:
        from rdf_graph_gen.validation import validate_generated
        # Constant focus nodes selected by sh:targetNode are the same in every batch: check them only once
        summary = validate_generated(state["shapes_graph"], graph, declared_target_nodes=(batch_index == 1))
        report_text = summary.report_graph.serialize(format="nt") if state["collect_report"] else None
        summary.report_graph = None  # keep what is sent back to the main process small
        validation = (summary, report_text)
    return serialize_batch(graph, state["output_format"]), validation


class MultiprocessGenerator:
    def __init__(self, shape_file, output_file, graph_number, batch_size=1000, processes=None, seed=None,
                 validate=False, collect_report=False, provenance=True, base_iri=DEFAULT_BASE_IRI,
                 output_format=None, shapes_graph=None):
        """
        shape_file: file with the SHACL shapes; output_file: the generated graph is written to it.
        graph_number: the scale factor (entities per top-level node shape); batch_size: entities per batch.
        processes: number of worker processes (default: number of CPUs; 1 = generate in this process).
        seed: optional; the same seed always produces the same output, for any number of processes.
        validate: validate each batch after it is generated; generate() then returns a ValidationSummary.
        collect_report: with validate, also collect the full SHACL validation report (summary.report_graph).
        provenance: link each entity to its shape (sh:description) in the output; validate checks every entity
        against its shape either way.
        base_iri: the IRIs of the generated entities start with it (default: http://example.org/ns#).
        output_format: "turtle" or "ntriples" (default: ntriples for an output file ending in .nt, else turtle).
        shapes_graph: optional, the shapes of shape_file already parsed (by default, they are parsed from it).
        """
        self.shape_file = shape_file
        self.output_file = output_file
        self.graph_number = graph_number
        self.batch_size = batch_size
        self.processes = processes or os.cpu_count() or 1
        self.seed = seed
        self.validate = validate
        self.collect_report = collect_report
        self.provenance = provenance
        self.base_iri = checked_base_iri(base_iri)
        self.output_format = output_format_of(output_file, output_format)

        # Parse the shapes in this process first, so that errors in the shapes are reported here.
        # bind_namespaces="core": the prefixes of the shapes file win over rdflib's defaults in summaries.
        if shapes_graph is None:
            shapes_graph = Graph(bind_namespaces="core").parse(self.shape_file)
        self.shape = shapes_graph
        self.dictionary = generate_dictionary_from_shapes_graph(self.shape)

    def batches(self):
        """(batch index, number of entities) for every batch."""
        index, remaining = 1, self.graph_number
        while remaining > 0:
            size = min(remaining, self.batch_size)
            yield index, size
            index += 1
            remaining -= size

    def generate(self):
        """Generate the graph into the output file. Returns the ValidationSummary if validate, otherwise None."""
        accumulator = None
        if self.validate:
            from rdf_graph_gen.validation import ValidationAccumulator
            accumulator = ValidationAccumulator(collect_report=self.collect_report)

        with open(self.output_file, "w", encoding="utf-8") as output:
            output.write(self.header())
            for text, validation in self._batch_results():
                output.write(text)
                if accumulator is not None:
                    accumulator.add(*validation)
        return accumulator.summary() if accumulator is not None else None

    def header(self):
        """
        A comment at the top of the output file that records how the graph was generated: everything that determines
        it (the versions, the shapes and their SHA-256 hash, the scale factor, the batch size, the seed and the
        options), so that the same graph can be generated again. It has no time stamp and no number of processes,
        since the same seed produces the same file regardless of when and with how many processes it runs.
        """
        with open(self.shape_file, "rb") as shapes:
            digest = hashlib.sha256(shapes.read()).hexdigest()
        seed = self.seed if self.seed is not None else "none (every run generates a different graph)"
        lines = [
            f"Generated by RDFGraphGen {__version__} (rdflib {rdflib.__version__}), {REPOSITORY_URL}",
            f"Shapes: {os.path.basename(self.shape_file)} (SHA-256: {digest})",
            f"Scale factor: {self.graph_number}, batch size: {self.batch_size}, seed: {seed}",
            f"Base IRI: {self.base_iri}, links of entities to their shapes (sh:description): "
            f"{'yes' if self.provenance else 'no'}",
        ]
        return "".join(f"# {' '.join(line.split())}\n" for line in lines) + "\n"

    def _batch_results(self):
        """The results of all batches, in batch order. Only a few batches are held in memory at any time."""
        init_args = (self.shape, self.dictionary, self.seed, self.validate, self.collect_report, self.provenance,
                     self.base_iri, self.output_format)
        number_of_batches = -(-self.graph_number // self.batch_size)
        processes = min(self.processes, number_of_batches)

        if processes <= 1:
            _init_worker(*init_args)
            for batch in self.batches():
                yield _generate_batch(*batch)
            return

        window = 2 * processes  # batches in progress or waiting to be written
        with mp.Pool(processes, initializer=_init_worker, initargs=init_args) as pool:
            batches = self.batches()
            pending = deque(pool.apply_async(_generate_batch, batch) for batch in islice(batches, window))
            while pending:
                result = pending.popleft().get()
                next_batch = next(batches, None)
                if next_batch is not None:
                    pending.append(pool.apply_async(_generate_batch, next_batch))
                yield result
