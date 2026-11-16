"""
A small conformance check for generated data: whether a node conforms to a shape (a shape dictionary of
shacl_mapping_generator), for the core constraint components of SHACL. The generator uses it for shapes that must
not hold for the data it generates (the other choices of sh:xone, and sh:not), since validation with pySHACL is
optional.

The result is True, False, or None if it is not known: for constraint components that are not checked here (e.g.
sh:closed, sh:qualifiedValueShape), for property paths that are not supported, and for very deep sh:node references.

Only the constraints given in the shapes are checked (a shape dictionary's "values"); the parser also adds hints for
the generator to shape dictionaries (e.g. the lower bound of the other property of sh:lessThan), which are not
constraints of the shape.
"""
import re

from rdflib import RDF, RDFS, SH, XSD, BNode, Literal, URIRef

from rdf_graph_gen.shacl_mapping_generator import language_matches

# sh:nodeKind: the kinds of nodes that each node kind allows
NODE_KINDS = {
    SH.IRI: (URIRef,), SH.BlankNode: (BNode,), SH.Literal: (Literal,),
    SH.BlankNodeOrIRI: (BNode, URIRef), SH.BlankNodeOrLiteral: (BNode, Literal), SH.IRIOrLiteral: (URIRef, Literal),
}

# Parameters of shapes that are not constraints, or that belong to the constraint of another parameter
NOT_CONSTRAINTS = {
    SH.path, SH.name, SH.description, SH.message, SH.severity, SH.order, SH.group, SH.defaultValue,
    SH.targetClass, SH.targetNode, SH.targetSubjectsOf, SH.targetObjectsOf, SH.target, SH.flags,
    SH.ignoredProperties, SH.qualifiedMinCount, SH.qualifiedMaxCount, SH.qualifiedValueShapesDisjoint,
    SH.deactivated,
}

# Constraints on the set of values of a property shape (checked once per focus node, not per value)
VALUE_SET_CONSTRAINTS = {SH.minCount, SH.maxCount, SH.hasValue, SH.equals, SH.disjoint, SH.lessThan,
                         SH.lessThanOrEquals, SH.uniqueLang}

# sh:node references deeper than this are not followed (the result is not known)
MAX_DEPTH = 16


def has_node_kind(value, kinds):
    """Whether a value is of every node kind in kinds (e.g. an IRI for sh:IRI)."""
    return all(isinstance(value, NODE_KINDS[kind]) for kind in kinds if kind in NODE_KINDS)


def all_hold(results):
    """Three-valued conjunction: False if a result is False, else None if a result is None, else True."""
    unknown = False
    for result in results:
        if result is False:
            return False
        if result is None:
            unknown = True
    return None if unknown else True


def any_holds(results):
    """Three-valued disjunction: True if a result is True, else None if a result is None, else False."""
    unknown = False
    for result in results:
        if result is True:
            return True
        if result is None:
            unknown = True
    return None if unknown else False


def exactly_one_holds(results):
    results = list(results)
    holding = results.count(True)
    if holding > 1:
        return False
    if None in results:
        return None
    return holding == 1


def negation(result):
    return None if result is None else not result


def conforms(graph, focus, shape, dictionary, depth=0):
    """
    Whether focus (a node of graph) conforms to shape (a shape dictionary): True, False, or None if it is not known.
    dictionary: the shape dictionaries of the named shapes (for sh:node).
    """
    if depth > MAX_DEPTH:
        return None
    constraints = shape.get("values", {})
    if Literal(True) in constraints.get(SH.deactivated, []):
        return True
    if shape.get(SH.path) is not None:
        # a property shape: the constraints apply to the values of the path
        values = _path_values(graph, focus, shape)
        if values is None:
            return None
        results = [_value_set_conforms(graph, focus, values, constraints)]
        results += [_value_conforms(graph, value, shape, dictionary, depth, in_property_shape=True)
                    for value in values]
    else:
        # a node shape: the constraints apply to the focus node itself
        results = [_value_conforms(graph, focus, shape, dictionary, depth, in_property_shape=False)]
    if shape.get("unsupported"):
        results.append(None)  # a property shape of it was skipped (an unsupported path)
    return all_hold(results)


def _path_values(graph, focus, shape):
    """The values of the property shape's path for focus, or None for paths that are not supported."""
    path = shape[SH.path]
    steps = shape.get("path_steps") or ([(path, False)] if isinstance(path, URIRef) else None)
    if steps is None:
        return None
    nodes = {focus}
    for predicate, inverse in steps:
        if inverse:
            nodes = {s for node in nodes for s in graph.subjects(predicate, node)}
        else:
            nodes = {o for node in nodes for o in graph.objects(node, predicate)}
    return nodes


def _value_set_conforms(graph, focus, values, constraints):
    results = []
    for count in constraints.get(SH.minCount, []):
        results.append(len(values) >= int(count))
    for count in constraints.get(SH.maxCount, []):
        results.append(len(values) <= int(count))
    for value in constraints.get(SH.hasValue, []):
        results.append(value in values)
    for other in constraints.get(SH.equals, []):
        results.append(values == set(graph.objects(focus, other)))
    for other in constraints.get(SH.disjoint, []):
        results.append(not values & set(graph.objects(focus, other)))
    for other in constraints.get(SH.lessThan, []):
        results.append(all(_compare(v, o, lambda a, b: a < b) for v in values for o in graph.objects(focus, other)))
    for other in constraints.get(SH.lessThanOrEquals, []):
        results.append(all(_compare(v, o, lambda a, b: a <= b) for v in values for o in graph.objects(focus, other)))
    if Literal(True) in constraints.get(SH.uniqueLang, []):
        languages = [value.language.lower() for value in values if isinstance(value, Literal) and value.language]
        results.append(len(languages) == len(set(languages)))
    return all_hold(results)


