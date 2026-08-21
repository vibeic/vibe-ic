"""Dump the live two-axis 63x8 census per cell. Not a dimension module.

Run from the tests dir:
    T2_CENSUS_OUT=/tmp/out.json python3 -m pytest test_zzz_census_dump.py -q -s
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(0)


def test_dump_two_axis_census():
    out = Path(os.environ["T2_CENSUS_OUT"])
    import test_matrix_63x8_coverage as CV
    from matrix_63x8 import cells as C
    from matrix_63x8 import flowref as F

    doc = {
        "out": str(out),
        "python": sys.version.split()[0],
        "pytest": pytest.__version__,
        "audit_env": os.environ.get("VIBE_IC_MATRIX_AUDIT_JSON"),
        "corpus_env": os.environ.get("VIBE_IC_BENCHMARK_DATA"),
        "error": None,
    }
    try:
        src = C.audit_source()
        doc["audit_source"] = str(src) if src else None
    except Exception as exc:  # noqa: BLE001
        doc["audit_source"] = f"<error {exc}>"
    try:
        from _published_corpus import corpus_root
        r = corpus_root()
        doc["corpus_root"] = str(r) if r else None
    except Exception as exc:  # noqa: BLE001
        doc["corpus_root"] = f"<error {exc}>"

    try:
        t0 = time.time()
        doc["n_steps"] = len(F.step_ids())
        doc["expected_cells"] = CV.expected_cells()
        states = CV.state_census()
        t1 = time.time()
        doc["secs_state_axis"] = round(t1 - t0, 1)
        doc["state_only_counts"] = {
            s: sum(1 for v in states.values() if v == s) for s in CV.VALID_STATES}

        outcomes = CV.cell_outcomes()
        t2 = time.time()
        doc["secs_outcome_axis"] = round(t2 - t1, 1)
        doc["n_outcomes"] = len(outcomes)

        joined = CV.enforcement_census()
        doc["two_axis_counts"] = CV.enforcement_counter(joined)

        rows = []
        for (sid, dim), v in sorted(joined.items(),
                                    key=lambda kv: (kv[0][1], kv[0][0])):
            rows.append({
                "step": sid,
                "dim": dim,
                "dim_name": C.DIMENSION_NAMES[dim],
                "published_state": v.state,
                "expects": CV.STATE_EXPECTS_OUTCOME[v.state],
                "observed": list(v.outcomes),
                "agrees": v.agrees,
                "label": v.label,
            })
        doc["cells"] = rows
        doc["audit_verdicts"] = {
            f"{F.normalize_id(c.step_id)}/d{c.dim}": c.audit_verdict
            for c in C.ALL_CELLS
        }
    except BaseException as exc:  # noqa: BLE001
        doc["error"] = f"{type(exc).__name__}: {exc}"
        doc["traceback"] = traceback.format_exc()[-12000:]

    out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print("AUDIT_SOURCE:", doc.get("audit_source"))
    print("CORPUS_ROOT :", doc.get("corpus_root"))
    print("STATE_ONLY  :", doc.get("state_only_counts"))
    print("TWO_AXIS    :", doc.get("two_axis_counts"))
    print("ERROR       :", doc["error"])
    assert doc["error"] is None, doc["error"]
