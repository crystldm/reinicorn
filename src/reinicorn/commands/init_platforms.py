"""Platform selection and instruction-file installation for ``rcorn init``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from reinicorn import console
from reinicorn.assets import get_asset_path

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class Platform:
    """Static configuration for one supported AI coding platform."""

    key: str
    label: str
    default: bool
    template_path: str | None
    destination_path: str | None


PLATFORMS: tuple[Platform, ...] = (
    Platform(
        "claude",
        "Claude Code",
        True,
        "platform-instructions/claude.md",
        "CLAUDE.md",
    ),
    Platform(
        "cursor",
        "Cursor",
        False,
        "platform-instructions/cursor.md",
        ".cursor/rules/reinicorn.mdc",
    ),
    Platform(
        "copilot",
        "GitHub Copilot",
        False,
        "platform-instructions/copilot.md",
        ".github/copilot-instructions.md",
    ),
    Platform("codex", "Codex", False, None, None),
)

_PLATFORM_BY_KEY = {platform.key: platform for platform in PLATFORMS}


def _split_comma_tokens(raw: str) -> list[str]:
    """Split on commas first, then strip each token; drop empty tokens."""
    return [token.strip() for token in raw.strip().split(",") if token.strip()]


def _default_platform_keys() -> list[str]:
    return [platform.key for platform in PLATFORMS if platform.default]


def _parse_platform_selection(raw: str) -> tuple[list[str], list[str]]:
    """Parse numeric interactive selections into platform keys and bad tokens."""
    selected: set[int] = set()
    discarded: list[str] = []
    for token in _split_comma_tokens(raw):
        if token.isascii() and token.isdecimal():
            index = int(token) - 1
            if 0 <= index < len(PLATFORMS):
                selected.add(index)
                continue
        discarded.append(token)
    selected_keys = [
        platform.key for index, platform in enumerate(PLATFORMS) if index in selected
    ]
    return selected_keys, discarded


def parse_platforms_flag(value: str) -> list[str] | None:
    """Parse --platforms KEYS. Returns key list, or None on hard error."""
    if value.strip() == "":
        return []
    selected: set[str] = set()
    for token in _split_comma_tokens(value):
        key = token.lower()
        if key not in _PLATFORM_BY_KEY:
            known_list = ", ".join(platform.key for platform in PLATFORMS)
            console.error(
                f"Unknown platform '{token}'. "
                f"Known platforms: {known_list}. "
                f"How to fix: pass a comma-separated subset, "
                f"e.g. --platforms claude,cursor"
            )
            return None
        selected.add(key)
    return [platform.key for platform in PLATFORMS if platform.key in selected]


def resolve_platforms_arg(
    platforms_raw: str | None,
) -> tuple[bool, list[str] | None]:
    """Resolve --platforms for asset-setup paths.

    Returns ``(ok, platforms)``. ``platforms`` is ``None`` when the flag was
    omitted (caller should prompt). ``ok`` is False when the flag was invalid
    (error already printed).
    """
    if platforms_raw is None:
        return True, None
    parsed = parse_platforms_flag(platforms_raw)
    if parsed is None:
        return False, None
    return True, parsed


def prompt_platforms() -> list[str]:
    """Prompt for a set of AI coding platforms."""
    print("Which AI coding platforms do you use?")
    print()
    for index, platform in enumerate(PLATFORMS, 1):
        print(f"  {index}) {platform.label}")
    print()
    default_labels = ", ".join(platform.label for platform in PLATFORMS if platform.default)
    print(
        f"Enter numbers to select (e.g. 1,2), or Enter for default [{default_labels}]: ",
        end="",
    )
    raw = input()
    stripped = raw.strip()
    if not stripped:
        return _default_platform_keys()

    selected, discarded = _parse_platform_selection(stripped)
    if discarded:
        kept_keys = selected or _default_platform_keys()
        kept_labels = ", ".join(
            platform.label for platform in PLATFORMS if platform.key in kept_keys
        )
        discarded_display = ", ".join(repr(token) for token in discarded)
        if selected:
            console.warn(
                f"Ignored invalid platform selection token(s) {discarded_display}; "
                f"using {kept_labels}."
            )
        else:
            console.warn(
                f"Ignored invalid platform selection {discarded_display}; "
                f"using default [{kept_labels}]."
            )

    return selected or _default_platform_keys()


def install_platform_instructions(
    target_dir: Path, slug: str, platforms: list[str]
) -> None:
    """Generate platform-specific instruction files from templates."""
    for platform in platforms:
        row = _PLATFORM_BY_KEY.get(platform)
        if row is None:
            continue
        if row.destination_path is None:
            console.success(f"{row.label}: uses AGENTS.md (already installed)")
            continue
        if row.template_path is None:
            continue
        src = get_asset_path(row.template_path)
        if src is None:
            console.warn(f"No template for {platform} — skipping")
            continue
        destination = target_dir / row.destination_path
        if destination.is_file():
            console.info(f"{row.destination_path} already exists — keeping existing")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_text().replace("{repo}", slug)
        destination.write_text(content)
        console.success(f"Generated {row.destination_path}")
    print()
