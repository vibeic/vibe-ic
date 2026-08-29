"""Step 18's EVIDENCE must not be hostage to a LATER step's verdict.

THE DEFECT, measured on the v1.12.54 tree. Steps 14-21 are driven by ONE
Python function, `step_pnr`, issuing ONE OpenROAD session. The generated
pnr.tcl orders the Step-18 block — insert, detailed_placement, tie-off,
FIRM-lock, check_placement — immediately after `write_def placed.def`, BEFORE
`clock_tree_synthesis` and ~200 lines before `detailed_route`. But the Python
that serialises Step 18's two required_outputs sat at the TAIL of `step_pnr`,
downstream of SIXTEEN early returns. One of them is the ROUTE_NOT_CONVERGED
gate. A route that did not converge therefore discarded the only record of
spares OpenROAD had already placed, tied off and locked, and Step 18 reported
MISSING — which reads as "the work was skipped", a different claim from "the
work happened and was not written down".

Step 18 was uniquely exposed. Every other step in the PnR band keeps a
TCL-WRITTEN DEF that OpenROAD lands whatever the Python later decides
(15 floorplan.def, 17 placed.def, 19 post_cts.def, 20 post_hold.def,
21 routed.def). Step 18's evidence is 100% Python-tail-written, so it had no
anchor at all.

THE ARMS. Every functional test below drives the real `step_pnr` through a
stubbed OpenROAD. The two route arms differ in EXACTLY ONE input — the
DRT-0199 violation count in the canned log. Design, die, util and the
SPARE_* markers are byte-identical between them, so a difference in the
Step-18 record can only come from the route verdict.

    CONTROL   route converges       -> record present   (green both ways)
    DEFECT    route does not        -> record present   (red before the fix,
              converge                                   green after)
    GUARD     OpenROAD dies before  -> record ABSENT,   (green both ways)
              the Step-18 block        step SAYS so

The GUARD arm is the one that stops the fix being satisfied by code that
writes the record unconditionally: committing the record early is only
honest because `_spare_insertion_observed` refuses to serialise the PLAN,
which is pre-run INTENT, on a run that never reached the insertion.
"""
from __future__ import annotations

import importlib
import json
import re

import pytest

mod = importlib.import_module("phase3_one_shot_runner")

_fb = importlib.import_module("test_gap_e2e_die_util_routing_feedback")
_PG_OK = _fb._PG_OK

# What a real OpenROAD run prints once the Step-18 block has executed: the
# spares tied off, FIRM-locked, and check_placement's own verdict. Emitted
# pre-CTS, so it is in the log of ANY run that reached detailed_route at all.
# Copied in shape from a real converged GF180MCU run's openroad.log, which
# carries SPARE_FIRM_LOCKED / SPARE_TIEOFF_NONFATAL / SPARE_CHECK_PLACEMENT_WARN.
_SPARE_EVIDENCE = (
    "SPARE_TIEOFF_CONNECTED 6 of 6\n"
    "SPARE_TIEOFF_DRIVERS 1\n"
    "SPARE_FIRM_LOCKED: 6 instances\n"
    "SPARE_CHECK_PLACEMENT_VIOLATIONS 0\n"
)

_NONCONV = (0, _SPARE_EVIDENCE
            + "[INFO DRT-0199] Number of violations = 40.\n"
            + "[INFO DRT-0199] Number of violations = 45.\n" + _PG_OK, "")
_CONV = (0, _SPARE_EVIDENCE
         + "[INFO DRT-0199] Number of violations = 0.\n" + _PG_OK, "")
# OpenROAD dies in the deck BEFORE the Step-18 fragment: no spare marker of
# any kind, and no route verdict either.
_DIED_EARLY = (1, "[ERROR ODB-0001] cannot read LEF\n", "")


