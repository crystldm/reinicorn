from __future__ import annotations

import tomllib
from pathlib import Path

from reinicorn.identity import (
    CLI_NAME,
    CONFIG_FILE_NAME,
    ENV_PREFIX,
    PRODUCT_NAME,
    STATE_DIR_NAME,
)


def test_public_identity_contract() -> None:
    assert PRODUCT_NAME == "Reinicorn"
    assert CLI_NAME == "rcorn"
    assert STATE_DIR_NAME == ".reinicorn"
    assert CONFIG_FILE_NAME == ".reinicorn-config"
    assert ENV_PREFIX == "REINICORN_"


def test_pyproject_exposes_only_rcorn() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text())
    assert data["project"]["name"] == "reinicorn"
    assert data["project"]["scripts"] == {"rcorn": "reinicorn.cli:main"}
