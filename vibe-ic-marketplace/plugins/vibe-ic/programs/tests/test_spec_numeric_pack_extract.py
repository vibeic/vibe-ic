"""Tests for spec_numeric_pack_extract.extract — PROGRAM-FIRST structural
numeric-semantics (rounding/saturation) + packing/width-conversion extractor.

Coverage:
  (a) POSITIVE — a real rounding-mode sentence + a real width-ratio sentence,
      VERBATIM from the scout-assigned CVDP prompts, assert the mode / ratio
      items are recovered with the right structured fields.
  (b) §4.05 NEGATIVE — "perform the computation" with NO stated rounding mode
      or width ratio -> extract() returns [] (no leak from silence).
  (c) chip-AGNOSTIC — a chip/vendor rename of the prompt does not change the
      extracted structure (the extractor keys on numeric/idiom grammar, not on
      any chip/SKU literal).
"""
from __future__ import annotations

import spec_numeric_pack_extract as M
import pytest


def _width_helper_prompt(name="bits_for"):
    return (
        f"input wire [{name}(LIMIT)-1:0] index;\n"
        "// Function to calculate the ceiling of log2\n"
        f"function integer {name};\n"
        "input integer value;\nendfunction\n"
    )


@pytest.mark.parametrize("name", ["bits_for", "address_size", "dimension_bits"])
def test_log2_width_helper_is_not_runtime_rounding(name):
    modes = M._detect_rounding_modes(_width_helper_prompt(name))
    assert modes == []


def test_real_completion_document_width_helper():
    from _hostpaths import require_repo
    # Lives with its sibling fixtures under `programs/tests/fixtures/`. It was
    # added at `plugins/vibe-ic/tests/fixtures/` by v1.17.39 (5fc0b5bea), which
    # is the ONLY tracked file that directory has ever held — and that broke two
    # unrelated things at once: `picker_fixture_thrash_guard`'s premise test
    # (`the phantom tests directory is still absent`) and `run_tests.sh`, which
    # then listed a `tests` tier that collects no tests at all.
    path = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                        "programs", "tests", "fixtures", "real_benchmark",
                        "log2_width_helper.md")
    text = path.read_text()
    assert "Function to calculate the ceiling of log2" in text
    assert M._detect_rounding_modes(text) == []


def test_log2_width_helper_does_not_hide_later_real_ceiling():
    modes = M._detect_rounding_modes(
        _width_helper_prompt() + "Round towards positive infinity.")
    assert modes == [("round_ceiling", "Round towards positive infinity")]


def test_actual_logarithm_datapath_retains_ceiling_mode():
    prompt = _width_helper_prompt() + "assign result = bits_for(sample);\n"
    assert M._detect_rounding_modes(prompt) == [("round_ceiling", "ceiling")]


def test_logarithm_prose_without_elaboration_usage_retains_mode():
    assert M._detect_rounding_modes(
        "Compute the ceiling of log2 for the output result.") == [
            ("round_ceiling", "ceiling")]


def test_width_helper_cannot_hide_same_line_real_rounding():
    text = _width_helper_prompt().replace(
        "ceiling of log2", "ceiling of log2; rounding mode is ceiling")
    assert M._detect_rounding_modes(text) == [("round_ceiling", "ceiling")]


