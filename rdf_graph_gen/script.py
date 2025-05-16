import argparse
from rdf_graph_gen.multiprocess_generate import MultiprocessGenerator


def main():
    parser = argparse.ArgumentParser(prog='RDFGraphGen', 
                                     description="A tool for generating synthetic RDF graphs based on input SHACL shapes.",
                                     epilog='For more information, visit the GitHub repository: https://github.com/etnc/RDFGraphGen.')
    parser.add_argument("input_file", help="Path to the input file with SHACL shapes")
    parser.add_argument("output_file", help="Path to the output file where the generated RDF graph will be saved",
                        default="output-graph.ttl")
    parser.add_argument("scale_factor", help="Controls the size of the generated RDF graph",
                        default=1)
    parser.add_argument("-b", "--batch_size", 
                        help="After this number of entities if generated, they are appended to the file with the main generated RDF graph", 
                        default=1000)

    args = parser.parse_args()
    
    generator = MultiprocessGenerator(args.input_file, args.output_file, int(args.scale_factor), int(args.batch_size))
    generator.generate()


if __name__ == "__main__":
    main()