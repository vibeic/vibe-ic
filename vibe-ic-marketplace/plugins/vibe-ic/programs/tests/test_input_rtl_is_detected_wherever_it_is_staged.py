"""The `has_context` detector must see input RTL wherever a runner staged it.

`task_nature_route.classify_task_nature` states the consequence of getting this
one boolean wrong:

    "Prose hints refine WHICH transform, but never promote a context-bearing
     task to spec_generation -- that is the mistake that pushes a debug task
     through Phase 1."

The guard was written; the detector feeding it was blind. It read ONE directory,
`<project>/input/rtl/`, while the rest of the plugin reads TWO --
`phase1_doc_one_shot_runner`'s top-module extractor iterates
`(project/"input"/"rtl", project/"rtl")`, and `phase3_one_shot_runner`'s
clock-port scanner lists `rtl/` among its search roots. Every design staged at
`<project>/rtl/` was therefore reported as arriving with NO RTL, and the exact
mistake the docstring forbids happened silently.

Measured on 302 real CVDP problems staged through `cvdp_phase1_entry.py`
(which stages context RTL to `<case>/rtl/<path>`): 132 designs flipped
`rtl_present_at_input` False->True, and the class the detector was blindest on
-- functional_modification -- went from 0/55 correctly routed to 45/55, with
zero regressions and no new false positive on a genuine spec_generation task.
"""
import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "fpa_under_test", PROGRAMS / "flow_phase_attribution.py")
fpa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fpa)


def _project(tmp_path, name="p"):
    p = tmp_path / name
    (p / "input").mkdir(parents=True)
    (p / "input" / "phase1_prompt.md").write_text(
        "Modify the encoder to add a bypass mode.\n", encoding="utf-8")
    return p


def _write(p: Path, text="module m(); endmodule\n"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ── the defect: RTL staged at <project>/rtl/ ─────────────────────────────────
def test_rtl_staged_at_the_project_rtl_dir_is_seen(tmp_path):
    """THE REGRESSION. `cvdp_phase1_entry._stage_case` writes context RTL to
    `<case>/<relpath>`, i.e. `<case>/rtl/foo.sv`. Reading only `input/rtl/`
    reported 'no RTL' for all 55 functional_modification problems."""
    p = _project(tmp_path)
    _write(p / "rtl" / "encoder_64b66b.sv")
    assert fpa.rtl_present_at_input(p) is True


def test_the_routing_consequence_is_not_spec_generation(tmp_path):
    """The boolean is not the point -- the ROUTE it decides is."""
    p = _project(tmp_path)
    _write(p / "rtl" / "encoder_64b66b.sv")
    v = fpa.derive_routing(p)["verdict"]
    assert v["nature"] != "spec_generation", v
    assert v["source"] != "no_context_heuristic", v


def test_rtl_nested_below_the_rtl_dir_is_seen(tmp_path):
    """A design may stage `rtl/core/alu.v`, not only `rtl/alu.v`."""
    p = _project(tmp_path)
    _write(p / "rtl" / "core" / "alu.v")
    assert fpa.rtl_present_at_input(p) is True


# ── the shape that already worked must keep working ──────────────────────────
def test_the_declared_input_rtl_dir_still_counts(tmp_path):
    p = _project(tmp_path)
    _write(p / "input" / "rtl" / "dut.v")
    assert fpa.rtl_present_at_input(p) is True


# ── both tails: what must stay False ─────────────────────────────────────────
def test_a_project_with_no_rtl_anywhere_is_false(tmp_path):
    assert fpa.rtl_present_at_input(_project(tmp_path)) is False


def test_a_non_rtl_file_in_the_rtl_dir_is_not_rtl(tmp_path):
    """A file is RTL by SUFFIX. A README beside the sources is not a module to
    transform, and the old `any(d.glob("*"))` called it one."""
    p = _project(tmp_path)
    _write(p / "input" / "rtl" / "README.md", "notes\n")
    assert fpa.rtl_present_at_input(p) is False


def test_rtl_this_run_PRODUCED_is_not_rtl_the_design_ARRIVED_with(tmp_path):
    """`phase2/stage1/rtl/` is the emit directory. Admitting it would make the
    signal true for every project after Phase 2 has run, which would invert the
    routing on re-attribution instead of fixing it."""
    p = _project(tmp_path)
    _write(p / "phase2" / "stage1" / "rtl" / "top.sv")
    assert fpa.rtl_present_at_input(p) is False


# ── the duplicate must be gone, not merely corrected ─────────────────────────
def test_benchmark_dispatch_has_no_private_reimplementation(tmp_path):
    """A second inline copy is how the two views of one tree came to disagree.
    `benchmark_dispatch` must ASK the detector, not re-derive it."""
    src = (PROGRAMS / "benchmark_dispatch.py").read_text(encoding="utf-8")
    assert 'input" / "rtl").glob(' not in src, \
        "benchmark_dispatch re-implements the input-RTL check inline"
    assert src.count("fpa.rtl_present_at_input(") >= 2, \
        "benchmark_dispatch should route both call sites through the detector"
