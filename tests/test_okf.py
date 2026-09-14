"""The docs/okf bundle conforms to OKF v0.2 and is safe to publish: every
concept has a type, index files carry no frontmatter (the root one only its
version), every relative link and source path resolves, every table has a
concept whose Schema lists exactly its columns, and no file holds an id, a
credential or a hostname."""

import re
from pathlib import Path

import pytest
from sqlmodel import SQLModel

import app.models  # noqa: F401  registers every table

BUNDLE = Path(__file__).resolve().parents[1] / "docs" / "okf"
LINK = re.compile(r"\]\(([^)\s]+)\)")
RESOURCE = re.compile(r"^\s*resource: (\S+)\s*$", re.MULTILINE)

files = sorted(BUNDLE.rglob("*.md"))


def frontmatter(text: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    return text[4:end] if end > 0 else None


@pytest.mark.parametrize("path", files, ids=lambda p: str(p.relative_to(BUNDLE)))
def test_concept_frontmatter(path: Path) -> None:
    text = path.read_text()
    fm = frontmatter(text)
    if path.name == "index.md":
        allowed = 'okf_version: "0.2"' if path.parent == BUNDLE else None
        assert fm is None or fm.strip() == allowed, "index.md carries no frontmatter"
        return
    if path.name == "log.md":
        assert fm is None, "log.md carries no frontmatter"
        return
    assert fm is not None, "a concept starts with a YAML block"
    kind = re.search(r"^type: (.+)$", fm, re.MULTILINE)
    assert kind and kind.group(1).strip(), "a concept names its type"


@pytest.mark.parametrize("path", files, ids=lambda p: str(p.relative_to(BUNDLE)))
def test_links_resolve(path: Path) -> None:
    text = path.read_text()
    targets = LINK.findall(text) + RESOURCE.findall(text)
    for target in targets:
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        if not target.startswith((".", "/")):
            continue  # a scope descriptor, not a path
        clean = target.split("#")[0]
        assert (path.parent / clean).exists(), f"{target} does not resolve"


CONCEPTS = [p for p in files if p.name not in ("index.md", "log.md")]
INDEXES = [p for p in files if p.name == "index.md"]
# YAML reads a bare `a: b` value as a nested key, so a value that holds `: ` is quoted
UNQUOTED_COLON = re.compile(r"^\s*(?:- )?[\w-]+: (?![\"'\[{|>]).*: ", re.MULTILINE)
INDEX_ENTRY = re.compile(r"^\* \[[^\]]+\]\(([^)]+)\) - (.+)$", re.MULTILINE)


def description(path: Path) -> str:
    found = re.search(
        r"^description: (.+)$", frontmatter(path.read_text()) or "", re.MULTILINE
    )
    assert found, f"{path.name} has no description"
    text = found.group(1).strip()
    return text[1:-1].replace('\\"', '"') if text.startswith('"') else text


@pytest.mark.parametrize("path", CONCEPTS, ids=lambda p: str(p.relative_to(BUNDLE)))
def test_concept_metadata(path: Path) -> None:
    fm = frontmatter(path.read_text()) or ""
    assert re.search(r"^title: \S", fm, re.MULTILINE), "a concept has a title"
    assert re.search(r"^tags: \[", fm, re.MULTILINE), "tags is a list"
    description(path)
    hit = UNQUOTED_COLON.search(fm)
    assert hit is None, f"quote the value: {hit.group().strip()!r}"


@pytest.mark.parametrize("path", INDEXES, ids=lambda p: str(p.relative_to(BUNDLE)))
def test_index_lists_its_directory(path: Path) -> None:
    listed = dict(INDEX_ENTRY.findall(path.read_text()))
    for concept in sorted(path.parent.glob("*.md")):
        if concept.name in ("index.md", "log.md"):
            continue
        assert concept.name in listed, f"{concept.name} is not in the index"
        assert listed[concept.name] == description(concept), (
            f"the index line for {concept.name} is not its description"
        )


# Content that must never appear in a public bundle: an id-shaped digit run, an
# email, a connection string, a token, a deployment hostname, an IP address.
SENSITIVE = re.compile(
    r"[0-9]{10,}"
    r"|[\w.+-]+@[\w-]+\.[a-z]{2,}"
    r"|(postgres(ql)?|mysql|redis|mongodb)://"
    r"|eyJ[A-Za-z0-9_-]{10,}"
    r"|\b(sk|pk|whsec|ghp|gho|github_pat)_[A-Za-z0-9]"
    r"|xox[bp]-"
    r"|Bearer [A-Za-z0-9._-]{20,}"
    r"|\.(vercel\.app|supabase\.co|azurewebsites\.net|ngrok\.io)\b"
    r"|\b(\d{1,3}\.){3}\d{1,3}\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize("path", files, ids=lambda p: str(p.relative_to(BUNDLE)))
def test_no_sensitive_content(path: Path) -> None:
    text = path.read_text()
    hit = SENSITIVE.search(text)
    assert hit is None, f"looks sensitive: {hit.group()!r}"


TABLES = BUNDLE / "data" / "tables"
SCHEMA_ROW = re.compile(r"^\| `(\w+)` \|", re.MULTILINE)


@pytest.mark.parametrize("table", sorted(SQLModel.metadata.tables))
def test_table_concept_lists_every_column(table: str) -> None:
    path = TABLES / f"{table}.md"
    assert path.exists(), f"docs/okf/data/tables/{table}.md is missing"
    _, found, rest = path.read_text().partition("\n# Schema\n")
    assert found, "a table concept has a # Schema section"
    listed = set(SCHEMA_ROW.findall(rest.split("\n# ", 1)[0]))
    columns = set(SQLModel.metadata.tables[table].columns.keys())
    assert listed == columns, (
        f"missing {sorted(columns - listed)}, stale {sorted(listed - columns)}"
    )


def test_every_table_concept_names_a_table() -> None:
    stray = (
        {p.stem for p in TABLES.glob("*.md")}
        - {"index"}
        - set(SQLModel.metadata.tables)
    )
    assert not stray, f"no such table: {sorted(stray)}"
