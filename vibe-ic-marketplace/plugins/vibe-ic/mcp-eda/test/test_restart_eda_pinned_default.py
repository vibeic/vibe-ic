#!/usr/bin/env python3
"""Regression: restart-eda.sh must default to the PINNED image version from
tools/vibeic-eda/VERSION, never a floating `latest` — a stale local `latest`
would silently recreate the MCP-EDA container on an outdated toolchain (the
same drift class fixed for fault_atpg_run.py in v1.3.80).

The script's RESTART_EDA_PRINT_IMAGE=1 mode prints the resolved image ref and exits before
any docker interaction, so these tests need no docker daemon. All tests SKIP
cleanly when repo-root tools/ is absent (packaged plugin ships no tools/).
"""
import subprocess
from pathlib import Path

import pytest


def _find_script():
    for up in Path(__file__).resolve().parents:
        c = up / "tools" / "vibeic-eda" / "restart-eda.sh"
        if c.is_file():
            return c
    return None


SCRIPT = _find_script()
_skip = pytest.mark.skipif(SCRIPT is None, reason="tools/vibeic-eda/restart-eda.sh not present")


def _resolve(*args) -> str:
    r = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "RESTART_EDA_PRINT_IMAGE": "1"},
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@_skip
def test_default_is_pinned_version_not_latest():
    version = (SCRIPT.parent / "VERSION").read_text(encoding="utf-8").strip()
    assert version and "latest" not in version
    assert _resolve() == f"vibeic/vibeic-eda:{version}"


@_skip
def test_bare_tag_prepends_repo():
    assert _resolve("0.1.99") == "vibeic/vibeic-eda:0.1.99"


@_skip
def test_full_ref_honored_as_is():
    # deliberately NOT a vibeic-eda ghcr ref — that literal form would trip the
    # sync tool's repo-wide drift net; any full ref exercises the same branch.
    ref = "example.com/some/image:1.2.3"
    assert _resolve(ref) == ref


@_skip
def test_explicit_latest_still_honored_as_opt_in():
    assert _resolve("latest") == "vibeic/vibeic-eda:latest"


@_skip
def test_no_floating_default_in_source():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "${1:-latest}" not in src, (
        "restart-eda.sh must not default to a floating :latest tag"
    )
