# Conventions

* [Code style](code-style.md) - Python 3.13, uv, ruff with annotations, ty as a ratchet, one-line comments in the present tense, and no scripts folder.
* [Git and pull requests](git-and-pull-requests.md) - One branch and one pull request per change, squash merged to main, with a migration rule that keeps the previous deploy alive during the build.
* [How this bundle is written](okf-bundle.md) - The rules for every file under docs/okf, and the one rule for talking about the other repositories.
* [Layering](layering.md) - Routes call services, services own their transactions, models hold the schema and the shapes, and pure rules live in app/core.
* [Testing](testing.md) - The suite migrates a temporary SQLite file with Alembic, opens no socket, and holds guard tests that pin contracts, statement counts and memory.
