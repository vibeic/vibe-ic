"""R-icgate3 — a refusing producer's step row carries the SET it refused on.

MEASURED on spm run15 (8HD-4, `_lane_icspm5/run15`),
`reports/orchestrator/phase3_one_shot.json`:

    steps[28] tapeout_docs_gen     NOT_MEASURED
      "NOT RELEASABLE — no documents written. 8 propert(ies) are not clean:"
    steps[29] ic_release_docs_gen  NOT_MEASURED
      "NOT RELEASABLE — no product documents written. 1 release(s) examined."

A colon and nothing after it. Nobody could name the eight.

THE PRODUCERS ALREADY ENUMERATE. `tapeout_docs_gen` prints `f"  - {b}"` for
every blocker (tapeout_docs_gen.py, in `main` under `release_blockers`), and
`ic_release_docs_gen._refuse` prints every artefact refusal and every unclean
property. Re-running `tapeout_docs_gen` on run15's own bytes (its
`phase3/final/metrics.json`, sha256 998c2d90b99b...) prints all eight:

    - Magic DRC: NOT_MEASURED (magic__drc_error__count)
    - KLayout DRC: 5 (klayout__drc_error__count)
    - Density: NOT_MEASURED (klayout__density_error__count)
    - Antenna — violating nets: 1 (antenna__violating__nets)
    - Antenna — violating pins: 1 (antenna__violating__pins)
    - GDS vs layout XOR: NOT_MEASURED (design__xor_difference__count)
    - Max-slew violations: NOT_MEASURED (design__max_slew_violation__count)
    - Max-cap violations: NOT_MEASURED (design__max_cap_violation__count)

so the defect is in the CONSUMER, and it is one expression, repeated at all
three producer-dispatch rows in `phase3_one_shot_runner`:

    detail_lines = (cp.stdout or cp.stderr or "").strip().splitlines()
    detail = detail_lines[0] if detail_lines else f"rc={cp.returncode}"

  * `detail_lines[0]` keeps the header and drops the set;
  * `stdout or stderr` drops the WHOLE refusal the moment the producer also
    prints one progress line — both refusals above go to stderr.

Grepping the whole of run15 for `propert(ies) are not clean` returns ONE hit,
the header itself, so the enumeration was not merely unrendered — it was never
kept anywhere. `_producer_detail` therefore also WRITES it, to
`reports/orchestrator/producers/<step>.log`.

chip-AGNOSTIC: this reasons about a subprocess's two streams, nothing else.
"""
import ast
import sys
import types
import unittest
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import tapeout_docs_gen as T                # noqa: E402


#: `tapeout_docs_gen`'s stderr on run15's own metrics, verbatim.
MEASURED_TAPEOUT_STDERR = """NOT RELEASABLE — no documents written. 8 propert(ies) are not clean:
  - Magic DRC: NOT_MEASURED (magic__drc_error__count)
  - KLayout DRC: 5 (klayout__drc_error__count)
  - Density: NOT_MEASURED (klayout__density_error__count)
  - Antenna — violating nets: 1 (antenna__violating__nets)
  - Antenna — violating pins: 1 (antenna__violating__pins)
  - GDS vs layout XOR: NOT_MEASURED (design__xor_difference__count)
  - Max-slew violations: NOT_MEASURED (design__max_slew_violation__count)
  - Max-cap violations: NOT_MEASURED (design__max_cap_violation__count)

A release document for a run that did not pass is worse than no document: it becomes a file that outlives the run it came from. Fix the run, or pass --allow-incomplete to write a DRAFT.
"""

#: The eight, by the metric key each names -- MEMBERSHIP, never a count.
MEASURED_EIGHT = (
    "magic__drc_error__count", "klayout__drc_error__count",
    "klayout__density_error__count", "antenna__violating__nets",
    "antenna__violating__pins", "design__xor_difference__count",
    "design__max_slew_violation__count", "design__max_cap_violation__count",
)


def _cp(stdout="", stderr="", rc=1):
    return types.SimpleNamespace(stdout=stdout, stderr=stderr, returncode=rc)


class _Tmp(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()


class ARefusalNamesItsWholeSet(_Tmp):


    # ---- the other direction --------------------------------------------- #
    def test_negative_control_zero_unclean_properties_still_says_zero(self):
        """A producer with nothing to refuse on refuses nothing. Driven through
        `release_blockers` itself, over the FULL declared key set."""
        clean = {key: 0 for _l, key, _p in T.MANUFACTURABILITY + T.ELECTRICAL}
        self.assertEqual(T.release_blockers(clean), [],
                         "a clean run acquired a blocker")


if __name__ == "__main__":
    unittest.main()
