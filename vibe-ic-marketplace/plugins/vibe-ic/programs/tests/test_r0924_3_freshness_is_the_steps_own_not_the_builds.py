#!/usr/bin/env python3
"""R-0924-3 — a cached step is fresh when THE STEP has not changed.

THE MEASURED DEFECT (spm run23, lane icspm5, 2026-09-23):

    [synth] the cached synth artefact was produced by a DIFFERENT build
    (plugin 1.23.70 -> 1.23.93; recipe e8fb29723876 -> cf8b2cd4ba76)
    — re-running

`--force-step gds` on a FINISHED tree re-ran synthesis and started PnR, because
freshness was decided from `_plugin_version()` + `_recipe_sha256()` — the
released version and the sha256 of the WHOLE ~66k-line runner. Both are facts
about the BUILD. Every landed fix bumps the version, so every landed fix
invalidated every cached step, whatever it actually touched.

The same key was simultaneously TOO NARROW, which the old code disclosed in a
comment instead of fixing: an in-tree edit to a helper module with no version
bump was not detected at all.

This deck holds BOTH halves, because a fix for either one alone is a different
and worse bug:

  SYMPTOM 1 (too coarse)  a no-op version bump must REUSE.
  SYMPTOM 2 (too narrow)  a helper edit with no version bump must INVALIDATE.

and it holds the fail-closed rules, which are the reason this is safe at all:
an unknown component is never freshness.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

# A HARD import, deliberately. `importorskip` would turn "main does not have
# this fix" into a SKIP, and a skip is not a red arm: the falsifiable-reference
# check needs this deck to FAIL against main's sources, not to pass by
# declining to run.
import _step_identity as si  # noqa: E402

RUNNER = PROGRAMS / "phase3_one_shot_runner.py"
FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
























# ---------------------------------------------------------------------------
# FAIL CLOSED — an unknown is never freshness
# ---------------------------------------------------------------------------
def test_two_unknowns_do_not_agree():
    """"I could not tell then" and "I cannot tell now" is not evidence that
    nothing moved."""
    fresh, why = si.compare({"inputs": None, "code": None,
                             "tools": None, "pdk": None},
                            {"inputs": None, "code": None,
                             "tools": None, "pdk": None})
    assert fresh is False, why


def test_no_sidecar_is_stale():
    fresh, why = si.compare(None, {c: "a" * 64 for c in si._COMPONENTS})
    assert fresh is False
    assert any("no recorded step identity" in w for w in why), why


def test_every_component_must_match_for_reuse():
    good = {c: "a" * 64 for c in si._COMPONENTS}
    assert si.compare(dict(good), dict(good))[0] is True
    for comp in si._COMPONENTS:
        rec = dict(good)
        rec[comp] = "b" * 64
        fresh, why = si.compare(rec, dict(good))
        assert fresh is False, f"{comp} differing must invalidate"
        assert any(w.startswith(f"{comp}:") for w in why), why






def test_tools_refuse_without_an_image_digest(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "provenance.jsonl").write_text(json.dumps({
        "tool": "yosys", "version": "0.38",
        "outputs": {"phase2/stage2/synth/netlist.v": "sha256:" + "0" * 64},
    }) + "\n", encoding="utf-8")
    dig, why = si.tools_digest(project, "synth", None)
    assert dig is None, "an unnameable image is not a proven image"
    assert any("image digest" in w for w in why), why


def test_tools_refuse_when_the_ledger_knows_nothing_of_this_step(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "provenance.jsonl").write_text(json.dumps({
        "tool": "klayout", "version": "0.28",
        "outputs": {"phase3/stage4/gds/top.gds": "sha256:" + "0" * 64},
    }) + "\n", encoding="utf-8")
    dig, why = si.tools_digest(project, "synth", "sha256:img")
    assert dig is None, why
    assert any("no invocation writing into" in w for w in why), why


def test_pdk_refuses_a_path_it_cannot_read(tmp_path):
    class _Pdk:
        liberty = "/nonexistent/inside/container/only.lib"
        tech_lef = cell_lef = cell_gds = drc_deck = None
    dig, why = si.pdk_digest(_Pdk())
    assert dig is None, "a PDK file that cannot be hashed is not a match"
    assert any("could not be read" in w for w in why), why


def test_pdk_is_hashed_where_it_actually_lives(tmp_path):
    """The container-only case, which is the ORDINARY one: measured on run2,
    every PDK path is under `/foss/pdks` and the host has no such directory.
    Without a reader that can reach them this component is never computable
    and the whole change degenerates into 'always re-run'."""
    class _Pdk:
        liberty = "/foss/pdks/only/inside/the/container.lib"
        tech_lef = cell_lef = cell_gds = drc_deck = None

    assert si.pdk_digest(_Pdk())[0] is None, "no reader: still refuses"

    seen = {}

    def hasher(paths):
        seen["paths"] = list(paths)
        return {p: "c" * 64 for p in paths}

    dig, why = si.pdk_digest(_Pdk(), hasher)
    assert dig is not None, why
    assert seen["paths"] == ["/foss/pdks/only/inside/the/container.lib"]


def test_a_hasher_that_answers_for_only_some_files_still_refuses():
    """Half an answer is not an answer: a PDK proven unchanged in four files
    out of five is not a PDK proven unchanged."""
    class _Pdk:
        liberty = "/foss/a.lib"
        tech_lef = "/foss/b.tlef"
        cell_lef = cell_gds = drc_deck = None
    dig, why = si.pdk_digest(_Pdk(), lambda paths: {"/foss/a.lib": "d" * 64})
    assert dig is None, "a partially readable PDK is not a matching PDK"
    assert any("/foss/b.tlef" in w for w in why), why


def test_a_failing_hasher_refuses_rather_than_raising():
    class _Pdk:
        liberty = "/foss/a.lib"
        tech_lef = cell_lef = cell_gds = drc_deck = None

    def boom(paths):
        raise RuntimeError("container gone")

    dig, why = si.pdk_digest(_Pdk(), boom)
    assert dig is None
    assert any("hasher failed" in w for w in why), why


def test_pdk_changes_when_a_pdk_file_changes(tmp_path):
    lib = tmp_path / "x.lib"
    lib.write_text("library(a){}\n", encoding="utf-8")

    class _Pdk:
        liberty = str(lib)
        tech_lef = cell_lef = cell_gds = drc_deck = None
    first, _ = si.pdk_digest(_Pdk())
    lib.write_text("library(b){}\n", encoding="utf-8")
    second, _ = si.pdk_digest(_Pdk())
    assert first is not None and first != second











# ---------------------------------------------------------------------------
# THE PREDICATE DELEGATES — the wiring itself, not a grep for a spelling
# ---------------------------------------------------------------------------
def _runner_module():
    import importlib
    return importlib.import_module("phase3_one_shot_runner")


def test_the_predicate_refuses_without_a_project():
    r = _runner_module()
    ok, why = r._producer_cache_valid_for(Path("/nonexistent"), "synth")
    assert ok is False
    assert "without the project" in why, why


def test_the_predicate_reuses_only_on_a_matching_sidecar(
        tmp_path, monkeypatch):
    """Drive the real predicate with a prepared directory: a sidecar that
    agrees with what this build computes reuses; one component moved does
    not."""
    r = _runner_module()
    out = tmp_path / "out"
    out.mkdir()
    ident = {c: "a" * 64 for c in si._COMPONENTS}
    monkeypatch.setattr(r, "_step_image_digest", lambda c: "sha256:img")
    monkeypatch.setattr(si, "identity_now",
                        lambda **kw: (dict(ident), {}))
    si.write_sidecar(out, "synth", dict(ident))
    ok, why = r._producer_cache_valid_for(
        out, "synth", project=tmp_path, pdk=None, container="")
    assert ok is True, why
    assert "step unchanged" in why, why

    moved = dict(ident)
    moved["code"] = "b" * 64
    si.write_sidecar(out, "synth", moved)
    ok, why = r._producer_cache_valid_for(
        out, "synth", project=tmp_path, pdk=None, container="")
    assert ok is False
    assert "code:" in why, why


def test_an_unnameable_image_makes_the_step_re_run(tmp_path, monkeypatch):
    r = _runner_module()
    monkeypatch.setattr(r, "_step_image_digest", lambda c: None)
    out = tmp_path / "out"
    out.mkdir()
    ok, why = r._producer_cache_valid_for(
        out, "synth", project=tmp_path, pdk=None, container="")
    assert ok is False, why




def test_mutation_comparing_unknowns_as_equal_is_caught():
    """SYMPTOM 2's mutation, and the fail-closed rule's: if two `None`s
    compared equal, a step whose identity cannot be computed would REUSE."""
    both_unknown = {c: None for c in si._COMPONENTS}
    fresh, _ = si.compare(dict(both_unknown), dict(both_unknown))
    assert fresh is False, (
        "compare() must never treat an uncomputable component as a match")
    partial = {c: "a" * 64 for c in si._COMPONENTS}
    partial["tools"] = None
    fresh, why = si.compare({c: "a" * 64 for c in si._COMPONENTS}, partial)
    assert fresh is False, why
    assert any("cannot be established" in w for w in why), why


# ===========================================================================
# r2 — THE REVIEW FINDINGS (wcxu446tu, 6 CONFIRMED)
#
# ROOT CAUSE of most of them: r1 tied each kind to the ONE flow step that
# declares its artefact, but the runner FUNCTION implements a RANGE.
# `step_pnr` is floorplan THROUGH routing; `step_gds` and the finishing around
# it span die-finishing through stream-out. Keying pnr on step 21 alone made
# its inputs `sha(post_hold.def)` — a file `step_pnr` WRITES ITSELF — so a new
# netlist, SDC or slot left the routed DEF "fresh" and the disclosure said so.
#
# NOTHING BELOW PATCHES AN IDENTITY HELPER. The r1 suite pinned
# `_step_image_digest`, and that is exactly what hid finding 5.
# ===========================================================================



def _pdk_with_real_files(root: Path):
    """A PDK OUTSIDE the project, which is where a PDK lives.

    r3 added a structural guard: a PDK path inside the run directory is this
    run's own derivation, not a PDK input, and refuses. Writing the fixture's
    PDK inside the project tripped it — correctly."""
    d = Path(root).parent / "_pdk_outside"
    d.mkdir(parents=True, exist_ok=True)
    lib, tlef = d / "tt.lib", d / "tech.lef"
    for f, t in ((lib, "library(t){}\n"), (tlef, "VERSION 5.8 ;\n")):
        if not f.is_file():
            f.write_text(t)

    class _Pdk:
        liberty = str(lib)
        tech_lef = str(tlef)
        cell_lef = cell_gds = drc_deck = None
    return _Pdk()


def _span_project(tmp_path: Path) -> Path:
    """A finished tree carrying what every span declares and reads."""
    for rel, text in (
        ("input/submission_template/tapeout_declaration.json",
         '{"answers": {"deliverable": "DIE"}}\n'),
        ("phase2/stage1/rtl/top.v", "module top(); endmodule\n"),
        ("phase2/stage2/constraints/top.sdc", "create_clock -period 10\n"),
        ("phase2/stage2/synth/netlist.v", "module top(); endmodule\n"),
        # the netlist PnR ACTUALLY reads, per `pnr_input_netlist`
        ("phase2/stage2/synth/top_synth.v", "module top(); endmodule\n"),
        ("phase3/stage3/pnr/routed.def", "VERSION 5.8 ;\nEND DESIGN\n"),
        ("phase3/stage3/pnr/top.def", "VERSION 5.8 ;\nEND DESIGN\n"),
        ("phase3/stage3/pnr/spare_cells.json", "{}\n"),
        ("phase3/stage3/extracted/parasitic.spef", "*SPEF\n"),
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    (tmp_path / "provenance.jsonl").write_text("".join(
        json.dumps({"tool": t, "version": v,
                    "outputs": {o: "sha256:" + "0" * 64}}) + "\n"
        for t, v, o in (
            ("yosys", "0.38", "phase2/stage2/synth/netlist.v"),
            ("openroad", "2.0", "phase3/stage3/pnr/routed.def"),
            ("klayout", "0.28", "phase3/stage4/gds/top.gds"))))
    return tmp_path



def _fake_recording():
    """A minimal RECORDING, so `identity_now` has a `code` to compute.

    r5 makes `code` come from what the step RAN, and a step with no recording
    gets no cache — which is the point. Tests that are about the OTHER three
    components supply a stable stand-in here; the recorder's own behaviour is
    covered by the r5 tests that drive it for real."""
    import _step_recorder as _sr
    d, err = _sr.check_digests(PROGRAMS / "_step_identity.py", [])
    assert not err, err
    return {"_step_identity.py": d,
            "__engine_env__": {name: _sr._engine_marker(name)
                               for name in _sr.ENGINE_ENV}}
















# --- (a) a new netlist / SDC / slot must invalidate PnR --------------------




# NOTE — two tests were removed here, both superseded by r4's resolver-driven
# input set rather than by a weakening:
#   * `test_a_rerouted_def_invalidates_the_gds` edited `routed.def`, which is
#     PnR's OUTPUT. The GDS step reads the DEF it STREAMS, and the test below
#     holds exactly that; in a real flow a reroute moves both.
#   * `test_a_new_slot_declaration_invalidates_every_kind` changed
#     `deliverable` on a declaration with NO `answer_provenance`, so the
#     flow-written-key rule correctly drops it.
#     `test_an_answer_the_operator_owns_still_invalidates` holds the
#     owner-claimed case, which is the one that matters.










# --- the PDK that the step itself derives ----------------------------------
def test_the_pdk_is_hashed_as_the_flow_received_it(tmp_path):
    """FINDING 4. `step_pnr` stages a VIA-legalised tech LEF into the RUN
    directory and MUTATES the shared PdkConfig to point at it. The stamp is
    written after the step, so the recorded PDK was the derived file, which
    differs every run — PnR was NEVER reused. `<field>_source` is the
    plugin's own record of the original."""
    derived = tmp_path / "active_via_legalized.tlef"
    derived.write_text("VERSION 5.8 ;\n# derived by this run\n")
    source = tmp_path / "nom.tlef"
    source.write_text("VERSION 5.8 ;\n")

    class _Pdk:
        liberty = None
        tech_lef = str(derived)
        tech_lef_source = str(source)
        cell_lef = cell_gds = drc_deck = None

    first, why = si.pdk_digest(_Pdk())
    assert first is not None, why
    # The run derives it again, differently — as it does on every run.
    derived.write_text("VERSION 5.8 ;\n# derived again, different bytes\n")
    second, _ = si.pdk_digest(_Pdk())
    assert first == second, (
        "the PDK identity moved because the STEP derived a file — that is an "
        "output, and it made the component never match")
    # ...but a real PDK change still moves it.
    source.write_text("VERSION 5.8 ;\n# a different PDK\n")
    third, _ = si.pdk_digest(_Pdk())
    assert third != first, "a real PDK change must still invalidate"




