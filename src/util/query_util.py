import re

from sqlalchemy import and_, or_


class ConcatenationType:
    _instances = {}

    def __new__(cls, value, *args, **kwargs):
        if value not in cls._instances:
            instance = super().__new__(cls, *args, **kwargs)
            instance.value = value
            cls._instances[value] = instance
        return cls._instances[value]

    def __repr__(self):
        return f"ConcatenationType({self.value})"


# Predefined instances
ConcatenationType.OR = ConcatenationType("OR")
ConcatenationType.QUERY = ConcatenationType("QUERY")
ConcatenationType.AND = ConcatenationType("AND")


class QueryElement:
    def __init__(self):
        self.type = None
        self.elementA = None
        self.elementB = None

    def setQueryElement(self, elem):
        if not self.elementA:
            self.elementA = elem
        else:
            self.elementB = elem

    def __str__(self):
        return f"QueryElement(type={self.type}, elementA={self.elementA}, elementB={self.elementB})"


class QueryCondition:
    def __init__(self, operator, key, value):
        self.operator = operator
        self.key = key
        self.value = value

    def __str__(self):
        return f"QueryCondition(key={self.key}, operator={self.operator}, value={self.value})"


class QueryUtil:
    @staticmethod
    def parseQuery(query):
        if not query:
            return None
        result = QueryElement()
        QueryUtil.find_and_split(result, query)
        return result

    @staticmethod
    def convertToQueryCondition(query):
        pattern = r"(\w+)\s*(==|!=|>=|<=|>|<|ilike)\s*(.+)"
        match = re.match(pattern, query)
        if match:
            key = match.group(1)
            operator = match.group(2)
            value = match.group(3)
            if value and value == "True":
                value = True
            elif value and value == "False":
                value = False
        else:
            raise Exception(
                f"Query or subquery could not be parsed into <key operator value> only following operators are allowed (==|!=|>=|<=|>|<|ilike): {query}"
            )
        return QueryCondition(operator, key, value)

    @staticmethod
    def createClassQuery(cls, query):
        filter = None
        column = getattr(cls, query.key, None)
        if column is not None:
            if query.operator == "==":
                filter = column == query.value
            elif query.operator == "!=":
                filter = column != query.value
            elif query.operator == ">":
                filter = column > query.value
            elif query.operator == ">=":
                filter = column >= query.value
            elif query.operator == "<":
                filter = column < query.value
            elif query.operator == "<=":
                filter = column <= query.value
            elif query.operator == "ilike":
                filter = column.ilike(f"%{query.value}%")
        return filter

    @staticmethod
    def convertQueryToDBFilter(cls, query):
        if not query:
            return None
        return QueryUtil.convertQueryToDBFilter_Rec(cls, query)

    @staticmethod
    def convertQueryToDBFilter_Rec(cls, query):
        if not query:
            return None
        if query.type == ConcatenationType.QUERY:
            return QueryUtil.createClassQuery(cls, query.elementA)
        queryA = QueryUtil.convertQueryToDBFilter_Rec(cls, query.elementA)
        queryB = QueryUtil.convertQueryToDBFilter_Rec(cls, query.elementB)
        if queryA is None or queryB is None:
            return None
        if query.type == ConcatenationType.OR:
            return or_(queryA, queryB)
        elif query.type == ConcatenationType.AND:
            return and_(queryA, queryB)
        return None

    @staticmethod
    def find_and_split(concatCondition, query):
        # Define the regex pattern to match " or " or " and "
        pattern_and = r"\s+((?i:and))\s+"
        pattern_or = r"\s+((?i:or))\s+"

        # Find the first occurrence of the pattern
        match = re.search(pattern_or, query)

        # Base case: if no match is found, return the query itself
        if not match:
            # Find the first occurrence of the pattern
            match = re.search(pattern_and, query)

            if not match:
                concatCondition.type = ConcatenationType.QUERY
                concatCondition.setQueryElement(
                    QueryUtil.convertToQueryCondition(query)
                )
                return

        # Split the string at the match
        left = query[: match.start()]
        right = query[match.end() :]

        operator = match.group(1).lower()
        if operator == "and":
            concatCondition.type = ConcatenationType.AND
        else:
            concatCondition.type = ConcatenationType.OR

        # Recursively process the left and right parts
        condA = QueryElement()
        QueryUtil.find_and_split(condA, left)
        concatCondition.setQueryElement(condA)
        condB = QueryElement()
        QueryUtil.find_and_split(condB, right)
        concatCondition.setQueryElement(condB)
        return
