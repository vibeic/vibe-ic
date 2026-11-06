"""`sdc_gen` names its output `{top}.sdc` from a top it resolves PER RUN, so a
change in that resolution orphans the previous run's deck in the directory
`sdc_validator_check` globs — and step 8 then FAILs forever on a file
constraining a module the design does not declare.

Measured on the tracked corpus: 4 roots carry >=2 generated decks under
different `# Top entity:` names, and the validator grades every one of them
(`espi` FAIL(6), `mdio` FAIL(4), `usb_pd` FAIL(4) before any regeneration).

WHY THE FIX IS IN THE CONSUMER — AND WHAT THAT COSTS TO GET WRONG
==================================================================
The obvious fix is for the generator to delete its own superseded siblings.
It cannot: the only top it knows is the one IT resolved this run, which is
exactly the unstable quantity, and the resolution ladder (`--top-name`, else
a board wrapper, else `L9.top_module`, else the literal `chip_top`) can
resolve to a module the design does not contain at all. On the corpus's
`usb_pd`, `L9.top_module` is `usb_pd_engine` and `grep -rn "module
usb_pd_engine"` over the whole project returns nothing; the only staged tops
are `chip_top` and `usb_pd_bmc_phy`. A resolution-keyed deletion therefore
destroys `chip_top.sdc` — the deck for the module that EXISTS — and keeps the
deck for the phantom. On `ibex` the same inversion destroys a COMPLETE 56-line
deck (its own `create_clock` on the real top's `clk_i`, 36 `set_input_delay`).

So the survivor's IDENTITY is the property under test here, not the file
count. `test_the_deck_for_the_module_that_exists_survives_a_phantom_l9_top`
is the control that pins it: it goes RED against any fix that keys on the
per-run resolution instead of on what the project DECLARES.

BIDIRECTIONAL CONTROLS
======================
FORWARD (RED against the byte-identical pre-fix `sdc_validator_check`,
GREEN after):
  * `test_a_superseded_generator_deck_is_not_graded` — the base case.
  * `test_the_second_search_root_is_covered_too` — the SAME orphan under
    `phase2/stage2/constraints`. `_SEARCH_ROOTS` is TWO directories; a
    generator-side cleanup walks only `fpga_early_dir`, so it leaves this one
    exactly where it found it and step 8 still FAILs.
  * `test_every_deck_superseded_is_not_checked_never_pass` — the filter's
    empty-set case lands in the exit-2 tier. This one is dual-role: it is
    RED pre-fix (which reports exit 1), and it is also the guard that goes
    RED against any fix that lets an emptied set certify step 8 at exit 0.
  * `test_the_generator_banner_the_consumer_looks_for_is_the_one_it_writes`
    — drives `sdc_gen` and parses its real output with the checker's own
    reader, so emitter and checker cannot drift into two spellings of "is
    this file ours?". Necessarily post-fix-only: the shared reader is what
    the fix introduces.

REVERSE (GREEN pre-fix; they go RED only if the fix OVER-reaches — i.e. if
it becomes "grade fewer files until step 8 goes green", or "delete"):
  * `test_the_deck_for_the_module_that_exists_survives_a_phantom_l9_top` —
    the IDENTITY control described above. RED against a resolution-keyed fix.
  * `test_a_foreign_sdc_is_never_set_aside` — no generator banner, no
    ownership, no licence to ignore it.
  * `test_the_declared_top_deck_is_graded_even_if_the_rtl_lacks_that_module`
    — the deck this run is producing is graded whatever the module set says,
    so an incomplete current deck still FAILs.
  * `test_nothing_is_removed_from_disk` — RED against any fix that resolves
    this by deleting the orphan rather than declining to grade it.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent
SDC_GEN = PROGRAMS / "sdc_gen.py"


def _foreign_deck() -> str:
    """Hand-authored / third-party: no banner, so nobody owns it."""
    return ("# board team's extra constraints -- do not regenerate\n"
            "# Top entity: some_bench_harness\n"
            "create_clock -name clk50 -period 20.000 [get_ports {CLOCK_50}]\n")


def _scaffold(tmp_path: Path, *, l9_top: str,
              rtl_modules=("chip_top",)) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L8_RTL_CONSTANTS.json").write_text(
        json.dumps({"clock_mhz": 50}))
    (proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({
            "top_module": l9_top,
            "top_module_pins": [
                {"name": "clk", "mode": "input"},
                {"name": "reset_n", "mode": "input"},
                {"name": "data_i", "mode": "input"},
                {"name": "data_o", "mode": "output"},
            ],
        }))
    for mod in rtl_modules:
        (rtl / f"{mod}.v").write_text(
            f"module {mod}(input wire clk, input wire reset_n, "
            f"input wire [7:0] data_i, output wire [7:0] data_o);\n"
            f"endmodule\n")
    return proj


def _fpga(proj: Path) -> Path:
    d = proj / "phase2" / "stage1" / "fpga"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----- FORWARD -------------------------------------------------------


# ----- REVERSE: the IDENTITY of the survivor -------------------------


# ----- REVERSE: emitter/checker coupling -----------------------------

def test_the_generator_banner_the_consumer_looks_for_is_the_one_it_writes(
        tmp_path):
    """Drive `sdc_gen`, then parse its REAL output with the consumer's own
    reader. A source-text assertion would pass while the two drifted."""
    sys.path.insert(0, str(PROGRAMS))
    try:
        import sdc_constraints as sdc  # noqa: E402
    finally:
        sys.path.pop(0)

    proj = _scaffold(tmp_path, l9_top="chip_top")
    _fpga(proj)
    cp = _pr.run([sys.executable, str(SDC_GEN), str(proj), "--force"],
                        capture_output=True, text=True)
    assert cp.returncode == 0, f"{cp.stdout}\n{cp.stderr}"
    written = _fpga(proj) / "chip_top.sdc"
    assert written.is_file(), cp.stdout

    assert sdc.generated_top_entity_of(written) == "chip_top", (
        "the checker must recognise, in the generator's REAL output, both the "
        "banner that proves ownership and the top it claims — otherwise every "
        "deck reads as foreign and nothing is ever set aside")
    # And the reader refuses to claim what it did not write.
    assert sdc.generated_top_entity(_foreign_deck()) is None
