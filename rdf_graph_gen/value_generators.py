import csv
import math
import random
from exrex import *
from exrex import _randone
from rdflib import XSD, Literal, URIRef, Namespace
import re
from collections import namedtuple
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from rdf_graph_gen.shacl_mapping_generator import SCH
from importlib.resources import files
import warnings

"""
Reads data from a CSV file and returns the content as a list of values.

Parameters:
-----------
file_name (str): The name of the CSV file from which data will be read.

Returns:
--------
list: A list containing the values read from the CSV file.
"""


def get_path(file_name):
    # Location of a bundled dataset file, resolved via importlib.resources (works for any installation layout)
    return files('rdf_graph_gen') / 'datasets' / file_name


def get_array_from_csv(file_name):
    results = []  # Initialize an empty list to store the values
    # file_name is either a plain path or a Traversable returned by get_path
    with (file_name.open(encoding='utf-8') if hasattr(file_name, 'open') else open(file_name, encoding='utf-8')) as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:  # Iterate through each row in the CSV file
            results = results + row  # Append values from each row to the results list
    return results  # Return the list containing values from the CSV file

dataset_dictionary = {'streetAddress': get_array_from_csv(get_path("street_name.csv")),
                      'givenNameMale': get_array_from_csv(get_path("male_first_name.csv")),
                      'givenNameFemale': get_array_from_csv(get_path("female_first_name.csv")),
                      'familyName': get_array_from_csv(get_path("surnames.csv")),
                      'gender': ['male', 'female', 'non-binary'],
                      'jobTitle': get_array_from_csv(get_path("job_title.csv")),
                      'bookAward': get_array_from_csv(get_path("book_awards.csv")),
                      'bookGenre': get_array_from_csv(get_path("book_genre.csv")),
                      'bookTitle': get_array_from_csv(get_path("book_titles.csv")),
                      'movieGenre': get_array_from_csv(get_path("movie_genre.csv")),
                      'movieAward': get_array_from_csv(get_path("movie_awards.csv")),
                      'movieTitle': get_array_from_csv(get_path("movie_titles.csv")),
                      'tvSeriesTitle': get_array_from_csv(get_path("tvseries_titles.csv"))
                      }


def getBookFormat():
    return URIRef(SCH[random.choice(["AudiobookFormat", "EBook", "GraphicNovel", "Hardcover", "Paperback"])])


# The value ranges of the XSD integer datatypes (None: unbounded)
INTEGER_DATATYPES = {
    XSD.integer: (None, None),
    XSD.nonNegativeInteger: (0, None), XSD.positiveInteger: (1, None),
    XSD.nonPositiveInteger: (None, 0), XSD.negativeInteger: (None, -1),
    XSD.long: (-2 ** 63, 2 ** 63 - 1), XSD.int: (-2 ** 31, 2 ** 31 - 1),
    XSD.short: (-2 ** 15, 2 ** 15 - 1), XSD.byte: (-2 ** 7, 2 ** 7 - 1),
    XSD.unsignedLong: (0, 2 ** 64 - 1), XSD.unsignedInt: (0, 2 ** 32 - 1),
    XSD.unsignedShort: (0, 2 ** 16 - 1), XSD.unsignedByte: (0, 2 ** 8 - 1),
}

# The XSD datatypes of numbers with a fractional part: xsd:decimal values are generated as decimal numbers, and
# xsd:double and xsd:float values as floating-point numbers
DECIMAL_DATATYPES = {XSD.decimal, XSD.double, XSD.float}


def _python(value):
    return value.toPython() if isinstance(value, Literal) else value


def _bounds(min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than, less_than_or_equals,
            convert=_python):
    """
    The strictest lower and upper bound of a value, each as (number, exclusive) or None, from the value range
    constraints and the values of the sh:lessThan and sh:lessThanOrEquals properties. `convert` turns a bound into a
    number (None: a bound that cannot be used).
    """
    lower = [(convert(bound), exclusive) for bound, exclusive in ((min_inclusive, False), (min_exclusive, True))
             if bound is not None]
    upper = [(convert(bound), exclusive) for bound, exclusive in ((max_inclusive, False), (max_exclusive, True))
             if bound is not None]
    upper += [(convert(value), True) for value in less_than or []]
    upper += [(convert(value), False) for value in less_than_or_equals or []]
    lower = [bound for bound in lower if bound[0] is not None]
    upper = [bound for bound in upper if bound[0] is not None]
    # the highest lower bound and the lowest upper bound; of two equal bounds, the exclusive one
    return max(lower, default=None), min(upper, key=lambda bound: (bound[0], not bound[1]), default=None)


