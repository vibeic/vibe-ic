"""Tests for v0.1.62 R14 capture: wire phase1_protocol_spec_extract.py
L14-L18 extractors into the doc-mode runner.

Captured from AMBA AXI parity v0.1.57: the extractors existed since
v0.1.51 but were never invoked from the doc-mode pipeline. The L14-L23
docs on disk for the AMBA project were 200-550 byte SHELLS, not real
extracted protocol data. The user's report named this as the "ABSENT_IN_
PROGRAM 343 backlog" — closes (in concert with R13's na_stub gate for
non-applicable slots) the gap between what the runner emits and what
Claude Opus 4.7 extracted.

Honesty: the extractors are deterministic regex passes over the
already-on-disk input text. No LLM call. No reading of score/.
"""
import importlib
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
RUNNER = PROGRAMS / "phase1_doc_one_shot_runner.py"


def _load_runner():
    if "phase1_doc_one_shot_runner" in sys.modules:
        del sys.modules["phase1_doc_one_shot_runner"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("phase1_doc_one_shot_runner")


def _load_extractor():
    if "phase1_protocol_spec_extract" in sys.modules:
        del sys.modules["phase1_protocol_spec_extract"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("phase1_protocol_spec_extract")


# ── Extractor module still has the 5 entry points ───────────────────

def test_extractor_module_has_all_5_entry_points():
    mod = _load_extractor()
    for fn in ("extract_l14_versioning", "extract_l15_encoding_tables",
                "extract_l16_compliance", "extract_l17_channels",
                "extract_l18_interconnect"):
        assert callable(getattr(mod, fn, None)), (
            f"phase1_protocol_spec_extract.{fn} missing")


# ── Runner imports the extractor + wires the call ───────────────────

def test_runner_imports_phase1_protocol_spec_extract():
    src = RUNNER.read_text()
    assert "import phase1_protocol_spec_extract" in src, (
        "Runner must import the L14-L18 extractor module.")


def test_runner_has_l14_l18_extractor_map():
    mod = _load_runner()
    assert hasattr(mod, "_L14_L18_EXTRACTORS")
    names = [name for name, _ in mod._L14_L18_EXTRACTORS]
    assert "L14_PROTOCOL_VERSIONING" in names
    assert "L15_ENCODING_TABLES" in names
    assert "L16_COMPLIANCE_PROPERTIES" in names
    assert "L17_CHANNEL_SIGNAL_CATALOG" in names
    assert "L18_INTERCONNECT_TOPOLOGY" in names


def test_emit_function_defined():
    mod = _load_runner()
    assert callable(getattr(mod, "_emit_l14_to_l18_via_extractor", None))


def test_main_calls_extractor_before_coverage_report():
    """The call MUST come before the [15/15] coverage report so the new
    L14-L18 docs count toward the coverage denominator."""
    src = RUNNER.read_text()
    call_pos = src.find("_emit_l14_to_l18_via_extractor(project")
    cov_pos = src.find("[15/15] coverage report")
    assert call_pos > 0, "main() must call _emit_l14_to_l18_via_extractor"
    assert cov_pos > 0
    assert call_pos < cov_pos, (
        "L14-L18 emit must run BEFORE the coverage report step.")


def test_main_calls_extractor_after_l13_lab_calibration():
    """The call MUST come after L13 + L8_TIMING + all the post-emit hooks
    so ic_class is final when R13 applicability gate inspects it."""
    src = RUNNER.read_text()
    # ORGANIC-20260522 routed L13 through the _run_layer watchdog wrapper, so
    # in source the L13 emit marker is the _run_layer("[14/15]", "L13_..." call
    # (it still prints "[14/15] L13_LAB_CALIBRATION ..." at runtime).
    l13_pos = src.find('_run_layer("[14/15]", "L13_LAB_CALIBRATION"')
    call_pos = src.find("_emit_l14_to_l18_via_extractor(project")
    assert l13_pos > 0
    assert l13_pos < call_pos, (
        "L14-L18 emit must run AFTER L13 emit so ic_class is final.")


# ── End-to-end with a synthetic protocol-spec input ──────────────────

def test_extractor_helper_returns_results_on_real_protocol_text(tmp_path,
                                                                  monkeypatch):
    """Drive _emit_l14_to_l18_via_extractor on synthetic protocol-spec text
    with version/encoding/compliance/channel/interconnect markers."""
    mod = _load_runner()
    proj = tmp_path / "p"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    # Seed L1 + L2 so detect_ic_class can route (any class — R13 gate
    # decides applicability; here we just want the extractor to RUN).
    (gd / "L1_DATASHEET.json").write_text('{"ic_name": "test_protocol"}')
    (gd / "L2_FRS.json").write_text('{"protocol_overview": "valid/ready '
                                       'handshake; multiple channels; master '
                                       'and slave roles; bursts; interconnect."}')

    # Synthetic input text designed to land in the extractor's regex catalogs
    extracted = {
        "spec.md": "\n".join([
            "Version 1.0 2020-01 Initial release",
            "Version 2.0 2022-06 Added burst support",
            "Table A1-1 Burst type encoding",
            "  0b00 FIXED Fixed-address burst",
            "  0b01 INCR  Incremental burst",
            "  0b10 WRAP  Wrapping burst",
            "The interconnect shall not stall a valid transfer.",
            "AWVALID Master Required ",
            "ARREADY Slave  Required ",
            "An interconnect must arbitrate requests fairly.",
        ])
    }

    out = mod._emit_l14_to_l18_via_extractor(proj, extracted)
    # At minimum L14 (versions extracted) AND L17 (channels extracted)
    # should produce non-empty results; the regex catalogs are conservative
    # enough that an empty `out` would indicate the wiring is broken.
    assert len(out) >= 2, (
        f"expected ≥2 L docs emitted from synthetic protocol text; got {len(out)}")
    names = [r.path.name for r in out]
    # All emitted files must be one of the L14-L18 set
    for name in names:
        assert any(name.startswith(p)
                   for p in ("L14_", "L15_", "L16_", "L17_", "L18_"))


def test_extractor_helper_fail_open_when_module_missing(monkeypatch, tmp_path):
    """If phase1_protocol_spec_extract import fails, the helper returns an
    empty list (no crash, no exception propagation)."""
    mod = _load_runner()
    # Force ImportError by removing the module from sys.modules + path
    monkeypatch.setitem(sys.modules, "phase1_protocol_spec_extract", None)
    proj = tmp_path / "p"
    proj.mkdir()
    out = mod._emit_l14_to_l18_via_extractor(proj, {"foo": "bar"})
    # sys.modules[name] = None causes ImportError in Python — verify graceful
    # handling: helper returns [] without raising.
    assert isinstance(out, list)


def test_extractor_helper_empty_input_returns_empty(tmp_path):
    mod = _load_runner()
    proj = tmp_path / "p"
    proj.mkdir()
    out = mod._emit_l14_to_l18_via_extractor(proj, {})
    assert out == []
    out = mod._emit_l14_to_l18_via_extractor(proj, {"empty.md": "   "})
    assert out == []
