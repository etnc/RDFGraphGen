#!/bin/bash
# This script is used to measure the performance of the RDFGraphGen application.
# It measures the time (in seconds) it takes RDFGraphGen to generate a graph from SHACL shapes at a scale factor, and
# appends the result to results.csv for later analysis. The generated graph is written to generated-graph.ttl; its
# header records how it was generated (versions, seed, options).
#
# Usage: ./measure.sh input-shacl-file.ttl scale-factor [rdfgen options]
# e.g.:  ./measure.sh shape-three-complex.ttl 10000 --seed 1 --processes 4
# (see 'rdfgen --help' for the options)

set -euo pipefail

if [ $# -lt 2 ]; then
    echo "Usage: $0 input-shacl-file.ttl scale-factor [rdfgen options]" >&2
    exit 2
fi
shapes=$1
scale_factor=$2
shift 2

# create the CSV file to store the results, with its header (once)
if [ ! -f results.csv ]; then
    echo "Size,Time" > results.csv
fi

# run RDFGraphGen and measure the elapsed time in seconds (a failed run is not recorded)
start=$(date +%s)
rdfgen "$shapes" generated-graph.ttl "$scale_factor" "$@"
end=$(date +%s)
elapsed=$(( end - start ))

# save the result in the CSV file
echo "$scale_factor,$elapsed" >> results.csv

echo "Done measuring performance. Results saved in results.csv"
