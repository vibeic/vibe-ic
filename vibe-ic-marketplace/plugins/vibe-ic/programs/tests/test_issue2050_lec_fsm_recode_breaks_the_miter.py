#!/usr/bin/env python3
"""Regression for #2050 — `synth`'s FSM re-encoding makes the LEC recipe build
an INCONSISTENT miter, and the gate then blamed induction depth for it.

MEASURED, opentitan_aes x sky130A, image sha256:06537f7e8d3c, plugin v1.17.72:

  * `synth` runs `fsm`, whose `fsm_recode` pass re-assigns FSM state encodings.
    19 of 19 extracted FSMs were recoded to one-hot; the state registers changed
    BOTH encoding and width (e.g. a 3-bit sparse `...u_prim_alert_sender.state_q`
    became a 7-bit one-hot register).
  * `equiv_make` matches key points BY NAME and has its OWN guard for this: it
    SKIPS a signal whose gold and gate widths differ.  `splitnets -ports`
    DEFEATS that guard — despite the flag name it splits internal signals too
    (internal-only is the default; `-ports` means "and ports as well"), so
    equiv_make no longer sees 3 bits against 7, it sees `state_q[0..2]` on each
    side and matches them POSITIONALLY.  Those pairs are not the same signal.
  * Forcing them equal makes the miter's key-point set inconsistent, and
    `equiv_induct`'s base case — `ez->assume(all unproven key points equal at
    steps 1..k); ez->solve()` — goes UNSAT: `Circuit inherently diverges!`.
    ONE poisoned pair aborts the induction for the WHOLE design: 3242 points
    across every block were left unproven by 3 recoded registers in one alert
    sender.
  * A/B on the SAME prepared design (only the named flag varies):
      splitnets + no encfile  : 4072 points,  676 proven, base case UNSAT at step 2
      no splitnets            : 4012 points, 1483 proven, base case HOLDS
      + `equiv_make -encfile` : 4087 points, 4056 proven / 31 unproven, 1068 s
    and, on a ~50-line design that reproduces the SAME SIGNATURE — a sparse,
    Hamming-separated FSM whose state flop lives in a submodule, so the recoded
    signal is `u_state_regs.u_state_flop.q_o` exactly as in the real design:
      RED   (recipe as shipped): three equiv_induct rungs, byte-identical output,
             all three `Proof for base case failed. Circuit inherently diverges!`
             at step 2 -> 9 points, 2 proven, 7 unproven
      GREEN (`synth -encfile` + `equiv_make -encfile`): "Creating encoder/decoder
             for signal u_state_regs.u_state_flop.q_o." -> 10/10, "Equivalence
             successfully proven!"
  * Adding `-encfile` to synth leaves the netlist BYTE-IDENTICAL (same sha256 on
    opentitan_aes and on fsmtop) — it only records the translation.

Two defects are fixed here:
  (1) build_equiv_script could not consume an encoding translation at all, and
      unconditionally emitted the `splitnets -ports` that defeats equiv_make's
      width guard;
  (2) the gate reported the base-case-UNSAT shape as "a disclosed
      sequential-depth capability gap ... close with sign-off LEC, which handles
      deep sequential induction", and justified it with "a real difference
      produces a counterexample".  SCOPED CLAIM, and the scope is the point: the
      gate also reads non-yosys LEC reports, where a real counterexample count
      CAN arrive and the guard is meaningful.  On the YOSYS path it cannot:
      lec_run.py hardcodes `non_equivalent_points` to 0 (its own comment says "a
      genuine difference surfaces as `unproven`"), and no pass in yosys's
      passes/equiv emits any counterexample phrase.  So on the path this design
      took, the sentence told the reader that 0 counterexamples meant something,
      from a field that could never be anything else.

chip-AGNOSTIC: yosys pass names and log phrases only; no chip/PDK/vendor
literal, and no design name is required by any assertion below.
"""
import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import lec_run                       # noqa: E402


