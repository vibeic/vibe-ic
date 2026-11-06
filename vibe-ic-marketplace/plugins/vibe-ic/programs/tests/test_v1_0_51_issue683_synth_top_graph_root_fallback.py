"""ORGANIC #683 — step_yosys_synth synth-top resolution lacked the
instantiation-graph-root fallback the TB resolver already has.

For a reused-IP / catalog-glue design whose Phase-1 doc-extraction lifts a
doc-prose integration top name into `L9.top_module` that is NOT a real staged
module (a PHANTOM top) and `L9.synth_top=null`, `step_yosys_synth`'s synth-top
precedence (waivers.phase2_synth_top → L9.synth_top → <top>_asic.sv → top_name)
resolves `synth_top='chip_top'` (caller default). No chip_top module exists, and
`_autoemit_chip_top_if_needed` BAILS 'genuinely ambiguous' on a multi-module
design → yosys `synth -top chip_top` → "chip_top is not a valid top-level module"
→ Phase-2 FAIL. The SAME-runner TB path `_v661_resolve_dut_module` HAS clause (c)
'unique instantiation-graph root' and resolves the real top correctly; the synth
step never called it.

Fix: in step_yosys_synth, ONLY when the precedence falls through to the runner
auto-wrapper name 'chip_top' AND no chip_top module is defined in staged rtl/,
call `_v661_resolve_dut_module(project, top_name, L9.top_module)` and, if it
returns a REAL instantiation-graph-root module, adopt it as synth_top. Pure
instantiation-graph structural detection; chip-AGNOSTIC.

POSITIVE: a reused-IP project with phantom L9.top_module + synth_top=null + no
chip_top module + a UNIQUE instantiation-graph root → step_yosys_synth adopts the
graph-root as synth_top (no 'chip_top is not valid' FAIL).
§4.05 NEGATIVE no-leak: a design WITH a real chip_top still uses chip_top (NOT
overridden); a design with a real L9.synth_top still uses it (precedence
preserved); a genuinely ambiguous multi-root design does NOT silently pick a
wrong root — the resolver returns None so it honestly bails/waives; the TB
resolver path is unchanged.

The fixtures embed the real repro SHAPE (phantom integration-top 'the_top' /
graph-root 'core' pattern, generalising the round-5 ibex_top→ibex_core case) with
generic names.
"""
import json
import shutil
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402
import _path_layout as _pl  # noqa: E402

#: THE CONTAINER IS DERIVED FROM THE PIN, NEVER SPELLED.
#
# The five end-to-end ids below used to pass the SHARED, host-global
# container name as a literal. A shared name is not an identity: whichever
# process got there first is holding it. `step_yosys_synth` runs the host
# yosys first and, when that yosys is too old for the script it emits, falls
# through to `_phase2_sv_synth_fallback`, which is CONTAINER-ONLY — so the
# verdict of a synth-TOP-RESOLUTION test was decided by whatever image
# somebody else's container of that name happened to be running.
#
# MEASURED 2026-09-10 on 8HD-9, the same file at the same tree 97990612f4:
#   pinned image (no docker on PATH -> local route)  8 passed
#   bare host   (docker present; a container holding
#                the shared name, up 4 days, running
#                sha256:06537f7e..., while the pin
#                requires sha256:89a8fd72...)        5 failed, 3 passed
# every one of the five raising `_container_exec.ContainerImageMismatch`.
# The three that passed are the resolver-unit ids, which never reach a tool.
#
# `_eda_pin.default_container_name()` derives the name FROM THE REQUIRED
# DIGEST, so it cannot be squatted by a container running other bytes.
# `test_the_run_path_resolves_the_pinned_image.py::test_no_shipped_file_
# names_the_shared_container_literal` already forbids the literal in every
# shipped program (42 sites before, 1 after — the definition itself), but
# its population helper `_shipped_py()` skips `tests/` by construction, so
# the test tree kept the defect the programs were cleaned of.

_HAVE_YOSYS = shutil.which("yosys") is not None

# ── reusable RTL bodies (generic names; phantom integration-top shape) ──────
_LEAF = """\
module {n} (
    input  wire clk,
    input  wire rst_n,
    output reg  [7:0] q
);
    always @(posedge clk or negedge rst_n)
        if (!rst_n) q <= 0; else q <= q + 1'b1;
endmodule
"""
_ROOT_WRAPPING = """\
module {root} (
    input  wire clk,
    input  wire rst_n,
    output wire [7:0] q
);
    {child} u_child (.clk(clk), .rst_n(rst_n), .q(q));
endmodule
"""


def _scaffold(tmp_path, rtl_files, l9, waivers=None):
    proj = tmp_path / "proj"
    rtl = _pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    for name, txt in rtl_files.items():
        (rtl / name).write_text(txt)
    gd = _pl.generated_docs_dir(proj)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj




# ── POSITIVE (resolver unit, no yosys needed) ───────────────────────────────

def test_resolver_picks_graph_root_for_phantom_top(tmp_path):
    """The structural resolver step_yosys_synth now consults returns the UNIQUE
    instantiation-graph root for a phantom L9.top_module."""
    proj = _scaffold(
        tmp_path,
        {"core.sv": _ROOT_WRAPPING.format(root="core", child="sub"),
         "sub.sv": _LEAF.format(n="sub")},
        {"top_module": "the_top", "synth_top": None})
    # top_name=chip_top is NOT a module here → falls through to graph root.
    assert R._v661_resolve_dut_module(proj, "chip_top", "the_top") == "core"
    # the phantom integration-top is NEVER returned.
    assert "the_top" not in set(R._v661_rtl_module_names(proj))


# ── POSITIVE (end-to-end through step_yosys_synth) ──────────────────────────



# ── §4.05 NEGATIVE no-leak ──────────────────────────────────────────────────







def test_noleak_ambiguous_multi_root_resolver_returns_none(tmp_path):
    """A genuinely ambiguous design (TWO instantiation-graph roots, no chip_top,
    phantom L9.top_module) → the resolver returns None, so the fallback does NOT
    silently pick a wrong root. (resolver-unit; no yosys needed.)"""
    proj = _scaffold(
        tmp_path,
        {"rootA.sv": _LEAF.format(n="rootA"),
         "rootB.sv": _LEAF.format(n="rootB")},
        {"top_module": "the_top", "synth_top": None})
    assert R._v661_resolve_dut_module(proj, "chip_top", "the_top") is None
