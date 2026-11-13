import random
from copy import deepcopy
from rdflib import Graph, BNode, Literal

from rdf_graph_gen.shacl_mapping_generator import *
from rdf_graph_gen.value_generators import *

# Counters for the identifiers of generated entities (IRIs) and nested values (blank nodes). They are reset at
# the start of every batch, so identifiers depend only on the batch, not on the process that generates it.
COUNTER = 100
BNODE_COUNTER = 0

# Recursive shapes (e.g. a Person who knows a Person): a shape occurs at most this many times on the path from a
# top-level entity to a generated entity. Beyond that, only the required number of values is generated for such a
# property, using earlier entities of that shape where possible, so that generation always ends.
RECURSION_LIMIT = 3

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


def _partners(shape_dictionary):
    """The other properties whose values a property needs: property pairs and dependencies of the heuristics."""
    pairs = {shape_dictionary.get(p) for p in (SH.equals, SH.disjoint, SH.lessThan, SH.lessThanOrEquals)}
    return {p for p in pairs if p is not None} | set(shape_dictionary.get("depends_on", []))


def _branch_as_node_shape(branch):
    """
    A shape of sh:and, sh:or or sh:xone, to be combined with a node shape: a property shape becomes a property of
    the node. Returns None for a property shape with a complex path, which is not supported yet (the parser warns).
    """
    sh_path = branch.get(SH.path)
    if sh_path is None:
        return branch
    if not isinstance(sh_path, URIRef) and not branch.get("path_steps"):
        return None
    return {"properties": {sh_path: branch}}


def _ends_with_inverse_step(property_dictionary):
    """Whether the values of the property are reached through an inverse step (they are subjects of triples)."""
    steps = property_dictionary.get("path_steps")
    return bool(steps) and steps[-1][1]


def _add_value(result, node, path, property_dictionary, value, batchID):
    """
    Add a value of a property to node, following the steps of its path: through fresh intermediate nodes for a
    sequence path (node ex:a [ ex:b value ]), and in the other direction for an inverse step (value ex:p node).
    """
    global BNODE_COUNTER
    steps = property_dictionary.get("path_steps")
    if not steps:
        result.add((node, path, value))
        return
    if steps[-1][1] and isinstance(value, Literal):
        return  # a literal cannot be the subject of a triple (the parser warns about such shapes)
    current = node
    for index, (predicate, inverse) in enumerate(steps):
        if index == len(steps) - 1:
            target = value
        else:
            target = BNode(f'{batchID}b{BNODE_COUNTER}')
            BNODE_COUNTER += 1
        result.add((target, predicate, current) if inverse else (current, predicate, target))
        current = target


def _values(result, node, path, property_dictionary):
    """The current values of a property of node (the nodes reached through the steps of its path)."""
    nodes = {node}
    for predicate, inverse in property_dictionary.get("path_steps") or [(path, False)]:
        if inverse:
            nodes = {s for n in nodes for s in result.subjects(predicate, n)}
        else:
            nodes = {o for n in nodes for o in result.objects(n, predicate)}
    return nodes


def _number_of_equal_values(property_dictionary, result, node):
    """
    For a property with sh:equals: the number of values of the other property (0 while it has none). The property
    gets at least that many values, since it must have all of them, whatever its own count would have been.
    """
    other = property_dictionary.get(SH.equals)
    return 0 if other is None else len(set(result.objects(node, other)))


def _earlier_entities(ancestors, value_shape, node):
    """
    For a property whose values are entities of value_shape: None if that shape occurs fewer than RECURSION_LIMIT
    times on the path from the top-level entity (new entities are generated as usual); otherwise the earlier
    entities of that shape on the path, nearest first and without the current entity, to be used as values.
    """
    if value_shape is None:
        return None
    earlier = [entity for shape, entity in reversed(ancestors) if shape == value_shape]
    if len(earlier) < RECURSION_LIMIT:
        return None
    return [entity for entity in earlier if entity != node]


