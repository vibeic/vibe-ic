#!/usr/bin/env python3
"""vibe-ic#991 — a field that is PRESENT in an unreadable shape is REFUSED,
never counted as a zero.

chip-AGNOSTIC: every fixture is synthesised from neutral parts. No design, PDK,
vendor, SKU or process token appears in the source, the test names or the
fixtures.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


# ===========================================================================
# ip_catalog_query — a declared dependency silently vanished.
# ===========================================================================
_CORE_MANIFEST = (
    "ip_name: dep_core\n" 'ip_version: "1.0"\n' "ip_class: leaf\n"
    "license: ISC\n" "canonical_url: https://example.invalid/dep_core\n"
    "description: a leaf\n" "implements:\n  architecture: leaf\n"
    "matches_when:\n  - \"L2 mentions 'zzq_leaf_token'\"\n"
    "interface:\n  ports:\n    - name: clk\n      dir: in\n"
    "rtl_files:\n  - dep_core.v\n")


def _top_manifest(depends_on: str) -> str:
    return ("ip_name: top_ip\n" 'ip_version: "1.0"\n' "ip_class: soc\n"
            "license: ISC\n" "canonical_url: https://example.invalid/top_ip\n"
            "description: a top\n" "implements:\n  architecture: soc\n"
            "matches_when:\n  - \"L2 mentions 'zzq_top_token'\"\n"
            "interface:\n  ports:\n    - name: clk\n      dir: in\n"
            "rtl_files:\n  - top_ip.v\n" + depends_on)


def _catalog_query(tmp_path: Path, name: str, depends_on: str):
    import ip_catalog_query as mod
    cat = tmp_path / name / "cat"
    for sub, body in (("top_ip", _top_manifest(depends_on)),
                      ("dep_core", _CORE_MANIFEST)):
        (cat / "cpu" / sub).mkdir(parents=True)
        (cat / "cpu" / sub / "manifest.yaml").write_text(body)
    proj = tmp_path / name / "proj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L2_ARCHITECTURE.json").write_text(
        '{"note": "this design needs a zzq_top_token block"}')
    return mod.query_catalog(proj, catalog_dir=cat, min_confidence=0.4)


def test_ipcatalog_a_a_manifest_with_an_unreadable_list_is_not_offered(tmp_path):
    ms = _catalog_query(tmp_path, "m",
                        "depends_on:\n  dep_core: required for integration\n")
    # On origin/main: `top_ip` IS offered, with `depends_on == []`, and
    # `dep_core` is silently absent — so this is `assert ['top_ip'] == []`.
    assert sorted(m.ip_name for m in ms) == [], [m.ip_name for m in ms]


def test_ipcatalog_b_the_refusal_is_recorded_on_the_match(tmp_path):
    import ip_catalog_query as mod
    m = mod._manifest_to_match(
        {"ip_name": "x", "depends_on": {"d": "why"},
         "rtl_files": ["a.v"]}, "p", 1.0)
    assert [r["field"] for r in m.shape_refusals] == ["depends_on"]
    assert m.shape_refusals[0]["keys"] == ["d"]
    assert "d" in (mod._refuse_unreadable_shape(m) or "")


def test_ipcatalog_c_a_well_formed_dependency_is_still_auto_included(tmp_path):
    """PASSES IN BOTH ARMS. The refusal must not have been bought by breaking
    the transitive auto-include the readable path depends on."""
    ms = _catalog_query(tmp_path, "w", "depends_on:\n  - dep_core\n")
    assert sorted(m.ip_name for m in ms) == ["dep_core", "top_ip"]


# ===========================================================================
# The helper's own guard rail. A module that refused absent / [] / null would
# replace one silent pass with a wall of false findings — the failure mode
# `gate_zero_denominator_refuses_check` records as having flipped
# 182/159/94/42 of 182 tracked run dirs before being reverted.
# ===========================================================================
@pytest.mark.parametrize("doc,key", [
    ({}, "k"),                      # absent
    ({"k": []}, "k"),               # a declared empty list
    ({"k": None}, "k"),             # an explicit null
    ({"k": ["a"]}, "k"),            # a well-formed list
    ("not an object", "k"),         # the caller's own outer shape problem
])
def test_helper_a_a_real_zero_is_never_a_refusal(doc, key):
    import _shape_refusal as sr
    _, mismatch = sr.read_list_from(doc, key)
    assert mismatch is None, (doc, mismatch)


def test_helper_b_a_refusal_names_the_type_and_the_content():
    import _shape_refusal as sr
    _, m = sr.read_list_from({"k": {"a": 1, "b": 2}}, "k")
    assert m["json_type"] == "object"
    assert m["keys"] == ["a", "b"]
    assert m["entries_not_examined"] == 2
    s = sr.sentence(m, "somewhere")
    assert "somewhere" in s and "'a'" in s and "NOT a reading of zero" in s
    # A boolean must not describe itself as a number: `isinstance(True, int)`.
    _, mb = sr.read_list_from({"k": True}, "k")
    assert mb["json_type"] == "boolean"
