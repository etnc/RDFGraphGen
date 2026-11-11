import warnings

from rdflib import SH, RDF, BNode, URIRef, Namespace, Literal

SCH = Namespace("http://schema.org/")

# Parameters that a shape can have at most one value for (SHACL syntax rules, as in the W3C SHACL-SHACL shapes).
# Other parameters, such as sh:class, sh:node, sh:hasValue, sh:not, sh:and, sh:or and sh:xone, can have several
# values in one shape, and each value is a separate constraint that must hold.
SINGLE_VALUED_PARAMETERS = {
    SH.path, SH.datatype, SH.nodeKind, SH.minCount, SH.maxCount, SH.minInclusive, SH.minExclusive, SH.maxInclusive,
    SH.maxExclusive, SH.minLength, SH.maxLength, SH.pattern, SH.flags, SH.languageIn, SH.uniqueLang, URIRef(SH['in']),
    SH.closed, SH.ignoredProperties, SH.qualifiedValueShape, SH.qualifiedMinCount, SH.qualifiedMaxCount,
    SH.qualifiedValueShapesDisjoint, SH.deactivated, SH.severity,
}


def add_parameter_value(shape_dictionary, parameter, value):
    """
    Record a value of a constraint parameter in a shape dictionary. shape_dictionary[parameter] is the first
    value; all values are kept in shape_dictionary["values"][parameter], in the order in which they are read.
    """
    values = shape_dictionary.setdefault("values", {}).setdefault(parameter, [])
    values.append(value)
    if len(values) == 1:
        shape_dictionary[parameter] = value
    elif parameter in SINGLE_VALUED_PARAMETERS:
        warnings.warn(f"{parameter} has several values in one shape, which SHACL does not allow; using the first "
                      f"one ({values[0]}).", stacklevel=2)


def path_to_text(path, shapes_graph):
    """A SHACL property path in SPARQL property path notation, e.g. ex:a/ex:b, ^ex:p, (ex:a|ex:b) or ex:p*."""
    if isinstance(path, URIRef):
        return path.n3(shapes_graph.namespace_manager)

    def inner(p):
        text = path_to_text(p, shapes_graph)
        return text if isinstance(p, URIRef) else f"({text})"

    if (path, RDF.first, None) in shapes_graph:  # sequence path: an RDF list of paths
        return "/".join(inner(p) for p in get_list_from_shacl_list(path, shapes_graph))
    alternatives = shapes_graph.value(path, SH.alternativePath)
    if alternatives is not None:
        return "|".join(inner(p) for p in get_list_from_shacl_list(alternatives, shapes_graph))
    for predicate, template in ((SH.inversePath, "^{}"), (SH.zeroOrMorePath, "{}*"), (SH.oneOrMorePath, "{}+"),
                                (SH.zeroOrOnePath, "{}?")):
        argument = shapes_graph.value(path, predicate)
        if argument is not None:
            return template.format(inner(argument))
    return str(path)


def path_steps(path, shapes_graph):
    """
    The steps of a property path as a list of (predicate, inverse) pairs, e.g. ( ex:a [ sh:inversePath ex:b ] )
    gives [(ex:a, False), (ex:b, True)]. Supported: predicates, sequence paths and inverse paths, also nested.
    Returns None for other paths (alternative, zero-or-more, one-or-more and zero-or-one paths).
    """
    if isinstance(path, URIRef):
        return [(path, False)]
    if (path, RDF.first, None) in shapes_graph:  # sequence path
        steps = []
        for element in get_list_from_shacl_list(path, shapes_graph):
            element_steps = path_steps(element, shapes_graph)
            if element_steps is None:
                return None
            steps += element_steps
        return steps
    inverse = shapes_graph.value(path, SH.inversePath)
    if inverse is not None:  # the steps of the inverted path in reverse order, each in the other direction
        inverse_steps = path_steps(inverse, shapes_graph)
        return None if inverse_steps is None else [(p, not backwards) for p, backwards in reversed(inverse_steps)]
    return None


