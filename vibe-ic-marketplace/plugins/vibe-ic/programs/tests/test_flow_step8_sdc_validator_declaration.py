"""Step 8's `sdc_validator_check` gate must actually read the project's SDC.

The defect
----------
`flow/phase1_phase2_phase3.yaml` step 8 declared

    sdc_validator_check phase2/stage2/constraints --l8 ... --json ...

but `sdc_validator_check`'s positional is the PROJECT ROOT — it resolves
`_path_layout.constraints_dir()` / `fpga_early_dir()` itself. The effective
search root therefore became

    phase2/stage2/constraints/phase2/stage2/constraints

which never exists on any project. Since v1.6.18 the program printed
`[SKIP] sdc_validator_check: no .sdc files` and exited 0 on EVERY run.

`optional_program_exit_zero` is optional only on its condition_files_exist
TRIGGER — once triggered, a non-zero exit sets passed=False and fails the
enclosing all_of (flow_compliance_check.py ~4442). So this was a BLOCKING gate
that had been silently disarmed, not an advisory one.

Measured on the real spm x ihp-sg13g2 run:
    yaml-literal form  -> [SKIP] no .sdc files, rc=0, no JSON written
    project-root form  -> [PASS] 2 SDC file(s) OK, rc=0, JSON written
and on a fixture whose SDC omits two directives the project-root form rc=1
while the yaml-literal form still rc=0.

What is asserted here
---------------------
The tests drive the LITERAL command string parsed out of the shipped yaml,
through flow_compliance_check's OWN resolver + runner (`_resolve_program_cmd`
/ `_check_program_exit_zero`), so a future edit that re-breaks the positional
— or a resolver change that mangles it — is caught. Nothing about the path is
hard-coded in the assertions; the yaml is the input.

Direction-1 guards assert what must NOT change: the project-root call shape
still works, a project with genuinely no .sdc anywhere still SKIPs at rc 0,
and an FPGA-side SDC is still validated.

DEFERRED, deliberately
----------------------
The recommended companion hardening — make `sdc_validator_check` emit a loud
non-zero `SDC_SEARCH_ROOT_MISDIRECTED` when the project carries .sdc files but
none are under the search roots, instead of the indistinguishable
`[SKIP] no .sdc files` — is NOT in this change. It was written and measured
(it turns the pre-fix invocation from rc 0 into rc 1 on the real project), then
withdrawn: `programs/sdc_validator_check.py` is being rewritten concurrently by
another fix group, which is adding an L8 cross-check and grows the file from 53
to 332 lines while keeping the search-root glob (their lines 296-298) and the
silent skip (their line 308) byte-identical to main. Editing the same region
would collide. The declaration fix here is what ARMS their cross-check too: on
the real project their program is reached only because the positional is now
the project root. The re-breakage guard that hardening would have provided is
covered by `test_shipped_gate_command_validates_a_real_constraints_sdc`, which
fails if the shipped gate ever SKIPs a project that ships an SDC.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PLUGIN = _PROGRAMS.parent
for _p in (str(_PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import flow_compliance_check as _fcc                      # noqa: E402

FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
PROG = _PROGRAMS / "sdc_validator_check.py"

_GOOD_SDC = """\
create_clock -name clk -period 20 [get_ports clk]
set_input_delay  -clock clk 2 [get_ports din]
set_output_delay -clock clk 2 [get_ports dout]
"""
# Real shape of the failure this gate exists to catch: syntactically fine,
# but two of the three mandated directives are absent.
_UNCONSTRAINED_SDC = "create_clock -name clk -period 20 [get_ports clk]\n"


# ── read the shipped declaration ─────────────────────────────────────────────

def _step8_sdc_validator_command() -> str:
    doc = yaml.safe_load(FLOW.read_text())
    for st in doc.get("steps", []):
        if str(st.get("id")) != "8":
            continue
        for member in (st.get("gate") or {}).get("all_of", []):
            spec = (member or {}).get("optional_program_exit_zero")
            if isinstance(spec, dict) and \
                    str(spec.get("command", "")).startswith(
                        "sdc_validator_check"):
                return spec["command"]
    raise AssertionError(
        "premise: step 8 no longer declares an sdc_validator_check gate — "
        "this test scans nothing")


@pytest.fixture(scope="module")
def gate_cmd() -> str:
    return _step8_sdc_validator_command()


def _project(tmp_path: Path, *, constraints=None, fpga=None) -> Path:
    project = tmp_path / "proj"
    (project / "phase1" / "generated_docs").mkdir(parents=True)
    (project / "phase1" / "generated_docs" /
     "L8_TIMING_WAVEFORM.json").write_text('{"clocks": []}')
    if constraints is not None:
        d = project / "phase2" / "stage2" / "constraints"
        d.mkdir(parents=True)
        (d / "top.sdc").write_text(constraints)
    if fpga is not None:
        d = project / "phase2" / "stage1" / "fpga"
        d.mkdir(parents=True)
        (d / "board.sdc").write_text(fpga)
    return project


def _run_gate(project: Path, cmd: str):
    """Exactly how flow_compliance_check runs a gate command."""
    return _fcc._check_program_exit_zero(project, cmd)


# ── THE discriminators: the shipped command must reach the real SDC ──────────

def test_shipped_gate_command_validates_a_real_constraints_sdc(
        tmp_path, gate_cmd):
    """A project with a complete SDC under phase2/stage2/constraints must be
    VALIDATED, not skipped. Pre-fix this printed `[SKIP] no .sdc files`."""
    project = _project(tmp_path, constraints=_GOOD_SDC)
    passed, out = _run_gate(project, gate_cmd)
    assert passed, f"gate must pass on a complete SDC; output: {out!r}"
    assert "[SKIP]" not in out, (
        "the step-8 gate SKIPPED a project that ships an SDC — the declared "
        f"positional is not reaching the constraints directory. output: {out!r}")
    assert "[PASS]" in out and "SDC file(s) OK" in out, out


def test_shipped_gate_command_fails_an_unconstrained_sdc(tmp_path, gate_cmd):
    """The blocking half. An SDC with no set_input_delay / set_output_delay
    must fail step 8's all_of. Pre-fix this was a silent exit-0 skip."""
    project = _project(tmp_path, constraints=_UNCONSTRAINED_SDC)
    passed, out = _run_gate(project, gate_cmd)
    assert not passed, (
        "an SDC missing set_input_delay and set_output_delay must FAIL the "
        f"step-8 gate; output: {out!r}")
    assert "set_input_delay" in out and "set_output_delay" in out, out


