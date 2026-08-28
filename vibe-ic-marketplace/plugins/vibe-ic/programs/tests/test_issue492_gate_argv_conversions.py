#!/usr/bin/env python3
"""#492 conversion half — which never-invoked gates were made to RUN, and why
every other candidate deliberately was not.

The caller-side discriminator (see `test_issue492_umbrella_gate_invocation.py`)
makes an argv rejection visible instead of benign. It does not by itself invoke
anything. This file covers the second half: supplying an argument the umbrella
already has, ONE GATE AT A TIME, each licensed by its own measurement.

THE BAR HAS TWO HALVES AND THE SECOND IS THE ONE THAT DISQUALIFIES MOST
CANDIDATES. Repairing an argv must not turn a silent skip into a universal FAIL
(the `l9_completeness_check` trap: 196/196). But it must also not turn a silent
skip into a PASS OVER AN EMPTY DENOMINATOR, which is a false PASS and is worse
than the skip it replaces — the umbrella would be certifying a check that
examined nothing. Both halves were measured; only three gates clear both.

MEASUREMENT PROVENANCE, stated so it reproduces rather than described. The
denominator is 108:

    git ls-files benchmark-data | grep -E '/rtl/[^/]+\\.(v|sv)$' \\
        | sed -E 's#/rtl/[^/]+$##' | sort -u | wc -l      -> 108

It was 107 when this was first measured at v1.7.69 and became 108 in cdc54d32f
(2026-08-02), which added
`benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage1/rtl`. The
whole sweep was RE-RUN over the 108 rather than the pin raised to match: three
rows claim "0 FAIL over ALL of them", and raising the number alone would assert
that about a directory no gate had been pointed at. What moved, and why nine of
the fifteen rows had rotted while this pin stayed green, is recorded in the
comment block above `P0_RTL_DIR_GROUP_MEASUREMENT` in `flow_compliance_check`.

Do not read this 108 as the v1.7.69 sweep's 108, which was a DIFFERENT set: that
one applied `flow_compliance_check`'s OWN rtl_dir alternation ("phase2/stage1/
rtl", "rtl", "src", "hdl") to a 107-dir corpus, and its extra member was
`benchmark-data/ic/subservient/phase2/stage1/formal/subservient/src` — a
vendored formal copy, not a project root the flow is pointed at. The numbers
below are quoted on the 108 directories NAMED `rtl`, which is the set the test
at the bottom of this file reconstructs.

Every gate CLI was run against a scratch MIRROR of those directories, never
against the tracked tree, which stays byte-clean.

THAT ONE-LINER NOW SPANS TWO TREES. The published cells moved to
https://github.com/vibeic/benchmark-data; the design INPUTS stayed in vibe-ic.
Neither half alone reconstructs the 108 — the corpus carries 105 and this
checkout carries the 3 under `ic/*/input/**/rtl` — and the two sets are
disjoint, so the denominator is the union and the reconstruction below takes it.
Run `git ls-files` in this checkout alone and you get 3, which is not a smaller
corpus but a half-read one; with no corpus to read at all the reconstruction
SKIPS naming it (`_published_corpus`) instead of reporting a corpus that shrank.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _gate_invocation as GI  # noqa: E402
import _published_tree  # noqa: E402  (the ONE tracked-ness resolver)

from _published_corpus import corpus_root, needs_corpus  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

#: The half of the published tree that stayed in vibe-ic: the design inputs.
_INPUT_HALF = PROGRAMS.parents[3] / "benchmark-data"


def _tracked_rtl_dirs(root: Path) -> set:
    """Directories NAMED `rtl` that hold published Verilog, root-relative.

    Tracked-ness, not disk presence, is what "published" means here, so this
    goes through `_published_tree` rather than asking this machine's checkout —
    otherwise a stray local run directory joins a denominator that three rows
    describe as "0 FAIL over ALL of them". Its `None` means "not a published
    tree", which is answered from disk rather than read as "published and
    empty".
    """
    if not root.is_dir():
        return set()
    tracked = _published_tree.published_paths(root)
    if tracked is None:
        tracked = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]
    return {str(Path(f).parent) for f in tracked
            if Path(f).parent.name == "rtl" and Path(f).suffix in (".v", ".sv")}


def _load_flow():
    spec = importlib.util.spec_from_file_location(
        "fcc_i492_conv", PROGRAMS / "flow_compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fcc_i492_conv"] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load_flow()

# vibe-ic#559 — the measurement now lives BESIDE the umbrella that needs it
# (`flow_compliance_check`), not here. A test file is not an importable decision
# record for the code under test: nothing in the umbrella could ask "is this gate
# deliberately unwired, or did nobody look?" while the answer was only in a test,
# and that question is what separates a licensed silence from an accidental one.
# The numbers are unchanged; this file still owns the RULE they license.
_CORPUS_DENOMINATOR = F.P0_CORPUS_DENOMINATOR
_RTL_DIR_GROUP_MEASUREMENT = F.P0_RTL_DIR_GROUP_MEASUREMENT


def _project_with_rtl(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top(input clk, input rst_n, output reg q);\n"
        "  always @(posedge clk) if (!rst_n) q <= 1'b0; else q <= ~q;\n"
        "endmodule\n")
    return tmp_path


def test_converted_gates_receive_the_rtl_dir_the_umbrella_derived(tmp_path):
    """The two measured conversions get `--rtl-dir`, pointed at the directory
    the umbrella computed — not at the project root."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    for gate in ("sustained_vs_edge_check", "timer_freeze_after_state_check"):
        argv = F._structural_gate_argv(gate, tmp_path, rtl_dir=rtl)
        assert argv[2] == "--rtl-dir"
        assert argv[3] == str(rtl)
        assert str(tmp_path) not in argv[3:4] or rtl != tmp_path