def dictionary_to_rdf_graph(shape_dictionary, shape_name, result, parent, dictionary,
                            property_pair_constraint_components_parent, parent_class, batchID, final_attempt=False,
                            ancestors=()):
    # initialization
    property_pair_constraint_components = []
    global COUNTER, BNODE_COUNTER

    if shape_name:
        node = URIRef(f'http://example.org/ns#Node{batchID}_{COUNTER}')
        COUNTER += 1
        # as SH.description add the name of the shape that this node was generated from
        result.add((node, SH.description, shape_name))
    else:
        # deterministic blank node identifiers (rdflib's default ones are random)
        node = BNode(f'{batchID}b{BNODE_COUNTER}')
        BNODE_COUNTER += 1

    # the generated entities on the path from the top-level entity to this one, with their shapes (see _earlier_entities)
    if shape_name:
        ancestors = ancestors + ((shape_name, node),)

    # The entity (or, for a property shape, each value) is an instance of every class given with sh:targetClass and
    # sh:class (all of them must hold). The classes are added to the value that is returned (see typed), which is
    # this node, or e.g. an entity of sh:node or a value of sh:in.
    classes = []
    for parameter in (SH.targetClass, URIRef(SH['class'])):
        classes += [c for c in parameter_values(shape_dictionary, parameter) if c not in classes]
    sh_class = classes[0] if classes else parent_class

    def typed(value):
        if value is not None and not isinstance(value, Literal):
            for c in classes:
                result.add((value, RDF.type, c))
        return value

    # A shape can have several sh:xone, sh:and and sh:or lists, and each of them must hold, so each list is used.
    # (The lists are read from the copy, so that merging never changes the shared shape dictionaries.)

    # if there is a sh:xone for this dict, choose one of the choices and merge it with the existing properties
    if shape_dictionary.get(URIRef(SH['xone'])):
        shape_dictionary = deepcopy(shape_dictionary)
        for sh_xone in parameter_values(shape_dictionary, URIRef(SH['xone'])):
            choice = _branch_as_node_shape(random.choice(sh_xone))
            if choice is not None:
                merge_shape_dictionaries(shape_dictionary, choice)

    # if there is a sh:and for this dict, merge all the choices  with the existing properties
    if shape_dictionary.get(URIRef(SH['and'])):
        shape_dictionary = deepcopy(shape_dictionary)
        for sh_and in parameter_values(shape_dictionary, URIRef(SH['and'])):
            for choice in sh_and:
                choice = _branch_as_node_shape(choice)
                if choice is not None:
                    merge_shape_dictionaries(shape_dictionary, choice)

    # if there is a sh:or for this dict, choose some of the choices and merge it with the existing properties
    if shape_dictionary.get(URIRef(SH['or'])):
        shape_dictionary = deepcopy(shape_dictionary)
        for sh_or in parameter_values(shape_dictionary, URIRef(SH['or'])):
            len_choices = len(sh_or)
            for choice in random.sample(sh_or, random.randint(1, len_choices)):
                choice = _branch_as_node_shape(choice)
                if choice is not None:
                    merge_shape_dictionaries(shape_dictionary, choice)

    # Property pairs (sh:equals, sh:disjoint, sh:lessThan, sh:lessThanOrEquals) and the dependencies of the
    # realistic-value heuristics need the values of another property of the parent. While that property has no
    # values yet, this property is postponed: it is generated after the parent's other properties (see the end
    # of the 'properties' branch below). In its final attempt, it uses the values that exist at that point.

    # get the dependent property for sh:equals: this property must have the same values
    sh_equals = shape_dictionary.get(SH.equals)
    if sh_equals:
        equal_values = list(result.objects(parent, sh_equals))
        if not equal_values:
            if final_attempt:
                return None  # the other property has no values, so this one must not have any either
            property_pair_constraint_components_parent.append(shape_dictionary)
            return None
        # the values of the other property, one by one (see _number_of_equal_values); this takes precedence over
        # the other constraints of this property, which the values must satisfy anyway
        existing = _values(result, parent, shape_dictionary.get(SH.path), shape_dictionary)
        return next((value for value in equal_values if value not in existing), None)

    # get the dependent property for sh:disjoint: this property must not have any of its values
    sh_disjoint = shape_dictionary.get(SH.disjoint)
    if sh_disjoint:
        sh_disjoint = list(result.objects(parent, sh_disjoint))
        if not sh_disjoint and not final_attempt:
            property_pair_constraint_components_parent.append(shape_dictionary)
            return None
    disjoint_values = sh_disjoint or []

    # get the dependent property for sh:lessThan
    sh_less_than = shape_dictionary.get(SH.lessThan)
    if sh_less_than:
        sh_less_than = [o for o in result.objects(parent, sh_less_than)]
        if len(sh_less_than) == 0 and not final_attempt:
            property_pair_constraint_components_parent.append(shape_dictionary)
            return None

    # get the dependent property for sh:lessThanOrEquals
    sh_less_than_or_equals = shape_dictionary.get(SH.lessThanOrEquals)
    if sh_less_than_or_equals:
        sh_less_than_or_equals = [o for o in result.objects(parent, sh_less_than_or_equals)]
        if len(sh_less_than_or_equals) == 0 and not final_attempt:
            property_pair_constraint_components_parent.append(shape_dictionary)
            return None

    # Define dependencies for the dictionary, so the generated result makes sense
    define_dependencies(shape_dictionary)

    dependencies = {}
    depends_on = shape_dictionary.get("depends_on", [])  # [] is to mot check if there are dependencies
    for dep in depends_on:
        val = [o for o in result.objects(parent, dep)]
        if len(val) == 0:
            if final_attempt:
                continue  # generate without this dependency
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
            # sh:hasValue: each of its values must be one of the values (a property can have several)
            has_values = parameter_values(value, SH.hasValue)
            for has_value in has_values:
                _add_value(result, node, key, value, has_value, batchID)
            sh_max_count -= len(has_values)
            
            # decrease sh_max_count because one value is generated. If the new value is lesser than sh_min_count, decrease sh_min_count to sh_max_count 
            if sh_max_count < sh_min_count:
                sh_min_count = sh_max_count
            
            # Recursion: if the values are entities of a shape that already occurs RECURSION_LIMIT times on the path
            # from the top-level entity, generate only the required number of values, using earlier entities of that
            # shape where possible (e.g. a cycle P2 knows P1), so that generation ends
            earlier = _earlier_entities(ancestors, value.get(SH.node), node)
            count = max(sh_min_count, 0) if earlier is not None else random.randint(sh_min_count, sh_max_count)
            count = max(count, _number_of_equal_values(value, result, node))
            for i in range(0, count):
                postponed_before = len(property_pair_constraint_components)
                if earlier:
                    generated_prop = earlier.pop(0)
                else:
                    generated_prop = dictionary_to_rdf_graph(value, None, result, node, dictionary,
                                                             property_pair_constraint_components, sh_class, batchID,
                                                             ancestors=ancestors)
                if generated_prop is not None:
                    _add_value(result, node, key, value, generated_prop, batchID)
                elif len(property_pair_constraint_components) > postponed_before:
                    break  # postponed: all its values are generated later (postpone it once, not once per value)

        # Generate the postponed properties. They are retried as long as some of them can be generated. When none
        # can, the properties they wait for will not get values anymore, so one of them is generated in a final
        # attempt with the values that exist at that point (preferably one that does not wait for another
        # postponed property). This guarantees that generation ends.
        postponed = property_pair_constraint_components
        forced = None
        while postponed:
            still_postponed = []
            for value in postponed:
                sh_min_count = int(value.get(SH.minCount, "1"))
                sh_max_count = int(value.get(SH.maxCount, sh_min_count))
                count = max(random.randint(sh_min_count, sh_max_count), _number_of_equal_values(value, result, node))
                for i in range(0, count):
                    generated_prop = dictionary_to_rdf_graph(value, None, result, node, dictionary, still_postponed,
                                                             sh_class, batchID, final_attempt=value is forced,
                                                             ancestors=ancestors)
                    if generated_prop is None:
                        break
                    _add_value(result, node, value.get(SH.path), value, generated_prop, batchID)
            forced = None
            if len(still_postponed) == len(postponed):  # no progress
                waiting_for = {value.get(SH.path) for value in still_postponed}
                forced = next((value for value in still_postponed if not _partners(value) & waiting_for),
                              still_postponed[0])
            postponed = still_postponed
        return typed(node)

    # if sh:in exists, return a value from it's predefined set. 
    # Check the parent shape so you dont add the same tuple multiple times.
    elif sh_in:
        existing = _values(result, parent, sh_path, shape_dictionary)
        # keep the order of the sh:in list (set order varies between runs, which breaks reproducibility);
        # prefer new values, and never values of the sh:disjoint property if that can be avoided
        candidates = ([value for value in sh_in if value not in existing and value not in disjoint_values]
                      or [value for value in sh_in if value not in disjoint_values] or sh_in)
        if _ends_with_inverse_step(shape_dictionary):
            # values reached through an inverse step are subjects of triples, so they cannot be literals
            candidates = ([value for value in candidates if not isinstance(value, Literal)]
                          or [value for value in sh_in if not isinstance(value, Literal)])
            if not candidates:
                return None
        return typed(random.choice(candidates))

    # if the property is described by a sh:node, generate a node and add it
    elif sh_node:
        n = dictionary.get(sh_node)
        if not n:
            raise Exception("The SHACL shape " + sh_node + " cannot be found!")
        return typed(dictionary_to_rdf_graph(n, sh_node, result, None, dictionary, [], sh_class, batchID,
                                             ancestors=ancestors))

    # The value is the fresh node created above, with the classes of the shape: for an entity of a node shape (e.g.
    # one without properties), for values that must be instances of a class (sh:class), and for values reached
    # through an inverse step (they are subjects of triples, so they cannot be literals)
    if shape_name or classes or _ends_with_inverse_step(shape_dictionary):
        return typed(node)

    # check if a predefined value exists for this iteration
    value = generate_intuitive_value(sh_path, sh_class, dependencies)
    if not value or value in disjoint_values:
        # a generated value based on multiple constarints; values of the sh:disjoint property are excluded in the
        # same way as the values that this property already has
        existing_values = {o.toPython() for o in _values(result, parent, sh_path, shape_dictionary)}
        existing_values |= {o.toPython() for o in disjoint_values}
        value = generate_default_value(existing_values, sh_datatype, sh_min_exclusive, sh_min_inclusive, sh_max_exclusive, sh_max_inclusive,
                                       sh_min_length, sh_max_length, sh_pattern, sh_equals, sh_disjoint, sh_less_than,
                                       sh_less_than_or_equals, sh_path, sh_class)

    # language-tagged strings (sh:datatype rdf:langString, or sh:languageIn): the string gets a language tag; with
    # sh:uniqueLang, one that the other values of the property do not have
    language_in = shape_dictionary.get(SH.languageIn)
    if ((language_in is not None or sh_datatype == RDF.langString) and sh_datatype in (None, RDF.langString)
            and isinstance(value, Literal) and value.datatype is None and value.language is None):
        used_languages = {o.language.lower() for o in _values(result, parent, sh_path, shape_dictionary)
                          if isinstance(o, Literal) and o.language}
        value = add_language_tag(value, used_languages, language_in, bool(shape_dictionary.get(SH.uniqueLang)))
    return value


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
    global COUNTER, BNODE_COUNTER
    COUNTER, BNODE_COUNTER = 100, 0  # identifiers are unique per batch (batchID) and independent of the process

    result_graph = Graph()
    result_graph.bind("schemaorg", SCH)

    # Find independent node shapes in the provided shapes_graph (in a fixed order, for reproducibility)
    independent_node_shapes = sorted(find_independent_node_shapes(shapes_graph), key=str)

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
    return generate_graph(shape_file, number)


