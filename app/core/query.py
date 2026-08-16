"""The query language the /search routes accept, for example
"season_id == 3 and name ilike smith".

A value reaches the parser as text, so the parser reads " and " and " or "
inside a value as part of the query. Use the services' find_by_ methods
for a value the caller supplies; keep this for a query a client wrote.
"""

import re
from typing import Self, cast

from sqlalchemy import ColumnElement, and_, or_

from app.core.exceptions import BadRequestError
from app.models.base import DBModel


class ConcatenationType:
    # The three members below, assigned right after the class body.
    OR: "ConcatenationType"
    QUERY: "ConcatenationType"
    AND: "ConcatenationType"

    _instances: dict[str, "ConcatenationType"] = {}
    value: str

    def __new__(cls, value: str, *args: object, **kwargs: object) -> Self:
        if value not in cls._instances:
            instance = super().__new__(cls, *args, **kwargs)
            instance.value = value
            cls._instances[value] = instance
        # The shared cache holds a cls only because nothing subclasses this
        return cast(Self, cls._instances[value])

    def __repr__(self) -> str:
        return f"ConcatenationType({self.value})"


# Predefined instances
ConcatenationType.OR = ConcatenationType("OR")
ConcatenationType.QUERY = ConcatenationType("QUERY")
ConcatenationType.AND = ConcatenationType("AND")


class QueryElement:
    """One node of the parsed query tree. A QUERY node holds a single
    condition in elementA; an AND/OR node holds a subtree on each side."""

    def __init__(self) -> None:
        self.type: ConcatenationType | None = None
        self.elementA: QueryElement | QueryCondition | None = None
        self.elementB: QueryElement | QueryCondition | None = None

    def setQueryElement(self, elem: "QueryElement | QueryCondition") -> None:
        if not self.elementA:
            self.elementA = elem
        else:
            self.elementB = elem

    def __str__(self) -> str:
        return f"QueryElement(type={self.type}, elementA={self.elementA}, elementB={self.elementB})"


class QueryCondition:
    def __init__(self, operator: str, key: str, value: str | bool) -> None:
        self.operator = operator
        self.key = key
        self.value = value

    def __str__(self) -> str:
        return f"QueryCondition(key={self.key}, operator={self.operator}, value={self.value})"


class QueryUtil:
    @staticmethod
    def parseQuery(query: str | None) -> QueryElement | None:
        if not query:
            return None
        result = QueryElement()
        QueryUtil.find_and_split(result, query)
        return result

    @staticmethod
    def convertToQueryCondition(query: str) -> QueryCondition:
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
            raise BadRequestError(
                f"Query or subquery could not be parsed into <key operator value> only following operators are allowed (==|!=|>=|<=|>|<|ilike): {query}"
            )
        return QueryCondition(operator, key, value)

    @staticmethod
    def createClassQuery(
        cls: type[DBModel], query: QueryCondition
    ) -> ColumnElement[bool] | None:
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
    def convertQueryToDBFilter(
        cls: type[DBModel], query: QueryElement | None
    ) -> ColumnElement[bool] | None:
        if not query:
            return None
        return QueryUtil.convertQueryToDBFilter_Rec(cls, query)

    @staticmethod
    def convertQueryToDBFilter_Rec(
        cls: type[DBModel], query: QueryElement | None
    ) -> ColumnElement[bool] | None:
        if not query:
            return None
        # QUERY nodes hold a condition, AND/OR nodes hold two QueryElements
        if query.type == ConcatenationType.QUERY:
            return QueryUtil.createClassQuery(cls, cast(QueryCondition, query.elementA))
        queryA = QueryUtil.convertQueryToDBFilter_Rec(
            cls, cast(QueryElement | None, query.elementA)
        )
        queryB = QueryUtil.convertQueryToDBFilter_Rec(
            cls, cast(QueryElement | None, query.elementB)
        )
        if queryA is None or queryB is None:
            return None
        if query.type == ConcatenationType.OR:
            return or_(queryA, queryB)
        elif query.type == ConcatenationType.AND:
            return and_(queryA, queryB)
        return None

    @staticmethod
    def find_and_split(concatCondition: QueryElement, query: str) -> None:
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
