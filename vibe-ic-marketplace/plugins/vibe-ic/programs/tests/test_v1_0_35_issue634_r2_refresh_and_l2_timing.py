"""Round-2 regression for ORGANIC #634 — two phase1-time gaps the field agent's
reopen pinned (the v1.0.32 gate-side relaxation was DEAD CODE in the real flow,
and L2 was 1 typed field short):

(1) DEAD-CODE / ORDERING — the L5 sparse_analog_block_set / sparse_control_timing
    relaxation keys on ic_class, but detect_ic_class persisted
    ic_class=digital_arithmetic_primitive (has_analog=False) during EARLY
    per-L-doc emission, BEFORE L5 analog_blocks existed, and phase1 NEVER
    refreshed it (zero refresh=True calls). So the phase1-time field-count gate
    read the stale class and the analog relaxation never applied.
    FIX: after ALL L1-L13 docs (incl L5) are emitted, the runner calls
    detect_ic_class(project, refresh=True) to re-stamp reports/ic_class.json —
    re-inferring the now-correct class from the complete L docs. (This test
    pins the re-stamp MECHANISM: a converter project whose L5 carries analog
    blocks re-stamps to data_converter under refresh=True even if a stale class
    was persisted first.)

(2) L2 EXTRACTION-DEPTH — a data-converter's L2 architecture spec documents its
    timing surface in a `| fclk | 1.0 | MHz |` spec-table row, which the
    prose-frequency promotion never reached, leaving L2.timing_parameters empty
    and the field-count gate 1 typed field short of ≥15. FIX: gen_l2_frs folds
    the converter spec-table / scalar timing (the facet-(a) harvester) into
    L2.timing_parameters.

NEGATIVE no-leak: refresh is a no-op when there is no analog evidence (stays
the detected class); the L2 timing fold is empty when the input has no
spec-table / scalar timing (no fabrication, L2 stays short → FAILs).

chip-AGNOSTIC: registry/canonical classifier + spec-table SHAPE; no
chip/vendor/SKU literal.
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R          # noqa: E402
import ic_class_profile as ICP                  # noqa: E402
import l_doc_structured_field_count_check as G  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402


# ── (1) refresh re-stamp mechanism (dead-code root cause) ────────────────────

def test_refresh_restamps_converter_to_data_converter(tmp_path):
    """A converter project whose L1 declares an analog/mixed-signal class and
    whose L5 carries analog blocks + a digital serial readout re-stamps to
    data_converter under refresh=True — even though a STALE
    digital_arithmetic_primitive was persisted first (the early-emission
    artifact)."""
    proj = tmp_path / "proj"
    gd = ICP._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    # stale early persist (before L5 existed)
    (proj / "reports").mkdir(parents=True)
    (proj / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": "digital_arithmetic_primitive",
                    "has_analog": False}))
    # complete L docs now present
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "doc_class": "L1_DATASHEET", "class": "mixed_signal_adc",
        "description": "sigma-delta with Digital serial outputs OUT1..OUT6 "
                       "(+ dout serial)."}))
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({
        "doc_class": "L5_ADI_SPEC", "no_analog": False,
        "analog_blocks": [{"name": "mod", "type": "delta_sigma"}],
        "signaling_summary": "output 1-bit serial (OUTn / dout) digital "
                             "bitstream per channel"}))
    prof = ICP.detect_ic_class(proj, refresh=True)
    assert prof["ic_class"] == "data_converter"
    # re-persisted single source of truth is corrected
    assert json.loads((proj / "reports" / "ic_class.json").read_text())[
        "ic_class"] == "data_converter"


def test_runner_calls_refresh_after_l_docs():
    """The phase1 runner main() wires the refresh re-stamp (the fix is in the
    real flow, not just a helper)."""
    src = (R.__file__)
    text = Path(src).read_text(encoding="utf-8")
    assert "detect_ic_class as _v634r2_detect" in text
    assert "_v634r2_detect(project, refresh=True)" in text


# ── (2) L2 timing-fold extraction-depth fix ──────────────────────────────────

_CONVERTER_L2 = {
    "L2_architecture.md": (
        "## Functional Requirements\n\n"
        "| Parameter | Min | Typ | Unit |\n|---|---|---|---|\n"
        "| fclk | 0.1 | 1.0 | MHz |\n"
        "| Resolution | | 16 | bit |\n\n"
        "## Clock\nModulator clock.\n\n## Power\nAnalog 3.3V.\n\n"
        "## Interface\nDigital serial output.\n\n## Performance\nSNDR 90 dB.\n\n"
        "## Architecture\n2nd-order modulator.\n\n## Datapath\nDecimation.\n\n"
        "## Verification intent\n- check SNDR\n")
}


def test_l2_folds_converter_spec_table_timing(tmp_path):
    proj = tmp_path / "proj"
    R.gen_l2_frs(proj, _CONVERTER_L2)
    d = json.loads(
        (R._pl.generated_docs_dir(proj) / "L2_FRS.json").read_text())
    tp_names = [t.get("name") for t in (d.get("timing_parameters") or [])]
    assert "fclk" in tp_names, f"converter spec-table fclk not folded: {tp_names}"


def test_l2_no_timing_when_no_spec_table_NOLEAK(tmp_path):
    """No-fabrication: a doc with no spec-table / scalar timing folds nothing
    into L2.timing_parameters."""
    proj = tmp_path / "proj"
    R.gen_l2_frs(proj, {"x.md": "## A\nProse only. No spec table, no fclk.\n"})
    d = json.loads(
        (R._pl.generated_docs_dir(proj) / "L2_FRS.json").read_text())
    # the prose-frequency harvest may still find nothing; the fold must add 0
    assert all(t.get("extraction_strategy") not in (
        "spec_table_name_value_unit_v634", "converter_scalar_param_v634")
        for t in (d.get("timing_parameters") or []))


def test_real_round2_converter_l2_passes_if_present():
    """End-state on the REAL round-2 converter input (when the run dir is on
    disk): regenerating L2 from its input docs clears the ≥15 floor. SKIPs
    off-monorepo."""
    run = require_corpus("_bench6_v100_r2/u_hawaii_adc")
    docs_dir = run / "input" / "docs"
    if not docs_dir.is_dir():
        pytest.skip("real round-2 converter run dir not on disk")
    docs = {f.name: f.read_text(errors="ignore")
            for f in docs_dir.iterdir()
            if f.suffix.lower() in (".md", ".txt")}
    proj = Path(tempfile.mkdtemp()) / "proj"
    R.gen_l2_frs(proj, docs)
    d = json.loads(
        (R._pl.generated_docs_dir(proj) / "L2_FRS.json").read_text())
    ok, msg = G._check_l_doc(2, d, ic_class="data_converter")
    assert ok, f"real converter L2 still FAILs: {msg}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