#: WHERE A REAL YOSYS IS, AND WHY THIS IS NOT A SKIP.
#:
#: Four tests in this file drive a REAL yosys, because a recipe asserted only as
#: a STRING cannot show that the SAT actually proves the points -- which is the
#: whole argument of #2050 and must not be downgraded to a text comparison.
#:
#: MEASURED on main 800cecb34 (8HD-8, a bare PATH; the tools live in the pinned
#: image): `test_empty_encoding_table_preserves_scalarized_register_proofs`
#: called `subprocess.run(["yosys", ...])` with nothing resolved and died
#: `FileNotFoundError: [Errno 2] ... 'yosys'` -- a missing INSTALL reported as a
#: claim about the CODE.
#:
#: AND THE ANSWER IS NOT A SKIP. A skip on the measuring host turns a test that
#: CANNOT RUN into a green line, which is the same lie in the other direction;
#: the sibling `test_scalar_data_and_recoded_fsm_real_yosys` did exactly that,
#: and it is why a real #2050 failure sat unseen on main behind a `2 skipped`.
#: So the test RESOLVES yosys the way `lec_run` itself does and measures
#: WHEREVER THE PROGRAM CAN RUN:
#:
#:   1. this filesystem, if `yosys` is on PATH -- which is the case INSIDE the
#:      image, where the plugin's own suite and an in-image flow run live;
#:   2. otherwise the pinned EDA container the flow dispatches into, named by
#:      `lec_run.DEFAULT_CONTAINER` (`_eda_pin.default_container_name()`, so
#:      `VIBEIC_EDA_CONTAINER` is honoured exactly as everywhere else).
#:
#: HOST FIRST is not a preference: it is what makes one test correct in both
#: environments, and it is the order `digital_hardmacro_gen.MagicSite`,
#: `_klayout_launch.find_runner` and `analog_pdk_deck_context.container_reader`
#: already follow.
#:
#: NO SECOND RESOLVER AND NO SECOND EXEC. Every container touch below is
#: `lec_run`'s own: `_container_available`, `_yosys_version`,
#: `_container_file_exists`, and `_docker`, whose first argument IS the
#: host/container switch (`container in ("", "host")` runs here, anything else
#: is a `docker exec`). So the test launches yosys through the same call the
#: program launches it through.
#:
#: AND IF NEITHER ROUTE REACHES IT, THE TEST FAILS -- naming NOT_MEASURED and
#: both routes it tried. A test that cannot measure says so as a failure.
class _YosysSite:
    """The one environment yosys, the scripts and the produced files share."""

    def __init__(self, where, workdir, tried):
        self.where = where          # "host", a container name, or "" for none
        self.dir = workdir
        self.tried = tried

    def require(self):
        assert self.where, (
            "NOT_MEASURED: no reachable yosys, so this test has no opinion and "
            "will not pretend to one. Routes tried, in order:\n  "
            + "\n  ".join(self.tried)
            + "\nRun the suite inside the pinned EDA image, or start that "
              "container on this host (its name comes from "
              "`_eda_pin.default_container_name()`; `VIBEIC_EDA_CONTAINER` "
              "overrides it).")

    def run(self, script_text, name):
        """Run `script_text` as a yosys script and return its output."""
        self.require()
        path = self.dir / (name + ".ys")
        path.write_text(script_text)
        cp = lec_run._docker(
            self.where, "yosys -Q -T -s %s" % shlex.quote(str(path)),
            timeout=900)
        out = lec_run._strip_login_banner(
            (cp.stdout or "") + (cp.stderr or ""))
        (self.dir / (name + ".log")).write_text(out)
        return cp.returncode, out


def _identity_mount_fixture_dirs(container):
    """A fixture directory under each bind mount `container` sees at the SAME
    path as this host (`Source == Destination`), from the container's own mount
    table. `[]` when the table cannot be read -- "could not look" is never
    turned into a guessed path."""
    import _designs_root  # noqa: PLC0415 -- the one reader of the mount table
    return [src / ".vibeic-lec-fixtures"
            for src, dst in _designs_root.container_mounts(container)
            if str(src) == str(Path(dst)) and src.is_dir()]


def _resolve_yosys_site(tmp_path):
    """`lec_run`'s own probes, in `lec_run`'s own order. Never raises."""
    tried = []
    if shutil.which("yosys"):
        return _YosysSite("host", tmp_path, tried)
    tried.append("this filesystem: `shutil.which('yosys')` found nothing on "
                 "PATH")

    container = lec_run.DEFAULT_CONTAINER
    if not lec_run._container_available(container):
        tried.append(f"container {container!r} (lec_run.DEFAULT_CONTAINER): "
                     f"`lec_run._container_available` could not run in it")
        return _YosysSite("", None, tried)
    version = lec_run._yosys_version(container)
    if not version:
        tried.append(f"container {container!r}: reachable, but "
                     f"`lec_run._yosys_version` got no version back")
        return _YosysSite("", None, tried)

    # The tool is reachable; the FILES have to be too. A container sees the
    # host paths it was started with, and a pytest `tmp_path` under /tmp is
    # usually not one of them -- so ASK, with lec_run's own probe, rather than
    # assume a mount table. The candidates are this run's tmp_path (correct in
    # the image, where both sides are one filesystem), then every directory
    # the container itself says it binds AT THE SAME PATH (`_designs_root`'s
    # reading of its own mount table), then the account home.
    #
    # THE MOUNT TABLE IS STATED, NOT ASSUMED. MEASURED on 8HD-6 (main
    # 539cd739d): pytest's basetemp is /tmp/pytest-of-<user>/..., the shared
    # `vibeic-eda` container binds only `~/vibeic-designs` (at the identical
    # path) and not ~/.cache, so all four real-yosys tests failed NOT_MEASURED
    # on a host whose container HAD yosys and HAD a shared path -- one this
    # probe never asked about. A mount whose container path differs is not a
    # candidate: the yosys scripts name host paths verbatim.
    for cand in (tmp_path, *_identity_mount_fixture_dirs(container),
                 Path.home() / ".cache" / "vibeic-lec-fixtures"):
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / f".visible-{os.getpid()}"
            probe.write_text("probe")
        except OSError as exc:
            tried.append(f"{cand}: not writable here ({exc})")
            continue
        seen = lec_run._container_file_exists(container, str(probe))
        probe.unlink(missing_ok=True)
        if seen:
            work = Path(tempfile.mkdtemp(dir=str(cand), prefix="issue2050-"))
            return _YosysSite(container, work, tried)
        tried.append(f"container {container!r} has yosys {version!r} but "
                     f"cannot see {cand} -- no shared path for the fixtures")
    return _YosysSite("", None, tried)


