"""Owner directive 2026-06-17 — "field dont need to have version to issue pr.
all versions are given by gatekeeper".

handoff_bundle_check criterion (7): a Field deep-resolution bundle's
candidate.patch must NOT bump a version file (`.claude-plugin/plugin.json` or
`.claude-plugin/marketplace.json`) — the gatekeeper assigns ALL versions at
merge (two in-flight bundles that each self-bumped would collide). A bundle
whose patch touches a version file is INCOMPLETE (fail-closed).

These pin the `check_version_less` unit AND the end-to-end `evaluate()` verdict.
chip-AGNOSTIC: pure diff-header inspection, no chip/vendor literal.
"""
import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))
import handoff_bundle_check as H  # noqa: E402


# ── unit: check_version_less on synthetic patch text ──────────────────────────
_PRODUCER_ONLY = (
    "diff --git a/programs/phase3_demo.py b/programs/phase3_demo.py\n"
    "--- a/programs/phase3_demo.py\n"
    "+++ b/programs/phase3_demo.py\n"
    "@@ -1,3 +1,3 @@\n"
    "-    tcl = _build_pnr_tcl(project, top)\n"
    "+    tcl = _build_pnr_tcl(project, top, fix=True)\n"
)
_BUMPS_PLUGIN = (
    "diff --git a/vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"
    " b/vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json\n"
    "--- a/vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json\n"
    "+++ b/vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json\n"
    "@@ -1,3 +1,3 @@\n"
    '-  "version": "1.1.6",\n'
    '+  "version": "1.1.7",\n'
)
_BUMPS_MARKETPLACE = (
    "diff --git a/vibe-ic-marketplace/.claude-plugin/marketplace.json"
    " b/vibe-ic-marketplace/.claude-plugin/marketplace.json\n"
    "--- a/vibe-ic-marketplace/.claude-plugin/marketplace.json\n"
    "+++ b/vibe-ic-marketplace/.claude-plugin/marketplace.json\n"
    "@@ -1,3 +1,3 @@\n"
    '-      "version": "1.1.6",\n'
    '+      "version": "1.1.7",\n'
)


def _write(tmp_path, text):
    p = tmp_path / "candidate.patch"
    p.write_text(text, encoding="utf-8")
    return p


def test_versionless_producer_patch_passes(tmp_path):
    ok, detail = H.check_version_less(_write(tmp_path, _PRODUCER_ONLY))
    assert ok is True, detail


def test_patch_bumping_plugin_json_fails(tmp_path):
    ok, detail = H.check_version_less(
        _write(tmp_path, _PRODUCER_ONLY + _BUMPS_PLUGIN))
    assert ok is False
    assert "plugin.json" in detail


def test_patch_bumping_marketplace_json_fails(tmp_path):
    ok, detail = H.check_version_less(
        _write(tmp_path, _PRODUCER_ONLY + _BUMPS_MARKETPLACE))
    assert ok is False
    assert "marketplace.json" in detail


def test_missing_patch_fails_closed(tmp_path):
    ok, detail = H.check_version_less(tmp_path / "nope.patch")
    assert ok is False


# ── §4.05: a NON-version JSON near the same dir must NOT trip the guard ────────
def test_unrelated_json_does_not_trip(tmp_path):
    # a plugin config that is NOT the .claude-plugin/{plugin,marketplace}.json
    other = (
        "diff --git a/programs/ic_class_registry.json"
        " b/programs/ic_class_registry.json\n"
        "--- a/programs/ic_class_registry.json\n"
        "+++ b/programs/ic_class_registry.json\n"
        "@@ -1 +1 @@\n"
        '-{"x": 1}\n+{"x": 2}\n'
    )
    ok, detail = H.check_version_less(_write(tmp_path, _PRODUCER_ONLY + other))
    assert ok is True, detail


# ── end-to-end evaluate(): a bundle whose patch bumps a version file is
#    INCOMPLETE with the version_less_candidate item failing ───────────────────
def test_evaluate_blocks_versionless_violation(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "candidate.patch").write_text(
        _PRODUCER_ONLY + _BUMPS_PLUGIN, encoding="utf-8")
    # minimal manifest so _load_manifest succeeds and evaluate() reaches the
    # contract items (the other items may fail — we only assert the version
    # criterion BLOCKs and the overall verdict is INCOMPLETE, not ADMIT).
    (bundle / "manifest.json").write_text(
        json.dumps({"candidate": "candidate.patch"}), encoding="utf-8")
    rep = H.evaluate(bundle, None, repo_root_override=tmp_path)
    assert rep.verdict == "INCOMPLETE"
    vl = next(it for it in rep.items if it.key == "version_less_candidate")
    assert vl.ok is False
    assert "plugin.json" in vl.detail


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
