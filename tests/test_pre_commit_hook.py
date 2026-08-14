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


def _setup_parent_repo(tmp_path: Path) -> Path:
    """Create a self-contained parent repo with kb/ and initial commit.

    kb/ is a plain directory (not a nested git repo), allowing tests to
    stage files under it with git add -f.
    """
    parent = tmp_path / "parent"
    parent.mkdir()
    run_git("init", "-q", "-b", "main", str(parent))
    run_git("config", "user.email", "test@test.com", cwd=parent)
    run_git("config", "user.name", "Test User", cwd=parent)

    # Create .gitignore for kb/
    (parent / ".gitignore").write_text("kb/\n")

    # Initial commit
    run_git("add", ".gitignore", cwd=parent)
    run_git("commit", "-q", "-m", "init", cwd=parent)

    # Create kb/ as a plain directory
    (parent / "kb").mkdir()

    return parent


def test_blocks_staged_kb_file(tmp_path: Path):
    """git add -f defeats .gitignore; hook refuses at commit time."""
    parent = _setup_parent_repo(tmp_path)

    # Create and force-add a file under kb/
    (parent / "kb" / "smuggled.md").write_text("x\n")
    run_git("add", "-f", "kb/smuggled.md", cwd=parent)

    # Hook should block it
    r = _run_hook(parent)
    assert r.returncode == 1
    assert "rcorn kb publish" in r.stdout + r.stderr


def test_allows_clean_commit(tmp_path: Path):
    """Hook allows staging and committing files outside kb/."""
    parent = _setup_parent_repo(tmp_path)

    # Stage a file outside kb/
    (parent / "src.py").write_text("x\n")
    run_git("add", "src.py", cwd=parent)

    # Hook should allow it
    assert _run_hook(parent).returncode == 0


def test_blocks_staged_gitlink(tmp_path: Path):
    """Hook blocks staging kb/ itself as a gitlink (submodule entry)."""
    parent = _setup_parent_repo(tmp_path)

    # Stage kb/ as a gitlink using git update-index (simulating submodule add).
    # Use parent's HEAD commit sha as the gitlink target.
    head_sha = run_git("rev-parse", "HEAD", cwd=parent).stdout.strip()
    run_git(
        "update-index", "--add", "--cacheinfo", f"160000,{head_sha},kb",
        cwd=parent,
    )

    # Hook should block it (kb itself is a non-deletion staging of path kb/)
    r = _run_hook(parent)
    assert r.returncode == 1
    assert "rcorn kb publish" in r.stdout + r.stderr


def test_allows_kb_deletion(submodule_repo):
    """Migration's `git rm --cached kb` stages a DELETION of the gitlink —
    the hook must let the migration commit through."""
    run_git("rm", "--cached", "kb", cwd=submodule_repo)
    assert _run_hook(submodule_repo).returncode == 0
