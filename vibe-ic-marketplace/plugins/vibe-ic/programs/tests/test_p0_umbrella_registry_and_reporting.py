"""P0 structural-RTL umbrella: registry integrity + report presence.

Three defects from the 63-step x 8-dimension flow-gate audit, all on step P0:

  * dim 2 — `skill_compliance_triangle_check` was registered in
    `_STRUCTURAL_RTL_GATES` but no `programs/skill_compliance_triangle_check.py`
    was ever authored. The dispatch loop's `if not prog.exists(): continue`
    dropped it with no fail, no skip, no waiver and no report line, while the
    umbrella kept advertising `len(_STRUCTURAL_RTL_GATES)` checkers. MEASURED
    on the reference run (spm x ihp-sg13g2, plugin 1.6.71-pr427):
    `reports/audit/flow_compliance_check.log` line 8 reads "P0 umbrella, 241
    checkers" and `grep -c skill_compliance_triangle` over that log returns 0.

  * dim 3 / dim 8 — when every gate PASSes with zero skips and zero waivers,
    the umbrella `StepResult` was never constructed, so P0 vanished from the
    human report, from the JSON `steps` array and from `counts`. The single
    best outcome was the only one with no audit record, and
    `--phase 2 --strict-structural` (verdict scope = `[r for r in results if
    r.id == "P0"]`) then decided PASS over an empty scope.

  * dim 5 — the flow yaml's own P0 name/comment and
    `benchmark_verify_report.STEP_METHOD["P0"]` hardcoded "77 gates", a figure
    roughly 3x below the live registry.

The tests below assert observable properties (what the report contains, which
gates actually dispatch), not source substrings, so they stay valid under any
correct alternative fix — e.g. authoring the missing checker instead of
retiring its registry entry would satisfy the dispatch test just as well.
"""
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest
import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PROGRAMS))
import benchmark_verify_report as _bvr  # noqa: E402
import flow_compliance_check as _flow  # noqa: E402


def _project_with_rtl(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "rtl").mkdir(parents=True)
    (proj / "rtl" / "top.v").write_text(
        "module top(input a, output b); assign b = a; endmodule\n")
    return proj


def _stub_subprocess(monkeypatch, dispatched: list, rc: int = 0):
    """Record every gate the umbrella actually spawns; return `rc` for each."""
    def _fake_run(argv, **_kw):
        dispatched.append(Path(argv[1]).stem)
        return types.SimpleNamespace(returncode=rc, stdout="", stderr="")

    monkeypatch.setattr(_flow.subprocess, "run", _fake_run)


# ---------------------------------------------------------------------------
# dim 2 — every advertised checker really dispatches (or is named as skipped)
# ---------------------------------------------------------------------------
def test_every_registered_structural_gate_dispatches_or_is_named(
        tmp_path, monkeypatch):
    """No registry entry may vanish between the advertised count and the run.

    The umbrella's own step name promises `len(_STRUCTURAL_RTL_GATES)`
    checkers. Each registered gate must therefore either be spawned, or be
    named in the skip list. Silently dropping one — which is what a registry
    entry with no backing program used to do — makes that promise false.
    """
    monkeypatch.setenv("VIBE_IC_COMPLIANCE_WORKERS", "1")
    proj = _project_with_rtl(tmp_path)
    dispatched: list[str] = []
    _stub_subprocess(monkeypatch, dispatched)

    passed, fails, skips, waivers = _flow._run_structural_rtl_gates(proj)

    registered = set(_flow._STRUCTURAL_RTL_GATES)
    named_in_skips = {s.split()[0] for s in skips}
    unaccounted = registered - set(dispatched) - named_in_skips
    assert not unaccounted, (
        "registered structural gates that neither dispatched nor were named "
        f"as skipped: {sorted(unaccounted)}")
    assert passed is True and fails == [] and waivers == []