def warn_if_literal_values_are_required(property_dictionary, shapes_graph):
    """
    The values of a path that ends with an inverse step are the subjects of triples, so they cannot be literals:
    warn if a property shape requires literal values for such a path, as that cannot be satisfied.
    """
    steps = property_dictionary.get("path_steps")
    if not steps or not steps[-1][1]:
        return
    in_values = property_dictionary.get(URIRef(SH['in']))
    if (property_dictionary.get(SH.datatype) is not None or property_dictionary.get(SH.nodeKind) == SH.Literal
            or any(isinstance(v, Literal) for v in parameter_values(property_dictionary, SH.hasValue))
            or (in_values and all(isinstance(v, Literal) for v in in_values))):
        warnings.warn(f"The values of the property path {path_to_text(property_dictionary[SH.path], shapes_graph)} "
                      f"are the subjects of triples (the path ends with an inverse step), so they cannot be literals; "
                      f"its constraints that require literal values cannot be satisfied.", stacklevel=2)


def warn_unsupported_path(path, shapes_graph):
    warnings.warn(f"The property path {path_to_text(path, shapes_graph)} is not supported yet (only predicate paths "
                  f"are); the property is not generated.", stacklevel=2)


def parameter_values(shape_dictionary, parameter):
    """All values of a constraint parameter in a shape dictionary (an empty list if it has none)."""
    values = shape_dictionary.get("values", {}).get(parameter)
    if values:
        return list(values)
    return [shape_dictionary[parameter]] if shape_dictionary.get(parameter) is not None else []


# Bounds: when two shapes that must both hold are combined, the strictest value applies
LOWER_BOUND_PARAMETERS = (SH.minCount, SH.minLength, SH.minInclusive, SH.minExclusive)
UPPER_BOUND_PARAMETERS = (SH.maxCount, SH.maxLength, SH.maxInclusive, SH.maxExclusive)


def _strictest(current, value, lower_bound):
    try:
        if (value > current) if lower_bound else (value < current):
            return value
    except TypeError:  # values that cannot be compared
        pass
    return current


def merge_shape_dictionaries(target, source):
    """
    Merge the shape dictionary `source` into `target` (in place) as a conjunction: the result requires everything
    that each of them requires. This is used for property shapes with the same path (each property shape is a
    separate constraint, so all of them must hold), and for the shapes of sh:and, sh:or and sh:xone that are
    combined with a shape during generation.
    - bounds (counts, lengths, value ranges): the strictest value
    - sh:in: the values that are in both lists
    - nested property shapes ("properties"): merged per path, in the same way
    - all values of every parameter are kept ("values"), e.g. all classes and all sh:hasValue values
    - any other parameter: the value of `target` is kept, if it has one (if the values differ, they cannot both
      hold anyway)
    """
    for key, value in source.items():
        if key == "properties":
            properties = target.setdefault("properties", {})
            for path, property_dictionary in value.items():
                if path in properties:
                    merge_shape_dictionaries(properties[path], property_dictionary)
                else:
                    properties[path] = property_dictionary
        elif key in ("values", "depends_on"):
            if key == "values":
                merged = target.setdefault("values", {})
                for parameter, values in value.items():
                    kept = merged.setdefault(parameter, [])
                    kept.extend(v for v in values if v not in kept)
            else:
                kept = target.setdefault("depends_on", [])
                kept.extend(v for v in value if v not in kept)
        elif target.get(key) is None:
            target[key] = value
        elif key in LOWER_BOUND_PARAMETERS or key in UPPER_BOUND_PARAMETERS:
            target[key] = _strictest(target[key], value, lower_bound=key in LOWER_BOUND_PARAMETERS)
        elif key == URIRef(SH['in']):
            target[key] = [v for v in target[key] if v in value]  # the values that both lists allow