@pytest.fixture
def yosys(tmp_path):
    """The resolved site, with any directory this fixture created removed."""
    site = _resolve_yosys_site(tmp_path)
    try:
        yield site
    finally:
        if site.dir is not None and site.dir != tmp_path:
            shutil.rmtree(site.dir, ignore_errors=True)
            try:                    # the fixture parent, only if now empty
                site.dir.parent.rmdir()
            except OSError:
                pass


_GOLD = ["/g/a.sv", "/g/b.sv"]
_GATE = "/n/netlist.v"


def _script(**kw):
    return lec_run.build_equiv_script(
        _GOLD, _GATE, "chip_top", None, gate_is_generic=True, **kw)


# ---------------------------------------------------------------------------
# (1) the recipe generator
# ---------------------------------------------------------------------------
def test_without_an_encfile_the_script_is_unchanged():
    """NO-LEAK: every caller that does not supply an encfile keeps the exact
    pre-change recipe, so no design's verdict can move."""
    s = _script()
    assert s.count("splitnets -ports\n") == 2, s
    assert "equiv_make gold gate equiv\n" in s
    assert "-encfile" not in s


def test_an_encfile_is_passed_to_equiv_make():
    s = _script(fsm_encfile="/r/fsm_encoding.enc")
    assert "equiv_make -encfile /r/fsm_encoding.enc gold gate equiv\n" in s


def test_an_encfile_suppresses_the_splitnets_that_defeats_the_width_guard():
    """`-encfile` is keyed on the WHOLE signal name (`.fsm <module> <signal>`),
    which a bit-blasted design no longer has; and it is `splitnets` that turns
    a width mismatch equiv_make would SKIP into positional bit matches."""
    s = _script(fsm_encfile="/r/fsm_encoding.enc")
    assert "splitnets" not in s, s


def test_the_encfile_changes_nothing_else_in_the_recipe():
    """MEMBERSHIP, not counts: the two scripts must differ ONLY by the two
    splitnets lines and the equiv_make flag."""
    a = _script().splitlines()
    b = _script(fsm_encfile="/r/f.enc").splitlines()
    removed = [l for l in a if l not in b]
    added = [l for l in b if l not in a]
    assert removed == ["splitnets -ports", "splitnets -ports",
                       "equiv_make gold gate equiv"], removed
    assert added == ["equiv_make -encfile /r/f.enc gold gate equiv"], added


# ---------------------------------------------------------------------------
# (2) the classifier — the two flat walls are not the same wall
# ---------------------------------------------------------------------------
# The AES shape.  Note that equiv_induct prints BOTH phrases on this shape: it
# returns straight after the base case, so `Proved 0 previously unproven` is
# there too.  Only the base-case line separates the two walls, which is why
# `induction_wall_kind` must check it FIRST.
_BASE_CASE_UNSAT = """\
Found 3396 unproven $equiv cells in module equiv:
  Proving existence of base case for step 1. (2962863 clauses over 1130042 variables)
  Proving induction step 1. (6000231 clauses over 2283008 variables)
  Proof for induction step failed. Extending to next time step.
  Proving existence of base case for step 2. (6000232 clauses over 2283008 variables)
  Proof for base case failed. Circuit inherently diverges!
Proved 0 previously unproven $equiv cells.
Found 4072 $equiv cells in equiv:
  Of those cells 830 are proven and 3242 are unproven.
"""

# A real depth wall: the base case HELD, the induction step did not close.
_DEPTH_WALL = """\
Found 909 unproven $equiv cells in module equiv:
  Proving existence of base case for step 1. (1263 clauses over 487 variables)
  Proving induction step 1. (2765 clauses over 1048 variables)
  Proof for induction step failed. Extending to next time step.
Proved 0 previously unproven $equiv cells.
Found 7259 $equiv cells in equiv:
  Of those cells 6350 are proven and 909 are unproven.
"""

# The REAL log of that ~50-line reproducer's RED arm, verbatim (862 clauses, not 6M) —
# a scale model of the design log, kept as evidence that the classifier is reading the
# shape yosys actually emits and not a shape I invented.
_REPRO_RED = """\
21. Executing EQUIV_INDUCT pass.
Found 7 unproven $equiv cells in module equiv:
  Proving existence of base case for step 1. (862 clauses over 322 variables)
  Proving induction step 1. (1883 clauses over 693 variables)
  Proof for induction step failed. Extending to next time step.
  Proving existence of base case for step 2. (1884 clauses over 693 variables)
  Proof for base case failed. Circuit inherently diverges!
Proved 0 previously unproven $equiv cells.
Found 9 $equiv cells in equiv:
  Of those cells 2 are proven and 7 are unproven.
"""

_PROVEN = """\
Found 65 $equiv cells in equiv:
  Of those cells 65 are proven and 0 are unproven.
  Equivalence successfully proven!
"""


def test_base_case_unsat_is_not_classified_as_a_depth_wall():
    assert lec_run.induction_wall_kind(_BASE_CASE_UNSAT) == "miter_inconsistent"


def test_a_real_depth_wall_is_still_a_depth_wall():
    assert lec_run.induction_wall_kind(_DEPTH_WALL) == "induction_depth"


