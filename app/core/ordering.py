from collections.abc import Mapping
from typing import Any, Literal

from sqlalchemy import Select, SQLColumnExpression

SortOrder = Literal["asc", "desc"]


def ordered[SelectT: Select[Any]](
    statement: SelectT,
    sort_map: Mapping[Any, SQLColumnExpression[Any]],
    sort: str | None,
    order: SortOrder,
    *default: SQLColumnExpression[Any],
) -> SelectT:
    """Order the statement by the column sort names, then by the default chain.

    A sort of None leaves the statement with the default chain alone.
    """
    if sort is not None:
        column = sort_map[sort]
        # A null leads the ascending page and closes the descending one on
        # every database; Postgres alone would put it at the other end.
        statement = statement.order_by(
            column.desc().nulls_last()
            if order == "desc"
            else column.asc().nulls_first()
        )
    return statement.order_by(*default)