"""
Function Explanation:
---------------------
The `update_dictionary` function facilitates the merging of two dictionaries, `dict1` and `dict2`. It iterates through
the key-value pairs of `dict2` and updates the values in `dict1`. In cases where a key already exists in `dict1` and
corresponds to a dictionary, the function recursively extends the update to nested dictionaries.

Parameters:
-----------
dict1 (dict): The primary dictionary to be updated.
dict2 (dict): The secondary dictionary containing values for the update.

Returns:
--------
None

Example:
--------
update_dictionary({'a': 1, 'b': {'c': 2}}, {'b': {'d': 3}})
# Result: {'a': 1, 'b': {'c': 2, 'd': 3}}
"""


def update_dictionary(dict1, dict2):
    # Iterate through keys and values in dict2
    for key2, value2 in dict2.items():
        # Get the corresponding value from dict1 for the current key
        value1 = dict1.get(key2)

        # Check if value1 is a dictionary
        if type(value1) == dict:
            # If it's a dictionary, recursively call update_dictionary
            update_dictionary(value1, value2)
        else:
            # If it's not a dictionary, update the value in dict1 with the value from dict2
            dict1[key2] = value2


"""
Function Explanation:
---------------------
The `find_node_shapes` function identifies and returns the unique SHACL Node Shapes present in a given RDF Shapes graph.

Parameters:
-----------
shapes_graph (rdflib.Graph): The RDF Shapes graph to analyze.

Returns:
--------
set: A set containing the unique SHACL Node Shapes identified in the given RDF Shapes graph.

Example:
--------
# Assuming SHACL Node Shapes are represented in the graph
shapes_graph = ...  # Some RDF Shapes graph
node_shapes = find_node_shapes(shapes_graph)
# Result: A set of unique SHACL Node Shapes in the RDF Shapes graph.
"""


def find_node_shapes(shapes_graph):
    # Use RDFlib to identify unique SHACL Node Shapes
    node_shapes = {s for s in shapes_graph.subjects(RDF.type, SH.NodeShape)}
    return node_shapes


# The parameters whose values are shapes that another shape uses, either for its property shapes or for the values of a
# property (sh:node, sh:qualifiedValueShape), or for the shape itself (sh:not, and the lists of sh:and, sh:or, sh:xone)
SHAPE_PARAMETERS = (SH.property, SH.node, SH.qualifiedValueShape, SH["not"])
SHAPE_LIST_PARAMETERS = (SH["and"], SH["or"], SH["xone"])


def _owner(node, shapes_graph):
    """The shape that a blank node (e.g. a property shape, or a shape in an sh:or list) is part of."""
    seen = set()
    while isinstance(node, BNode) and node not in seen:
        seen.add(node)
        parent = next(shapes_graph.subjects(None, node), None)
        if parent is None:
            break
        node = parent
    return node


def shape_uses(shapes_graph):
    """
    Map each shape to the shapes it uses: the shapes given (by name) as values of sh:property, sh:node,
    sh:qualifiedValueShape or sh:not, or in the lists of sh:and, sh:or and sh:xone, in the shape or in any of its
    blank-node parts (its property shapes, the shapes in its lists, ...).
    """
    uses = {}
    for parameter in SHAPE_PARAMETERS:
        for subject, shape in shapes_graph.subject_objects(parameter):
            uses.setdefault(_owner(subject, shapes_graph), set()).add(shape)
    for parameter in SHAPE_LIST_PARAMETERS:
        for subject, shape_list in shapes_graph.subject_objects(parameter):
            uses.setdefault(_owner(subject, shapes_graph), set()).update(shapes_graph.items(shape_list))
    return uses


def _reachable(shape, uses):
    """The shapes that a shape uses, directly or through other shapes."""
    reached, stack = set(), [shape]
    while stack:
        for used in uses.get(stack.pop(), ()):
            if used not in reached:
                reached.add(used)
                stack.append(used)
    return reached