def test_the_reproducers_real_log_classifies_as_miter_inconsistent():
    """Not a hand-written fixture: this is the verbatim equiv_induct output of the
    ~50-line reproducer's RED arm. It must land on the same side as the design log."""
    assert lec_run.induction_wall_kind(_REPRO_RED) == "miter_inconsistent"
    r = lec_run.build_report(
        lec_run.parse_equiv_output(_REPRO_RED), "sfsm3", "netlist.v", None)
    assert r["verdict"] == "INCONCLUSIVE"
    assert r["induction_wall_kind"] == "miter_inconsistent"
    assert r["unproven_points"] == 7


def test_a_clean_proof_has_no_wall():
    assert lec_run.induction_wall_kind(_PROVEN) == ""
    assert lec_run.induction_wall_kind("") == ""


def test_the_kind_reaches_the_report():
    for raw, want in ((_BASE_CASE_UNSAT, "miter_inconsistent"),
                      (_DEPTH_WALL, "induction_depth"),
                      (_PROVEN, "")):
        r = lec_run.build_report(
            lec_run.parse_equiv_output(raw), "chip_top", "netlist.v", None)
        assert r["induction_wall_kind"] == want, raw[:60]


# ---------------------------------------------------------------------------
# (3) the gate — name the right cause, and stop prescribing the one remedy
#     that provably cannot work
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# (4) producer <-> consumer contract
#
# The fix is a CONJUNCTION: synth must WRITE the translation and LEC must READ
# it.  A missing file is not an error anywhere — it silently restores the old,
# name-positional matching — so the two halves have to be pinned to each other
# by a test, not by a comment.
# ---------------------------------------------------------------------------
def test_the_resolver_finds_the_file_the_synth_step_writes(tmp_path):
    net = tmp_path / "netlist.v"
    net.write_text("module t(); endmodule\n")
    assert lec_run.fsm_encfile_beside_netlist(str(net)) is None
    enc = tmp_path / lec_run.FSM_ENCFILE_NAME
    enc.write_text(".fsm t state_q\n.map 010 ---1\n")
    assert lec_run.fsm_encfile_beside_netlist(str(net)) == str(enc.resolve())


def test_the_resolver_never_guesses(tmp_path):
    assert lec_run.fsm_encfile_beside_netlist("") is None
    assert lec_run.fsm_encfile_beside_netlist(
        str(tmp_path / "does_not_exist.v")) is None




def test_empty_synth_map_preserves_scalar_register_alignment(tmp_path):
    net = tmp_path / "netlist.v"
    net.write_text("module t(); endmodule\n")
    (tmp_path / lec_run.FSM_ENCFILE_NAME).write_text("")
    enc = lec_run.fsm_encfile_beside_netlist(str(net))
    assert enc is None, "no FSM was recoded, so bit matching must remain enabled"
    script = lec_run.build_equiv_script(
        ["rtl.v"], str(net), "t", None, fsm_encfile=enc)
    assert script.count("splitnets -ports") == 2


def _functions_owning(src: str, marker: str) -> set:
    """The INNERMOST function that owns each occurrence of `marker`, by NAME.

    A call-site's identity is the function it lives in, not the line it sits
    on: a line number moves with every edit above it, while the owning
    function is the thing a reader means by "the other call-site". Parsed
    with `ast` and located by offset, so a nested helper that carried the
    marker would be named as itself rather than credited to its parent.
    """
    lines = src.splitlines(keepends=True)
    starts, acc = [], 0
    for ln in lines:
        starts.append(acc)
        acc += len(ln)

    def _line_of(offset: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    tree = ast.parse(src)
    funcs = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and getattr(n, "end_lineno", None)]
    owners = set()
    for m in re.finditer(re.escape(marker), src):
        line = _line_of(m.start())
        enclosing = [n for n in funcs if n.lineno <= line <= n.end_lineno]
        if enclosing:
            owners.add(max(enclosing, key=lambda n: n.lineno).name)
    return owners


def test_both_phase2_synth_call_sites_write_the_encfile():
    """The netlist that step-13 compares can come from either synth call-site
    (built-in read_verilog, or the read_slang/sv2v fallback that a modern-SV
    design such as an OpenTitan-class IP takes).  BOTH must record the
    translation, or the LEC fix is live on only one of them.  Read as TEXT:
    importing design_one_shot_runner drags in the whole runner."""
    src = (_PROGRAMS / "design_one_shot_runner.py").read_text()
    # THE MEMBER SET, not its size. `len(sites) == 2` and `src.count(...) == 2`
    # were pins on a live population's SIZE with nothing pinning its MEMBERS:
    # one call-site leaving and one arriving in the same batch leaves both
    # numbers at 2 while the population has become a different set, and the pin
    # would never say so (`population_pin_without_its_member_set` names this
    # module and this assertion). The identities are the FUNCTIONS that own the
    # call-sites, compared as a set in BOTH directions; the count survives only
    # as `len()` of that same set, never as a typed literal.
    _SYNTH_CALL_SITES = {"_phase2_sv_synth_fallback", "step_yosys_synth"}
    sites = _functions_owning(src, "synth -top {synth_top} -flatten")
    assert sites == _SYNTH_CALL_SITES, {
        "missing": sorted(_SYNTH_CALL_SITES - sites),
        "unexpected": sorted(sites - _SYNTH_CALL_SITES)}
    # The CODE form (the f-string interpolation `-encfile {`), never the bare
    # word: the surrounding comments name the flag too, and matching those
    # would pass on a file where neither call-site actually carries it.
    enc = _functions_owning(src, "-encfile {")
    assert enc == _SYNTH_CALL_SITES, {
        "missing": sorted(_SYNTH_CALL_SITES - enc),
        "unexpected": sorted(enc - _SYNTH_CALL_SITES)}
    # BOTH halves of the conjunction over the SAME set: every synth call-site
    # is an encfile call-site and back again, so a third call-site that
    # forgot the flag cannot hide behind a second one that carries it twice.
    assert enc == sites, {"synth_only": sorted(sites - enc),
                          "encfile_only": sorted(enc - sites)}
    assert len(sites) == len(_SYNTH_CALL_SITES)
    assert "from lec_run import FSM_ENCFILE_NAME" in src
    # AND THE OTHER HALF OF THAT IMPORT MUST EXIST. Caught for real while
    # writing this: restoring lec_run.py from a stale snapshot during a
    # negative-control swap dropped the constant and the resolver while
    # leaving the producer's `from lec_run import FSM_ENCFILE_NAME` in place —
    # a shipped ImportError in the synth step that every OTHER test in this
    # file still passed, because they all read the producer as TEXT and never
    # execute the import. A conjunction needs both halves asserted.
    assert isinstance(getattr(lec_run, "FSM_ENCFILE_NAME", None), str)
    assert callable(getattr(lec_run, "fsm_encfile_beside_netlist", None))
    assert src.count('"fsm_encoding.enc"') == 0, (
        "the producer must not re-type the filename — one definition, in "
        "lec_run.FSM_ENCFILE_NAME, is what keeps a rename from silently "
        "disabling the fix")


