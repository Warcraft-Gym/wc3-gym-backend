"""Checks on the mapping itself, independent of any request.

A relationship that needs foreign_keys names its columns in a string, for
example "[Series.match_id]". SQLAlchemy resolves that string the first
time the class is queried, so a wrong name would otherwise surface as a
failing request rather than as a failing test.
"""

import importlib
import pkgutil

from sqlalchemy.orm import configure_mappers

import app.models


def import_all_models() -> None:
    for module in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{module.name}")


def test_every_mapping_resolves() -> None:
    import_all_models()
    configure_mappers()
