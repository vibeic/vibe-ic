"""tapeout_docs_gen must state a measurement or say NOT_MEASURED — never a default.

The documents this program writes are the ones a reader believes. So the tests
here are about the two ways a generated document lies:

  * it fills a gap with a plausible number, and the gap becomes invisible;
  * it assembles one document out of two different runs, and every figure is
    individually true while the document as a whole is false.

Both are measured failures, not hypotheticals — on 2026-08-20 the 0p5x0p5 die
that passed precheck and the 1x1 die that carries the full metrics were both
"spm on gf180mcuD", and only comparing their bounding boxes caught it.
"""
import fnmatch
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from _hostpaths import repo_path

PROG = Path(__file__).resolve().parents[1] / "tapeout_docs_gen.py"

CLEAN = {
    "design__die__bbox": "0.0 0.0 3932.0 5122.0",
    "route__drc_errors": 0, "magic__drc_error__count": 0,
    "klayout__drc_error__count": 0, "klayout__density_error__count": 0,
    "antenna__violating__nets": 0, "antenna__violating__pins": 0,
    "design__lvs_error__count": 0, "design__lvs_unmatched_device__count": 0,
    "design__lvs_unmatched_net__count": 0, "design__lvs_unmatched_pin__count": 0,
    "design__xor_difference__count": 0,
    "timing__setup__ws": 0.5, "timing__setup__tns": 0.0,
    "timing__hold__ws": 0.3, "timing__hold__tns": 0,
    "design__max_slew_violation__count": 0, "design__max_cap_violation__count": 0,
}


def run(tmp, metrics, extra=()):
    mp = tmp / "m.json"
    mp.write_text(json.dumps(metrics), encoding="utf-8")
    out = tmp / "out"
    r = subprocess.run(
        [sys.executable, str(PROG), "--metrics", str(mp), "--design", "d",
         "--pdk", "pdk", "--out-dir", str(out), *extra],
        capture_output=True, text=True)
    return r, out


def test_a_clean_run_is_signed_off(tmp_path):
    r, out = run(tmp_path, CLEAN)
    assert r.returncode == 0, r.stderr
    html = (out / "SIGNOFF_d_pdk.html").read_text(encoding="utf-8")
    assert "MEASURED CHECKS PASS" in html and "PARTIAL" not in html
    assert "TAPE-OUT SIGN-OFF REPORT" not in html
    assert "not a tape-out approval" in html
    assert "manufactured part" in html


def test_a_timing_violation_blocks_generation_entirely(tmp_path):
    """Owner, 2026-08-20: 一定要全部 pass 才會開始生成.

    A release document for a failing run is worse than none -- it is a FILE, and
    files outlive the run they came from. So the program writes NOTHING and names
    what is not clean. The ABSENCE of the documents is the signal.
    """
    m = dict(CLEAN, **{"timing__setup__ws": -1.53})
    r, out = run(tmp_path, m)
    assert r.returncode != 0, "a failing run must not silently produce documents"
    assert not (out / "SIGNOFF_d_pdk.html").exists(), "no file may be written"
    assert "NOT RELEASABLE" in r.stderr
    assert "timing__setup__ws" in r.stderr, "it must name WHICH property"


def test_a_failing_run_can_be_drafted_but_the_file_says_so(tmp_path):
    """The escape hatch must not produce a document indistinguishable from a real one."""
    m = dict(CLEAN, **{"timing__setup__ws": -1.53})
    r, out = run(tmp_path, m, extra=("--allow-incomplete",))
    assert r.returncode == 0
    html = (out / "SIGNOFF_d_pdk.html").read_text(encoding="utf-8")
    assert "DRAFT" in html, "a draft must be stamped in the FILE, not only on the console"
    assert "不可發布" in html


def test_a_failing_drc_blocks_generation(tmp_path):
    m = dict(CLEAN, **{"magic__drc_error__count": 7})
    r, out = run(tmp_path, m)
    assert r.returncode != 0
    assert not out.exists() or not list(out.glob("*.html"))