# ===========================================================================
# r3 — ROUND-2 REVIEW (wt0nrjhv6, 5 CONFIRMED)
#
# The theme: r2 still hashed what the FLOW DECLARES rather than what the STEP
# OPENS. `step_pnr` does not read `phase2/stage2/constraints/<top>.sdc` — that
# is a copy the runner writes once — and two files a step genuinely reads are
# rewritten by the flow AFTER the stamp that vouches for them.
#
# These drive the REAL resolution path: a staged SDC under `input/constraints`,
# a real declaration with real `answer_provenance`, the real knobs.
# ===========================================================================
def _staged_project(tmp_path: Path, *, stage_sdc: bool = True) -> Path:
    project = _span_project(tmp_path)
    if stage_sdc:
        ic = project / "input" / "constraints"
        ic.mkdir(parents=True, exist_ok=True)
        (ic / "silicon.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    (project / "input" / "submission_template"
     / "tapeout_declaration.json").write_text(json.dumps({
         "schema": 1,
         "answers": {"deliverable": "DIE", "core_area_um": [0, 0, 10, 10],
                     "top_cell": "top"},
         "answer_provenance": {"deliverable": {"answered_by": "owner"}},
     }, indent=2))
    (project / "phase2" / "stage2" / "synth" / "top_synth.v").write_text(
        "module top(); endmodule\n")
    (project / "phase3" / "stage3" / "pnr" / "top.def").write_text(
        "VERSION 5.8 ;\nEND DESIGN\n")
    return project






