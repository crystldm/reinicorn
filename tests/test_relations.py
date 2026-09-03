"""Relations (`depends_on`/`closes`): overlay parsing, invariants, graph
queries, and the phantom-pair proof that lifecycle behavior comes from
registry rows alone.

Spec: process-as-config-doc-type-registry-overlay-and-declarative §2.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from reinicorn.doc_types import (
    REGISTRY,
    Closes,
    DependsOn,
    DocTypesError,
    closable_types,
    closer_of,
    dependencies_of,
    registry,
)


def _repo_with_overlay(tmp_path: Path, overlay_yaml: str | None) -> Path:
    """A repo root with a configured scope, kb marker, and optional overlay."""
    from reinicorn.git import run_git

    root = tmp_path / "repo"
    scope_dir = root / "kb" / "myscope"
    scope_dir.mkdir(parents=True)
    (root / "kb" / ".git").mkdir()  # get_kb_dir wants a .git entry
    run_git("init", "-q", "-b", "main", str(root))
    (root / ".reinicorn-config").write_text("REINICORN_KB_SCOPE=myscope\n")
    if overlay_yaml is not None:
        (scope_dir / "doc-types.yaml").write_text(overlay_yaml)
    return root


PHANTOM_PAIR = (
    "doc_types:\n"
    "  quest:\n"
    "    dir_path: quests\n"
    "    filename: '{stage}/{branch}/quest.md'\n"
    "    addressing: branch\n"
    "    title_source: none\n"
    "    required_sections: [Objective]\n"
    "    fields: [ticket, basis]\n"
    "    depends_on: {field: basis, type: spec, status: approved}\n"
    "  wrap:\n"
    "    dir_path: quests\n"
    "    filename: wrap.md\n"
    "    addressing: branch\n"
    "    title_source: none\n"
    "    required_sections: [Outcome]\n"
    "    closes: {type: quest}\n"
)


# --- Defaults ---------------------------------------------------------------


def test_default_graph():
    assert [dt.key for dt in closable_types()] == ["plan"]
    closer = closer_of(REGISTRY["plan"])
    assert closer is not None and closer.key == "retro"
    assert closer_of(REGISTRY["spec"]) is None
    assert dependencies_of(REGISTRY["plan"]) == DependsOn(
        field="spec", type="spec", status="approved"
    )
    assert dependencies_of(REGISTRY["retro"]) is None
    assert REGISTRY["retro"].closes == Closes(type="plan", required=False)


# --- Overlay validation -----------------------------------------------------


def test_depends_on_missing_target_fails(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  plan:\n"
        "    depends_on: {field: spec, type: ghost, status: approved}\n",
    )
    with pytest.raises(DocTypesError, match="ghost"):
        registry(root)


def test_depends_on_undeclared_field_fails(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  plan:\n"
        "    depends_on: {field: nonfield, type: spec, status: approved}\n",
    )
    with pytest.raises(DocTypesError, match="nonfield"):
        registry(root)


def test_closes_missing_target_fails(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  retro:\n"
        "    closes: {type: ghost}\n",
    )
    with pytest.raises(DocTypesError, match="ghost"):
        registry(root)


def test_closes_pair_must_be_branch_addressed(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  retro:\n"
        "    closes: {type: spec}\n",
    )
    with pytest.raises(DocTypesError, match="branch-addressed"):
        registry(root)


def test_two_closers_for_one_closee_fails(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  wrap:\n"
        "    dir_path: exec-plans\n"
        "    filename: wrap.md\n"
        "    addressing: branch\n"
        "    title_source: none\n"
        "    closes: {type: plan}\n",
    )
    with pytest.raises(DocTypesError, match="at most one enabled closer"):
        registry(root)


def test_closer_chain_fails(tmp_path):
    # seal closes retro, but retro itself closes plan — depth one only.
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  seal:\n"
        "    dir_path: exec-plans\n"
        "    filename: seal.md\n"
        "    addressing: branch\n"
        "    title_source: none\n"
        "    closes: {type: retro}\n",
    )
    with pytest.raises(DocTypesError, match="depth one"):
        registry(root)


def test_closer_filename_must_be_bare(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  retro:\n"
        "    filename: '{stage}/{branch}/retro.md'\n",
    )
    with pytest.raises(DocTypesError, match="bare name"):
        registry(root)


def test_closee_filename_must_be_staged(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  plan:\n"
        "    filename: 'active/{branch}/plan.md'\n",
    )
    with pytest.raises(DocTypesError, match="stage"):
        registry(root)


def test_disabling_related_group_is_atomic(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  plan: {disabled: true}\n"
        "  retro: {disabled: true}\n",
    )
    effective = registry(root)
    assert "plan" not in effective and "retro" not in effective
    assert closable_types(root) == []


def test_disabling_only_closee_fails_naming_closer(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  plan: {disabled: true}\n",
    )
    with pytest.raises(DocTypesError, match="retro"):
        registry(root)


def test_null_clears_relation_with_reshaped_filename(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  retro:\n"
        "    filename: 'completed/{branch}/retro.md'\n"
        "    closes: null\n",
    )
    effective = registry(root)
    assert effective["retro"].closes is None
    assert closable_types(root) == []


def test_disabled_must_be_boolean(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  prd: {disabled: 'false'}\n",
    )
    with pytest.raises(DocTypesError, match="boolean"):
        registry(root)


def test_relation_value_shape_is_checked(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  retro:\n"
        "    closes: {type: plan, required: 'yes'}\n",
    )
    with pytest.raises(DocTypesError, match="bool"):
        registry(root)


# --- Phantom pair: behavior from rows alone ---------------------------------


def test_phantom_pair_loads_and_wires_the_graph(tmp_path):
    root = _repo_with_overlay(tmp_path, PHANTOM_PAIR)
    effective = registry(root)
    quest, wrap = effective["quest"], effective["wrap"]
    # Auto-added engine fields on both branch-addressed rows.
    assert "branch" in quest.required_fields
    assert "branch" in wrap.required_fields
    closer = closer_of(quest, root)
    assert closer is not None and closer.key == "wrap"
    assert [dt.key for dt in closable_types(root)] == ["plan", "quest"]


def test_phantom_pair_cli_gains_lifecycle_verbs(tmp_path, monkeypatch):
    root = _repo_with_overlay(tmp_path, PHANTOM_PAIR)
    monkeypatch.chdir(root)
    from reinicorn.cli import _build_parser, _dispatch_table

    parser = _build_parser()
    args = parser.parse_args(["quest", "complete", "some-branch"])
    assert args.quest_command == "complete"
    table = _dispatch_table()
    assert ("quest", "complete") in table
    assert ("quest", "status") in table
    assert ("wrap", "create") in table
    assert ("wrap", "complete") not in table


def test_phantom_closer_rides_with_active_closee(tmp_path):
    root = _repo_with_overlay(tmp_path, PHANTOM_PAIR)
    repo_dir = root / "kb" / "myscope"
    wrap = registry(root)["wrap"]
    from reinicorn.staging import closer_target

    with patch("reinicorn.staging.registry", return_value=registry(root)):
        # No quest dir at all → the completed stage.
        assert closer_target(wrap, repo_dir, "feat/x") == (
            repo_dir / "quests" / "completed" / "feat-x" / "wrap.md"
        )
        active = repo_dir / "quests" / "active" / "feat-x"
        active.mkdir(parents=True)
        assert closer_target(wrap, repo_dir, "feat/x") == active / "wrap.md"


def test_phantom_complete_moves_stage_and_wants_closer(
    tmp_path, monkeypatch, capsys,
):
    root = _repo_with_overlay(tmp_path, PHANTOM_PAIR)
    monkeypatch.chdir(root)
    active = root / "kb" / "myscope" / "quests" / "active" / "feat-done"
    active.mkdir(parents=True)
    (active / "quest.md").write_text("# Quest\n\n## Objective\n\n- Ship\n")

    from reinicorn.commands.doc_lifecycle import cmd_lifecycle_complete

    with patch(
        "reinicorn.commands.doc_lifecycle.repo_root", return_value=root
    ), patch("reinicorn.commands.doc_lifecycle.commit_kb"):
        assert cmd_lifecycle_complete("quest", "feat/done") == 0

    assert not active.is_dir()
    completed = root / "kb" / "myscope" / "quests" / "completed" / "feat-done"
    assert (completed / "quest.md").is_file()
    out = capsys.readouterr().out
    assert "Quest archived" in out
    assert "No wrap captured" in out
    assert "rcorn wrap create" in out


def test_phantom_structure_lint_reads_rows(tmp_path):
    root = _repo_with_overlay(tmp_path, PHANTOM_PAIR)
    active = root / "kb" / "myscope" / "quests" / "active" / "feat-x"
    active.mkdir(parents=True)
    (active / "quest.md").write_text(
        "---\ntype: quest\n---\n\n# Quest\n\n## Wrong Section\n"
    )

    from reinicorn.linter.rules.doc_structure import DocStructureRule

    diags = DocStructureRule().run(root)
    joined = "\n".join(diags)
    assert "'## Objective' section" in joined
    assert "'basis:' frontmatter field" in joined
    assert "quest" in joined


def test_defaults_unchanged_by_relation_machinery(tmp_path):
    """The phantom rows exist only under their overlay: the default
    registry keeps exactly one closable type and one closer."""
    root = _repo_with_overlay(tmp_path, None)
    effective = registry(root)
    assert "quest" not in effective and "wrap" not in effective
    assert [dt.key for dt in closable_types(root)] == ["plan"]


def test_closee_title_source_must_be_none(tmp_path):
    """The lifecycle create derives the title from the branch; a parser that
    demanded one the command then ignored would lie to the user."""
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  plan:\n"
        "    title_source: title\n",
    )
    with pytest.raises(DocTypesError, match="title_source: none"):
        registry(root)


def test_repeated_seq_placeholder_fails(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  rfc:\n"
        "    dir_path: rfcs\n"
        "    filename: 'RFC-{seq}-{seq}-{slug}.md'\n"
        "    addressing: slug\n",
    )
    with pytest.raises(DocTypesError, match="repeats"):
        registry(root)


def test_phantom_dashboards_label_branch_by_present_type(
    tmp_path, monkeypatch, capsys,
):
    """A branch whose only active doc is the second closable type is
    reported as that type, with a `show` hint that resolves."""
    root = _repo_with_overlay(tmp_path, PHANTOM_PAIR)
    monkeypatch.chdir(root)
    active = root / "kb" / "myscope" / "quests" / "active" / "feat-x"
    active.mkdir(parents=True)
    (active / "quest.md").write_text("# Quest\n")

    from reinicorn.commands.home import cmd_home
    from reinicorn.commands.status import cmd_status

    with patch("reinicorn.commands.status.repo_root", return_value=root), \
         patch("reinicorn.commands.status.current_branch", return_value="feat/x"), \
         patch("reinicorn.commands.status.kb_scope", return_value="myscope"), \
         patch("reinicorn.commands.status.overlap_line", return_value="overlap: none"):
        assert cmd_status(compact=True) == 0
    out = capsys.readouterr().out
    assert "quest present" in out
    assert "plans: 0 active" in out
    assert "quests: 1 active" in out
    assert "next: rcorn quest show" in out
    assert "rcorn plan show" not in out

    with patch("reinicorn.commands.home.repo_root", return_value=root), \
         patch("reinicorn.commands.home.current_branch", return_value="feat/x"), \
         patch("reinicorn.commands.home.kb_scope", return_value="myscope"), \
         patch("reinicorn.commands.home.overlap_line", return_value="overlap: none"):
        assert cmd_home() == 0
    out = capsys.readouterr().out
    assert "quest: feat-x (this branch)" in out
    assert "next: rcorn quest show" in out
