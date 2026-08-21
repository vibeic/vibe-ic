#!/usr/bin/env python3
"""_shipped_version.py — the shipped plugin version, read INDEPENDENTLY.

vibe-ic#800. Eighteen attribution tests asserted `"v0.1.50" in
d["emitted_by"]`. That shape cannot distinguish a version that was READ from
one that was TYPED, so it passed unbroken while the plugin advanced from 0.1.50
to 1.9.78 and every artefact carried the stale claim. Worse, it actively
DEFENDED the defect: correcting the emitter turned the test red, so the cheap
move was always to leave the literal alone.

The replacement asserts the emitted string equals `"<tool> v<shipped>"`. To
avoid the tautology of asking the code under test what it thinks the version is,
this helper reads `.claude-plugin/plugin.json` itself, with `json`, and nothing
else. `plugin_manifest_discovery.running_plugin_version()` is separately pinned
against this same manifest AND against two absurd manifests in
`test_issue800_emitted_by_reads_the_real_version.py`.

Its own module rather than conftest.py for the reason `_source_pin.py` gives:
two conftest.py files sit on the path and a bare `from conftest import …`
resolves to whichever pytest imported first.
"""
from __future__ import annotations

import json
from pathlib import Path

_PLUGIN_JSON = (Path(__file__).resolve().parent.parent.parent
                / ".claude-plugin" / "plugin.json")


def shipped_plugin_version() -> str:
    """`version` from the plugin manifest. Raises if it cannot be read — a test
    helper that guesses is how an assertion passes over an unknown truth."""
    return json.loads(_PLUGIN_JSON.read_text(encoding="utf-8"))["version"]
