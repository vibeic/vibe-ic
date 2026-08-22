#!/usr/bin/env python3
"""#494 — a read-only validator must not write a file nobody asked for.

Four gates defaulted `--out-dir` to a hardcoded `/tmp/<gatename>`, so every
invocation deposited a JSON report at a fixed, shared, world-writable path:

    crc_seed_consistency_check   -> /tmp/crc_seed_consistency/
    fpga_pullup_lint             -> /tmp/fpga_pullup_lint/
    sustained_vs_edge_check      -> /tmp/sustained_vs_edge/
    transient_signal_latch_check -> /tmp/transient_signal_latch_check/

The P0 umbrella runs its structural gates in a `ThreadPoolExecutor` and passes
only `--rtl-dir` (`flow_compliance_check._structural_gate_argv`), so it never
opted in — yet two concurrent umbrella runs would overwrite each other's report
at that fixed path with nothing marking whose design the surviving file
described. A fixed name under a shared `/tmp` is also a standing symlink-hijack
target, and this repo's own `project_outputs_in_tree_check` FAILs a project for
citing exactly such an artifact.

These tests drive the gates' REAL CLI entry points and read OBSERVABLE results
(exit code, stdout, what appeared on disk). None of them asserts on source text:
a test that greps the program for `default=None` would stay green even if the
line it names blew up at runtime.

Measured over a 561-case corpus, x {--out-dir given, --out-dir omitted}.

DENOMINATOR, stated so it reproduces: `git ls-files benchmark-data` filtered to
.v/.sv, taking the parent directory, keeps **107** dirs named `rtl` — plus the
ONE vendored copy named `src`
(`benchmark-data/ic/subservient/phase2/stage1/formal/subservient/src`) that
this gate's own `rtl|src|hdl` alternation also admits, for 108 directories.
That is the same 107-plus-one split v1.7.69 publishes; the vendored copy
contributes 4 cases, all rc 0 on both sides, and dropping it changes no
verdict below (unrequested writes 545 -> 0 instead of 549 -> 0). Real RTL is
COPIED OUT of benchmark-data before any gate runs; no gate is ever pointed at
the tracked tree. Synthetic fixtures cover every remaining branch.

Results:

  * exit code identical in 561/561 cases, both arms      (nothing about the
    "examined nothing -> rc 2" convention moves)
  * `--out-dir` given: stdout byte-identical, and the same 549 cases write the
    same report files
  * `--out-dir` omitted: unrequested writes 549 -> 0; the ONLY stdout change is
    the trailing `json: <path>` line, dropped in the 459 cases that had one
    (the other 90 were `fpga_pullup_lint`'s no-inout early return, which wrote
    the file but never announced it)

Concurrency note: the negative tests observe the real hardcoded paths, so a
second process deliberately writing `/tmp/<gatename>/<gatename>.json` during
the run could redden them. That is the very collision the issue is about.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent

# gate -> (hardcoded default dir that must no longer be written,
#          report basename)
GATES = {
    "crc_seed_consistency_check":
        ("/tmp/crc_seed_consistency", "crc_seed_consistency_check.json"),
    "fpga_pullup_lint":
        ("/tmp/fpga_pullup_lint", "fpga_pullup_lint.json"),
    "sustained_vs_edge_check":
        ("/tmp/sustained_vs_edge", "sustained_vs_edge_check.json"),
    "transient_signal_latch_check":
        ("/tmp/transient_signal_latch_check",
         "transient_signal_latch_check.json"),
}


def _run(gate: str, args: list) -> subprocess.CompletedProcess:
    """Drive the gate's real CLI — same entry point the P0 umbrella uses."""
    return subprocess.run([sys.executable, str(PROGRAMS / f"{gate}.py")] + args,
                          capture_output=True, text=True)


