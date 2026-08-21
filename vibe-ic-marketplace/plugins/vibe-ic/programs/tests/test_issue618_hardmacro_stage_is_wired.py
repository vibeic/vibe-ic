"""#618 — the staged-hard-macro resolver was tested; its THREE call sites were not.

`test_staged_hardmacro_blackbox` drives `_hardmacro_stage` directly and covers it
well — positive discovery, the `(* blackbox *)` stub, and four negative controls.
Nothing drove the places that CALL it: the sim compile set, the sanity-synth
source list, and the LEC gold/gate build. Each is reachable only through a full
Phase-2 run, so the PR's evidence (one design, one container) is a measurement
rather than a regression guard, and the wiring is where this repo has repeatedly
leaked — `checker_execution_wiring_audit` exists because "a checker that only its
own test runs is not wired".

WHAT COULD BREAK SILENTLY, and is now pinned:

  * `build_equiv_script(..., blackbox_v=...)` — the parameter is real on main,
    but nothing exercised the call. A signature drift here is a TypeError raised
    inside a subprocess whose stderr the LEC step folds into a FAIL verdict, so
    it would read as "the design does not match", not as a broken call.
  * the synth stub is appended AFTER the #662 re-glob. Moving it before would be
    silently undone by the re-glob and the macro would go back to
    `Unknown module type` — with the module still present and its own tests
    green.
  * the sim path appends the BEHAVIOURAL model and the synth path appends the
    BLACKBOX copy. Swapping them synthesises the macro body into flops (the area
    the blackbox exists to prevent) while every existing test still passes.
"""
from __future__ import annotations

import importlib
import inspect
import json
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]

HMS = importlib.import_module("_hardmacro_stage")