# --- A: the SDC the step ACTUALLY resolves --------------------------------








# --- A: the knobs ---------------------------------------------------------






# --- D: the declaration the flow writes back ------------------------------




def test_the_declaration_rule_keeps_provenance_itself(tmp_path):
    project = _staged_project(tmp_path)
    decl = project / "input" / "submission_template" / \
        "tapeout_declaration.json"
    before = si.canonical_bytes(decl, "declaration_as_asked")
    doc = json.loads(decl.read_text())
    doc["answer_provenance"]["deliverable"]["answered_by"] = "someone else"
    decl.write_text(json.dumps(doc, indent=2))
    after = si.canonical_bytes(decl, "declaration_as_asked")
    assert before != after, "who answered is itself operator input"


# --- C/E: the volatile SPEF ------------------------------------------------
def test_the_spef_date_line_is_normalised_away(tmp_path):
    """FINDINGS C and E. A SPEF carries `*DATE "<wall clock>"`, so two runs
    never agree. The GDS identity does not list the SPEF at all — `step_gds`
    does not read it and it is written after the stamp — but the rule exists
    and is stated, so it is asserted rather than assumed."""
    a = tmp_path / "a.spef"
    b = tmp_path / "b.spef"
    a.write_text('*SPEF "ieee 1481-1999"\n*DATE "one o\'clock"\n*DESIGN "x"\n')
    b.write_text('*SPEF "ieee 1481-1999"\n*DATE "half past two"\n*DESIGN "x"\n')
    assert si.canonical_bytes(a, "raw") != si.canonical_bytes(b, "raw")
    assert si.canonical_bytes(a, "spef_no_date") == \
        si.canonical_bytes(b, "spef_no_date")
    b.write_text('*SPEF "ieee 1481-1999"\n*DATE "x"\n*DESIGN "DIFFERENT"\n')
    assert si.canonical_bytes(a, "spef_no_date") != \
        si.canonical_bytes(b, "spef_no_date"), (
        "normalising the clock must not normalise the content")










