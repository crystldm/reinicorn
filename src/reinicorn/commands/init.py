"""rcorn init — unified setup for existing and new repos.

Replaces both `attach` (bolt onto existing repo) and `init` (new project).
Detects context and runs the appropriate flow.

Modes:
- Existing repo, no kb -> full setup (submodule + AGENTS + skills + hooks)
- Existing repo, has kb -> hooks-only setup (teammate clone scenario)
- Not in a git repo -> error with guidance
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING

from reinicorn import console
from reinicorn.assets import get_asset_path
from reinicorn.commands.hooks_install import cmd_hooks_install
from reinicorn.config import KB_DIR_NAME, config_set, kb_scope
from reinicorn.git import (
    file_transport_args,
    https_to_ssh,
    reinicorn_root,
    remote_uses_ssh,
    repo_slug,
    run_git,
)
from reinicorn.github import (
    gh_auth_login,
    gh_authenticated,
    gh_available,
    gh_repo_create,
)
from reinicorn.identity import KB_SCOPE_KEY
from reinicorn.manifest import MANIFEST_PATH, write_manifest
from reinicorn.submodule import SubmoduleError, setup_submodule
from reinicorn.validation import is_valid_scope_name

if TYPE_CHECKING:
    from pathlib import Path

AGENTS_ASSET = "templates/AGENTS.md"
AGENTS_DESTINATION = "AGENTS.md"
SKILLS_ASSET = ".agents/skills"

PLATFORM_FILES = {
    "claude": "CLAUDE.md",
    "cursor": ".cursor/rules/reinicorn.mdc",
    "copilot": ".github/copilot-instructions.md",
}

PLATFORM_TEMPLATES = {
    "claude": "platform-instructions/claude.md",
    "cursor": "platform-instructions/cursor.md",
    "copilot": "platform-instructions/copilot.md",
}


def _detect_gh_status() -> str:
    """Detect gh CLI availability and auth status.
    Returns one of: 'ready', 'not_authenticated', 'not_installed'.
    """
    if not gh_available():
        return "not_installed"
    if not gh_authenticated():
        return "not_authenticated"
    return "ready"


def _write_init_manifest(target_dir: Path) -> None:
    """Write the Reinicorn manifest after asset copy."""
    from reinicorn import __version__

    manifest_path = write_manifest(target_dir, version=__version__)
    console.success(f"Wrote {manifest_path.relative_to(target_dir)}")
    print()


def _validate_scope_name(slug: str) -> bool:
    """Validate a KB scope supplied at the init boundary."""
    if is_valid_scope_name(slug):
        return True
    console.error(
        f"Invalid scope name '{slug}': must start with alphanumeric, "
        f"contain only alphanumeric, hyphens, dots, or underscores.\n"
        f"  How to fix: Use --slug with a valid name, e.g. --slug my-project"
    )
    return False


def cmd_init(
    *,
    kb_url: str | None = None,
    local: bool = False,
    create_remote: bool = False,
    kb_name: str | None = None,
    cwd: Path | None = None,
    slug: str | None = None,
) -> int:
    """Unified init command.

    Args:
        kb_url: URL to existing kb repo (skips interactive prompt).
        local: Create a local bare repo instead of using a remote.
        cwd: Override working directory (for testing).
        slug: Override the auto-derived repo scope name.
    """
    if cwd is None:
        from reinicorn.git import repo_root as _repo_root
        cwd = _repo_root(quiet=True)
        if cwd is None:
            console.error("Not inside a git repository.")
            print()
            print("  Run 'rcorn init' from within the repo you want to set up.")
            print("  Or create a repo first: git init && rcorn init")
            return 1

    # Check if cwd is actually a git repo
    r = run_git("rev-parse", "--git-dir", check=False, cwd=cwd)
    if r.returncode != 0:
        console.error("Not inside a git repository.")
        print()
        print("  Run 'rcorn init' from within the repo you want to set up.")
        print("  Or create a repo first: git init && rcorn init")
        return 1

    print()
    console.header("Reinicorn Init")
    print("==============")
    print()
    console.info(f"Repository: {cwd}")
    print()

    kb_dir = cwd / KB_DIR_NAME
    gitmodules = cwd / ".gitmodules"

    # Detect: repo already has kb (teammate clone scenario)
    if gitmodules.is_file() and KB_DIR_NAME in gitmodules.read_text():
        if slug is not None and not _validate_scope_name(slug):
            return 1
        template_ok, agent_template = _preflight_agent_instructions(cwd)
        if not template_ok:
            return 1
        effective_slug = slug or ""
        if agent_template is not None:
            effective_slug = slug or kb_scope(cwd)
            if not _validate_scope_name(effective_slug):
                return 1
        if slug is not None:
            config_set(KB_SCOPE_KEY, slug, cwd)
        if not kb_dir.is_dir() or not any(kb_dir.iterdir()):
            console.info("Initializing kb submodule...")
            run_git("submodule", "update", "--init", KB_DIR_NAME, cwd=cwd)
        # A committed manifest means the assets were already laid down (a genuine
        # teammate clone) — just wire up hooks + agent instructions. Without one,
        # the kb submodule exists but Reinicorn assets were never installed (e.g.
        # the submodule was added by hand), so fall through to full asset setup,
        # skipping the submodule creation that is already done.
        if (cwd / MANIFEST_PATH).is_file():
            console.info("Kb submodule already configured — setting up hooks.")
            if not _copy_agent_instructions(
                reinicorn_root(), cwd, effective_slug, template=agent_template
            ):
                return 1
            hooks_rc = cmd_hooks_install()
            _print_teammate_summary(hooks_rc)
            return 0
        console.info(
            "Kb submodule configured but Reinicorn assets missing — setting up assets."
        )
        asset_slug = effective_slug or kb_scope(cwd)
        if not _validate_scope_name(asset_slug):
            return 1
        hooks_rc = _setup_assets(
            reinicorn_root(), cwd, asset_slug, agent_template=agent_template
        )
        if hooks_rc is None:
            return 1
        _print_full_summary(hooks_rc, asset_slug)
        return 0

    # Full setup flow
    r_root = reinicorn_root()

    # Determine kb URL
    explicit_slug = slug
    slug = slug or repo_slug()
    if not _validate_scope_name(slug):
        return 1
    template_ok, agent_template = _preflight_agent_instructions(cwd)
    if not template_ok:
        return 1
    if kb_name and not create_remote:
        console.warn("--kb-name has no effect without --create-remote — ignoring.")
        print()
    if kb_url is None and not local and not create_remote:
        kb_url = _prompt_kb_source(cwd, slug)
        if kb_url is None:
            return 1

    if create_remote:
        kb_url = _create_github_remote(slug, name=kb_name or f"{slug}-kb")
        if kb_url is None:
            return 1

    if local:
        kb_url = _create_local_bare(cwd)

    # Setup submodule (handles empty remotes, cleanup, etc.)
    console.info(f"Kb scope: {slug}")
    if kb_url is None:
        console.error("No kb URL resolved — cannot continue.")
        return 1
    try:
        setup_submodule(cwd, kb_url, repo_slug=slug)
    except SubmoduleError as e:
        console.error(str(e))
        return 1
    if explicit_slug:
        config_set(KB_SCOPE_KEY, slug, cwd)

    # Ensure repo-scoped dir exists in kb (multi-repo case)
    kb_scope_dir = kb_dir / slug
    if kb_dir.is_dir() and not kb_scope_dir.is_dir():
        from reinicorn.kb_seed import generate_seed_tree

        console.info(f"Creating kb scope for '{slug}'...")
        generate_seed_tree(kb_dir, slug)
        try:
            ft = file_transport_args(cwd=kb_dir)
            run_git("add", "-A", cwd=kb_dir)
            run_git("commit", "-q", "-m", f"chore: add kb scope for {slug}", cwd=kb_dir)
            run_git(*ft, "push", "-q", "origin", "HEAD", cwd=kb_dir)
            console.success(f"Created {KB_DIR_NAME}/{slug}/ in shared kb")
        except subprocess.CalledProcessError as e:
            console.warn(f"Could not push repo-scoped dir for '{slug}': {e.stderr or e}")
            console.warn("You can push the kb changes manually later.")

    hooks_rc = _setup_assets(r_root, cwd, slug, agent_template=agent_template)
    if hooks_rc is None:
        return 1
    local_bare_path = str(cwd.parent / f"{cwd.name}-kb.git") if local else None
    _print_full_summary(hooks_rc, slug, local_bare_path=local_bare_path)
    return 0


def _setup_assets(
    r_root: Path, cwd: Path, slug: str, *, agent_template: Path | None
) -> int | None:
    """Lay down Reinicorn assets: agent instructions, platform files, skills,
    the session hook, lint config, and the manifest. Shared tail of the
    full-init and existing-kb-without-manifest flows. Returns the hooks-install
    rc, or None if agent-instruction setup failed (caller should return 1).
    """
    print()
    if not _copy_agent_instructions(r_root, cwd, slug, template=agent_template):
        return None
    platforms = _prompt_platforms()
    _install_platform_instructions(cwd, slug, platforms)
    _copy_skills(r_root, cwd)
    _install_session_hook(cwd)
    _copy_lint_config(cwd)
    _write_init_manifest(cwd)
    return cmd_hooks_install()


def _prompt_kb_source(target_dir: Path, slug: str) -> str | None:
    """Interactive prompt for kb repo source."""
    gh_status = _detect_gh_status()

    if gh_status == "not_authenticated":
        console.warn("gh CLI is installed but not authenticated.")
        print()
        answer = input("  Run 'gh auth login' now? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            if gh_auth_login():
                gh_status = "ready"
                console.success("Authenticated with GitHub.")
                print()
            else:
                console.warn("Authentication failed — GitHub option unavailable.")
                print()

    print("Where should the kb live?")
    print()

    if gh_status == "ready":
        print("  1) Create a private GitHub repo (recommended)")
        print("  2) I have an existing kb repo URL")
        print("  3) Create a local bare repo (offline/testing)")
        print()
        choice = input("Choose [1/2/3]: ").strip()
        if choice == "1":
            return _create_github_remote(slug)
        if choice == "3":
            return _create_local_bare(target_dir)
    else:
        if gh_status == "not_installed":
            console.info("Tip: Install 'gh' CLI to create GitHub repos automatically.")
            print()
        print("  1) I have an existing kb repo URL")
        print("  2) Create a local bare repo (offline/testing)")
        print()
        choice = input("Choose [1/2]: ").strip()
        if choice == "2":
            return _create_local_bare(target_dir)

    print()
    url = input("Kb repo URL (git@... or https://...): ").strip()
    if not url:
        console.error("Repository URL cannot be empty.")
        return None
    return url


def _create_github_remote(slug: str, *, name: str | None = None) -> str | None:
    """Create a private GitHub repo for the kb.

    Args:
        slug: Project slug (used for default repo name and description).
        name: Explicit repo name. If None, prompts interactively.
    """
    if name is None:
        default_name = f"{slug}-kb"
        print()
        name = input(f"  Repo name [{default_name}]: ").strip() or default_name
    console.info(f"Creating private repo '{name}'...")
    try:
        url = gh_repo_create(name, description=f"Reinicorn kb for {slug}")
    except RuntimeError as e:
        console.error(str(e))
        return None

    # Match parent repo's protocol: if parent uses SSH, convert HTTPS → SSH
    if remote_uses_ssh() and url.startswith("https://"):
        url = https_to_ssh(url)

    console.success(f"Created {url}")
    print()
    return url


def _create_local_bare(target_dir: Path) -> str:
    """Create a local bare kb repo for testing."""
    bare = target_dir.parent / f"{target_dir.name}-kb.git"
    console.info(f"Creating bare kb repo at: {bare}")
    bare.mkdir(parents=True, exist_ok=True)
    run_git("init", "--bare", "-q", "-b", "main", str(bare))
    # seed_remote will be called by setup_submodule when it detects empty.
    # Return an absolute path so it passes the git-transport allow-list.
    return str(bare.resolve())


def _preflight_agent_instructions(target_dir: Path) -> tuple[bool, Path | None]:
    """Resolve the required AGENTS template before init creates external state."""
    dest = target_dir / AGENTS_DESTINATION
    if dest.exists() or dest.is_symlink():
        return True, None

    template = get_asset_path(AGENTS_ASSET)
    if template is None:
        console.warn(
            "Missing packaged template 'templates/AGENTS.md'. Reinstall Reinicorn, "
            "then rerun 'rcorn init'."
        )
        print()
        return False, None
    return True, template


def _copy_agent_instructions(
    _r_root: Path,
    target_dir: Path,
    slug: str,
    *,
    template: Path | None = None,
) -> bool:
    """Copy AGENTS.md to the target repo, substituting {repo} with slug."""
    dest = target_dir / AGENTS_DESTINATION
    if dest.exists() or dest.is_symlink():
        console.info(f"{AGENTS_DESTINATION} already exists — keeping existing")
        print()
        return True

    src = template or get_asset_path(AGENTS_ASSET)
    if src is None:
        console.warn(
            "Missing packaged template 'templates/AGENTS.md'. Reinstall Reinicorn, "
            "then rerun 'rcorn init'."
        )
        print()
        return False

    content = src.read_text()
    content = content.replace("{repo}", slug)
    dest.write_text(content)
    console.success(f"Copied {AGENTS_DESTINATION}")
    print()
    return True


def _check_skill_collisions(skill_names: list[str]) -> None:
    """Warn about skill name collisions with user-level skills and plugins."""
    from pathlib import Path

    # Check ~/.claude/skills/ and ~/.agents/skills/ for user-level collisions
    user_skills: set[str] = set()
    for user_skills_dir in (
        Path.home() / ".claude" / "skills",
        Path.home() / ".agents" / "skills",
    ):
        if user_skills_dir.is_dir():
            user_skills |= {
                d.name for d in user_skills_dir.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            } | {
                f.stem for f in user_skills_dir.iterdir()
                if f.is_file() and f.suffix == ".md"
            }
    if user_skills:
        collisions = sorted(set(skill_names) & user_skills)
        if collisions:
            console.warn(
                f"Skill name collision with user-level skills: {', '.join(collisions)}"
            )
            console.info(
                "  These user-level skills will conflict with reinicorn's repo-level skills."
            )
            console.info(
                "  Consider removing the duplicates from ~/.claude/skills/"
                " or ~/.agents/skills/"
            )
            print()

    # Check for superpowers plugin specifically
    user_settings = Path.home() / ".claude" / "settings.json"
    if user_settings.is_file():
        try:
            data = json.loads(user_settings.read_text())
            plugins = data.get("enabledPlugins", {})
            sp_keys = [k for k in plugins if "superpowers" in k and plugins[k]]
            if sp_keys:
                console.warn(
                    "The superpowers plugin is enabled at user level."
                )
                console.info(
                    "  Reinicorn includes forked superpowers skills — having both"
                    " will cause duplicates."
                )
                console.info(
                    "  To disable superpowers for this project, add to"
                    " .claude/settings.json:"
                )
                console.info(
                    f'    "disabledPlugins": ["{sp_keys[0]}"]'
                )
                print()
        except (json.JSONDecodeError, OSError):
            pass


def _copy_skills(_r_root: Path, target_dir: Path) -> None:
    """Copy skills to <target>/.agents/skills/ and link .claude/skills to it."""
    skills_src = get_asset_path("skills")
    if skills_src is None:
        skills_src = get_asset_path(SKILLS_ASSET)
    if skills_src is None:
        console.warn("No skills directory found — skipping")
        return

    skills_dest = target_dir / SKILLS_ASSET
    skills_dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skills_src, skills_dest, dirs_exist_ok=True)
    _link_claude_skills(target_dir)

    # List skill names for the user
    skill_names = sorted(
        d.name for d in skills_dest.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )
    standalone = sorted(
        f.stem for f in skills_dest.iterdir()
        if f.is_file() and f.suffix == ".md" and f.name != "ATTRIBUTION.md"
    )
    all_skills = skill_names + standalone
    console.success(f"Copied {len(all_skills)} skill(s) to .agents/skills/")
    for name in all_skills:
        print(f"    {name}")
    print()

    _check_skill_collisions(all_skills)


def _link_claude_skills(target_dir: Path) -> None:
    """Make .claude/skills a symlink to ../.agents/skills (copy fallback).

    Claude Code only reads .claude/skills; Codex/Cursor/Copilot read
    .agents/skills natively. A pre-existing REAL .claude/skills dir is
    left untouched (never delete user content) — warn instead.
    """
    from pathlib import Path

    claude_dir = target_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    link = claude_dir / "skills"
    rel_target = Path("..") / ".agents" / "skills"

    if link.is_symlink():
        return  # already linked
    if link.is_dir():
        console.warn(
            ".claude/skills already exists as a real directory — left in place.\n"
            "  Canonical skills now live in .agents/skills/. Remove the old\n"
            "  directory and re-run 'rcorn update' to switch to the symlink."
        )
        return
    try:
        link.symlink_to(rel_target, target_is_directory=True)
        console.success("Linked .claude/skills -> .agents/skills")
    except OSError:
        shutil.copytree(target_dir / SKILLS_ASSET, link, dirs_exist_ok=True)
        console.warn(
            "Symlinks unavailable (Windows without developer mode?) — copied\n"
            "  skills to .claude/skills instead. This copy is NOT auto-synced;\n"
            "  re-run 'rcorn init' after each 'rcorn update' to refresh it."
        )


_CHECK_AGENTS_SCRIPT = """\
#!/bin/bash
# Check if AGENTS.md needs population.
# Runs on SessionStart — stdout is injected into agent context.
AGENTS_FILE="${CLAUDE_PROJECT_DIR:-.}/AGENTS.md"

