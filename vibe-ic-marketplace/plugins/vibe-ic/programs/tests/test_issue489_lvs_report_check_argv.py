#!/usr/bin/env python3
"""#489 — the two argv defects of `lvs_report_check.py`, the Step-31 LVS gate.

EVERY test here DRIVES THE PROGRAM. Not one of them reads the source text of the
thing it is testing: a test that asserts on source text passes while the code it
names raises at runtime, and that shipped in this repo. The end-to-end tests go
one level further and drive the REAL Step-31 gate runner
(`flow_compliance_check._check_program_exit_zero`), because the property that
matters is not "the wrapper returns N" but "the hard sign-off gate does not go
green when nothing was audited".

Measured on v1.7.66 before the fix, on the fixtures below:

    lvs_report_check proj --mode=power --json out.json  -> audit program was
                                                           `eda_report_audit:power`
    lvs_report_check --json out.json proj               -> IsADirectoryError,
                                                           NO audit written
    lvs_report_check proj --help                        -> rc 0, gate GREEN,
                                                           nothing audited
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
PROG = PROGRAMS / "lvs_report_check.py"

sys.path.insert(0, str(PROGRAMS))

import _report_check_argv as argv_helper  # noqa: E402
import lvs_report_check as wrapper  # noqa: E402

# An AUTHENTIC netgen sign-off transcript: tool signature, a mismatch-category
# keyword, the terminal MATCH token, and enough per-cell body to clear the
# netgen byte floor. Chip-AGNOSTIC: no vendor / SKU / IC literal anywhere.
_MATCH_RPT = (
    "netgen 1.5.257 compare\n"
    "Contents of circuit 1:  Circuit: 'top'\n"
    "Contents of circuit 2:  Circuit: 'top'\n"
    + "".join(f"Device classes cell_{i} and cell_{i} are equivalent.\n"
             for i in range(60))
    + "Cell pin lists are equivalent.\n"
      "Net count: 128   Device count: 512\n"
      "Final result: Circuits match uniquely.\n"
)

# A clean POWER report, and NO lvs report. This is the project shape that turns
# the mode-spoof into a FALSE CERTIFICATE: the power audit passes, so a wrapper
# that lets the caller redirect it exits 0 on the LVS gate.
_POWER_RPT = (
    "OpenROAD Power Report\n"
    "Group: sequential    Internal Power: 0.12 mW\n"
    "Group: combinational Switching Power: 0.34 mW\n"
    "Leakage Power: 0.05 mW (static power)\n"
    + "# " + ("=" * 78 + "\n") * 40
)


def _run(args, cwd=None):
    return subprocess.run([sys.executable, str(PROG)] + list(args),
                          capture_output=True, text=True, timeout=60, cwd=cwd)


def _project(tmp_path, *, lvs=True, power=False):
    d = tmp_path / "proj" / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    if lvs:
        (d / "lvs.rpt").write_text(_MATCH_RPT)
    if power:
        (d / "power_analysis.rpt").write_text(_POWER_RPT)
    return tmp_path / "proj"


# ── DEFECT 1 — `--mode` is actually pinned now, in BOTH spellings ──────────

def test_space_spelling_pins_lvs(tmp_path):
    proj = _project(tmp_path)
    out = tmp_path / "a.json"
    r = _run([str(proj), "--mode", "lvs", "--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(out.read_text())["program"] == "eda_report_audit:lvs"


def test_equals_spelling_pins_lvs(tmp_path):
    """The spelling the old splitter forwarded verbatim. `--mode=lvs` names the
    mode this wrapper pins, so it is accepted and pins lvs — it must not be
    refused just because it uses an `=`."""
    proj = _project(tmp_path)
    out = tmp_path / "b.json"
    r = _run([str(proj), "--mode=lvs", "--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(out.read_text())["program"] == "eda_report_audit:lvs"


@pytest.mark.parametrize("spelling", [["--mode=power"], ["--mode", "power"],
                                      ["--mode=drc"], ["--mode"]])
def test_any_other_mode_is_refused_not_honoured(tmp_path, spelling):
    """v1.7.66: `--mode=power` ran `eda_report_audit:power` (silently HONOURED)
    and `--mode power` was silently DROPPED. Both lie to the caller about what
    was certified; both are refused now, in every spelling, including a
    valueless `--mode`."""
    proj = _project(tmp_path)
    out = tmp_path / "c.json"
    r = _run([str(proj)] + spelling + ["--json", str(out)])
    assert r.returncode != 0, r.stdout + r.stderr
    assert "REFUSED" in r.stderr
    payload = json.loads(out.read_text())
    assert payload["passed"] is False
    assert payload["program"] == "lvs_report_check"
    assert [f["rule"] for f in payload["findings"]] == ["LVS_MODE_PIN_REFUSED"]
    assert payload["summary"]["checked"] is False


def test_mode_spoof_no_longer_manufactures_an_lvs_certificate(tmp_path):
    """THE defect, in the shape that makes it a sign-off bug rather than an argv
    nit: a project with a clean POWER report and NO LVS report at all. On
    v1.7.66 `--mode=power` audited power, exited 0, and wrote
    `eda_report_audit:power / passed: true` into the file the flow declares as
    the LVS audit."""
    proj = _project(tmp_path, lvs=False, power=True)
    out = proj / "reports" / "phase3" / "lvs.json"
    honest = _run([str(proj), "--mode", "lvs", "--json", str(out)])
    assert honest.returncode == 1, "no LVS report present -> must FAIL"
    spoof = _run([str(proj), "--mode=power", "--json", str(out)])
    assert spoof.returncode != 0
    written = json.loads(out.read_text())
    assert written["passed"] is False
    assert written["program"] != "eda_report_audit:power"


# ── DEFECT 2 — the split is value-aware ────────────────────────────────────

def test_json_value_is_not_taken_as_the_project_dir(tmp_path):
    """v1.7.66: `--json out.json <proj>` resolved the project to `out.json` and
    handed `<proj>` — a directory — to `--json`, dying with IsADirectoryError
    and writing NO audit."""
    proj = _project(tmp_path)
    out = tmp_path / "d.json"
    r = _run(["--json", str(out), str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "IsADirectoryError" not in r.stderr
    payload = json.loads(out.read_text())
    assert payload["program"] == "eda_report_audit:lvs"
    assert payload["passed"] is True
    assert payload["summary"]["files_found"] >= 1


def test_json_before_project_still_emits_on_a_failing_project(tmp_path):
    """Same argv order, FAILING project: the audit must still be written. The
    defect wrote nothing at all, so a reviewer could not tell a fail from a
    crash."""
    proj = _project(tmp_path, lvs=False)
    out = tmp_path / "e.json"
    r = _run(["--json", str(out), str(proj)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert json.loads(out.read_text())["passed"] is False


def test_equals_spelling_of_json_is_forwarded_untouched(tmp_path):
    proj = _project(tmp_path)
    out = tmp_path / "f.json"
    r = _run([str(proj), f"--json={out}"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(out.read_text())["passed"] is True


def test_double_dash_lets_a_dash_leading_project_be_named(tmp_path):
    proj = _project(tmp_path)
    out = tmp_path / "g.json"
    r = _run(["--json", str(out), "--", str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(out.read_text())["passed"] is True


# ── the audit is ALWAYS emitted, or the run says it was not ───────────────

def test_json_naming_a_directory_does_not_crash_and_says_so(tmp_path):
    """`--json <an existing directory>` used to escape as an uncaught
    IsADirectoryError traceback. It must now be a stated, non-zero
    NOT-CHECKED."""
    proj = _project(tmp_path)
    victim = tmp_path / "adir"
    victim.mkdir()
    r = _run([str(proj), "--json", str(victim)])
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
    assert "NOT CHECKED" in r.stderr


def test_help_does_not_spend_a_signoff_credit(tmp_path):
    """v1.7.66: `lvs_report_check <proj> --help` exited 0 — argparse's help
    action propagated SystemExit(0) through the wrapper — so the Step-31 gate
    went green having audited nothing. Exit 0 from this program IS the
    sign-off credit; an invocation that certified nothing must not spend
    one."""
    proj = _project(tmp_path)
    r = _run([str(proj), "--help"])
    assert r.returncode != 0, r.stdout + r.stderr
    assert "NOT CHECKED" in r.stderr


def test_a_second_bare_positional_stays_visible(tmp_path):
    """A broken declaration must be reported, never absorbed into a pass."""
    proj = _project(tmp_path)
    r = _run([str(proj), str(tmp_path), "--mode", "lvs"])
    assert r.returncode != 0


# ── the rc contract, and a PASS that discloses its denominator ────────────

def test_pass_discloses_its_denominator_on_stderr(tmp_path):
    proj = _project(tmp_path)
    r = _run([str(proj), "--mode", "lvs"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "files_found=1" in r.stderr
    assert "terminal_verdict=MATCH" in r.stderr


def test_stdout_stays_pure_audit_json(tmp_path):
    """`test_v0_2_97_issue477_lvs_incomplete` does `json.loads(cp.stdout)`.
    Every disclosure this wrapper adds therefore goes to stderr."""
    proj = _project(tmp_path)
    r = _run([str(proj), "--mode", "lvs"])
    assert json.loads(r.stdout)["program"] == "eda_report_audit:lvs"
    r_fail = _run([str(tmp_path / "nonexistent")])
    assert json.loads(r_fail.stdout)["passed"] is False


def test_a_pass_that_cannot_name_a_denominator_is_refused():
    """Tripwire, driven through `run()` with an injected audit because
    `_check_lvs` cannot currently produce this payload (it returns early on an
    empty discovery). Four sibling modes CAN — their `_waived_for_pdk` path
    sets passed=True with a summary carrying no `files_found` — so if lvs ever
    grows one, a denominator-less PASS on a hard sign-off must not slip
    through."""
    def _denominator_less_pass(argv):
        print(json.dumps({"program": "eda_report_audit:lvs", "passed": True,
                          "findings": [],
                          "summary": {"waived": True, "reason": "x" * 40}}))
        return 0

    assert wrapper.run(["."], _audit=_denominator_less_pass) == 1
    ok, files_found, _ = wrapper.denominator_of(
        {"summary": {"waived": True}})
    assert ok is False and files_found is None
    assert wrapper.denominator_of({"summary": {"files_found": 3}})[0] is True
    # a bool is not a denominator
    assert wrapper.denominator_of({"summary": {"files_found": True}})[0] is False


# ── the property that actually matters: the Step-31 GATE ──────────────────

@pytest.mark.parametrize("cmd", [
    "lvs_report_check . --mode=power --json reports/phase3/lvs.json",
    "lvs_report_check . --mode power --json reports/phase3/lvs.json",
    "lvs_report_check . --help",
])
def test_step31_gate_does_not_go_green_on_a_spoofed_invocation(tmp_path, cmd):
    """Driven through the REAL gate runner. On v1.7.66 all three of these
    returned passed=True against a project with NO LVS report at all."""
    import flow_compliance_check as fcc
    proj = _project(tmp_path, lvs=False, power=True)
    passed, _snippet = fcc._check_program_exit_zero(proj, cmd)
    assert passed is False, cmd


def test_step31_gate_still_passes_the_flow_s_own_declaration(tmp_path):
    """No-regression: the declaration in flow/phase1_phase2_phase3.yaml Step 31,
    verbatim, on a genuinely LVS-clean project."""
    import flow_compliance_check as fcc
    proj = _project(tmp_path)
    passed, _snippet = fcc._check_program_exit_zero(
        proj, "lvs_report_check . --mode lvs --json reports/phase3/lvs.json")
    assert passed is True
    assert json.loads(
        (proj / "reports/phase3/lvs.json").read_text())["passed"] is True


def test_refusal_rc_is_not_the_vacuous_pass_code(tmp_path, monkeypatch):
    """`_check_program_exit_zero` credits rc==2 as a VACUOUS_PASS
    UNCONDITIONALLY (rc==3 additionally requires a stdout sentinel; rc==2 does
    not). This test DRIVES that runner with a probe that exits 2 to prove the
    credit is real, then pins that this wrapper's refusal does not use that
    code — a refusal that exited 2 would turn Step 31 green, which is a cheaper
    false certificate than the one the refusal exists to close.

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
    credited, _ = fcc._check_program_exit_zero(proj, "rc2_probe .")
    assert credited is True, "premise changed: rc 2 is no longer a vacuous pass"

    r = _run([str(_project(tmp_path, lvs=True)), "--mode=power"])
    assert r.returncode != 2
    assert r.returncode == 1


