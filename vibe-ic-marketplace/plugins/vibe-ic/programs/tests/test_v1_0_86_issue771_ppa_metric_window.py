#!/usr/bin/env python3
"""ORGANIC #771 [P2 structural real_gap] — two prompt parsers in the SAME ppa
gate file disagreed on the EXACT prompt: `parse_threshold_from_prompt` used a
±60-char metric window, but `_nearest_metric_for_pct` (the clause parser's
backward fallback) used only 40 chars. An explicitly single-metric spec whose
metric word sat 41-60 chars before the '%' silently degraded to the conservative
`both` bind → a correct wire-only / cell-only optimization received a vacuous
NOT-APPLICABLE verdict (no enforcement of the spec's explicit success criterion).

Fix: widen the backward window 40→60 to match the single-tuple parser, AND
collapse to `both` when BOTH metric words co-occur in the (now wider) window with
no clause break — so a true "both cells and wires by N%" spec is not mis-bound to
the nearer single metric (the widening's own no-leak boundary).

§4.05 NO-LEAK: this is a STRUCTURAL real_gap — it must KEEP blocking once fixed.
A multi-clause "cells by 20% OR wires by 12%" must still split into two clauses;
a true "both" spec must stay `both`.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import ppa_area_threshold_check as P  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


def _clauses(txt):
    return P.parse_threshold_clauses_from_prompt(txt)[0]


# ── NEW-PATH: single-metric specs bind correctly (no degrade to 'both') ──────
def test_771_wire_only_binds_wires():
    txt = ("Reduce the interconnect, specifically the number of wires used. "
           "The minimum reduction must be 50% for this to count.")
    assert P.parse_threshold_from_prompt(txt) == (50.0, "wires")
    assert _clauses(txt) == [(50.0, "wires")]


def test_771_cell_only_binds_cells():
    txt = "Cut down on the cell count. A reduction of at least 70% is required."
    assert _clauses(txt) == [(70.0, "cells")]


def test_771_two_sentence_phrasing_binds_single_metric():
    txt = "Use fewer wires.\nThe area reduction threshold must be 60%."
    assert _clauses(txt) == [(60.0, "wires")]


# ── §4.05 NO-LEAK: a true 'both' spec must STAY both (the widening must not
#    mis-bind it to the nearer single metric) ──────────────────────────────────
def test_771_noleak_true_both_stays_both():
    txt = "Reduce both cells and wires by at least 30%."
    assert P.parse_threshold_from_prompt(txt) == (30.0, "both")
    assert _clauses(txt) == [(30.0, "both")]


# ── §4.05 NO-LEAK: a genuine multi-clause spec must STILL split ──────────────
def test_771_noleak_multiclause_or_still_splits():
    txt = "Cells must drop by 20% or wires by 12%."
    cl, comb = P.parse_threshold_clauses_from_prompt(txt)
    assert sorted(cl) == [(12.0, "wires"), (20.0, "cells")], cl
    assert comb == "or"


def test_771_noleak_multiclause_and_still_splits():
    txt = "Reduce cells by 25% and wires by 15%."
    cl, _ = P.parse_threshold_clauses_from_prompt(txt)
    assert sorted(cl) == [(15.0, "wires"), (25.0, "cells")], cl


def _container_up(container: str = "vibeic-eda") -> bool:
    """Is a RUNNING container of that name exec-able?

    `--type=container` matters: a bare `docker inspect vibeic-eda` also resolves
    the IMAGE of that name (which is exactly our image), so it reports success
    on any host that merely has the image pulled.
    """
    if shutil.which("docker") is None:
        return False
    try:
        cp = _pr.run(
            ["docker", "inspect", "--type=container", "-f", "{{.State.Running}}", container],
            capture_output=True, text=True)
        return cp.returncode == 0 and cp.stdout.strip() == "true"
    except Exception:  # noqa: BLE001
        return False


# ── #478 END-STATE: the real program binds the single metric ('wires'), via a
#    tmp_path defect artifact + subprocess + returncode/JSON assert ────────────
# Container-gated like its ppa siblings (test_v1_0_85_issue769, _80, _83, _85):
# the program needs to SYNTHESISE to count wires, and without the container it
# honestly self-reports NOT-APPLICABLE (rc 0) — so asserting the BLOCK rc 1 is
# only meaningful when the container is up. This guard was missing here, which
# made the file the single red in a full-suite run on a host with no container.
@pytest.mark.skipif(not _container_up(),
                    reason="vibeic-eda container not running — cannot synthesise")
def test_771_endstate_real_program_binds_wires(tmp_path):
    import json
    import subprocess
    prog = _PROGRAMS / "ppa_area_threshold_check.py"
    (tmp_path / "orig.v").write_text(
        "module m(input a, output b); assign b=a; endmodule\n")
    (tmp_path / "opt.v").write_text(
        "module m(input a, output b); assign b=a; endmodule\n")
    (tmp_path / "prompt.txt").write_text(
        "Reduce the interconnect, specifically the number of wires used. "
        "The minimum reduction must be 50% for this to count.\n")
    out = tmp_path / "out.json"
    cp = subprocess.run(
        [sys.executable, str(prog),
         "--original", str(tmp_path / "orig.v"),
         "--optimized", str(tmp_path / "opt.v"), "--top", "m",
         "--prompt", str(tmp_path / "prompt.txt"), "--json", str(out)],
        capture_output=True, text=True)
    rep = json.loads(out.read_text())
    # the #771 fix: the gate binds the EXPLICIT single metric 'wires', not the
    # conservative 'both' (which made the 0-cell design vacuously NOT-APPLICABLE).
    assert rep["metric"] == "wires", rep
    # a do-nothing (0% wires) submission against an explicit 50% wires bar is a
    # real under-reduction → the gate BLOCKs (rc 1), proving enforcement is live.
    assert cp.returncode == 1, cp.stdout + cp.stderr


def test_771_endstate_parsers_agree_on_single_metric():
    txt = ("Reduce the interconnect, specifically the number of wires used. "
           "The minimum reduction must be 50% for this to count.")
    single = P.parse_threshold_from_prompt(txt)
    clauses = P.parse_threshold_clauses_from_prompt(txt)[0]
    assert single[1] == "wires"
    assert clauses == [(50.0, "wires")]
    assert clauses != [(50.0, "both")]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
