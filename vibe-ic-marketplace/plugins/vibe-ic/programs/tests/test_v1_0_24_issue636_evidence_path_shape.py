"""Regression for ORGANIC #636 — flow_compliance_check._evidence_integrity_scan
dereferences any verdict-JSON `evidence` string containing a '/' as a file
path, so prose notes with an embedded slash false-FAIL EVIDENCE_MISSING.

現象 (round-2 v1.0.22 6-IC clean-room): a PASS verdict artifact carries a
human-readable prose `evidence` field. The #433 scan treated it as a
dereferenceable path whenever it contained ANY '/' (`"/" in ev_ptr`). The
standard single-clock-domain CDC/RDC prose — "...no clock-domain crossings
exist; derived/gated clock tokens attributed to root" — contains the slash
token "derived/gated", so `project / <whole-sentence>` resolved to no file →
the step was downgraded to FAIL EVIDENCE_MISSING, cascading to ~25 downstream
steps.

Fix: `_evidence_integrity_scan` dereferences a verdict-JSON `evidence` string
ONLY when it is structurally path-SHAPED — no embedded whitespace AND (a known
artifact extension OR a known project-output dir prefix) — via the new
`_looks_like_evidence_path` helper. Prose (a multi-word note, or a slashed word
with no extension/prefix) is exempted.

The load-bearing NEGATIVE no-leak half (this is a guard-RELAXING fix — it
narrows WHEN we dereference): a GENUINE broken pointer (#433b, the empty
`sim/reference_tb/ref_tb.log` chain) is still path-shaped (`sim/` prefix +
`.log` ext), so it is STILL dereferenced and STILL FAILs. If the relaxation
were too wide it would silently wave through a real missing-evidence PASS.

chip-AGNOSTIC: pure path-shape structure; no IC-class / token literals.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as F  # noqa: E402


def _verdict_step(project: Path, name: str, payload: dict) -> "F.StepResult":
    """Build a defect-artifact fixture: write a PASS verdict JSON carrying the
    given payload and return a PASS StepResult pointing at it. The end state is
    the status after _evidence_integrity_scan runs the REAL scan."""
    d = project / "reports" / "phase2" / "cdc"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(payload), encoding="utf-8")
    return F.StepResult(id=3, name="CDC / RDC check", stage="phase2",
                        status="PASS",
                        evidence=[f"reports/phase2/cdc/{name}"])


# ── (1) the fix: prose evidence with a slash-in-word stays PASS ──────────────

def test_prose_evidence_with_slash_word_stays_pass(tmp_path):
    """The exact 現象: the standard CDC prose carries 'derived/gated' — must
    NOT be dereferenced as a path; the step stays PASS."""
    sr = _verdict_step(tmp_path, "crossing.json", {
        "verdict": "PASS", "crossings": [], "clocks_found": ["clk_i"],
        "evidence": ("clock-domain scan of 95 RTL file(s); no clock-domain "
                     "crossings exist; derived/gated clock tokens attributed "
                     "to root")})
    out = F._evidence_integrity_scan(tmp_path, sr)
    assert out.status == "PASS", out.reasons


@pytest.mark.parametrize("prose", [
    "input/output delay applied to all ports",
    "REQ/ACK handshake verified",
    "registered and/or combinational outputs checked",
    "scanned RTL file(s) across the design",
])
def test_other_prose_slash_idioms_not_dereferenced(tmp_path, prose):
    sr = _verdict_step(tmp_path, "note.json",
                       {"verdict": "PASS", "evidence": prose})
    out = F._evidence_integrity_scan(tmp_path, sr)
    assert out.status == "PASS", (prose, out.reasons)


# ── (2) NEGATIVE no-leak: a genuine broken pointer still FAILs ────────────────

def test_broken_path_shaped_pointer_still_fails_NOLEAK(tmp_path):
    """#433b: a real broken file pointer with a dir prefix + extension
    (sim/reference_tb/ref_tb.log) is still path-shaped → still dereferenced →
    still FAILs. The relaxation must not leak a real missing-evidence PASS."""
    sr = _verdict_step(tmp_path, "broken.json", {
        "verdict": "PASS", "evidence": "sim/reference_tb/ref_tb.log"})
    out = F._evidence_integrity_scan(tmp_path, sr)
    assert out.status == "FAIL"
    assert any("EVIDENCE_MISSING" in r for r in out.reasons)


def test_broken_bare_filename_pointer_still_fails_NOLEAK(tmp_path):
    """A bare filename WITH a known extension (ref_tb.log) is also path-shaped
    and still caught when missing — the extension arm of the heuristic."""
    sr = _verdict_step(tmp_path, "broken2.json",
                       {"verdict": "PASS", "evidence": "ref_tb.log"})
    out = F._evidence_integrity_scan(tmp_path, sr)
    assert out.status == "FAIL"


def test_empty_path_shaped_pointer_still_fails_NOLEAK(tmp_path):
    """A path-shaped pointer to a 0-byte file still FAILs (the #433 empty
    branch)."""
    (tmp_path / "sim").mkdir()
    (tmp_path / "sim" / "ref_tb.log").write_text("")  # 0 bytes
    sr = _verdict_step(tmp_path, "empty.json",
                       {"verdict": "PASS", "evidence": "sim/ref_tb.log"})
    out = F._evidence_integrity_scan(tmp_path, sr)
    assert out.status == "FAIL"


def test_real_existing_pointer_stays_pass(tmp_path):
    (tmp_path / "sim").mkdir()
    (tmp_path / "sim" / "real.log").write_text("substantive evidence\n")
    sr = _verdict_step(tmp_path, "good.json",
                       {"verdict": "PASS", "evidence": "sim/real.log"})
    out = F._evidence_integrity_scan(tmp_path, sr)
    assert out.status == "PASS", out.reasons


# ── (3) helper unit: path-shape discriminator ────────────────────────────────

@pytest.mark.parametrize("s", [
    "reports/phase2/cdc/crossing.json",
    "sim/reference_tb/ref_tb.log",
    "phase3/pnr/route.def",
    "ref_tb.log",
    "./reports/audit/x.rpt",
    "results/sta/timing.rpt",
])
def test_helper_accepts_real_paths(s):
    assert F._looks_like_evidence_path(s) is True


@pytest.mark.parametrize("s", [
    "derived/gated clock tokens attributed to root",
    "and/or",
    "REQ/ACK",
    "input/output delay",
    "clock-domain scan of 95 RTL file(s)",
    "no crossings",
    "",
    "100% capture",
])
def test_helper_rejects_prose(s):
    assert F._looks_like_evidence_path(s) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