# A REAL liberty on disk, so `_build_spare_cells_plan` resolves a non-empty
# spare mix and the observation gate below has something to be about. The
# shared fixture points `liberty` at /placeholder/, which resolves ZERO spare
# classes — a plan of 0 spares cannot distinguish "insertion observed" from
# "nothing was ever asked for". Names are sky130-shaped because the fixture
# PDK is; nothing in the runner or the gate keys on them.
_LIB_CELLS = ("sky130_fd_sc_hd__inv_1", "sky130_fd_sc_hd__nand2_1",
              "sky130_fd_sc_hd__nor2_1", "sky130_fd_sc_hd__mux2_1",
              "sky130_fd_sc_hd__a21oi_1", "sky130_fd_sc_hd__o21ai_1",
              "sky130_fd_sc_hd__dfxtp_1", "sky130_fd_sc_hd__conb_1")


def _pdk_with_real_liberty(tmp_path):
    lib = tmp_path / "lib" / "sky130_fd_sc_hd__tt.lib"
    lib.parent.mkdir(parents=True, exist_ok=True)
    lib.write_text('library (tt) {\n'
                   + "".join(f'  cell ("{c}") {{\n  }}\n' for c in _LIB_CELLS)
                   + '}\n')
    import dataclasses
    pdk = dataclasses.replace(_fb._sky130_pdk(), liberty=str(lib))
    assert pdk.liberty != _fb._sky130_pdk().liberty   # never a silent no-op
    return pdk


def _drive(tmp_path, monkeypatch, responses, die_um="480x480", top="widget"):
    """`_drive_step_pnr` with ONE faithfulness fix: the real `_docker_exec`
    is handed `log_path=out_dir/'openroad.log'` and writes the session log
    there. The shared fake never did, so every measurement `step_pnr` takes
    off its OWN log file — the tie-off count, and now the insertion — was
    reading an absent file under test. Writing it is strictly closer to the
    tool; nothing here is stubbed that the tool does not do."""
    project = _fb._build_project(tmp_path, top, 300)
    calls = {"n": 0}

    def fake_docker_exec(container, cmd, timeout=None, **kw):
        if "openroad -no_init" in cmd:
            i = calls["n"]
            calls["n"] += 1
            out_dir = mod._pl.pnr_dir(project)
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{top}.def").write_text(
                "VERSION 5.8 ;\nDESIGN x ;\nEND DESIGN\n")
            rc, o, e = responses[min(i, len(responses) - 1)]
            (out_dir / "openroad.log").write_text(o + e)
            return rc, o, e
        return (0, "", "")

    monkeypatch.setattr(mod, "_docker_exec", fake_docker_exec)
    res = mod.step_pnr(project, top, _pdk_with_real_liberty(tmp_path), "iic",
                       die_um, 0.30)
    return res, project


def _record(project):
    return mod._pl.pnr_dir(project) / "spare_cells.json"