if [ -f "$AGENTS_FILE" ] && grep -q '<!-- UNPOPULATED' "$AGENTS_FILE"; then
    echo "⚠️ AGENTS.md has not been populated yet."
    echo "Run the populate-agents-md skill to analyze this repo" \
         "and fill in project-specific sections."
fi

exit 0
"""

_SESSION_HOOK_ENTRY = {
    "matcher": "",
    "hooks": [
        {
            "type": "command",
            "command": ".claude/hooks/check-agents-md.sh",
        }
    ],
}


def _install_session_hook(target_dir: Path) -> None:
    """Install SessionStart hook that checks AGENTS.md population status."""
    # Write the hook script
    hooks_dir = target_dir / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script = hooks_dir / "check-agents-md.sh"
    script.write_text(_CHECK_AGENTS_SCRIPT)
    script.chmod(0o755)

    # Merge hook entry into settings.json
    settings_path = target_dir / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text()) if settings_path.is_file() else {}

    hooks = data.setdefault("hooks", {})
    session_hooks = hooks.setdefault("SessionStart", [])

    # Idempotency: check if our hook command is already present
    hook_cmd = _SESSION_HOOK_ENTRY["hooks"][0]["command"]
    already = any(
        hook_cmd in (h.get("command", "") for h in entry.get("hooks", []))
        for entry in session_hooks
    )
    if not already:
        session_hooks.append(_SESSION_HOOK_ENTRY)

    settings_path.write_text(json.dumps(data, indent=2) + "\n")
    console.success("Installed SessionStart hook for AGENTS.md check")
    print()


def _copy_lint_config(target_dir: Path) -> None:
    """Copy linters/ directory to the target repo."""
    lint_src = get_asset_path("linters")
    if lint_src is None:
        return
    lint_dest = target_dir / "linters"
    lint_dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(lint_src, lint_dest, dirs_exist_ok=True)
    console.success("Copied linters/ config")
    print()


def _prompt_platforms() -> list[str]:
    """Interactive multi-select for AI coding platforms."""
    print("Which AI coding platforms do you use?")
    print()
    options = [
        ("claude", "Claude Code", True),
        ("cursor", "Cursor", False),
        ("copilot", "GitHub Copilot", False),
        ("codex", "Codex", False),
    ]
    for i, (_key, label, default) in enumerate(options, 1):
        marker = "x" if default else " "
        print(f"  {i}) [{marker}] {label}")
    print()
    raw = input("Toggle by number (e.g. 1,3), enter to confirm defaults: ").strip()
    selected = [default for _, _, default in options]
    if raw:
        for token in raw.replace(" ", "").split(","):
            if token.isdigit():
                idx = int(token) - 1
                if 0 <= idx < len(options):
                    selected[idx] = not selected[idx]
    return [key for (key, _, _), sel in zip(options, selected, strict=True) if sel]


def _install_platform_instructions(target_dir: Path, slug: str, platforms: list[str]) -> None:
    """Generate platform-specific instruction files from templates."""
    for platform in platforms:
        if platform == "codex":
            console.success("Codex: uses AGENTS.md (already installed)")
            continue
        template_name = PLATFORM_TEMPLATES.get(platform)
        dest_rel = PLATFORM_FILES.get(platform)
        if not template_name or not dest_rel:
            continue
        src = get_asset_path(template_name)
        if src is None:
            console.warn(f"No template for {platform} — skipping")
            continue
        dest = target_dir / dest_rel
        if dest.is_file():
            console.info(f"{dest_rel} already exists — keeping existing")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_text()
        content = content.replace("{repo}", slug)
        dest.write_text(content)
        console.success(f"Generated {dest_rel}")
    print()


def _print_full_summary(hooks_rc: int, slug: str, *, local_bare_path: str | None = None) -> None:
    """Print summary after full init."""
    print()
    if hooks_rc != 0:
        console.warn("Hook installation had issues — review output above.")
    print("==========================================")
    console.success("Reinicorn initialized!")
    print("==========================================")
    print()
    print("Next steps:")
    print()
    print("  1. Review and customize AGENTS.md")
    print("  2. Review .agents/skills/ for your workflow")
    print(f"  3. Review {KB_DIR_NAME}/{slug}/golden-principles.md")
    print(
        f"  4. Commit: git add .gitmodules {KB_DIR_NAME} AGENTS.md "
        f".agents .claude .cursor .github .reinicorn CLAUDE.md"
    )
    print("     git commit -m 'chore: initialize reinicorn kb'")
    if local_bare_path:
        print()
        print("  To move this kb to GitHub later:")
        print(f"    gh repo create {slug}-kb --private --source {local_bare_path} --push")
        print(f"    cd {KB_DIR_NAME} && git remote set-url origin <new-github-url>")
    print()


def _print_teammate_summary(hooks_rc: int) -> None:
    """Print summary after hooks-only init (teammate clone)."""
    print()
    if hooks_rc != 0:
        console.warn("Hook installation had issues — review output above.")
    print("==========================================")
    console.success("Reinicorn hooks installed!")
    print("==========================================")
    print()
    print("Your kb is ready.")
    console.next_step("rcorn kb status")
    print()