"""
Function Explanation:
---------------------
The `find_independent_node_shapes` function returns the top-level SHACL Node Shapes of an RDF Shapes graph: the node
shapes for which entities are generated directly. The entities of the other node shapes are generated as part of the
entities of the shapes that use them (e.g. as the values of a property with sh:node).

A node shape is top-level if no other shape uses it. A shape that only uses itself (e.g. a person who knows other
persons) is top-level. Shapes that use each other in a cycle that no top-level shape uses (e.g. A uses B, and B uses A)
would have no entities, so one shape of each such cycle (the first one, in IRI order) is top-level too.

Parameters:
-----------
shapes_graph (rdflib.Graph): The RDF Shapes graph to analyze.

Returns:
--------
set: The top-level SHACL Node Shapes in the given RDF Shapes graph.
"""


def find_independent_node_shapes(shapes_graph):
    node_shapes = find_node_shapes(shapes_graph)
    uses = shape_uses(shapes_graph)

    # the node shapes that another shape uses (a shape that uses itself does not count)
    used = {shape for owner, shapes in uses.items() for shape in shapes if shape != owner}
    top_level = node_shapes - used

    reached = set(top_level)
    for shape in top_level:
        reached |= _reachable(shape, uses)
    unreached = sorted(node_shapes - reached, key=str)
    while unreached:
        # start from a shape that no other unreached shape uses (the first shape of a cycle), so that all shapes of
        # the cycle, and the shapes they use, are generated as its parts
        shape = unreached[0]
        while True:
            upstream = [s for s in unreached if shape in _reachable(s, uses) and s not in _reachable(shape, uses)]
            if not upstream:
                break
            shape = upstream[0]
        top_level.add(shape)
        reached |= {shape} | _reachable(shape, uses)
        unreached = [s for s in unreached if s not in reached]
    return top_level


# given a rdf list, it returns a python list containing the items in the RDF list.
"""
Function Explanation:
---------------------
The function 'get_list_from_shacl_list' extracts a list from a SHACL list in an RDF Shapes graph, starting from a given node.

Parameters:
-----------
start (rdflib.term.Identifier): The starting node of the SHACL list.
shapes_graph (rdflib.Graph): The RDF Shapes graph containing the SHACL list.

Returns:
--------
list: A Python list containing the elements of the SHACL list.
"""


def get_list_from_shacl_list(start, shapes_graph):
    # Initialize an empty list to store SHACL list elements
    _list = []

    # Get the value of the first element in the SHACL list
    first = next(shapes_graph.objects(start, RDF.first))
    _list.append(first)

    # Get the value of the rest of the list
    rest = next(shapes_graph.objects(start, RDF.rest))

    # Check if the rest is RDF.nil, indicating the end of the list
    if rest == RDF.nil:
        return _list
    else:
        # If the rest is not RDF.nil, recursively call the function with the rest as the new starting node
        # Append the result to the current list
        return _list + get_list_from_shacl_list(rest, shapes_graph)


"""
Function Explanation:
---------------------
The function 'get_dict_list_from_shacl_list' extracts a list of dictionaries from a SHACL list in an RDF Shapes graph, starting from a given node.

Parameters:
-----------
start (rdflib.term.Identifier): The starting node of the SHACL list.
shapes_graph (rdflib.Graph): The RDF Shapes graph containing the SHACL list.
property_pair_constraint_components (list): List of property pair constraint components.

Returns:
--------
list: A Python list containing dictionaries converted from SHACL shapes in the list.
"""


def get_dict_list_from_shacl_list(start, shapes_graph, property_pair_constraint_components):
    # Initialize an empty list to store dictionaries converted from SHACL shapes
    items = []

    # Get the value of the first element in the SHACL list
    first = next(shapes_graph.objects(start, RDF.first))

    # Convert the SHACL shape to a dictionary and append it to the list
    items.append(shape_to_dictionary(first, shapes_graph, property_pair_constraint_components))

    # Get the value of the rest of the list
    rest = next(shapes_graph.objects(start, RDF.rest))

    # Check if the rest is RDF.nil, indicating the end of the list
    if rest == RDF.nil:
        return items
    else:
        # If the rest is not RDF.nil, recursively call the function with the rest as the new starting node
        # Append the result to the current list
        return items + get_dict_list_from_shacl_list(rest, shapes_graph, property_pair_constraint_components)


