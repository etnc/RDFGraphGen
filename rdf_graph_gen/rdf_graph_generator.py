from copy import deepcopy
from rdflib import Graph, BNode

from rdf_graph_gen.shacl_mapping_generator import *
from rdf_graph_gen.value_generators import *

COUNTER = 100

"""
Function Explanation:
---------------------
The 'dictionary_to_rdf_graph' function generates RDF triples based on the specified constraints of a SHACL shape
represented as a dictionary.

Parameters:
-----------
shape_dictionary (dict): A dictionary representing a SHACL shape with constraints and properties.
shape_name (str): Name of the SHACL shape.
result (rdflib.Graph): RDF graph to which the generated triples will be added.
parent (rdflib.BNode or None): Parent node in the RDF graph to which the generated triples will be attached.
dictionary (dict): Dictionary containing other SHACL shapes for reference.
property_pair_constraint_components_parent (list): List of property pair constraint components.
parent_class (rdflib.URIRef): URIRef representing the parent class of the SHACL shape.

Returns:
--------
rdflib.BNode or rdflib.URIRef: The RDF node representing the SHACL shape in the generated graph.
"""


def dictionary_to_rdf_graph(shape_dictionary, shape_name, result, parent, dictionary,
                            property_pair_constraint_components_parent, parent_class, batchID):
    # initialization
    property_pair_constraint_components = []
    node = BNode()

    if shape_name:
        global COUNTER
        node = URIRef(f'http://example.org/ns#Node{batchID}_{COUNTER}')
        COUNTER += 1
        # as SH.description add the name of the shape that this node was generated from
        result.add((node, SH.description, shape_name))

    sh_class = shape_dictionary.get(SH.targetClass, shape_dictionary.get(URIRef(SH['class'])))
    if sh_class:
        result.add((node, RDF.type, sh_class))
    else:
        sh_class = parent_class

    # if there is a sh:xone for this dict, choose one of the choices and merge it with the existing properties
    sh_xone = shape_dictionary.get(URIRef(SH['xone']))
    if sh_xone:
        shape_dictionary = deepcopy(shape_dictionary)
        choice = random.choice(sh_xone)
        sh_path = choice.get(SH.path)
        if sh_path:
            choice = {"properties": {sh_path: choice}}
        update_dictionary(shape_dictionary, choice)

    # if there is a sh:and for this dict, merge all the choices  with the existing properties
    sh_and = shape_dictionary.get(URIRef(SH['and']))
    if sh_and:
        shape_dictionary = deepcopy(shape_dictionary)
        for choice in sh_and:
            sh_path = choice.get(SH.path)
            if sh_path:
                choice = {"properties": {sh_path: choice}}
            update_dictionary(shape_dictionary, choice)

    # if there is a sh:or for this dict, choose some of the choices and merge it with the existing properties
    sh_or = shape_dictionary.get(URIRef(SH['or']))
    if sh_or:
        shape_dictionary = deepcopy(shape_dictionary)
        len_choices = len(sh_or)
        for choice in random.sample(sh_or, random.randint(1, len_choices)):
            sh_path = choice.get(SH.path)
            if sh_path:
                choice = {"properties": {sh_path: choice}}
            update_dictionary(shape_dictionary, choice)

    # get the dependent property for sh:equals
    sh_equals = shape_dictionary.get(SH.equals)
    if sh_equals:
        sh_equals = next(result.objects(parent, sh_equals), None)
        if sh_equals is None:
            property_pair_constraint_components_parent.append(shape_dictionary)
            return None

    # get the dependent property for sh:disjoint
    sh_disjoint = shape_dictionary.get(SH.disjoint)
    if sh_disjoint:
        sh_disjoint = next(result.objects(parent, sh_disjoint), None)
        if not sh_disjoint is None:
            property_pair_constraint_components_parent.append(shape_dictionary)
            return None

    # get the dependent property for sh:lessThan
    sh_less_than = shape_dictionary.get(SH.lessThan)
    if sh_less_than:
        # sh_less_than = next(result.objects(parent, sh_less_than), None)
        sh_less_than = [o for o in result.objects(parent, sh_less_than)]
        if len(sh_less_than) == 0:
            property_pair_constraint_components_parent.append(shape_dictionary)
            return None

    # get the dependent property for sh:lessThanOrEquals
    sh_less_than_or_equals = shape_dictionary.get(SH.lessThanOrEquals)
    if sh_less_than_or_equals:
        sh_less_than_or_equals = [o for o in result.objects(parent, sh_less_than_or_equals)]
        if len(sh_less_than_or_equals) == 0:
            property_pair_constraint_components_parent.append(shape_dictionary)
            return None

    # Define dependencies for the dictionary, so the generated result makes sense
    define_dependencies(shape_dictionary)

    dependencies = {}
    depends_on = shape_dictionary.get("depends_on", [])  # [] is to mot check if there are dependencies
    for dep in depends_on:
        val = [o for o in result.objects(parent, dep)]
        if len(val) == 0:
            property_pair_constraint_components_parent.append(shape_dictionary)
            return None
        dependencies[dep] = val

    # Get the rest of the constraints
    sh_in = shape_dictionary.get(URIRef(SH + "in"))
    sh_datatype = shape_dictionary.get(SH.datatype)
    sh_min_exclusive = shape_dictionary.get(SH.minExclusive)
    sh_min_inclusive = shape_dictionary.get(SH.minInclusive)
    sh_max_exclusive = shape_dictionary.get(SH.maxExclusive)
    sh_max_inclusive = shape_dictionary.get(SH.maxInclusive)
    sh_min_length = shape_dictionary.get(SH.minLength)
    sh_max_length = shape_dictionary.get(SH.maxLength)
    sh_pattern = shape_dictionary.get(SH.pattern)
    sh_node = shape_dictionary.get(SH.node)
    sh_path = shape_dictionary.get(SH.path)

    # get the nested properties
    properties = shape_dictionary.get("properties")
    # for each nested property generate a rdf graph recursively
    if properties:
        for key, value in properties.items():
            
            # the min count of the property that is generated (generate at least 1)
            sh_min_count = int(value.get(SH.minCount, "1"))
            sh_max_count = int(value.get(SH.maxCount, sh_min_count))
            
            # check if property has hasValue, and if it has add one tuple and go on with that property
            sh_has_value = value.get(SH.hasValue)
            if sh_has_value is not None:
                result.add((node, key, sh_has_value))
                sh_max_count -= 1
            
            # decrease sh_max_count because one value is generated. If the new value is lesser than sh_min_count, decrease sh_min_count to sh_max_count 
            if sh_max_count < sh_min_count:
                sh_min_count = sh_max_count
            
            for i in range(0, random.randint(sh_min_count, sh_max_count)):
                generated_prop = dictionary_to_rdf_graph(value, None, result, node, dictionary,
                                                         property_pair_constraint_components, sh_class, batchID)
                if generated_prop is not None:
                    result.add((node, key, generated_prop))

        # generate the properties that weren't generated due to a missing dependency
        while property_pair_constraint_components:
            value = property_pair_constraint_components.pop(0)
            sh_min_count = int(value.get(SH.minCount, "1"))
            sh_max_count = int(value.get(SH.maxCount, sh_min_count))
            for i in range(0, random.randint(sh_min_count, sh_max_count)):
                generated_prop = dictionary_to_rdf_graph(value, None, result, node, dictionary,
                                                         property_pair_constraint_components, sh_class, batchID)
                if generated_prop is not None:
                    result.add((node, value.get(SH.path), generated_prop))
                else:
                    break
        return node

    # if sh:in exists, return a value from it's predefined set. 
    # Check the parent shape so you dont add the same tuple multiple times.
    elif sh_in:
        existing = {o for o in result.objects(parent, sh_path)}
        potential = set(sh_in) - existing
        if len(potential) > 0:
            return random.choice(list(potential))
        return random.choice(sh_in)
    
    # if the property is described by a sh:node, generate a node and add it
    elif sh_node:
        n = dictionary.get(sh_node)
        if not n:
            raise Exception("The SHACL shape " + sh_node + " cannot be found!")
        return dictionary_to_rdf_graph(n, sh_node, result, None, dictionary, [], sh_class, batchID)

    # check if a predefined value exists for this iteration
    predefined_value = generate_intuitive_value(sh_path, sh_class, dependencies)
    if predefined_value:
        return predefined_value

    # return a generated value based on multiple constarints
    existing_values = {o.toPython() for o in result.objects(parent, sh_path)}
    return generate_default_value(existing_values, sh_datatype, sh_min_exclusive, sh_min_inclusive, sh_max_exclusive, sh_max_inclusive,
                                  sh_min_length, sh_max_length, sh_pattern, sh_equals, sh_disjoint, sh_less_than,
                                  sh_less_than_or_equals, sh_path, sh_class)


