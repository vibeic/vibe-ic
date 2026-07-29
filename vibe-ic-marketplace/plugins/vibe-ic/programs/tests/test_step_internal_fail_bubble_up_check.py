"""Tests for step_internal_fail_bubble_up_check.py (v1.6.44)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "programs"))

import step_internal_fail_bubble_up_check as g  # noqa: E402


def _proj(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    (p / "reports" / "phase3").mkdir(parents=True)
    return p


def _write_report(p: Path, name: str, verdict: str,
                  subdir: str = "phase3") -> Path:
    rp = p / "reports" / subdir / f"{name}.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"verdict": verdict, "tool": "test"}))
    return rp


def _write_waivers(p: Path, entries):
    (p / "waivers.json").write_text(json.dumps({
        "_doc": "test waivers",
        "waived_steps": entries,
    }))


def test_vacuous_when_no_reports(tmp_path):
    p = tmp_path / "empty"
    p.mkdir()
    verdict, findings = g.audit(p)
    assert verdict == "VACUOUS_PASS"


def test_vacuous_when_no_fail_reports(tmp_path):
    p = _proj(tmp_path)
    _write_report(p, "foo", "PASS")
    verdict, findings = g.audit(p)
    assert verdict == "VACUOUS_PASS"


def test_fail_when_no_waiver_no_bubble(tmp_path):
    """The escape this gate exists to catch."""
    p = _proj(tmp_path)
    _write_report(p, "lvs", "FAIL")
    verdict, findings = g.audit(p)
    assert verdict == "FAIL"
    assert findings[0].rule == "STEP_FAIL_NOT_BUBBLED"
    assert "lvs" in findings[0].report_file


def test_pass_when_waiver_mentions_name(tmp_path):
    """The standard happy path: waiver text references the gate name."""
    p = _proj(tmp_path)
    _write_report(p, "lvs", "FAIL")
    _write_waivers(p, [{
        "id": 29,
        "reason": "LVS deferred to Calibre",
        "ticket": "BACKLOG-step29-lvs",
        "evidence": "no LVS artefact",
    }])
    verdict, findings = g.audit(p)
    assert verdict == "PASS", findings


def test_pass_when_bubble_up_records_fail(tmp_path):
    """Even without a waiver, an orchestrator record naming the FAIL
    is enough — overall verdict reflects the failure."""
    p = _proj(tmp_path)
    _write_report(p, "antenna", "FAIL")
    odir = p / "reports" / "orchestrator"
    odir.mkdir(parents=True)
    (odir / "phase3_one_shot.json").write_text(json.dumps({
        "summary": "antenna gate FAIL — see reports/phase3/antenna.json",
        "verdict": "FAIL",
    }))
    verdict, findings = g.audit(p)
    assert verdict == "PASS", findings


def test_neutral_verdicts_skipped(tmp_path):
    """INSUFFICIENT_DATA, FALLBACK, SKELETON_EMITTED, WAIVED do not
    trigger the gate — they're orthogonal to bubble-up enforcement."""
    p = _proj(tmp_path)
    for v in ("INSUFFICIENT_DATA", "FALLBACK", "SKELETON_EMITTED",
              "WAIVED"):
        _write_report(p, f"r_{v.lower()}", v)
    verdict, findings = g.audit(p)
    assert verdict == "VACUOUS_PASS"


def test_audit_dir_excluded(tmp_path):
    """reports/audit/ files are human-authored; gate must not flag
    their `verdict: FAIL` as escapes."""
    p = _proj(tmp_path)
    audit_dir = p / "reports" / "audit"
    audit_dir.mkdir(parents=True)
    (audit_dir / "human_review.json").write_text(json.dumps({
        "verdict": "FAIL",
        "reviewer": "human",
    }))
    verdict, findings = g.audit(p)
    assert verdict == "VACUOUS_PASS"


def test_waiver_matches_via_step_id(tmp_path):
    """Waiver `id: 29` matches reports referencing `step29` / step-29
    via the `step{id}` corpus expansion."""
    p = _proj(tmp_path)
    rp = p / "reports" / "phase3" / "step29.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"verdict": "FAIL"}))
    _write_waivers(p, [{
        "id": 29,
        "reason": "deferred",
        "ticket": "T-29",
        "evidence": "x",
    }])
    verdict, findings = g.audit(p)
    assert verdict == "PASS", findings


def test_short_candidates_filtered(tmp_path):
    """Two-letter parent dirs / stem fragments must NOT cause spurious
    matches against random corpus text."""
    p = _proj(tmp_path)
    # "em.json" stem split would yield "em" (2 chars) — but we keep
    # the full stem candidate "em" (2 chars) intentionally below the
    # 3-char minimum, so it must NOT match "memory" in waiver text.
    _write_report(p, "em", "FAIL")
    _write_waivers(p, [{
        "id": 99,
        "reason": "memory leak deferred",
        "ticket": "X",
        "evidence": "y",
    }])
    verdict, findings = g.audit(p)
    # Should FAIL — `em` is too short to match anything reliably.
    assert verdict == "FAIL"
    assert findings[0].rule == "STEP_FAIL_NOT_BUBBLED"


# --- the CLI layer: the gate had, one layer up, the defect it exists to catch

def _cli():
    import step_internal_fail_bubble_up_check as M
    return M


def test_an_unacknowledged_fail_exits_1(tmp_path, monkeypatch):
    """THE point of this file.

    Every test above drives `audit()` and asserts on the VERDICT. None of them
    touches `main()`, so the verdict -> exit-code mapping was unmeasured — and
    the flow reads the exit code, not the verdict. `gate_cli_mutation_probe`
    neutered the CLI so it could never return non-zero and all nine passed.

    Which makes this gate the plainest example in the repo of a checker
    exhibiting the defect it checks for: its subject is an inner FAIL that never
    reaches the outer exit code, and that is exactly what it had.
    """
    M = _cli()
    from dataclasses import dataclass

    @dataclass
    class F:
        rule: str = "unacknowledged"
        report_file: str = "reports/step07/lint.json"
        verdict: str = "FAIL"
        detail: str = ""
    monkeypatch.setattr(M, "audit", lambda proj: ("FAIL", [F()]))
    assert M.main([str(tmp_path)]) == 1


def test_pass_exits_0(tmp_path, monkeypatch):
    """…or the test above is met by a gate that always returns 1."""
    M = _cli()
    monkeypatch.setattr(M, "audit", lambda proj: ("PASS", []))
    assert M.main([str(tmp_path)]) == 0


def test_vacuous_pass_exits_0(tmp_path, monkeypatch):
    """A third verdict with its own branch, and its own way to go wrong.

    VACUOUS_PASS means nothing was examined. It exits 0 deliberately — a
    pre-output project has no reports to acknowledge — so the branch is easy to
    break in the direction of "always 0" without any test noticing.
    """
    M = _cli()
    monkeypatch.setattr(M, "audit", lambda proj: ("VACUOUS_PASS", []))
    assert M.main([str(tmp_path)]) == 0


def test_a_missing_project_dir_is_rc_2_not_rc_0(tmp_path):
    """"I could not look" must never share an exit code with "I looked and it
    was clean" — the absence-renders-as-a-pass shape this repo keeps finding."""
    M = _cli()
    assert M.main([str(tmp_path / "no-such-project")]) == 2
