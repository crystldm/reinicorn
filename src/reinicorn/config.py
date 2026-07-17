"""Read and write Reinicorn repository configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reinicorn.identity import CONFIG_FILE_NAME, KB_SCOPE_KEY

if TYPE_CHECKING:
    from pathlib import Path


KB_DIR_NAME = "kb"


def config_get(key: str, default: str = "", root: Path | None = None) -> str:
    """Read a repository config key, returning *default* if missing."""
    if root is None:
        from reinicorn.git import repo_root
        root = repo_root(quiet=True)
        if root is None:
            return default

    config_file = root / CONFIG_FILE_NAME
    if not config_file.is_file():
        return default

    for line in config_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        k, v = stripped.split("=", 1)
        if k.strip() == key:
            return v.strip().strip("\"'")

    return default


def kb_scope(root: Path | None = None) -> str:
    """Return the configured KB scope, falling back to the origin-derived slug.

    A configured scope becomes a directory name under kb/, so an invalid value
    is rejected here (fail closed) rather than silently trusted.
    """
    configured = config_get(KB_SCOPE_KEY, root=root)
    if configured:
        from reinicorn.validation import is_valid_scope_name
        if not is_valid_scope_name(configured):
            from reinicorn import console
            console.error(
                f"Invalid {KB_SCOPE_KEY} '{configured}' in {CONFIG_FILE_NAME}.\n"
                f"  A scope must start with a letter or digit and contain only\n"
                f"  letters, digits, '.', '-', or '_'.\n"
                f"  How to fix: edit {CONFIG_FILE_NAME} and set a valid {KB_SCOPE_KEY}."
            )
            raise SystemExit(1)
        return configured
    from reinicorn.git import repo_slug
    return repo_slug()


def config_set(key: str, value: str, root: Path) -> None:
    """Set one KEY=value entry while preserving unrelated config lines."""
    path = root / CONFIG_FILE_NAME
    lines = path.read_text().splitlines() if path.is_file() else []
    replacement = f"{key}={value}"
    output: list[str] = []
    replaced = False
    for line in lines:
        if line.partition("=")[0].strip() == key:
            output.append(replacement)
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(replacement)
    path.write_text("\n".join(output) + "\n")