def test_the_recipe_funnel_is_actually_wired_to_the_resolver():
    """The generator can take an encfile and the synth step can write one, and the fix
    still does NOTHING unless the two are joined — `_make_script`, the one funnel every
    recipe in lec_run.main() goes through, has to pass the resolver's answer.

    Parsed with `ast`, not grepped: a comment mentioning `fsm_encfile=` would satisfy a
    grep and wire nothing, and this is the third half of a conjunction whose other two
    halves each have their own test above."""
    import ast
    tree = ast.parse((_PROGRAMS / "lec_run.py").read_text())

    funnels = [n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_make_script"]
    assert len(funnels) == 1, [n.lineno for n in funnels]

    calls = [n for n in ast.walk(funnels[0])
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "build_equiv_script"]
    assert len(calls) == 1, len(calls)

    kw = {k.arg: k.value for k in calls[0].keywords if k.arg}
    assert "fsm_encfile" in kw, sorted(kw)
    value = kw["fsm_encfile"]
    assert isinstance(value, ast.Call) and isinstance(value.func, ast.Name), \
        ast.dump(value)
    assert value.func.id == "fsm_encfile_beside_netlist", value.func.id
    # …and it must be asked about the netlist under test, not about something else.
    assert len(value.args) == 1 and isinstance(value.args[0], ast.Name), \
        ast.dump(value)
    assert value.args[0].id == "gate_abs", value.args[0].id


def test_encoding_names_preserve_all_hierarchical_state_words(tmp_path):
    enc = tmp_path / "enc"
    enc.write_text(".fsm top state_q\n.map 00 --1\n"
                   ".fsm child pipe.state_q\n.map 01 -1-\n")
    names = lec_run.fsm_signal_names(str(enc))
    assert names == ["pipe.state_q", "state_q"]
    script = _script(fsm_encfile=str(enc), fsm_preserve_signals=names)
    assert script.count("w:state_q %d w:*.state_q %d") == 2
    assert script.count("w:pipe.state_q %d w:*.pipe.state_q %d") == 2
    assert script.count("select *\n") == 2


@pytest.mark.parametrize("content", [
    ".fsm t state[0]\n.map 00 --1\n", ".map 00 --1\n",
    ".fsm t state\n.unrecognized command\n",
])
def test_unknown_encoding_selection_retains_width_guard(tmp_path, content):
    enc = tmp_path / "enc"
    enc.write_text(content)
    names = lec_run.fsm_signal_names(str(enc))
    assert names is None
    assert "splitnets" not in _script(
        fsm_encfile=str(enc), fsm_preserve_signals=names)


def test_empty_encoding_is_observed_not_assumed(tmp_path):
    enc = tmp_path / "enc"
    assert lec_run.fsm_signal_names(str(enc)) is None
    enc.write_text("# no FSM was extracted\n")
    assert lec_run.fsm_signal_names(str(enc)) == []
    assert _script(fsm_encfile=str(enc), fsm_preserve_signals=[]).count(
        "splitnets -ports w:*\n") == 2


@pytest.mark.parametrize("broken_reset", [False, True])
def test_scalar_data_and_recoded_fsm_real_yosys(yosys, broken_reset):
    """A real scalarized synthesis DUT, its full state map, and reset mutation.

    Candidate must recover data anchors without pairing binary FSM bits with
    one-hot bits. The reset mutant must remain unproven on the same recipe.
    """
    yosys.require()
    tmp_path = yosys.dir
    rtl = """module toy(input clk, input rst_n, input go, input [3:0] d,
                       output [3:0] q);
    reg [1:0] state;
    (* keep *) reg [3:0] data_q;
    always @(posedge clk) begin
      if (!rst_n) begin state <= 0; data_q <= 0; end
      else begin
        case (state)
          0: if (go) state <= 1;
          1: state <= 2;
          2: state <= 3;
          3: state <= 0;
        endcase
        if (state == 1) data_q <= d;
      end
    end
    assign q = data_q ^ {4{state == 2}};
    endmodule
    """
    gold = tmp_path / "gold.v"
    gate_rtl = tmp_path / "gate_rtl.v"
    gate = tmp_path / "gate.v"
    enc = tmp_path / "enc"
    wrapper = ("module testtop(input clk, input rst_n, input go, input [3:0] d, "
               "output [3:0] q); toy inner(clk, rst_n, go, d, q); endmodule\n")
    gold.write_text(rtl + wrapper)
    gate_rtl.write_text(rtl.replace("if (!rst_n)", "if (rst_n)")
                        if broken_reset else rtl)

    def run(script, name):
        rc, out = yosys.run(script, name)
        assert rc == 0, out[-1500:]
        return out

    run(f"read_verilog {gate_rtl}\nsynth -top toy -encfile {enc}\n"
        f"splitnets\nwrite_verilog -noexpr {gate}\n", "synth")
    gate.write_text(gate.read_text() + wrapper)
    names = lec_run.fsm_signal_names(str(enc))
    assert names == ["state"], enc.read_text()
    # THE LADDER MUST CONTAIN THE PROVER THIS TEST'S ASSERTION NEEDS.
    #
    # `ladder_rungs=2` emits `LEC_LADDER`'s first two rungs — `equiv_simple
    # -short` and `equiv_simple` — and NOTHING ELSE; induction is rungs 3, 4
    # and 5. But `data_q` is a register whose ENABLE is the FSM state
    # (`if (state == 1)`) and whose output is XORed with another state decode,
    # so proving it equal across a re-encoded state is a SEQUENTIAL obligation.
    # Asserting `equivalent and unproven == 0` while truncating the ladder below
    # every sequential prover asked the recipe for a proof the recipe had not
    # been told to attempt.
    #
    # MEASURED in the pinned image (sha256:89a8fd7295…, yosys 0.68+), this
    # fixture, sweeping only this number:
    #     rungs=2  (0 induct)  13/17 proven, 4 unproven  -> equivalent False
    #     rungs=3  (1 induct)  17/17 proven, 0 unproven  -> equivalent True
    #     rungs=4  (2 induct)  17/17                     -> True
    #     rungs=5  (3 induct)  17/17                     -> True
    # and the 4 unproven at rungs=2 are exactly `inner.data_q[0..3]` — the data
    # register, never the FSM state the #2050 repair anchors, which is proven in
    # both arms. So the recipe under test was working and the FIXTURE was short.
    # `ladder_rungs` is #2194's per-rung RESOURCE knob, not a soundness claim.
    #
    # THE ASSERTIONS BELOW ARE UNCHANGED, and this is not a softening: it makes
    # the recipe do MORE work, and the mutation arm still discriminates at this
    # depth — the broken-reset mutant stays 16/17 with 1 unproven at rungs 3 AND
    # 5, so induction does not launder it.
    kwargs = dict(gold_files=[str(gold)], gate_netlist=str(gate), top="testtop",
                  liberty=None, gate_is_generic=True, fsm_encfile=str(enc),
                  ladder_rungs=3)
    before = run(lec_run.build_equiv_script(**kwargs), "baseline")
    flat_enc = tmp_path / "flat.enc"
    flat_enc.write_text(enc.read_text().replace(".fsm toy state", ".fsm toy inner.state"))
    import hashlib
    width = len(next(line.split()[2] for line in enc.read_text().splitlines()
                     if line.startswith(".map ")))
    restore = {"encoding_path": str(flat_enc),
               "encoding_sha256": hashlib.sha256(flat_enc.read_bytes()).hexdigest(),
               "aliases": {"inner.state": [f"inner.state[{i}]" for i in range(width)]}}
    after = run(lec_run.build_equiv_script(
        **kwargs, fsm_preserve_signals=names, scan_fsm_restore=restore), "candidate")
    b = lec_run.parse_equiv_output(before)
    c = lec_run.parse_equiv_output(after)
    assert c["total"] > b["total"], (b, c)
    assert "Presumably equivalent wires: inner.state[" not in after
    assert "Presumably equivalent wires: inner.data_q[" in after
    if broken_reset:
        assert not c["equivalent"] and c["unproven"] > 0, c
    else:
        assert c["equivalent"] and c["unproven"] == 0, c


def test_scan_mapping_follows_only_an_identified_flop_output(tmp_path):
    enc = tmp_path / "enc"
    enc.write_text(".fsm top state\n.map 0 -1\n.map 1 1-\n")
    pre = tmp_path / "pre.v"
    pre.write_text("module top();\n"
                   " FF f0 (.CK(clk), .D(d), .Q(state[0]));\n"
                   " FF f1 (.CK(clk), .D(d), .Q(state[1]));\nendmodule\n")
    gate = tmp_path / "scan.v"
    gate.write_text("module top();\n"
                    " wire \\core.state[0] ;\n wire \\scan_tail ;\n"
                    " FF \\core.f0 (.CK(clk), .D(muxed), .Q(\\core.state[0] ));\n"
                    " FF \\core.f1 (.CK(clk), .D(muxed), .Q(\\scan_tail ));\n"
                    "endmodule\n")
    lib = ('cell(FF) { pin(D) { direction : input; } '
           'pin(Q) { direction : output; function : "IQ"; } }')
    args = dict(encfile=str(enc), gate_netlist=str(gate), top="top",
                scan_mode={"internal_prefix": "core"}, pre_scan_netlist=str(pre),
                liberty_text=lib, dff_cells=["FF"])
    found = lec_run.scan_fsm_mapping(**args)
    assert found is not None
    assert found["aliases"] == {"_LECWRAP.core.state": [
        "_LECWRAP.core.state[0]", "_LECWRAP.scan_tail"]}
    assert ".fsm top _LECWRAP.core.state\n" in found["encoding_text"]
    # Input muxes must never become a claimed state alias.
    assert lec_run.scan_fsm_mapping(**dict(args, liberty_text=lib.replace(
        "direction : output", "direction : input"))) is None
    assert lec_run.scan_fsm_mapping(**dict(args, dff_cells=[])) is None
    assert lec_run.scan_fsm_mapping(**dict(args, scan_mode={})) is None


def test_no_test_here_can_excuse_itself_from_measuring():
    """THE LINE, asserted over this file's OWN source as CODE.

    Three properties, and each one is a way this file has already gone wrong:

      (1) NO BARE TOOL LAUNCH. A test that shells out to a tool it never
          resolved reports a missing INSTALL as a failing ASSERTION -- a claim
          about the code that the run never made. That is how
          `test_empty_encoding_table_preserves_scalarized_register_proofs` was
          red on main 800cecb34.
      (2) NO `pytest.skip`, ANYWHERE, IN ANY SPELLING. Not a disciplined one,
          not a tool guard, not "just while the tool is missing". A skip on the
          measuring host turns a test that CANNOT RUN into a green line, and a
          green line is what a reader counts. This file's own history is the
          argument: `test_scalar_data_and_recoded_fsm_real_yosys` skipped on
          every bare-PATH host, and a REAL #2050 failure sat behind that
          `2 skipped` for as long as nobody ran the suite in the image.
      (3) NO SECOND RESOLVER. `lec_run.DEFAULT_CONTAINER` and `lec_run._docker`
          are how the PROGRAM finds and launches yosys; a test that grew its own
          copy would be free to disagree with the program about where the tool
          is, which is the class `digital_hardmacro_gen.MagicSite` was written
          to close.

    The only correct answer when the tool cannot be reached is the one
    `_YosysSite.require` gives: FAIL, naming NOT_MEASURED and every route tried.
    """
    src = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    bare = sorted({n.lineno for n in ast.walk(tree)
                   if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute)
                   and n.func.attr in ("run", "Popen", "check_output", "call")
                   for a in ast.walk(n)
                   if isinstance(a, ast.Constant) and a.value == "yosys"})
    assert not bare, (
        f"line(s) {bare} launch a literal `yosys` without resolving it; on a "
        f"host with a bare PATH that is a FileNotFoundError wearing an "
        f"assertion's clothes. Go through the `yosys` fixture")

    skips = sorted({n.lineno for n in ast.walk(tree)
                    if isinstance(n, ast.Call)
                    and ((isinstance(n.func, ast.Attribute)
                          and n.func.attr in ("skip", "importorskip", "xfail"))
                         or (isinstance(n.func, ast.Name)
                             and n.func.id in ("skip", "xfail")))})
    assert not skips, (
        f"line(s) {skips} skip. Nothing in this file may: a skip on the "
        f"measuring host is a test that did not run, counted as one that "
        f"passed. If the tool is unreachable, FAIL and say so")
    assert not [n for n in ast.walk(tree)
                if isinstance(n, ast.Attribute) and n.attr == "skipif"], (
        "a `skipif` marker appeared; same rule, same reason")

    # (3) the resolver is lec_run's, by name, at the one site that resolves.
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_resolve_yosys_site")
    borrowed = {a.attr for a in ast.walk(fn) if isinstance(a, ast.Attribute)}
    for owed in ("DEFAULT_CONTAINER", "_container_available",
                 "_yosys_version", "_container_file_exists"):
        assert owed in borrowed, (
            f"`_resolve_yosys_site` no longer consults `lec_run.{owed}` — the "
            f"test would be resolving yosys somewhere the program does not")
    launch = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "run" and any(
                      isinstance(a, ast.Attribute) and a.attr == "_docker"
                      for a in ast.walk(n)))
    assert launch is not None