def _project(tmp_path, *, instantiate=True, staged=True):
    """A design with an rtl/ that instantiates a macro, and a staged model."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    body = ("module top(input clk, input [7:0] d, output [7:0] q);\n"
            + ("  memblk u_m (.clk(clk), .d(d), .q(q));\n" if instantiate else "")
            + "endmodule\n")
    (rtl / "top.v").write_text(body, encoding="utf-8")
    if staged:
        pdk = tmp_path / "input" / "pdk_local"
        pdk.mkdir(parents=True)
        (pdk / "memblk.v").write_text(
            "module memblk(input clk, input [7:0] d, output [7:0] q);\n"
            "  reg [7:0] mem [0:255];\n"
            "  assign q = mem[0];\n"
            "endmodule\n", encoding="utf-8")
        (pdk / "memblk.lib").write_text(
            "library (m) { cell (memblk) { } }\n", encoding="utf-8")
    return tmp_path, [rtl / "top.v"]


# ── the resolver answers for this fixture at all ────────────────────────────
def test_the_fixture_is_one_the_resolver_finds(tmp_path):
    """Positive control for everything below: a wiring test whose fixture the
    resolver returns nothing for would pass while wired to nothing."""
    project, rtl = _project(tmp_path)
    got = HMS.staged_hardmacro_models(project, rtl)
    assert [m["name"] for m in got] == ["memblk"], got
    assert got[0]["v"] is not None and got[0]["lib"] is not None


def test_an_uninstantiated_macro_is_not_returned(tmp_path):
    project, rtl = _project(tmp_path, instantiate=False)
    assert HMS.staged_hardmacro_models(project, rtl) == []


# ── call site 1 + 2: the runner ─────────────────────────────────────────────
def test_the_runner_binds_the_shared_resolver_not_a_private_copy():
    """One resolver, three consumers. A second copy is how the sim set and the
    synth set come to disagree about which macros are staged."""
    dosr = importlib.import_module("design_one_shot_runner")
    assert dosr._staged_hardmacro_models is HMS.staged_hardmacro_models
    assert dosr._emit_hardmacro_blackbox_stub is HMS.emit_blackbox_stub


def test_the_sim_path_streams_the_BEHAVIOURAL_model(tmp_path):
    """Sim needs real memory behaviour; a blackbox there simulates nothing.
    Driven through the resolver the sim site calls, then asserted on the FILE
    it would append — the blackbox copy has a different name (`.bb.v`)."""
    project, rtl = _project(tmp_path)
    m = HMS.staged_hardmacro_models(project, rtl)[0]
    assert m["v"].name == "memblk.v"
    assert "(* blackbox *)" not in m["v"].read_text()
    assert "reg [7:0] mem" in m["v"].read_text(), (
        "the sim model must carry the behaviour, not an empty shell")


def test_the_synth_path_appends_a_BLACKBOX_copy_not_the_model(tmp_path):
    """Synth must not elaborate the macro body into flops — that is the area
    blow-up the blackbox exists to prevent."""
    project, rtl = _project(tmp_path)
    m = HMS.staged_hardmacro_models(project, rtl)[0]
    stub = HMS.emit_blackbox_stub(m["v"], m["name"], tmp_path / "bb")
    assert stub.name == "memblk.bb.v"
    assert stub.read_text().count("(* blackbox *)") == 1
    assert stub != m["v"], "synth was handed the behavioural model"


def test_the_two_runner_sites_append_DIFFERENT_things():
    """The swap is invisible to every other test: give sim the blackbox and it
    simulates an empty shell; give synth the behavioural model and the macro
    body is elaborated into flops. Scanned per SITE, with comments stripped, so
    a rationale in a comment cannot satisfy it."""
    src = (_PROGRAMS / "design_one_shot_runner.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))

    def _site(marker):
        i = code.index(marker)
        seg = code[i:]
        return seg[:seg.index("\ndef ", 10)]

    sim = _site("def _reference_tb_generic_full_stack(")
    synth = _site("def step_yosys_synth(")
    assert 'rtl_files.append(_m["v"])' in sim, (
        "the sim compile set no longer gets the BEHAVIOURAL model")
    assert "_emit_hardmacro_blackbox_stub(" not in sim, (
        "sim was handed a blackbox — it would simulate an empty shell")
    assert "_emit_hardmacro_blackbox_stub(" in synth, (
        "synth no longer gets the BLACKBOX copy")
    assert 'rtl_files.append(_m["v"])' not in synth, (
        "synth was handed the behavioural model — the macro body elaborates "
        "into flops, which is the area blow-up the blackbox prevents")


def test_the_synth_injection_happens_after_the_662_reglob():
    """ORDER IS LOAD-BEARING and invisible to any unit test of the module: the
    #662 dependency pre-check RE-GLOBS `rtl_files`, so a stub appended before it
    is discarded and the macro goes back to `Unknown module type` with every
    test still green."""
    src = (_PROGRAMS / "design_one_shot_runner.py").read_text(encoding="utf-8")
    seg = src[src.index("def step_yosys_synth("):]
    seg = seg[:seg.index("\ndef ", 10)]
    reglob = seg.index("re-glob staged deps")
    inject = seg.index("_emit_hardmacro_blackbox_stub(")
    assert reglob < inject, (
        "the hard-macro stub is appended BEFORE the #662 re-glob, which "
        "discards it")


# ── call site 3: LEC ────────────────────────────────────────────────────────
def test_the_equiv_script_accepts_the_argument_lec_run_passes():
    """The call is made in a branch reached only by a real equiv run, and a
    signature drift would surface as a subprocess traceback that the step folds
    into a FAIL — reading as "the design does not match"."""
    lec = importlib.import_module("lec_run")
    params = inspect.signature(lec.build_equiv_script).parameters
    assert "blackbox_v" in params
    assert params["blackbox_v"].default is None, (
        "a non-None default would blackbox something on every run")


def test_lec_puts_the_stub_on_BOTH_sides(tmp_path):
    """The gold reads it as a source and the gate reads it as `blackbox_v`. On
    one side only, the miter compares a module against nothing."""
    src = (_PROGRAMS / "lec_run.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "gold_files = macro_blackbox_v + gold_files" in code, (
        "the stub no longer reaches the GOLD read")
    assert "blackbox_v=macro_blackbox_v or None" in code, (
        "the stub no longer reaches the GATE read")


def test_the_lec_timeout_knob_is_read_from_the_environment(monkeypatch):
    """`VIBEIC_LEC_YOSYS_TIMEOUT_S` is resolved at import, so it is the kind of
    knob that is easy to add and never exercised. Driven, including the
    unchanged default and a value that is not a number."""
    lec = importlib.import_module("lec_run")
    assert lec._env_yosys_timeout_default() == 7200
    monkeypatch.setenv("VIBEIC_LEC_YOSYS_TIMEOUT_S", "900")
    assert lec._env_yosys_timeout_default() == 900
    monkeypatch.setenv("VIBEIC_LEC_YOSYS_TIMEOUT_S", "not-a-number")
    assert lec._env_yosys_timeout_default() == 7200, (
        "a malformed budget must fall back, not raise into the step")
    monkeypatch.setenv("VIBEIC_LEC_YOSYS_TIMEOUT_S", "0")
    assert lec._env_yosys_timeout_default() == 7200


# ── the no-op promise, which is what makes this safe for every other design ──
def test_a_design_with_no_staged_root_reaches_none_of_it(tmp_path):
    project, rtl = _project(tmp_path, staged=False)
    assert HMS.staged_hardmacro_models(project, rtl) == []


def test_the_manifest_is_preferred_over_the_fallback(tmp_path):
    """Phase 1 records the roots; `input/pdk_local` is only the fallback. A
    design whose manifest names a DIFFERENT root must use it."""
    project, rtl = _project(tmp_path)
    other = project / "input" / "vendor_ip"
    other.mkdir(parents=True)
    (other / "memblk.v").write_text(
        "module memblk(input clk, input [7:0] d, output [7:0] q);\n"
        "endmodule\n", encoding="utf-8")
    ph1 = project / "phase1"
    ph1.mkdir(exist_ok=True)
    (ph1 / "pdk_staging_read.json").write_text(
        json.dumps({"staged_pdk_roots": ["input/vendor_ip"]}), encoding="utf-8")
    got = HMS.staged_hardmacro_models(project, rtl)
    assert [m["v"].parent.name for m in got] == ["vendor_ip"], got
