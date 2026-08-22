"""The via-patch min-width fact must reach a run, not just a test fixture.

The checker landed with nothing but its own test executing it: `gate_is_wired_
check` reported it unwired and `checker_execution_wiring_audit` reported "1
checker(s) that NOTHING but their own test runs". A gate nothing invokes
produces no verdict, and the tree looks the same either way.

`step_pnr` already resolves the tech LEF text host-or-container for the
single-cut via analyzer, one line above, so the fact is reachable there for
free — and that is the step it is about, because the defect fires at a ROUTE
TERMINUS.

These tests RUN the helper the runner calls, over a fixture carrying the real
contradiction in both of the forms the PDK writes it. They do not assert on
source text: a wiring test that greps the runner would stay green through a
`NameError` on the line it claims to prove.
"""
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phase3_one_shot_runner as p3  # noqa: E402

# The two declarations that contradict each other, as the real file writes
# them: the fixed via, and the generate rule that restates the same 1.42 um as
# 0.8 + 2 x 0.31.
TLEF = textwrap.dedent("""\
    LAYER met4
      TYPE ROUTING ;
      WIDTH 0.3 ;
    END met4

    LAYER via4
      TYPE CUT ;
      WIDTH 0.8 ;
    END via4

    LAYER met5
      TYPE ROUTING ;
      WIDTH 1.6 ;
    END met5

    VIA M4M5_PR DEFAULT
      LAYER via4 ;
      RECT -0.4 -0.4 0.4 0.4 ;
      LAYER met5 ;
      RECT -0.71 -0.71 0.71 0.71 ;
    END M4M5_PR

    VIARULE M4M5_PR GENERATE
      LAYER met5 ;
      ENCLOSURE 0.31 0.31 ;
      LAYER via4 ;
      RECT -0.4 -0.4 0.4 0.4 ;
    END M4M5_PR
    """)

CLEAN = TLEF.replace("RECT -0.71 -0.71 0.71 0.71 ;",
                     "RECT -0.8 -0.8 0.8 0.8 ;") \
            .replace("ENCLOSURE 0.31 0.31 ;", "ENCLOSURE 0.4 0.4 ;")


class ViaPatchAdvisoryReachesTheRun(unittest.TestCase):

    def test_the_defect_produces_a_note_and_an_artefact_payload(self):
        note, payload = p3._via_patch_min_width_advisory(
            TLEF, "/foss/pdks/x/techlef/x.tlef", "met5")
        self.assertTrue(note, "the runner would have printed nothing")
        self.assertIn("met5", note)
        self.assertEqual(len(payload["findings"]), 2)          # both forms
        self.assertEqual({f["form"] for f in payload["findings"]},
                         {"VIA", "VIARULE"})
        self.assertEqual(payload["issue"], "vibe-ic#768")

    def test_inside_the_routing_range_it_says_this_run_will_hit_it(self):
        note, payload = p3._via_patch_min_width_advisory(
            TLEF, "/x/x.tlef", "met5")
        self.assertEqual(len(payload["inside_routing_range"]), 2)
        self.assertIn("THIS run routes signals on", note)

    def test_above_the_routing_range_it_says_latent(self):
        """The one mitigation checkable here: a layer no signal is routed on
        cannot produce a route terminus, so nothing can fire."""
        note, payload = p3._via_patch_min_width_advisory(
            TLEF, "/x/x.tlef", "met4")
        self.assertEqual(payload["inside_routing_range"], [])
        self.assertIn("latent", note)
        self.assertIn("met4", note)

    def test_no_declared_ceiling_is_not_read_as_a_mitigation(self):
        """"I was not told the range" must not become "the layer is outside
        it" — that is the shape of every vacuous pass this repo has fixed."""
        note, payload = p3._via_patch_min_width_advisory(TLEF, "/x/x.tlef",
                                                         None)
        self.assertEqual(len(payload["inside_routing_range"]), 2)
        self.assertIn("no routing ceiling declared", note)

    def test_a_clean_pdk_produces_no_note_at_all(self):
        note, payload = p3._via_patch_min_width_advisory(CLEAN, "/x/x.tlef",
                                                         "met5")
        self.assertEqual(note, "")
        self.assertEqual(payload, {})

    def test_it_is_an_advisory_and_states_why(self):
        """The severity is a decision, so it is written down where a reader
        of the artefact meets it."""
        _, payload = p3._via_patch_min_width_advisory(TLEF, "/x/x.tlef", "met5")
        self.assertEqual(payload["severity"], "ADVISORY")
        self.assertIn("cannot fix", payload["why_not_a_verdict"])


if __name__ == "__main__":
    unittest.main()
