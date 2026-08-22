#!/usr/bin/env python3
"""The per-corner `.temp` card must be anchored to a real `.control` CARD, never
to a prose MENTION of one.

THE DEFECT (chip-AGNOSTIC, reproduced here on synthetic decks only).
`render_deck` stamped the corner temperature with a bare substring substitution:

    deck = deck.replace(".control", f".temp {temp_c}\\n.control", 1)

`str.replace(..., 1)` takes the FIRST occurrence anywhere in the file. A SPICE
deck comment that *explains* ngspice's control-mode behaviour contains the token
`.control` as prose, and a comment can legally precede the real card. When it
does, the substitution splits that comment in half and produces TWO faults from
one edit:

  (1) SILENT  — the `.temp <T>` text lands inside a line that still begins with
      `*`, so ngspice never sees the card and the corner temperature is never
      applied. A "PVT sweep" that is not swept in T, with no error emitted.
  (2) FATAL   — the comment's tail now starts at column 1 with `.control`, so
      ngspice reads a SECOND control block:
          Error: Nesting of .control statements is not allowed!
          ERROR: fatal error in ngspice, exit(1)

(1) is the dangerous one: it does not announce itself. (2) merely happens to be
loud.

The two neighbouring override substitutions in the same function were already
line-anchored (`re.subn(r"(?m)^(v_vref\\s+vref\\s+0\\s+)\\S+", …)`); only the
temperature card was not.

Every fixture below is SYNTHETIC — invented block names, invented device names,
invented node names. No design, PDK SKU, vendor or part number appears.
"""

import re
import sys
import unittest
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import analog_real_corner_sweep as ars  # noqa: E402


# ── synthetic deck fixtures ────────────────────────────────────────────────
# A deck whose COMMENT mentions the control card before the real card appears.
# This is the shape that reproduces the defect.
DECK_MENTION_FIRST = """\
* synth_widget — synthetic fixture, no design content
.option scale=1u
.param gizmo=4
* NOTE — a stop time must be a concrete number for
* the `.control` `tran` command: the simulator does not expand a `.param`
* symbol inside a control-mode argument.
v_vdd vdd 0 1.2
xm1 nout nin 0 0 synth_nfet w=4 l=1
.control
tran 1n 1u
.endc
.end
"""

# The same deck with no prose mention — the ordinary case that must keep working.
DECK_NO_MENTION = """\
* synth_widget — synthetic fixture, no design content
.option scale=1u
v_vdd vdd 0 1.2
xm1 nout nin 0 0 synth_nfet w=4 l=1
.control
tran 1n 1u
.endc
.end
"""

# A deck with NO control card at all — the card must still be placed somewhere
# the simulator will read, and the caller must be able to see that it was.
DECK_NO_CONTROL = """\
* synth_widget — synthetic fixture, no design content
v_vdd vdd 0 1.2
xm1 nout nin 0 0 synth_nfet w=4 l=1
.op
.end
"""

# No control card, but a subckt terminator that shares `.end`'s prefix. The
# card must go before the real `.end`, never before `.ends` — `.ends` closes a
# subcircuit, so a card placed there lands INSIDE the subcircuit.
DECK_ENDS_BEFORE_END = """\
* synth_widget — synthetic fixture, no design content
.subckt synth_leaf a b
xm1 a b 0 0 synth_nfet w=4 l=1
.ends
v_vdd vdd 0 1.2
xsub vdd 0 synth_leaf
.op
.end
"""

# A deck whose mention is an INLINE (semicolon) comment on a real card line.
DECK_INLINE_COMMENT_MENTION = """\
* synth_widget — synthetic fixture, no design content
v_vdd vdd 0 1.2 ; see the `.control` block below for the analysis
xm1 nout nin 0 0 synth_nfet w=4 l=1
.control
tran 1n 1u
.endc
.end
"""


def _stamp(deck_text, temp_c):
    """Drive ONLY the temperature-card placement, on a synthetic deck string.

    Calls the shipped helper if the module exposes one, so this test exercises
    the REAL function rather than a copy of it.
    """
    fn = getattr(ars, "stamp_temp_card", None)
    if fn is None:  # pre-fix tree — reproduce the shipped expression exactly
        if temp_c is None:
            return deck_text, {}
        return deck_text.replace(".control",
                                 ".temp %s\n.control" % temp_c, 1), {}
    return fn(deck_text, temp_c)


# ── the properties a correct placement must have ───────────────────────────

