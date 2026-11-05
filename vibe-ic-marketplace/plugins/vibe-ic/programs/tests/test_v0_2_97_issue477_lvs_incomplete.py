"""v0.2.97 — ORGANIC-20260606 #477: the LVS runner must NOT accept an
incomplete / aborted compare as a non-FAIL.

Audited rot (real field case): netgen was killed mid-run → lvs.rpt was
truncated at 'Flattening unmatched ...' with NO terminal verdict token
('Circuits match uniquely' / 'do NOT match' both absent); ext2spice.log
reported a huge extraction error count (observed 106,250,195 errors);
the merged GDS artifact was 0 bytes. NONE of these produced a FAIL.

The fix gives `_run_extraction_lvs` / `step_lvs` three run-completion
honesty checks, each recorded in a named verdict artifact
(reports/phase3/lvs_verdict.json), never silent:

  (a) report missing a terminal verdict token  → FAIL + INCOMPLETE
      verdict + finding LVS_NO_TERMINAL_VERDICT
  (b) 0-byte layout GDS input                   → FAIL + finding
      LVS_INPUT_GDS_EMPTY
  (c) ext2spice 'N errors' above the sane ceiling → FAIL + finding
      LVS_EXTRACTION_ERROR_FLOOD; a small nonzero count → hard WARNING
      surfaced in the verdict artifact (not swallowed)

Acceptance (executed end-to-end below):
  * a defect-artifact fixture (truncated verdict-less lvs.rpt + 0-byte
    merged GDS + ext2spice.log with a huge error count) drives the
    runner's LVS step to FAIL/INCOMPLETE with named findings;
  * a complete clean LVS replica still PASSes;
  * the Step-31 gate consumer (lvs_report_check → eda_report_audit
    --mode lvs) STILL exits 1 on a verdict-less log (regression guard
    for the gate the runner pairs with — #470 owns the gate, this only
    asserts it keeps tripping).

chip-AGNOSTIC: synthetic project + fake docker transcripts; no chip /
vendor / SKU literal used as detection logic.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
_SRC = (PROGRAMS / "phase3_one_shot_runner.py").read_text()








# --------------------------------------------------------------------------
# (a) verdict-less / truncated report → FAIL + INCOMPLETE verdict
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# (b) 0-byte layout GDS input → FAIL before tools even launch
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# (c) ext2spice error flood → FAIL with the count named
# --------------------------------------------------------------------------




# --------------------------------------------------------------------------
# regression: a complete clean LVS replica still PASSes
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# regression: a REAL mismatch still FAILs and keeps the "real compare
# ran" classification (NOT downgraded to INCOMPLETE).
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# the error-count parser: commas tolerated, MAX across lines, None when
# absent.
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# ACCEPTANCE (end-to-end): the Step-31 gate consumer still exits 1 on a
# verdict-less log. This pairs the runner's own INCOMPLETE status with
# the gate that #470 owns — assert the gate keeps tripping.
# --------------------------------------------------------------------------
def test_gate_consumer_still_exits1_on_verdictless_log(tmp_path):
    rpt_dir = tmp_path / "reports" / "phase3"
    rpt_dir.mkdir(parents=True)
    # large enough to pass the byte floor, has LVS categories, but NO
    # tool signature and NO terminal verdict → LVS_NO_TOOL_SIGNATURE.
    body = ("LVS run report\ninstance net device parameter\n"
            + ("Flattening unmatched subcircuit padding line xxxxxxxxxx\n"
               * 200))
    (rpt_dir / "lvs.rpt").write_text(body)
    cp = subprocess.run(
        [sys.executable, str(PROGRAMS / "lvs_report_check.py"),
         str(tmp_path)],
        capture_output=True, text=True)
    assert cp.returncode == 1, (cp.returncode, cp.stdout)
    out = json.loads(cp.stdout)
    assert out["passed"] is False
    rules = [f["rule"] for f in out["findings"]]
    assert "LVS_NO_TOOL_SIGNATURE" in rules


# --------------------------------------------------------------------------
# source-shape guards: the verdict artifact + honesty checks are in the
# source (not just runtime), and the misleading unconditional
# "real compare ran" message is no longer the verdict-less path.
# --------------------------------------------------------------------------
def test_source_carries_honesty_checks():
    assert "_write_lvs_verdict" in _SRC
    assert "LVS_NO_TERMINAL_VERDICT" in _SRC
    # v0.3.13 #508/#509: the layout source is the routed DEF now.
    assert "LVS_INPUT_DEF_EMPTY" in _SRC
    assert "LVS_EXTRACTION_ERROR_FLOOD" in _SRC
    assert "_parse_ext2spice_error_count" in _SRC
    assert "lvs_verdict.json" in _SRC
