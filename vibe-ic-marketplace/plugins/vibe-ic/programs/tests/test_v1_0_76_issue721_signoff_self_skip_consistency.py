#!/usr/bin/env python3
"""test_v1_0_76_issue721_signoff_self_skip_consistency.py

Regression test for ORGANIC #721 — META-audit
`signoff_gate_self_skip_consistency_check.py`.

The CLASS (chip-AGNOSTIC, structural): a sign-off gate must NOT map a
runner-disclosed SELF-SKIP / capability-gap attestation (SKIPPED-CONDITION /
SKIP / a named `formal_not_run.json` / `sparse_die_skip.json` /
`single_corner_stance.json` / BENIGN-ERC) to a HARD FAIL. The runner
discloses an honest deferral; a downstream gate that reads only its own rc /
required-output hard-FAILs it. This shipped SIX TIMES (#673/#675/#692/#693/
#694/#696) and was fixed one-at-a-time; this meta-audit catches the CLASS.

This test covers BOTH scopes the program implements and the §4.05 negative:

  CLEAN  (exit 0):
    - the real HEAD plugin tree (corpus-clean bar — all six gates already
      honor their attestation);
    - a synthesized consumer that DOES honor a disclosed skip (defer outcome
      present).

  DEFECT (exit 1) — reproduced as FIXTURES (tmp_path), never mutating real
  files — shaped like each historical 現象:
    - general scope: an `if verdict == 'SKIPPED-CONDITION': return 1` gate
      (a disclosed skip routed straight to a hard FAIL — the #673 / #675 shape);
    - registry scope: a registered consumer (cdc_crossing_check.py) that
      references its disclosed-skip token but has NO distinct defer outcome
      (the pre-#673 `if verdict != 'PASS': FAIL` shape);
    - registry scope: a registered consumer (pvt_matrix_check.py) whose
      disclosed-skip token has been DROPPED entirely (the pre-#694 shape).

  §4.05 NEGATIVE NO-LEAK:
    - a gate that hard-FAILs ONLY on a GENUINE FAIL verdict (verdict=="FAIL")
      while routing the disclosed SKIP to a non-FAIL outcome must NOT be
      flagged — the audit only flags the disclosed-deferral-treated-as-FAIL
      direction, never the reverse;
    - a gate that hard-FAILs on a genuine real violation (no self-skip
      comparison at all) must NOT be flagged.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# programs/ dir is the parent of programs/tests/
_PROGRAMS = Path(__file__).resolve().parent.parent
_PROGRAM = _PROGRAMS / "signoff_gate_self_skip_consistency_check.py"
_PLUGIN_ROOT = _PROGRAMS.parent  # .../plugins/vibe-ic

sys.path.insert(0, str(_PROGRAMS))
import signoff_gate_self_skip_consistency_check as M  # noqa: E402


# ─────────────────────────── helpers ────────────────────────────
def _make_tree(tmp_path: Path, files: dict) -> Path:
    """Build a fake plugin-root with a programs/ dir containing `files`
    (name -> source). Returns the plugin-root path."""
    root = tmp_path / "fake_plugin"
    pd = root / "programs"
    pd.mkdir(parents=True)
    for name, body in files.items():
        (pd / name).write_text(body, encoding="utf-8")
    return root


def _run_cli(plugin_root: Path, tmp_path: Path):
    """Invoke the REAL program as a subprocess. Returns (rc, report_dict)."""
    out_json = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, str(_PROGRAM), str(plugin_root),
         "--json", str(out_json)],
        capture_output=True, text=True,
    )
    report = json.loads(out_json.read_text(encoding="utf-8"))
    return proc.returncode, report


# ───────────────────── corpus-clean (HEAD) ──────────────────────
def test_head_tree_is_corpus_clean():
    """The meta-audit must exit 0 on the current HEAD plugin tree — a
    meta-audit that false-fires on legitimate HEAD state is worse than none."""
    rc, findings, stats = M.audit(_PLUGIN_ROOT)
    assert rc == 0, (
        "meta-audit FALSE-FIRED on HEAD: "
        + "; ".join(f.render() for f in findings))
    assert stats["total_findings"] == 0
    assert stats["registry_edges"] == len(M._REGISTRY)


def test_head_tree_is_corpus_clean_via_cli(tmp_path):
    """Same, but through the real CLI (subprocess) — exit 0 + verdict PASS."""
    rc, report = _run_cli(_PLUGIN_ROOT, tmp_path)
    assert rc == 0, report
    assert report["verdict"] == "PASS"
    assert report["findings"] == []


# ───────────── DEFECT — general scope (the #673/#675 shape) ──────────────
_BUGGY_GENERAL = (
    "import sys\n"
    "def main(argv=None):\n"
    "    # reads the runner's disclosed self-skip verdict ...\n"
    "    verdict = _load_verdict()\n"
    "    if verdict == 'SKIPPED-CONDITION':\n"
    "        # BUG: a disclosed deferral routed straight to a hard FAIL\n"
    "        print('FAIL: required output missing')\n"
    "        return 1\n"
    "    return 0\n"
    "def _load_verdict():\n"
    "    return 'SKIPPED-CONDITION'\n"
)


def test_defect_general_scope_skip_routed_to_hard_fail(tmp_path):
    """A gate whose `if verdict == 'SKIPPED-CONDITION'` body returns 1 (with
    no defer outcome) is the bug shape — must be FLAGGED (exit 1)."""
    root = _make_tree(tmp_path, {"some_signoff_gate.py": _BUGGY_GENERAL})
    rc, findings, _ = M.audit(root)
    assert rc == 1
    rules = {f.rule for f in findings}
    assert "SELF_SKIP_ROUTED_TO_HARD_FAIL" in rules
    assert any(f.scope == "general" for f in findings)


def test_defect_general_scope_via_cli(tmp_path):
    """Same defect, exercised through the real CLI subprocess."""
    root = _make_tree(tmp_path, {"some_signoff_gate.py": _BUGGY_GENERAL})
    rc, report = _run_cli(root, tmp_path)
    assert rc == 1
    assert report["verdict"] == "FAIL"
    assert any(f["rule"] == "SELF_SKIP_ROUTED_TO_HARD_FAIL"
               for f in report["findings"])


def test_defect_general_scope_set_membership_shape(tmp_path):
    """The bug also takes the `verdict in (SKIP, SKIPPED, ...)` membership
    form — must be flagged too."""
    body = (
        "def check(verdict):\n"
        "    if verdict in ('SKIP', 'SKIPPED', 'SKIPPED-CONDITION'):\n"
        "        return 1\n"   # routes disclosed skip to hard fail, no defer
        "    return 0\n"
    )
    root = _make_tree(tmp_path, {"membership_gate.py": body})
    rc, findings, _ = M.audit(root)
    assert rc == 1
    assert any(f.rule == "SELF_SKIP_ROUTED_TO_HARD_FAIL" for f in findings)


# ───────────── DEFECT — registry scope (pre-#673 / pre-#694) ──────────────
def test_defect_registry_consumer_references_skip_but_no_defer(tmp_path):
    """A REGISTERED consumer (cdc_crossing_check.py) that references its
    disclosed-skip token but carries NO distinct defer outcome — the pre-#673
    `if verdict != 'PASS': FAIL` shape — must be FLAGGED."""
    pre_673 = (
        "def main():\n"
        "    verdict = _load()  # may be 'SKIPPED-CONDITION'\n"
        "    if verdict != 'PASS':\n"
        "        print('No CDC report found')\n"
        "        return 1\n"
        "    return 0\n"
        "def _load():\n"
        "    return 'SKIPPED-CONDITION'\n"
    )
    root = _make_tree(tmp_path, {"cdc_crossing_check.py": pre_673})
    rc, findings, _ = M.audit(root)
    assert rc == 1
    reg = [f for f in findings if f.scope == "registry"]
    assert reg, "expected a registry-scope finding for the pre-#673 cdc shape"
    assert reg[0].rule == "EDGE_NO_DEFER_OUTCOME"
    assert reg[0].issue == "#673"


def test_defect_registry_consumer_dropped_skip_token(tmp_path):
    """A REGISTERED consumer (pvt_matrix_check.py) whose disclosed-skip token
    has been DROPPED entirely — the pre-#694 `corner_count==0 -> FAIL` shape,
    blind to single_corner_stance.json — must be FLAGGED."""
    pre_694 = (
        "def main():\n"
        "    corner_count = _count_corners()\n"
        "    if corner_count == 0:\n"
        "        print('not a PVT matrix (#442)')\n"
        "        return 1\n"
        "    return 0\n"
        "def _count_corners():\n"
        "    return 0\n"
    )
    root = _make_tree(tmp_path, {"pvt_matrix_check.py": pre_694})
    rc, findings, _ = M.audit(root)
    assert rc == 1
    reg = [f for f in findings if f.scope == "registry"]
    assert reg, "expected a registry-scope finding for the pre-#694 pvt shape"
    assert reg[0].rule == "EDGE_SKIP_TOKEN_DROPPED"
    assert reg[0].issue == "#694"


# ───────────────────── §4.05 NEGATIVE — no-leak ──────────────────────
def test_negative_genuine_fail_verdict_not_flagged(tmp_path):
    """§4.05: a gate that routes a GENUINE FAIL verdict (a real violation) to
    a hard FAIL — while routing the disclosed SKIP to a non-FAIL outcome —
    is CORRECT and must NOT be flagged. The audit only flags the
    disclosed-deferral-treated-as-FAIL direction, never the reverse."""
    honest = (
        "def main():\n"
        "    verdict = _load()\n"
        "    if verdict == 'SKIPPED-CONDITION':\n"
        "        print('WAIVED-DEFERRED (review required)')\n"
        "        return 0\n"                       # disclosed skip → defer
        "    if verdict == 'FAIL':\n"
        "        print('genuine CDC violation')\n"
        "        return 1\n"                        # GENUINE FAIL → hard fail
        "    return 0\n"
        "def _load():\n"
        "    return 'FAIL'\n"
    )
    root = _make_tree(tmp_path, {"honest_gate.py": honest})
    rc, findings, _ = M.audit(root)
    assert rc == 0, (
        "§4.05 LEAK: a genuine-FAIL gate was wrongly flagged: "
        + "; ".join(f.render() for f in findings))
    assert findings == []


def test_negative_pure_genuine_violation_gate_not_flagged(tmp_path):
    """A gate that hard-FAILs on a genuine violation with NO self-skip
    comparison at all must NOT be flagged (no self-skip token routed to a
    hard FAIL)."""
    real_gate = (
        "def main():\n"
        "    violations = _count()\n"
        "    if violations > 0:\n"
        "        print('DRC dirty')\n"
        "        return 1\n"
        "    return 0\n"
        "def _count():\n"
        "    return 5\n"
    )
    root = _make_tree(tmp_path, {"real_drc_gate.py": real_gate})
    rc, findings, _ = M.audit(root)
    assert rc == 0
    assert findings == []


def test_negative_honoring_registered_consumer_not_flagged(tmp_path):
    """A registered consumer that references its skip token AND carries a
    distinct defer outcome (the HEAD honoring shape) must NOT be flagged."""
    honoring = (
        "def main():\n"
        "    verdict = 'SKIPPED-CONDITION'\n"
        "    if verdict == 'SKIPPED-CONDITION':\n"
        "        print('WAIVED-DEFERRED')\n"
        "        return 0\n"
        "    if verdict == 'FAIL':\n"
        "        return 1\n"
        "    return 0\n"
    )
    root = _make_tree(tmp_path, {"cdc_crossing_check.py": honoring})
    rc, findings, _ = M.audit(root)
    assert rc == 0
    assert findings == []


# ───────────────────── argparse / error handling ──────────────────────
def test_missing_programs_dir_is_io_error(tmp_path):
    """A path with no programs/ dir → rc 2 (argument / I/O error)."""
    proc = subprocess.run(
        [sys.executable, str(_PROGRAM), str(tmp_path / "nope")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))