class TestStep18EvidenceIsNotHostageToTheRouteVerdict:

    def test_control_converged_route_keeps_the_step18_record(
            self, tmp_path, monkeypatch):
        """CONTROL — green BOTH ways, before and after the fix. Without it the
        fix is satisfied by code that changes every input's answer."""
        res, project = _drive(tmp_path, monkeypatch, [_CONV])
        assert res.status == "PASS", res.detail
        assert _record(project).is_file(), (
            "the converged arm must produce spare_cells.json; if this is red "
            "the fixture is broken, not the flow")
        rec = json.loads(_record(project).read_text())
        assert rec["count"] > 0

    def test_nonconverged_route_still_keeps_the_step18_record(
            self, tmp_path, monkeypatch):
        """THE FIX. Identical run, identical spare markers — only the DRT-0199
        count differs. PRE-FIX this is red with

            AssertionError: STEP18_RECORD_LOST: step_pnr returned
            ROUTE_NOT_CONVERGED and Step 18's record went with it

        because the emit sat past the gate."""
        res, project = _drive(tmp_path, monkeypatch, [_NONCONV])
        assert res.status == "FAIL"
        assert res.extras.get("finding") == "ROUTE_NOT_CONVERGED"
        assert _record(project).is_file(), (
            "STEP18_RECORD_LOST: step_pnr returned ROUTE_NOT_CONVERGED and "
            "Step 18's record went with it — the spares were inserted, tied "
            "off and FIRM-locked ~200 lines before detailed_route ran")
        rec = json.loads(_record(project).read_text())
        assert rec["count"] > 0
        assert rec["insertion_observed"]["observed"] is True
        assert "SPARE_FIRM_LOCKED" in rec["insertion_observed"]["markers"]

    def test_the_insertion_is_ordered_before_the_failure_point(
            self, tmp_path, monkeypatch):
        """The load-bearing half of the claim, read off the pnr.tcl the
        non-converging run itself generated: whatever the router later
        decides, OpenROAD has ALREADY placed, tied off and locked the spares.
        Matches the COMMAND, not a mention of it — `detailed_route` appears in
        prose many times before it is ever invoked.

        The base route is pinned by its own catch variable (`dr_err`), not by
        its argument list. It used to be matched as the literal
        `if {[catch {detailed_route}`, which broke the moment the base route
        gained an argument (`{*}$_vic_drc_opt`, the probed `-output_drc`) —
        the ORDERING this test is about was never affected. `dr_err` names
        this call site and no other."""
        res, project = _drive(tmp_path, monkeypatch, [_NONCONV])
        tcl = (mod._pl.pnr_dir(project) / "pnr.tcl").read_text().splitlines()

        def _line_of(pred):
            for n, ln in enumerate(tcl, 1):
                if pred(ln):
                    return n
            return None

        n_ins = _line_of(lambda l: "Design-for-ECO" in l and "spare" in l)
        n_cts = _line_of(
            lambda l: l.lstrip().startswith("if {[catch {clock_tree_synthesis"))
        n_route = _line_of(
            lambda l: l.lstrip().startswith("if {[catch {detailed_route")
            and "dr_err]" in l)
        assert n_ins and n_cts and n_route, (n_ins, n_cts, n_route)
        assert n_ins < n_cts < n_route, (n_ins, n_cts, n_route)

    def test_control_no_record_when_the_insertion_was_never_observed(
            self, tmp_path, monkeypatch):
        """CONTROL — green BOTH ways, and the one that makes the fix mean
        something. OpenROAD dies before the Step-18 block, so the log carries
        no marker. The spare PLAN is nonetheless sitting in memory, fully
        formed and completely untrue: `spare_plan` is what the runner ASKED
        OpenROAD to insert, never what OpenROAD did. Serialising it here would
        manufacture a well-formed record of work that never happened.

        Without this arm the fix is satisfied by `write the record
        unconditionally`, which passes both route arms and is a fabrication
        engine on every failure path the early commit newly reaches."""
        res, project = _drive(tmp_path, monkeypatch, [_DIED_EARLY])
        assert res.status == "FAIL"
        assert not _record(project).is_file(), (
            "the plan was serialised as a record for a run that never reached "
            "the insertion — that is a fabrication, not a fix")

    def test_a_withheld_record_says_why(self, tmp_path, monkeypatch):
        """DEGRADE LOUDLY. Withholding the record is correct; withholding it
        SILENTLY is the defect wearing the other hat — step 18 would report
        MISSING again with nothing said about why."""
        res, project = _drive(tmp_path, monkeypatch, [_DIED_EARLY])
        assert "SPARE_INSERTION_NOT_OBSERVED" in res.detail, res.detail

    def test_the_failed_run_names_its_record_as_non_signoff(
            self, tmp_path, monkeypatch):
        """The record now exists after a FAILED PnR, which it never did
        before. It attests STEP 18 and nothing else, so the verdict names it
        among the artefacts this run does not vouch for — on a RESUMED run a
        leftover record must never speak for spares the shipped netlist has
        lost. Disclosure only; the verdict is unchanged."""
        res, project = _drive(tmp_path, monkeypatch, [_NONCONV])
        named = (res.extras or {}).get("non_signoff_outputs") or []
        assert any(n.endswith("spare_cells.json") for n in named), named