def _whole_number_bounds(lower, upper):
    """The lowest and the highest whole number within the bounds given by _bounds (None: unbounded)."""
    lowest = None if lower is None else math.floor(lower[0]) + 1 if lower[1] else math.ceil(lower[0])
    highest = None if upper is None else math.ceil(upper[0]) - 1 if upper[1] else math.floor(upper[0])
    return lowest, highest


def _whole_number(min_n, max_n, is_new, kind, default_start=1, span=50, limits=(None, None), describe=str):
    """
    A random whole number from min_n to max_n (None: unbounded) for which is_new is true, or None. With one bound,
    the number is at most `span` away from it, and without bounds, it is from default_start to default_start + span.
    The number is always within `limits` (the value range of the datatype).
    """
    if max_n is not None:
        if min_n is not None:
            if max_n < min_n:
                replacement = max_n - span
                warnings.warn(f"Invalid {kind} range: ({describe(min_n)}, {describe(max_n)}). The range will be "
                              f"changed to: ({describe(replacement)}, {describe(max_n)}).", stacklevel=3)
                min_n = replacement
        else:
            min_n = max_n - span
    else:
        if min_n is None:
            min_n = default_start
        max_n = min_n + span

    # the default range of values may exceed the range of the datatype (e.g. xsd:byte with sh:minInclusive 100)
    lowest, highest = limits
    if lowest is not None:
        min_n = max(min_n, lowest)
    if highest is not None:
        max_n = min(max_n, highest)
    if min_n > max_n:
        warnings.warn(f"Invalid {kind} range: the value range of the property is outside the range of its datatype, "
                      f"so no value is generated.", stacklevel=3)
        return None

    # Find a value in the range that has not been generated yet
    value_down = value_up = random.randint(min_n, max_n)
    while value_up <= max_n:
        if is_new(value_up):
            return value_up
        value_up += 1
    while value_down >= min_n:
        if is_new(value_down):
            return value_down
        value_down -= 1
    return None


# The min_length, max_length, pattern, disjoint, has_value properties are not taken into account at this point for
# integer generation
def generate_integer(existing_values, min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than,
                     less_than_or_equals, datatype=XSD.integer):
    lower, upper = _bounds(min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than, less_than_or_equals)
    min_int, max_int = _whole_number_bounds(lower, upper)
    limits = INTEGER_DATATYPES.get(datatype, (None, None))
    # by default, small positive numbers; for xsd:negativeInteger and xsd:nonPositiveInteger, small negative ones
    default_start = 1 if limits[1] is None else min(1, limits[1] - 50)
    value = _whole_number(min_int, max_int, lambda n: n not in existing_values, "int", default_start, 50, limits)
    return None if value is None else Literal(value, datatype=datatype)


# The min_length, max_length, pattern, disjoint, has_value properties are not taken into account at this point for
# decimal generation
def generate_decimal(existing_values, min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than,
                     less_than_or_equals, datatype=XSD.decimal):
    lower, upper = _bounds(min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than, less_than_or_equals)
    lower = None if lower is None else (Decimal(str(lower[0])), lower[1])
    upper = None if upper is None else (Decimal(str(upper[0])), upper[1])
    if upper is not None:
        if lower is not None:
            if upper[0] < lower[0] or (upper[0] == lower[0] and (upper[1] or lower[1])):
                lower_replacement = (upper[0] - 50, False)
                warnings.warn(f"Invalid decimal range: ({lower[0]}, {upper[0]}). The range will be changed to: "
                              f"({lower_replacement[0]}, {upper[0]}).", stacklevel=2)
                lower = lower_replacement
        else:
            lower = (upper[0] - 50, False)
    else:
        if lower is None:
            lower = (Decimal(1), False)
        upper = (lower[0] + 50, False)

    # values with two decimal places, or with more if the range has no such values (e.g. between 0.001 and 0.002)
    for places in range(2, 16):
        scale = Decimal(10) ** places
        first = math.floor(lower[0] * scale) + 1 if lower[1] else math.ceil(lower[0] * scale)
        last = math.ceil(upper[0] * scale) - 1 if upper[1] else math.floor(upper[0] * scale)
        if first <= last:
            break
    else:
        return None

    def literal(scaled):
        value = Decimal(scaled).scaleb(-places)
        # xsd:double and xsd:float values are floating-point numbers
        return Literal(value) if datatype == XSD.decimal else Literal(float(value), datatype=datatype)

    # Find a value in the range that has not been generated yet
    value_down = value_up = random.randint(first, last)
    while value_up <= last:
        if literal(value_up).toPython() not in existing_values:
            return literal(value_up)
        value_up += 1
    while value_down >= first:
        if literal(value_down).toPython() not in existing_values:
            return literal(value_down)
        value_down -= 1
    return None


