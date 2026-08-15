"""A freshly created doc of every type passes the frontmatter lint clean.

The regression test issue #34 proposed and issue #41 proved missing: the
create paths and the `kb/frontmatter` rule must share one definition of
valid, so a doc can never be born failing the check that guards it. Plans
run through the real template path — that is the path #41 broke.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.doc_create import (
    cmd_debt_create,
    cmd_doc_create,
    cmd_prd_create,
    cmd_principle_add,
    cmd_retro_create,
    cmd_spec_create,
)
from reinicorn.commands.plan import cmd_plan_create
from reinicorn.linter.rules.frontmatter import FrontmatterRule

_GIT_USER = subprocess.CompletedProcess(args=[], returncode=0, stdout="Test User\n")


def test_every_create_path_births_a_lint_clean_doc(kb_repo: Path, capsys):
    common = dict(return_value=kb_repo)
    with patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.doc_create.repo_root", **common), \
         patch("reinicorn.commands.doc_create.run_git", return_value=_GIT_USER), \
         patch("reinicorn.commands.doc_create.commit_kb"), \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.doc_create.current_branch", return_value="feature/born"), \
         patch("reinicorn.commands.plan.repo_root", **common), \
         patch("reinicorn.commands.plan.run_git", return_value=_GIT_USER), \
         patch("reinicorn.commands.plan.commit_kb"), \
         patch("reinicorn.commands.plan.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.current_branch", return_value="feature/born"):
        assert cmd_spec_create("Born spec") == 0
        assert cmd_prd_create("Born prd") == 0
        assert cmd_debt_create("Born debt") == 0
        assert cmd_principle_add("Born principle") == 0
        assert cmd_doc_create("idea", "Born idea") == 0
        assert cmd_plan_create() == 0
        assert cmd_retro_create() == 0

    assert FrontmatterRule().run(kb_repo) == []