"""
Function Explanation:
---------------------
The 'shape_to_dictionary' function converts a SHACL shape into a dictionary representation, capturing its properties and 
constraints. It recursively processes nested shapes, property paths, and other SHACL constructs.

Parameters:
-----------
shape (rdflib.term.Identifier): The SHACL shape to be converted into a dictionary.
shapes_graph (rdflib.Graph): The RDF Shapes graph containing the SHACL shape and related information.
property_pair_constraint_components_parent (list): List of property pair constraint components from the parent shape.

Returns:
--------
dict: A Python dictionary representing the converted SHACL shape.

Explanation:
------------
- The function begins by retrieving all triples associated with the given SHACL shape from the RDF Shapes graph.
- It initializes several old_shapes structures to store property information, dictionaries, and the final shape dictionary.

# Handling SHACL Properties and Nested Constructs
- The function iterates through the triples, handling different cases for SHACL properties, paths, and nested constructs.
- For properties represented by SH:path, SH:in, SH:or, SH:and, SH:xone, and SH:not, the function recursively calls itself or other specific functions.
- The resulting dictionaries and values are added to the shape dictionary.

# Special Handling for Property Pair Constraint Components
- Special handling is performed for Property Pair Constraint Components, ensuring proper dependencies and constraints are captured.
- This includes checking for SH:equals, SH:disjoint, SH:lessThan, SH:lessThanOrEquals constraints and updating the shape dictionary accordingly.

# Finalization and Return
- The function returns the final shape dictionary, representing the SHACL shape in a structured Python format.

Note: The function utilizes other helper functions such as 'get_list_from_shacl_list' and 'get_dict_list_from_shacl_list'.
"""