# The XSD date and time datatypes. Their values are generated as whole numbers of a unit (e.g. days for xsd:date,
# seconds for xsd:dateTime), in the same way as integers.
TEMPORAL_DATATYPES = {XSD.date, XSD.dateTime, XSD.dateTimeStamp, XSD.time,
                      XSD.gYear, XSD.gYearMonth, XSD.gMonth, XSD.gDay, XSD.gMonthDay}

# Without bounds, dates are generated in the 50 years from this day
DEFAULT_FIRST_DAY = date(1970, 7, 7)
DEFAULT_DAYS = (date(2020, 7, 7) - DEFAULT_FIRST_DAY).days
EPOCH = datetime(1970, 1, 1)
SECONDS_PER_DAY = 24 * 60 * 60
TIME_ZONE = r"(?:Z|[+-]\d{2}:\d{2})?"

# to_number: a bound (a literal) as a whole number, or None; to_literal: a whole number as a literal of the datatype;
# without bounds, the numbers are from default_start to default_start + span; limits: the range of the numbers
_TimeScale = namedtuple("_TimeScale", "to_number to_literal default_start span limits")


def _parts(pattern, combine=lambda first: first):
    """A to_number function: the numbers in the lexical form of a bound (with an optional time zone), combined."""
    def to_number(bound):
        match = re.fullmatch(pattern + TIME_ZONE, str(bound))
        if match is None:
            return None
        try:
            return combine(*(int(part) for part in match.groups()))
        except ValueError:  # e.g. 2023-02-30
            return None
    return to_number


def _typed(lexical_form, datatype):
    return lambda number: Literal(lexical_form(number), datatype=datatype)


def _python_value(bound, datatype, python_type):
    """The value of a bound as converted by rdflib, or None if it is not a valid value of the datatype."""
    value = Literal(str(bound), datatype=datatype).toPython()
    return value if isinstance(value, python_type) else None


def _month_day(number):
    """The --MM-DD form of a day of the year 2000 (a leap year, so 29 February is included)."""
    day = date(2000, 1, 1) + timedelta(days=number - 1)
    return f"--{day.month:02d}-{day.day:02d}"


SIMPLE_TIME_SCALES = {
    XSD.date: _TimeScale(_parts(r"(\d{4})-(\d{2})-(\d{2})", lambda y, m, d: date(y, m, d).toordinal()),
                         lambda number: Literal(date.fromordinal(number)),
                         DEFAULT_FIRST_DAY.toordinal(), DEFAULT_DAYS, (1, date.max.toordinal())),
    XSD.gYear: _TimeScale(_parts(r"(\d{4})"), _typed(lambda y: f"{y:04d}", XSD.gYear),
                          DEFAULT_FIRST_DAY.year, 50, (1, 9999)),
    XSD.gYearMonth: _TimeScale(_parts(r"(\d{4})-(\d{2})", lambda y, m: 12 * y + m - 1 if 1 <= m <= 12 else None),
                               _typed(lambda n: f"{n // 12:04d}-{n % 12 + 1:02d}", XSD.gYearMonth),
                               12 * DEFAULT_FIRST_DAY.year + DEFAULT_FIRST_DAY.month - 1, 12 * 50, (12, 12 * 9999 + 11)),
    XSD.gMonth: _TimeScale(_parts(r"--(\d{2})"), _typed(lambda m: f"--{m:02d}", XSD.gMonth), 1, 11, (1, 12)),
    XSD.gDay: _TimeScale(_parts(r"---(\d{2})"), _typed(lambda d: f"---{d:02d}", XSD.gDay), 1, 30, (1, 31)),
    XSD.gMonthDay: _TimeScale(_parts(r"--(\d{2})-(\d{2})", lambda m, d: date(2000, m, d).timetuple().tm_yday),
                              _typed(_month_day, XSD.gMonthDay), 1, 365, (1, 366)),
}


