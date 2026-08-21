"""ORGANIC #607 [MEDIUM] — for an IC class the runner intentionally FPGA-SKIPs
(no DE10 board-pin contract / no Quartus on host), the FPGA early-prototype
compliance step hard-required phase2/stage1/fpga/output_files/*.sof with no
platform-capability-gap branch. The step FALSE-FAILed and cascaded
blocked-by-upstream across stage2/stage3 → Overall:FAIL — even though the runner
ALREADY discloses the skip (quartus_map_audit.json verdict=SKIP,
sof_present=false). Unlike the PDK-substitution case (#496), there was no
auto-synthesis of the deferral from that self-report.

Fix: `_synthesise_fpga_skip_waivers` auto-adds an ENV_UNAVAILABLE-tier cap-gap
waiver for the FPGA early-prototype step when the disclosed-skip predicate holds
(quartus_map_audit.json verdict==SKIP AND sof_present==False), mirroring
`_synthesise_pdk_substitution_waivers`. check_step's existing fallback then
converts the natural MISSING (.sof absent) → WAIVED-DEFERRED (not FAIL, not
blocking).

POSITIVE (#607): a disclosed FPGA skip with no .sof → step WAIVED.

NEGATIVE no-leak (issue-mandated — an UNDISCLOSED missing .sof must still FAIL):
  - no quartus_map_audit.json → FAIL.
  - audit verdict != SKIP (e.g. FAIL) → FAIL.
  - sof_present claimed True but .sof absent → FAIL.
  - a real .sof present → PASS (waiver moot).

The step is referenced by CANONICAL NAME via the name->id table (renumber-proof).
chip-AGNOSTIC: keyed on the runner's own SKIP self-report, no chip name.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import flow_compliance_check as F  # noqa: E402

EARLY = F._ENV_UNAVAILABLE_STEP_NAME_TO_ID["fpga_early_prototype"]
STEP6 = {"id": EARLY, "name": "FPGA early prototype", "stage": "stage1",
         "gate": {"files_exist": ["phase2/stage1/fpga/output_files/*.sof"]}}


def _proj(tmp_path, audit=None, with_sof=False):
    if audit is not None:
        d = tmp_path / "reports" / "phase2" / "fpga"
        d.mkdir(parents=True)
        (d / "quartus_map_audit.json").write_text(json.dumps(audit))
    if with_sof:
        d = tmp_path / "phase2" / "stage1" / "fpga" / "output_files"
        d.mkdir(parents=True)
        (d / "top.sof").write_text("SOF\n")
    return tmp_path


def _status(tmp_path):
    return F.check_step(tmp_path, STEP6, F._load_waivers(tmp_path)).status


def test_predicate_disclosed_skip():
    import tempfile
    p = _proj(Path(tempfile.mkdtemp()), {"verdict": "SKIP", "sof_present": False})
    assert F._fpga_skip_disclosed(p) is True
    p2 = _proj(Path(tempfile.mkdtemp()), {"verdict": "FAIL", "sof_present": False})
    assert F._fpga_skip_disclosed(p2) is False
    p3 = _proj(Path(tempfile.mkdtemp()), {"verdict": "SKIP", "sof_present": True})
    assert F._fpga_skip_disclosed(p3) is False
    import tempfile as _t
    assert F._fpga_skip_disclosed(Path(_t.mkdtemp())) is False  # no audit


def test_disclosed_skip_synthesises_waiver(tmp_path):
    _proj(tmp_path, {"verdict": "SKIP", "sof_present": False})
    w = F._load_waivers(tmp_path)
    assert EARLY in w and w[EARLY].get("_env_unavailable") is True
    assert w[EARLY].get("_fpga_skip") is True


def test_disclosed_skip_waives_step(tmp_path):
    _proj(tmp_path, {"verdict": "SKIP", "sof_present": False,
                     "evidence": "fpga_compile not run"})
    assert _status(tmp_path) == "WAIVED"


def test_undisclosed_no_audit_still_fails(tmp_path):
    _proj(tmp_path, audit=None)
    assert _status(tmp_path) not in ("WAIVED", "PASS", "SKIPPED-CONDITION")


def test_nonskip_verdict_still_fails(tmp_path):
    _proj(tmp_path, {"verdict": "FAIL", "sof_present": False})
    assert _status(tmp_path) not in ("WAIVED", "PASS")


def test_sof_present_claim_but_absent_still_fails(tmp_path):
    _proj(tmp_path, {"verdict": "SKIP", "sof_present": True})
    assert _status(tmp_path) not in ("WAIVED", "PASS")


def test_real_sof_present_passes(tmp_path):
    _proj(tmp_path, {"verdict": "SKIP", "sof_present": False}, with_sof=True)
    assert _status(tmp_path) == "PASS"
