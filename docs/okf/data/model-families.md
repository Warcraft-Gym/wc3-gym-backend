---
type: Data Model
title: Model families
description: Every entity is a family of SQLModel classes, one table class and separate Create, Update and Public shapes, with validators in one module and every datetime aware UTC.
resource: ../../../app/models/base.py
tags: [data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-23T12:00:00Z }
sources:
  - id: base
    resource: ../../../app/models/base.py
    title: DBModel, PublicModel, Stored
  - id: types
    resource: ../../../app/models/types.py
    title: The validators and the UTC datetime type
  - id: user
    resource: ../../../app/models/user.py
    title: A worked example of a family
---

# One family per entity

| Class | Role |
|---|---|
| `XBase(SQLModel)` | the fields shared by the table and the shapes |
| `X(XBase, DBModel, table=True)` | the table. `id: int | None` because a row exists before the database assigns its key. Relationships live here. |
| `XCreate(XBase)` | what a client sends to create. Required fields are required here. Never carries `id`. |
| `XUpdate(SQLModel)` | every field optional. The service applies `model_dump(exclude_unset=True)`, so a key left out keeps its stored value. |
| `XPublic(XBase, PublicModel)` | what the API answers. `id: int` because the client can rely on it. Derived fields are filled by `app/services/derived.py`. |

An update path takes an `XUpdate` built from the fields it means to change, never an `XPublic` read back. One schema doing create, update and response duty wiped columns silently; see [the pitfall](../pitfalls/one-schema-wipes-columns.md).

Some tables have a table class and a Public class with `Write` shapes for the admin forms instead of the Base/Create/Update trio (`EventStage`, `EventEntrant`, `EventDivision`). Join tables are named `DB*` (`DBTeamSeason`, `DBUserTeamSeason`, `DBMapSeason`) and carry no Public shape of their own. The class of the `event` table is `Season`, because the GNL payloads keep that word. Every table has one concept under [tables](tables/index.md) that lists its columns.

`DBModel` holds the shared query helpers (`getById`, finders); `PublicModel` also answers a plain dict. `Stored` is a protocol for a mapped row whose id is set, and `ident()` types it.

# Validators

`app/models/types.py` holds the validators the shapes reuse as `Annotated` markers. The input validators sit on the input models (`XCreate`, `XUpdate`, the `Write` shapes, `ProfileUpdate`): `NumToStr` (the workbook import sends numeric cells), `MapRules`, `KnownScoreSystem`, `KnownTimeZone`, `PlacePoints`, `TwitchChannel`, `YouTubeChannel`, and `RoundToInt` on `W3CStatsCreate` (the ladder sends fractions). A field that carries one is declared plainly on `XBase` and again, with the validator, on the input model. An input validator's input is public JSON, so it takes any value and hands an unknown one back for pydantic to refuse with a 422.

A response model is built from stored rows and carries the output validators, `EnumValue` and `NoneToList`. It never re-runs one of the input rules above, so a stored value that an input rule refuses still reads back. Two markers still reach responses through a shared base: `AwareUTC`, which only reads a stored datetime as UTC, and `SuggestRace` on the off races of `SeriesBase`, which passes every stored race.

# Datetimes

Every stored datetime is `timestamptz` through `UTCDateTime`, and every input field is `AwareUTC`: a bare value is read as UTC, a zoned value is converted, and a stored value reads back aware on SQLite and Postgres alike. Responses end in `Z`. `utcnow()` in `types.py` is the one clock. See [the pitfall](../pitfalls/datetimes-are-utc.md).

# Relationships

A relationship names its foreign keys as a string when SQLAlchemy needs them, `"[Series.match_id]"`, and `tests/test_models.py` resolves every one so a wrong name fails as a test and not as a request. Loader options are pinned per Public shape (`_eager_options`) and the query budget test counts them. Two sibling eager loads run in hash order, so a test that captures SQL treats the statements after the first as a set.

# Pictures are URLs

No mapped column holds bytes. `teams.icon_url` and `maps.image` hold public URLs into the blob store. `tests/test_blob_budget.py` fails on any binary column. See [pictures and replays](../concepts/pictures-and-replays.md).

# Response annotation is the response model

FastAPI builds the response model from a handler's return annotation and re-serializes every body with it. A union that mixes a `Response` with anything else fails at import. A handler that answers a `Response` or a plain dict on different paths carries `response_model=None`.