def _time_scale(datatype, bounds):
    """
    How the values of a date or time datatype are generated. The values of xsd:dateTime and xsd:time have the time
    zone of the first bound that has one (xsd:dateTimeStamp values always have a time zone, by default UTC).
    """
    if datatype in SIMPLE_TIME_SCALES:
        return SIMPLE_TIME_SCALES[datatype]
    if datatype == XSD.time:
        values = [_python_value(bound, XSD.time, time) for bound in bounds]
        zone = next((value.tzinfo for value in values if value is not None and value.tzinfo is not None), None)

        def to_number(bound):
            value = _python_value(bound, XSD.time, time)
            if value is None:
                return None
            return value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1e6

        def to_literal(number):
            return Literal(time(number // 3600, number % 3600 // 60, number % 60, tzinfo=zone))

        return _TimeScale(to_number, to_literal, 0, SECONDS_PER_DAY - 1, (0, SECONDS_PER_DAY - 1))

    # xsd:dateTime and xsd:dateTimeStamp
    values = [_python_value(bound, XSD.dateTime, datetime) for bound in bounds]
    zone = next((value.tzinfo for value in values if value is not None and value.tzinfo is not None),
                timezone.utc if datatype == XSD.dateTimeStamp else None)

    def to_number(bound):
        value = _python_value(bound, XSD.dateTime, datetime)
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(zone)
        return (value.replace(tzinfo=None) - EPOCH).total_seconds()

    def to_literal(number):
        return Literal((EPOCH + timedelta(seconds=number)).replace(tzinfo=zone), datatype=datatype)

    second = timedelta(seconds=1)
    return _TimeScale(to_number, to_literal, (datetime.combine(DEFAULT_FIRST_DAY, time()) - EPOCH) // second,
                      DEFAULT_DAYS * SECONDS_PER_DAY, ((datetime.min - EPOCH) // second, (datetime.max - EPOCH) // second))


def generate_temporal(existing_values, datatype, min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than,
                      less_than_or_equals):
    bounds = [bound for bound in (min_inclusive, min_exclusive, max_inclusive, max_exclusive) if bound is not None]
    bounds += list(less_than or []) + list(less_than_or_equals or [])
    scale = _time_scale(datatype, bounds)
    lower, upper = _bounds(min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than, less_than_or_equals,
                           convert=scale.to_number)
    min_n, max_n = _whole_number_bounds(lower, upper)

    def describe(number):
        try:
            return str(scale.to_literal(number))
        except (ValueError, OverflowError):  # outside the range of the datatype
            return str(number)

    value = _whole_number(min_n, max_n, lambda n: scale.to_literal(n).toPython() not in existing_values,
                          datatype.split("#")[-1], scale.default_start, scale.span, scale.limits, describe)
    return None if value is None else scale.to_literal(value)


# The min_exclusive, min_inclusive, max_exclusive, max_inclusive, disjoint, less_than, less_than_or_equals, has_value
# properties are not taken into account at this point for string generation
def generate_string(existing_values, min_length, max_length, pattern):
    
    # If pattern is present, generate a literal using it. 
    # Try to find a value that is not allready generated 10 times, if u cant, give up.
    if pattern:
        for i in range(10):
            literal = _randone(parse(pattern))
            if literal not in existing_values:
                return Literal(literal)
        return None
    
    if min_length:
        min_length = int(min_length)
        if max_length:
            max_length = int(max_length)
            if min_length > max_length:
                max_length_replacement = min_length + 10
                warnings.warn(f"Invalid string length range: ({min_length}, {max_length}). The range will be changed to: ({min_length}, {max_length_replacement}).", stacklevel=2)
                max_length = max_length_replacement
        else:
            max_length = min_length + 10
    else:
        if max_length:
            max_length = int(max_length)
            min_length = max_length - 5 if max_length > 5 else 0
        else:
            min_length, max_length = 8, 15

    # If a pattern is not present, use this one
    pattern = '^([a-zA-Z0-9])*'
    # Try to find a value that is not allready generated 10 times, if u cant, give up.
    for i in range(10):
        length = random.randint(min_length, max_length)
        strp = ''
        while len(strp) < length:
            strp = strp + _randone(parse(pattern))
        if len(strp) > length:
            strp = strp[:length]
        if strp not in existing_values:
            return Literal(strp)
        
    return None


"""
    Generate a random value based on the specified constraints for a given SHACL property.

    Parameters:
    - datatype (URIRef): The datatype of the SHACL property.
    - min_exclusive, min_inclusive, max_exclusive, max_inclusive: Numeric constraints for the property.
    - min_length, max_length: String length constraints.
    - pattern (str): Regular expression pattern for string values.
    - equals, disjoint, less_than, less_than_or_equals, has_value: Specific constraints for certain values.
    - path (URIRef): SHACL path for the property.
    - sh_class (URIRef): SHACL class to which the property belongs.

    Returns:
    - Literal or None: The generated RDF literal value for the SHACL property, or None if it cannot be generated.

    Explanation:
    - The function starts by extracting the specific class (cl) and property path (path) from the given SHACL class.
    - It handles special cases and applies standard constraints based on the SHACL class and property path.
    - For specific properties like 'isbn', 'numberOfPages', 'abridged', 'bookEdition', 'date', 'number', 'email',
      and 'telephone', it sets standard data types and patterns if not explicitly specified.
    - If constraints like 'equals' are specified, the function returns the specified value.
    - For different data types (integer, decimal, boolean, date, string), it invokes specific helper functions
      to generate values based on constraints.
    - The function returns the generated value or None if a value cannot be generated based on constraints.
"""


def generate_default_value(existing_values, datatype, min_exclusive, min_inclusive, max_exclusive, max_inclusive, min_length, max_length,
                           pattern, equals, disjoint, less_than, less_than_or_equals, path, sh_class):

    # Return specified value if 'equals' constraint is present
    if equals:
        return equals

    # Extract the class and property path from URIs
    cl = str(sh_class).split('/')[-1]
    path = str(path).split('/')[-1]

    # Apply default datatype and pattern for certain property paths
    if ('date' in path or 'Date' in path) and not datatype:
        datatype = XSD.date
    elif ('number' in path or 'Number' in path) and not datatype:
        datatype = XSD.integer

    # Apply default patterns for certain property paths
    elif 'email' in path and not pattern:
        pattern = '([a-z0-9]+[_])*[A-Za-z0-9]@gmail.com'
    elif 'telephone' in path and not pattern:
        pattern = '^(([0-9]{3})|[0-9]{3}-)[0-9]{3}-[0-9]{4}$'

    # Special handling for certain properties and their constraints
    if cl == 'Person':
        if 'taxID' == path and not pattern:
            pattern = '[0-9]{9}'
    if cl == 'Book':
        if 'isbn' in path and not pattern:
            pattern = '[0-9]{3}-[0-9]-[0-9]{2}-[0-9]{6}-[0-9]'
        elif 'numberOfPages' in path and not datatype:
            datatype = XSD.integer
            if not min_inclusive:
                min_inclusive = 100
        elif 'abridged' in path and not datatype:
            datatype = XSD.boolean
        elif 'bookEdition' in path and not datatype:
            datatype = XSD.integer

    # Generate values based on datatype and constraints
    if datatype in INTEGER_DATATYPES:
        return generate_integer(existing_values, min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than,
                                less_than_or_equals, datatype)
    elif datatype in DECIMAL_DATATYPES:
        return generate_decimal(existing_values, min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than,
                                less_than_or_equals, datatype)
    elif datatype == XSD.boolean:
        return Literal(bool(random.getrandbits(1)))
    elif datatype in TEMPORAL_DATATYPES:
        return generate_temporal(existing_values, datatype, min_exclusive, min_inclusive, max_exclusive, max_inclusive,
                                 less_than, less_than_or_equals)

    # Default case: Generate a string value
    return generate_string(existing_values, min_length, max_length, pattern)


"""
    Function Explanation:
    ---------------------
    The 'get_predefined_value' function generates predefined values for specific SHACL properties based on the provided
    constraints. It handles different cases for SHACL classes such as 'Person', 'Book', 'Movie', and 'TVSeries' and
    generates values accordingly.

    Parameters:
    -----------
    sh_path (rdflib.term.Identifier): SHACL property for which to generate a predefined value.
    sh_class (rdflib.term.Identifier): SHACL class to which the property belongs.
    dependencies (dict): Dictionary containing required dependencies for generating predefined values.

    Returns:
    --------
    rdflib.term.Literal or None: The generated predefined value or None if a predefined value cannot be generated.

    Explanation:
    ------------
    - The function starts by extracting the specific property ('prop') and class ('cl') from the given SHACL path and class.
    - For each case (class-property combination), it generates a predefined value using the 'values_dict' dictionary.
    - The function supports various properties such as 'givenName', 'familyName', 'name', 'streetAddress', 'gender',
      'jobTitle', 'bookTitle', 'bookAward', 'bookGenre', 'movieTitle', 'movieAward', 'movieGenre', 'tvSeriesTitle', etc.
    - 'random.choice' is used to select values from predefined data, ensuring diversity in the generated values.
    - The function returns the generated predefined value or None if a predefined value cannot be generated for the given constraints.
"""


def generate_intuitive_value(sh_path, sh_class, dependencies):

    # Handle cases for Person class
    if sh_class == SCH.Person:
        gender = URIRef(SCH.gender)
        given_name = URIRef(SCH.givenName)
        family_name = URIRef(SCH.familyName)
        name = URIRef(SCH.name)

        if sh_path == SCH.additionalName or sh_path == SCH.givenName:
            # Generate predefined value based on gender dependency
            gender = str(dependencies.get(gender, ["none"])[0])
            if gender in (SCH.Female, 'female', 'f', 'fem'):
                return Literal(random.choice(dataset_dictionary.get('givenNameFemale')))
            elif gender in (SCH.Male, 'male', 'm'):
                return Literal(random.choice(dataset_dictionary.get('givenNameMale')))
            else:
                return Literal(
                    random.choice(dataset_dictionary.get('givenNameMale') + dataset_dictionary.get('givenNameFemale')))

        if sh_path == SCH.email:
            given_name = dependencies.get(given_name)
            family_name = dependencies.get(family_name)
            name = dependencies.get(name)

            # Generate email based on given_name, family_name, or name dependencies
            if given_name and family_name:
                return Literal(given_name[0].lower() + "_" + family_name[0].lower() + "@gmail.com")
            elif name:
                email = ""
                for p in name[0].split(' '):
                    email = email + p.lower()
                return Literal(email + "@gmail.com")
            elif given_name:
                return Literal(given_name[0].lower() + "_" + str(random.randrange(100, 1000)) + "@gmail.com")

        # Handle other properties for Person class
        if sh_path == SCH.familyName:
            return Literal(random.choice(dataset_dictionary.get('familyName')))
        if sh_path == SCH.name:
            gender = str(dependencies.get(gender, ["none"])[0])
            if gender in (SCH.Female, 'female', 'f', 'fem'):
                return Literal(random.choice(dataset_dictionary.get('givenNameFemale')) + " " + random.choice(
                    dataset_dictionary.get('familyName')))
            elif gender in (SCH.Male, 'male', 'm'):
                return Literal(random.choice(dataset_dictionary.get('givenNameMale')) + " " + random.choice(
                    dataset_dictionary.get('familyName')))
            else:
                return Literal(
                    random.choice(dataset_dictionary.get('givenNameMale') + dataset_dictionary.get('givenNameFemale')) +
                    " " + random.choice(dataset_dictionary.get('familyName')))
        if sh_path == SCH.streetAddress:
            return Literal(
                "no. " + str(random.randint(1, 100)) + " " + random.choice(dataset_dictionary.get('streetAddress')))
        if sh_path == SCH.gender:
            return Literal(random.choice(dataset_dictionary.get('gender')))
        if sh_path == SCH.jobTitle:
            return Literal(random.choice(dataset_dictionary.get('jobTitle')))

    # Handle cases for Book class
    elif sh_class == SCH.Book:
        # Handle properties for Book class
        if sh_path == SCH.name:
            return Literal(random.choice(dataset_dictionary.get("bookTitle")))
        if sh_path == SCH.award:
            return Literal(random.choice(dataset_dictionary.get('bookAward')))
        if sh_path == SCH.genre:
            return Literal(random.choice(dataset_dictionary.get('bookGenre')))
        if sh_path == SCH.bookEdition:
            return getBookFormat()

    # Handle cases for Movie class
    elif sh_class == SCH.Movie:
        # Handle properties for Movie class
        if sh_path == SCH.name:
            return Literal(random.choice(dataset_dictionary.get("movieTitle")))
        if sh_path == SCH.award:
            return Literal(random.choice(dataset_dictionary.get('movieAward')))
        if sh_path == SCH.genre:
            return Literal(random.choice(dataset_dictionary.get('movieGenre')))

    # Handle cases for TVSeries class
    elif sh_class == SCH.TVSeries:
        # Handle properties for TVSeries class
        if sh_path == SCH.name:
            return Literal(random.choice(dataset_dictionary.get("tvSeriesTitle")))
        if sh_path == SCH.genre:
            return Literal(random.choice(dataset_dictionary.get('movieGenre')))

    return None