def test_missing_backing_program_is_disclosed_not_silently_dropped(
        tmp_path, monkeypatch):
    """A registry entry whose program is absent must SAY so, by name.

    Synthetic fixture (the shipped registry has no such entry any more): a
    phantom gate name is injected into the registry, so the missing-program
    branch is exercised for real rather than assumed.
    """
    monkeypatch.setenv("VIBE_IC_COMPLIANCE_WORKERS", "1")
    proj = _project_with_rtl(tmp_path)
    phantom = "zzz_never_authored_gate_check"
    assert not (PROGRAMS / f"{phantom}.py").exists()
    monkeypatch.setattr(
        _flow, "_STRUCTURAL_RTL_GATES",
        tuple(_flow._STRUCTURAL_RTL_GATES) + (phantom,))
    dispatched: list[str] = []
    _stub_subprocess(monkeypatch, dispatched)

    passed, fails, skips, waivers = _flow._run_structural_rtl_gates(proj)

    assert phantom not in dispatched, "phantom gate cannot have a program"
    assert any(s.startswith(phantom) for s in skips), (
        f"missing-program gate {phantom} left no record; skips={skips}")
    # Direction 1: disclosure is not a new failure mode — a missing program
    # is reported, never converted into an umbrella FAIL.
    assert passed is True and fails == []


# ---------------------------------------------------------------------------
# dim 3 / dim 8 — P0 is present in the report in EVERY outcome, including the
# all-clean one
# ---------------------------------------------------------------------------
def _run_main(tmp_path, monkeypatch, umbrella_return, extra_args=()):
    """Drive main() with the gate runner replaced by a fixed outcome."""
    proj = _project_with_rtl(tmp_path)
    monkeypatch.setattr(_flow, "_run_structural_rtl_gates",
                        lambda *a, **k: umbrella_return)
    out = tmp_path / "report.json"
    rc = _flow.main([str(proj), "--json", str(out), *extra_args])
    return rc, json.loads(out.read_text())


def _p0(report):
    hits = [s for s in report["steps"] if s["id"] == "P0"]
    return hits[0] if hits else None


def test_all_gates_clean_still_emits_a_P0_step(tmp_path, monkeypatch, capsys):
    """Clean sweep: P0 must appear as an explicit PASS, not disappear."""
    rc, report = _run_main(tmp_path, monkeypatch, (True, [], [], []),
                           ("--lenient",))
    p0 = _p0(report)
    assert p0 is not None, (
        "P0 missing from the JSON steps array on an all-clean structural run")
    assert p0["status"] == "PASS"
    assert p0["reasons"], "an all-clean P0 must still say what it verified"
    assert report["counts"]["PASS"] >= 1
    assert "Step P0" in capsys.readouterr().out, (
        "P0 missing from the human-readable per-step listing")


def test_strict_structural_verdict_is_not_decided_over_an_empty_scope(
        tmp_path, monkeypatch):
    """`--phase 2 --strict-structural` scopes its verdict to P0 alone.

    With P0 absent that scope is empty and the tool reports PASS having
    examined nothing. The umbrella result must be in the report for the
    verdict to mean anything.
    """
    rc, report = _run_main(tmp_path, monkeypatch, (True, [], [], []),
                           ("--phase", "2", "--strict-structural"))
    assert _p0(report) is not None, (
        "strict-structural verdict computed with no P0 result in scope")
    assert rc == 0


# --- direction 1: the outcomes that already worked must not change ---------
def test_failing_umbrella_still_reports_FAIL_with_its_gate_lines(
        tmp_path, monkeypatch):
    rc, report = _run_main(
        tmp_path, monkeypatch,
        (False, ["FAIL: gate_a — boom", "FAIL: gate_b — bang"], [], []),
        ("--strict",))
    p0 = _p0(report)
    assert p0 is not None and p0["status"] == "FAIL"
    assert p0["reasons"][0] == "Failed gates (2):"
    assert p0["reasons"][1:] == ["  - gate_a — boom", "  - gate_b — bang"]
    assert rc != 0


def test_single_fail_reason_shape_unchanged(tmp_path, monkeypatch):
    rc, report = _run_main(tmp_path, monkeypatch,
                           (False, ["FAIL: gate_a — boom"], [], []),
                           ("--strict",))
    p0 = _p0(report)
    assert p0 is not None and p0["status"] == "FAIL"
    assert p0["reasons"] == ["FAIL: gate_a — boom"]