# --- fail-closed, harder than r2 ------------------------------------------
def test_an_empty_input_set_refuses(tmp_path):
    dig, why = si.resolved_inputs_digest(tmp_path, (), {})
    assert dig is None
    assert any("enumerated no input" in w for w in why), why


def test_an_input_the_step_could_not_resolve_refuses(tmp_path):
    dig, why = si.resolved_inputs_digest(
        tmp_path, (("sdc", None, "raw"),), {})
    assert dig is None
    assert any("produced no path" in w for w in why), why


def test_a_pdk_path_in_the_runs_output_tree_refuses(tmp_path):
    """The structural form of finding 4, narrowed by round-3 review finding 5:
    only the run's OUTPUT tree is this run's own derivation."""
    derived = tmp_path / "phase3" / "stage3" / "pnr" / "active.tlef"
    derived.parent.mkdir(parents=True, exist_ok=True)
    derived.write_text("VERSION 5.8 ;\n")

    class _Pdk:
        liberty = None
        tech_lef = str(derived)
        cell_lef = cell_gds = drc_deck = None

    dig, why = si.pdk_digest(_Pdk(), None, tmp_path)
    assert dig is None, "a PDK path in the run's OUTPUT tree is not an input"
    assert any("OUTPUT tree" in w for w in why), why


def test_a_pdk_the_design_stages_under_input_is_hashed(tmp_path):
    """ROUND-3 REVIEW FINDING 5. `input/` is the design's — that is this
    module's own rule — so a PDK staged there is a DESIGN INPUT. Refusing it
    made every staged-PDK run (asap7 measured) permanently un-fresh."""
    staged = tmp_path / "input" / "pdk" / "tech.lef"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text("VERSION 5.8 ;\n")

    class _Pdk:
        liberty = None
        tech_lef = str(staged)
        cell_lef = cell_gds = drc_deck = None

    dig, why = si.pdk_digest(_Pdk(), None, tmp_path)
    assert dig is not None, (
        f"a PDK the design staged under input/ must be hashed, not refused: "
        f"{why}")
    staged.write_text("VERSION 5.8 ;\n# a different PDK\n")
    assert si.pdk_digest(_Pdk(), None, tmp_path)[0] != dig, (
        "and a change to it must invalidate")


# ===========================================================================
# r4 — ROUND-3 REVIEW (w18fc56v9, 5 CONFIRMED)
#
# The theme, and it is the last restatement: r3 still NAMED each input instead
# of ASKING the step. Every miss the review found is that one mistake.
# ===========================================================================




















# ===========================================================================
# r5 — ROUND-4 REVIEW (wlfte9cfq, 6 confirmed)
#
# "Stop patching the static closure; this is round 4 of the same hole class,
# and Python's dynamism guarantees a round 5." So the closure stops being the
# authority: the step RUNS and what ran is RECORDED.
# ===========================================================================
import _step_recorder as sr  # noqa: E402


def _mini_tree(tmp_path: Path) -> Path:
    root = tmp_path / "progs"
    root.mkdir()
    (root / "m_alias.py").write_text("TUNING = 7\ndef helper():\n    return TUNING\n")
    (root / "m_dyn.py").write_text("def dynamic():\n    return 2\n")
    (root / "m_top.py").write_text(
        "from m_alias import helper as _h\n"
        "import importlib\n"
        "def run():\n"
        "    mod = importlib.import_module('m_dyn')\n"
        "    return _h() + mod.dynamic()\n")
    return root


def _record_run(root: Path):
    import importlib
    sys.path.insert(0, str(root))
    try:
        for name in ("m_top", "m_alias", "m_dyn"):
            sys.modules.pop(name, None)
        mod = importlib.import_module("m_top")
        with sr.Recorder(root) as r:
            mod.run()
        return r.recorded()
    finally:
        sys.path.remove(str(root))


def test_an_aliased_import_is_recorded_because_it_ran(tmp_path):
    """ROUND-4 FINDING 1. `from X import f as g` was recorded by the static
    closure as a member named `g`, which does not exist — so it was DROPPED
    WITH NO NOTE. Real escapes: `routing_layer_upper_bound as _rub` (shapes
    the routed DEF), `pdn_ring_dimensions` (the PDN ring), `drop_include_hubs`
    (synth's read set)."""
    root = _mini_tree(tmp_path)
    record, why = _record_run(root)
    assert record is not None, why
    assert "m_alias.py" in record, record
    # QUALNAMES, not name@lineno — r5 review finding 4: a key carrying a line
    # number turns every function below an inserted line into ABSENT, which
    # degrades the file to one bit of granularity.
    assert "helper" in record["m_alias.py"], record
    base = sr.digest_of(record)
    (root / "m_alias.py").write_text(
        "TUNING = 7\ndef helper():\n    return TUNING + 1\n")
    now, err = sr.rederive(record, root)
    assert not err, err
    assert sr.digest_of(now) != base, (
        "an edit to a function reached only through an ALIAS went unnoticed")


def test_an_importlib_loaded_module_is_recorded(tmp_path):
    """ROUND-4 FINDING 1. `importlib.import_module("<literal>")` is invisible
    to any import-graph walk — measured on the GDS label restore
    (`gds_port_label_check`)."""
    root = _mini_tree(tmp_path)
    record, why = _record_run(root)
    assert record is not None, why
    assert "m_dyn.py" in record, record
    base = sr.digest_of(record)
    (root / "m_dyn.py").write_text("def dynamic():\n    return 3\n")
    now, _ = sr.rederive(record, root)
    assert sr.digest_of(now) != base


