#!/usr/bin/env python3
"""programs/lessons_corpus_consistency_check.py — ORGANIC #741

Self-consistency audit for the blind-authoring lessons corpus
(`agents/ic-expert-agent.md`, which the general benchmark solve entry renders
into each run's `lessons.md`).

WHY THIS EXISTS
---------------
#718/#733 made the blind author READ + APPLY the genre-convention digest. That
amplified a latent risk: a convention section can encode an *actively wrong*
directive that steers a faithful author to the FAILING choice. #741 found two —
a barrel-shifter §4-E carve-out that contradicted its own sibling skill, and an
async-FIFO "make the RAM read COMBINATIONAL" directive that contradicted the
corpus's own "do not default to combinational; read which it is" rule and
inverted the golden's registered read.

The durable guard: no two `### Skill:` sections may prescribe OPPOSITE actions on
the same directive AXIS for the same design GENRE. This program parses the
corpus structurally and flags such a contradiction deterministically — so a
future harmful convention cannot ship into the digest unnoticed.

chip-AGNOSTIC: detection keys on genre keywords + directive-polarity tokens +
the spec-deference escape phrase. No chip / vendor / SKU / design-name literal.

DIRECTIVE AXES (each = two opposite poles on one design decision)
----------------------------------------------------------------
A section "takes a pole" on an axis when its body contains a pole's token in an
IMPERATIVE form (Make/Implement/Use/Default to/Keep ...). A section is EXEMPT
from contradicting on that axis when it DEFERS TO THE SPEC — it contains a
spec-deference phrase (e.g. "follows the spec", "read which it is",
"do not default", "the spec port type wins", "unless the spec"). Two sections
sharing a genre that take OPPOSITE poles on the same axis, with NEITHER
deferring to the spec, are a CONTRADICTION.

The same author-source check is used by the digest renderer. It refuses explicit
oracle behaviour/answer authority, not mentions of verification or legitimate
references supplied as design inputs. This CLI is an audit; at render time a
finding blocks only the contaminated knowledge artifact, with a named refusal.

EXIT CODES
----------
  0  consistent (or no corpus / no genre overlap)
  1  >=1 contradictory directive or oracle-authority finding (listed)
  2  usage / I/O error
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── genre keywords: a section is "about" a genre if its heading or body names it.
_GENRES = {
    "fifo": ("fifo",),
    "shifter": ("shifter", "barrel shift", "shift-amount", "shift amount"),
    "counter": ("counter",),
    "fsm": ("fsm", "state machine"),
    "encoder": ("encoder",),
    "decoder": ("decoder",),
    "arbiter": ("arbiter",),
    "crc": ("crc",),
    "uart": ("uart",),
    "spi": ("spi",),
}

# ── directive axes: (axis_name, applicable_genres, pole_A_tokens, pole_B_tokens).
# An axis is checked ONLY within the genre(s) where that decision is a real
# design choice — so a "combinational" mention in an unrelated genre (e.g. an
# FSM's combinational-helper inlining) is never compared against a FIFO's
# read-timing pole. This genre-binding is what keeps the audit from false-firing
# on sections that merely share a polarity token by coincidence.
# A pole is "taken" only in an IMPERATIVE clause (see _IMPERATIVE_RE) so that a
# descriptive mention (e.g. "the registered-read variant is only correct when…")
# does not count as prescribing that pole. The pole tokens additionally require
# the contested NOUN (the RAM/data read for read-timing; the shift operation for
# shift-kind) so an axis fires only on the genuine decision.
_AXES = [
    ("read-timing", ("fifo",),
     # pole A: combinational read (of the RAM/data)
     (r"\b(?:ram|data|rdata|mem(?:ory)?)\b[^.;\n]{0,40}\bcombinational\b",
      r"\bcombinational\b[^.;\n]{0,40}\b(?:ram|read|rdata|mem(?:ory)?)\b",
      r"\bzero-cycle\b[^.;\n]{0,20}\bread\b"),
     # pole B: registered read (of the RAM/data)
     (r"\bregistered\b[^.;\n]{0,40}\bread\b",
      r"\b(?:ram|data|rdata|mem(?:ory)?)\b[^.;\n]{0,40}\bregistered\b",
      r"\bone-cycle read\b")),
    ("shift-kind", ("shifter",),
     # pole A: rotate / wrap-around
     (r"\brotate\b", r"\bwrap-around\b", r"\bwraparound\b"),
     # pole B: logical / zero-fill shift
     (r"\blogical shift\b", r"\bzero-fill\b", r"\bzero fill\b")),
]

# imperative lead-ins that mark a clause as PRESCRIPTIVE (taking a pole).
_IMPERATIVE_RE = re.compile(
    r"\b(make|implement|use|default to|keep|emit|drive|set|write)\b",
    re.IGNORECASE)

# spec-deference phrases: a section carrying any of these conditions its choice
# on what the SPEC declares (rather than hard-coding a fixed pole), so it DEFERS
# to the spec on the contested decision and is exempt. The list is deliberately
# broad on the "condition the choice on the spec" intent — a harmful section
# that hard-codes a pole (e.g. "Make the RAM read COMBINATIONAL") names no such
# condition and is still flagged.
_SPEC_DEFERENCE = re.compile(
    r"follows the spec|follow the spec|read which it is|do not default|"
    r"don'?t default|spec port type|unless the spec|the spec(?:'s)?\b[^.;\n]{0,30}\bport|"
    r"match(?:es|ed)? (?:the |to the )?spec|per the spec|spec[- ]declared|"
    r"when the spec|from the spec|what the spec|"
    r"the spec(?:'s)? ?(?:explicitly )?(?:says|states|declares|forbids|wants)|"
    r"reads? .{0,30}from the spec|follow(?:s|ing)? the (?:declared |stated )?spec",
    re.IGNORECASE)

def _split_skill_sections(text: str) -> List[Tuple[str, str]]:
    """Return active Skill sections, with the same heading boundaries as render."""
    out: List[Tuple[str, str]] = []
    heading = None
    body: List[str] = []
    for line in text.splitlines():
        if line.startswith(("# ", "## ", "### ")):
            if heading is not None:
                out.append((heading, "\n".join(body).rstrip()))
            heading = (line[len("### Skill:"):].strip()
                       if line.startswith("### Skill:") else None)
            body = []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        out.append((heading, "\n".join(body).rstrip()))
    return out


# These are authority claims, not a list of benchmark names or forbidden words.
# Keep verification provenance (including blind A/B), public constants, and
# references explicitly supplied by the input legal. A deference sentence
# elsewhere in a lesson cannot license a separate hidden-answer assertion.
_AUTHOR_AUTHORITY_PATTERNS = {
    "ORACLE_OUTCOME_JUSTIFICATION": (
        r"oracle-(?:FAIL|PASS)|fail\w*\s+the\s+oracle"),
    "PROMPT_OVERRIDE": (
        r"do\s*not\s+implement\s+that\s+literal|OPPOSITE\s+of\s+the\s+literal|"
        r"outrank\w*\s+a\s+relative"),
    "ORACLE_BEHAVIOUR": (
        r"\b(?:oracle|golden(?:\s+(?:reference\s+)?(?:model|RTL|implementation))?|"
        r"hidden(?:/golden)?\s+(?:TB|testbench))\s+"
        r"(?:holds?|expects?|requires?|wants?|applies|outputs?|produces?|returns?)\b"),
    "HIDDEN_REFERENCE_AUTHORITY": (
        r"\bhidden\s+(?:TB|testbench)\b[^.!?]{0,180}?\b(?:wins|overrides?|outranks?)\b|"
        r"\bgolden\s+(?:reference\s+)?model\b[^.!?]{0,200}?"
        r"\b(?:must\s+match|authoritative|not\s+the\s+ambiguous)\b|"
        r"\bgolden\s+RTL\b[^.!?]{0,160}?\b(?:ARE|IS)\s+the\s+spec\b"),
    "SCORER_PHASE_AUTHORITY": (
        r"\bscorer\s+confirms\b[^.!?]{0,100}?\bgolden\b|"
        r"\bguaranteed\s+match\b[^.!?]{0,100}?\bgolden\b"),
    "ORIGINAL_GOLDEN_AS_INPUT": (
        r"\b(?:reference|example)\b[^.!?]{0,100}?\bor\s+the\s+original\s+golden\b"),
}


def author_source_findings(text: str) -> List[str]:
    """Recognise explicit oracle-authority claims in author-facing prose.

    This bounded lexical check does not establish semantic purity of arbitrary
    natural language. Source review still owns paraphrases outside these forms.
    """
    # Markdown soft wraps do not change a claim's source. Keep paragraph
    # boundaries while treating a single physical newline as whitespace.
    text = re.sub(r"\n[ \t]*\n", "\n\n", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    findings = []
    for name, pattern in _AUTHOR_AUTHORITY_PATTERNS.items():
        # Overlapping starts keep a later source claim visible even if an
        # earlier qualified span reaches across it before exemption.
        for match in re.finditer("(?=(" + pattern + "))", text, re.IGNORECASE):
            prefix = re.split(r"[.!?;\n]", text[:match.start()])[-1]
            # A qualifier must attach to THIS claim's source, not be an escape
            # phrase elsewhere in a paragraph/lesson containing hidden advice.
            # Intervening words must describe that source; arbitrary prose is
            # not a bridge from a supplied document to an oracle assertion.
            supplied = re.search(
                r"\b(?:provided|supplied|given|input[- ]declared|spec[- ]derived)"
                r"(?:\s+(?:public|normative|executable|reference|independent|arithmetic)){0,3}"
                r"\s+(?:the\s+)?$", prefix, re.I)
            prohibition = re.search(
                r"\b(?:never|do not|don't|must not)\s+"
                r"(?:read|inspect|consult|use|assume|follow)\s+(?:the\s+)?$", prefix, re.I)
            if prohibition or (supplied and not re.search(
                    r"\bhidden\b", supplied.group() + match.group(1), re.I)):
                continue
            findings.append(name)
            break
    return findings


class LessonSourceRefusal(ValueError):
    """A contaminated knowledge artifact was withheld from the author."""

    def __init__(self, surface: str, findings: List[str]):
        self.record = {"reason_class": "AUTHOR_LESSON_ORACLE_AUTHORITY",
                       "surface": surface, "rules": sorted(set(findings))}
        # No rejected source text (including its title) reaches the author.
        super().__init__(f"AUTHOR_LESSON_ORACLE_AUTHORITY: {surface} withheld; "
                         + ", ".join(self.record["rules"]))


def require_author_source(text: str, surface: str, output: Path) -> None:
    findings = author_source_findings(text)
    if findings:
        # This renderer owns the artifact. A failed rerender must not leave a
        # previously rendered answer available at the advertised output path.
        output.unlink(missing_ok=True)
        raise LessonSourceRefusal(surface, findings)


def _section_genres(heading: str, body: str) -> List[str]:
    blob = (heading + "\n" + body).lower()
    return [g for g, kws in _GENRES.items() if any(k in blob for k in kws)]


# The PRESCRIPTIVE directive of a `### Skill:` section lives in its
# "**What to do**:" block (the imperative action), NOT in the "**Pattern**:" /
# "**Worked pattern**:" descriptive blocks (which often MENTION the opposite
# pole to describe the wrong default being corrected — e.g. "Classic templates
# default to a REGISTERED read" sitting above a "Make the read COMBINATIONAL"
# directive). Scanning the directive block only is what lets the audit read the
# section's ACTUAL prescription instead of being confused by a descriptive
# mention of the other pole. (#741 adversarial-review fix.)
_DIRECTIVE_BLOCK_RE = re.compile(
    r"\*\*What to do\*\*\s*:?(.*?)(?=\n\s*\*\*[A-Z]|\Z)", re.IGNORECASE | re.DOTALL)
# strong prescriptive verbs (the section's own action); deliberately EXCLUDES
# "default to", which in a Pattern line describes a convention being corrected.
_PRESCRIBE_RE = re.compile(
    r"\b(make|implement|use|emit|drive|set|keep|assign|write|reserve)\b",
    re.IGNORECASE)


def _directive_text(body: str) -> str:
    """The prescriptive '**What to do**:' block, or the whole body if absent."""
    m = _DIRECTIVE_BLOCK_RE.search(body)
    return m.group(1) if m else body


def _prescriptive_clauses(directive: str) -> str:
    """Clauses in the directive block that carry a strong prescriptive verb."""
    out: List[str] = []
    for raw in re.split(r"(?<=[.;:])\s+|\n", directive):
        if _PRESCRIBE_RE.search(raw):
            out.append(raw)
    return "\n".join(out) if out else directive


def _poles_taken(body: str, pole_a, pole_b) -> Tuple[bool, bool]:
    """Does the section PRESCRIBE pole A / pole B? Read ONLY the prescriptive
    clauses of the '**What to do**:' directive block, so a descriptive mention
    of the opposite pole (in a Pattern/Worked-pattern line) is not mistaken for
    a second prescription."""
    imp = _prescriptive_clauses(_directive_text(body))
    took_a = any(re.search(p, imp, re.IGNORECASE) for p in pole_a)
    took_b = any(re.search(p, imp, re.IGNORECASE) for p in pole_b)
    return took_a, took_b


def audit_text(text: str) -> List[Dict]:
    """Return directive and author-source findings (empty == consistent)."""
    sections = _split_skill_sections(text)
    enriched = []
    for heading, body in sections:
        genres = _section_genres(heading, body)
        defers = bool(_SPEC_DEFERENCE.search(body))
        enriched.append((heading, body, genres, defers))

    contradictions: List[Dict] = [
        {"reason_class": "AUTHOR_LESSON_ORACLE_AUTHORITY", "section": heading,
         "rules": findings}
        for heading, body in sections
        if (findings := author_source_findings(heading + "\n" + body))]
    for axis_name, axis_genres, pole_a, pole_b in _AXES:
        # The correct guidance on a spec-governed axis (read-timing, shift-kind)
        # is "FOLLOW THE SPEC" — the reference vectors are captured against the
        # spec's declaration, so the right pole is whichever the spec states.
        # Therefore ANY section that HARD-PRESCRIBES a single fixed pole on this
        # axis WITHOUT deferring to the spec is itself the defect: it steers a
        # faithful author to a fixed choice that fails whenever the spec wants the
        # other pole (the exact #741 async-FIFO "Make it COMBINATIONAL" harm).
        # Collect every such hard, non-deferring single-pole steer.
        steers: List[Tuple[str, str, str]] = []  # (heading, genre, pole)
        for heading, body, genres, defers in enriched:
            applicable = [g for g in genres if g in axis_genres]
            if not applicable or defers:
                continue
            took_a, took_b = _poles_taken(body, pole_a, pole_b)
            if took_a == took_b:
                continue  # neither, or both (ambiguous — not a single-pole steer)
            pole = "A" if took_a else "B"
            for g in applicable:
                steers.append((heading, g, pole))
        by_genre: Dict[str, List[Tuple[str, str]]] = {}
        for heading, g, pole in steers:
            by_genre.setdefault(g, []).append((heading, pole))
        for g, items in by_genre.items():
            headings = sorted({h for h, _p in items})
            poles = sorted({p for _h, p in items})
            contradictions.append({
                "axis": axis_name,
                "genre": g,
                # the harmful hard-coded steer(s): a fixed pole on a
                # spec-governed axis with no spec-deference. Each one overrides
                # the spec-faithful default and contradicts the corpus's own
                # "read which it is" guidance for this axis.
                "hard_coded_sections": headings,
                "poles": poles,
            })
    return contradictions


def audit_file(path: Path) -> List[Dict]:
    return audit_text(path.read_text(errors="replace"))


def _default_corpus() -> Path:
    return Path(__file__).resolve().parents[1] / "agents" / "ic-expert-agent.md"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit the lessons corpus for contradictory genre "
                    "directives (ORGANIC #741). chip-AGNOSTIC.")
    ap.add_argument("corpus", nargs="?", default=None,
                    help="path to the lessons corpus markdown "
                         "(default: agents/ic-expert-agent.md)")
    args = ap.parse_args(argv)
    path = Path(args.corpus) if args.corpus else _default_corpus()
    if not path.is_file():
        print(f"ERROR: corpus not found: {path}", file=sys.stderr)
        return 2
    contradictions = audit_file(path)
    if not contradictions:
        print(f"PASS: lessons corpus self-consistent — no oracle-authority claim "
              f"or Skill section "
              f"hard-codes a single pole on a spec-governed axis without "
              f"deferring to the spec ({path.name})")
        return 0
    print(f"FAIL: {len(contradictions)} harmful directive/authority finding(s) in "
          f"{path.name}:", file=sys.stderr)
    for c in contradictions:
        if c.get("reason_class"):
            print(f"  - {c['reason_class']}: {c['section']}: {c['rules']}",
                  file=sys.stderr)
            continue
        print(f"  - axis={c['axis']} genre={c['genre']} poles={c['poles']}: "
              f"{c['hard_coded_sections']} hard-codes a fixed pole on a "
              f"spec-governed axis without deferring to the spec", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