# ---------------------------------------------------------------------------
# (5) #2050 FAMILY, SECOND INSTANCE — "induction did not converge" was said
#     about logs in which induction never ran.
#
# Sections (2) and (3) above separated the TWO flat induction walls and stopped
# the gate blaming depth for an inconsistent miter. The same sentence was still
# being said about a THIRD shape that is not a wall at all: a ladder TRUNCATED
# below its induction rungs. `equiv_simple` prints the very same
# `Proved 0 previously unproven $equiv cells.` line `equiv_induct` does, and
# the classifiers searched the whole log for it.
#
# MEASURED in the pinned image, this file's own reproducer at ladder_rungs=2
# (LEC_LADDER rungs 1-2, zero induction commands emitted): the log contains the
# string "induct" ZERO times, and the record read
#     induction_wall_kind: "induction_depth"
#     "equiv_induct did NOT converge (equiv_induct proved 0 previously-unproven
#      cells across the escalating -seq sweep) ... a disclosed sequential-depth
#      capability gap ... Close the remainder with sign-off LEC, which handles
#      deep sequential induction."
# The remedy was one more rung, for free: 13/17 -> 17/17, equivalent.
# ---------------------------------------------------------------------------

#: A REAL `equiv_simple`-only log, lines taken verbatim from the measured run.
_LADDER_TRUNCATED = """\
19. Executing EQUIV_SIMPLE pass.
Found 17 unproven $equiv cells (16 groups) in equiv:
  Trying to prove $equiv for \\inner.d[2]:ezsat
 success!
Proved 13 previously unproven $equiv cells.

20. Executing EQUIV_SIMPLE pass.
Found 4 unproven $equiv cells (4 groups) in equiv:
  Trying to prove $equiv for \\inner.data_q[0]:ezsat
ezsat
 failed.
Proved 0 previously unproven $equiv cells.

21. Executing EQUIV_STATUS pass.
Found 17 $equiv cells in equiv:
  Of those cells 13 are proven and 4 are unproven.
Found a total of 4 unproven $equiv cells.
"""