def _value_conforms(graph, value, shape, dictionary, depth, in_property_shape):
    """Whether a value node (of a property shape, or the focus node of a node shape) satisfies the shape."""
    constraints = shape.get("values", {})
    results = []
    for parameter, parameter_values in constraints.items():
        if not str(parameter).startswith(str(SH)) or parameter in NOT_CONSTRAINTS:
            continue  # e.g. rdf:type sh:NodeShape, or sh:name
        if parameter in VALUE_SET_CONSTRAINTS:
            if not in_property_shape and parameter != SH.hasValue:
                results.append(None)  # e.g. sh:equals on a node shape: not checked here
            elif not in_property_shape:
                results += [value == has_value for has_value in parameter_values]
            continue
        check = VALUE_CHECKS.get(parameter)
        if check is None:
            results.append(None)  # a constraint component that is not checked here (e.g. sh:closed)
            continue
        results += [check(graph, value, parameter_value, constraints, dictionary, depth)
                    for parameter_value in parameter_values]
    results += [conforms(graph, value, property_shape, dictionary, depth + 1)
                for property_shape in shape.get("properties", {}).values()]
    results += [negation(conforms(graph, value, negated, dictionary, depth + 1)) for negated in shape.get(SH["not"], [])]
    return all_hold(results)


def _compare(value, bound, holds):
    """A comparison of two literals; values that cannot be compared (e.g. a string and a number) do not satisfy it."""
    if not isinstance(value, Literal) or not isinstance(bound, Literal):
        return False
    a, b = value.toPython(), bound.toPython()
    if isinstance(a, Literal) or isinstance(b, Literal):
        return False  # no Python value (e.g. xsd:gYear), as in SPARQL, where they cannot be compared either
    try:
        return bool(holds(a, b))
    except TypeError:
        return False


def _is_instance(graph, value, cls):
    """SHACL instances: the value has rdf:type cls, or a subclass of it (rdfs:subClassOf in the data graph)."""
    if isinstance(value, Literal):
        return False
    return any(t == cls or cls in graph.transitive_objects(t, RDFS.subClassOf) for t in graph.objects(value, RDF.type))


def _datatype(value):
    if value.datatype is not None:
        return value.datatype
    return RDF.langString if value.language else XSD.string


def _pattern_holds(value, pattern, constraints):
    if isinstance(value, BNode):
        return False
    flags = 0
    for flag in str((constraints.get(SH.flags) or [""])[0]):
        flags |= {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL, "x": re.VERBOSE}.get(flag, 0)
    try:
        return re.search(str(pattern), str(value), flags) is not None
    except re.error:
        return None  # a pattern that Python cannot read


def _length(value):
    return None if isinstance(value, BNode) else len(str(value))


def _shape_conforms(graph, value, name, dictionary, depth):
    shape = dictionary.get(name)
    return None if shape is None else conforms(graph, value, shape, dictionary, depth + 1)


# The checks of single value nodes: check(graph, value, parameter value, all constraints, dictionary, depth)
VALUE_CHECKS = {
    SH["class"]: lambda g, v, cls, c, d, depth: _is_instance(g, v, cls),
    SH.datatype: lambda g, v, datatype, c, d, depth: (isinstance(v, Literal) and _datatype(v) == datatype
                                                      and not v.ill_typed),
    SH.nodeKind: lambda g, v, kind, c, d, depth: has_node_kind(v, {kind}),
    SH.minInclusive: lambda g, v, bound, c, d, depth: _compare(v, bound, lambda a, b: a >= b),
    SH.minExclusive: lambda g, v, bound, c, d, depth: _compare(v, bound, lambda a, b: a > b),
    SH.maxInclusive: lambda g, v, bound, c, d, depth: _compare(v, bound, lambda a, b: a <= b),
    SH.maxExclusive: lambda g, v, bound, c, d, depth: _compare(v, bound, lambda a, b: a < b),
    SH.minLength: lambda g, v, length, c, d, depth: _length(v) is not None and _length(v) >= int(length),
    SH.maxLength: lambda g, v, length, c, d, depth: _length(v) is not None and _length(v) <= int(length),
    SH.pattern: lambda g, v, pattern, c, d, depth: _pattern_holds(v, pattern, c),
    SH.languageIn: lambda g, v, tags, c, d, depth: (isinstance(v, Literal) and bool(v.language)
                                                    and language_matches(v.language, [str(t) for t in tags])),
    SH["in"]: lambda g, v, values, c, d, depth: v in values,
    SH.node: lambda g, v, name, c, d, depth: _shape_conforms(g, v, name, d, depth),
    SH["and"]: lambda g, v, shapes, c, d, depth: all_hold(conforms(g, v, s, d, depth + 1) for s in shapes),
    SH["or"]: lambda g, v, shapes, c, d, depth: any_holds(conforms(g, v, s, d, depth + 1) for s in shapes),
    SH.xone: lambda g, v, shapes, c, d, depth: exactly_one_holds(conforms(g, v, s, d, depth + 1) for s in shapes),
}