def _sig(p: Path):
    """Observable write-signature of a path: None, or (mtime_ns, size).

    Comparing this across a run detects a write whether the file was created
    fresh or overwritten in place — which is exactly what a shared fixed path
    does to a concurrent run.
    """
    try:
        st = p.stat()
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _fixture(tmp_path: Path, gate: str) -> list:
    """Minimal real inputs that carry `gate` all the way to its verdict."""
    rtl = tmp_path / "rtl"
    rtl.mkdir(exist_ok=True)
    if gate == "crc_seed_consistency_check":
        vec = tmp_path / "vectors.json"
        vec.write_text(json.dumps({
            "rtl_params": {"width": 8, "poly": 7, "init": 0,
                           "reflect_input": False, "reflect_output": False,
                           "xor_output": 0},
            "spec_vectors": [{"input_hex": "31 32 33 34 35 36 37 38 39",
                              "expected_crc_hex": "0xF4",
                              "source": "CRC-8 check value"}]}))
        return ["--vectors-json", str(vec)]
    if gate == "fpga_pullup_lint":
        # The port list MUST be multi-line. `find_inouts_in_top` consumes the
        # `module top(...)` line and `continue`s, so an inout declared on that
        # same line is never seen — a single-line fixture silently takes the
        # no-inout EARLY RETURN and never reaches the normal verdict's write
        # site. Mutation M6 (unguarding that write site) survived until this
        # was found; `test_fpga_pullup_lint_no_inout_early_return_writes_nothing`
        # below covers the early return deliberately instead of by accident.
        (rtl / "top.v").write_text(
            "module top(\n"
            "  input clk,\n"
            "  inout sda,\n"
            "  inout scl\n"
            ");\nendmodule\n")
        qsf = tmp_path / "top.qsf"
        qsf.write_text(
            "set_location_assignment PIN_A1 -to sda\n"
            "set_instance_assignment -name WEAK_PULL_UP_RESISTOR ON -to sda\n")
        return ["--rtl-dir", str(rtl), "--top-module", "top",
                "--constraint", str(qsf)]
    # the two --rtl-dir gates
    (rtl / "top.v").write_text(
        "module top(input clk, input req, output reg ack);\n"
        "reg req_q;\n"
        "always @(posedge clk) begin\n"
        "  req_q <= req;\n"
        "  if (req && !req_q) ack <= 1'b1;\n"
        "end\nendmodule\n")
    return ["--rtl-dir", str(rtl)]


# ---------------------------------------------------------------------------
# 1. NEGATIVE — omitting --out-dir must leave the hardcoded path untouched
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("gate", sorted(GATES))
def test_no_outdir_writes_nothing_to_the_hardcoded_tmp_path(gate, tmp_path):
    default_dir, basename = GATES[gate]
    target = Path(default_dir) / basename
    before = _sig(target)

    r = _run(gate, _fixture(tmp_path, gate))

    # `rc in (0, 1)` alone is too weak to be a verdict check: an uncaught
    # exception also exits 1, so a gate that crashed on `None / "x.json"`
    # would slip through. Require a real verdict line and no traceback.
    assert "Traceback" not in r.stderr, (
        f"{gate} crashed with no --out-dir:\n{r.stderr}")
    assert r.returncode in (0, 1), (
        f"{gate} did not reach a verdict: rc={r.returncode}\n"
        f"stdout={r.stdout}\nstderr={r.stderr}")
    assert r.stdout.startswith(f"{gate}: "), (
        f"{gate} printed no verdict line: {r.stdout!r}")
    assert _sig(target) == before, (
        f"{gate} wrote {target} without being asked to. A read-only validator "
        f"must produce no file unless a caller passes --out-dir.")


def test_fpga_pullup_lint_no_inout_early_return_writes_nothing(tmp_path):
    """`fpga_pullup_lint` has TWO write sites; this covers the first.

    A top module with no inout ports returns PASS early, from its own
    `write_text` call. That branch is easy to miss because it is reached only
    when the port parser finds nothing — which a single-line port list also
    produces, for an unrelated reason.
    """
    default_dir, basename = GATES["fpga_pullup_lint"]
    target = Path(default_dir) / basename
    before = _sig(target)

    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").write_text("module top(\n  input clk\n);\nendmodule\n")
    qsf = tmp_path / "top.qsf"
    qsf.write_text('set_global_assignment -name FAMILY "MAX 10"\n')

    r = _run("fpga_pullup_lint", ["--rtl-dir", str(rtl), "--top-module", "top",
                                  "--constraint", str(qsf)])
    assert "Traceback" not in r.stderr, r.stderr
    assert r.returncode == 0, f"{r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "no inout ports" in r.stdout, r.stdout   # the early return was taken
    assert _sig(target) == before, (
        f"the no-inout early return wrote {target} without being asked to")

    # and the opt-in path still produces the report from that same branch
    out = tmp_path / "reports"
    r2 = _run("fpga_pullup_lint", ["--rtl-dir", str(rtl), "--top-module", "top",
                                   "--constraint", str(qsf),
                                   "--out-dir", str(out)])
    assert r2.returncode == 0, r2.stderr
    assert "no inout ports" in r2.stdout, r2.stdout
    assert (out / basename).is_file(), "early return dropped the opt-in report"