def test_a_missing_metric_blocks_generation_too(tmp_path):
    """"We did not look" and "we looked and it was fine" must not produce the same file."""
    m = {k: v for k, v in CLEAN.items() if k != "design__lvs_error__count"}
    r, out = run(tmp_path, m)
    assert r.returncode != 0, "an unmeasured property is not a passing one"
    assert "NOT_MEASURED" in r.stderr
    assert "design__lvs_error__count" in r.stderr


def test_an_unreadable_metrics_file_is_refused(tmp_path):
    mp = tmp_path / "m.json"
    mp.write_text("{not json", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(PROG), "--metrics", str(mp), "--design", "d",
         "--pdk", "pdk", "--out-dir", str(tmp_path / "o")],
        capture_output=True, text=True)
    assert r.returncode != 0, "a document must not be written from an unreadable run"


def test_two_runs_in_one_project_are_refused(tmp_path):
    """Ambiguity is refused rather than resolved by picking one."""
    proj = tmp_path / "proj"
    for slot in ("a", "b"):
        d = proj / slot / "final"
        d.mkdir(parents=True)
        (d / "metrics.json").write_text(json.dumps(CLEAN), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(PROG), "--project", str(proj), "--design", "d",
         "--pdk", "pdk", "--out-dir", str(tmp_path / "o")],
        capture_output=True, text=True)
    assert r.returncode != 0
    assert "refusing to guess" in (r.stderr + r.stdout)


def test_the_scope_section_is_always_present(tmp_path):
    """Even on a clean run, what was NOT checked must be stated."""
    r, out = run(tmp_path, CLEAN)
    html = (out / "SIGNOFF_d_pdk.html").read_text(encoding="utf-8")
    assert "未簽核的部分" in html
    assert "矽上量測" in html, "silicon measurement is never covered and must say so"


# ---------------------------------------------------------------------------
# The gate clause step 37.5ic declares must be an invocation this program
# ACCEPTS, and must write the names the step declares.
#
# MEASURED on origin/main 69ce9260d, which landed both the step and this
# program: the flow declared
#
#     program_exit_zero: "tapeout_docs_gen --project . --out-dir reports/phase3/docs"
#
# and argparse refused it, because --design and --pdk were required=True:
#
#     tapeout_docs_gen.py: error: the following arguments are required: --design, --pdk
#     RC=2
#
# rc==2 is the flow's "input-missing skip" convention, so
# flow_compliance_check._check_program_exit_zero read the refusal as
# VACUOUS_PASS. The only declared invocation of this program could therefore
# never do anything but pass, on every project, forever.
# ---------------------------------------------------------------------------
FLOW_YAML = Path(__file__).resolve().parents[2] / "flow" / "phase1_phase2_phase3.yaml"


def _declared_clause() -> str:
    """The gate command the flow yaml actually declares, read live."""
    text = FLOW_YAML.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if "tapeout_docs_gen" in line and line.startswith("- program_exit_zero:"):
            return line.split(":", 1)[1].strip().strip('"')
    raise AssertionError("no tapeout_docs_gen gate clause found in the flow yaml")


def test_the_invocation_the_flow_declares_is_one_this_program_accepts(tmp_path):
    """A clause the program's own parser rejects measures nothing."""
    clause = _declared_clause()
    argv = clause.split()
    assert argv[0] == "tapeout_docs_gen"
    r = subprocess.run([sys.executable, str(PROG), *argv[1:]],
                       cwd=tmp_path, capture_output=True, text=True)
    assert "the following arguments are required" not in r.stderr, (
        "the flow declares an invocation this program refuses, and argparse's "
        f"rc=2 is the flow's VACUOUS_PASS tier:\n{r.stderr}")
    assert not (r.returncode == 2 and "error:" in r.stderr), (
        f"parser rejected the declared clause: {r.stderr}")


