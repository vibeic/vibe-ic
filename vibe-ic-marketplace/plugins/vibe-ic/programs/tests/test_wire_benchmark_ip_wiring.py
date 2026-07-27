#!/usr/bin/env python3
"""wire/benchmark_ip — the wiring for three checks that already worked and that
nothing invoked, so what they check had never been enforced.

Each of the three had a written claim of enforcement and no caller:

  benchmark_result_md_lint.py   open-benchmark-methodology § 6 says it "fails the
                                run if any of the seven mandatory sections is
                                missing"; repo-wide the only non-test mentions
                                were that skill line and a docstring in
                                run_output_completeness_check.py that explicitly
                                DISCLAIMS running it.
  benchmark_score_cwd_guard.py  § 3 says the cwd=design_dir rule is "enforced by"
                                it; the only other mention was a docstring inside
                                score_iverilog_tb.py.
  ip_catalog_validate.py        its own docstring says "Run from CI / pre-commit
                                hook"; no workflow, no hook and no flow step ran
                                it, while ip-catalog/README.md step 4 declares
                                passing it mandatory for a new IP.

These tests assert the WIRING EXISTS so it cannot silently fall out again, and —
where the channel allows it — that the check still FAILs on a bad input THROUGH
the new channel.

logic-pinned.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = _PROGRAMS.parent
_REPO = _PLUGIN.parent.parent.parent
_HYGIENE = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
_SECTIONS_GATE = _REPO / "tools" / "ci" / "benchmark_result_md_sections_gate.sh"
_SCORER = _PLUGIN / "benchmark" / "score_iverilog_tb.py"
_DISPATCH = _PROGRAMS / "benchmark_dispatch.py"

_LINT = _PROGRAMS / "benchmark_result_md_lint.py"
_CWD_GUARD = _PROGRAMS / "benchmark_score_cwd_guard.py"
_CATALOG_VALIDATE = _PROGRAMS / "ip_catalog_validate.py"


def _complete_result_md() -> str:
    """A RESULT.md carrying all seven § 6 sections."""
    return (
        "# Headline: pass@1 = 3/3, denominator 3, what was measured: functional\n"
        "## Shape\nShape B; entry point vibe_ic_one_shot_runner.py.\n"
        "## Score trajectory\nsingle-shot 2/3 -> close-loop stage 1 -> 3/3.\n"
        "## Residual triage\ncategory A: none. floor: none. agent-fixable: none.\n"
        "## Tool substitution\nWe substitute iverilog 12 for Synopsys VCS.\n"
        "## Reproduce\ncommand line: score_iverilog_tb.py --bench rtllm "
        "--dataset <DS> --run <RUN>\n"
        "## Sequence/plan status\nroadmap: nothing intentionally skipped.\n")


# ── the three programs still exist where the wiring points ──────────────────
@pytest.mark.parametrize("prog", [_LINT, _CWD_GUARD, _CATALOG_VALIDATE])
def test_wired_program_exists(prog: Path):
    assert prog.is_file(), f"wiring points at a program that is not there: {prog}"


# ── channel: CI repo-hygiene lane ───────────────────────────────────────────
def test_hygiene_lane_exists():
    assert _HYGIENE.is_file(), (
        "tools/ci/repo_hygiene_gates.sh is the channel two of these three are "
        "wired through; it must exist for that wiring to mean anything")


def test_ip_catalog_validate_is_wired_into_the_hygiene_lane():
    """WIRING EXISTS — ip_catalog_validate runs on every CI/merge-queue run."""
    text = _HYGIENE.read_text()
    assert "ip_catalog_validate.py" in text, (
        "ip_catalog_validate.py fell out of tools/ci/repo_hygiene_gates.sh — a "
        "malformed or non-permissively-licensed ip-catalog manifest can land "
        "again with nothing objecting")
    # It must be a BLOCKING `run` line, not the non-fatal variant.
    line = next(ln for ln in text.splitlines() if "ip_catalog_validate.py" in ln
                and ln.strip().startswith("run "))
    assert not line.strip().startswith("run_tolerating_uncheckable"), (
        "ip_catalog_validate has a real rc=1 path over tracked files; it is "
        "wired blocking on purpose")


def test_benchmark_result_md_lint_is_wired_into_the_hygiene_lane():
    """WIRING EXISTS — the published per-benchmark RESULT.md is § 6-gated.

    The linter takes ONE file, so the hygiene lane calls a population-enumeration
    wrapper. Both halves of that chain are pinned: the lane must invoke the
    wrapper, and the wrapper must invoke the (unmodified) linter.
    """
    lane = _HYGIENE.read_text()
    assert "benchmark_result_md_sections_gate.sh" in lane, (
        "the § 6 gate fell out of tools/ci/repo_hygiene_gates.sh — a "
        "§ 6-incomplete published RESULT.md can be committed again with no gate "
        "firing")
    line = next(ln for ln in lane.splitlines()
                if "benchmark_result_md_sections_gate.sh" in ln
                and ln.strip().startswith("run "))
    assert not line.strip().startswith("run_tolerating_uncheckable"), (
        "the canonical published RESULT.md set is gated blocking on purpose")

    assert _SECTIONS_GATE.is_file(), f"wrapper missing: {_SECTIONS_GATE}"
    wrapper = _SECTIONS_GATE.read_text()
    assert "benchmark_result_md_lint.py" in wrapper, (
        "the wrapper must call the real linter — it carries no checking logic "
        "of its own")
    assert "benchmark-data/evaluation/*/RESULT.md" in wrapper, (
        "the § 6 gate must name the canonical published RESULT.md population it "
        "judges; a gate that does not state its denominator can pass vacuously")
    assert "REFUSING a vacuous PASS" in wrapper, (
        "the § 6 gate must FAIL rather than pass when it finds zero canonical "
        "RESULT.md — an empty population is not a clean result")


def test_sections_gate_wrapper_is_valid_bash_and_passes_today():
    r = subprocess.run(["bash", "-n", str(_SECTIONS_GATE)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    if not (_REPO / "benchmark-data" / "evaluation").is_dir():
        pytest.skip("benchmark-data/evaluation not present in this checkout")
    r = subprocess.run(["bash", str(_SECTIONS_GATE)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    # It must SAY how much it looked at, blocking half and advisory half.
    assert "canonical published RESULT.md (BLOCKING)" in r.stdout
    assert "ADVISORY:" in r.stdout


def test_sections_gate_refuses_a_vacuous_pass_on_an_empty_population(tmp_path):
    """An empty population is a FAILURE, not a clean result (vibe-ic#447)."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "tools" / "ci").mkdir(parents=True)
    (fake_repo / "benchmark-data" / "evaluation").mkdir(parents=True)
    plug = (fake_repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs")
    plug.mkdir(parents=True)
    (plug / "benchmark_result_md_lint.py").write_text(_LINT.read_text())
    copy = fake_repo / "tools" / "ci" / _SECTIONS_GATE.name
    copy.write_text(_SECTIONS_GATE.read_text())
    r = subprocess.run(["bash", str(copy)], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REFUSING a vacuous PASS" in (r.stdout + r.stderr)


def test_hygiene_lane_is_valid_bash():
    r = subprocess.run(["bash", "-n", str(_HYGIENE)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ── channel: benchmark_dispatch --score subprocess call ─────────────────────
def test_dispatch_score_is_wired_to_the_result_md_lint():
    """WIRING EXISTS — the benchmark front door enforces § 6 sections."""
    text = _DISPATCH.read_text()
    assert "benchmark_result_md_lint.py" in text, (
        "benchmark_dispatch.py no longer invokes benchmark_result_md_lint — the "
        "§ 6 'fails the run' doctrine is a claim with nothing behind it again")
    assert "_lint_result_md" in text
    assert "cmd_score" in text


def test_dispatch_lint_helper_fails_a_section_incomplete_result_md(tmp_path):
    """FAILs on a bad input THROUGH the new channel (rc 1)."""
    sys.path.insert(0, str(_PROGRAMS))
    import benchmark_dispatch as bd  # noqa: E402

    (tmp_path / "RESULT.md").write_text("# stub\n\nnothing auditable here\n")
    assert bd._lint_result_md(tmp_path) == 1


def test_dispatch_lint_helper_passes_a_complete_result_md(tmp_path):
    sys.path.insert(0, str(_PROGRAMS))
    import benchmark_dispatch as bd  # noqa: E402

    (tmp_path / "RESULT.md").write_text(_complete_result_md())
    assert bd._lint_result_md(tmp_path) == 0


def test_dispatch_lint_helper_does_not_fail_an_unwritten_result_md(tmp_path):
    """An ABSENT RESULT.md is a NOTICE, not a FAIL.

    On a first score the agent writes RESULT.md AFTER the scorer; failing on
    absence would fail every honest first run. This pins that deliberate choice
    so nobody "tightens" it into a gate that always fires.
    """
    sys.path.insert(0, str(_PROGRAMS))
    import benchmark_dispatch as bd  # noqa: E402

    assert bd._lint_result_md(tmp_path) == 0


def test_cmd_score_exits_nonzero_on_a_section_incomplete_result_md(tmp_path, monkeypatch):
    """INTEGRATION — the real cmd_score body, not just the helper.

    Every front-door guard and the scorer itself are stubbed to rc 0, so the ONLY
    thing that can make this exit non-zero is the newly wired § 6 lint. Before the
    wiring, a run dir carrying a stub RESULT.md scored and exited 0.
    """
    sys.path.insert(0, str(_PROGRAMS))
    import benchmark_dispatch as bd  # noqa: E402

    run_dir = tmp_path / "run"
    (run_dir / "samples").mkdir(parents=True)
    (run_dir / "RESULT.md").write_text("# stub\n\nno auditable sections\n")
    ds = tmp_path / "ds"
    ds.mkdir()

    real_call = subprocess.call

    def fake_call(argv, *a, **kw):
        # Let the § 6 linter really run; stub every other subprocess (the entry
        # guard, clean-room guard, emit-attestation guard, and the scorer).
        if any("benchmark_result_md_lint" in str(x) for x in argv):
            return real_call(argv, *a, **kw)
        return 0

    monkeypatch.setattr(bd.subprocess, "call", fake_call)
    with pytest.raises(SystemExit) as exc:
        bd.cmd_score("rtllm", str(run_dir), str(ds))
    assert exc.value.code == 1, (
        "cmd_score must exit non-zero when <RUNDIR>/RESULT.md is missing a § 6 "
        "section — that is the whole point of the wiring")


def test_cmd_score_exits_zero_on_a_complete_result_md(tmp_path, monkeypatch):
    """The same path with a § 6-complete deliverable must still exit 0."""
    sys.path.insert(0, str(_PROGRAMS))
    import benchmark_dispatch as bd  # noqa: E402

    run_dir = tmp_path / "run"
    (run_dir / "samples").mkdir(parents=True)
    (run_dir / "RESULT.md").write_text(_complete_result_md())
    ds = tmp_path / "ds"
    ds.mkdir()

    real_call = subprocess.call

    def fake_call(argv, *a, **kw):
        if any("benchmark_result_md_lint" in str(x) for x in argv):
            return real_call(argv, *a, **kw)
        return 0

    monkeypatch.setattr(bd.subprocess, "call", fake_call)
    with pytest.raises(SystemExit) as exc:
        bd.cmd_score("rtllm", str(run_dir), str(ds))
    assert exc.value.code == 0


# ── channel: score_iverilog_tb pre-flight subprocess call ───────────────────
def test_scorer_is_wired_to_the_cwd_guard():
    """WIRING EXISTS — the § 3 pre-flight runs inside the scorer."""
    text = _SCORER.read_text()
    assert "benchmark_score_cwd_guard.py" in text
    assert "_cwd_guard_preflight" in text, (
        "the § 3 cwd-guard pre-flight fell out of score_iverilog_tb.py")
    assert '"cwd_guard": cwd_guard' in text, (
        "the pre-flight report must travel with the score in pass_at_1.json so a "
        "reader can tell 'checked, clean' from 'never checked'")


def _load_scorer():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_score_iverilog_tb_wire", _SCORER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cwd_guard_preflight_finds_an_unresolvable_tb_datafile(tmp_path):
    """FAILs on a bad input THROUGH the new channel — as a RECORDED finding."""
    mod = _load_scorer()
    ds = tmp_path / "ds"
    (ds / "good").mkdir(parents=True)
    (ds / "good" / "testbench.v").write_text(
        'module tb; reg [7:0] m[0:1]; initial $readmemh("reference.txt", m); endmodule\n')
    (ds / "good" / "reference.txt").write_text("00\n")
    (ds / "bad").mkdir(parents=True)
    (ds / "bad" / "testbench.v").write_text(
        'module tb; reg [7:0] m[0:1]; initial $readmemh("golden_vectors.txt", m); endmodule\n')

    rep = mod._cwd_guard_preflight(["good", "bad"], ds,
                                   {"tb_filename": "testbench.v"},
                                   {"cwd_design_dir": True})
    assert rep["examined"] == 2
    assert [f["design"] for f in rep["findings"]] == ["bad"]
    assert "golden_vectors.txt" in rep["findings"][0]["detail"]


def test_cwd_guard_preflight_is_advisory_not_a_gate(tmp_path):
    """SEVERITY IS PINNED — advisory, and the report says so.

    The guard's own regex matches a WRITE-mode `$fopen("out.txt","w")` and then
    demands that OUTPUT file already exist. Measured: rc 1 with
    "relative TB datafile(s) do not resolve under cwd: sim_output.txt". Wiring
    that as blocking would manufacture the exact false-fail class the guard was
    written to prevent, so the pre-flight records and never changes a verdict.
    """
    mod = _load_scorer()
    ds = tmp_path / "ds"
    (ds / "writer").mkdir(parents=True)
    (ds / "writer" / "testbench.v").write_text(
        'module tb; integer fd; initial fd = $fopen("sim_output.txt", "w"); endmodule\n')

    rep = mod._cwd_guard_preflight(["writer"], ds,
                                   {"tb_filename": "testbench.v"},
                                   {"cwd_design_dir": True})
    assert rep["enforced"] is False
    assert rep["severity"] == "advisory"
    # The known false positive is REAL and is exactly why this must stay advisory.
    assert rep["findings"], (
        "if the guard stopped flagging a write-mode $fopen it has been fixed — "
        "re-evaluate whether the pre-flight can now be promoted to blocking")


def test_cwd_guard_preflight_discloses_when_it_does_not_apply(tmp_path):
    """A pre-flight that cannot check must not report a clean result."""
    mod = _load_scorer()
    ds = tmp_path / "ds"
    (ds / "d").mkdir(parents=True)
    rep = mod._cwd_guard_preflight(["d"], ds, {"tb_filename": "testbench.v"},
                                   {"cwd_design_dir": False})
    assert rep["reason"] == "cwd_design_dir_disabled_for_this_benchmark"
    assert rep["examined"] == 0


# ── the wired checks still discriminate (rc 1 on a bad input) ───────────────
def test_ip_catalog_validate_fails_a_malformed_manifest(tmp_path):
    """Through the wired command shape: a bad manifest makes the gate rc 1."""
    cat = tmp_path / "ip-catalog"
    (cat / "peripheral" / "badip").mkdir(parents=True)
    (cat / "peripheral" / "badip" / "manifest.yaml").write_text(
        "ip_name: badip\n"
        "ip_version: \"0.1\"\n"
        "ip_class: peripheral\n"
        "license: NotAWhitelistedLicense-1.0\n"
        "canonical_url: not-a-url\n"
        "description: deliberately malformed\n"
        "implements:\n  - nothing\n"
        "matches_when:\n  - mentions: badip\n"
        "interface:\n  ports:\n    - name: clk\n"
        "rtl_files:\n  - rtl/badip.v\n")
    r = subprocess.run([sys.executable, str(_CATALOG_VALIDATE),
                        "--catalog-dir", str(cat)],
                       capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL: 1" in r.stdout


def test_ip_catalog_validate_passes_the_real_tracked_catalog():
    """Wiring it blocking costs nothing today — measured 18/18 PASS."""
    r = subprocess.run([sys.executable, str(_CATALOG_VALIDATE)],
                       capture_output=True, text=True, cwd=str(_PLUGIN))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL: 0" in r.stdout


def test_benchmark_result_md_lint_fails_a_stub(tmp_path):
    p = tmp_path / "RESULT.md"
    p.write_text("# stub\n")
    r = subprocess.run([sys.executable, str(_LINT), str(p)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "missing mandatory" in r.stderr


def test_benchmark_result_md_lint_passes_the_published_canonical_results():
    """The blocking half of the hygiene gate is GREEN at wiring time.

    If this goes red, a canonical published RESULT.md lost a § 6 section — fix
    the RESULT.md, never the gate.
    """
    canon = sorted((_REPO / "benchmark-data" / "evaluation").glob("*/RESULT.md"))
    if not canon:
        pytest.skip("benchmark-data/evaluation not present in this checkout")
    bad = [str(p) for p in canon
           if subprocess.run([sys.executable, str(_LINT), str(p)],
                             capture_output=True).returncode != 0]
    assert bad == [], f"§ 6-incomplete canonical published RESULT.md: {bad}"