def shape_to_dictionary(shape, shapes_graph, property_pair_constraint_components_parent):
    # Get all triples related to the SHACL shape
    triples = shapes_graph.triples((shape, None, None))

    # Initialize old_shapes structures
    property_pair_constraint_components = []
    sh_properties = {}
    shape_dictionary = {}

    # Iterate through triples and process SHACL properties and constructs
    for s, p, o in triples:
        if p == SH.property:
            # Handle SH:path property and nested shapes
            property_path = next(shapes_graph.objects(o, SH.path))
            if not isinstance(property_path, URIRef) and path_steps(property_path, shapes_graph) is None:
                # a complex property path other than sequence and inverse paths (e.g. an alternative path): not
                # supported yet, so the property is skipped (writing the path as a predicate would be invalid RDF)
                warn_unsupported_path(property_path, shapes_graph)
                continue

            # Retrieve or initialize property dictionary for the current property path
            property_dict = sh_properties.get(property_path, {})

            # Recursively call the function to process nested shapes within the property
            new_prop_dict = shape_to_dictionary(o, shapes_graph, property_pair_constraint_components)

            # Update the existing property dictionary with the new old_shapes
            # several property shapes with the same path must all hold
            merge_shape_dictionaries(property_dict, new_prop_dict)

            # Update the sh_properties dictionary with the updated property dictionary
            sh_properties[property_path] = property_dict

        elif p == URIRef(SH['in']):
            # Handle SH:in property
            add_parameter_value(shape_dictionary, p, get_list_from_shacl_list(o, shapes_graph))

        elif p in {URIRef(SH['or']), URIRef(SH['and']), URIRef(SH['xone'])}:
            # Handle SH:or, SH:and, SH:xone properties: their value is an RDF list of shapes (a shape can have
            # several such lists, and each must hold)
            add_parameter_value(shape_dictionary, p, get_dict_list_from_shacl_list(
                o, shapes_graph, property_pair_constraint_components_parent))

        elif p == URIRef(SH['not']):
            # Handle SH:not: its value is a single shape (not a list), and a shape can have several sh:not.
            # The negated shape is parsed in isolation (its property pairs must not affect this shape).
            shape_dictionary.setdefault(p, []).append(shape_to_dictionary(o, shapes_graph, []))

        else:
            # Handle other SHACL properties
            if p == SH.lessThan or p == SH.lessThanOrEquals or p == SH.equals or p == SH.disjoint:
                # Add the current shape_dictionary to the list of property pair constraint components
                property_pair_constraint_components_parent.append(shape_dictionary)

            if p == SH.path and not isinstance(o, URIRef):
                steps = path_steps(o, shapes_graph)
                if steps is not None:
                    # a sequence or inverse path: its values are reached through these steps, one by one
                    shape_dictionary["path_steps"] = steps
                else:
                    # a property shape used in sh:and, sh:or or sh:xone with an unsupported path (see above)
                    warn_unsupported_path(o, shapes_graph)

            # a parameter can have several values (e.g. sh:class ex:A, ex:B), which must all hold
            add_parameter_value(shape_dictionary, p, o)

    # Add properties dictionary only if the node has properties
    if bool(sh_properties):
        shape_dictionary["properties"] = sh_properties

    # Fix dependencies caused by Property Pair Constraint Components
    for d in property_pair_constraint_components:
        # Handle SH:equals, SH:disjoint, SH:lessThan, SH:lessThanOrEquals constraints
        equals = d.get(SH.equals)
        disjoint = d.get(SH.disjoint)
        less_than = d.get(SH.lessThan)
        less_than_or_equals = d.get(SH.lessThanOrEquals)

        # Additional handling for constraints
        # Make sure the other property of the pair is generated; if the shape declares it, keep its constraints
        if equals and not sh_properties.get(equals):
            sh_properties[equals] = {SH.path: equals}
        if disjoint and not sh_properties.get(disjoint):
            sh_properties[disjoint] = {SH.path: disjoint}
        if less_than and not sh_properties.get(less_than):
            less_than_dict = sh_properties.get(less_than, {})
            less_than_dict[SH.path] = less_than
            if not less_than_dict.get(SH.datatype) and d.get(SH.datatype):
                less_than_dict[SH.datatype] = d.get(SH.datatype)
            sh_properties[less_than] = less_than_dict
            min_constraint = d.get(SH.minInclusive, d.get(SH.minExclusive))
            if min_constraint:
                less_than_dict[SH.minInclusive] = min_constraint
        if less_than_or_equals and not sh_properties.get(less_than_or_equals):
            less_than_or_equals_dict = sh_properties.get(less_than_or_equals, {})
            less_than_or_equals_dict[SH.path] = less_than_or_equals
            if not less_than_or_equals_dict.get(SH.datatype) and d.get(SH.datatype):
                less_than_or_equals_dict[SH.datatype] = d.get(SH.datatype)
            sh_properties[less_than_or_equals] = less_than_or_equals_dict
            min_constraint = d.get(SH.minInclusive, d.get(SH.minExclusive))
            if min_constraint:
                less_than_or_equals_dict[SH.minInclusive] = min_constraint

    warn_if_literal_values_are_required(shape_dictionary, shapes_graph)
    return shape_dictionary


"""
Function Explanation:
---------------------
The 'define_dependencies' function establishes dependencies between properties within a SHACL shape based on the 
specified target class. It specifically addresses the 'Person' class, examining properties such as 'gender', 
'givenName', 'familyName', 'name', and 'email', and updates the 'depends_on' list accordingly.

Parameters:
-----------
dictionary (dict): A dictionary representing a SHACL shape.
    - SH.targetClass (rdflib.term.Identifier): The target class of the SHACL shape.
    - "properties" (dict): Dictionary containing properties of the SHACL shape.

Returns:
--------
None: The function modifies the input dictionary in place.

Explanation:
------------
- The function begins by retrieving the target class and properties dictionary from the input SHACL shape dictionary.
- It then extracts the last segment of the target class URI as a string for further processing.

# Handling Dependencies for 'Person' Class Properties
- The function checks if the target class is 'Person' and proceeds to handle dependencies for specific properties.
- Dependencies are established between 'givenName' and 'gender' and between 'name' and 'gender'.
- Additionally, dependencies are considered for 'email' based on other properties such as 'givenName' and 'familyName'.

# Modifying 'depends_on' Lists
- The function updates the 'depends_on' lists for relevant properties to reflect the established dependencies.

Note: This function assumes the presence of certain SHACL properties ('gender', 'givenName', 'familyName', 'name', 
'email') and may need adaptation for other contexts.
"""


