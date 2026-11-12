import csv
import math
import random
from exrex import *
from exrex import _randone
from rdflib import XSD, Literal, URIRef, Namespace
from datetime import date
from decimal import Decimal
from dateutil.relativedelta import relativedelta
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


def get_date_between_two_dates(date1, date2):
    days_between = relativedelta(date2, date1).days
    months_between = relativedelta(date2, date1).months
    years_between = relativedelta(date2, date1).years

    increase = random.random()
    new_days = relativedelta(days=int(days_between * increase))
    new_months = relativedelta(months=int(months_between * increase))
    new_years = relativedelta(years=int(years_between * increase))

    between_date = date1 + new_years + new_months + new_days
    return between_date


def add_to_date(date1, years, months, days):
    time_addition = relativedelta(days=days, months=months, years=years)
    return time_addition + date1


# The min_length, max_length, pattern, disjoint, has_value properties are not taken into account at this point for date
# generation
def generate_date(existing_values, min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than, less_than_or_equals):
    min_date, max_date = None, None
    if min_inclusive or min_exclusive:
        min_date = date.fromisoformat(min_inclusive) if min_inclusive else add_to_date(
            date.fromisoformat(min_exclusive), 0, 0, +1)
    if max_inclusive or max_exclusive:
        max_date = date.fromisoformat(max_inclusive) if max_inclusive else add_to_date(
            date.fromisoformat(max_exclusive), 0, 0, -1)
    if less_than_or_equals and len(less_than_or_equals) > 0:
        max_date = date.fromisoformat(min(less_than_or_equals))
    if less_than and len(less_than) > 0:
        max_date = date.fromisoformat(min(less_than))
    if max_date:
        if min_date:
            if max_date < min_date:
                # raise Exception("A conflicting date definition")
                min_date_replacement = add_to_date(max_date, -50, 0, 0)
                warnings.warn(f"Invalid date range: ({min_date}, {max_date}). The range will be changed to: ({min_date_replacement}, {max_date}).", stacklevel=2)
                min_date = min_date_replacement
        else:
            min_date = add_to_date(max_date, -50, 0, 0)
    else:
        if not min_date:
            min_date = date.fromisoformat('1970-07-07')
        max_date = add_to_date(min_date, 50, 0, 0)
    
    # Find a value in interval that is not allready generated
    date_value_down = date_value_up = get_date_between_two_dates(min_date, max_date)

    while date_value_up <= max_date:
        if date_value_up not in existing_values:
            return date_value_up
        date_value_up = add_to_date(date_value_up, 0, 0, 1)
        
    while date_value_down >= min_date:
        if date_value_down not in existing_values:
            return date_value_down
        date_value_down = add_to_date(date_value_down, 0, 0, -1)

    return None



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


def _numeric_bounds(min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than, less_than_or_equals):
    """
    The strictest lower and upper bound of a number, each as (value, exclusive) or None, from the value range
    constraints and the values of the sh:lessThan and sh:lessThanOrEquals properties.
    """
    lower = [(_python(bound), exclusive) for bound, exclusive in ((min_inclusive, False), (min_exclusive, True))
             if bound is not None]
    upper = [(_python(bound), exclusive) for bound, exclusive in ((max_inclusive, False), (max_exclusive, True))
             if bound is not None]
    upper += [(_python(value), True) for value in less_than or []]
    upper += [(_python(value), False) for value in less_than_or_equals or []]
    # the highest lower bound and the lowest upper bound; of two equal bounds, the exclusive one
    return max(lower, default=None), min(upper, key=lambda bound: (bound[0], not bound[1]), default=None)


# The min_length, max_length, pattern, disjoint, has_value properties are not taken into account at this point for
# integer generation
def generate_integer(existing_values, min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than,
                     less_than_or_equals, datatype=XSD.integer):
    lower, upper = _numeric_bounds(min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than,
                                   less_than_or_equals)
    min_int = None if lower is None else math.floor(lower[0]) + 1 if lower[1] else math.ceil(lower[0])
    max_int = None if upper is None else math.ceil(upper[0]) - 1 if upper[1] else math.floor(upper[0])

    # the value range of the datatype; a lower limit of 0 or more (e.g. of xsd:positiveInteger) and an upper limit
    # of 0 or less (e.g. of xsd:negativeInteger) also apply when the shape gives no bound
    lowest, highest = INTEGER_DATATYPES.get(datatype, (None, None))
    if lowest is not None and (min_int is not None or lowest >= 0):
        min_int = lowest if min_int is None else max(min_int, lowest)
    if highest is not None and (max_int is not None or highest <= 0):
        max_int = highest if max_int is None else min(max_int, highest)

    if max_int is not None:
        if min_int is not None:
            if max_int < min_int:
                min_int_replacement = max_int - 50
                warnings.warn(f"Invalid int range: ({min_int}, {max_int}). The range will be changed to: ({min_int_replacement}, {max_int}).", stacklevel=2)
                min_int = min_int_replacement
        else:
            min_int = max_int - 50
    else:
        if min_int is None:
            min_int = 1
        max_int = min_int + 50

    # the default range of values may exceed the range of the datatype (e.g. xsd:byte with sh:minInclusive 100)
    if lowest is not None:
        min_int = max(min_int, lowest)
    if highest is not None:
        max_int = min(max_int, highest)
    if min_int > max_int:
        warnings.warn(f"The value range of the property is outside the range of {datatype}, so no value is "
                      f"generated.", stacklevel=2)
        return None

    # Find a value in interval that is not allready generated
    int_value_down = int_value_up = random.randint(min_int, max_int)

    while int_value_up <= max_int:
        if int_value_up not in existing_values:
            return Literal(int_value_up, datatype=datatype)
        int_value_up += 1

    while int_value_down >= min_int:
        if int_value_down not in existing_values:
            return Literal(int_value_down, datatype=datatype)
        int_value_down -= 1

    return None


# The min_length, max_length, pattern, disjoint, has_value properties are not taken into account at this point for
# decimal generation
def generate_decimal(existing_values, min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than,
                     less_than_or_equals, datatype=XSD.decimal):
    lower, upper = _numeric_bounds(min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than,
                                   less_than_or_equals)
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
    elif datatype == XSD.date:
        date = generate_date(existing_values, min_exclusive, min_inclusive, max_exclusive, max_inclusive, less_than,
                                     less_than_or_equals)
        if date: 
            return Literal(date)
        return None

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