def test_a_module_level_constant_is_recorded_though_it_never_runs(tmp_path):
    """Constants, compiled regex tables and dict dispatch tables are not
    functions and never appear as a call, yet changing one changes what every
    function in the file does. Earlier rounds had to special-case exactly
    this; the module-body digest covers it by construction."""
    root = _mini_tree(tmp_path)
    record, why = _record_run(root)
    assert record is not None, why
    base = sr.digest_of(record)
    (root / "m_alias.py").write_text(
        "TUNING = 8\ndef helper():\n    return TUNING\n")
    now, _ = sr.rederive(record, root)
    assert sr.digest_of(now) != base, (
        "a module-level constant the step's code READS was not covered")


def test_an_unrelated_edit_in_a_recorded_file_changes_nothing(tmp_path):
    """The other half: function-level, so a function the step never ran does
    not cost a re-run even in a file it did."""
    root = _mini_tree(tmp_path)
    record, why = _record_run(root)
    assert record is not None, why
    base = sr.digest_of(record)
    (root / "m_alias.py").write_text(
        "TUNING = 7\ndef helper():\n    return TUNING\n"
        "def never_called():\n    return 999\n")
    now, _ = sr.rederive(record, root)
    assert sr.digest_of(now) == base, (
        "adding a function the step never runs re-ran it anyway")


def test_a_recorded_function_that_vanished_is_the_strongest_stale(tmp_path):
    root = _mini_tree(tmp_path)
    record, why = _record_run(root)
    assert record is not None, why
    (root / "m_alias.py").write_text("TUNING = 7\n")
    now, _ = sr.rederive(record, root)
    assert any(v == "ABSENT" for d in now.values() for v in d.values()), now
    assert sr.digest_of(now) != sr.digest_of(record)


def test_no_recording_means_no_cache(tmp_path):
    """A step whose code could not be recorded is not a step anyone can prove
    current."""
    dig, why = si.code_from_stored(None, PROGRAMS)
    assert dig is None
    assert any("carries no recording" in w for w in why), why
    dig, why = si.code_from_recording(None)
    assert dig is None and why


def test_the_pdk_identity_is_every_field_the_step_received(tmp_path):
    """ROUND-4 FINDING 2. The recipe-shaping fields are built in `main()`
    (`_detect_pdk` -> `_pdk_config_from_registry` -> `_derive_tapcell_master`),
    outside every seed closure — so a `pdk_registry.json` edit
    (`clk_buf_cell`, `pdn_straps`, `pdn_ring`) or a tap-master rule change
    altered the DEF with all four components unchanged."""
    lib = tmp_path / "x.lib"
    lib.write_text("library(a){}\n")

    class _Pdk:
        name = "gf180mcuD"
        liberty = str(lib)
        tech_lef = cell_lef = cell_gds = drc_deck = None
        clk_buf_cell = "gf180mcu_fd_sc_mcu7t5v0__clkbuf_1"
        tapcell_master = "gf180mcu_fd_sc_mcu7t5v0__filltie"
        macro_lefs: list = []

    pdk = _Pdk()
    base, why = si.pdk_digest(pdk, None, tmp_path / "proj")
    assert base is not None, why
    pdk.clk_buf_cell = "gf180mcu_fd_sc_mcu7t5v0__clkbuf_4"
    assert si.pdk_digest(pdk, None, tmp_path / "proj")[0] != base, (
        "a registry-derived master changed and the PDK identity did not")
    pdk.clk_buf_cell = "gf180mcu_fd_sc_mcu7t5v0__clkbuf_1"
    pdk.macro_lefs = ["/some/macro.lef"]
    assert si.pdk_digest(pdk, None, tmp_path / "proj")[0] != base, (
        "the macro set is part of the PDK the step received")


def test_the_tools_component_is_carried_not_re_read(tmp_path, monkeypatch):
    """ROUND-4 FINDING 4. `step_canonicalize_artefacts` keeps APPENDING to
    `provenance.jsonl` after the stamps, with version-less reconstructed rows
    (measured: yosys -> "", pnr tools -> None), so re-reading the ledger made
    this component move on every no-op re-run. The ledger is a record of the
    past and it grows; a freshness key may not be read from it."""
    project = _staged_project(tmp_path)
    stored = json.dumps({"yosys": "0.38"}, sort_keys=True)
    ident, why = si.identity_now(
        project=project, kind="synth", runner_path=RUNNER,
        programs_dir=PROGRAMS, flow_yaml=FLOW,
        pdk=_pdk_with_real_files(project), image_digest="sha256:img",
        inputs=[("declaration",
                 project / "input/submission_template/tapeout_declaration.json",
                 "raw")],
        knobs={}, recording=_fake_recording(), stored_tools=stored)
    assert ident["tools"] is not None, why["tools"]
    # the ledger grows underneath — and it must not matter
    (project / "provenance.jsonl").write_text(
        (project / "provenance.jsonl").read_text()
        + json.dumps({"tool": "klayout", "version": "",
                      "outputs": {"phase2/stage2/synth/x.v": "sha256:0"}})
        + "\n")
    again, _ = si.identity_now(
        project=project, kind="synth", runner_path=RUNNER,
        programs_dir=PROGRAMS, flow_yaml=FLOW,
        pdk=_pdk_with_real_files(project), image_digest="sha256:img",
        inputs=[("declaration",
                 project / "input/submission_template/tapeout_declaration.json",
                 "raw")],
        knobs={}, recording=_fake_recording(), stored_tools=stored)
    assert again["tools"] == ident["tools"], (
        "the tools component moved because the ledger grew after the stamp")