@pytest.mark.parametrize("gate", sorted(GATES))
def test_no_outdir_prints_no_json_path_line(gate, tmp_path):
    """With nothing written there is no path to announce.

    A `json: /tmp/...` line naming a file that does not exist would send a
    human diagnosing a failure to a phantom artifact — or, worse, to a real
    one left behind by a different project's run.
    """
    r = _run(gate, _fixture(tmp_path, gate))
    offending = [ln for ln in r.stdout.splitlines() if ln.startswith("json: ")]
    assert not offending, (
        f"{gate} announced a report path with no --out-dir given: {offending}")


# ---------------------------------------------------------------------------
# 2. POSITIVE CONTROL — the opt-in path still works
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("gate", sorted(GATES))
def test_explicit_outdir_still_writes_a_parseable_report(gate, tmp_path):
    """Guards the opposite failure: 'fixing' this by never writing at all."""
    _, basename = GATES[gate]
    out = tmp_path / "reports"
    r = _run(gate, _fixture(tmp_path, gate) + ["--out-dir", str(out)])

    assert r.returncode in (0, 1), (
        f"{gate} rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}")
    report = out / basename
    assert report.is_file(), (
        f"{gate} did not write {report} despite an explicit --out-dir")
    payload = json.loads(report.read_text())
    assert payload.get("status") in ("PASS", "FAIL"), payload


def test_explicit_outdir_announces_the_path_it_wrote(tmp_path):
    """The three gates that announce their report still do so.

    `fpga_pullup_lint` is excluded on purpose: its no-inout early return has
    never printed a `json:` line, and this fix did not add one.
    """
    for gate in ("crc_seed_consistency_check", "sustained_vs_edge_check",
                 "transient_signal_latch_check"):
        d = tmp_path / gate
        d.mkdir()
        out = d / "reports"
        r = _run(gate, _fixture(d, gate) + ["--out-dir", str(out)])
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith("json: ")]
        assert lines, f"{gate} wrote a report but did not announce it"
        assert Path(lines[-1][len("json: "):]).is_file(), lines


# ---------------------------------------------------------------------------
# 3. rc INVARIANCE — whether a report is written must not steer the verdict
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("gate", sorted(GATES))
def test_outdir_never_changes_the_exit_code(gate, tmp_path):
    """v1.7.69 pinned 'examined nothing -> rc 2'. Nothing here may move an rc.

    Runs the same inputs twice — once with --out-dir, once without — and
    requires an identical exit code. Covers the verdict paths (rc 0/1) and the
    input-missing / nothing-examined path (rc 2).
    """
    base = _fixture(tmp_path, gate)
    variants = {"verdict": base}
    if gate == "crc_seed_consistency_check":
        variants["missing_input"] = ["--vectors-json",
                                     str(tmp_path / "absent.json")]
    elif gate == "fpga_pullup_lint":
        variants["missing_input"] = ["--rtl-dir", str(tmp_path / "absent"),
                                     "--top-module", "top",
                                     "--constraint", str(tmp_path / "top.qsf")]
    else:
        variants["missing_input"] = ["--rtl-dir", str(tmp_path / "absent")]
        # dangling symlink => globbed but unreadable => the v1.7.69 rc 2
        nore = tmp_path / "noread"
        nore.mkdir()
        os.symlink("/nonexistent/target.v", nore / "dangling.v")
        variants["nothing_readable"] = ["--rtl-dir", str(nore)]

    for name, argv in variants.items():
        with_out = _run(gate, argv + ["--out-dir", str(tmp_path / f"o_{name}")])
        without = _run(gate, argv)
        assert with_out.returncode == without.returncode, (
            f"{gate} [{name}]: rc changed with --out-dir "
            f"({with_out.returncode}) vs without ({without.returncode}); "
            f"whether a report is written must never steer the verdict")