class TestStep18MarkerVocabularyIsDerivedFromTheTcl:
    """The marker list is a claim about what the TCL emits. A hand-written
    list of "the ways insertion can happen" omits what the tree actually
    does, so both directions are pinned against the builders themselves."""

    def test_the_marker_vocabulary_exists(self):
        """Named first and on its own so the two directional pins below can
        never pass vacuously against an empty tuple."""
        assert getattr(mod, "_STEP18_INSERTION_MARKERS", None), (
            "the runner declares no Step-18 marker vocabulary, so nothing "
            "gates the record on measured evidence")

    def _emitted(self):
        plan = {"count": 2, "instances": [
            {"name": "spare_inverter_0", "type": "inverter",
             "cell": "CELLA", "llx": 10, "lly": 10},
            {"name": "spare_nand2_0", "type": "nand2",
             "cell": "CELLB", "llx": 30, "lly": 10}]}
        tcl = (mod._build_spare_protection_tcl(plan, "/w/pnr")
               + mod._build_spare_postfix_tcl(plan, "TIELO", "LO"))
        return set(re.findall(r"SPARE_[A-Z_]+", tcl))

    def test_every_listed_marker_is_one_the_tcl_can_emit(self):
        emitted = self._emitted()
        unemittable = [m for m in getattr(mod, "_STEP18_INSERTION_MARKERS", ())
                       if m not in emitted]
        assert not unemittable, (
            f"_STEP18_INSERTION_MARKERS names {unemittable}, which the "
            f"Step-18 TCL builders cannot emit — the observation gate would "
            f"be waiting for a string that never arrives")

    def test_every_marker_the_tcl_emits_is_listed(self):
        emitted = self._emitted()
        # SPARE_TIEOFF_* housekeeping lines the fragment prints on paths that
        # ALSO print one of the listed markers are not needed for observation,
        # but a marker in NEITHER set is a hole: a run could reach the block,
        # print only that, and be judged NOT OBSERVED.
        missing = sorted(emitted - set(getattr(mod, "_STEP18_INSERTION_MARKERS", ())))
        assert not missing, (
            f"the Step-18 TCL emits {missing}, which the observation gate "
            f"does not recognise — a run whose only evidence is one of these "
            f"would be read as 'insertion never ran'")

    def test_the_firm_lock_pair_makes_observation_unconditional(self):
        """`catch` around the FIRM-lock prints SPARE_FIRM_LOCKED on success
        and SPARE_FIXED_NONFATAL on failure. Both listed => any run that
        REACHES the block is observed, whatever happens inside it."""
        assert "SPARE_FIRM_LOCKED" in getattr(mod, "_STEP18_INSERTION_MARKERS", ())
        assert "SPARE_FIXED_NONFATAL" in getattr(mod, "_STEP18_INSERTION_MARKERS", ())
        emitted = self._emitted()
        assert {"SPARE_FIRM_LOCKED", "SPARE_FIXED_NONFATAL"} <= emitted


class TestStep18EmitPrecedesEveryRouteOutcomeGate:
    """Structural pin. The functional arms above prove the record survives the
    ONE gate the spm run tripped; this proves it precedes ALL of them, so the
    next gate added below does not silently re-open the hole."""

    def test_the_emit_call_precedes_every_early_return_in_step_pnr(self):
        import ast
        import inspect
        src = inspect.getsource(mod)
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "step_pnr")
        emit = [n.lineno for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "_emit_step18_spare_record"]
        assert emit, "step_pnr no longer calls _emit_step18_spare_record"
        first_emit = min(emit)
        nested = {id(m) for n in ast.walk(fn)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n is not fn
                  for m in ast.walk(n) if isinstance(m, ast.Return)}
        late = [n.lineno for n in ast.walk(fn)
                if isinstance(n, ast.Return) and id(n) not in nested
                and n.lineno > first_emit
                and n.lineno < fn.end_lineno - 40]
        # Every remaining return below the emit is a route/PG verdict about a
        # LATER step; none of them can now discard Step 18's evidence, because
        # the evidence was already committed.
        assert first_emit < min(late), (
            f"the Step-18 emit at line {first_emit} is no longer above the "
            f"early returns at {sorted(late)[:5]}")
        assert len(late) >= 8, (
            f"only {len(late)} early returns below the emit — if the function "
            f"was restructured, re-derive this pin rather than lowering it")
