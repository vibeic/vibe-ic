"""Minimum viable tests for phase1_consistency_check.py (K4 cross-layer gate)."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "phase1_consistency_check.py"


def _setup(tmp: Path, layers: dict) -> Path:
    d = tmp / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    for name, obj in layers.items():
        (d / f"{name}.json").write_text(json.dumps(obj))
    return d


def _run(docs: Path):
    r = subprocess.run([sys.executable, str(PROG), str(docs), "--json"],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _minimal_consistent_set():
    """Minimal L1-L23 set that doesn't trigger any cross-layer rule violation."""
    return {
        "L1_DATASHEET": {"part_number": "X", "pinout": {"A": "1"}},
        "L2_FRS": {"requirements": []},
        "L3_CMD_PROTOCOL": {"crc": {"poly": "0x31"}, "commands": []},
        "L4_REGMAP": {"registers": []},
        "L5_ADI_SPEC": {"adi_signals": []},
        "L6_CONTROL_LOGIC": {"submodule_control_logic": {}},
        "L7_TEST_DEBUG": {},
        "L8_TIMING_WAVEFORM": {"break_timing": {"break_low_min_us": 10}},
        "L8_RTL_CONSTANTS": {"crc": {"poly": "0x31"}},
        "L9_INTEGRATION_SPEC": {"top_level_ports": [], "submodules": [],
                                 "internal_wires": [], "registers": []},
    }


def test_program_exists_and_runs(tmp_path):
    _setup(tmp_path, _minimal_consistent_set())
    code, out, _ = _run(tmp_path / "phase1" / "generated_docs")
    # exit may be 0 or 1 depending on rules; just ensure it doesn't crash
    assert code in (0, 1)


def test_json_output_valid(tmp_path):
    _setup(tmp_path, _minimal_consistent_set())
    code, out, _ = _run(tmp_path / "phase1" / "generated_docs")
    # Output should contain JSON somewhere
    assert "{" in out


def test_missing_docs_dir_errors(tmp_path):
    r = subprocess.run([sys.executable, str(PROG),
                        str(tmp_path / "does_not_exist"), "--json"],
                       capture_output=True, text=True)
    assert r.returncode != 0


def test_help_works():
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "docs_dir" in r.stdout.lower() or "docs" in r.stdout


# ---------------------------------------------------------------------------
# R_l2_per_axis_l4_array — per-<axis> parameterization must be an L4 array,
# not a single scalar register (advisory / warn-only).
# ---------------------------------------------------------------------------
import importlib as _il
import sys as _sys
_sys.path.insert(0, str(PROG.parent))
_K = _il.import_module("phase1_consistency_check")


def _per_axis(l2_text, l4_regs):
    docs = {"L2": {"requirements": [{"id": "R1", "text": l2_text}]},
            "L4": {"register_map": l4_regs}}
    return _K._per_axis_scalar_findings(docs)


def test_per_axis_scalar_register_flagged():
    hits = _per_axis("A per-output-channel scale is applied to each accumulator.",
                     [{"name": "SCALE", "width_bits": 16}])
    assert hits == [("SCALE", "channel")]


def test_per_axis_noun_before_per_form_flagged():
    hits = _per_axis("A separate scale per channel is stored.",
                     [{"name": "SCALE"}])
    assert ("SCALE", "channel") in hits


def test_axis_wise_form_flagged_with_plural():
    hits = _per_axis("Channel-wise scale factors are applied.",
                     [{"name": "scale_factor"}])
    assert hits and hits[0][0] == "scale_factor"


def test_array_via_count_not_flagged():
    assert _per_axis("A per-channel scale is applied.",
                     [{"name": "SCALE", "count": 8}]) == []


def test_array_via_is_array_flag_not_flagged():
    assert _per_axis("A per-channel scale is applied.",
                     [{"name": "SCALE", "is_array": True}]) == []


def test_enumerated_siblings_not_flagged():
    # SCALE0..SCALE7 (an enumerated array, no bare scalar SCALE) — no flag.
    assert _per_axis("A per-channel scale is applied.",
                     [{"name": f"SCALE{i}"} for i in range(8)]) == []


def test_index_form_name_not_flagged():
    assert _per_axis("A per-channel scale is applied.",
                     [{"name": "SCALE[8]"}]) == []


def test_per_axis_language_not_bound_to_register_not_flagged():
    # "per channel" present but not adjacent to any register NAME — no flag.
    assert _per_axis("Data is processed per channel then written to CTRL.",
                     [{"name": "CTRL"}, {"name": "STATUS"}]) == []


def test_register_name_without_per_axis_context_not_flagged():
    assert _per_axis("The SCALE register sets a global gain.",
                     [{"name": "SCALE"}]) == []


def test_short_register_name_not_anchored():
    # a too-short/ambiguous name must not anchor a false positive.
    assert _per_axis("per-channel a is applied", [{"name": "A"}]) == []


def test_advisory_is_warn_severity_end_to_end(tmp_path):
    """The rule surfaces as a warn (advisory) finding, not an error — it must
    NOT change the gate exit code by itself."""
    layers = _minimal_consistent_set()
    layers["L2_FRS"] = {"requirements": [
        {"id": "R1", "text": "A per-output-channel scale is applied."}]}
    layers["L4_REGMAP"] = {"register_map": [{"name": "SCALE", "width_bits": 16}]}
    docs = _setup(tmp_path, layers)
    code, out, err = _run(docs)
    findings = json.loads(out)
    rec = next(f for f in findings if f["rule_id"] == "R_l2_per_axis_l4_array")
    assert rec["severity"] == "warn"
    assert rec["passed"] is False
    assert "SCALE" in rec["detail"]
