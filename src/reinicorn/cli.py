"""CLI entry point — argparse dispatcher."""

from __future__ import annotations

import argparse
import importlib
import sys

from reinicorn import __version__
from reinicorn.identity import CLI_NAME, PRODUCT_NAME


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=CLI_NAME,
        description=f"{PRODUCT_NAME} — agentic engineering knowledgebase CLI",
    )
    parser.add_argument(
        "--version", action="version", version=f"{CLI_NAME} {__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    # ── Doc-type groups ────────────────────────────────────
    def _doc_group_with_create_title(name: str, help_text: str):
        g = sub.add_parser(name, help=help_text)
        gs = g.add_subparsers(dest=f"{name}_command")
        gs.required = True
        cp = gs.add_parser("create", help=f"Create a {name} doc")
        cp.add_argument("title", nargs="+", help="Document title")
        sp = gs.add_parser("show", help=f"Show a {name} doc (truncated; --full for all)")
        sp.add_argument("slug", help="Doc slug (see 'list')")
        sp.add_argument("--full", action="store_true", help="Print the whole doc")
        sp.add_argument(
            "--include-drafts", action="store_true",
            help="Include drafts/ (unapproved) docs",
        )
        lp = gs.add_parser("list", help=f"List {name} docs")
        lp.add_argument(
            "--include-drafts", action="store_true",
            help="Include drafts/ (unapproved) docs",
        )
        return g

    _doc_group_with_create_title("spec", "Spec doc operations (the implementation contract)")
    _doc_group_with_create_title("prd", "Product requirements doc operations")
    _doc_group_with_create_title("debt", "Tech debt doc operations")

    # idea: takes free-form text, not a title
    idea_p = sub.add_parser("idea", help="Idea capture")
    idea_sub = idea_p.add_subparsers(dest="idea_command")
    idea_sub.required = True
    idea_create_p = idea_sub.add_parser("create", help="Capture an idea")
    idea_create_p.add_argument("text", nargs="+", help="Idea text")
    idea_show_p = idea_sub.add_parser("show", help="Show an idea doc (truncated; --full for all)")
    idea_show_p.add_argument("slug", help="Doc slug (see 'list')")
    idea_show_p.add_argument("--full", action="store_true", help="Print the whole doc")
    idea_show_p.add_argument(
        "--include-drafts", action="store_true",
        help="Include drafts/ (unapproved) docs",
    )
    idea_list_p = idea_sub.add_parser("list", help="List idea docs")
    idea_list_p.add_argument(
        "--include-drafts", action="store_true",
        help="Include drafts/ (unapproved) docs",
    )

    # plan: branch-derived; status/complete verbs
    plan_p = sub.add_parser("plan", help="Execution plan operations")
    plan_sub = plan_p.add_subparsers(dest="plan_command")
    plan_sub.required = True
    plan_sub.add_parser("create", help="Create execution plan for current branch")
    plan_sub.add_parser("status", help="Show plan status for current branch")
    plan_complete_p = plan_sub.add_parser("complete", help="Archive plan to completed/")
    plan_complete_p.add_argument(
        "branch", nargs="?", default=None, help="Branch name (default: current)"
    )
    plan_show_p = plan_sub.add_parser("show", help="Show the plan doc (truncated; --full for all)")
    plan_show_p.add_argument(
        "branch", nargs="?", default=None, help="Branch name (default: current)"
    )
    plan_show_p.add_argument("--full", action="store_true", help="Print the whole doc")

    # retro: branch-derived; no title
    retro_p = sub.add_parser("retro", help="Retrospective operations")
    retro_sub = retro_p.add_subparsers(dest="retro_command")
    retro_sub.required = True
    retro_sub.add_parser("create", help="Create retro for current branch")
    retro_show_p = retro_sub.add_parser(
        "show", help="Show the retro doc (truncated; --full for all)"
    )
    retro_show_p.add_argument(
        "branch", nargs="?", default=None, help="Branch name (default: current)"
    )
    retro_show_p.add_argument("--full", action="store_true", help="Print the whole doc")

    # principle: 'add' verb
    principle_p = sub.add_parser("principle", help="Golden principle operations")
    principle_sub = principle_p.add_subparsers(dest="principle_command")
    principle_sub.required = True
    principle_add_p = principle_sub.add_parser("add", help="Append a principle")
    principle_add_p.add_argument("title", nargs="+", help="Principle title")

    # ── Review group ────────────────────────────────────────
    review_p = sub.add_parser(
        "review", help="Doc-review lane (start, push, merge, cancel, link, status)"
    )
    review_sub = review_p.add_subparsers(dest="review_command")
    review_sub.required = True

    def _review_verb(name: str, help_text: str):
        p = review_sub.add_parser(name, help=help_text)
        p.add_argument("slug", help="Draft slug or path")
        p.add_argument(
            "--type", dest="type_key", default=None,
            help="Doc type key when the slug matches more than one type",
        )
        return p

    review_start_p = _review_verb("start", "Push the candidate ref and open the review PR")
    review_start_p.add_argument(
        "--reviewer", dest="reviewers", action="append", default=[],
        help="GitHub login to request review from (repeatable)",
    )
    _review_verb("push", "Update the candidate on the review ref")
    review_merge_p = _review_verb("merge", "Merge the approved PR and land the doc")
    review_merge_p.add_argument(
        "--force", action="store_true",
        help="Skip the approval and divergence guards",
    )
    _review_verb("cancel", "Close the PR and return the draft to draft status")
    review_link_p = _review_verb("link", "Record a manually-opened PR URL on the draft")
    review_link_p.add_argument("pr_url", help="PR URL")
    review_sub.add_parser("status", help="List open doc reviews")
    review_setup_p = review_sub.add_parser(
        "setup", help="Set up the kb repo for the review lane"
    )
    review_setup_p.add_argument("--force", action="store_true", help="Re-apply setup")

    # ── Kb group ────────────────────────────────────────────
    kb_p = sub.add_parser("kb", help="Kb operations (sync, publish, status, lint, ...)")
    kb_sub = kb_p.add_subparsers(dest="kb_command")
    kb_sub.required = True
    kb_sub.add_parser("sync", help="Pull latest kb state")
    kb_sub.add_parser("publish", help="Push kb changes (rebase + push)")
    kb_status_p = kb_sub.add_parser("status", help="Show kb status and health")
    kb_status_p.add_argument(
        "--compact",
        action="store_true",
        help="≤10-line dashboard for session-start context injection",
    )
    kb_sub.add_parser("lint", help="Run kb lint rules")
    kb_sub.add_parser("list", help="List repo scopes in the kb")
    kb_remove_p = kb_sub.add_parser("remove-scope", help="Remove a repo scope from the kb")
    kb_remove_p.add_argument("name", help="Scope name to remove")
    kb_remove_p.add_argument("--force", "-f", action="store_true",
                             help="Skip confirmation prompt")
    kb_git_p = kb_sub.add_parser("git", help="Run git commands inside kb directory")
    kb_git_p.add_argument("git_args", nargs=argparse.REMAINDER, help="Git arguments")

    # ── Mode group ──────────────────────────────────────────
    mode_p = sub.add_parser("mode", help="Mode toggles (enable, disable, incognito, status)")
    mode_sub = mode_p.add_subparsers(dest="mode_command")
    mode_sub.required = True
    mode_sub.add_parser("enable", help="Enable hooks and publishing")
    mode_sub.add_parser("disable", help="Disable all hooks and publishing")
    mode_sub.add_parser(
        "incognito",
        help="Enter read-only mode (blocks publishing; 'mode enable' to exit)",
    )
    mode_sub.add_parser("status", help="Show active mode")

    # ── Top-level (operate on reinicorn itself) ────────────────
    init_p = sub.add_parser("init", help="Set up reinicorn in this repo")
    init_source = init_p.add_mutually_exclusive_group()
    init_source.add_argument("--kb-url", help="Kb repo URL (skip interactive prompt)")
    init_source.add_argument("--local", action="store_true", help="Create local bare repo")
    init_source.add_argument("--create-remote", action="store_true",
                             help="Create a private GitHub repo for the kb")
    init_p.add_argument("--slug", help="Override the auto-derived repo scope name")
    init_p.add_argument("--kb-name", help="Custom name for the GitHub kb repo")
    init_p.add_argument(
        "--platforms",
        help=(
            "Comma-separated platform keys "
            "(claude,cursor,copilot,codex; case-insensitive; "
            "skip interactive prompt)"
        ),
    )

    hooks_p = sub.add_parser("hooks", help="Git hook management")
    hooks_sub = hooks_p.add_subparsers(dest="hooks_command")
    hooks_sub.required = True
    hooks_sub.add_parser("install", help="Install git and editor hooks")

    update_p = sub.add_parser(
        "update",
        help=(
            "Re-sync bundled files (skills, hooks, linters) "
            "to the installed Reinicorn version"
        ),
    )
    update_p.add_argument(
        "--diff", dest="diff_target", help="Show diff for a specific bundled file"
    )

    feedback_p = sub.add_parser("feedback", help="Report a bug or idea")
    feedback_p.add_argument("text", nargs="*", help="Feedback text (will prompt if omitted)")

    sub.add_parser("help", help="Show help")

    return parser


def _load(module: str, func: str):
    """Lazily import and return a command function from reinicorn.commands.<module>.

    Importing on demand (rather than at module load) keeps CLI startup fast.
    """
    return getattr(importlib.import_module(f"reinicorn.commands.{module}"), func)


# Maps (noun, verb) -> handler taking the parsed args Namespace and returning an
# exit code. Top-level nouns with no sub-verb use a None verb. Each handler lazily
# imports its command so importing this module stays cheap.
_DISPATCH = {
    ("spec", "create"): lambda a: _load("doc_create", "cmd_spec_create")(" ".join(a.title)),
    ("spec", "show"): lambda a: _load("doc_show", "cmd_doc_show")(
        "spec", a.slug, full=a.full, include_drafts=getattr(a, "include_drafts", False)
    ),
    ("spec", "list"): lambda a: _load("doc_show", "cmd_doc_list")(
        "spec", include_drafts=getattr(a, "include_drafts", False)
    ),
    ("prd", "create"): lambda a: _load("doc_create", "cmd_prd_create")(" ".join(a.title)),
    ("prd", "show"): lambda a: _load("doc_show", "cmd_doc_show")(
        "prd", a.slug, full=a.full, include_drafts=getattr(a, "include_drafts", False)
    ),
    ("prd", "list"): lambda a: _load("doc_show", "cmd_doc_list")(
        "prd", include_drafts=getattr(a, "include_drafts", False)
    ),
    ("debt", "create"): lambda a: _load("doc_create", "cmd_debt_create")(" ".join(a.title)),
    ("debt", "show"): lambda a: _load("doc_show", "cmd_doc_show")(
        "debt", a.slug, full=a.full, include_drafts=getattr(a, "include_drafts", False)
    ),
    ("debt", "list"): lambda a: _load("doc_show", "cmd_doc_list")(
        "debt", include_drafts=getattr(a, "include_drafts", False)
    ),
    ("idea", "create"): lambda a: _load("idea", "cmd_idea")(" ".join(a.text)),
    ("idea", "show"): lambda a: _load("doc_show", "cmd_doc_show")(
        "idea", a.slug, full=a.full, include_drafts=getattr(a, "include_drafts", False)
    ),
    ("idea", "list"): lambda a: _load("doc_show", "cmd_doc_list")(
        "idea", include_drafts=getattr(a, "include_drafts", False)
    ),
    ("plan", "create"): lambda _: _load("plan", "cmd_plan_create")(),
    ("plan", "status"): lambda _: _load("plan", "cmd_plan_status")(),
    ("plan", "complete"): lambda a: _load("plan", "cmd_plan_complete")(a.branch),
    ("plan", "show"): lambda a: _load("doc_show", "cmd_plan_show")(a.branch, full=a.full),
    ("retro", "create"): lambda _: _load("doc_create", "cmd_retro_create")(),
    ("retro", "show"): lambda a: _load("doc_show", "cmd_retro_show")(a.branch, full=a.full),
    ("principle", "add"): lambda a: _load("doc_create", "cmd_principle_add")(" ".join(a.title)),
    ("review", "start"): lambda a: _load("review", "cmd_review_start")(
        a.slug, a.reviewers, type_key=a.type_key
    ),
    ("review", "push"): lambda a: _load("review", "cmd_review_push")(
        a.slug, type_key=a.type_key
    ),
    ("review", "merge"): lambda a: _load("review", "cmd_review_merge")(
        a.slug, type_key=a.type_key, force=a.force
    ),
    ("review", "cancel"): lambda a: _load("review", "cmd_review_cancel")(
        a.slug, type_key=a.type_key
    ),
    ("review", "link"): lambda a: _load("review", "cmd_review_link")(
        a.slug, a.pr_url, type_key=a.type_key
    ),
    ("review", "status"): lambda _: _load("review", "cmd_review_status")(),
    ("review", "setup"): lambda a: _load("review", "cmd_review_setup")(force=a.force),
    ("kb", "sync"): lambda _: _load("sync", "cmd_sync")(),
    ("kb", "publish"): lambda _: _load("publish", "cmd_publish")(),
    ("kb", "status"): lambda a: _load("status", "cmd_status")(
        compact=getattr(a, "compact", False)
    ),
    ("kb", "lint"): lambda _: _load("lint", "cmd_lint")(),
    ("kb", "list"): lambda _: _load("kb_manage", "cmd_kb_list")(),
    ("kb", "remove-scope"): lambda a: _load("kb_manage", "cmd_kb_remove_scope")(
        a.name, force=a.force
    ),
    ("kb", "git"): lambda a: _load("kb_git", "cmd_kb_git")(a.git_args),
    ("mode", "enable"): lambda _: _load("mode_cmds", "cmd_enable")(),
    ("mode", "disable"): lambda _: _load("mode_cmds", "cmd_disable")(),
    ("mode", "incognito"): lambda _: _load("mode_cmds", "cmd_incognito")(),
    ("mode", "status"): lambda _: _load("mode_cmds", "cmd_mode_status")(),
    ("init", None): lambda a: _load("init", "cmd_init")(
        kb_url=getattr(a, "kb_url", None),
        local=getattr(a, "local", False),
        create_remote=getattr(a, "create_remote", False),
        kb_name=getattr(a, "kb_name", None),
        slug=getattr(a, "slug", None),
        platforms_raw=getattr(a, "platforms", None),
    ),
    ("hooks", "install"): lambda _: _load("hooks_install", "cmd_hooks_install")(),
    ("update", None): lambda a: _load("update", "cmd_update")(
        diff_target=getattr(a, "diff_target", None)
    ),
    ("feedback", None): lambda a: _load("feedback", "cmd_feedback")(
        " ".join(a.text) if a.text else None
    ),
}


def _dispatch(args: argparse.Namespace) -> int:
    cmd = args.command
    verb = getattr(args, f"{cmd}_command", None)
    handler = _DISPATCH.get((cmd, verb))
    if handler is None:
        # Unreachable when argparse `required=True` is set on every subgroup.
        # If we get here, a verb was added to the parser without a table entry.
        raise RuntimeError(f"No dispatch handler for '{cmd} {verb}'")
    return handler(args)


_INTERNAL_COMMANDS = {
    "_hook-check", "_post-checkout", "_pre-push", "_post-merge",
    "_check-path", "_review-cleanup",
}


def _dispatch_internal(argv: list[str]) -> int:
    """Dispatch internal git hook callbacks (not in argparse, hidden from help)."""
    cmd = argv[0]
    rest = argv[1:]

    if cmd == "_hook-check":
        from reinicorn.commands.internal.hook_check import cmd_hook_check
        return cmd_hook_check()

    if cmd == "_post-checkout":
        from reinicorn.commands.internal.post_checkout import cmd_post_checkout
        return cmd_post_checkout(rest)

    if cmd == "_pre-push":
        from reinicorn.commands.internal.pre_push import cmd_pre_push
        return cmd_pre_push()

    if cmd == "_post-merge":
        from reinicorn.commands.internal.post_merge import cmd_post_merge
        return cmd_post_merge()

    if cmd == "_check-path":
        from reinicorn.commands.doc_create import cmd_doc_check_path
        if not rest:
            return 1
        return cmd_doc_check_path(rest[0])

    if cmd == "_review-cleanup":
        from reinicorn.commands.internal.review_cleanup import cmd_review_cleanup
        return cmd_review_cleanup(rest)

    return 1


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # Internal git hook callbacks bypass argparse (hidden from help).
    if argv and argv[0] in _INTERNAL_COMMANDS:
        try:
            return _dispatch_internal(argv)
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 1

    parser = _build_parser()

    if not argv:
        # home-view note: bare `reinicorn` shows live state (axi principle 8:
        # content first), not the argparse usage manual.
        from reinicorn.commands.home import cmd_home
        return cmd_home()

    if argv[0] == "help":
        parser.print_help()
        return 0

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2

    try:
        return _dispatch(args)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except KeyboardInterrupt:
        return 130
