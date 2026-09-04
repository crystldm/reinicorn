"""CLI entry point — argparse dispatcher."""

from __future__ import annotations

import argparse
import importlib
import sys

from reinicorn import __version__
from reinicorn.doc_types import (
    Addressing,
    CreateMode,
    DocTypesError,
    TitleSource,
    closable_types,
    registry,
)
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

    # ── Doc-type groups (generated from the registry; spec:
    # registry-driven-doc-types stage 2) ─────────────────────
    def _add_doc_type_groups(sub) -> dict:
        """Returns {key: subparsers action} so bespoke verbs (plan's
        lifecycle) can attach without reflecting over argparse internals."""
        groups: dict = {}
        for dt in registry().values():
            g = sub.add_parser(dt.key, help=dt.help_text)
            gs = g.add_subparsers(dest=f"{dt.key}_command")
            gs.required = True
            groups[dt.key] = gs
            if dt.title_source is TitleSource.TITLE:
                cp = gs.add_parser(
                    dt.create_verb,
                    help=(f"Append a {dt.key}" if dt.create_mode is CreateMode.APPEND
                          else f"Create a {dt.key} doc"),
                )
                cp.add_argument("title", nargs="+", help="Document title")
            elif dt.title_source is TitleSource.FREE_TEXT:
                cp = gs.add_parser(
                    dt.create_verb, help=f"Capture free-form {dt.key} text"
                )
                cp.add_argument("text", nargs="+", help=f"{dt.key} text")
            else:
                gs.add_parser(
                    dt.create_verb,
                    help=f"Create the {dt.key} for the current branch",
                )
            if dt.addressing is Addressing.SLUG:
                sp = gs.add_parser(
                    "show",
                    help=f"Show a {dt.key} doc (truncated; --full for all)",
                )
                sp.add_argument("slug", help="Doc slug (see 'list')")
                sp.add_argument("--full", action="store_true", help="Print the whole doc")
                sp.add_argument(
                    "--include-drafts", action="store_true",
                    help="Include drafts/ (unapproved) docs",
                )
                lp = gs.add_parser("list", help=f"List {dt.key} docs")
                lp.add_argument(
                    "--include-drafts", action="store_true",
                    help="Include drafts/ (unapproved) docs",
                )
            elif dt.addressing is Addressing.BRANCH:
                sp = gs.add_parser(
                    "show", help=f"Show the {dt.key} doc (truncated; --full for all)"
                )
                sp.add_argument(
                    "branch", nargs="?", default=None,
                    help="Branch name (default: current)",
                )
                sp.add_argument("--full", action="store_true", help="Print the whole doc")
            # Addressing.SINGLETON: create verb only (principle today).
        return groups

    doc_groups = _add_doc_type_groups(sub)

    # Lifecycle verbs, generated for every closable type (something in the
    # registry closes it): status and complete join the generated create.
    for dt in closable_types():
        group = doc_groups[dt.key]
        group.add_parser(
            "status", help=f"Show {dt.key} status for current branch"
        )
        complete_p = group.add_parser(
            "complete", help=f"Archive {dt.key} to the completed stage"
        )
        complete_p.add_argument(
            "branch", nargs="?", default=None,
            help="Branch name (default: current)",
        )

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

    # ── Doc-types group (the process-as-config surface) ─────
    dtypes_p = sub.add_parser(
        "doc-types", help="Doc-type registry operations (effective process)"
    )
    dtypes_sub = dtypes_p.add_subparsers(dest="doc-types_command")
    dtypes_sub.required = True
    dtypes_show_p = dtypes_sub.add_parser(
        "show", help="Print the effective registry (defaults + overlay)"
    )
    dtypes_show_p.add_argument(
        "--schema", action="store_true",
        help="Emit a JSON Schema for doc-types.yaml instead",
    )

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

    # ── Skills group ────────────────────────────────────────
    skills_p = sub.add_parser(
        "skills", help="Skill-set adapter management (install, status, update, list)"
    )
    skills_sub = skills_p.add_subparsers(dest="skills_command")
    skills_sub.required = True
    skills_install_p = skills_sub.add_parser("install", help="Install a skill-set adapter")
    skills_install_p.add_argument(
        "adapter", help="Bundled adapter name or path to an adapter directory"
    )
    skills_sub.add_parser("status", help="Installed adapter, pin, and local drift")
    skills_update_p = skills_sub.add_parser(
        "update", help="Re-fetch and re-apply the installed adapter"
    )
    skills_update_p.add_argument(
        "--ref", dest="ref", default=None, help="New commit SHA to pin"
    )
    skills_update_p.add_argument(
        "--force", action="store_true", help="Overwrite locally modified files"
    )
    skills_sub.add_parser("list", help="List bundled adapters")

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
            "(case-insensitive; skip interactive prompt)"
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


