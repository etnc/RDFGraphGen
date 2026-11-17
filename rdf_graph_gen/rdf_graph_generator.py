import random
import re
import warnings
from copy import deepcopy
from rdflib import Graph, BNode, Literal

from rdf_graph_gen.shacl_mapping_generator import *
from rdf_graph_gen.value_generators import *
from rdf_graph_gen.checker import conforms, exactly_one_holds, has_node_kind, value_conforms

# Counters for the identifiers of generated entities (IRIs) and nested values (blank nodes). They are reset at
# the start of every batch, so identifiers depend only on the batch, not on the process that generates it.
COUNTER = 100
BNODE_COUNTER = 0

# Recursive shapes (e.g. a Person who knows a Person): a shape occurs at most this many times on the path from a
# top-level entity to a generated entity. Beyond that, only the required number of values is generated for such a
# property, using earlier entities of that shape where possible, so that generation always ends.
RECURSION_LIMIT = 3

# The number of realistic values (e.g. names from the name lists) that are tried for a value, before a value is
# generated from the constraints of the property instead
REALISTIC_VALUE_ATTEMPTS = 10

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
            target = _blank_node(batchID, BNODE_COUNTER)
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


# sh:nodeKind values that do not allow literals
NON_LITERAL_NODE_KINDS = {SH.IRI, SH.BlankNode, SH.BlankNodeOrIRI}


def _without_node(shape_dictionary):
    shape_dictionary.pop(SH.node, None)
    shape_dictionary.get("values", {}).pop(SH.node, None)


def _with_node_shapes(shape_dictionary, dictionary):
    """
    sh:node on a node shape (e.g. ex:S sh:node ex:T): the entities of the shape must conform to the shapes of sh:node
    as well, so these are combined with it, like the shapes of sh:and (their own sh:node shapes in turn, each once).
    Returns a combined copy without sh:node. (On a property shape, sh:node describes the values instead: they are
    entities of the shapes of sh:node, see dictionary_to_rdf_graph.)
    """
    names = parameter_values(shape_dictionary, SH.node)
    if shape_dictionary.get(SH.path) is not None or not names:
        return shape_dictionary
    combined = deepcopy(shape_dictionary)
    _without_node(combined)
    seen = set()
    while names:
        name = names.pop(0)
        if name in seen:
            continue
        seen.add(name)
        if dictionary.get(name) is None:
            raise Exception("The SHACL shape " + name + " cannot be found!")
        other = deepcopy(dictionary[name])
        names += parameter_values(other, SH.node)
        _without_node(other)
        merge_shape_dictionaries(combined, other)
    return combined


def _classes(shape_dictionary):
    """The classes of a shape's entities (or of a property shape's values): sh:targetClass and sh:class."""
    classes = []
    for parameter in (SH.targetClass, URIRef(SH['class'])):
        classes += [c for c in parameter_values(shape_dictionary, parameter) if c not in classes]
    return classes


# The shapes that target each class (sh:targetClass), per shapes dictionary (it is the same one for a whole run)
_TARGETING_SHAPES = {}


def _targeting_shapes(dictionary):
    if id(dictionary) not in _TARGETING_SHAPES:
        _TARGETING_SHAPES.clear()
        targeting = _TARGETING_SHAPES.setdefault(id(dictionary), {})
        for name in sorted(dictionary, key=str):
            for target_class in parameter_values(dictionary[name], SH.targetClass):
                targeting.setdefault(target_class, []).append(name)
    return _TARGETING_SHAPES[id(dictionary)]


def _with_class_shapes(shape_dictionary, dictionary, shape_name):
    """
    Every instance of a class must conform to all shapes that target the class (sh:targetClass), whichever shape it
    is generated from: e.g. the entities of another shape with the same target class, or the values of a property with
    sh:class. So these shapes are combined with the shape (also for the classes that they add in turn, each shape
    once). Returns the shape (a combined copy, if shapes were added) and the names of the added shapes.
    """
    targeting = _targeting_shapes(dictionary)
    added = []
    while targeting:
        names = [name for c in _classes(shape_dictionary) for name in targeting.get(c, ())
                 if name != shape_name and name not in added]
        if not names:
            break
        if not added:
            shape_dictionary = deepcopy(shape_dictionary)
        for name in names:
            if name not in added:
                added.append(name)
                merge_shape_dictionaries(shape_dictionary, deepcopy(dictionary[name]))
    return shape_dictionary, added


