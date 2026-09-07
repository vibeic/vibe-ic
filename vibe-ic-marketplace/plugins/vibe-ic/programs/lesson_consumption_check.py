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

THE DENOMINATOR MUST BE THE ONE THAT WAS SCORED (vibe-ic#2086)
--------------------------------------------------------------
This gate used to take `--prompt <file>` and nothing else, so it could not tell
"I examined this design's spec and nothing applied" from "you handed me one file
out of nine and I examined almost nothing". Measured on 8HD-9: the spec-to-rtl
WAIVE handoff scored 202 strong matches against `_gather_spec_text(project)` and
in the same breath printed a verification command taking `--prompt <spec-file>`;
run literally on one input doc that command scored 0 of 212 and printed
`PASS: no strongly-matched lesson section` with rc 0. All three of one-file,
nine-docs and the gathered text exited 0 with 0, 17 and 202 matches.

Two repairs, and both are needed:
  * `--project <dir>` scores `_path_layout.gather_spec_text(project)` — the SAME
    function the runner scores, so the denominator is reproducible by
    construction rather than by the author picking the right file; and
  * `--scoring-record <json>` pins what the runner actually scored (the digest's
    section count, the sha256 and byte length of the spec text, its source list,
    and the strongly-matched section titles it NAMED to the author). When the
    text this run scored is not that text, the gate REFUSES with rc 2 and says
    which — a strict subset of the project's input, or a different spec
    altogether. A PASS that examined nothing is the defect; refusing is the fix.

EXIT CODES
----------
  0 = no strong match, or every strong match acknowledged, or advisory mode
  1 = --strict and >=1 strongly-matched section unacknowledged
  2 = IO / usage error, or REFUSED / NOT_MEASURED — never a vacuous pass
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl  # noqa: E402  — the ONE spec-text gather (#2086)

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


#: The runner writes this next to the digest it rendered; the gate reads it.
SCORING_RECORD_NAME = "lessons_scoring_record.json"


def spec_identity(spec_text: str) -> Dict:
    """CONTENT identity of the text that was scored. GENERAL CORE.

    sha256 over the exact bytes, plus the length, so a refusal can say HOW the
    two inputs differ and not merely THAT they differ. Never mtime: this corpus
    is distributed by clone/copy/rsync, none of which preserve mtimes.
    """
    data = spec_text.encode("utf-8", "replace")
    return {"spec_bytes": len(data),
            "spec_sha256": hashlib.sha256(data).hexdigest()}


def spec_subset_relation(text: str, full: str) -> str:
    """Is `text` the whole spec, a strict SUBSET of it, or something else?
    GENERAL CORE — pure strings, no project layout.

    Two ways to be a subset, because a caller may hand over the bytes of one
    source file (literally contained) or a re-concatenation of several of them
    (not byte-contained, but contributing no term the whole gather does not
    already carry). Both are the #2086 defect: a run that scored less than the
    spec the scorer scored, printing a verdict that reads like the whole.
    """
    if text == full:
        return "SAME"
    if not text or not full:
        return "DIFFERENT"
    if text in full:
        return "STRICT_SUBSET"
    t, f = _terms(text), _terms(full)
    if t and t < f:
        return "STRICT_SUBSET"
    return "DIFFERENT"


def build_scoring_record(project, digest_path: str, sections: List[Dict],
                         matches: List[Dict], spec_text: str) -> Dict:
    """What the SCORER scored, written at the moment it scored it. GENERAL CORE.

    The record exists so the verification command the scorer prints can be
    checked against the scoring it is verifying. Without it the author's run and
    the scorer's run are two unrelated measurements that happen to share a
    digest (#2086).
    """
    rec = {
        "gate": "lesson_consumption_check",
        "record_version": 1,
        "digest": str(digest_path),
        "sections_in_digest": len(sections),
        "strong_sections": [m["section"] for m in matches if m.get("strong")],
        "spec_sources": [],
    }
    rec["strong_matches"] = len(rec["strong_sections"])
    if project is not None:
        rec["project"] = str(project)
        try:
            rec["spec_sources"] = [str(f) for f in _pl.spec_text_sources(Path(project))]
        except OSError:
            rec["spec_sources"] = []
    rec.update(spec_identity(spec_text))
    return rec


def record_disagreement(record: Dict, sections: List[Dict], spec_text: str,
                        prompt_path: Optional[str] = None) -> Optional[str]:
    """Why this run is NOT a verification of `record`, by name. GENERAL CORE.

    Returns None when the two agree, otherwise a one-line reason. Every branch
    is a REFUSAL, never a downgrade to a pass: the whole point is that "I
    matched nothing" and "there was nothing to match" must not print the same.
    """
    if not isinstance(record, dict) or record.get("gate") != "lesson_consumption_check":
        return ("the scoring record is not a lesson_consumption_check record "
                "(no `gate` field naming this gate)")
    want_sections = record.get("sections_in_digest")
    if isinstance(want_sections, int) and want_sections != len(sections):
        return (f"the digest moved under the record: it was scored over "
                f"{want_sections} '### Skill:' section(s), this run parsed "
                f"{len(sections)}")
    here = spec_identity(spec_text)
    want_sha = record.get("spec_sha256")
    if want_sha and want_sha != here["spec_sha256"]:
        want_bytes = record.get("spec_bytes")
        sources = [str(x) for x in (record.get("spec_sources") or [])]
        named = ""
        if prompt_path:
            for i, src in enumerate(sources, 1):
                if Path(src).name == Path(prompt_path).name:
                    named = (f" — it is source {i} of {len(sources)} in that "
                             f"gather ({src})")
                    break
        subset = ""
        proj = record.get("project")
        if proj:
            try:
                full = _pl.gather_spec_text(Path(proj))
            except OSError:
                full = ""
            if spec_subset_relation(spec_text, full) == "STRICT_SUBSET":
                subset = "STRICT SUBSET — "
        return (f"{subset}the text this run scored is not the text the record "
                f"was scored over ({here['spec_bytes']} bytes vs "
                f"{want_bytes} bytes){named}. Score the SAME source with "
                f"`--project {proj or '<project>'}`, or re-score the record.")
    return None


def strong_set_disagreement(record: Dict, strong: List[Dict]) -> Optional[str]:
    """The two numbers that must agree: the count the scorer NAMED to the author
    and the count this verification reproduces. MEMBERSHIP, not count — a
    substitution of equal size is exactly what a count cannot see. GENERAL CORE.
    """
    want = record.get("strong_sections")
    if not isinstance(want, list):
        return None
    got = {m["section"] for m in strong}
    want_set = {str(x) for x in want}
    if got == want_set:
        return None
    missing = sorted(want_set - got)
    extra = sorted(got - want_set)
    return (f"this run reproduces {len(got)} strongly-matched "
            f"section(s), the record names {len(want_set)}; "
            f"{len(missing)} in the record are absent here"
            + (f" (e.g. {missing[0][:60]!r})" if missing else "")
            + f" and {len(extra)} here are absent from the record"
            + (f" (e.g. {extra[0][:60]!r})" if extra else "")
            + ". The number you were handed and the number you can reproduce "
              "must be the same number.")


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify that a strongly-matched captured lesson was CONSUMED, "
                    "not merely staged (ORGANIC #733 enforced program-first).")
    ap.add_argument("--prompt", help="prompt / spec text file")
    ap.add_argument("--project",
                    help="score this design's WHOLE gathered spec text — the same "
                         "`_path_layout.gather_spec_text` the runner scored (#2086). "
                         "With --prompt as well, the named file is REFUSED when it "
                         "is a strict subset of that gather.")
    ap.add_argument("--scoring-record",
                    help="the record the scorer wrote when it named the strong "
                         "matches to the author (phase2/stage1/"
                         + SCORING_RECORD_NAME + "). The gate REFUSES when what it "
                         "scored is not what the record was scored over.")
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

    if not a.prompt and not a.project:
        print("error: name a spec source — --project <dir> (the whole gathered "
              "spec, what the scorer scored) or --prompt <file>", file=sys.stderr)
        return 2
    try:
        digest = Path(a.digest).read_text(errors="ignore")
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    # THE SPEC SOURCE. --project is the canonical one: it is the same gather the
    # scorer scored, so the author cannot reproduce a different denominator by
    # picking a different file (#2086).
    project_text = None
    if a.project:
        try:
            project_text = _pl.gather_spec_text(Path(a.project))
        except OSError as e:
            print(f"error: could not gather the project's spec text: {e}",
                  file=sys.stderr)
            return 2
        if not project_text:
            print(f"NOT_MEASURED: {a.project} carries no spec text source "
                  f"(phase1/input_prompt, phase1/input_doc, "
                  f"phase1/generated_docs) — refusing rather than scoring an "
                  f"empty prompt.", file=sys.stderr)
            return 2
    if a.prompt:
        try:
            prompt = Path(a.prompt).read_text(errors="ignore")
        except OSError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        # A FILE NAMED ALONGSIDE A PROJECT IS THE DEFECT ITSELF. Scoring one
        # input doc out of nine printed `PASS: no strongly-matched lesson
        # section` at 0 of 212 (#2086) — indistinguishable, in its own output,
        # from a design nothing applies to.
        rel = spec_subset_relation(prompt, project_text) if project_text is not None else "SAME"
        if rel == "STRICT_SUBSET":
            n_src = len(_pl.spec_text_sources(Path(a.project)))
            print(f"REFUSED: STRICT SUBSET — --prompt {a.prompt} is "
                  f"{len(prompt)} bytes of the {len(project_text)} bytes this "
                  f"project's {n_src} spec source(s) gather to. Scoring a "
                  f"subset cannot verify the whole; drop --prompt and let "
                  f"--project name the spec.", file=sys.stderr)
            return 2
        if rel == "DIFFERENT":
            print(f"REFUSED: --prompt {a.prompt} ({len(prompt)} bytes) is not "
                  f"the text --project {a.project} gathers ({len(project_text)} "
                  f"bytes). Name ONE spec source.", file=sys.stderr)
            return 2
    else:
        prompt = project_text
    ack = {}
    if a.ack and Path(a.ack).is_file():
        try:
            ack = json.loads(Path(a.ack).read_text())
        except (OSError, ValueError) as e:
            print(f"error: unreadable acknowledgement record: {e}", file=sys.stderr)
            return 2

    # THE RECORD THE SCORER WROTE. An unreadable one is NOT_MEASURED, never a
    # pass: a verification whose subject cannot be read has verified nothing.
    record = None
    if a.scoring_record:
        try:
            record = json.loads(Path(a.scoring_record).read_text())
        except (OSError, ValueError) as e:
            print(f"NOT_MEASURED: unreadable scoring record "
                  f"{a.scoring_record}: {e}", file=sys.stderr)
            return 2

    sections = parse_digest(digest)
    if record is not None:
        why = record_disagreement(record, sections, prompt, a.prompt)
        if why:
            print(f"NOT_MEASURED (refusing — a PASS that examined something "
                  f"else is not a PASS): {why}", file=sys.stderr)
            return 2
    if not sections:
        print("NOTICE: digest carries no '### Skill:' sections — nothing to enforce.")
        return 0
    matches = match_sections(prompt, sections, a.threshold, a.min_distinctive,
                             a.distinctive_isf)
    strong = [m for m in matches if m["strong"]]
    if record is not None:
        why = strong_set_disagreement(record, strong)
        if why:
            print(f"NOT_MEASURED (refusing — a PASS that examined something "
                  f"else is not a PASS): {why}", file=sys.stderr)
            return 2
    missing = check_acknowledgement(matches, ack)

    report = {
        "gate": "lesson_consumption_check",
        "sections_in_digest": len(sections),
        "strong_matches": len(strong),
        "unacknowledged": len(missing),
        # WHAT WAS SCORED — so a later reader can tell a verification of this
        # design's spec from a verification of one file out of nine (#2086).
        "spec_source": ("project:" + str(a.project)) if a.project else ("prompt:" + str(a.prompt)),
        "verified_against_record": str(a.scoring_record) if a.scoring_record else None,
        # DUAL-TRACK: the raw evidence this verdict was judged on.
        "evidence": matches[:max(a.top, len(strong))],
    }
    report.update(spec_identity(prompt))
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