def test_mutation_recording_only_calls_would_miss_the_module_body(tmp_path):
    """The mutation for the recorder: drop the module-body digest and a
    constant edit becomes invisible again."""
    root = _mini_tree(tmp_path)
    record, _why = _record_run(root)
    stripped = {f: {k: v for k, v in d.items() if k != sr.MODULE_BODY}
                for f, d in record.items()}
    base = sr.digest_of(stripped)
    (root / "m_alias.py").write_text(
        "TUNING = 8\ndef helper():\n    return TUNING\n")
    now, _ = sr.rederive(record, root)
    now_stripped = {f: {k: v for k, v in d.items() if k != sr.MODULE_BODY}
                    for f, d in now.items()}
    assert sr.digest_of(now_stripped) == base, (
        "sanity: without the module body, the constant edit is invisible")
    assert sr.digest_of(now) != sr.digest_of(record), (
        "and WITH it, the same edit is caught — which is why it is there")


# ===========================================================================
# r6 — ROUND-5 REVIEW (wk2vtxpjt)
#
# "record what ran" is the right AUTHORITY, but it recorded the wrong SPAN and
# keyed on line numbers. These exercise the DECISION PATH (`identity_now` /
# the recorder that feeds it), not the static closure — which the review
# showed has no caller at all, so the tests that exercised it proved nothing.
# ===========================================================================
def _rec_tree(tmp_path: Path) -> Path:
    root = tmp_path / "p"
    root.mkdir()
    (root / "m.py").write_text(
        "import functools\n"
        "TUNING = 7\n"
        "def deco(f):\n"
        "    return f\n"
        "class C:\n"
        "    TABLE = {'a': 1}\n"
        "    def meth(self):\n"
        "        return TUNING\n"
        "@deco\n"
        "def decorated():\n"
        "    return [x for x in range(3)]\n"
        "def run():\n"
        "    return C().meth() + len(decorated())\n")
    return root


def _rec_of(root: Path):
    import importlib
    sys.path.insert(0, str(root))
    try:
        sys.modules.pop("m", None)
        mod = importlib.import_module("m")
        with sr.Recorder(root) as r:
            mod.run()
        return r.recorded()
    finally:
        sys.path.remove(str(root))


def test_keys_are_qualnames_and_carry_no_line_numbers(tmp_path):
    """ROUND-5 FINDING 4. A key carrying a line number turns every function
    below an inserted line into ABSENT, so the runner degrades to whole-file
    granularity — which is exactly what run23 showed."""
    root = _rec_tree(tmp_path)
    record, why = _rec_of(root)
    assert record is not None, why
    keys = set(record["m.py"])
    assert {"run", "decorated", "C.meth", sr.MODULE_BODY} <= keys, keys
    assert not any("@" in k for k in keys), keys


def test_inserting_a_line_at_the_top_of_a_file_changes_nothing(tmp_path):
    root = _rec_tree(tmp_path)
    record, why = _rec_of(root)
    assert record is not None, why
    base = sr.digest_of(record)
    src = (root / "m.py").read_text()
    (root / "m.py").write_text("# a new first line\n" + src)
    now, err = sr.rederive(record, root)
    assert not err, err
    assert sr.digest_of(now) == base, (
        "an edit ABOVE the recorded functions re-ran the step")


def test_a_decorated_functions_body_edit_is_detected(tmp_path):
    """ROUND-5 FINDING 3. `co_firstlineno` for a decorated function is the
    DECORATOR line; keying on the `def` line made it ABSENT at stamp AND at
    check, so ABSENT == ABSENT and a body edit was never noticed."""
    root = _rec_tree(tmp_path)
    record, why = _rec_of(root)
    assert record is not None, why
    assert "decorated" in record["m.py"], record
    base = sr.digest_of(record)
    (root / "m.py").write_text((root / "m.py").read_text().replace(
        "range(3)", "range(4)"))
    now, _ = sr.rederive(record, root)
    assert sr.digest_of(now) != base


def test_a_class_body_statement_is_in_the_digest(tmp_path):
    """The other half of finding 3: a statement in a CLASS body is in no
    function, and was in no digest at all."""
    root = _rec_tree(tmp_path)
    record, why = _rec_of(root)
    assert record is not None, why
    base = sr.digest_of(record)
    (root / "m.py").write_text((root / "m.py").read_text().replace(
        "TABLE = {'a': 1}", "TABLE = {'a': 2}"))
    now, _ = sr.rederive(record, root)
    assert sr.digest_of(now) != base


def test_an_unnameable_code_object_refuses_at_stamp_time(tmp_path):
    """An ABSENT at STAMP time is a refusal, not a stored value — storing it
    made it compare equal to the ABSENT the check re-derives."""
    root = _rec_tree(tmp_path)
    digests, err = sr.stamp_digests(root / "m.py", [("nope", 9999)])
    assert digests == {} and err, (digests, err)
    assert "has no definition" in err, err


def test_a_comprehension_folds_into_its_enclosing_function(tmp_path):
    """On 3.10 a `<listcomp>` carries the line it appears on, so keying it
    separately made an edit anywhere above turn it ABSENT."""
    root = _rec_tree(tmp_path)
    record, why = _rec_of(root)
    assert record is not None, why
    assert not any(k.startswith("<") for k in record["m.py"]), record


# --- the SPAN: every step that writes the kind's artefacts -----------------
def test_the_post_stamp_writers_are_recorded_into_pnr_and_gds():
    """ROUND-5 FINDING 1, on the decision path. `step_signoff_spef_repair` and
    `step_signoff_drv_wire_length_repair` run AFTER `step_pnr` and copy a
    repaired DEF over `routed.def` and `{top}.def`, so an edit to the repair
    path read "pnr unchanged" and shipped the old repaired DEF."""
    src = RUNNER.read_text()
    for writer in ("step_signoff_spef_repair",
                   "step_signoff_drv_wire_length_repair"):
        assert f'_recorded(("pnr", "gds"), {writer})' in src \
            or f'_recorded(("pnr", "gds"),\n                             {writer})' in src, (
            f"{writer} writes the cached DEF and is not recorded into the "
            f"kinds it rewrites")
    assert "RE-STAMP PnR AFTER ITS LAST WRITER" in src, (
        "the pnr stamp must be taken after the last step that writes its "
        "artefacts, or the stamp vouches for bytes that were then replaced")