def test_no_rtl_umbrella_still_reports_SKIPPED_CONDITION(
        tmp_path, monkeypatch):
    """#447: 0/N checkers executed is not a PASS — must stay a skip."""
    rc, report = _run_main(
        tmp_path, monkeypatch,
        (None, [], ["no RTL directory found — structural gates skipped"], []),
        ("--lenient",))
    p0 = _p0(report)
    assert p0 is not None and p0["status"] == "SKIPPED-CONDITION"
    assert p0["reasons"] == [
        "SKIP: no RTL directory found — structural gates skipped"]


def test_skips_and_waivers_are_still_listed_verbatim(tmp_path, monkeypatch):
    waiver = {"gate": "gate_w", "ticket": "T-1", "first_line": "why",
              "review_required": True}
    rc, report = _run_main(tmp_path, monkeypatch,
                           (True, [], ["gate_s (SKIP: class N/A)"], [waiver]),
                           ("--lenient",))
    p0 = _p0(report)
    assert p0 is not None and p0["status"] == "PASS"
    assert p0["reasons"] == [
        "SKIP: gate_s (SKIP: class N/A)",
        "WAIVED-DEFERRED: gate_w — thin-input (ticket=T-1, "
        "review_required=true): why",
    ]
    assert report["counts"]["WAIVED"] == 1


# ---------------------------------------------------------------------------
# dim 5 — P0's static documentation may not state a gate count that the live
# registry contradicts
# ---------------------------------------------------------------------------
# "77 gates", "77 chip-AGNOSTIC structural gates", "77 structural-RTL
# chip-agnostic checkers" all match; version strings like "v1.6.15" and bare
# numbers not describing gates do not.
_COUNT_RE = re.compile(
    r"(?<![.\d])(\d+)\s+(?:[\w-]+\s+){0,3}?(?:gates|checkers|checks)\b",
    re.IGNORECASE)


def _p0_doc_blocks() -> dict[str, str]:
    """P0's static prose: the yaml comment block, the yaml step, the report
    method string."""
    lines = FLOW_YAML.read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if "── P0 " in ln)
    end = next(i for i in range(start, len(lines))
               if lines[i].strip() == "" and i > start)
    steps = yaml.safe_load(FLOW_YAML.read_text())["steps"]
    p0_step = next(s for s in steps if s.get("id") == "P0")
    return {
        f"{FLOW_YAML.name} P0 block": "\n".join(lines[start:end]),
        f"{FLOW_YAML.name} P0 step": json.dumps(p0_step, ensure_ascii=False),
        "benchmark_verify_report.STEP_METHOD['P0']":
            " ".join(_bvr.STEP_METHOD["P0"]),
    }


def test_p0_documentation_exists_and_describes_the_structural_umbrella():
    """Presence guard: the count check below must not pass vacuously."""
    blocks = _p0_doc_blocks()
    assert len(blocks) == 3
    for where, text in blocks.items():
        assert "structural" in text.lower(), f"{where} no longer describes P0"


def test_p0_documentation_states_no_stale_gate_count():
    """Any gate count P0's documentation states must be the live count.

    Either fix satisfies this: drop the hardcoded number, or keep one that is
    correct. What may not survive is a number that contradicts the registry.
    """
    live = len(_flow._STRUCTURAL_RTL_GATES)
    stale = []
    for where, text in _p0_doc_blocks().items():
        for m in _COUNT_RE.finditer(text):
            if int(m.group(1)) != live:
                stale.append(f"{where}: {m.group(0)!r} (live count is {live})")
    assert not stale, "stale gate counts in P0's documentation: " + "; ".join(
        stale)


def test_registry_and_shipped_programs_agree():
    """Every registered structural gate names a program that exists.

    Deliberate policy, stated so a future reader does not mistake it for an
    accident: the umbrella's advertised checker count IS the registry length,
    so the package must ship every checker it registers. A checker that cannot
    be shipped is removed from the registry (and tracked as open work), not
    left in it to skip for ever. The runtime named-skip added alongside this
    test is the safety net for the window in between, not a licence to keep
    phantom entries.

    Static twin of the dispatch test above; catches a phantom entry without
    running 240 subprocesses.
    """
    missing = [g for g in _flow._STRUCTURAL_RTL_GATES
               if not (PROGRAMS / f"{g}.py").exists()]
    assert not missing, (
        "registered in _STRUCTURAL_RTL_GATES but not shipped: "
        f"{missing} — the umbrella advertises "
        f"{len(_flow._STRUCTURAL_RTL_GATES)} checkers")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
