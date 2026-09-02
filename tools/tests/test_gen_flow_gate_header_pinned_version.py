"""A version beside a pinned commit is that commit's version, not today's.

MEASURED 2026-08-28: the page states `plugin v1.12.33 - source 10b9e12c3`,
because its figures were measured on that commit. The working tree had moved to
v1.12.34, so the generator reported drift, and a plain run would have written
`plugin v1.12.34 - source 10b9e12c3` -- a version and a commit that contradict
each other, on the page whose own rule is that published digits are derived.

Restamping half of a pin breaks the pin.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

for _anc in Path(__file__).resolve().parents:
    if (_anc / "tools" / "gen_flow_gate_header.py").is_file():
        _ROOT = _anc
        break
else:                                                    # pragma: no cover
    raise RuntimeError("gen_flow_gate_header.py not found above this test")

_GEN = _ROOT / "tools" / "gen_flow_gate_header.py"
_PLUGIN_JSON = ("vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json")
_FLOW = (_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "flow"
         / "phase1_phase2_phase3.yaml")


def _live_steps() -> int:
    """The step figure the generator will derive, asked of the SAME function.

    THIS USED TO BE THE LITERAL 68 inside `_page` below, and canonical step 37.4
    turned it red on 2026-09-03: `DRIFT  flow steps 68 -> 69`. The VERSION half
    of this file's subject is pinned to a past commit; the step half is not, and
    never was — the generator derives it from the working tree — so a typed
    figure here was a second, unpinned population that had to be hand-moved
    every time the flow grew, on the page whose entire rule is that a published
    digit must be derived. It is asked of `gen_flow_gate_header.flow_steps`
    rather than recomputed, so the fixture and the generator cannot disagree
    about what a step is.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("_fgh", _GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.flow_steps(_FLOW)[0]

_ROWS = "".join(f'<tr><td>D{i}</td></tr>' for i in range(1, 10))


def _page(tmp_path: Path, version: str, source: str | None) -> Path:
    src = f"<span>source <b>{source}</b></span>" if source else ""
    p = tmp_path / "page.html"
    p.write_text(
        f'<html><body><div class="fg-snapshot">'
        f'<span>plugin <b>v{version}</b></span>{src}'
        f'<span>flow steps <b>{_live_steps()}</b></span></div>'
        f"<table>{_ROWS}</table></body></html>", encoding="utf-8")
    return p


def _check(p: Path):
    return subprocess.run(
        [sys.executable, str(_GEN), "--page", str(p), "--check"],
        capture_output=True, text=True)


def _head_version() -> str:
    return json.loads((_ROOT / _PLUGIN_JSON).read_text(encoding="utf-8"))["version"]


def _a_past_commit() -> tuple[str, str]:
    """An ancestor commit whose plugin version DIFFERS from the tree's."""
    head = _head_version()
    log = subprocess.run(["git", "log", "--format=%H", "-40", "--", _PLUGIN_JSON],
                         cwd=str(_ROOT), capture_output=True, text=True)
    for sha in log.stdout.split():
        blob = subprocess.run(["git", "show", f"{sha}:{_PLUGIN_JSON}"],
                              cwd=str(_ROOT), capture_output=True, text=True)
        if blob.returncode:
            continue
        try:
            v = json.loads(blob.stdout)["version"]
        except (ValueError, KeyError):
            continue
        if v != head:
            return sha[:9], v
    raise AssertionError("no ancestor commit carries a different plugin version")


# ---------------------------------------------------------------- can PASS --
def test_a_pinned_page_is_judged_at_its_pin_not_at_head():
    sha, version = _a_past_commit()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        r = _check(_page(Path(td), version, sha))
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"plugin v{version}" in r.stdout


# ---------------------------------------------------------------- can FAIL --
def test_an_unpinned_page_still_drifts_against_head(tmp_path):
    """Without a pin the old contract holds: the page tracks the tree."""
    r = _check(_page(tmp_path, "0.0.1", None))
    assert r.returncode == 1
    assert f"plugin v0.0.1 -> v{_head_version()}" in r.stdout


def test_a_pin_that_cannot_be_resolved_is_refused_not_restamped(tmp_path):
    r = _check(_page(tmp_path, "0.0.1", "deadbee"))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT a pass" in r.stderr


def test_a_pinned_page_whose_version_is_wrong_for_its_pin_drifts():
    sha, version = _a_past_commit()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        r = _check(_page(Path(td), "0.0.1", sha))
    assert r.returncode == 1
    assert f"plugin v0.0.1 -> v{version}" in r.stdout