# --- r6 finding 2: code that runs OUT OF PROCESS ---------------------------
def _launch_tree(tmp_path: Path) -> Path:
    root = tmp_path / "p2"
    root.mkdir()
    (root / "helper_lib.py").write_text("VALUE = 1\n")
    (root / "metal_fill.py").write_text(
        "import helper_lib\nprint(helper_lib.VALUE)\n")
    (root / "m.py").write_text(
        "import subprocess, sys\n"
        "def run():\n"
        "    subprocess.run([sys.executable, 'metal_fill.py'],\n"
        "                   cwd=%r, capture_output=True)\n"
        "    subprocess.run(['bash', '-lc',\n"
        "                    'klayout -b -rm metal_fill.py || true'],\n"
        "                   cwd=%r, capture_output=True)\n" % (str(root),
                                                               str(root)))
    return root


def _launch_record(root: Path):
    import importlib
    sys.path.insert(0, str(root))
    try:
        sys.modules.pop("m", None)
        mod = importlib.import_module("m")
        with sr.Recorder(root) as r:
            mod.run()
        return r.recorded()
    finally:
        sys.path.remove(str(root))


def test_a_script_launched_out_of_process_is_recorded(tmp_path):
    """ROUND-5 FINDING 2. `sys.setprofile` cannot see another process, so
    klayout's `metal_fill/metal_fill.py`, `die_finishing_gen`'s seal ring and
    the `pad_*_gen` programs run via `_docker_exec python3` all executed with
    NOTHING recorded. Both launch shapes are watched — a bare argv and a
    `bash -lc "klayout -b -rm …"` string — at the one place every launch
    passes through, rather than by enumerating call sites, which is the
    mistake rounds 1-5 kept repeating."""
    root = _launch_tree(tmp_path)
    record, why = _launch_record(root)
    assert record is not None, why
    assert "launched:metal_fill.py" in record, sorted(record)
    base = sr.digest_of(record)
    (root / "metal_fill.py").write_text(
        "import helper_lib\nprint(helper_lib.VALUE + 1)\n")
    now, err = sr.rederive(record, root)
    assert not err, err
    assert sr.digest_of(now) != base, (
        "an edit to a script this step runs OUT OF PROCESS went unnoticed")


def test_the_launched_scripts_import_closure_is_recorded(tmp_path):
    """It runs in another process, so there is nothing to be clever with: the
    file is taken WHOLE and so is everything it imports from this tree."""
    root = _launch_tree(tmp_path)
    record, why = _launch_record(root)
    assert record is not None, why
    assert "launched:helper_lib.py" in record, sorted(record)
    base = sr.digest_of(record)
    (root / "helper_lib.py").write_text("VALUE = 2\n")
    now, _ = sr.rederive(record, root)
    assert sr.digest_of(now) != base


def test_the_engine_selecting_env_is_recorded(tmp_path, monkeypatch):
    """`$VIBEIC_KLAYOUT_TOOLS` points `_klayout_launch` at a fork checkout, so
    the same recipe can execute entirely different code."""
    monkeypatch.setenv("VIBEIC_KLAYOUT_TOOLS", "/a/fork")
    root = _launch_tree(tmp_path)
    record, why = _launch_record(root)
    assert record is not None, why
    assert "__engine_env__" in record, sorted(record)
    assert "VIBEIC_KLAYOUT_TOOLS" in record["__engine_env__"]


def test_an_unattributable_plugin_launch_refuses(tmp_path):
    """A plugin script we cannot READ means this kind gets no cache."""
    root = tmp_path / "p3"
    root.mkdir()
    (root / "ghost.py").write_text("x = 1\n")
    r = sr.Recorder(root)
    r._launched.add("ghost.py")
    r._hits.add((str(root / "ghost.py"), "f", 1))
    (root / "ghost.py").chmod(0o000)
    try:
        record, why = r.recorded()
        assert record is None, record
        assert "could not be read" in why or "has no definition" in why, why
    finally:
        (root / "ghost.py").chmod(0o644)


def test_a_launch_of_a_non_plugin_script_is_not_a_refusal(tmp_path):
    """Only a PLUGIN launch has to be attributable; a system script is not
    ours to hash, and treating it as a refusal would mean no cache ever."""
    root = _launch_tree(tmp_path)
    r = sr.Recorder(root)
    r._launched.add("/usr/lib/python3/something_else.py")
    r._hits.add((str(root / "m.py"), "run", 2))
    record, why = r.recorded()
    assert record is not None, why
    assert not any(k.endswith("something_else.py") for k in record), record


# ===========================================================================
# r7 — ROUND-6 REVIEW (wcr8rvg8d): 2 HIGH + 1 MED, all narrow
# ===========================================================================




def test_unset_engine_name_is_recorded_and_later_set_invalidates(
        tmp_path, monkeypatch):
    monkeypatch.delenv("VIBEIC_KLAYOUT_TOOLS", raising=False)
    root = _rec_tree(tmp_path)
    record, why = _rec_of(root)
    assert record is not None, why
    name = "VIBEIC_KLAYOUT_TOOLS"
    assert record["__engine_env__"][name] == sr._engine_marker(name)
    assert si.code_from_stored({"m.py": record["m.py"]}, root)[0] is None
    fork = tmp_path / "fork"
    fork.mkdir()
    (fork / "engine.rb").write_text("engine\n")
    monkeypatch.setenv(name, str(fork))
    now, err = sr.rederive(record, root)
    assert not err, err
    assert sr.digest_of(now) != sr.digest_of(record)


def test_docstring_asset_name_does_not_bind_an_unexecuted_test(tmp_path):
    root = tmp_path / "plugin"
    root.mkdir()
    (root / "tests").mkdir()
    irrelevant = root / "tests" / "test_mirror.py"
    irrelevant.write_text("unrelated test\n")
    emitter = root / "emit.py"
    emitter.write_text('"""tests/test_mirror.py"""\n'
                       'ENGINE = "metal_fill.py"\n')
    (root / "metal_fill.py").write_text("engine\n")
    assets = sr._engine_assets(emitter, root)
    assert root / "metal_fill.py" in assets
    assert irrelevant not in assets


