#!/usr/bin/env python3
"""A cell that CITES evidence must publish the record saying whether a reader
can follow each citation.

MEASURED on the stamp full-tier run of 2026-08-31. `evidence citation resolves`
reported 14 NEW dangling citations, all of them corpus-side, and the cheap tier
of the SAME run reported `PASS  benchmark evidence structure` over the cells
carrying them. Bisected against the corpus: at benchmark-data `6bd1513` the gate
is GREEN (`unresolved now : 4   baseline: 4`) and at `e03ccabf` it is
`unresolved now : 18` — so all 14 arrived with two corpus commits:

    88621a5  restore spm/v1.10.18_sky130A as a SPECIMEN, on owner instruction
             (486 files)                                          ->  2
    a467106  publish spm/v1.5.65_sky130A, pulled off the fleet
             (203 files)                                          -> 12

THE DISCLOSURE CHANNEL ALREADY EXISTS AND NOTHING REQUIRES IT.
`CITATION_ROUTING.txt` is per published cell; `benchmark_evidence_publish.py`
emits it (`write_citation_routing`, staged in the publish list) and
`evidence_citation_resolves_check` HONOURS its `OUT_OF_PUBLISHED_SCOPE` and
`UNFOLLOWABLE_ABSOLUTE` rows. `citation_routing_is_true_check` audits the
content of routing files THAT EXIST. A cell shipping none is simply never
asked, so the whole corpus tracks exactly one of them.

MEASURED per cell at e03ccabf:

    spm/v1.10.18_sky130A   routing present   28 citations,  4 uncovered
    spm/v1.5.65_sky130A    routing ABSENT    18 citations, 18 uncovered

The second cell was "pulled off the fleet" and committed after passing the
structure check; it never went through the publisher, so the record was never
derived. The first was restored wholesale without re-deriving the record it
already had. One rule covers both, because both are the same fact: the cell
publishes citations the record does not answer for.

WHY HERE. This gate is the one the landing runs over benchmark-data and the one
that says a published cell is well formed. Saying yes about a cell missing the
record that keeps a later, more expensive gate honest is the hole. Two of the
fourteen are worse than unfollowable — they publish an absolute personal home
path into a signed-off report — and `UNFOLLOWABLE_ABSOLUTE` is the decision the
publisher already has a name for.

NOT A REQUIREMENT MANUFACTURED FOR EVERY CELL: a cell whose documents cite no
evidence at all carries no obligation, and that arm is tested.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parents[1]
GATE = PROGRAMS / "benchmark_evidence_structure_check.py"

pytestmark = pytest.mark.timeout(0)


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _cell(root: Path, *, cites: bool = True) -> Path:
    """A structurally conformant published cell, so the only thing that can
    move the verdict below is the rule under test."""
    cell = root / "ic" / "design" / "v1.0.0_pdkx"
    _write(cell / "RESULT.md", "# RESULT\n\n## VERDICT\n\nPASS\n")
    _write(cell / "phase1" / "generated_docs" / "L1.json", '{"layer": "L1"}\n')
    _write(cell / "phase2" / "top.v", "module top(); endmodule\n")
    _write(cell / "reports" / "phase3" / "drc.json",
           json.dumps({"verdict": "PASS"}) + "\n")
    _write(cell / "phase3" / "stage4" / "gds" / "GDS_MANIFEST.txt",
           "top.gds 1024B sha256:" + "0" * 64 + "\n")
    if cites:
        _write(cell / "reports" / "phase3" / "sta.json",
               json.dumps({"verdict": "PASS",
                           "report": "phase3/stage3/sta/sta.rpt"}) + "\n")
    return cell


def _routing(cell: Path, rows) -> None:
    _write(cell / "CITATION_ROUTING.txt",
           "# CITATION_ROUTING\n"
           + "".join(f"{d} :: {c} {v}\n" for d, c, v in rows))


def _run(root: Path):
    return subprocess.run(
        [sys.executable, str(GATE), "--tree", str(root)],
        capture_output=True, text=True, cwd=str(PROGRAMS.parents[3]))


def test_a_citing_cell_with_no_routing_record_is_refused(tmp_path):
    """THE STAMP RED, in the shape a467106 committed."""
    _cell(tmp_path)
    proc = _run(tmp_path)
    both = proc.stdout + proc.stderr
    assert proc.returncode != 0, both
    assert "CITATION_ROUTING" in both, both


def test_a_routing_record_that_does_not_cover_a_citation_is_refused(tmp_path):
    """THE OTHER SHAPE, which 88621a5 committed: the record exists and the
    restore added documents it never answered for. A record that covers only
    some of a cell's citations is, to a reader, indistinguishable from one
    saying the rest are fine."""
    cell = _cell(tmp_path)
    _routing(cell, [("reports/phase3/drc.json", "phase3/x.rpt", "RESOLVES")])
    proc = _run(tmp_path)
    both = proc.stdout + proc.stderr
    assert proc.returncode != 0, both
    assert "CITATION_ROUTING" in both, both
    assert "phase3/stage3/sta/sta.rpt" in both, both


def test_a_fully_covered_cell_passes(tmp_path):
    """The positive control. A rule that refuses every cell is not a rule."""
    cell = _cell(tmp_path)
    _routing(cell, [("reports/phase3/sta.json", "phase3/stage3/sta/sta.rpt",
                     "OUT_OF_PUBLISHED_SCOPE")])
    proc = _run(tmp_path)
    both = proc.stdout + proc.stderr
    assert proc.returncode == 0, both


def test_a_cell_that_cites_nothing_carries_no_obligation(tmp_path):
    """NOT A REQUIREMENT MANUFACTURED FOR EVERY CELL. An empty record proves
    nothing and demanding one would be ceremony, so the rule does not apply."""
    _cell(tmp_path, cites=False)
    proc = _run(tmp_path)
    both = proc.stdout + proc.stderr
    assert proc.returncode == 0, both


def test_the_rule_is_reported_by_name_so_a_reader_can_act(tmp_path):
    """A nonconformance nobody can name is one nobody can fix."""
    _cell(tmp_path)
    out = tmp_path / "report.json"
    subprocess.run(
        [sys.executable, str(GATE), "--tree", str(tmp_path),
         "--json", str(out)],
        capture_output=True, text=True, cwd=str(PROGRAMS.parents[3]))
    doc = json.loads(out.read_text(encoding="utf-8"))
    blob = json.dumps(doc)
    assert "CITATION_ROUTING" in blob, blob[:2000]
