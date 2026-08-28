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

_ROWS = "".join(f'<tr><td>D{i}</td></tr>' for i in range(1, 10))


def _page(tmp_path: Path, version: str, source: str | None) -> Path:
    src = f"<span>source <b>{source}</b></span>" if source else ""
    p = tmp_path / "page.html"
    p.write_text(
        f'<html><body><div class="fg-snapshot">'
        f'<span>plugin <b>v{version}</b></span>{src}'
        f'<span>flow steps <b>68</b></span></div>'
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
