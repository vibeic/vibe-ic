"""ORGANIC #781 — the catalog-glue duplicate-module crash-gate fires on files
synth never compiles.

現象: a REUSED-IP / catalog-glue project whose vendor bundle keeps some sources
in a nested sub-path (e.g. the lowRISC Ibex bundle ships
``syn/rtl/prim_clock_gating.v``) gets that file staged BOTH flat in
``phase2/stage1/rtl/`` AND under its original relative sub-path. The staged tree
then holds two files declaring ``prim_clock_gating``.

``catalog_glue_closure_resolver._gather`` walks ``rglob`` — deliberately, so a
nested include-only header can chain a module into the closure. But the runner's
compile set (``design_one_shot_runner._select_asic_rtl_sources``) is a TOP-LEVEL
``glob``, NOT ``rglob``. So synth is handed exactly ONE ``prim_clock_gating.v``
and elaborates cleanly — yet the gate scanned the rglob set, found "2 staged
files", and hard-FAILed the run with
``CATALOG_GLUE_CLOSURE (#774): vendor bundle duplicate-module defect``.

The gate exists solely to pre-empt a raw yosys-slang "duplicate definition"
abort. A file the frontend never reads cannot produce that abort, so it must not
raise the gate. Empirically (ibex × sky130A, image 0.2.28): ``read_slang`` over
the real 23-file compile set elaborates ``chip_top`` with zero duplicate errors,
while the gate FAILed the run before synth was ever invoked.

Secondary defect, same site: the remediation printed bare ``p.name`` for both
sides, so the same-basename case rendered as the self-contradictory
"Canonical: prim_clock_gating.v ... drop variant/shim file(s):
prim_clock_gating.v" — an instruction that cannot be followed.

Fix: ``resolve()`` takes ``synth_files`` (the exact set the caller compiles) and
restricts duplicate REPORTING to it; closure resolution still uses the full
rglob walk. When omitted it falls back to top-level-glob semantics so the
standalone CLI agrees with the in-flow gate. ``_disp()`` renders the shortest
path suffix that actually distinguishes the colliding files.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import catalog_glue_closure_resolver as R  # noqa: E402


def _stage(rtl: Path, files: dict) -> None:
    for rel, text in files.items():
        p = rtl / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


# The 現象 shape: ONE vendor leaf staged twice — flat + under its原 sub-path.
_CGATE = ("module prim_clock_gating (input clk_i, input en_i, input test_en_i,"
          " output clk_o); assign clk_o = clk_i & (en_i | test_en_i);"
          " endmodule\n")
_NESTED_DUP = {
    "chip_top.sv": (
        "module chip_top (input clk, input en, output q);\n"
        "  core u_core (.clk(clk), .en(en), .q(q));\n"
        "endmodule\n"),
    "core.sv": (
        "module core (input clk, input en, output q);\n"
        "  prim_clock_gating u_cg (.clk_i(clk), .en_i(en),"
        " .test_en_i(1'b0), .clk_o(q));\n"
        "endmodule\n"),
    "prim_clock_gating.v": _CGATE,          # top level — synth COMPILES this
    "syn/rtl/prim_clock_gating.v": _CGATE,  # nested — synth NEVER reads it
}


def test_nested_copy_outside_compile_set_is_not_a_bundle_defect(tmp_path):
    """REPRODUCE: the duplicate lives only in the nested tail, which the
    top-level-glob compile set excludes → no crash is possible → PASS."""
    rtl = tmp_path / "rtl"
    _stage(rtl, _NESTED_DUP)

    rep = R.resolve("chip_top", rtl)

    assert rep["verdict"] == "PASS", rep
    assert rep["duplicates"] == []


def test_nested_copy_still_gathered_for_closure(tmp_path):
    """NO-LEAK: narrowing the DUPLICATE scope must not narrow the closure walk
    — the nested file is still gathered (headers chain in via `include)."""
    rtl = tmp_path / "rtl"
    _stage(rtl, _NESTED_DUP)

    gathered = R._gather(rtl)
    assert any(f.parent.name == "rtl" and "syn" in f.parts for f in gathered), \
        "nested sources must still participate in closure resolution"


def test_explicit_synth_files_scopes_the_gate(tmp_path):
    """The caller's compile set is authoritative: pass BOTH copies as the
    compile set and the gate MUST fire (synth really would see both)."""
    rtl = tmp_path / "rtl"
    _stage(rtl, _NESTED_DUP)

    both = [rtl / "prim_clock_gating.v", rtl / "syn" / "rtl" / "prim_clock_gating.v"]
    rep = R.resolve("chip_top", rtl, synth_files=both + [rtl / "chip_top.sv",
                                                         rtl / "core.sv"])
    assert rep["verdict"] == "DUPLICATE", rep
    msg = rep["duplicates"][0]["message"]
    # the remediation must name DISTINGUISHABLE paths, not "foo.v ... foo.v"
    assert "syn/rtl/prim_clock_gating.v" in msg, msg
    canon_part = msg.split("Canonical: ")[1].split(" ")[0]
    drop_part = msg.split("drop variant/shim file(s): ")[1].rstrip(".")
    assert canon_part != drop_part, f"self-contradictory remediation: {msg}"


def test_genuine_top_level_duplicate_still_fails(tmp_path):
    """NEGATIVE CONTROL: a real bundle defect — two DIFFERENT top-level files
    declaring the same module — is inside the compile set and must still be a
    hard-gated FAIL. The fix must not weaken #639/#774."""
    rtl = tmp_path / "rtl"
    _stage(rtl, {
        "chip_top.sv": ("module chip_top (input a, output b);\n"
                        "  leaf u (.a(a), .b(b));\nendmodule\n"),
        "leaf.sv": "module leaf (input a, output b); assign b = ~a; endmodule\n",
        "leaf_shim.sv": "module leaf (input a, output b); assign b = a; endmodule\n",
    })

    rep = R.resolve("chip_top", rtl)
    assert rep["verdict"] == "DUPLICATE", rep
    assert rep["duplicates"][0]["module"] == "leaf"


def test_disp_disambiguates_same_basename():
    """`_disp` renders the shortest suffix that distinguishes the peers."""
    a = Path("/x/rtl/prim_clock_gating.v")
    b = Path("/x/rtl/syn/rtl/prim_clock_gating.v")
    assert R._disp(a, [a, b]) != R._disp(b, [a, b])
    # a UNIQUE basename still renders as the bare name
    c = Path("/x/rtl/leaf.sv")
    d = Path("/x/rtl/leaf_shim.sv")
    assert R._disp(c, [c, d]) == "leaf.sv"


def test_top_not_found_reports_honestly_not_as_duplicate(tmp_path):
    """A top that does not exist must report TOP_NOT_FOUND — the pre-#781 code
    masked it as STAGED_DUPLICATE via the out-of-compile-set nested copy."""
    rtl = tmp_path / "rtl"
    _stage(rtl, _NESTED_DUP)

    rep = R.resolve("no_such_top", rtl)
    assert rep["verdict"] == "TOP_NOT_FOUND", rep


def test_step_yosys_synth_does_not_gate_on_nested_copy(tmp_path, monkeypatch):
    """INTEGRATION: step_yosys_synth must get PAST the closure gate to yosys
    when the only duplicate is a nested copy outside the compile set."""
    import design_one_shot_runner as P2

    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    _stage(rtl, _NESTED_DUP)

    calls = {"n": 0}

    def _sentinel_run(*a, **k):
        calls["n"] += 1
        return (1, "", "stub yosys ran")
    monkeypatch.setattr(P2, "_run", _sentinel_run)

    res = P2.step_yosys_synth(proj, top_name="chip_top")
    assert calls["n"] >= 1, "the #781 gate must not short-circuit before yosys"
    assert "CATALOG_GLUE_CLOSURE" not in res.detail, res.detail