def test_a_ladder_that_never_reached_induction_is_not_an_induction_wall():
    """The heart of it: no induction pass, so no depth opinion."""
    assert not lec_run.ladder_reached_induction(_LADDER_TRUNCATED)
    assert lec_run.induction_wall_kind(_LADDER_TRUNCATED) == \
        "ladder_below_induction"
    noconv, _ = lec_run.induction_did_not_converge(_LADDER_TRUNCATED)
    assert noconv is False, (
        "`equiv_simple`'s own `Proved 0` line was read as an equiv_induct "
        "result; that is the whole defect")
    fired, ev = lec_run.ladder_stopped_below_induction(_LADDER_TRUNCATED)
    assert fired and "STOPPED BELOW" in ev


def test_an_excerpted_induction_log_is_still_an_induction_wall():
    """REVERT-PROOF FOR THE WIDENING, and the reason it had to be wide.

    `_DEPTH_WALL` is this file's oldest depth fixture and it is an EXCERPT: it
    begins BELOW `Executing EQUIV_INDUCT pass.` and carries only the lines the
    pass prints while working. Keying "did induction run?" on the header alone
    would reclassify it — and every real log that has been tailed or clipped —
    as a truncated ladder. `equiv_induct` is the only pass that prints either of
    those lines, VERIFIED against an equiv_simple-only log that contains neither.
    """
    assert lec_run.ladder_reached_induction(_DEPTH_WALL)
    assert lec_run.induction_wall_kind(_DEPTH_WALL) == "induction_depth"
    assert "Executing EQUIV_INDUCT" not in _DEPTH_WALL, (
        "the fixture gained the header, so this test would pass on the narrow "
        "marker too and stops being a control")


