"""ORGANIC #663 [MEDIUM] — a disclosed FPGA board-skip (quartus_map_audit.json
verdict=SKIP, sof_present=false) auto-deferred ONLY the FPGA early-prototype
step (id 6). The FINAL on-board sign-off step (id 39) still hard-FAILed under
the canonical no-flag `--strict` audit (its gate is an all_of containing a
program_exit_zero attestation check that emits 'no-hardware-evidence'). The
asymmetry: identical board-absent signal → WAIVED-DEFERRED for one FPGA-board
step but a hard-FAIL for the other.

Root cause: `_synthesise_fpga_skip_waivers` hard-coded
`_ENV_UNAVAILABLE_STEP_NAME_TO_ID['fpga_early_prototype']` (id 6) only, while
the final-signoff id (39) is already in the renumber-proof board-step set
`_FPGA_BOARD_STEP_IDS` used by the --skip-hardware path.

Fix: iterate `_FPGA_BOARD_STEP_IDS` (derived from the canonical name->id
table) so the cap-gap auto-deferral is SYMMETRIC across all board steps. The
waiver-synthesis layer is the right place: the final-signoff gate is an all_of
with a program_exit_zero attestation that the #608 json_field_true self-skip
promotion never reaches; check_step's ENV_UNAVAILABLE fallback honours the
waiver and converts the natural FAIL → WAIVED-DEFERRED.

POSITIVE (#663): a disclosed FPGA skip auto-defers BOTH step 6 AND step 39.
KEEP #607 positive: step 6 still WAIVED.

NEGATIVE no-leak (issue-mandated): an UNDISCLOSED missing bitstream (no SKIP
self-report) must STILL hard-FAIL every board step.
  - no quartus_map_audit.json → no waiver for 6 or 39.
  - audit verdict != SKIP → no waiver.
  - sof_present claimed True → no waiver.
  - a genuine attestation FAIL on a non-board step is untouched.

Steps referenced by CANONICAL NAME via the name->id table (renumber-proof).
chip-AGNOSTIC: keyed on the runner's own SKIP self-report + structural step
roles, no chip name.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import flow_compliance_check as F  # noqa: E402

EARLY = F._ENV_UNAVAILABLE_STEP_NAME_TO_ID["fpga_early_prototype"]
FINAL = F._ENV_UNAVAILABLE_STEP_NAME_TO_ID["fpga_final_signoff"]

# A final-signoff-shaped step whose gate is an all_of containing a
# program_exit_zero attestation that will FAIL naturally (the attestation
# program is not invokable / no hardware evidence on disk).
FINAL_STEP = {
    "id": FINAL, "name": "FPGA on-board final sign-off", "stage": "stage4",
    "gate": {"all_of": [
        {"program_exit_zero":
            "fpga_on_board_attestation_check . --json reports/x.json"},
    ]},
}
EARLY_STEP = {
    "id": EARLY, "name": "FPGA early prototype", "stage": "stage1",
    "gate": {"files_exist": ["phase2/stage1/fpga/output_files/*.sof"]},
}


def _proj(tmp_path, audit=None):
    if audit is not None:
        d = tmp_path / "reports" / "phase2" / "fpga"
        d.mkdir(parents=True, exist_ok=True)
        (d / "quartus_map_audit.json").write_text(json.dumps(audit))
    return tmp_path


def _status(tmp_path, step):
    return F.check_step(tmp_path, step, F._load_waivers(tmp_path)).status


# ── structure: the fix derives from the renumber-proof board set ──────────
def test_final_signoff_id_in_board_step_set():
    assert FINAL in F._FPGA_BOARD_STEP_IDS
    assert EARLY in F._FPGA_BOARD_STEP_IDS


# ── POSITIVE: disclosed skip auto-defers BOTH board steps ─────────────────
def test_disclosed_skip_synthesises_waiver_for_both_board_steps(tmp_path):
    _proj(tmp_path, {"verdict": "SKIP", "sof_present": False})
    w = F._load_waivers(tmp_path)
    for sid in (EARLY, FINAL):
        assert sid in w, f"board step {sid} not auto-deferred"
        assert w[sid].get("_env_unavailable") is True
        assert w[sid].get("_fpga_skip") is True


def test_disclosed_skip_defers_final_signoff_step(tmp_path):
    # The #663 core symptom: final-signoff was a hard FAIL; now WAIVED-DEFERRED.
    _proj(tmp_path, {"verdict": "SKIP", "sof_present": False})
    assert _status(tmp_path, FINAL_STEP) == "WAIVED"


def test_keep_607_early_prototype_still_deferred(tmp_path):
    # #607 positive case must still pass (no regression).
    _proj(tmp_path, {"verdict": "SKIP", "sof_present": False})
    assert _status(tmp_path, EARLY_STEP) == "WAIVED"


# ── NEGATIVE no-leak: undisclosed missing bitstream still FAILs ───────────
def test_undisclosed_no_audit_final_signoff_still_fails(tmp_path):
    _proj(tmp_path, audit=None)
    w = F._load_waivers(tmp_path)
    assert FINAL not in w and EARLY not in w
    assert _status(tmp_path, FINAL_STEP) not in ("WAIVED", "PASS",
                                                 "SKIPPED-CONDITION")


def test_nonskip_verdict_final_signoff_still_fails(tmp_path):
    _proj(tmp_path, {"verdict": "FAIL", "sof_present": False})
    w = F._load_waivers(tmp_path)
    assert FINAL not in w
    assert _status(tmp_path, FINAL_STEP) not in ("WAIVED", "PASS")


def test_sof_present_claim_final_signoff_still_fails(tmp_path):
    _proj(tmp_path, {"verdict": "SKIP", "sof_present": True})
    w = F._load_waivers(tmp_path)
    assert FINAL not in w
    assert _status(tmp_path, FINAL_STEP) not in ("WAIVED", "PASS")


def test_genuine_nonboard_attestation_fail_untouched(tmp_path):
    # NO-LEAK: even WITH a disclosed FPGA skip, a non-board step that FAILs its
    # own gate is not waived (the skip only covers the board steps).
    _proj(tmp_path, {"verdict": "SKIP", "sof_present": False})
    nonboard = {
        "id": 31, "name": "Physical Verification (DRC/LVS/ERC)", "stage": "stage4",
        "gate": {"all_of": [
            {"program_exit_zero": "drc_check . --json reports/x.json"},
        ]},
    }
    w = F._load_waivers(tmp_path)
    assert 31 not in w
    assert F.check_step(tmp_path, nonboard, w).status not in ("WAIVED", "PASS")