@pytest.mark.parametrize("gate", sorted(F._STRUCTURAL_GATE_ARGV_ADAPTERS))
def test_every_adapter_produces_an_argv_its_gate_actually_accepts(gate, tmp_path):
    """A conversion is only real if the gate PARSES the new argv. This runs the
    gate for real on an empty RTL dir and asserts argument parsing did not
    reject it — the exact failure mode #492 is about, now proven absent for
    every converted gate rather than assumed."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "m.v").write_text("module m(input a); endmodule\n")
    argv = F._structural_gate_argv(gate, tmp_path, rtl_dir=rtl)
    r = _pr.run(argv, cwd=tmp_path, capture_output=True, text=True)
    why = GI.classify_not_invocable(
        r.stdout, r.stderr,
        supplied_flags=[a for a in argv if a.startswith("--")])
    assert why is None, f"{gate} still rejects the umbrella's argv: {why}"



def test_converted_gates_are_no_longer_reported_as_skipped(tmp_path):
    """The conversion half: these two now RUN. If a future edit breaks their
    argv they would silently return to the skip list — this is what notices."""
    proj = _project_with_rtl(tmp_path)
    _passed, _fails, skips, _waivers = F._run_structural_rtl_gates(proj)
    skipped_names = {s.split(" ", 1)[0] for s in skips}
    for gate in F._STRUCTURAL_GATE_ARGV_ADAPTERS:
        assert gate not in skipped_names, (
            f"{gate} is registered as converted but the umbrella still skipped it")



# Gates wanting ONLY `--rtl-dir` — a value the umbrella already derives — plus the
# one wanting `--rtl --strict`. All 15 were re-measured over the 108 tracked RTL
# directories under benchmark-data, on a scratch MIRROR of the corpus (no gate CLI
# was pointed at the tracked tree).
# Two bars must BOTH be cleared: converting must not turn the gate red, and the
# gate must actually EXAMINE something, because a PASS over an empty denominator
# is a false PASS and is worse than the skip it replaces.
#
#   gate                              new FAIL/108   projects w/ denominator>0


def _dangling_symlink_rtl_dir(tmp_path):
    """An RTL directory whose glob yields a path that cannot be read.

    This is not a contrived input: 6 dangling `.v` symlinks exist in this
    repo's own tracked tree (generated netlists under `steps/*/netlist.v`),
    so it is the normal layout of several projects here.
    """
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "real.v").write_text("module m(input clk); endmodule\n")
    (rtl / "netlist.v").symlink_to("/nonexistent/netlist.v")
    assert (rtl / "netlist.v").is_symlink() and not (rtl / "netlist.v").exists()
    return rtl


@pytest.mark.parametrize("gate", sorted(F._STRUCTURAL_GATE_ARGV_ADAPTERS))
def test_unreadable_rtl_file_is_not_reported_as_a_design_failure(gate, tmp_path):
    """A crash is not a verdict. `timer_freeze_after_state_check` read straight
    off the glob, so a dangling symlink raised `FileNotFoundError`; the uncaught
    traceback exits 1, and rc 1 is FAIL. Converting the gate would therefore
    have turned an unreadable file in a user's RTL directory into a FAIL about
    their design — the same false-certificate family as #492 itself, pointed the
    other way. Every converted gate must survive the argument the umbrella now
    supplies."""
    rtl = _dangling_symlink_rtl_dir(tmp_path)
    argv = F._structural_gate_argv(gate, tmp_path, rtl_dir=rtl)
    r = _pr.run(argv, cwd=tmp_path, capture_output=True, text=True)
    assert "Traceback" not in r.stderr, (
        f"{gate} crashed on an unreadable RTL file:\n{r.stderr[-600:]}")
    assert r.returncode != 1, (
        f"{gate} reported FAIL for an unreadable file, not a design defect")


def test_denominator_excludes_files_the_gate_could_not_read(tmp_path):
    """The non-empty-denominator bar is what licenses these conversions, so the
    denominator must count files actually READ. `files_scanned` used to be the
    glob count, computed independently of what was read, which let it include a
    file the gate never opened."""
    import json as _json
    rtl = _dangling_symlink_rtl_dir(tmp_path)
    argv = F._structural_gate_argv("timer_freeze_after_state_check", tmp_path,
                                   rtl_dir=rtl)
    r = _pr.run(argv, cwd=tmp_path, capture_output=True, text=True)
    summary = _json.loads(r.stdout)["summary"]
    assert summary["files_scanned"] == 1, (
        f"denominator counts unread files: {summary}")
    assert summary["files_unreadable"] == 1
    assert any("netlist.v" in p for p in summary["unreadable_files"])


def test_sibling_denominator_also_counts_only_what_it_read(tmp_path):
    """`sustained_vs_edge_check` swallowed the read error and still counted the
    file, so it reported 2 scanned having read 1. One convention per batch."""
    rtl = _dangling_symlink_rtl_dir(tmp_path)
    argv = F._structural_gate_argv("sustained_vs_edge_check", tmp_path,
                                   rtl_dir=rtl)
    r = _pr.run(argv, cwd=tmp_path, capture_output=True, text=True)
    assert "1 files scanned" in r.stdout, (
        f"denominator still counts a file that does not exist: {r.stdout!r}")


# ── examined nothing -> NOT CHECKED, never PASS ──────────────────────────────

def _all_dangling_rtl_dir(tmp_path):
    """A project whose RTL is symlinked in with the target missing.

    REACHABLE, not hypothetical. The umbrella selects an rtl_dir with
    `any(d.glob("*.v"))`, and a dangling symlink SATISFIES that glob — so this
    directory is chosen, handed to the converted gates, and read as nothing.
    6 dangling `.v` symlinks exist in this repo's own tracked tree.
    """
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").symlink_to("/nonexistent/top.v")
    assert any(rtl.glob("*.v")), "fixture must satisfy the umbrella's selection"
    assert not any(p.exists() for p in rtl.glob("*.v"))
    return rtl


@pytest.mark.parametrize("gate", sorted(F._STRUCTURAL_GATE_ARGV_ADAPTERS))
def test_examined_nothing_is_rc2_not_pass(gate, tmp_path):
    """rc 0 over a zero denominator is a PASS certifying a check that looked at
    nothing — strictly worse than the skip it replaces, and a false certificate
    this conversion would INTRODUCE rather than inherit (before it, the gate was
    never invoked at all). rc 2 is this repo's NOT CHECKED / VACUOUS code, and
    it is what `phase1_k5_quality_check` returns in the same situation: one
    convention across the batch, not two."""
    rtl = _all_dangling_rtl_dir(tmp_path)
    argv = F._structural_gate_argv(gate, tmp_path, rtl_dir=rtl)
    r = _pr.run(argv, cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 2, (
        f"{gate} returned rc {r.returncode} having examined nothing; "
        f"stdout={r.stdout[:300]!r}")


@pytest.mark.parametrize("gate", sorted(F._STRUCTURAL_GATE_ARGV_ADAPTERS))
def test_examined_nothing_reads_as_a_genuine_skip_not_a_caller_defect(gate, tmp_path):
    """That rc 2 must land in the INPUT-MISSING bucket, not NOT INVOKED. The
    gate was invoked correctly; it simply had nothing to read. Misfiling it
    would blame the caller for a project-shaped condition."""
    rtl = _all_dangling_rtl_dir(tmp_path)
    argv = F._structural_gate_argv(gate, tmp_path, rtl_dir=rtl)
    r = _pr.run(argv, cwd=tmp_path, capture_output=True, text=True)
    why = GI.classify_not_invocable(
        r.stdout, r.stderr,
        supplied_flags=[a for a in argv if a.startswith("--")])
    assert why is None, f"{gate}'s vacuous rc 2 was misfiled as NOT INVOKED: {why}"


def test_umbrella_records_the_vacuous_project_as_a_skip_not_a_pass(tmp_path):
    """END-TO-END. The umbrella must neither PASS these gates nor blame them."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").symlink_to("/nonexistent/top.v")
    _passed, fails, skips, _waivers = F._run_structural_rtl_gates(tmp_path)
    skip_names = {s.split(" ", 1)[0] for s in skips}
    not_invoked = {s.split(" ", 1)[0] for s in skips
                   if GI.is_not_invocable_entry(s)}
    joined_fails = " ".join(fails)
    for gate in F._STRUCTURAL_GATE_ARGV_ADAPTERS:
        assert gate in skip_names, f"{gate} did not report NOT CHECKED"
        assert gate not in not_invoked, f"{gate} misfiled as a caller defect"
        assert gate not in joined_fails, f"{gate} blamed the design for no input"