def test_shipped_gate_command_writes_its_declared_json(tmp_path, gate_cmd):
    """The gate declares `--json reports/sdc_validator.json`. Pre-fix that file
    was never created on any project, which is the cheapest external signal
    that the program never ran on real input."""
    project = _project(tmp_path, constraints=_GOOD_SDC)
    _run_gate(project, gate_cmd)
    assert (project / "reports" / "sdc_validator.json").is_file(), (
        "the gate's declared JSON report was not written — the program did "
        "not reach any SDC")


def test_shipped_gate_command_positional_is_the_project_root(gate_cmd):
    """Pin the contract in the declaration itself, so the failure mode is
    reported as a wrong POSITIONAL rather than as a mysterious skip."""
    argv = gate_cmd.split()
    assert argv[0] == "sdc_validator_check"
    assert argv[1] == ".", (
        f"step 8 must pass the PROJECT ROOT to sdc_validator_check; the "
        f"declaration passes {argv[1]!r}, which the program will re-resolve "
        f"against _path_layout and turn into a nonexistent doubled path")


# ── the pre-fix invocation, pinned as the defect it was ─────────────────────

def _run_prog(args):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, timeout=60)


def test_the_prefix_positional_reaches_no_sdc_at_all(tmp_path):
    """Pin WHY the declaration had to change, against the program as it ships.
    Handed the constraints directory, the program resolves
    phase2/stage2/constraints/phase2/stage2/constraints — reads nothing — and
    reports the same `no .sdc files` it reports for a project that genuinely
    has none. That indistinguishability is the whole defect; the DECLARATION is
    what fixes it (see the DEFERRED note in this module's docstring for the
    program-side self-diagnostic)."""
    project = _project(tmp_path, constraints=_GOOD_SDC)
    cp = _run_prog([str(project / "phase2" / "stage2" / "constraints")])
    assert "[SKIP]" in cp.stdout, cp.stdout
    empty = _project(tmp_path / "empty")
    cp2 = _run_prog([str(empty)])
    assert cp.stdout.strip() == cp2.stdout.strip(), (
        "premise: a misdirected invocation is indistinguishable from an empty "
        f"project. misdirected={cp.stdout!r} empty={cp2.stdout!r}")


# ── direction-1 guards: behaviour that must NOT change ──────────────────────

def test_guard_project_root_call_shape_still_passes(tmp_path):
    """The call shape used by programs/tests/test_sdc_validator_check.py."""
    project = _project(tmp_path, fpga=_GOOD_SDC)
    cp = _run_prog([str(project)])
    assert cp.returncode == 0, cp.stdout
    assert "[PASS]" in cp.stdout and "1 SDC" in cp.stdout


def test_guard_no_sdc_anywhere_is_still_a_zero_exit_skip(tmp_path):
    """A project that genuinely ships no SDC still SKIPs — `sdc_syntax_check`,
    the FIRST member of step 8's all_of, is what blocks that case."""
    project = _project(tmp_path)
    cp = _run_prog([str(project)])
    assert cp.returncode == 0, cp.stdout
    assert "[SKIP]" in cp.stdout


def test_guard_empty_search_root_directories_still_skip(tmp_path):
    project = _project(tmp_path)
    (project / "phase2" / "stage2" / "constraints").mkdir(parents=True)
    (project / "phase2" / "stage1" / "fpga").mkdir(parents=True)
    cp = _run_prog([str(project)])
    assert cp.returncode == 0, cp.stdout
    assert "[SKIP]" in cp.stdout


def test_guard_both_search_roots_are_still_searched(tmp_path):
    """Widened scope disclosure: with the project root the program globs BOTH
    phase2/stage1/fpga and phase2/stage2/constraints, so FPGA-side SDCs come
    under the same three-directive rule. Pin that both are read."""
    project = _project(tmp_path, constraints=_GOOD_SDC, fpga=_GOOD_SDC)
    cp = _run_prog([str(project)])
    assert cp.returncode == 0, cp.stdout
    assert "2 SDC file(s) OK" in cp.stdout, cp.stdout


def test_guard_a_broken_fpga_sdc_still_fails(tmp_path):
    project = _project(tmp_path, constraints=_GOOD_SDC,
                       fpga=_UNCONSTRAINED_SDC)
    cp = _run_prog([str(project)])
    assert cp.returncode == 1, cp.stdout
    assert "board.sdc" in cp.stdout, cp.stdout
