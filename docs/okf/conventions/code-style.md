---
type: Convention
title: Code style
description: Python 3.13, uv, ruff with annotations, ty as a ratchet, one-line comments in the present tense, and no scripts folder.
resource: ../../../pyproject.toml
tags: [tooling]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: pyproject
    resource: ../../../pyproject.toml
    title: Project metadata, ruff and ty rules
  - id: justfile
    resource: ../../../justfile
    title: The recipes CI runs
---

# Toolchain

- Python 3.13 or newer. `requires-python` has a floor and no ceiling: the deployed version is pinned by the runtime, not by the project file.
- `uv` manages the interpreter, the virtual environment and the lock file. Run everything through `uv run`, including one-off scripts. The system `python3` is older than the floor and fails on the syntax.
- `just` runs the recipes. The dev dependencies install it as `rust-just`, so `uv run just <recipe>` works without a system install.

# Lint and types

- `uv run just lint` runs `ruff format --check` and `ruff check`. CI runs the same recipe. `extend-select = ["ANN", "N", "FURB"]` means every function is annotated, names follow PEP 8, and refurb's modernisations apply.
- `uv run just typecheck` runs `ty` over `app` and `tests`. It is its own CI job, kept apart from lint because a type failure needs thought and a lint failure fixes itself with `just fmt`.
- `[tool.ty.rules]` is a ratchet. A rule sits at `ignore` while it still fails; each one flips to `error` in its own pull request once its diagnostics are fixed. Never flip a rule back to `ignore`.
- SQLModel types a class attribute as its instance value. Three helpers give an expression its real type: `sqlmodel.col()` at a column site, `app.core.db.rel()` at a loader option, `app.models.base.ident()` for a stored row's id. Use them in new code; ty flags the omission.

# Typing

- `X | None`, never `Optional`. `list[X]` and `dict[K, V]`, never `List` and `Dict`. `collections.abc` for `Sequence`, `Iterable` and `Iterator`.
- One exception: a SQLModel `Relationship` whose target class is importable only under `TYPE_CHECKING` keeps `Optional["X"]`. Quoting the whole union (`"X | None"`) breaks every mapper. See [the pitfall](../pitfalls/sqlmodel-relationship-quoting.md).
- A function that hands an arbitrary value through is a PEP 695 generic, `def f[T](value: T) -> str | T`, not `Any`. `Any` is fine inside a container type such as `dict[str, Any]`.
- The only `typing` imports in the app are `Any`, `TYPE_CHECKING`, `Annotated`, `Self` and `cast`.

# Comments and prose

- A comment describes the current state in the present tense. It never says "previously", "we used to", or "TODO". What changed and why belongs in the pull request.
- A comment fits on one line, as a trailing tag where it can: `extend-select = ["ANN"]  # flake8-annotations`. Two lines is the ceiling. A paragraph belongs in a document.
- Docstrings follow the same rule. A module docstring says what the module does and what a caller must do or must not do.
- Every piece of prose, in code, in pull requests and in this bundle, uses plain words and short sentences. See [the writing rule](okf-bundle.md).
- Use the words the code uses today: "Public models", "model families", "eager-load options". Not "DTO", not "schemas layer". The events vocabulary is in [vocabulary](../concepts/vocabulary.md).

# What not to add

- No `scripts/` folder. An operational step is a `just` recipe that imports the app and calls the real service, so the shipped path is what runs. See [runbooks](../runbooks/index.md).
- No configuration knob that restates a library default. State the default in a comment instead. Keep only a setting that differs from the default and has a reason on the same line.
- No fix at the symptom layer. A memory problem is fixed in the query, not with a garbage-collector call per request. A runtime mitigation that is really needed goes in operations configuration, never in application code.
- No hand-written parser over a binary format the app does not own. Reading a documented header is fine; walking records is not, without approval.
