#!/usr/bin/env python3
"""programs/lesson_consumption_check.py — staged != CONSUMED, enforced by a program.

WHY THIS EXISTS
---------------
The captured-lesson digest is rendered into every run by `_lesson_digest.py`, and
#733 ("staged != consumed") tried to make authors APPLY it by injecting a stronger
MANDATORY paragraph into the digest header. That fix is itself PROSE — and prose
regresses. This codebase already proved that twice (an in-gate fix held across 17
fresh agents while the identical content as free-text guidance regressed; and a
31-agent batch run produced ZERO spontaneous plugin-program calls).

It regressed again, measurably: a blind author was handed a digest section that
quoted its design's exact trap sentence and said "Do NOT implement that literal
reading", including the exact fail signature ("everything right except literal
RISE->open polarity - oracle-FAIL on more than half the vectors"). The author did
not consume it and reproduced that signature precisely (57% mismatch). Three
independent authors that DID consume the same staged section all PASSED.

#741 built `lessons_corpus_consistency_check.py` to audit whether a lesson's
CONTENT is correct. Nothing audited whether a lesson was USED. This is that gate.

WHAT IT DOES (GENERAL CORE — benchmark-AGNOSTIC)
-----------------------------------------------
Operates on plain strings: a prompt/spec text and a rendered digest. It does NOT
know about any benchmark record format, so the general Phase-1 path (a design doc
with a staged digest) gets the identical verdict with no harness present.

  1. Parse the digest into `### Skill:` sections.
  2. Score each section against the prompt by ISF-weighted term overlap.
     ISF (inverse section frequency) = log(N_sections / sections_containing(t)),
     computed from the digest itself, so it is ALWAYS available (no external
     corpus) and self-calibrating: terms that appear in many sections ("output",
     "clock", "reset") are automatically down-weighted toward zero, while
     distinctive genre terms ("thermometer", "supplemental", "barrel") dominate.
     No hand-curated stopword list to rot.
  3. A section is a STRONG match when its normalized score clears --threshold AND
     it contributes at least --min-distinctive high-ISF terms (guards against a
     long section matching on an accumulation of weak terms).
  4. Report, or under --strict REQUIRE, an acknowledgement record naming every
     strong match.

DUAL-TRACK (ORGANIC #716): the gate emits the RAW EVIDENCE it judged on — every
matched section with its score and the exact terms that drove it — so an
independent track can re-judge the same inputs and disagreements can be converged.
A verdict with no attached evidence cannot be cross-checked.

ACKNOWLEDGEMENT RECORD (--ack, JSON)
------------------------------------
    {"lessons_applied": [
        {"section": "<section title substring>", "applied": true,
         "note": "one line: how it changed the RTL, or why it does not apply"}]}
`applied: false` is a LEGITIMATE acknowledgement — the author considered the
section and rejected it (the digest's own rule is "apply UNLESS the spec states
otherwise"). What this gate forbids is SILENCE on a strongly-matched section.

chip-AGNOSTIC / no-cheat: reads only the prompt and already-captured general
patterns. It never reads a golden, a testbench, or any oracle, so it cannot leak
solution knowledge and is safe inside a blind authoring loop.

EXIT CODES
----------
  0 = no strong match, or every strong match acknowledged, or advisory mode
  1 = --strict and >=1 strongly-matched section unacknowledged
  2 = IO / usage error
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

SECTION_RE = re.compile(r"^###\s+Skill:\s*(.+?)\s*$", re.M)
# A "term" is an alphabetic token of >=4 chars; short tokens are almost always
# grammar words and carry no genre signal.
TERM_RE = re.compile(r"[A-Za-z][A-Za-z-]{3,}")


# CLOSED-CLASS FUNCTION WORDS — grammar, never genre. This is deliberately NOT a
# domain stopword list (those rot as the domain shifts); English function words
# are a fixed, finite, domain-independent set. They must be removed outright
# because inverse-section-frequency alone cannot down-weight a function word
# that happens to be rare in a SMALL corpus — the exact false positive this
# guard's own test caught ("with" scoring as a distinctive term).
_FUNCTION_WORDS = frozenset("""
that this these those with from into onto upon when then than there their them
they your yours have has had been being will would shall should must may might
can could does doing done make makes made only also both each every either
neither other others some such same very more most less least much many
about above below after before during under over between within without
while where which whose what whom here hence thus therefore however
because since unless until always never often sometimes
""".split())


def _terms(text: str) -> set:
    return {t for t in (m.group(0).lower().strip("-")
                        for m in TERM_RE.finditer(text))
            if t not in _FUNCTION_WORDS}


def parse_digest(digest_text: str) -> List[Dict]:
    """Split a rendered digest into its `### Skill:` sections. GENERAL CORE."""
    marks = list(SECTION_RE.finditer(digest_text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(digest_text)
        body = digest_text[m.end():end]
        title = m.group(1)
        out.append({"title": title, "body": body,
                    "terms": _terms(title + " " + body)})
    return out


def _isf(sections: List[Dict]) -> Dict[str, float]:
    """Inverse section frequency from the digest itself. GENERAL CORE."""
    n = max(1, len(sections))
    df: Dict[str, int] = {}
    for s in sections:
        for t in s["terms"]:
            df[t] = df.get(t, 0) + 1
    return {t: math.log(n / c) for t, c in df.items()}


# A term's ISF is bounded above by log(N_sections), so a FIXED distinctive-ISF
# floor is unsound: on a small digest no term can ever clear it and a strong
# match becomes impossible. Scale the floor to the digest instead — a term is
# "distinctive" when it is rare RELATIVE to the corpus it was measured in.
_DISTINCTIVE_FRACTION = 0.45

# ISF needs enough sections for "rare" to be informative: with a handful of
# sections max ISF = log(N) is tiny and the gradations are too coarse to
# separate a genre term from an ordinary one. Below this, the gate still
# REPORTS its matches but must never BLOCK on them — an honest low-confidence
# regime, not a silent pass and not a false block.
_MIN_SECTIONS_FOR_STRICT = 8


def distinctive_floor(n_sections: int) -> float:
    """Scale-relative distinctiveness floor. GENERAL CORE."""
    return _DISTINCTIVE_FRACTION * math.log(max(2, n_sections))


def match_sections(prompt_text: str, sections: List[Dict],
                   threshold: float = 0.14, min_distinctive: int = 2,
                   distinctive_isf: float = None) -> List[Dict]:
    """Score every section against the prompt. GENERAL CORE — pure strings in,
    ranked matches + the evidence that drove each one out."""
    if distinctive_isf is None:
        distinctive_isf = distinctive_floor(len(sections))
    isf = _isf(sections)
    pterms = _terms(prompt_text)
    results = []
    for s in sections:
        # Only terms carrying signal can contribute at all.
        weights = {t: isf.get(t, 0.0) for t in s["terms"]}
        total = sum(w for w in weights.values() if w > 0)
        if total <= 0:
            continue
        hit = {t: w for t, w in weights.items() if w > 0 and t in pterms}
        score = sum(hit.values()) / total
        distinctive = sorted((t for t, w in hit.items() if w >= distinctive_isf),
                             key=lambda t: -hit[t])
        strong = score >= threshold and len(distinctive) >= min_distinctive
        if hit:
            results.append({
                "section": s["title"],
                "score": round(score, 4),
                "strong": strong,
                "distinctive_terms": distinctive[:12],
                "n_matched_terms": len(hit),
            })
    results.sort(key=lambda r: -r["score"])
    return results


def check_acknowledgement(matches: List[Dict], ack: dict) -> List[Dict]:
    """Which STRONG matches were never acknowledged? GENERAL CORE."""
    entries = (ack or {}).get("lessons_applied") or []
    acked = []
    for e in entries:
        if isinstance(e, dict) and e.get("section"):
            acked.append(str(e["section"]).lower())
        elif isinstance(e, str):
            acked.append(e.lower())
    missing = []
    for m in matches:
        if not m["strong"]:
            continue
        title = m["section"].lower()
        if not any(a in title or title in a or
                   (len(a) > 12 and a[:12] in title) for a in acked):
            missing.append(m)
    return missing


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify that a strongly-matched captured lesson was CONSUMED, "
                    "not merely staged (ORGANIC #733 enforced program-first).")
    ap.add_argument("--prompt", required=True, help="prompt / spec text file")
    ap.add_argument("--digest", required=True, help="rendered lesson digest (lessons.md)")
    ap.add_argument("--ack", help="acknowledgement JSON written by the author")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when a strongly-matched section is unacknowledged")
    ap.add_argument("--threshold", type=float, default=0.14)
    ap.add_argument("--min-distinctive", type=int, default=2)
    ap.add_argument("--distinctive-isf", type=float, default=None,
                    help="override the scale-relative distinctiveness floor "
                         "(default: 0.45*log(N_sections))")
    ap.add_argument("--top", type=int, default=5, help="how many matches to report")
    ap.add_argument("--json", help="write the evidence report here (dual-track input)")
    a = ap.parse_args(argv)

    try:
        prompt = Path(a.prompt).read_text(errors="ignore")
        digest = Path(a.digest).read_text(errors="ignore")
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    ack = {}
    if a.ack and Path(a.ack).is_file():
        try:
            ack = json.loads(Path(a.ack).read_text())
        except (OSError, ValueError) as e:
            print(f"error: unreadable acknowledgement record: {e}", file=sys.stderr)
            return 2

    sections = parse_digest(digest)
    if not sections:
        print("NOTICE: digest carries no '### Skill:' sections — nothing to enforce.")
        return 0
    matches = match_sections(prompt, sections, a.threshold, a.min_distinctive,
                             a.distinctive_isf)
    strong = [m for m in matches if m["strong"]]
    missing = check_acknowledgement(matches, ack)

    report = {
        "gate": "lesson_consumption_check",
        "sections_in_digest": len(sections),
        "strong_matches": len(strong),
        "unacknowledged": len(missing),
        # DUAL-TRACK: the raw evidence this verdict was judged on.
        "evidence": matches[:max(a.top, len(strong))],
    }
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(report, indent=2) + "\n")

    if not strong:
        print(f"PASS: no strongly-matched lesson section "
              f"({len(sections)} scanned; top score "
              f"{matches[0]['score'] if matches else 0.0}).")
        return 0
    for m in strong:
        mark = "UNACKNOWLEDGED" if m in missing else "acknowledged"
        print(f"  [{mark}] {m['score']:.3f}  {m['section'][:78]}")
        print(f"      driven by: {', '.join(m['distinctive_terms'][:8])}")
    if not missing:
        print(f"PASS: all {len(strong)} strongly-matched lesson section(s) acknowledged.")
        return 0
    if a.strict and len(sections) < _MIN_SECTIONS_FOR_STRICT:
        print(f"NOTICE: digest has only {len(sections)} section(s) "
              f"(< {_MIN_SECTIONS_FOR_STRICT}) — too few for the inverse-section-"
              f"frequency weighting to separate genre terms from ordinary ones "
              f"reliably. Reporting {len(missing)} unacknowledged match(es) as "
              f"ADVISORY; not blocking on a low-confidence signal.")
        return 0
    print(f"\n{'FAIL' if a.strict else 'WARN'}: {len(missing)} strongly-matched "
          f"lesson section(s) NOT acknowledged. The author must record, per section, "
          f"applied true/false plus a one-line note — 'applied: false' is a valid "
          f"answer; SILENCE is not.", file=sys.stderr if a.strict else sys.stdout)
    return 1 if a.strict else 0


if __name__ == "__main__":
    sys.exit(main())
