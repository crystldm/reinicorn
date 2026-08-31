"""Tests for reinicorn.corpus — the one kb walk and the one path contract."""

from __future__ import annotations

import pytest

from reinicorn.corpus import Doc, doc_path, iter_branch_dirs, iter_docs
from reinicorn.doc_types import REGISTRY, Addressing, DocType
from tests.conftest import doc_text

PHANTOM_SEQ = DocType(
    key="rfc", dir_path="rfcs", filename="RFC-{seq:04}-{slug}.md",
    protected=True, help_text="RFC ops", template_body="{sections}",
    addressing=Addressing.SLUG,
)


def _seed_kb(tmp_path):
    kb = tmp_path / "kb"
    scope = kb / "myrepo"
    (scope / "specs").mkdir(parents=True)
    (scope / "specs" / "one.md").write_text(doc_text(slug="one"))
    (scope / "specs" / "index.md").write_text("# not a doc\n")
    (scope / "exec-plans" / "active" / "br").mkdir(parents=True)
    (scope / "exec-plans" / "active" / "br" / "plan.md").write_text(
        doc_text(type="plan", slug="br", branch="br", body="\n## Goal\n\ng\n")
    )
    (scope / "exec-plans" / "active" / "empty-dir").mkdir()
    # Non-scope dirs must be skipped.
    (kb / "generated").mkdir()
    (kb / "generated" / "x.md").write_text("no frontmatter")
    (kb / "_shared").mkdir()
    (kb / "_shared" / "y.md").write_text("no frontmatter")
    return kb


def test_iter_docs_yields_docs_with_rows(tmp_path):
    kb = _seed_kb(tmp_path)
    docs = list(iter_docs(kb))
    by_name = {d.path.name: d for d in docs}
    assert set(by_name) == {"one.md", "plan.md"}
    assert by_name["one.md"].dt is not None
    assert by_name["one.md"].dt.key == "spec"
    assert by_name["one.md"].scope == "myrepo"
    assert by_name["one.md"].meta["slug"] == "one"
    assert by_name["plan.md"].dt.key == "plan"


def test_iter_docs_scope_filter(tmp_path):
    kb = _seed_kb(tmp_path)
    other = kb / "otherrepo" / "specs"
    other.mkdir(parents=True)
    (other / "two.md").write_text(doc_text(slug="two"))
    assert {d.scope for d in iter_docs(kb)} == {"myrepo", "otherrepo"}
    assert {d.scope for d in iter_docs(kb, scope="myrepo")} == {"myrepo"}


def test_iter_docs_unknown_type_yields_dt_none(tmp_path):
    kb = _seed_kb(tmp_path)
    (kb / "myrepo" / "specs" / "odd.md").write_text("no frontmatter here\n")
    odd = next(d for d in iter_docs(kb) if d.path.name == "odd.md")
    assert isinstance(odd, Doc)
    assert odd.dt is None
    assert odd.meta == {}


def test_doc_path_slug(tmp_path):
    p = doc_path(tmp_path, REGISTRY["spec"], "my-slug")
    assert p == tmp_path / "specs" / "my-slug.md"


def test_doc_path_branch_sanitizes(tmp_path):
    p = doc_path(tmp_path, REGISTRY["plan"], "feat/x", stage="active")
    assert p == tmp_path / "exec-plans" / "active" / "feat-x" / "plan.md"


def test_doc_path_staged_requires_stage(tmp_path):
    with pytest.raises(ValueError, match="stage"):
        doc_path(tmp_path, REGISTRY["plan"], "feat/x")


def test_doc_path_singleton(tmp_path):
    p = doc_path(tmp_path, REGISTRY["principle"])
    assert p == tmp_path / "golden-principles.md"


def test_doc_path_missing_ident_raises(tmp_path):
    with pytest.raises(ValueError, match="branch"):
        doc_path(tmp_path, REGISTRY["plan"], stage="active")
    with pytest.raises(ValueError, match="slug"):
        doc_path(tmp_path, REGISTRY["spec"])


def test_doc_path_refuses_creation_only_placeholders(tmp_path):
    with pytest.raises(ValueError, match="iter_docs"):
        doc_path(tmp_path, PHANTOM_SEQ, "some-slug")
    with pytest.raises(ValueError, match="iter_docs"):
        doc_path(tmp_path, REGISTRY["idea"], "some-slug")


def test_closer_target_parity_with_stage_layout(tmp_path):
    """The closer's path lands beside its closee at the closee's stage."""
    from reinicorn.staging import closer_target

    active = tmp_path / "exec-plans" / "active" / "feat-slash"
    active.mkdir(parents=True)
    assert closer_target(
        REGISTRY["retro"], tmp_path, "feat/slash"
    ) == active / "retro.md"
    # No closee dir at all: a retro without a plan is a closed branch.
    assert closer_target(
        REGISTRY["retro"], tmp_path, "feat/none"
    ) == tmp_path / "exec-plans" / "completed" / "feat-none" / "retro.md"


def test_iter_branch_dirs_includes_empty_dirs(tmp_path):
    kb = _seed_kb(tmp_path)
    dirs = list(iter_branch_dirs(kb, REGISTRY["plan"], "active"))
    names = [(scope, d.name) for scope, d in dirs]
    assert ("myrepo", "br") in names
    assert ("myrepo", "empty-dir") in names


def test_iter_branch_dirs_singleton_pattern_yields_nothing(tmp_path):
    kb = _seed_kb(tmp_path)
    assert list(iter_branch_dirs(kb, REGISTRY["principle"])) == []