# ── anti-drift: the shared splitter knows every value-taking option ───────

def test_value_flags_cover_eda_report_audit_s_real_parser():
    """Derived from the WRAPPED program's actual argparse parser, not from a
    hand-kept list: a new value-taking option added to `eda_report_audit`
    without being told to the splitter reintroduces defect 2 for that option,
    and this test goes red the moment it is added."""
    import argparse
    import eda_report_audit

    captured = {}

    class _Stop(Exception):
        pass

    original = argparse.ArgumentParser.parse_args

    def _spy(self, *a, **k):
        captured["parser"] = self
        raise _Stop()

    argparse.ArgumentParser.parse_args = _spy
    try:
        eda_report_audit.main(["x", "--mode", "lvs"])
    except _Stop:
        pass
    finally:
        argparse.ArgumentParser.parse_args = original

    parser = captured["parser"]
    value_taking = {opt for act in parser._actions
                    for opt in act.option_strings
                    if act.nargs != 0}
    assert value_taking, "spy failed to capture the parser"
    assert value_taking <= set(argv_helper.VALUE_FLAGS), (
        f"eda_report_audit takes a value for {sorted(value_taking)} but "
        f"_report_check_argv.VALUE_FLAGS is {argv_helper.VALUE_FLAGS}")


def test_under_value_is_not_taken_as_the_project_dir():
    """THE DRIFT THE GUARD ABOVE CAUGHT, pinned as behaviour.

    `--under` was added to `eda_report_audit` by the step-21 scoping work that
    landed in the same batch as this helper. Neither change was red alone; the
    accumulation was. Before `--under` joined VALUE_FLAGS:

        split_argv(["--under", "sub/dir", "myproj", "--mode", "lvs"])
            -> project = "sub/dir"          <- the flag's ARGUMENT
               passthrough = ["--under", "myproj", ...]

    i.e. the auditor would have run against the scope directory and forwarded
    the real project as the scope. That is this helper's own defect class,
    arriving through a sibling change rather than a copy."""
    proj, rest = argv_helper.split_argv(
        ["--under", "sub/dir", "myproj", "--mode", "lvs"])
    assert proj == "myproj", proj
    assert rest == ["--under", "sub/dir", "--mode", "lvs"], rest