def test_design_and_pdk_are_read_off_the_project_not_demanded(tmp_path):
    """They are properties OF the run, which is why `--project .` can be the clause."""
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "project.json").write_text(
        json.dumps({"design": "widget", "pdk": "openpdk"}), encoding="utf-8")
    final = tmp_path / "phase3" / "final"
    final.mkdir(parents=True)
    (final / "metrics.json").write_text(json.dumps(CLEAN), encoding="utf-8")
    out = tmp_path / "reports" / "phase3" / "docs"
    r = subprocess.run(
        [sys.executable, str(PROG), "--project", str(tmp_path),
         "--out-dir", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (out / "SIGNOFF_widget_openpdk.html").is_file(), sorted(
        p.name for p in out.iterdir())
    assert (out / "BRIEF_widget_openpdk.html").is_file()


def test_an_unidentifiable_run_says_so_rather_than_guessing_a_name(tmp_path):
    """No project.json is a hole, and the hole is visible in the FILENAME."""
    final = tmp_path / "phase3" / "final"
    final.mkdir(parents=True)
    (final / "metrics.json").write_text(json.dumps(CLEAN), encoding="utf-8")
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, str(PROG), "--project", str(tmp_path),
         "--out-dir", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    names = sorted(p.name for p in out.iterdir())
    assert any("NOT_MEASURED" in n for n in names), names


def test_the_step_declares_the_names_this_program_writes(tmp_path):
    """d4/criteria_match caught these two disagreeing; keep them agreeing here."""
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "project.json").write_text(
        json.dumps({"design": "widget", "pdk": "openpdk"}), encoding="utf-8")
    final = tmp_path / "phase3" / "final"
    final.mkdir(parents=True)
    (final / "metrics.json").write_text(json.dumps(CLEAN), encoding="utf-8")
    out = tmp_path / "reports" / "phase3" / "docs"
    subprocess.run([sys.executable, str(PROG), "--project", str(tmp_path),
                    "--out-dir", str(out)], capture_output=True, text=True)
    written = {p.name for p in out.iterdir()} if out.is_dir() else set()

    text = FLOW_YAML.read_text(encoding="utf-8").splitlines()
    declared = [l.strip().lstrip("- ").strip('"') for l in text
                if "reports/phase3/docs/" in l and l.strip().startswith('- "')]
    assert declared, "step 37.5ic declares no document output any more"
    for d in declared:
        pat = d.rsplit("/", 1)[-1]
        assert any(fnmatch.fnmatch(w, pat) for w in written), (
            f"the flow declares {d!r} and this program wrote {sorted(written)} "
            f"— a declared output no producer writes can never be produced")


def test_phase3_dispatches_the_real_37_5ic_producer_and_mutation_refuses(tmp_path):
    """The runner must execute the producer; its gate declaration is not that.

    The first assertion is intentionally VALUE-based for the frozen-producer
    control: candidate tests restored over the old runner observe zero
    executable references, rather than failing because a new symbol is absent.
    The second half changes one measured property and proves the dispatched
    producer refuses to publish release HTML for a non-releasable run.
    """
    runner_path = repo_path(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "phase3_one_shot_runner.py")
    runner_text = runner_path.read_text(encoding="utf-8")
    executable_refs = runner_text.count('PROGRAMS_DIR / "tapeout_docs_gen.py"')
    assert executable_refs == 1, (
        f"observed executable tapeout_docs_gen references={executable_refs}; "
        "the YAML gate is an auditor channel, not the phase-3 producer dispatch")
    from _phase3_main_dispatch import guarded_producer_line
    assert guarded_producer_line("step_tapeout_docs_gen",
                                 "tapeout_docs_gen")

    import phase3_one_shot_runner as runner

    def _project(tag, ws):
        proj = tmp_path / tag
        (proj / "phase3" / "final").mkdir(parents=True)
        (proj / "input" / "submission_template").mkdir(parents=True)
        (proj / "input" / "submission_template" / "SELF_TAPEOUT.txt").write_text(
            "self tape-out\n", encoding="utf-8")
        (proj / "input" / "project.json").write_text(
            json.dumps({"design": "widget", "pdk": "openpdk"}),
            encoding="utf-8")
        metrics = dict(CLEAN)
        metrics["timing__setup__ws"] = ws
        (proj / "phase3" / "final" / "metrics.json").write_text(
            json.dumps(metrics), encoding="utf-8")
        return proj

    clean = _project("clean-dispatch", 0.5)
    clean_result = runner.step_tapeout_docs_gen(clean)
    assert clean_result.status == "PASS", clean_result
    assert sorted(Path(p).name for p in clean_result.output_files) == [
        "BRIEF_widget_openpdk.html", "SIGNOFF_widget_openpdk.html"]

    harmed = _project("one-property-harm", -1.53)
    harmed_result = runner.step_tapeout_docs_gen(harmed)
    # R-0915-85 — the producer declined and NAMED why (producer_rc below),
    # so nothing about the docs was measured.
    assert harmed_result.status == "NOT_MEASURED", harmed_result
    assert harmed_result.extras.get("producer_rc") == 1, harmed_result
    assert not (harmed / "reports" / "phase3" / "docs").exists(), (
        "a negative setup slack published release documents")


def test_phase3_does_not_dispatch_37_5ic_on_the_ip_path(tmp_path):
    """37.5ic and 37.5ip are mutually exclusive consumer contracts."""
    import phase3_one_shot_runner as runner

    template = tmp_path / "input" / "submission_template"
    template.mkdir(parents=True)
    (template / "NO_TEMPLATE.txt").write_text("cell delivery\n", encoding="utf-8")
    result = runner.step_tapeout_docs_gen(tmp_path)
    assert result.status == "NOT_APPLICABLE", result
    assert result.output_files == [], result
    assert not (tmp_path / "reports" / "phase3" / "docs").exists()


# ---------------------------------------------------------------------------
# A run this program REFUSES to document must not be scored as a gate pass.
#
# MEASURED on origin/main 69ce9260d: `NOT RELEASABLE` exited 2, and rc==2 is the
# flow's input-missing-skip convention. Driving the flow's own evaluator over a
# project whose only defect was `timing__setup__ws: -1.53`:
#
#     ok = True
#     snippet = __VACUOUS_HINT__: tapeout_docs_gen --project . --out-dir ...
#
# The gate passed the run it had just refused to write documents for.
# ---------------------------------------------------------------------------
NOT_CLEAN = dict(CLEAN, **{"timing__setup__ws": -1.53, "timing__setup__tns": -40.0})

# rc values `flow_compliance_check` scores as a PASS tier: 0 PASS, 2 VACUOUS_PASS,
# 3 PASS_WITH_WAIVERS.
_PASS_TIER_RCS = (0, 2, 3)


def _project(tmp_path, metrics):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "input" / "project.json").write_text(
        json.dumps({"design": "widget", "pdk": "openpdk"}), encoding="utf-8")
    final = tmp_path / "phase3" / "final"
    final.mkdir(parents=True, exist_ok=True)
    (final / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return tmp_path


def test_a_run_that_is_not_releasable_exits_a_code_the_flow_scores_as_fail(tmp_path):
    proj = _project(tmp_path, NOT_CLEAN)
    r = subprocess.run(
        [sys.executable, str(PROG), "--project", str(proj),
         "--out-dir", str(proj / "reports" / "phase3" / "docs")],
        capture_output=True, text=True)
    assert "NOT RELEASABLE" in r.stderr
    assert r.returncode not in _PASS_TIER_RCS, (
        f"rc={r.returncode} is a PASS tier in this flow (0 PASS / 2 VACUOUS_PASS "
        f"/ 3 PASS_WITH_WAIVERS), so the gate reports a pass on a run this "
        f"program just refused to document")


def test_the_flows_own_evaluator_fails_the_gate_on_a_run_that_is_not_clean(tmp_path):
    """The composition, not the exit code in isolation -- this is what the gate does."""
    fcc_path = PROG.parent / "flow_compliance_check.py"
    spec = importlib.util.spec_from_file_location("_fcc_docs_probe", fcc_path)
    fcc = importlib.util.module_from_spec(spec)
    sys.modules["_fcc_docs_probe"] = fcc
    spec.loader.exec_module(fcc)

    proj = _project(tmp_path, NOT_CLEAN)
    ok, out = fcc._check_program_exit_zero(
        proj, "tapeout_docs_gen --project . --out-dir reports/phase3/docs")
    assert not ok, (
        f"the flow scored a NOT-RELEASABLE run as a gate pass: {out[:160]!r}")

    clean = _project(tmp_path / "clean", CLEAN)
    ok_clean, out_clean = fcc._check_program_exit_zero(
        clean, "tapeout_docs_gen --project . --out-dir reports/phase3/docs")
    assert ok_clean, (
        f"a clean run must still PASS, or this gate is red for everyone: "
        f"{out_clean[:200]!r}")


def test_canonical_gate_preserves_producer_citations_across_clock_change(tmp_path, monkeypatch):
    import datetime
    import shlex
    import _cited_artefacts as citations
    import flow_compliance_check as fcc
    import phase3_one_shot_runner as runner

    spec = importlib.util.spec_from_file_location('tdg_readonly_source_control', PROG)
    tdg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tdg)
    clock = [datetime.datetime(2026, 1, 2, 3, 4, tzinfo=datetime.timezone.utc)]

    class Clock(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz)

    monkeypatch.setattr(tdg, 'datetime', Clock)

    def invoke(argv):
        monkeypatch.setattr(sys, 'argv', [str(PROG), *argv])
        try:
            tdg.main()
        except SystemExit as exc:
            return exc.code if type(exc.code) is int else 1
        return 0

    project = _project(tmp_path / 'run', CLEAN)
    out = project / 'reports/phase3/docs'
    producer = ['--project', str(project), '--out-dir', str(out)]
    assert invoke(producer) == 0
    paths = sorted(out.glob('*.html'))
    assert len(paths) == 2
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    runner._publish_in_progress_steps(project, [runner.StepResult(
        'tapeout_docs_gen', 'PASS', 0.0, 'source fixture: actual document producer rc0',
        [str(p) for p in paths])])
    record_path = project / citations.REPORT_REL
    record = json.loads(record_path.read_text())
    record_before = record_path.read_bytes()
    assert citations.check(project, record)[0] == 'PASS'
    clock[0] += datetime.timedelta(hours=1)
    monkeypatch.chdir(project)
    gate_argv = shlex.split(_declared_clause())[1:]
    rc = invoke(gate_argv)
    assert rc == 0
    citation_status = citations.check(project, record)[0]
    assert citation_status == 'PASS', 'canonical release gate changed producer-owned HTML bytes'
    assert '--check-only' in gate_argv
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths} == before
    assert record_path.read_bytes() == record_before
    metrics = project / 'phase3/final/metrics.json'
    for damage in ('negative_setup', 'missing_tns', 'draft_flag'):
        broken = dict(CLEAN)
        if damage in ('negative_setup', 'draft_flag'):
            broken['timing__setup__ws'] = -1.53
        else:
            broken.pop('timing__hold__tns')
        metrics.write_text(json.dumps(broken))
        rc = invoke(gate_argv + (['--allow-incomplete'] if damage == 'draft_flag' else []))
        assert rc == 1, damage
        assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths} == before
        print('READONLY_RELEASE_REFUSED', damage)
    metrics.write_text(json.dumps(CLEAN))
    signoff = next(p for p in paths if p.name.startswith('SIGNOFF_'))
    signoff.write_bytes(before[signoff.name][0] + b'edited document')
    status, rows = citations.check(project, record)
    assert status == 'NOT_MEASURED'
    assert any(r['reason'] == 'STALE_CITATION' for r in rows)
    print('READONLY_RELEASE_REFUSED', 'html_tamper_by_original_citation_check')
    signoff.unlink()
    assert invoke(gate_argv) == 0
    assert citations.check(project, record)[0] == 'NOT_MEASURED'
    satisfied, *_ = fcc._resolve_required_output(
        project, '37.5ic', 'reports/phase3/docs/SIGNOFF_*.html', {})
    assert satisfied is False
    assert not signoff.exists()
    assert record_path.read_bytes() == record_before
    print('READONLY_RELEASE_REFUSED', 'missing_html_by_original_required_output')
