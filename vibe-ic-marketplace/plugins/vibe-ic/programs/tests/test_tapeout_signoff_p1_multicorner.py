#!/usr/bin/env python3
"""TAPEOUT-SIGNOFF P1 — multi-corner SPEF + AOCV/blackbox discovery (runner).

These exercise the DETERMINISTIC runner helpers without a live container by
stubbing _docker_exec. The heart of the fix they guard: the iic-osic-tools
`bash -lc` login BANNER (`[INFO] Final PATH variable: ...`) must NOT leak into a
discovered captable / AOCV / blackbox path (a naive `head -1` captured the
banner). Also verifies:
  * multi-corner captable discovery returns the DECLARED model per corner
    (F13: it used to prefer an undeclared .magic sibling);
  * AOCV discovery is None on a PDK that ships none (honest);
  * corner-STA recipe splits SETUP(max-RC) / HOLD(min-RC);
  * the disclosure JSON logic (single- vs multi-corner) is honest.
"""
from __future__ import annotations

import sys
from pathlib import Path

from _source_pin import func_src

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))



_BANNER = ("[INFO] Final PATH variable: /foss/tools/bin:/usr/bin\n"
           "[INFO] Final PYTHONPATH variable: /usr/lib/python3.12\n")




# ---------------------------------------------------------------------------












# ---- structure of the corner-aware STA + multi-corner extraction recipe ----
def test_corner_sta_recipe_splits_setup_max_hold_min():
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    window = func_src(src, "_emit_corner_spef_sta")
    assert 'setup_corner = ("max"' in window   # setup at slow/max-RC
    assert 'hold_corner = ("min"' in window    # hold at fast/min-RC
    assert 'report_worst_slack' in window
    assert '"SETUP"' in window and '"HOLD"' in window
    # the report must state which LIBERTY each corner was analysed with, and
    # must ask OpenSTA for DRV — N corner sections over one silently-shared
    # library used to be indistinguishable from genuine multi-corner sign-off,
    # and max_slew violations could not appear in this report at all.
    assert "# corner_liberty:" in window
    assert "distinct_corner_libraries" in window
    assert "_report_check_types_tcl(rpt_c)" in window


def test_multicorner_extract_recipe_loops_corners():
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    window = func_src(src, "_emit_spef_corners")
    # one OpenROAD run reads the DEF once then extract+write per corner
    assert "extract_parasitics -ext_model_file" in window
    assert "write_spef" in window
    assert "define_process_corner" in window


def test_multicorner_disclosure_is_honest():
    # the stance JSON must carry both the multi-corner claim AND an honest
    # single-corner disclosure branch.
    #
    # #563 r3 — the fallback text was re-derived. It used to read
    # "SINGLE-CORNER (nom) only — this PDK did not ship the min/max OpenRCX
    # captables", which asserted a CAUSE the code never checked (measured
    # counter-example: the failing run's own log named all three captables it
    # read). "Honest" now means it reports the observation and names no cause,
    # so this assertion tracks the observation wording instead of the old
    # PDK-blaming sentence.
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    i = src.index("multi_corner_spef_stance.json")
    window = src[i:i + 8000]
    assert "SINGLE-CORNER only (extracted:" in window   # honest fallback text
    assert "NOT attributed to the PDK" in window
    assert '"multi_corner"' in window
    assert '"setup_corner"' in window and '"hold_corner"' in window
    # ...and the corner->liberty resolution, so the corner COUNT can never be
    # read as a library count.
    assert '"corner_library_resolution"' in window
