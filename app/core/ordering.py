from typing import Any, Literal

from sqlalchemy import ColumnElement, Select

SortOrder = Literal["asc", "desc"]


def ordered[SelectT: Select[Any]](
    statement: SelectT,
    sort_map: dict[Any, ColumnElement[Any]],
    sort: str | None,
    order: SortOrder,
    *default: ColumnElement[Any],
) -> SelectT:
    """Order the statement by the column sort names, then by the default chain.

    A sort of None leaves the statement with the default chain alone.
    """
    if sort is not None:
        column = sort_map[sort]
        statement = statement.order_by(
            column.desc() if order == "desc" else column.asc()
        )
    return statement.order_by(*default)
