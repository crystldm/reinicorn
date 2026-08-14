"""The pre-commit hook is the boundary layer .gitignore can't be:
`git add -f` defeats .gitignore; this refuses at commit time. Runs the
hook script directly via bash — no rcorn on PATH required, because a
guard that needs rcorn fails open exactly when it matters."""
import subprocess
from pathlib import Path

from reinicorn.git import reinicorn_root, run_git

HOOK = reinicorn_root() / "hooks" / "pre-commit"


def _run_hook(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOK)], cwd=cwd, capture_output=True, text=True,
    )


def test_blocks_staged_kb_file(kb_clone_repo):
    (kb_clone_repo / "kb" / "smuggled.md").write_text("x\n")
    run_git("add", "-f", "kb/smuggled.md", cwd=kb_clone_repo)
    r = _run_hook(kb_clone_repo)
    assert r.returncode == 1
    assert "rcorn kb publish" in r.stdout + r.stderr


def test_allows_clean_commit(kb_clone_repo):
    (kb_clone_repo / "src.py").write_text("x\n")
    run_git("add", "src.py", cwd=kb_clone_repo)
    assert _run_hook(kb_clone_repo).returncode == 0


def test_allows_kb_deletion(submodule_repo):
    """Migration's `git rm --cached kb` stages a DELETION of the gitlink —
    the hook must let the migration commit through."""
    run_git("rm", "--cached", "kb", cwd=submodule_repo)
    assert _run_hook(submodule_repo).returncode == 0
