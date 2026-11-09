"""Allows running the command-line tool from a source checkout: ``python -m rdf_graph_gen ...``."""
import sys

from rdf_graph_gen.script import main

if __name__ == "__main__":
    sys.exit(main())
