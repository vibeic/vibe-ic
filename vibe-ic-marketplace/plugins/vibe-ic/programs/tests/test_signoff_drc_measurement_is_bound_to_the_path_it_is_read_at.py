"""A measured sign-off DRC invocation must be bound to the path its report is
READ at — and re-binding must be impossible when the bytes are not that
measurement's.

MEASURED 2026-09-15 (lane icspm) on a signed-off gf180mcuD run of the canonical
front door. `eda_report_audit._measured_klayout_receipt_files` accepts a zero
only from a ledger row that is an `invocation`, `measured`, exit 0, whose
`outputs` carry BOTH the report and its `.log` at the digests on disk, and one
of whose `inputs` is a GDS still matching on disk. The run satisfied every one
of those facts and was refused::

    provenance.jsonl, newest klayout invocation (exit 0, measured true)
      out phase3/reports/drc.rpt      ledger c5a1b3be…  disk c5a1b3be…  MATCH
      out phase3/reports/drc.log      ledger fb0cf634…  disk fb0cf634…  MATCH
      in  phase3/stage3/pnr/spm.gds   ledger 06fc4aac…  disk 06fc4aac…  MATCH

    what the gate reads
      reports/phase3/drc_signoff.rpt  disk c5a1b3be…   <- the SAME BYTES
      reports/phase3/drc_signoff.log  disk fb0cf634…   <- the SAME BYTES

    reports/phase3/drc_signoff.json -> passed: false
      DRC_ZERO_NOT_MEASURED: … NO report stated a violation count and NONE was
      corroborated … This is NOT_MEASURED, not clean.

The measurement happened; the canonicalised copy is simply read under a name the
invocation never recorded. The workaround reached for instead was to HAND-WRITE
the missing row into a published cell (benchmark-data `71071a1dd400`,
"evidence(spm): record measured signoff DRC invocation").

THE DANGEROUS HALF of this fix is not the positive case — it is that a function
which appends "this was measured" rows must be unable to say so when it was not.
The negative controls below are the real subject of this file, and each one is a
way the re-bind could have been wrong:

  * bytes that no measured invocation produced          -> nothing written
  * an input GDS that changed since the deck ran        -> nothing written
  * a declaration row instead of a measurement          -> nothing written
  * a measured invocation that exited non-zero          -> nothing written
  * the transcript missing from the source's outputs    -> nothing written
  * already bound                                       -> no duplicate row

In every one of those the gate must still refuse, because an uncorroborated zero
that starts reading as corroborated is the exact defect this repo exists to
prevent.

chip-AGNOSTIC: ledger schema and canonical PV paths only. No PDK, design, vendor
or IC literal — the fixture's GDS is three bytes of nothing in particular.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import eda_report_audit as A  # noqa: E402

CANON_RPT = "reports/phase3/drc_signoff.rpt"
CANON_LOG = "reports/phase3/drc_signoff.log"
SRC_RPT = "phase3/reports/drc.rpt"
SRC_LOG = "phase3/reports/drc.log"
SRC_GDS = "phase3/stage3/pnr/fixture_core.gds"

RPT_BYTES = b"<report-database><top-cell>fixture_core</top-cell></report-database>\n"
LOG_BYTES = b"klayout -b -r deck.drc\nfixture transcript\n"
GDS_BYTES = b"\x00\x06\x00\x02fixture"


def _sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _write(root: Path, rel: str, data: bytes) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def _ledger(root: Path, rows: list) -> None:
    (root / "provenance.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def _measured_row(**over) -> dict:
    row = {
        "record": "invocation",
        "measured": True,
        "tool": "klayout",
        "exit_code": 0,
        "inputs": {SRC_GDS: _sha(GDS_BYTES)},
        "outputs": {SRC_RPT: _sha(RPT_BYTES), SRC_LOG: _sha(LOG_BYTES)},
        "command": ["docker", "run", "…", "klayout", "-b", "-r", "deck.drc"],
        "deck": "/deck.drc",
        "top_cell": "fixture_core",
        "timestamp": "2026-09-15T00:00:00+00:00",
    }
    row.update(over)
    return row


def _project(tmp_path: Path, rows: list, *,
             rpt: bytes = RPT_BYTES, log: bytes = LOG_BYTES,
             gds: bytes = GDS_BYTES) -> Path:
    """The shipped shape: the measurement wrote the SOURCE paths, and a
    byte-identical canonical copy is what every consumer reads."""
    _write(tmp_path, SRC_RPT, rpt)
    _write(tmp_path, SRC_LOG, log)
    _write(tmp_path, CANON_RPT, rpt)
    _write(tmp_path, CANON_LOG, log)
    _write(tmp_path, SRC_GDS, gds)
    _ledger(tmp_path, rows)
    return tmp_path




def _corroborated(root: Path) -> bool:
    return bool(A._measured_klayout_receipt_files(root, [root / CANON_RPT]))




# ── the defect, and its repair ──────────────────────────────────────────────

def test_the_shipped_shape_is_refused_before_the_rebind(tmp_path):
    """THE MEASURED DEFECT. Every fact the contract wants is true, recorded
    under the source path, and the canonical copy is refused."""
    proj = _project(tmp_path, [_measured_row()])
    assert _corroborated(proj) is False










# ── NEGATIVE CONTROLS: it must be unable to say "measured" when it was not ──















# The current publisher records a copy, not a second native invocation.
