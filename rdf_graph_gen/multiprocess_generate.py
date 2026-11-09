"""
Generation of (large) RDF graphs in batches, optionally in parallel worker processes.

Each batch is generated independently: its entities never reference entities of other batches, and with a
seed, its content depends only on (seed, batch index). The batches are written to the output file in batch
order, so the output is the same regardless of the number of processes. Optionally, each batch is validated
right after it is generated (in its worker process), which is exact because the batches are disjoint, and
keeps validation as scalable as generation.
"""
import multiprocessing as mp
import os
from collections import deque
from itertools import islice

from rdflib import Graph

from rdf_graph_gen.rdf_graph_generator import generate_batch
from rdf_graph_gen.shacl_mapping_generator import generate_dictionary_from_shapes_graph

# State of a worker process, set once per process by _init_worker
_worker_state = {}


def _init_worker(shapes_graph, dictionary, seed, validate, collect_report):
    _worker_state.update(shapes_graph=shapes_graph, dictionary=dictionary, seed=seed, validate=validate,
                         collect_report=collect_report)


def _generate_batch(batch_index, size):
    """Generate one batch; return its Turtle serialization and, if requested, its validation results."""
    state = _worker_state
    graph = generate_batch(state["shapes_graph"], state["dictionary"], size, batch_index, state["seed"])
    validation = None
    if state["validate"]:
        from rdf_graph_gen.validation import validate_generated
        # Constant focus nodes selected by sh:targetNode are the same in every batch: check them only once
        summary = validate_generated(state["shapes_graph"], graph, declared_target_nodes=(batch_index == 1))
        report_text = summary.report_graph.serialize(format="nt") if state["collect_report"] else None
        summary.report_graph = None  # keep what is sent back to the main process small
        validation = (summary, report_text)
    return graph.serialize(format="turtle"), validation


class MultiprocessGenerator:
    def __init__(self, shape_file, output_file, graph_number, batch_size=1000, processes=None, seed=None,
                 validate=False, collect_report=False):
        """
        shape_file: file with the SHACL shapes; output_file: the generated graph is written to it (Turtle).
        graph_number: the scale factor (entities per top-level node shape); batch_size: entities per batch.
        processes: number of worker processes (default: number of CPUs; 1 = generate in this process).
        seed: optional; the same seed always produces the same output, for any number of processes.
        validate: validate each batch after it is generated; generate() then returns a ValidationSummary.
        collect_report: with validate, also collect the full SHACL validation report (summary.report_graph).
        """
        self.shape_file = shape_file
        self.output_file = output_file
        self.graph_number = graph_number
        self.batch_size = batch_size
        self.processes = processes or os.cpu_count() or 1
        self.seed = seed
        self.validate = validate
        self.collect_report = collect_report

        # Parse the shapes in this process first, so that errors in the shapes are reported here.
        # bind_namespaces="core": the prefixes of the shapes file win over rdflib's defaults in summaries.
        self.shape = Graph(bind_namespaces="core")
        self.shape.parse(self.shape_file)
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
            for text, validation in self._batch_results():
                output.write(text)
                if accumulator is not None:
                    accumulator.add(*validation)
        return accumulator.summary() if accumulator is not None else None

    def _batch_results(self):
        """The results of all batches, in batch order. Only a few batches are held in memory at any time."""
        init_args = (self.shape, self.dictionary, self.seed, self.validate, self.collect_report)
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