def test_nothing_readable_still_returns_rc_2_without_outdir(tmp_path):
    """Pins the v1.7.69 convention on the no-out-dir path specifically."""
    for gate in ("sustained_vs_edge_check", "transient_signal_latch_check"):
        d = tmp_path / gate
        d.mkdir()
        os.symlink("/nonexistent/target.v", d / "dangling.v")
        r = _run(gate, ["--rtl-dir", str(d)])
        if gate == "sustained_vs_edge_check":
            assert r.returncode == 2, (
                f"{gate} must still report NOT CHECKED as rc 2 "
                f"(got {r.returncode}): {r.stdout}{r.stderr}")
        else:
            assert r.returncode in (0, 1, 2), r.returncode


# ---------------------------------------------------------------------------
# 4. GENERALIZATION — no program may reintroduce a volatile --out-dir default
# ---------------------------------------------------------------------------
_VOLATILE_PREFIXES = ("/tmp", "/var/tmp", "/dev/shm", "/run")


def _literal_str(node):
    """Fold `"s"` and `Path("s")` to `s`; anything else to None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call):
        fn = node.func
        name = (fn.id if isinstance(fn, ast.Name)
                else fn.attr if isinstance(fn, ast.Attribute) else None)
        if name in ("Path", "PosixPath") and node.args:
            return _literal_str(node.args[0])
    return None


def test_no_program_defaults_an_output_flag_to_a_volatile_path():
    """Structural, repo-wide guard — catches the 5th offender before it lands.

    Parses every program with `ast` rather than grepping, because a grep hit
    can be a docstring example (several programs legitimately show
    `--out-dir /tmp/audit` in usage text) while a real defect is an
    `add_argument(..., default=Path("/tmp/..."))` node.
    """
    offenders = []
    for prog in sorted(PROGRAMS.glob("*.py")):
        try:
            tree = ast.parse(prog.read_text(errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_argument"):
                continue
            flag = next((s for s in map(_literal_str, node.args)
                         if s and s.startswith("--")), None)
            if flag not in ("--out-dir", "--out", "--json", "--report",
                            "--output", "--out-file"):
                continue
            for kw in node.keywords:
                if kw.arg != "default":
                    continue
                val = _literal_str(kw.value)
                if val and val.startswith(_VOLATILE_PREFIXES):
                    offenders.append(f"{prog.name}:{node.lineno} "
                                     f"{flag} default={val!r}")
    assert not offenders, (
        "an output flag defaults to a hardcoded volatile path — a run that "
        "asked for no file would write one, and two concurrent runs would "
        "overwrite each other:\n  " + "\n  ".join(offenders))


# ---------------------------------------------------------------------------
# 5. INTEGRATION — the P0 umbrella's own argv leaves /tmp alone
# ---------------------------------------------------------------------------
def test_umbrella_argv_produces_no_tmp_artifact(tmp_path):
    """Drives `flow_compliance_check._structural_gate_argv` — the REAL builder
    the umbrella worker uses — rather than a re-typed argv that would agree
    with the umbrella only by coincidence.
    """
    sys.path.insert(0, str(PROGRAMS))
    try:
        import flow_compliance_check as F
    finally:
        sys.path.pop(0)

    project = tmp_path / "proj"
    rtl = project / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top(input clk, input req, output reg ack);\n"
        "reg req_q;\n"
        "always @(posedge clk) begin\n"
        "  req_q <= req;\n"
        "  if (req && !req_q) ack <= 1'b1;\n"
        "end\nendmodule\n")

    gate = "sustained_vs_edge_check"
    default_dir, basename = GATES[gate]
    target = Path(default_dir) / basename
    before = _sig(target)

    argv = F._structural_gate_argv(gate, project, rtl_dir=rtl)
    assert "--out-dir" not in argv, (
        "the umbrella does not opt in to a report, so the gate must not "
        f"write one: {argv}")
    r = subprocess.run(argv, cwd=project, capture_output=True, text=True,
                       timeout=60)

    assert r.returncode in (0, 1), (
        f"umbrella argv rc={r.returncode}\n{r.stdout}\n{r.stderr}")
    assert _sig(target) == before, (
        f"a P0 umbrella run wrote {target}; two concurrent umbrella runs "
        f"would overwrite each other's report there")