@needs_corpus
def test_the_published_denominator_is_the_one_a_reader_reconstructs():
    """The corpus size is the LICENCE for both conversions ("0 FAIL and a
    non-zero denominator on ALL of them"), so it has to be the number an
    independent reviewer gets from the tracked tree — not a near-miss. A
    denominator stated one larger than it is would mean the sweep either
    skipped a directory or double-counted one, and "I measured all of them" is
    exactly the claim a wrong denominator quietly breaks.

    Reconstructed from BOTH halves of the published tree (see the module
    docstring): the cells in `vibeic/benchmark-data` and the design inputs still
    here. Both are keyed benchmark-data-relative, so a tree that carries both
    halves reconstructs to the same set rather than to twice it.
    """
    rtl_dirs = _tracked_rtl_dirs(corpus_root()) | _tracked_rtl_dirs(_INPUT_HALF)
    assert len(rtl_dirs) == _CORPUS_DENOMINATOR, (
        f"corpus moved: {len(rtl_dirs)} rtl/ dirs now, table says "
        f"{_CORPUS_DENOMINATOR} — re-run the measurement before trusting it")
    for gate, (_fails, denom) in _RTL_DIR_GROUP_MEASUREMENT.items():
        assert denom is None or denom <= _CORPUS_DENOMINATOR, (
            f"{gate} claims a denominator above the corpus size")


def test_only_gates_that_cleared_both_bars_were_converted():
    """Pins the conversion RULE, not just its current answer: convert iff the
    gate adds no FAIL over the corpus AND discloses a non-zero denominator on
    every project. Anything else stays disclosed as NOT INVOKED."""
    licensed = {g for g, (fails, denom) in _RTL_DIR_GROUP_MEASUREMENT.items()
                if fails == 0 and denom == _CORPUS_DENOMINATOR}
    assert licensed == set(F._STRUCTURAL_GATE_ARGV_ADAPTERS), (
        "the converted set no longer matches what the measurement licenses")