def _doc_dispatch_rows() -> dict:
    """Generated (noun, verb) rows for every registry doc type (spec:
    registry-driven-doc-types stage 2). Hand-wired rows merged into
    _DISPATCH after this override plan's create/status/complete."""
    rows: dict = {}
    closable = {t.key for t in closable_types()}
    for dt in registry().values():
        key = dt.key
        if key in closable:
            # Closable types route create through the lifecycle entry point
            # (templates, ticket, overlap check) and gain status/complete.
            rows[(key, dt.create_verb)] = (
                lambda _, k=key: _load(
                    "doc_lifecycle", "cmd_lifecycle_create"
                )(k)
            )
            rows[(key, "status")] = (
                lambda _, k=key: _load(
                    "doc_lifecycle", "cmd_lifecycle_status"
                )(k)
            )
            rows[(key, "complete")] = (
                lambda a, k=key: _load(
                    "doc_lifecycle", "cmd_lifecycle_complete"
                )(k, a.branch)
            )
        elif dt.title_source is TitleSource.TITLE:
            rows[(key, dt.create_verb)] = (
                lambda a, k=key: _load("doc_create", "cmd_doc_create")(
                    k, " ".join(a.title)
                )
            )
        elif dt.title_source is TitleSource.FREE_TEXT:
            rows[(key, dt.create_verb)] = (
                lambda a, k=key: _load("doc_create", "cmd_doc_create")(
                    k, " ".join(a.text)
                )
            )
        else:
            rows[(key, dt.create_verb)] = (
                lambda _, k=key: _load("doc_create", "cmd_doc_create")(k)
            )
        if dt.addressing is Addressing.SLUG:
            rows[(key, "show")] = (
                lambda a, k=key: _load("doc_show", "cmd_doc_show")(
                    k, a.slug, full=a.full, include_drafts=a.include_drafts
                )
            )
            rows[(key, "list")] = (
                lambda a, k=key: _load("doc_show", "cmd_doc_list")(
                    k, include_drafts=a.include_drafts
                )
            )
        elif dt.addressing is Addressing.BRANCH:
            rows[(key, "show")] = (
                lambda a, k=key: _load("doc_show", "cmd_branch_show")(
                    k, a.branch, full=a.full
                )
            )
    return rows


# Maps (noun, verb) -> handler taking the parsed args Namespace and returning an
# exit code. Top-level nouns with no sub-verb use a None verb. Each handler lazily
# imports its command so importing this module stays cheap.
# Registry-generated rows merge in at dispatch time (not import time): the
# effective registry may read a kb overlay, and a broken overlay must fail
# closed through main's DocTypesError handler, not as an import crash.
_DISPATCH = {
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
    ("doc-types", "show"): lambda a: _load("doc_types_cmd", "cmd_doc_types_show")(
        schema=a.schema
    ),
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
    ("skills", "install"): lambda a: _load("skills_cmds", "cmd_skills_install")(
        a.adapter
    ),
    ("skills", "status"): lambda _: _load("skills_cmds", "cmd_skills_status")(),
    ("skills", "update"): lambda a: _load("skills_cmds", "cmd_skills_update")(
        ref=a.ref, force=a.force
    ),
    ("skills", "list"): lambda _: _load("skills_cmds", "cmd_skills_list")(),
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


def _dispatch_table() -> dict:
    """The effective dispatch table: generated rows, hand-wired overrides."""
    return {**_doc_dispatch_rows(), **_DISPATCH}


def _dispatch(args: argparse.Namespace) -> int:
    cmd = args.command
    verb = getattr(args, f"{cmd}_command", None)
    handler = _dispatch_table().get((cmd, verb))
    if handler is None:
        # Unreachable when argparse `required=True` is set on every subgroup.
        # If we get here, a verb was added to the parser without a table entry.
        raise RuntimeError(f"No dispatch handler for '{cmd} {verb}'")
    return handler(args)


_INTERNAL_COMMANDS = {
    "_hook-check", "_post-checkout", "_pre-push", "_post-merge",
    "_check-path", "_review-cleanup", "_review-check",
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

    if cmd == "_review-check":
        from reinicorn.commands.internal.review_check import cmd_review_check
        return cmd_review_check(rest)

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

    try:
        parser = _build_parser()
    except DocTypesError as e:
        # A broken doc-types.yaml fails closed for every command (the
        # parser itself is generated from the registry) — with the file
        # and offending key, not a traceback.
        from reinicorn import console
        console.error(str(e))
        return 1

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
    except DocTypesError as e:
        from reinicorn import console
        console.error(str(e))
        return 1
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except KeyboardInterrupt:
        return 130
