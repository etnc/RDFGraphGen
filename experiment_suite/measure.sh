#!/bin/bash
# This script is used to measure the performance of the RDFGraphGen application
# It measures the time it takes for the RDFGraphGen to execute, under different configurations
# and with different scale factors. The results are saved in a CSV file for later analysis.
# Usage: ./measure.sh input-shacl-file.ttl scale-factor

# create a CSV file to store the results
echo "Size,Time" >> results.csv

# start the timer in milliseconds
start=$(date +%s)
# run RDFGraphGen
# usage: rdfgen [-h] [-b BATCH_SIZE] input_file output_file scale_factor
rdfgen $1 generated-graph.ttl $2
# end the timer
end=$(date +%s)
# calculate the elapsed time in milliseconds
elapsed=$(( end - start ))
# save the results in the CSV file
echo "$2,$elapsed" >> results.csv

echo "Done measuring performance. Results saved in results.csv"