def generate_batch(shapes_graph, dictionary, number, batch_index, seed=None):
    """
    Generate one batch: `number` entities per top-level node shape, with identifiers that are unique to the
    batch. With a seed, the batch depends only on (seed, batch_index), not on the process that generates it.
    """
    if seed is not None:
        # The generator (and exrex) use the global random module; seeding with a string is stable across runs
        random.seed(f"{seed}/{batch_index}")
    return generate_rdf_graphs_from_dictionary(shapes_graph, dictionary, number, f'B{batch_index}')


def generate_graph(shapes, scale_factor, seed=None):
    """
    Generate a synthetic RDF graph in memory and return it as an rdflib Graph.

    shapes: an rdflib Graph with SHACL shapes, or the path to a file with SHACL shapes.
    scale_factor: the number of entities generated for each top-level node shape.
    seed: optional; the same seed always produces the same graph. The result is the same as the first batch
          of 'rdfgen ... --seed SEED' with a batch size of at least scale_factor.
    """
    shapes_graph = shapes if isinstance(shapes, Graph) else Graph().parse(shapes)
    dictionary = generate_dictionary_from_shapes_graph(shapes_graph)
    return generate_batch(shapes_graph, dictionary, scale_factor, 1, seed)


def generate_rdf(shape_file, output_file, number, batch_size=1000, seed=None, processes=1):
    """
    Generate a synthetic RDF graph and write it to output_file (Turtle), in batches of batch_size entities.
    With processes > 1, the batches are generated in parallel. The same seed always produces the same file,
    regardless of the number of processes.
    """
    from rdf_graph_gen.multiprocess_generate import MultiprocessGenerator
    MultiprocessGenerator(shape_file, output_file, number, batch_size, processes=processes, seed=seed).generate()
