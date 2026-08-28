#!/usr/bin/env python3
"""#490 — `drc_report_check.py` discarded its argv, so the DRC sign-off audit
trail was never written on any run.

EVERY test here DRIVES THE PROGRAM, and the ones that matter most check that a
FILE REALLY APPEARS AT THE DECLARED PATH. A test that asserts on source text
passes while the code it names raises at runtime; a test that asserts a wrapper
"forwards --json" without looking on disk passes while the forwarding writes
nothing. The end-to-end tests drive the REAL gate runner
(`flow_compliance_check._check_program_exit_zero`), because the property that
matters is not "the wrapper returns N" but "the DRC gate does not go green with
no audit behind it".

MEASURED on v1.7.66 before anything was changed, on the fixtures below:

    drc_report_check proj --mode drc --json out/drc_signoff.json
        -> rc 0 (gate GREEN) and out/drc_signoff.json DOES NOT EXIST
    drc_report_check proj --mode=power --json out.json
        -> the caller's mode was silently DISCARDED, rc 0, nothing written
    drc_report_check --json out.json proj
        -> argparse rejected the line and exited 2, which
           `_check_program_exit_zero` credits as a VACUOUS_PASS -> gate GREEN
    drc_report_check --help
        -> argparse's help action exited 0 -> gate GREEN, nothing audited

Corpus: `reports/phase3/drc_signoff.json` appears 0 times and
`reports/phase3/drc_router.json` 0 times across the 119 tracked project
snapshots under `benchmark-data/`.

chip-AGNOSTIC: every fixture below is generic tool-shaped output — no vendor,
SKU, PDK or IC literal anywhere.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
PROG = PROGRAMS / "drc_report_check.py"
FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PROGRAMS))

import _report_check_argv as argv_helper  # noqa: E402
import drc_report_check as wrapper  # noqa: E402
import eda_report_audit as era  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

# Padding that clears the drc byte floor (MIN_REPORT_BYTES['drc'] == 2048)
# without carrying any design-specific content.
_PAD = "".join(f"  rule check {i:04d} "
               f"{'.' * 40} 0 items\n" for i in range(48))

#: An AUTHENTIC, CLEAN DRC report: a tool signature (`klayout`), a determinable
#: real violation count of zero, and enough body to clear the byte floor.
_CLEAN_DRC = (
    "KLayout DRC sign-off report\n"
    "Deck: sign-off runset\n"
    "total violations: 0\n"
    "DRC clean\n"
    "category: spacing count: 0\n"
    "category: width count: 0\n"
    "category: density count: 0\n"
    "category: antenna count: 0\n"
    "category: via count: 0\n"
    "category: enclosure count: 0\n" + _PAD
)

#: A DIRTY but equally authentic report — the audit must still be WRITTEN.
_DIRTY_DRC = _CLEAN_DRC.replace("total violations: 0", "total violations: 17")

#: A clean POWER report. On a project with this and NO drc report, a wrapper
#: that let the caller redirect the mode would certify power under the DRC
#: gate's name.
_POWER_RPT = (
    "OpenROAD Power Report\n"
    "Group: sequential    Internal Power: 0.12 mW\n"
    "Group: combinational Switching Power: 0.34 mW\n"
    "Leakage Power: 0.05 mW\n"
    "Total Power: 0.51 mW\n" + "# " + ("=" * 78 + "\n") * 40
)


def _run(args, cwd=None):
    return _pr.run([sys.executable, str(PROG)] + [str(a) for a in args],
                          capture_output=True, text=True, cwd=cwd)


def _project(tmp_path, *, drc=_CLEAN_DRC, power=False):
    d = tmp_path / "proj" / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    if drc is not None:
        (d / "drc_signoff.rpt").write_text(drc)
    if power:
        (d / "power_analysis.rpt").write_text(_POWER_RPT)
    return tmp_path / "proj"


# ── THE DEFECT: `--json` never produced a file ────────────────────────────

def test_declared_json_path_really_appears_on_disk(tmp_path):
    """THE headline. The Step-31 declaration, verbatim, must leave the audit at
    the path it names. On v1.7.66 this file did not exist afterwards."""
    proj = _project(tmp_path)
    out = tmp_path / "reports" / "phase3" / "drc_signoff.json"
    r = _run([proj, "--mode", "drc", "--json", out])
    assert out.is_file(), (
        f"--json named {out} and nothing was written there (rc={r.returncode})")
    doc = json.loads(out.read_text())
    assert doc["program"] == "eda_report_audit:drc"
    assert doc["passed"] is True
    assert r.returncode == 0


def test_audit_is_written_even_when_the_verdict_is_bad(tmp_path):
    """"There is no such evidence" and "the evidence says it failed" read
    completely differently to a reviewer. A FAILing gate must still leave the
    audit."""
    proj = _project(tmp_path, drc=_DIRTY_DRC)
    out = tmp_path / "out" / "drc_signoff.json"
    r = _run([proj, "--mode", "drc", "--json", out])
    assert r.returncode == 1
    assert out.is_file(), "a FAILing DRC gate wrote no audit trail"
    assert json.loads(out.read_text())["passed"] is False


def test_audit_is_written_when_there_is_no_drc_report_at_all(tmp_path):
    """104 of the 119 tracked snapshots discover zero DRC reports. That is the
    case that most needs a written verdict, and it is the one the old wrapper
    was silent about."""
    proj = _project(tmp_path, drc=None)
    out = tmp_path / "out" / "drc_signoff.json"
    r = _run([proj, "--mode", "drc", "--json", out])
    assert r.returncode == 1
    assert out.is_file()
    doc = json.loads(out.read_text())
    assert doc["passed"] is False
    assert doc["summary"]["files_found"] == 0


def test_json_equals_spelling_also_produces_the_file(tmp_path):
    proj = _project(tmp_path)
    out = tmp_path / "o" / "a.json"
    r = _run([proj, "--mode", "drc", f"--json={out}"])
    assert r.returncode == 0
    assert out.is_file()


def test_json_target_directories_are_created(tmp_path):
    """`reports/phase3/` does not exist on a fresh project; the declared path
    must still be produced."""
    proj = _project(tmp_path)
    out = tmp_path / "deep" / "nested" / "reports" / "phase3" / "drc.json"
    assert not out.parent.exists()
    _run([proj, "--mode", "drc", "--json", out])
    assert out.is_file()


# ── the mode is PINNED, in both spellings ─────────────────────────────────

@pytest.mark.parametrize("mode_args", [["--mode", "drc"], ["--mode=drc"]])
def test_both_spellings_of_the_pinned_mode_are_accepted(tmp_path, mode_args):
    proj = _project(tmp_path)
    out = tmp_path / f"o{len(mode_args)}.json"
    r = _run([proj] + mode_args + ["--json", out])
    assert r.returncode == 0
    assert json.loads(out.read_text())["program"] == "eda_report_audit:drc"


@pytest.mark.parametrize("mode_args", [
    ["--mode", "power"], ["--mode=power"],
    ["--mode", "sta"], ["--mode=lvs"],
])
def test_any_other_mode_is_refused_with_a_stated_reason(tmp_path, mode_args):
    """Not silently honoured (#489's shape) and not silently discarded (#490's
    shape). The project carries a CLEAN power report and NO drc report, so a
    wrapper that honoured `--mode power` would certify the DRC gate on power."""
    proj = _project(tmp_path, drc=None, power=True)
    out = tmp_path / "o.json"
    r = _run([proj] + mode_args + ["--json", out])
    assert r.returncode == 1, r.stderr
    assert "REFUSED" in r.stderr
    assert mode_args[-1] in r.stderr, "the refusal must name what was requested"
    doc = json.loads(out.read_text())
    assert doc["passed"] is False
    assert doc["summary"]["terminal_verdict"] == "NOT_CHECKED"
    assert doc["summary"]["pinned_mode"] == "drc"


def test_a_valueless_mode_flag_is_refused(tmp_path):
    proj = _project(tmp_path)
    r = _run([proj, "--mode"])
    assert r.returncode == 1
    assert "REFUSED" in r.stderr


def test_the_refusal_record_reaches_the_declared_json_path(tmp_path):
    """A refusal is a verdict too, and the artefact must carry it — otherwise
    the reader is back to "no evidence" for a different reason."""
    proj = _project(tmp_path)
    out = tmp_path / "r" / "drc_signoff.json"
    _run([proj, "--mode=power", "--json", out])
    assert out.is_file()
    assert json.loads(out.read_text())["passed"] is False


# ── the split is VALUE AWARE ──────────────────────────────────────────────

def test_json_before_the_project_dir_still_resolves_both(tmp_path):
    """`--json <path> <proj>`: the path is `--json`'s ARGUMENT, not the project
    dir. On v1.7.66 this reached argparse as `["--json","--mode","drc"]` and
    exited 2."""
    proj = _project(tmp_path)
    out = tmp_path / "o" / "v.json"
    r = _run(["--json", out, proj])
    assert r.returncode == 0, r.stderr
    assert out.is_file()
    doc = json.loads(out.read_text())
    assert doc["passed"] is True
    assert doc["summary"]["files_found"] >= 1


def test_double_dash_lets_a_dash_leading_project_dir_be_named(tmp_path):
    proj = _project(tmp_path)
    out = tmp_path / "o.json"
    r = _run(["--json", out, "--", proj])
    assert r.returncode == 0
    assert out.is_file()


def test_the_wrapper_uses_the_SHARED_splitter_not_a_fourth_copy(tmp_path):
    """A runtime identity check, not a source-text assertion: this module's
    splitter must BE the shared one. A per-wrapper hand-rolled splitter is
    exactly how this defect propagated across the seven-wrapper family."""
    assert wrapper.split_and_pin is argv_helper.split_and_pin
    assert wrapper.json_target is argv_helper.json_target


def test_value_taking_options_of_the_wrapped_cli_are_all_known(tmp_path):
    """ANTI-DRIFT. Derive the value-taking options from `eda_report_audit`'s
    REAL argparse parser; a new one added there without being told to the
    shared splitter would silently reintroduce the value-awareness defect."""
    import argparse
    seen = set()
    real_add = argparse.ArgumentParser.add_argument

    def spy(self, *args, **kw):
        action = real_add(self, *args, **kw)
        if getattr(action, "nargs", None) != 0 and action.option_strings:
            for opt in action.option_strings:
                if opt.startswith("--"):
                    seen.add(opt)
        return action

    argparse.ArgumentParser.add_argument = spy
    try:
        try:
            era.main(["--this-argv-is-rejected-on-purpose"])
        except SystemExit:
            pass
    finally:
        argparse.ArgumentParser.add_argument = real_add
    seen.discard("--help")
    assert seen, "the spy captured no options — the probe stopped working"
    assert seen <= set(argv_helper.VALUE_FLAGS), (
        f"eda_report_audit takes {sorted(seen - set(argv_helper.VALUE_FLAGS))} "
        f"with a value, and the shared splitter does not know it")


# ── no exit path spends a VACUOUS_PASS ────────────────────────────────────

@pytest.mark.parametrize("args", [
    ["--help"],
    ["--mode"],
    ["--mode", "power"],
    ["--mode=power"],
    ["--not-a-real-flag"],
    ["--json"],
])
def test_no_invocation_ever_exits_2(tmp_path, args):
    """rc 2 is credited by `_check_program_exit_zero` as a VACUOUS_PASS and
    returns passed=True UNCONDITIONALLY (rc 3 additionally requires a stdout
    sentinel). An invocation that certified nothing must never spend that
    code."""
    proj = _project(tmp_path)
    r = _run([proj] + args)
    assert r.returncode != 2, (
        f"{args} exited 2, which the gate runner credits as a PASS")
    assert r.returncode != 0 or "--mode" not in " ".join(args)


def test_help_certifies_nothing_and_does_not_exit_zero(tmp_path):
    proj = _project(tmp_path)
    r = _run([proj, "--help"])
    assert r.returncode == 1
    assert "NOT CHECKED" in r.stderr


def test_an_unwritable_json_target_is_reported_not_swallowed(tmp_path):
    """`--json` naming an existing DIRECTORY. The run must say the audit was
    not written and must not exit 0."""
    proj = _project(tmp_path)
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    r = _run([proj, "--mode", "drc", "--json", blocked])
    assert r.returncode == 1
    assert "NOT CHECKED" in r.stderr or "NO AUDIT WRITTEN" in r.stderr


# ── the PASS discloses its denominator ────────────────────────────────────

def test_pass_discloses_how_many_files_it_examined(tmp_path):
    proj = _project(tmp_path)
    r = _run([proj, "--mode", "drc", "--json", tmp_path / "o.json"])
    assert r.returncode == 0
    m = re.search(r"files_found=(\d+)", r.stderr)
    assert m, f"a PASS disclosed no denominator: {r.stderr!r}"
    assert int(m.group(1)) >= 1
    assert "determined_files=" in r.stderr
    assert "real_violation_total=" in r.stderr


def test_stdout_is_pure_audit_json_on_pass_fail_and_refusal(tmp_path):
    """Disclosures go to stderr; stdout stays machine-parseable, because
    `_gate_detail` and sibling tests do `json.loads(stdout)`."""
    proj = _project(tmp_path)
    for args in (["--mode", "drc"], ["--mode=power"]):
        r = _run([proj] + args)
        json.loads(r.stdout)
    dirty = _project(tmp_path / "d", drc=_DIRTY_DRC)
    json.loads(_run([dirty, "--mode", "drc"]).stdout)


def test_a_denominatorless_pass_is_refused(tmp_path):
    """TRIPWIRE. `_check_drc` cannot currently return passed=True with
    files_found==0, so the measured blast radius over the 119 tracked
    snapshots is 0. Four sibling modes DO have a `_waived_for_pdk` path that
    sets passed=True with no files_found; this pins that if drc ever grows
    one, the PASS is refused rather than credited silently."""
    def fake_audit(argv):
        print(json.dumps({"program": "eda_report_audit:drc", "passed": True,
                          "findings": [],
                          "summary": {"waived": "tool unavailable"}}))
        return 0

    rc = wrapper.run([str(tmp_path)], _audit=fake_audit)
    assert rc == 1


def test_the_wrapper_re_emits_an_audit_eda_report_audit_left_absent(tmp_path):
    """The audit is ALWAYS emitted when `--json` is declared."""
    def fake_audit(argv):
        print(json.dumps({"program": "eda_report_audit:drc", "passed": True,
                          "findings": [], "summary": {"files_found": 3}}))
        return 0                              # writes NO file

    out = tmp_path / "o" / "re.json"
    rc = wrapper.run([str(tmp_path), "--json", str(out)], _audit=fake_audit)
    assert rc == 0
    assert out.is_file(), "the wrapper did not re-emit an absent audit"
    assert json.loads(out.read_text())["passed"] is True


# ── the property that actually matters: the real GATE ─────────────────────

def _flow_declared_drc_commands():
    """Every `drc_report_check ...` gate command the flow actually declares."""
    text = FLOW.read_text(errors="replace")
    return sorted(set(re.findall(
        r"program_exit_zero:\s*\"(drc_report_check [^\"]+)\"", text)))


def test_the_flow_declares_drc_report_check_with_a_json_audit():
    cmds = _flow_declared_drc_commands()
    assert cmds, "the flow no longer declares drc_report_check"
    for c in cmds:
        assert "--json" in c, c


#: Suffixes `eda_report_audit` discovers drc reports by (`*drc*.rpt/log/txt`),
#: used to tell an `--under` scope that names a FILE from one that names a
#: DIRECTORY. `_in_scope` accepts both: it keeps a path whose resolved form is
#: relative to the scope root, and a file is relative to itself.
_REPORT_SUFFIXES = (".rpt", ".log", ".txt")


def _under_scopes(cmd: str):
    """The `--under` scopes a flow-declared command restricts discovery to."""
    toks = cmd.split()
    return [toks[i + 1] for i, t in enumerate(toks)
            if t == "--under" and i + 1 < len(toks)]


#: An AUTHENTIC, CLEAN SIGN-OFF DRC report: a KLayout report database that
#: names the deck it ran. `_CLEAN_DRC` above is a plain-text body — fine for the
#: ROUTER gate (step 21), where the router is the right producer, and refused by
#: the step-31 `--signoff` scope, which requires a rule deck applied to a
#: layout. The two fixtures exist because the two steps ask different questions
#: of the same program.
_CLEAN_SIGNOFF_RDB = (
    "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
    "<report-database>\n"
    "  <description>DRC runset</description>\n"
    "  <generator>drc: script='/pdk/tech/klayout/drc/deck.lydrc'</generator>\n"
    "  <top-cell>chip_top</top-cell>\n"
    "  <categories>\n"
    + "".join(f"    <category><name>'m{2 + i % 4}.{i}'</name><description>"
              f"metal spacing width density antenna via enclosure rule {i}"
              f"</description></category>\n" for i in range(24)) +
    "  </categories>\n"
    "  <items>\n  </items>\n"
    "</report-database>\n"
)


def _plant_signoff_evidence(proj: Path):
    """What a step-31 `--signoff` invocation legitimately needs on disk.

    Not a relaxation of the gate: a real run reaching step 31 HAS streamed a
    layout, and the fixture has to carry what a real run carries or it is
    testing a project that could not exist.
    """
    gds = proj / "phase3" / "stage3" / "pnr"
    gds.mkdir(parents=True, exist_ok=True)
    (gds / "chip_top.gds").write_bytes(b"\x00\x06\x00\x02\x00\x07")


def _plant_in_scope(proj: Path, cmd: str, body: str = None):
    """Put an authentic router-DRC report inside each `--under` scope of `cmd`.

    An invocation that SCOPES its discovery can only be exercised by a fixture
    that puts the evidence where that scope looks. Step 21 declares
    `--under phase3/stage3/pnr --under reports/phase3/drc_router.rpt`
    precisely so that Step 31's `reports/phase3/drc_signoff.rpt` — the only
    report `_project` builds — CANNOT carry it, so on that fixture the audit
    correctly reported `files_found: 0`, `SCOPE_NOT_FOUND` and `passed: false`.
    That is the scoping working, not a defect.

    The evidence is derived from the command's own `--under` tokens rather
    than hardcoded, so a new scoped declaration in the flow is exercised the
    same way instead of silently reddening. Returns the scopes it planted, so
    a caller can assert it was not a no-op.

    The BODY is chosen from the command's own `--signoff` token, for the same
    reason the scopes are: the sign-off scope demands a rule-deck producer and
    the router scope does not, so a single hardcoded body would test one of the
    two declarations against the wrong premise.
    """
    signoff = "--signoff" in cmd.split()
    if body is None:
        body = _CLEAN_SIGNOFF_RDB if signoff else _CLEAN_DRC
    for rel in _under_scopes(cmd):
        target = proj / rel
        if target.suffix in _REPORT_SUFFIXES:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / "routed.drc.rpt").write_text(body)
    if signoff:
        _plant_signoff_evidence(proj)
    return _under_scopes(cmd)


@pytest.mark.parametrize("cmd", _flow_declared_drc_commands())
def test_every_flow_declared_invocation_produces_the_file_it_names(tmp_path,
                                                                   cmd):
    """Driven through the REAL gate runner, with the flow's own command string.
    THE regression guard for #490: on v1.7.66 both of these exited 0 and left
    the path they name empty.

    The fixture plants clean evidence inside whatever `--under` scope the
    command declares (none, for the project-wide Step-31 form). Without that,
    the SCOPED Step-21 declaration could only ever produce `passed: false` —
    not because `--json` was dropped, but because its scope deliberately
    excludes the Step-31 report `_project` writes. Relaxing this assertion to
    accept `passed: false` was the alternative, and it would have cost the
    test its ability to tell "the audit landed with a clean verdict" from "a
    file of some kind appeared".
    """
    import flow_compliance_check as fcc
    proj = _project(tmp_path)
    _plant_in_scope(proj, cmd)
    declared = cmd.split("--json", 1)[1].strip()
    passed, _snippet = fcc._check_program_exit_zero(proj, cmd)
    assert (proj / declared).is_file(), (
        f"the flow declares `--json {declared}` and no file appeared there")
    doc = json.loads((proj / declared).read_text())
    # Disclose the denominator: a PASS reached over zero discovered reports
    # would be the vacuous verdict this whole family exists to prevent.
    assert doc["summary"]["files_found"] >= 1, doc
    assert doc["passed"] is True
    assert passed is True


def _scopes_exclude_the_fixture_report(cmd: str) -> bool:
    """True when `_project`'s only report lies OUTSIDE this command's scopes.

    vibe-ic#584 added a scoped DRC gate at step 31, whose declared artefact IS
    `reports/phase3/drc_signoff.rpt` — the one file `_project` builds. For that
    command the fixture is IN scope by definition, so the out-of-scope premise
    below cannot hold and the case is not applicable rather than failing.

    Derived from the command's own `--under` tokens, not from a step id, so a
    future scoped gate is classified by what it actually scopes to.
    """
    return not any(_FIXTURE_REPORT == u or _FIXTURE_REPORT.startswith(u.rstrip("/") + "/")
                   for u in _under_scopes(cmd))


#: The single report `_project` writes. Named once so the two helpers that
#: reason about it cannot drift apart.
_FIXTURE_REPORT = "reports/phase3/drc_signoff.rpt"


@pytest.mark.parametrize("cmd", [c for c in _flow_declared_drc_commands()
                                 if _under_scopes(c)
                                 and _scopes_exclude_the_fixture_report(c)])
def test_a_scoped_invocation_is_not_carried_by_an_out_of_scope_report(tmp_path,
                                                                      cmd):
    """The other direction, and the reason the fixture above had to change: a
    scoped declaration must NOT go green off a report outside its scope.

    `_project` writes `reports/phase3/drc_signoff.rpt` — STEP 31's KLayout
    sign-off DRC. Step 21's gate asks about the ROUTER's DRC. Before `--under`
    existed, step 31's report carried step 21's gate (measured on the real run
    cited at flow yaml:1683: files_found=5, verdict reached over step 31's
    report). With nothing planted in scope, the gate must FAIL.

    This is what keeps the fixture change above honest: it proves the planted
    evidence is what produces the PASS, not the pre-existing report.
    """
    import flow_compliance_check as fcc
    proj = _project(tmp_path)          # step 31's report only; nothing planted
    passed, _snippet = fcc._check_program_exit_zero(proj, cmd)
    declared = cmd.split("--json", 1)[1].strip()
    doc = json.loads((proj / declared).read_text())
    assert doc["summary"]["files_found"] == 0, (
        f"an out-of-scope report was discovered by {cmd}: {doc['summary']}")
    assert doc["passed"] is False
    assert passed is False


@pytest.mark.parametrize("cmd", [c for c in _flow_declared_drc_commands()
                                 if _under_scopes(c)])
def test_a_scoped_invocation_still_fails_on_dirty_in_scope_evidence(tmp_path,
                                                                    cmd):
    """And the fixture is not a rubber stamp: the same planting with a DIRTY
    report must FAIL. Otherwise `_plant_in_scope` would be manufacturing a
    PASS rather than supplying the evidence the scope asks for."""
    import flow_compliance_check as fcc
    proj = _project(tmp_path)
    _plant_in_scope(proj, cmd, body=_DIRTY_DRC)
    declared = cmd.split("--json", 1)[1].strip()
    passed, _snippet = fcc._check_program_exit_zero(proj, cmd)
    doc = json.loads((proj / declared).read_text())
    assert doc["summary"]["files_found"] >= 1, doc
    assert doc["passed"] is False
    assert passed is False


@pytest.mark.parametrize("suffix", [
    "--mode=power --json reports/phase3/drc_signoff.json",
    "--mode power --json reports/phase3/drc_signoff.json",
    "--help",
])
def test_the_gate_does_not_go_green_on_a_spoofed_invocation(tmp_path, suffix):
    """On v1.7.66 all three returned passed=True against a project with NO drc
    report at all (the `--json ... .` ordering additionally exited 2, which the
    runner credits unconditionally)."""
    import flow_compliance_check as fcc
    proj = _project(tmp_path, drc=None, power=True)
    passed, _snippet = fcc._check_program_exit_zero(
        proj, f"drc_report_check . {suffix}")
    assert passed is False, suffix


def test_the_vacuous_pass_credit_this_refusal_avoids_is_real(tmp_path,
                                                             monkeypatch):
    """DRIVES the runner with a probe that exits 2, proving the credit is
    unconditional — the reason this wrapper's refusals exit 1.

    The probe lives in a tmp dir and `PROGRAMS_DIR` is redirected there, so no
    file is ever created inside the real `programs/` tree.
    """
    import flow_compliance_check as fcc
    proj = tmp_path / "p"
    (proj / "reports").mkdir(parents=True)
    probe_dir = tmp_path / "probe_programs"
    probe_dir.mkdir()
    (probe_dir / "rc2_probe.py").write_text("import sys\nsys.exit(2)\n")
    monkeypatch.setattr(fcc, "PROGRAMS_DIR", probe_dir)
    passed, snippet = fcc._check_program_exit_zero(proj, "rc2_probe .")
    assert passed is True, (
        "rc 2 is no longer credited as a vacuous PASS — the refusal rc "
        "rationale in drc_report_check.py's docstring must be re-derived")
    assert "VACUOUS" in snippet.upper()

    # ...and this wrapper's own refusal does not spend that code.
    assert _run([str(_project(tmp_path / "q")), "--mode=power"]).returncode == 1


# ── the ENFORCEMENT claim the docstring makes ─────────────────────────────

def test_the_docstring_does_not_claim_an_enforcement_tier_it_lacks(tmp_path):
    """`flow_gate_enforcement_audit` exits 1 when a gate DECLARES
    `ENFORCEMENT: blocking` while being reachable only through the final
    compliance audit. This gate IS audit-only — `_DECLARED_SIGNOFF_GATES` in
    phase3_one_shot_runner carries sta/em, not drc — so the docstring must not
    claim otherwise. Driven, not read."""
    out = tmp_path / "enf.json"
    r = _pr.run(
        [sys.executable, str(PROGRAMS / "flow_gate_enforcement_audit.py"),
         "--json", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-800:]
    gates = {g["gate"]: g for g in json.loads(out.read_text())["gates"]}
    assert gates["drc_report_check"]["enforcement"] == "AUDIT_ONLY"
    assert gates["drc_report_check"]["declared"] is None


def test_the_phase3_runner_really_does_not_invoke_this_gate_inline():
    """The AST fact the docstring states: `_DECLARED_SIGNOFF_GATES` names
    sta_report_check and em_report_check, not drc_report_check."""
    import ast
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text(errors="replace")
    tree = ast.parse(src)
    programs = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "_DECLARED_SIGNOFF_GATES"
                   for t in node.targets):
            continue
        for elt in ast.walk(node.value):
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str) \
                    and elt.value.endswith(".py"):
                programs.add(elt.value)
    assert programs, "_DECLARED_SIGNOFF_GATES was not found or is empty"
    assert "sta_report_check.py" in programs
    assert "drc_report_check.py" not in programs, (
        "the runner now invokes this gate inline — the docstring's AUDIT_ONLY "
        "statement must be re-derived")
