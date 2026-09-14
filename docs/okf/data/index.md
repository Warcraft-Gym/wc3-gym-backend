# Data model

* [Migrations](migrations.md) - Alembic owns the schema, the production build migrates while the old code serves, a preview gets its own database copy, and one head is allowed at a time.
* [Model families](model-families.md) - Every entity is a family of SQLModel classes, one table class and separate Create, Update and Public shapes, with validators in one module and every datetime aware UTC.
* [Tables](tables/index.md) - The 40 tables, grouped by what they serve, one concept each with every column and its meaning.
