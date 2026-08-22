"""ORGANIC #741 [P1] — the #718/#733 lessons digest carried TWO actively-WRONG
conventions that steered a faithful blind author to the FAILING choice:
  FACET A: barrel-shifter §4-E carve-out ("rotate explicitly") self-contradicted
           its sibling logical-shift-default skill → author chose ROTATE.
  FACET B: async-FIFO "make the RAM read COMBINATIONAL" inverted the golden's
           REGISTERED read (`output reg rdata` + posedge rclk) → 46/48 mismatch,
           and contradicted the corpus's own "do not default to combinational".

Fix: corrected both sections in agents/ic-expert-agent.md AND added a durable
self-consistency audit (programs/lessons_corpus_consistency_check.py) so no two
`### Skill:` sections may prescribe opposite directives for the same genre.

This test (a) asserts the audit PASSES on the shipped corpus, (b) asserts it
CATCHES the pre-fix contradictory pair (embedded VERBATIM as the defect-artifact
fixture) and assert an end-state via the real program's main(), (c) asserts the
two corrected corpus sections now carry the spec-faithful directive, and (d)
guards the §4.05 no-leak: a spec-deferring pair is NOT flagged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import lessons_corpus_consistency_check as A  # noqa: E402

_CORPUS = _PROGRAMS.parent / "agents" / "ic-expert-agent.md"


# ── (a) the shipped corpus is self-consistent (end-state via main()) ─────────
def test_shipped_corpus_passes_audit_via_main():
    rc = A.main([str(_CORPUS)])
    assert rc == 0, "shipped lessons corpus must be self-consistent"


# ── (b) the audit CATCHES the REAL pre-fix shape (defect-artifact fixture) ────
# This is the VERBATIM pre-fix async-FIFO readback section (#741 FACET B): a
# DESCRIPTIVE Pattern line that mentions the REGISTERED pole (the wrong default
# being described) sitting above a PRESCRIPTIVE "Make the RAM read COMBINATIONAL"
# directive. The adversarial review proved an earlier audit version MISSED this
# real shape (it saw both poles and exempted the section); the fix reads only the
# prescriptive '**What to do**:' directive and flags a hard-coded pole on a
# spec-governed axis that does not defer to the spec.
_PREFIX_REAL_SHAPE = """\
### Skill: async-FIFO readback — zero-cycle RAM read aligns with TB sample timing

**Pattern**: Classic async-FIFO templates default to a REGISTERED RAM read on the read-clock, plus REGISTERED full/empty flags. The TB samples `rdata` on the SAME read-clock edge that drives `rinc`, so any registered-read FIFO loses byte 0.

**When to apply**: Authoring any dual-clock asynchronous FIFO.

**What to do**: Make the RAM read COMBINATIONAL (`always @(*) rdata = mem[raddr]` or `assign rdata = mem[raddr]`).

**Why this is GENERAL**: Standard for any dual-clock FIFO whose downstream consumer samples on the read-clock edge.
"""


def test_audit_catches_real_prefix_shape(tmp_path):
    """END-STATE via the real program's main() on a tmp_path-shaped defect
    artifact = the VERBATIM pre-fix FIFO section. Despite the Pattern line
    DESCRIBING the registered pole, the prescriptive directive hard-codes
    COMBINATIONAL on a spec-governed axis without deferring → FLAGGED (rc=1)."""
    (tmp_path / "corpus.md").write_text(_PREFIX_REAL_SHAPE)
    rc = A.main([str(tmp_path / "corpus.md")])
    assert rc == 1, "the real pre-fix hard-coded-combinational FIFO section must FAIL"
    contradictions = A.audit_text(_PREFIX_REAL_SHAPE)
    assert any(c["axis"] == "read-timing" and c["genre"] == "fifo"
               and "A" in c["poles"] for c in contradictions), contradictions
    # NOTE on the durable-fixture choice: `_PREFIX_REAL_SHAPE` above embeds the
    # VERBATIM pre-#741 async-FIFO section (descriptive REGISTERED Pattern line +
    # prescriptive COMBINATIONAL directive). It is the stable defect artifact —
    # we do NOT git-archaeology the live `HEAD` corpus for it, because once this
    # #741 fix is committed HEAD holds the FIXED (passing) corpus, so a
    # HEAD-reading guard would invert. The embedded verbatim shape is the
    # authoritative regression and cannot rot with the tree state.


# ── (c) the corrected corpus sections carry the spec-faithful directive ──────
def test_facet_b_fifo_read_follows_spec_port_type():
    text = _CORPUS.read_text()
    # the async-FIFO readback skill must defer to the spec port type, NOT force
    # combinational.
    i = text.index("async-FIFO readback")
    section = text[i:i + 1500]
    assert "FOLLOWS THE SPEC" in section.upper() or "follows the spec" in section.lower()
    assert "output reg rdata" in section          # names the registered case
    assert "do NOT default" in section or "do not default" in section.lower()
    # it must NOT issue a blanket "Make the RAM read COMBINATIONAL" imperative.
    assert "Make the RAM read COMBINATIONAL" not in section


def test_facet_a_shifter_rotate_only_carveout():
    text = _CORPUS.read_text()
    i = text.index("Shift-amount-controlled shifter")
    section = text[i:i + 1500]
    # the carve-out must be rotate-ONLY (forbids zero-fill), not the loose
    # "rotate explicitly" that tripped on "shift OR rotate".
    assert "rotate-ONLY" in section
    assert "shift OR rotate" in section or "shifts or rotates" in section.lower()
    # the loose pre-fix phrasing must be gone.
    assert "specs that state rotate explicitly" not in section


# ── (d) §4.05 no-leak: a spec-deferring pair is NOT flagged ───────────────────
def test_noleak_spec_deferring_pair_not_flagged():
    ok = (
        "### Skill: fifo read A\n"
        "**What to do**: Make the RAM read COMBINATIONAL when the spec port is a wire.\n\n"
        "### Skill: fifo read B\n"
        "**What to do**: Implement a REGISTERED read; the RAM-read type FOLLOWS "
        "THE SPEC port declaration, do not default.\n")
    assert A.audit_text(ok) == []


# ── unrelated-genre no-false-fire (the FSM combinational-helper case) ─────────
def test_noleak_unrelated_genre_combinational_not_compared():
    """A 'combinational' directive in an FSM section must NOT be compared against
    a 'registered read' directive elsewhere — read-timing is genre-bound to FIFO."""
    blob = (
        "### Skill: FSM combinational helper\n"
        "**What to do**: Inline combinational helpers into the always block.\n\n"
        "### Skill: pipeline registered read\n"
        "**What to do**: Implement a REGISTERED read on posedge clk.\n")
    assert A.audit_text(blob) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