def _directive_lines(deck_text, name):
    """Lines the SIMULATOR would read as the named dot-card.

    Faithful to how ngspice actually tokenises, which is the only definition
    that makes this a control rather than a restatement of the fix:

      * a line whose first non-blank character is `*` is a comment, however
        many times it spells a card;
      * text after `;` is an inline comment;
      * otherwise the leading token is matched by PREFIX, not by equality.
        ngspice accepted the split line `` .control` `tran` … `` as a control
        card — that is precisely why it reported "Nesting of .control
        statements is not allowed". An equality match would score that line as
        "not a card" and the test would pass on a broken deck.
    """
    out = []
    for i, line in enumerate(deck_text.split("\n"), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        code = stripped.split(";", 1)[0].strip()
        if not code:
            continue
        head = code.split()[0]
        if head.startswith(name):
            out.append((i, line))
    return out


def _deck_card_head_local(line):
    """The card token on one line, by the same simulator-faithful rule."""
    stripped = line.strip()
    if not stripped or stripped.startswith("*"):
        return None
    code = stripped.split(";", 1)[0].strip()
    return code.split()[0] if code else None


def _temp_cards(deck_text):
    return _directive_lines(deck_text, ".temp")


def _control_cards(deck_text):
    return _directive_lines(deck_text, ".control")


class TestTempCardAnchor(unittest.TestCase):

    # ── POSITIVE: the case that reproduces the defect ──────────────────────

    def test_mention_first_temp_card_is_a_real_directive(self):
        """The stamped `.temp` must be a REAL card, not text inside a comment."""
        out, _ = _stamp(DECK_MENTION_FIRST, 125)
        cards = _temp_cards(out)
        self.assertEqual(
            len(cards), 1,
            "expected exactly one real .temp directive line, got %d.\n"
            "This is fault (1): the card was swallowed by a comment and the "
            "corner temperature is silently never applied.\n---\n%s" %
            (len(cards), out))
        self.assertIn("125", cards[0][1])

    def test_mention_first_does_not_create_a_second_control_card(self):
        """Splitting a comment must not manufacture a nested control block."""
        out, _ = _stamp(DECK_MENTION_FIRST, 125)
        cards = _control_cards(out)
        self.assertEqual(
            len(cards), 1,
            "expected exactly one real .control card, got %d — a second one is "
            "fault (2): 'Nesting of .control statements is not allowed'."
            "\n---\n%s" % (len(cards), out))

    def test_mention_first_no_original_line_is_edited(self):
        """Stamping ADDS a card. It must never rewrite an existing line.

        Counting comment lines is NOT a control here: the bad substitution
        leaves the head of the split comment still starting with `*`, so the
        count is unchanged while the line itself has been cut in half. The
        property that actually holds is that every original line survives
        VERBATIM.
        """
        out, _ = _stamp(DECK_MENTION_FIRST, 125)
        after = out.split("\n")
        missing = [l for l in DECK_MENTION_FIRST.split("\n")
                   if l.strip() and l not in after]
        self.assertEqual(
            missing, [],
            "these original deck lines were edited, not preserved: %r\n---\n%s"
            % (missing, out))

    def test_temp_card_precedes_the_control_card(self):
        """`.temp` is a netlist directive; it must sit OUTSIDE the control block."""
        out, _ = _stamp(DECK_MENTION_FIRST, 125)
        t = _temp_cards(out)
        c = _control_cards(out)
        self.assertTrue(t and c)
        self.assertLess(t[0][0], c[0][0],
                        ".temp must precede .control, not sit inside it")

    # ── the ordinary case must keep working (no regression) ────────────────

    def test_plain_deck_still_gets_exactly_one_temp_card(self):
        out, _ = _stamp(DECK_NO_MENTION, -40)
        cards = _temp_cards(out)
        self.assertEqual(len(cards), 1, out)
        self.assertIn("-40", cards[0][1])
        self.assertEqual(len(_control_cards(out)), 1, out)

    def test_plain_deck_temp_precedes_control(self):
        out, _ = _stamp(DECK_NO_MENTION, 27)
        self.assertLess(_temp_cards(out)[0][0], _control_cards(out)[0][0])

    def test_none_temperature_is_a_no_op(self):
        out, _ = _stamp(DECK_NO_MENTION, None)
        self.assertEqual(out, DECK_NO_MENTION)
        self.assertEqual(len(_temp_cards(out)), 0)

    # ── NEGATIVE / no-leak: the placement must not become permissive ───────
    # This change makes the anchor STRICTER. The failure mode a stricter
    # anchor introduces is the OPPOSITE one — refusing to place the card at
    # all, which reproduces fault (1) by a different route. These are the
    # boundary-outside cases that must still get a real, readable card.

    def test_deck_without_a_control_card_still_gets_a_readable_temp_card(self):
        """No control block is not a licence to drop the temperature."""
        out, applied = _stamp(DECK_NO_CONTROL, 125)
        cards = _temp_cards(out)
        self.assertEqual(
            len(cards), 1,
            "a stricter anchor must not silently drop the card — that is the "
            "same silent fault by another route\n---\n%s" % out)
        end = _directive_lines(out, ".end")
        if end:
            self.assertLess(cards[0][0], end[0][0],
                            ".temp must precede .end to be read")

    def test_subckt_terminator_is_not_mistaken_for_the_netlist_terminator(self):
        """`.ends` closes a subcircuit; it is not `.end`.

        A prefix match on the fallback anchor would drop the card inside a
        subcircuit, where it is scoped away — silent fault (1) again, by a
        third route.
        """
        out, applied = _stamp(DECK_ENDS_BEFORE_END, 125)
        cards = _temp_cards(out)
        self.assertEqual(len(cards), 1, out)
        ends = [i for i, l in enumerate(out.split("\n"), 1)
                if _deck_card_head_local(l) == ".ends"]
        end = [i for i, l in enumerate(out.split("\n"), 1)
               if _deck_card_head_local(l) == ".end"]
        self.assertTrue(ends and end)
        self.assertGreater(cards[0][0], ends[0],
                           ".temp landed inside the subcircuit\n---\n%s" % out)
        self.assertLess(cards[0][0], end[0], out)

    def test_inline_comment_mention_is_not_an_anchor(self):
        """`; … .control …` on a real card line is still a comment."""
        out, _ = _stamp(DECK_INLINE_COMMENT_MENTION, 125)
        self.assertEqual(len(_control_cards(out)), 1, out)
        cards = _temp_cards(out)
        self.assertEqual(len(cards), 1, out)
        self.assertLess(cards[0][0], _control_cards(out)[0][0], out)
        # the supply card must not have been mangled
        self.assertTrue(any(l.strip().startswith("v_vdd")
                            for l in out.split("\n")), out)

    def test_placement_is_reported_to_the_caller(self):
        """A dropped card must be observable, not silent."""
        fn = getattr(ars, "stamp_temp_card", None)
        if fn is None:
            self.skipTest("pre-fix tree exposes no helper to report through")
        _, applied = fn(DECK_MENTION_FIRST, 125)
        self.assertEqual(applied.get("temp_c"), 125)
        self.assertIn(applied.get("temp_c_anchor"),
                      ("control", "end", "append"))

    def test_repeated_stamp_does_not_accumulate_cards(self):
        """Idempotence: stamping twice must not leave two temperatures."""
        once, _ = _stamp(DECK_NO_MENTION, 27)
        twice, _ = _stamp(once, 27)
        self.assertEqual(len(_temp_cards(twice)), 1, twice)

    # ── END-TO-END through the SHIPPED entry point ────────────────────────
    # Testing the helper alone is not a control: a revert that leaves the
    # helper in place but stops CALLING it passes a helper-only suite while
    # shipping the original defect. `render_deck` is the function the sweep
    # actually calls, so it is the function that must be measured.

    def _render(self, template_text, temp_c):
        btype = "__synthetic_anchor_fixture__"
        saved = ars.T.get(btype)
        ars.T[btype] = template_text
        try:
            return ars.render_deck(
                btype, block="synth_block", pdk="synth_pdk",
                pdk_lib="synth_lib.spice", corner="synth_tt",
                knob="__noop__", val=0, temp_c=temp_c)
        finally:
            if saved is None:
                ars.T.pop(btype, None)
            else:
                ars.T[btype] = saved

    # `{block}` / `{pdk}` / `{pdk_lib}` / `{corner}` are the substitutions
    # every shipped template takes; the fixture takes the same ones so it goes
    # down the identical code path.
    E2E_TEMPLATE = """\
* {block} — synthetic fixture, no design content ({pdk})
.lib {pdk_lib} {corner}
* NOTE — a stop time must be a concrete number for
* the `.control` `tran` command: the simulator does not expand a `.param`
v_vdd vdd 0 1.2
.control
tran 1n 1u
.endc
.end
"""

    def test_render_deck_end_to_end_places_a_real_temp_card(self):
        out, applied = self._render(self.E2E_TEMPLATE, 125)
        self.assertEqual(
            len(_temp_cards(out)), 1,
            "render_deck — the SHIPPED path — did not emit a readable .temp "
            "card\n---\n%s" % out)
        self.assertEqual(applied.get("temp_c"), 125)

    def test_render_deck_end_to_end_emits_one_control_card(self):
        out, _ = self._render(self.E2E_TEMPLATE, 125)
        self.assertEqual(
            len(_control_cards(out)), 1,
            "render_deck emitted a nested control block — the simulator aborts "
            "with 'Nesting of .control statements is not allowed'\n---\n%s"
            % out)

    def test_render_deck_end_to_end_edits_no_existing_line(self):
        rendered_clean, _ = self._render(self.E2E_TEMPLATE, None)
        out, _ = self._render(self.E2E_TEMPLATE, 125)
        after = out.split("\n")
        missing = [l for l in rendered_clean.split("\n")
                   if l.strip() and l not in after]
        self.assertEqual(
            missing, [],
            "render_deck cut an existing deck line in half: %r\n---\n%s"
            % (missing, out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
