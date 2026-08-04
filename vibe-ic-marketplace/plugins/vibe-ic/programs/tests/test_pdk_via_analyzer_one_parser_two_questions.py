"""One LEF via-block parser, two questions asked of it.

`_pdk_via_analyzer` was already the repo's chip-AGNOSTIC LEF via-block parser,
wired into `phase3_one_shot_runner.step_pnr`, with a comment on the very line
that distinguishes `VIA` from `VIARULE`. The via-patch min-width checker
re-derived the same parser from scratch in its own file — and re-derived the
same VIARULE blind spot with it.

Two parsers over one file format drift, and the drift is invisible until the
day they disagree about a PDK. These tests pin that they cannot: both answers
come from `parse_tech_lef`, and the block enumeration one sees is the block
enumeration the other sees.
"""
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _pdk_via_analyzer as A  # noqa: E402

# Both forms, a multi-cut block, and a same-name VIA/VIARULE pair — the shape
# the real sky130 and gf180 tech LEFs have.
LEF = textwrap.dedent("""\
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
      MINWIDTH 1.6 ;
      WIDTH 1.6 ;
    END met5

    VIA M4M5_PR DEFAULT
      LAYER via4 ;
      RECT -0.4 -0.4 0.4 0.4 ;
      LAYER met4 ;
      RECT -0.59 -0.59 0.59 0.59 ;
      LAYER met5 ;
      RECT -0.71 -0.71 0.71 0.71 ;
    END M4M5_PR

    VIARULE M4M5_PR GENERATE
      LAYER met4 ;
      ENCLOSURE 0.19 0.19 ;
      LAYER met5 ;
      ENCLOSURE 0.31 0.31 ;
      LAYER via4 ;
      RECT -0.4 -0.4 0.4 0.4 ;
      SPACING 1.6 BY 1.6 ;
    END M4M5_PR

    VIA M4M5_2CUT DEFAULT
      LAYER via4 ;
      RECT -1.0 -0.4 -0.2 0.4 ;
      RECT 0.2 -0.4 1.0 0.4 ;
      LAYER met4 ;
      RECT -1.2 -0.59 1.2 0.59 ;
      LAYER met5 ;
      RECT -1.2 -0.8 1.2 0.8 ;
    END M4M5_2CUT
    """)


class OneParserTwoQuestions(unittest.TestCase):

    def test_both_forms_are_scanned(self):
        blocks = A.parse_tech_lef(LEF).blocks
        self.assertEqual([(b.kind, b.name) for b in blocks],
                         [("VIA", "M4M5_PR"),
                          ("VIARULE", "M4M5_PR"),
                          ("VIA", "M4M5_2CUT")])

    def test_a_via_and_a_viarule_of_one_name_are_two_entries(self):
        """Both close with `END M4M5_PR`. Keyed only by name they would be one,
        and the fixed via's patch would silently overwrite the rule's."""
        ext = A.via_patch_extents(LEF)
        self.assertIn(("VIA", "M4M5_PR"), ext)
        self.assertIn(("VIARULE", "M4M5_PR"), ext)
        self.assertEqual(ext[("VIA", "M4M5_PR")]["met5"], (1.42, 1.42))
        # 0.8 cut + 2 x 0.31 enclosure = the same 1.42, by other arithmetic.
        self.assertEqual(ext[("VIARULE", "M4M5_PR")]["met5"], (1.42, 1.42))

    def test_the_cut_layer_is_the_one_the_file_does_not_call_routing(self):
        """Not name vocabulary: the VIARULE's cut extent is derived by
        elimination against the file's own ROUTING declarations."""
        self.assertEqual(sorted(A.routing_layer_min_widths(LEF)),
                         ["met4", "met5"])
        self.assertNotIn("via4", A.via_patch_extents(LEF)[("VIA", "M4M5_PR")])

    def test_minwidth_outranks_width(self):
        tl = A.parse_tech_lef(LEF.replace("  MINWIDTH 1.6 ;",
                                          "  MINWIDTH 1.8 ;"))
        self.assertEqual(tl.routing["met5"].min_width, 1.8)
        self.assertEqual(tl.routing["met5"].width_source, "MINWIDTH")
        self.assertEqual(tl.routing["met4"].width_source, "WIDTH")

    def test_the_cut_count_question_reads_the_same_blocks(self):
        """`analyze_lef` (single-cut coverage) and `via_patch_extents` (patch
        width) must agree on which FIXED vias the file declares. They are one
        scan now; this fails the moment either grows a private one."""
        cut = {n for info in A.analyze_lef(LEF).values()
               for n in info["names"]}
        patch = {name for (kind, name) in A.via_patch_extents(LEF)
                 if kind == "VIA"}
        self.assertEqual(cut, patch)

    def test_a_viarule_is_not_counted_as_a_single_cut_via(self):
        """A rule is not a fixed via. Counting it would report DRT-0234
        coverage the router does not have."""
        info = A.analyze_lef(LEF)["via4"]
        self.assertEqual(info["total"], 2)                  # the two VIA blocks
        self.assertEqual(sorted(info["single_cut_names"]), ["M4M5_PR"])
        self.assertEqual(sorted(info["multi_cut_names"]), ["M4M5_2CUT"])

    def test_a_lead_comment_denial_is_recorded_with_its_sentence(self):
        text = LEF.replace("\nVIA M4M5_PR DEFAULT",
                           "\n# Centered via rule, we really do not want to "
                           "use it\nVIA M4M5_PR DEFAULT")
        blk = A.parse_tech_lef(text).blocks[0]
        self.assertEqual(blk.source_denial, "not")
        self.assertIn("do not want to use it", blk.source_comment)

    def test_a_blank_line_ends_the_lead_comment(self):
        """Scope is the CONTIGUOUS comment above the block. A blank line means
        the comment belongs to whatever came before."""
        text = LEF.replace("\nVIA M4M5_PR DEFAULT",
                           "\n# we really do not want to use it\n\n"
                           "VIA M4M5_PR DEFAULT")
        self.assertIsNone(A.parse_tech_lef(text).blocks[0].source_denial)


if __name__ == "__main__":
    unittest.main()