def define_dependencies(dictionary):
    # Retrieve the class of the generated entities (sh:targetClass, or sh:class as for shapes used via sh:node,
    # the same way the generator assigns rdf:type) and the properties from the SHACL shape dictionary
    t_class = dictionary.get(SH.targetClass, dictionary.get(SH['class']))
    properties = dictionary.get("properties")

    # This function is called for every generated entity, on shape dictionaries that are shared between
    # entities, so it must be idempotent: dependencies are added only once (see _add_dependency).
    if t_class and properties:

        # Check if the target class is 'Person'
        if t_class == SCH.Person:
            # Define URIs for specific properties
            gender = URIRef(SCH.gender)
            given_name = URIRef(SCH.givenName)
            family_name = URIRef(SCH.familyName)
            name = URIRef(SCH.name)
            email = URIRef(SCH.email)

            # Retrieve dictionaries for each property
            gender_dict = properties.get(gender)
            given_name_dict = properties.get(given_name)
            family_name_dict = properties.get(family_name)
            name_dict = properties.get(name)
            email_dict = properties.get(email)

            # Check and establish dependencies for 'givenName' and 'gender'
            if gender_dict and given_name_dict:
                _add_dependency(given_name_dict, gender)

            # Check and establish dependencies for 'name' and 'gender'
            if gender_dict and name_dict:
                _add_dependency(name_dict, gender)

            # Check and establish dependencies for 'email' based on other properties
            if email_dict:
                # Check for 'givenName' and 'familyName' dependencies
                if given_name_dict and family_name_dict:
                    _add_dependency(email_dict, given_name)
                    _add_dependency(email_dict, family_name)
                # Check for 'name' dependency
                elif name_dict:
                    _add_dependency(email_dict, name)
                # Check for 'givenName' dependency
                elif given_name_dict:
                    _add_dependency(email_dict, given_name)


def _add_dependency(property_dict, dependency):
    dependency_list = property_dict.setdefault('depends_on', [])
    if dependency not in dependency_list:
        dependency_list.append(dependency)


"""
Function Explanation:
---------------------
The 'generate_dictionary_from_shapes_graph' function creates a dictionary representation of SHACL shapes within an RDF Shapes graph. It utilizes the 'find_node_shapes' function to identify node shapes, and the 'shape_to_dictionary' function to convert each shape into a dictionary format.

Parameters:
-----------
shapes_graph (rdflib.Graph): The RDF Shapes graph containing SHACL shapes.

Returns:
--------
dict: A Python dictionary representing SHACL shapes and their properties.

Explanation:
------------
- The function begins by identifying all node shapes in the RDF Shapes graph using the 'find_node_shapes' function.
- It initializes an empty dictionary to store the converted shapes.
- For each node shape found, the 'shape_to_dictionary' function is called to convert the shape into a dictionary.
- The resulting dictionary is added to the main dictionary with the node shape URI as the key.

# Note:
- The function currently calls the 'define_dependencies' function to establish dependencies for each shape. However, this line is commented out, as it may require adaptation based on specific use cases or constraints.

Note: This function assumes the presence of the 'find_node_shapes' and 'shape_to_dictionary' functions.
"""


def generate_dictionary_from_shapes_graph(shapes_graph):
    # Identify all node shapes in the RDF Shapes graph
    node_shapes = find_node_shapes(shapes_graph)

    # Initialize an empty dictionary to store converted shapes
    dictionary = {}

    # Process each node shape and convert it into a dictionary
    for n in node_shapes:
        # Convert the shape into a dictionary
        d = shape_to_dictionary(n, shapes_graph, [])

        # Add the dictionary to the main dictionary with the node shape URI as the key
        dictionary[n] = d

    return dictionary
