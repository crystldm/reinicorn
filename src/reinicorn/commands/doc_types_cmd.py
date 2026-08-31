"""`rcorn doc-types show` — print the effective registry.

"Copy the row, change one line" is the documented way to customize the doc
process, so the printout is valid overlay YAML with each row annotated
`built-in` / `overlay`. `--schema` emits a JSON Schema for editor
validation of ``doc-types.yaml``.
"""

from __future__ import annotations

import dataclasses
import json
from enum import Enum

import yaml

from reinicorn.doc_types import (
    OVERLAY_FILENAME,
    DocType,
    overlay_keys,
    overlay_schema,
    registry,
)


def _row_yaml(dt: DocType) -> str:
    """One row as overlay-shaped YAML (enums by value, tuples as lists)."""
    entry: dict[str, object] = {}
    for f in dataclasses.fields(DocType):
        if f.name == "key":
            continue
        value = getattr(dt, f.name)
        if isinstance(value, Enum):
            value = value.value
        elif f.name == "extra_meta":
            value = dict(value)
        elif isinstance(value, tuple):
            value = list(value)
        entry[f.name] = value
    return yaml.safe_dump(
        entry, sort_keys=False, allow_unicode=True,
        default_flow_style=False, width=float("inf"),
    )


def cmd_doc_types_show(schema: bool = False) -> int:
    if schema:
        print(json.dumps(overlay_schema(), indent=2))
        return 0

    overlaid = overlay_keys()
    print(f"# Effective doc-type registry (built-in defaults + {OVERLAY_FILENAME})")
    print("doc_types:")
    for key, dt in registry().items():
        origin = "overlay" if key in overlaid else "built-in"
        print(f"  {key}:  # {origin}")
        for line in _row_yaml(dt).rstrip("\n").splitlines():
            print(f"    {line}")
    return 0