"""
    Function Explanation:
    ---------------------
    The 'generate_rdf_graph' function generates RDF graphs by processing SHACL shapes from the provided shapes_graph.
    For each independent node shape, it generates the specified number of RDF samples using the 'dictionary_to_rdf_graph'
    function.

    Parameters:
    -----------
    shapes_graph (rdflib.Graph): The RDF Shapes graph containing SHACL shapes and related information.
    dictionary (dict): Dictionary of SHACL shapes.
    number_of_samples (int): The number of RDF samples to generate for each independent node shape.

    Returns:
    --------
    rdflib.Graph: The resulting RDF graph containing generated samples based on SHACL shapes.

    Explanation:
    ------------
    - The function initializes an empty RDF graph ('result_graph') to store the generated triples.
    - It identifies independent node shapes using the 'find_independent_node_shapes' function.
    - For each independent node shape, it iteratively calls the 'dictionary_to_rdf_graph' function to generate
      RDF samples and adds them to 'result_graph'.
    - Finally, it returns the resulting RDF graph containing the generated samples.

    Note: The 'dictionary_to_rdf_graph' function is responsible for generating RDF triples based on SHACL constraints.
"""


def generate_rdf_graphs_from_dictionary(shapes_graph, dictionary, number_of_samples, batchID):
    result_graph = Graph()
    result_graph.bind("schemaorg", SCH)

    # Find independent node shapes in the provided shapes_graph
    independent_node_shapes = find_independent_node_shapes(shapes_graph)

    # Generate RDF samples for each independent node shape
    for key in independent_node_shapes:
        for i in range(0, number_of_samples):
            # Call 'dictionary_to_rdf_graph' to generate RDF triples for the current shape
            dictionary_to_rdf_graph(dictionary[key], key, result_graph, None, dictionary, [], None, batchID)

    return result_graph