def test_real_uncovered_rounding_still_blocks_strict_cli(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    script = Path(M.__file__).with_name("spec_coverage_check.py")
    spec = tmp_path / "spec.md"
    tb = tmp_path / "tb.sv"
    spec.write_text("RUP: Round towards positive infinity (ceiling behavior).\n")
    tb.write_text('module tb; initial begin $display("PASS"); $finish; end endmodule\n')
    result = subprocess.run([sys.executable, str(script), "--spec", str(spec),
                             "--tb", str(tb), "--strict"], capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "round_ceiling" in result.stdout + result.stderr


def test_width_helper_no_longer_blocks_strict_cli(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    script = Path(M.__file__).with_name("spec_coverage_check.py")
    spec = tmp_path / "spec.md"
    tb = tmp_path / "tb.sv"
    spec.write_text(_width_helper_prompt())
    tb.write_text('module tb; reg [3:0] index; initial begin index=0; if(index!==0) $fatal; $finish; end endmodule\n')
    result = subprocess.run([sys.executable, str(script), "--spec", str(spec),
                             "--tb", str(tb), "--strict"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# (a) POSITIVE — real rounding-mode + real width-ratio sentences (VERBATIM)
# ---------------------------------------------------------------------------
def test_named_rounding_mode_round_to_nearest_even_verbatim():
    # VERBATIM from cvdp_copilot_rounding_0001.txt (Behavior > Rounding Modes).
    prompt = (
        "RNE: Round to the nearest value, with ties resolved by rounding to "
        "the nearest even.\n"
        "RTZ: Truncate the fractional part without rounding up.\n"
        "RUP: Round towards positive infinity (ceiling behavior).\n"
        "RDN: Round towards negative infinity (floor behavior).\n"
        "Set inexact = 1 if either roundin or stickyin is 1. "
        "Set cout = 1 if the rounded value exceeds the representable range. "
        "r_up indicates if rounding up occurred."
    )
    items = M.extract(prompt)
    modes = {it["mode"] for it in items if it["kind"] == "rounding_mode"}
    assert "round_to_nearest_even" in modes
    assert "round_toward_zero" in modes
    assert "round_ceiling" in modes
    assert "round_floor" in modes

    # the RNE item carries the tie-break + the status flags it states
    rne = next(it for it in items
               if it.get("mode") == "round_to_nearest_even")
    assert "tie_break" in rne and "even" in rne["tie_break"].lower()
    assert set(rne.get("status_flags", [])) == {"inexact", "cout", "r_up"}

    # §4.05: a tie-break is NOT attached to a deterministic (non-nearest) mode
    rtz = next(it for it in items if it.get("mode") == "round_toward_zero")
    assert "tie_break" not in rtz


def test_width_ratio_downscale_verbatim():
    # VERBATIM from cvdp_copilot_axi_stream_downscale_0001.txt.
    prompt = (
        "Complete the given partial SystemVerilog code for an AXI stream data "
        "digital circuit conversion that supports downscaling for single-"
        "channel input data from a higher 16-bit width to a smaller width of "
        "8-bits."
    )
    items = M.extract(prompt)
    wc = [it for it in items if it["kind"] == "width_convert"]
    assert len(wc) == 1
    it = wc[0]
    assert it["in_width"] == 16
    assert it["out_width"] == 8
    assert it["ratio"] == "2:1"
    assert "down" in it["direction"].lower()


def test_width_ratio_upscale_verbatim():
    # VERBATIM from cvdp_copilot_axi_stream_upscale_0001.txt.
    prompt = (
        "A AXI stream data upsizer is a digital circuit used to upscale "
        "single-channel input data from a smaller 24-bit width to a larger "
        "width of 32-bits, supporting features like sign extension."
    )
    items = M.extract(prompt)
    wc = [it for it in items if it["kind"] == "width_convert"]
    assert len(wc) == 1
    it = wc[0]
    assert (it["in_width"], it["out_width"]) == (24, 32)
    assert it["ratio"] == "3:4"
    assert "up" in it["direction"].lower()


def test_concat_pack_and_split_unpack_verbatim():
    # VERBATIM from cvdp_copilot_concatenate_0001.txt (PROCESS state).
    prompt = (
        "Concatenates six 5-bit input vectors into a single 30-bit bus, "
        "appends two 1 bits at the LSB to form a 32-bit bus, and splits it "
        "into four 8-bit output vectors."
    )
    items = M.extract(prompt)
    packs = [it for it in items if it["kind"] == "width_convert"]
    # one concat (6x5 -> 30) and one split (32 -> 4x8)
    concat = next(it for it in packs if it.get("n_inputs"))
    assert concat["n_inputs"] == 6
    assert concat["member_width"] == 5
    assert concat["out_width"] == 30  # 6*5 (stated total 30 captured)

    split = next(it for it in packs if it.get("n_outputs"))
    assert split["n_outputs"] == 4
    assert split["member_width"] == 8
    assert split["in_width"] == 32


def test_bitslice_width_pick_verbatim():
    # VERBATIM from cvdp_copilot_gaussian_rounding_div_0005.txt.
    prompt = (
        "In step 2 of Gold-Schmidt algorithm the multiplication output can be "
        "up to 48 bits long. However we select only the middle 18 bits for the "
        "next stage of computation which is bits [26:9]."
    )
    items = M.extract(prompt)
    wc = [it for it in items if it["kind"] == "width_convert"]
    assert len(wc) == 1
    it = wc[0]
    assert it["slice_hi"] == 26
    assert it["slice_lo"] == 9
    assert it["out_width"] == 18          # 26-9+1
    assert it["in_width"] == 48           # "48 bits long"


def test_byte_order_with_byte_enable_lanes_verbatim():
    # VERBATIM fragments from cvdp_copilot_wb2ahb_0001.txt.
    prompt = (
        "sel_i[3:0]: Byte enables to select which bytes are active.\n"
        "Perform endian conversion for read and write data between Wishbone "
        "and AHB. Convert between Wishbone's little-endian format and AHB's "
        "data handling."
    )
    items = M.extract(prompt)
    bo = [it for it in items if it["kind"] == "byte_order"]
    assert len(bo) == 1
    it = bo[0]
    assert "endian" in it["byte_order"]
    assert it["byte_enable_lanes"] == 4   # sel_i[3:0] -> 4 lanes


def test_saturation_on_overflow():
    # An explicit ACTIVE saturate-on-overflow requirement.
    prompt = ("The accumulator must saturate to its maximum value on overflow "
              "rather than wrapping around.")
    items = M.extract(prompt)
    sat = [it for it in items if it["kind"] == "saturation"]
    assert len(sat) == 1
    assert "saturat" in sat[0]["coverage_tokens"]


# ---------------------------------------------------------------------------
# (b) §4.05 NEGATIVE — silence yields nothing
# ---------------------------------------------------------------------------
def test_no_stated_mode_or_ratio_returns_empty():
    # No named rounding mode, no stated width ratio, no endian token.
    prompt = ("Perform the computation and drive the result onto the output "
              "port. The module adds two operands and registers the sum on the "
              "rising clock edge.")
    assert M.extract(prompt) == []


def test_around_does_not_fire_rounding():
    # 'around' / 'wrap around' must NOT be misread as a rounding mode, and a
    # bare 'wrap around' is not the active saturate verb. §4.05 no-leak.
    prompt = ("The read pointer wraps around the circular buffer; route the "
              "clock around the macro keep-out region.")
    assert M.extract(prompt) == []


def test_floorplan_and_building_floors_do_not_fire_rounding():
    """Physical/layout and building-floor prose is not numeric rounding."""
    prompt = (
        '"floorplan_hints": []\n'
        "Route around the floorplan macro and preserve the floorplanning "
        "constraints. The elevator starts at the ground floor and reports "
        "the current floor."
    )
    assert M.extract(prompt) == []


def test_floor_number_is_not_a_rounding_mode():
    prompt = (
        "Convert a binary floor number input into a multi-digit BCD "
        "representation and display the current floor number."
    )
    assert M.extract(prompt) == []


def test_lint_truncation_is_not_a_rounding_mode():
    prompt = (
        "Perform a LINT code review addressing truncation of bits when "
        "assigning values and width mismatch in assignments."
    )
    assert M.extract(prompt) == []


def test_floor_rounding_requires_explicit_numeric_context():
    prompts = (
        "Use floor rounding for negative quotients.",
        "Rounding mode: floor.",
        "Floor the result before assignment.",
        "Apply the floor function to the output.",
    )
    for prompt in prompts:
        modes = {it.get("mode") for it in M.extract(prompt)
                 if it["kind"] == "rounding_mode"}
        assert modes == {"round_floor"}, prompt


def test_arithmetic_truncation_requires_explicit_numeric_context():
    prompts = (
        "RTZ: Truncate the fractional part without rounding up.",
        "Rounding truncates.",
        "Truncation toward zero is required for the quotient.",
    )
    for prompt in prompts:
        modes = {it.get("mode") for it in M.extract(prompt)
                 if it["kind"] == "rounding_mode"}
        assert "round_toward_zero" in modes, prompt


def test_unstated_division_returns_empty():
    # A non-restoring INTEGER division (cvdp_copilot_gaussian_rounding_div_0003
    # shape) states NO named rounding mode and NO width ratio -> []. This is the
    # honest §4.05 outcome: the topic word "division" is not a mode.
    prompt = ("Implement an iterative non-restoring division of dividend by "
              "divisor producing a quotient and remainder. Shift left the "
              "concatenation of A and Q by 1 bit each iteration and check the "
              "sign bit of A.")
    assert M.extract(prompt) == []


def test_empty_and_non_string_inputs():
    assert M.extract("") == []
    assert M.extract(None) == []          # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# (c) chip-AGNOSTIC — a chip/vendor rename does not change the structure
# ---------------------------------------------------------------------------
def test_chip_agnostic_rename_invariance():
    base = (
        "Round to the nearest value, with ties resolved by rounding to the "
        "nearest even. Downscale the data from a 32-bit width to a smaller "
        "width of 8-bits."
    )
    # rename every proper-noun-ish token to an unrelated vendor/SKU; the
    # numeric/idiom grammar the extractor keys on is unchanged.
    renamed = (
        "Round to the nearest value, with ties resolved by rounding to the "
        "nearest even. Downscale the AcmeChip XK-9000 data from a 32-bit width "
        "to a smaller width of 8-bits."
    )
    a = M.extract(base)
    b = M.extract(renamed)

    def _shape(items):
        return sorted(
            (it["kind"], it.get("mode"), it.get("in_width"),
             it.get("out_width"), it.get("ratio"))
            for it in items
        )

    assert _shape(a) == _shape(b)
    # and the structure is the expected one
    kinds = {it["kind"] for it in a}
    assert kinds == {"rounding_mode", "width_convert"}
    wc = next(it for it in a if it["kind"] == "width_convert")
    assert (wc["in_width"], wc["out_width"], wc["ratio"]) == (32, 8, "4:1")


# ── polarity: a spec states a RETIRED width as readily as a live one (#712) ──
#
# Found by `prose_polarity_census`, which counts extractors the blocking gate
# cannot see. `_detect_width_pairs` published both of these as EXPLICIT stated
# pairs, and a caller receiving one cannot tell it from a live statement.

def _pairs(text):
    import spec_numeric_pack_extract as M
    return {(a, b) for a, b, _ in M._detect_width_pairs(text)}


def test_a_retired_width_pair_is_not_published_as_stated():
    assert _pairs("The path from 8-bit to 16-bit is no longer supported.") == set()


def test_an_explicitly_negated_width_pair_is_not_published():
    assert _pairs("The block does not pack from 8-bit to 16-bit.") == set()


def test_a_denial_does_not_refuse_a_LIVE_pair_beside_it():
    """The other direction, and the one this fix nearly broke. The shared
    vocabulary breaks on ". " and not on ".\\n", so the scope of the live match
    reached back over the full stop into the denial and refused it -- returning
    NOTHING for a document that plainly states 8 to 32."""
    text = ("The path from 8-bit to 16-bit is no longer supported.\n"
            "Data is packed from 8-bit to 32-bit words.")
    assert _pairs(text) == {(8, 32)}


def test_a_denial_wrapped_across_two_lines_is_still_a_denial():
    """`"\\n"` alone would have been the wrong break: a spec wraps mid-sentence,
    and breaking on every newline misses this -- an under-reach that publishes a
    denied value, which is the failure being fixed."""
    assert _pairs("The path from 8-bit to 16-bit is no\nlonger supported.") == set()


def test_a_plainly_stated_pair_is_still_published():
    """The control arm. A fix that refused everything would pass the four tests
    above and be worthless."""
    assert _pairs("Data is packed from 8-bit to 32-bit words.") == {(8, 32)}


# ── polarity for the siblings of the guarded width-pair reader (#712) ───────
#
# `_detect_width_pairs` was guarded and its ten siblings were not, so one spec
# was read by two rules. Byte order and rounding are what the arithmetic IS.

def test_a_retired_byte_order_is_not_read_as_stated():
    assert M._detect_byte_order(
        "Little-endian packing is no longer used.\n"
        "The packing is big-endian.") == "big-endian"


def test_a_retired_saturation_requirement_is_not_evidence_for_it():
    """It returned the sentence RETIRING saturation as the evidence FOR it."""
    assert M._detect_saturation(
        "Saturation on overflow is no longer used; the result wraps.") is None


def test_a_retired_rounding_mode_is_dropped_and_the_live_one_kept():
    assert M._detect_rounding_modes(
        "Round-half-up is no longer used.\nRounding truncates.") \
        == [("round_toward_zero", "truncates")]


def test_a_MODE_DESCRIPTION_containing_a_negative_word_is_not_a_denial():
    """The false refusal this nearly shipped, caught by the suite. VERBATIM from
    the corpus: "RTZ: Truncate the fractional part without rounding up." The
    full negation vocabulary reads "without" and drops a correctly stated mode,
    so the rounding path asks only whether the mode was RETIRED.

    What that misses is stated in `_first_not_retired`: "does not use
    round-half-up" is not caught, because the vocabulary that catches it is the
    one that breaks this line."""
    modes = {t for t, _ in M._detect_rounding_modes(
        "RTZ: Truncate the fractional part without rounding up.\n")}
    assert "round_toward_zero" in modes