def test_a_grandchild_engine_is_reached_from_the_real_program(tmp_path):
    """ROUND-6 FINDING 2. The `Popen` wrapper sees HOP 1 (runner ->
    `metal_fill_emit.py`) but not HOP 2 (`metal_fill_emit.py` -> `klayout -b
    -r metal_fill/metal_fill.py`), and both rewrite the GDS in place inside
    `step_gds`. `_SCRIPT_RE` was `.py`-only and `_static_imports` follows
    Python imports only, so the engine was outside the key entirely.

    Driven against the REAL program, not a shape the flow does not use."""
    emit = PROGRAMS / "metal_fill_emit.py"
    assert emit.is_file(), "the real program must exist for this to mean it"
    assets = sr._engine_assets(emit, PROGRAMS)
    names = {str(q.relative_to(PROGRAMS)) for q in assets
             if str(q).startswith(str(PROGRAMS))}
    assert "metal_fill/metal_fill.py" in names, (
        f"the KLayout engine this program hands off to is not reachable: "
        f"{sorted(names)}")


def test_an_engine_asset_edit_invalidates_the_launched_closure(tmp_path):
    root = tmp_path / "eng"
    (root / "metal_fill").mkdir(parents=True)
    (root / "metal_fill" / "metal_fill.py").write_text("print('v1')\n")
    (root / "emit.py").write_text("ENGINE = 'metal_fill.py'\nprint(ENGINE)\n")
    (root / "m.py").write_text(
        "import subprocess, sys\n"
        "def run():\n"
        "    subprocess.run([sys.executable, 'emit.py'], cwd=%r,\n"
        "                   capture_output=True)\n" % str(root))
    import importlib
    sys.path.insert(0, str(root))
    try:
        sys.modules.pop("m", None)
        mod = importlib.import_module("m")
        with sr.Recorder(root) as r:
            mod.run()
        record, why = r.recorded()
    finally:
        sys.path.remove(str(root))
    assert record is not None, why
    assert "launched:metal_fill/metal_fill.py" in record, sorted(record)
    base = sr.digest_of(record)
    (root / "metal_fill" / "metal_fill.py").write_text("print('v2')\n")
    now, err = sr.rederive(record, root)
    assert not err, err
    assert sr.digest_of(now) != base, (
        "an edit to the engine a launched program hands to KLayout went "
        "unnoticed")


def test_the_engine_env_is_compared_by_its_bytes(tmp_path, monkeypatch):
    """ROUND-6 FINDING 3. `__engine_env__` was recorded and then copied back
    verbatim by `rederive`, so it was never COMPARED — swapping the fork
    engine never made the GDS stale. And a PATH STRING is not an engine: two
    different checkouts at the same path read identical."""
    fork = tmp_path / "fork"
    fork.mkdir()
    (fork / "engine.rb").write_text("v1\n")
    monkeypatch.setenv("VIBEIC_KLAYOUT_TOOLS", str(fork))
    record = {"__engine_env__": {"VIBEIC_KLAYOUT_TOOLS":
                                 sr._engine_marker("VIBEIC_KLAYOUT_TOOLS")}}
    base = sr.digest_of(record)
    assert sr.digest_of(sr.rederive(record, tmp_path)[0]) == base, "stable"
    # same PATH, different BYTES
    (fork / "engine.rb").write_text("v2\n")
    assert sr.digest_of(sr.rederive(record, tmp_path)[0]) != base, (
        "the fork engine's contents changed and nothing noticed")


def test_shared_launched_dependency_is_analysed_once(tmp_path, monkeypatch):
    root = tmp_path / "programs"
    root.mkdir()
    for name in ("first", "second"):
        (root / f"{name}.py").write_text("import shared\n")
    (root / "shared.py").write_text('ENGINE = "recipe.tcl"\n')
    (root / "recipe.tcl").write_text("puts first_recipe\n")
    recorder = sr.Recorder(root)
    recorder._launched.update(["first.py", "second.py"])
    calls = []
    original = sr._engine_assets
    def measured(path, *args, **kwargs):
        calls.append(Path(path).name)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(sr, "_engine_assets", measured)
    record, error = recorder._launched_digests()
    assert not error
    assert set(record) == {"launched:first.py", "launched:second.py",
                           "launched:shared.py", "launched:recipe.tcl"}
    assert calls.count("shared.py") == 1
    # The next collection still reads current files and current directory
    # members; an analysis cache must not hide an edited engine or new import.
    (root / "extra.py").write_text("VALUE = 2\n")
    (root / "shared.py").write_text('import extra\nENGINE = "recipe.tcl"\n')
    (root / "recipe.tcl").write_text("puts second_recipe\n")
    after, error = recorder._launched_digests()
    assert not error and "launched:extra.py" in after
    assert after["launched:recipe.tcl"] != record["launched:recipe.tcl"]
    assert after["launched:shared.py"] != record["launched:shared.py"]


def test_repeated_declaration_reads_do_not_reparse_unchanged_source(tmp_path, monkeypatch):
    root = tmp_path / "programs"
    root.mkdir()
    emitter = root / "emitter.py"
    emitter.write_text('"""Historical ghost.rb is not an engine."""\n'
                       'ENGINE = "first.tcl"\n')
    (root / "first.tcl").write_text("puts first\n")
    (root / "second.tcl").write_text("puts second\n")
    original = sr.ast.parse
    calls = []
    def measured(source, *args, **kwargs):
        calls.append(source)
        return original(source, *args, **kwargs)
    monkeypatch.setattr(sr.ast, "parse", measured)
    for _ in range(3):
        assert sr._engine_assets(emitter, root) == [root / "first.tcl"]
        assert sr._static_imports(emitter, root) == [emitter]
    emitter.write_text('ENGINE = "second.tcl"\n')
    assert sr._engine_assets(emitter, root) == [root / "second.tcl"]
    assert len(calls) <= 2
