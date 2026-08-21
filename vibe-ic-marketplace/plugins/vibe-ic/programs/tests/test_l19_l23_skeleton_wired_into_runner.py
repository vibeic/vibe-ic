"""Tests for v0.1.63 R15 capture: wire phase1_post_process.emit_l_doc_skeleton
for L19-L23 into the doc-mode runner.

Captured from v0.1.62 GAP run: L19-L23 docs were absent from disk because
the runner has no extractor for them. For IC classes where L19+L22 are
applicable (bus_interconnect_protocol, cpu_core_isa, chip_otp_centric),
missing-on-disk surfaces as 'missing required L doc' FAILs downstream.

Fix pattern: same dead-code wiring as R11/R12/R13/R14 — the helper
existed since v0.1.51 but was never invoked from the runner pipeline.
"""
import importlib
import json
import sys
from pathlib import Path
from _hostpaths import require_repo  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]
RUNNER = PROGRAMS / "phase1_doc_one_shot_runner.py"


def _load_runner():
    if "phase1_doc_one_shot_runner" in sys.modules:
        del sys.modules["phase1_doc_one_shot_runner"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("phase1_doc_one_shot_runner")


def _load_post_process():
    if "phase1_post_process" in sys.modules:
        del sys.modules["phase1_post_process"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("phase1_post_process")


# ── Helper module still works ───────────────────────────────────────

def test_emit_l_doc_skeleton_returns_typed_envelope():
    mod = _load_post_process()
    for code in ("L19", "L20", "L21", "L22", "L23"):
        sk = mod.emit_l_doc_skeleton(code, "bus_interconnect_protocol")
        assert sk["doc_id"] == code
        assert sk["applicability"] == "APPLICABLE"
        assert sk["ic_class"] == "bus_interconnect_protocol"
        assert "fields" in sk
        assert sk["extraction_status"] == "NOT_YET_EXTRACTED"


def test_runner_imports_emit_l_doc_skeleton():
    src = RUNNER.read_text()
    assert "from phase1_post_process import emit_l_doc_skeleton" in src


def test_l19_l23_codes_and_names_map_populated():
    mod = _load_runner()
    assert hasattr(mod, "_L19_L23_CODES_AND_NAMES")
    pairs = dict(mod._L19_L23_CODES_AND_NAMES)
    assert pairs == {
        "L19": "L19_CONSTRAINTS_PDK",
        "L20": "L20_DFT_SCAN_TOPOLOGY",
        "L21": "L21_POWER_INTENT",
        "L22": "L22_VERIFICATION_PLAN",
        "L23": "L23_SECURITY_REQUIREMENTS",
    }


def test_helper_function_defined():
    mod = _load_runner()
    assert callable(getattr(mod, "_emit_l19_to_l23_skeletons", None))


# ── Driver call site ────────────────────────────────────────────────

def test_main_step_order_l14_l18_before_l19_l23_before_coverage():
    """The runner's main() step labels must appear in the correct order:
    [14c/15] L14-L18 → [14d/15] L19-L23 → [15/15] coverage. We search for
    the step-label strings (unique to main()) so the helper-definition
    sites (which appear elsewhere) don't confuse the diff."""
    src = RUNNER.read_text()
    l14_label_pos = src.find("[14c/15] L14-L18 protocol spec extract")
    l19_label_pos = src.find("[14d/15] L19-L23 skeleton emit")
    cov_pos = src.find("[15/15] coverage report")
    assert l14_label_pos > 0, "main() missing [14c/15] step label"
    assert l19_label_pos > 0, "main() missing [14d/15] step label"
    assert cov_pos > 0
    assert l14_label_pos < l19_label_pos < cov_pos, (
        f"steps out of order: 14c={l14_label_pos} 14d={l19_label_pos} "
        f"cov={cov_pos}")


# ── End-to-end ──────────────────────────────────────────────────────

def test_helper_emits_5_l_docs_for_bus_protocol(tmp_path):
    """When L1+L2 trigger bus_interconnect_protocol detection, the L19-L23
    emit chain produces 5 docs (R13 gate keeps L19+L22 as APPLICABLE
    skeletons, marks L20/L21/L23 as na_stub via the gate)."""
    arm = require_repo("benchmark-data/evaluation/phase1_parity/arm_aix/phase1/generated_docs")
    if not (arm / "L1_DATASHEET.json").is_file():
        import pytest
        pytest.skip("AMBA AXI benchmark not present on this host")
    mod = _load_runner()
    proj = tmp_path / "p"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    # Seed L1+L2 so detect_ic_class sees bus_interconnect_protocol
    (gd / "L1_DATASHEET.json").write_text((arm / "L1_DATASHEET.json").read_text())
    (gd / "L2_FRS.json").write_text((arm / "L2_FRS.json").read_text())

    out = mod._emit_l19_to_l23_skeletons(proj)
    assert len(out) == 5, f"expected 5 L19-L23 docs emitted; got {len(out)}"
    names = sorted(r.path.name for r in out)
    assert names == [
        "L19_CONSTRAINTS_PDK.json",
        "L20_DFT_SCAN_TOPOLOGY.json",
        "L21_POWER_INTENT.json",
        "L22_VERIFICATION_PLAN.json",
        "L23_SECURITY_REQUIREMENTS.json",
    ]
    # The applicable ones (L19, L22) should be APPLICABLE skeletons;
    # the non-applicable ones (L20, L21, L23) should be N/A via R13 gate.
    by_name = {r.path.name: r for r in out}
    l19 = json.loads(by_name["L19_CONSTRAINTS_PDK.json"].path.read_text())
    l20 = json.loads(by_name["L20_DFT_SCAN_TOPOLOGY.json"].path.read_text())
    assert l19.get("applicability") == "APPLICABLE", (
        f"L19 applicable to bus_interconnect_protocol; got {l19}")
    assert l20.get("applicability") == "N/A", (
        f"L20 N/A for bus_interconnect_protocol; got {l20}")


def test_helper_fail_open_when_skeleton_module_missing(monkeypatch, tmp_path):
    mod = _load_runner()
    monkeypatch.setitem(sys.modules, "phase1_post_process", None)
    proj = tmp_path / "p"
    proj.mkdir()
    out = mod._emit_l19_to_l23_skeletons(proj)
    assert isinstance(out, list)