def test_the_truncated_ladder_is_INCONCLUSIVE_and_names_the_real_remedy():
    """It must not become a false NOT_EQUIVALENT — the design IS equivalent,
    and one more rung proves it — and it must stop selling a commercial tool
    for work this recipe has not been asked to do."""
    r = lec_run.build_report(
        lec_run.parse_equiv_output(_LADDER_TRUNCATED), "toy", "netlist.v", None)
    assert r["verdict"] == "INCONCLUSIVE", r
    assert r["equivalent"] is False
    assert r["induction_wall_kind"] == "ladder_below_induction"
    why = r["verdict_explanation"]
    assert "STOPPED BELOW ITS INDUCTION RUNGS" in why, why
    assert "equiv_induct -seq 4/16/64" in why, (
        "the remedy must name the rungs that would close it", why)
    assert "did NOT converge" not in why, (
        "still claiming a convergence result from a run with no induction", why)
    assert "deep sequential induction" not in why, (
        "still prescribing sign-off LEC for a ladder that stopped short", why)


def test_a_counterexample_still_FAILS_even_on_a_truncated_ladder():
    """§4.05 NO-LEAK CONTROL. The new branch softens a verdict, so the thing to
    prove is what it CANNOT soften: a real, witnessed difference."""
    raw = _LADDER_TRUNCATED + "Found counterexample for $equiv cell.\n"
    r = lec_run.build_report(
        lec_run.parse_equiv_output(raw), "toy", "netlist.v", None)
    assert r["verdict"] == "FAIL", r
    assert r["equivalent"] is False


def test_a_stateless_miter_still_FAILS_on_a_truncated_ladder():
    """The OTHER no-leak control, and the one the `miter_is_stateless` guard
    was added for: on a combinational miter induction could never have helped,
    so a truncated ladder is not an excuse either."""
    # `stat`'s real column order is COUNT then TYPE; the shape is the one
    # `test_lec_bounded_proof._STAT_COMB` already uses, so the two fixtures
    # cannot drift apart about what yosys prints.
    raw = ("\n=== equiv ===\n\n"
           "       25   $_NAND_\n"
           "       11   $_NOT_\n"
           "       36   $equiv\n\n"
           + _LADDER_TRUNCATED)
    stateless, _ = lec_run.miter_is_stateless(raw)
    if not stateless:                       # the fixture must earn the control
        raise AssertionError(
            "fixture no longer reads as a stateless miter, so this control "
            "proves nothing — repair the `stat` block")
    r = lec_run.build_report(
        lec_run.parse_equiv_output(raw), "toy", "netlist.v", None)
    assert r["verdict"] == "FAIL", r