def _value_shape(property_dictionary, dictionary):
    """
    The shape of a property's values, if they are entities of a shape: the (first) shape of sh:node, or else the
    first shape that targets a class of the values (sh:class). Used to limit recursion.
    """
    shape = property_dictionary.get(SH.node)
    if shape is None:
        targeting = _targeting_shapes(dictionary)
        shape = next((name for c in parameter_values(property_dictionary, URIRef(SH['class']))
                      for name in targeting.get(c, ())), None)
    return shape


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


# The IRIs of generated entities start with this base IRI, unless another one is given (--base-iri)
DEFAULT_BASE_IRI = "http://example.org/ns#"


def checked_base_iri(base_iri):
    """The base IRI for generated entities, if it is an absolute IRI; raises ValueError otherwise."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s<>\"{}|\\^`]+", base_iri or ""):
        raise ValueError(f"the base IRI must be an absolute IRI, e.g. https://data.example.com/ (not {base_iri!r})")
    return base_iri


def _entity_iri(result, batchID, number):
    """The IRI of the entity with this number: generated from its constraints (see _new_entity_iri), or numbered."""
    iri = getattr(result, "iris_from_constraints", {}).get(number)
    return iri if iri is not None else URIRef(f'{getattr(result, "base_iri", DEFAULT_BASE_IRI)}Node{batchID}_{number}')


def _iri_form(shape_dictionary, iri_form=None):
    """
    The constraints of a shape on the IRI of a node (sh:pattern, sh:minLength, sh:maxLength: they apply to the text of
    an IRI, and never hold for a blank node), combined with iri_form (those of the property whose value the node is,
    for sh:node), as (patterns, minimum length, maximum length); None if there are none.
    """
    patterns = [str(pattern) for pattern in parameter_values(shape_dictionary, SH.pattern)]
    min_length, max_length = shape_dictionary.get(SH.minLength), shape_dictionary.get(SH.maxLength)
    if iri_form is not None:
        patterns += iri_form[0]
        min_length = max((n for n in (min_length, iri_form[1]) if n is not None), key=int, default=None)
        max_length = min((n for n in (max_length, iri_form[2]) if n is not None), key=int, default=None)
    if not patterns and min_length is None and max_length is None:
        return None
    return patterns, min_length, max_length


def _new_entity_iri(result, batchID, form=None):
    """
    A new IRI for an entity: numbered (e.g. http://example.org/ns#NodeB1_100), or, if its IRI must have a certain
    form (see _iri_form), generated from it (and remembered under its number, see _entity_iri).
    """
    global COUNTER
    number = COUNTER
    COUNTER += 1
    if form is not None:
        iri = generate_iri(*form, getattr(result, "base_iri", DEFAULT_BASE_IRI),
                           lambda iri: (iri, None, None) not in result and (None, None, iri) not in result)
        if iri is not None:
            if isinstance(result, GeneratedGraph):
                result.iris_from_constraints[number] = iri
            return iri
        warnings.warn(f"No new IRI with the pattern(s) {form[0]} and a length from {form[1]} to {form[2]} was "
                      f"found, so the node gets a numbered IRI.", stacklevel=2)
    return _entity_iri(result, batchID, number)


def _blank_node(batchID, number):
    # deterministic blank node identifiers (rdflib's default ones are random)
    return BNode(f'{batchID}b{number}')


class GeneratedGraph(Graph):
    """
    A generated graph. entity_shapes: (entity, shape) for every generated entity, with the shape it was generated
    from. The data links an entity to its shape with sh:description, except where that would break the shape (a
    closed shape, see _link_to_shape); validation of the generated graph uses entity_shapes, so that every entity is
    validated against its shape.
    """
    def __init__(self, *args, provenance=True, base_iri=DEFAULT_BASE_IRI, **kwargs):
        super().__init__(*args, **kwargs)
        self.entity_shapes = []
        # provenance=False: no entity is linked to its shape in the data (the record is still kept)
        self.provenance = provenance
        # the IRIs of the generated entities start with this
        self.base_iri = checked_base_iri(base_iri)
        # IRIs generated from the constraints of their nodes (sh:pattern), by the number of the entity
        self.iris_from_constraints = {}


def _link_to_shape(result, entity, shape, written):
    """Record that entity was generated from shape, and link it to the shape in the data if written."""
    if isinstance(result, GeneratedGraph):
        result.entity_shapes.append((entity, shape))
    if written and getattr(result, "provenance", True):
        result.add((entity, SH.description, shape))


def _allows_the_link_to_its_shape(shape_dictionary):
    """
    Whether the entities of a shape can have the link to their shape (sh:description): not if the shape is closed
    (sh:closed true), since a closed shape allows only the properties it declares, unless sh:ignoredProperties
    lists sh:description.
    """
    if Literal(True) not in parameter_values(shape_dictionary, SH.closed):
        return True
    return any(SH.description in ignored for ignored in parameter_values(shape_dictionary, SH.ignoredProperties))


def _remove_nodes_since(result, batchID, counters):
    """Remove the nodes created since the counters (COUNTER, BNODE_COUNTER) had these values, with their triples."""
    counter, bnode_counter = counters
    nodes = [_entity_iri(result, batchID, n) for n in range(counter, COUNTER)]
    nodes += [_blank_node(batchID, n) for n in range(bnode_counter, BNODE_COUNTER)]
    for node in nodes:
        result.remove((node, None, None))
        result.remove((None, None, node))
    if isinstance(result, GeneratedGraph):
        removed = set(nodes)
        result.entity_shapes = [(entity, shape) for entity, shape in result.entity_shapes if entity not in removed]


# sh:xone and sh:not: the number of attempts to generate data for which exactly one choice of each sh:xone list holds,
# and no negated shape of sh:not
CHECKED_ATTEMPTS = 20


def _generate_checked(xone_lists, negated_shapes, generate, result, dictionary, batchID):
    """
    Generate data (an entity or a value, with generate()) for a shape with sh:xone or sh:not. For sh:xone, one choice
    of each list is used, but the data can satisfy another choice as well (e.g. a choice that only limits a property,
    such as sh:maxCount 1, holds for a node without that property); and the data can satisfy a negated shape of
    sh:not. So the data is checked, and generated again until exactly one choice of each sh:xone list holds and no
    negated shape; the nodes of a failed attempt are removed first. After CHECKED_ATTEMPTS attempts, the last one is
    kept, with a warning. Shapes whose conformance the checker cannot tell are assumed not to break this.
    """
    for attempt in range(CHECKED_ATTEMPTS):
        counters = (COUNTER, BNODE_COUNTER)
        value = generate()
        if value is None:
            return None  # postponed, or no value can be generated
        if (all(exactly_one_holds(conforms(result, value, choice, dictionary) for choice in choices) is not False
                for choices in xone_lists)
                and all(conforms(result, value, negated, dictionary) is not True for negated in negated_shapes)):
            return value
        if attempt < CHECKED_ATTEMPTS - 1:
            _remove_nodes_since(result, batchID, counters)
    warnings.warn(f"No data was found for which exactly one shape of each sh:xone list holds and no shape of sh:not, "
                  f"after {CHECKED_ATTEMPTS} attempts.", stacklevel=2)
    return value


def dictionary_to_rdf_graph(shape_dictionary, shape_name, result, parent, dictionary,
                            property_pair_constraint_components_parent, parent_class, batchID, final_attempt=False,
                            ancestors=(), node_kind=None, checked=False, iri_form=None):
    # initialization
    property_pair_constraint_components = []
    global COUNTER, BNODE_COUNTER

    # the shape as it was given: a property that is postponed is generated again from it later (with new choices of
    # sh:or and sh:xone, which are combined with a copy of it below)
    postponed_shape = shape_dictionary

    # sh:node on a node shape: its entities conform to the shapes of sh:node as well
    shape_dictionary = _with_node_shapes(shape_dictionary, dictionary)

    # Instances of a class conform to all shapes that target the class. (For values of sh:node, this is done when
    # the entity is generated, see below; values of sh:in are used as they are.)
    class_shapes = []
    if (shape_dictionary.get(SH.path) is None
            or not (parameter_values(shape_dictionary, SH.node) or shape_dictionary.get(URIRef(SH + "in")))):
        shape_dictionary, class_shapes = _with_class_shapes(shape_dictionary, dictionary, shape_name)
        shape_dictionary = _with_node_shapes(shape_dictionary, dictionary)

    # sh:xone: exactly one choice of each list must hold; sh:not: no negated shape may hold. The generated data is
    # checked (see _generate_checked).
    xone_lists = parameter_values(shape_dictionary, URIRef(SH['xone']))
    negated_shapes = shape_dictionary.get(SH["not"], [])
    if (xone_lists or negated_shapes) and not checked:
        return _generate_checked(xone_lists, negated_shapes, lambda: dictionary_to_rdf_graph(
            postponed_shape, shape_name, result, parent, dictionary, property_pair_constraint_components_parent,
            parent_class, batchID, final_attempt, ancestors, node_kind, checked=True, iri_form=iri_form), result,
            dictionary, batchID)

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

    # if there is a sh:or for this dict, choose one of the choices and merge it with the existing properties. (One is
    # enough for sh:or to hold; combining several could combine constraints that contradict each other, e.g. two
    # datatypes, so that none of them holds.) Choices that cannot be generated (unsupported paths) are not used.
    if shape_dictionary.get(URIRef(SH['or'])):
        shape_dictionary = deepcopy(shape_dictionary)
        for sh_or in parameter_values(shape_dictionary, URIRef(SH['or'])):
            choices = [choice for choice in map(_branch_as_node_shape, sh_or) if choice is not None]
            if choices:
                merge_shape_dictionaries(shape_dictionary, random.choice(choices))

    # a shape of sh:and, sh:or or sh:xone can itself have sh:node
    shape_dictionary = _with_node_shapes(shape_dictionary, dictionary)

    # The node is created once the shape is complete (its node kind and classes can come from the shapes above)

    # sh:nodeKind of the shape (of a node shape: its entities; of a property shape: its values), and node_kind: the
    # node kind that the property whose value this entity is requires (for sh:node)
    kinds = {kind for kind in (shape_dictionary.get(SH.nodeKind), node_kind) if kind is not None}
    blank = bool(kinds & {SH.BlankNode, SH.BlankNodeOrLiteral})

    # The node is the value (of a property shape, or the entity of a node shape), unless the value comes from
    # elsewhere (an entity of sh:node, a value of sh:in) or is a literal. Its sh:pattern, sh:minLength and
    # sh:maxLength (iri_form: those of the property, for an entity of sh:node) then constrain its IRI.
    value_node = bool(shape_name or kinds & {SH.IRI, SH.BlankNodeOrIRI, SH.IRIOrLiteral} or _classes(shape_dictionary)
                      or shape_dictionary.get("properties") or _ends_with_inverse_step(shape_dictionary))
    if shape_dictionary.get(SH.path) is not None and (parameter_values(shape_dictionary, SH.node)
                                                       or shape_dictionary.get(URIRef(SH + "in"))):
        value_node = False
    form = _iri_form(shape_dictionary, iri_form) if value_node else None

    # Entities of a named shape are IRIs, and other nodes (e.g. values with nested properties) blank nodes, unless
    # the node kind requires the other kind, or the IRI must have a certain form
    if (shape_name or kinds & {SH.IRI, SH.IRIOrLiteral} or form is not None) and not blank:
        node = _new_entity_iri(result, batchID, form)
    else:
        node = _blank_node(batchID, BNODE_COUNTER)
        BNODE_COUNTER += 1
    if shape_name:
        # as SH.description add the name of the shape that this node was generated from (see _link_to_shape)
        _link_to_shape(result, node, shape_name, _allows_the_link_to_its_shape(shape_dictionary))

    # the generated entities on the path from the top-level entity to this one, with their shapes (see _earlier_entities)
    for name in ([shape_name] if shape_name else []) + class_shapes:
        ancestors = ancestors + ((name, node),)

    # The entity (or, for a property shape, each value) is an instance of every class given with sh:targetClass and
    # sh:class (all of them must hold). The classes are added to the value that is returned (see typed), which is
    # this node, or e.g. an entity of sh:node or a value of sh:in.
    classes = _classes(shape_dictionary)
    sh_class = classes[0] if classes else parent_class

    def typed(value):
        if value is not None and not isinstance(value, Literal):
            for c in classes:
                result.add((value, RDF.type, c))
        return value

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
            property_pair_constraint_components_parent.append(postponed_shape)
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
            property_pair_constraint_components_parent.append(postponed_shape)
            return None
    disjoint_values = list(sh_disjoint or [])

    # sh:not with sh:in or sh:hasValue (e.g. sh:not [ sh:in (1 2) ]): a value that is not one of these values does
    # not conform to the negated shape, so these values are avoided in the same way as those of sh:disjoint
    if shape_dictionary.get(SH.path) is not None:
        for negated in shape_dictionary.get(SH["not"], []):
            for excluded in parameter_values(negated, URIRef(SH['in'])) + [parameter_values(negated, SH.hasValue)]:
                disjoint_values += [value for value in excluded if value not in disjoint_values]

    # get the dependent property for sh:lessThan
    sh_less_than = shape_dictionary.get(SH.lessThan)
    if sh_less_than:
        sh_less_than = [o for o in result.objects(parent, sh_less_than)]
        if len(sh_less_than) == 0 and not final_attempt:
            property_pair_constraint_components_parent.append(postponed_shape)
            return None

    # get the dependent property for sh:lessThanOrEquals
    sh_less_than_or_equals = shape_dictionary.get(SH.lessThanOrEquals)
    if sh_less_than_or_equals:
        sh_less_than_or_equals = [o for o in result.objects(parent, sh_less_than_or_equals)]
        if len(sh_less_than_or_equals) == 0 and not final_attempt:
            property_pair_constraint_components_parent.append(postponed_shape)
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
            property_pair_constraint_components_parent.append(postponed_shape)
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
    sh_path = shape_dictionary.get(SH.path)

    # get the nested properties
    properties = shape_dictionary.get("properties")

    # sh:node on a property shape (on a node shape, it is combined with the shape, see _with_node_shapes): each value
    # is an entity that conforms to all shapes of sh:node, and to the nested property shapes of the property, if any.
    # It is linked to each of these shapes (sh:description), so that it is validated against each of them.
    node_shapes = parameter_values(shape_dictionary, SH.node)
    if node_shapes:
        for name in node_shapes:
            if dictionary.get(name) is None:
                raise Exception("The SHACL shape " + name + " cannot be found!")
        if len(node_shapes) == 1 and not properties and not classes:
            entity_shape = dictionary[node_shapes[0]]
        else:
            entity_shape = {SH.node: node_shapes[0], "values": {SH.node: list(node_shapes)}}
            if classes:  # the entity is an instance of the classes of the property, and conforms to their shapes
                entity_shape[URIRef(SH['class'])] = classes[0]
                entity_shape["values"][URIRef(SH['class'])] = list(classes)
            if properties:
                entity_shape["properties"] = properties
        entity = dictionary_to_rdf_graph(entity_shape, node_shapes[0], result, None, dictionary, [], sh_class, batchID,
                                         ancestors=ancestors, node_kind=shape_dictionary.get(SH.nodeKind),
                                         iri_form=_iri_form(shape_dictionary))
        linked = (entity, SH.description, node_shapes[0]) in result  # not for entities of closed shapes
        for name in node_shapes[1:]:
            _link_to_shape(result, entity, name, linked)
        return typed(entity)

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
            earlier = _earlier_entities(ancestors, _value_shape(value, dictionary), node)
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
        # only values of the node kind; values reached through an inverse step are subjects of triples, so they
        # cannot be literals
        allowed_kinds = kinds | ({SH.BlankNodeOrIRI} if _ends_with_inverse_step(shape_dictionary) else set())
        if allowed_kinds:
            candidates = ([value for value in candidates if has_node_kind(value, allowed_kinds)]
                          or [value for value in sh_in if has_node_kind(value, allowed_kinds)])
            if not candidates:
                return None
        return typed(random.choice(candidates))

    # The value is the fresh node created above, with the classes of the shape: for an entity of a node shape (e.g.
    # one without properties), for values that must be instances of a class (sh:class), for values of a node kind
    # other than literals (sh:nodeKind), and for values reached through an inverse step (they are subjects of
    # triples, so they cannot be literals)
    if (shape_name or classes or kinds & NON_LITERAL_NODE_KINDS
            or _ends_with_inverse_step(shape_dictionary)):
        return typed(node)

    # language-tagged strings (sh:datatype rdf:langString, or sh:languageIn): the string gets a language tag; with
    # sh:uniqueLang, one that the other values of the property do not have
    language_in = shape_dictionary.get(SH.languageIn)

    def with_language(value):
        if ((language_in is not None or sh_datatype == RDF.langString) and sh_datatype in (None, RDF.langString)
                and isinstance(value, Literal) and value.datatype is None and value.language is None):
            used_languages = {o.language.lower() for o in _values(result, parent, sh_path, shape_dictionary)
                              if isinstance(o, Literal) and o.language}
            value = add_language_tag(value, used_languages, language_in, bool(shape_dictionary.get(SH.uniqueLang)))
        return value

    # A realistic value (e.g. a name from the name lists for schema:givenName) is used if it satisfies the constraints
    # of the property on its values (e.g. sh:maxLength or sh:pattern), is not yet a value of the property, and is not
    # excluded (sh:disjoint, sh:not); a few are tried, and otherwise a value is generated from the constraints
    existing = _values(result, parent, sh_path, shape_dictionary)
    for _ in range(REALISTIC_VALUE_ATTEMPTS):
        value = generate_intuitive_value(sh_path, sh_class, dependencies)
        if not value:
            break
        value = with_language(value)
        if (value is not None and value not in disjoint_values and value not in existing
                and value_conforms(result, value, shape_dictionary, dictionary) is not False):
            return value

    # a generated value based on multiple constraints; values of the sh:disjoint property are excluded in the same
    # way as the values that this property already has
    existing_values = {o.toPython() for o in existing} | {o.toPython() for o in disjoint_values}
    value = generate_default_value(existing_values, sh_datatype, sh_min_exclusive, sh_min_inclusive, sh_max_exclusive,
                                   sh_max_inclusive, sh_min_length, sh_max_length, sh_pattern, sh_equals, sh_disjoint,
                                   sh_less_than, sh_less_than_or_equals, sh_path, sh_class)
    return with_language(value)


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


def generate_rdf_graphs_from_dictionary(shapes_graph, dictionary, number_of_samples, batchID, provenance=True,
                                        base_iri=DEFAULT_BASE_IRI):
    global COUNTER, BNODE_COUNTER
    COUNTER, BNODE_COUNTER = 100, 0  # identifiers are unique per batch (batchID) and independent of the process

    result_graph = GeneratedGraph(provenance=provenance, base_iri=base_iri)
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


def generate_batch(shapes_graph, dictionary, number, batch_index, seed=None, provenance=True,
                   base_iri=DEFAULT_BASE_IRI):
    """
    Generate one batch: `number` entities per top-level node shape, with identifiers that are unique to the
    batch. With a seed, the batch depends only on (seed, batch_index), not on the process that generates it.
    provenance=False: the entities are not linked to their shapes (sh:description) in the data.
    base_iri: the IRIs of the generated entities start with it.
    """
    if seed is not None:
        # The generator (and exrex) use the global random module; seeding with a string is stable across runs
        random.seed(f"{seed}/{batch_index}")
    return generate_rdf_graphs_from_dictionary(shapes_graph, dictionary, number, f'B{batch_index}', provenance,
                                               base_iri)


def generate_graph(shapes, scale_factor, seed=None, provenance=True, base_iri=DEFAULT_BASE_IRI):
    """
    Generate a synthetic RDF graph in memory and return it as an rdflib Graph.

    shapes: an rdflib Graph with SHACL shapes, or the path to a file with SHACL shapes.
    scale_factor: the number of entities generated for each top-level node shape.
    seed: optional; the same seed always produces the same graph. The result is the same as the first batch
          of 'rdfgen ... --seed SEED' with a batch size of at least scale_factor.
    provenance: link each entity to the shape it was generated from (entity sh:description shape), so that a
          validation of the graph can check each entity against its shape (see rdf_graph_gen.validation). With
          provenance=False, the data has no such links; validate_generated still uses them for the returned graph.
    base_iri: the IRIs of the generated entities start with it (default: http://example.org/ns#).
    """
    shapes_graph = shapes if isinstance(shapes, Graph) else Graph().parse(shapes)
    dictionary = generate_dictionary_from_shapes_graph(shapes_graph)
    return generate_batch(shapes_graph, dictionary, scale_factor, 1, seed, provenance, base_iri)


def generate_rdf(shape_file, output_file, number, batch_size=1000, seed=None, processes=1, provenance=True,
                 base_iri=DEFAULT_BASE_IRI):
    """
    Generate a synthetic RDF graph and write it to output_file (Turtle), in batches of batch_size entities.
    With processes > 1, the batches are generated in parallel. The same seed always produces the same file,
    regardless of the number of processes. provenance=False: the entities are not linked to their shapes
    (sh:description) in the output. base_iri: the IRIs of the generated entities start with it.
    """
    from rdf_graph_gen.multiprocess_generate import MultiprocessGenerator
    MultiprocessGenerator(shape_file, output_file, number, batch_size, processes=processes, seed=seed,
                          provenance=provenance, base_iri=base_iri).generate()