# ── the shared splitter, as a pure function ──────────────────────────────

@pytest.mark.parametrize("rest,expected", [
    ([], (".", [])),
    (["proj"], ("proj", [])),
    (["--json", "out.json", "proj"], ("proj", ["--json", "out.json"])),
    (["proj", "--json", "out.json"], ("proj", ["--json", "out.json"])),
    (["--json=out.json", "proj"], ("proj", ["--json=out.json"])),
    (["--", "-weird-dir"], ("-weird-dir", [])),
    (["--json", "out.json"], (".", ["--json", "out.json"])),
    (["a", "b"], ("a", ["b"])),
    # an option-looking token is never eaten as another option's value —
    # argparse reads it the same way, and swallowing it would drop a real flag
    (["--json", "--quiet", "proj"], ("proj", ["--json", "--quiet"])),
    (["-"], ("-", [])),
])
def test_split_argv_is_value_aware(rest, expected):
    assert argv_helper.split_argv(rest) == expected


@pytest.mark.parametrize("rest,refused", [
    (["p", "--mode", "lvs"], False),
    (["p", "--mode=lvs"], False),
    (["p", "--mode", "power"], True),
    (["p", "--mode=power"], True),
    (["p", "--mode"], True),
    (["p"], False),
])
def test_split_and_pin_refuses_only_a_foreign_mode(rest, refused):
    _proj, passthrough, refusal = argv_helper.split_and_pin(rest, mode="lvs")
    assert (refusal is not None) is refused
    assert not any(t.startswith("--mode") for t in passthrough), (
        "a caller --mode must never reach the wrapped program")