"""
    Function Explanation:
    ---------------------
    The 'generate_rdf_graphs_from_shacl_constraints' function streamlines the process of generating RDF graphs based on
    SHACL (Shapes Constraint Language) constraints specified in a given file. It parses the SHACL shapes from the input
    file, converts them into a dictionary representation, and utilizes this dictionary to create RDF graphs conforming to
    the specified constraints.

    Parameters:
    -----------
    shape_file (str): The path to the file containing SHACL shapes.
    number (int): The number of RDF graphs to generate.

    Returns:
    --------
    rdflib.Graph: The resulting RDF graph conforming to the SHACL constraints.

    Explanation:
    ------------
    - The function begins by creating an empty RDF graph ('shape') using the 'rdflib' library and parses the SHACL
      shapes from the given file into this graph.
    - It then calls the helper function 'generate_dictionary_from_shapes_graph' to convert the parsed SHACL shapes
      graph into a dictionary representation. This dictionary encompasses the properties and constraints specified
      in SHACL shapes.
    - The function proceeds to invoke 'generate_rdf_graph', passing the parsed SHACL shapes graph, the generated
      dictionary, and the specified number of samples. This function creates RDF graphs conforming to the SHACL
      constraints.
    - Finally, the function returns the resulting RDF graph, providing easy access to a representation of RDF data
      structures compliant with the specified SHACL constraints.
"""


def generate_rdf_graphs_from_shacl_constraints(shape_file, number):
    # Create an empty RDF graph
    shape = Graph()
    # Parse SHACL shapes from the input file into the graph
    shape.parse(shape_file)
    # Convert parsed SHACL shapes graph into a dictionary representation
    dictionary = generate_dictionary_from_shapes_graph(shape)
    # Generate RDF graphs conforming to SHACL constraints
    graph = generate_rdf_graphs_from_dictionary(shape, dictionary, number, 'B1')
    # Return the resulting RDF graph
    return graph


def generate_rdf(shape_file, output_file, number, batch_size):
    shape = Graph()
    shape.parse(shape_file)
    dictionary = generate_dictionary_from_shapes_graph(shape)
    
    # implement generating and writing down of the graphs in batches
    with open(output_file, "a") as ttl_file:
        while number > 0:
            
            batch_number = min(number, batch_size)
            graph = generate_rdf_graphs_from_dictionary(shape, dictionary, batch_number, 'B1')
            text_graph = graph.serialize(format = 'ttl')
            ttl_file.write(text_graph)
            
            number -= batch_size
            
        ttl_file.flush()
        ttl_file.close()
