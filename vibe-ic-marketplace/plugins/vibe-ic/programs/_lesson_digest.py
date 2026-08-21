#!/usr/bin/env python3
"""_lesson_digest.py — shared deterministic renderer of the captured-lesson
digest from `agents/ic-expert-agent.md` `### Skill:` sections.

WHY THIS MODULE EXISTS (routing-gap fix)
----------------------------------------
The benchmark-enhancement-capture loop appends chip-AGNOSTIC general-pattern
`### Skill:` sections to `agents/ic-expert-agent.md`. The Shape-C benchmark
setup (`benchmark_dispatch._render_lesson_digest`) already renders them into a
`lessons.md` that blind single-shot authors MUST read. But the PRODUCTION
spec-to-rtl path — `design_one_shot_runner.step_rtl_gen` WAIVING to the AI
author (Shape-B / runner-driven) — surfaced NO lessons, so a runner-driven
author re-invented a genre-DETERMINED topology (e.g. the canonical
odd/fractional clock-divider dual-edge-OR LEVEL form) and fell into a wording
trap, mismatching the golden even though the GENERAL recovery was already
captured in the corpus.

This module hoists the digest renderer out of `benchmark_dispatch.py` so BOTH
the benchmark setup AND the production runner WAIVE surface the SAME corpus.
The render is fully deterministic (no LLM), and the corpus is by-construction
chip-AGNOSTIC (no design identifiers, no oracle data) — so surfacing it
preserves blindness while preventing already-captured recoveries from
recurring. It is NOT a per-genre filter: it surfaces the WHOLE general corpus
(every active `### Skill:`), so it can never leak a dataset-specific answer and
can never mis-route by guessing a genre.
"""
from __future__ import annotations
import re
from pathlib import Path

EXPERT_AGENT_MD = Path(__file__).resolve().parent.parent / "agents" / "ic-expert-agent.md"

# §4.1 BLINDNESS — the author-facing digest must carry GENERAL topology/convention
# patterns ONLY, never a "benchmark-design-X → use-structure-Y" association. Some
# captured `### Skill:` sections cite the specific benchmark design they were
# verified against as PROVENANCE (e.g. "the level form host-PASSes freq_divbyodd",
# "Prob098_circuit7", "circuit7"). Surfacing those literal identifiers to a BLIND
# author leaks a design-name→solution mapping (a sibling-knowledge blindness
# violation). Scrub the dataset identifiers at render time — the general lesson
# content is untouched; only the leaking provenance token is neutralised. This
# protects BOTH the Shape-C and the production spec-to-rtl digests, and guards
# future lessons that name a design.
# Case-INSENSITIVE (Step-2.7: PROB099 / Circuit7 / FREQ_DIVBYODD case-variants
# must scrub too). Robustly neutralising the STRUCTURED dataset identifiers also
# defangs an oracle-value leak: a concrete value is only a cheat when BOUND to a
# named design ("Prob099 expects 0xF2"); strip the name and "a benchmark design
# expects 0xF2" carries no usable association. Bare ad-hoc design leafs (a raw
# module name) and standalone general constants are deliberately NOT scrubbed
# here — they cannot be enumerated mechanically and a value-class scrub would
# over-scrub general protocol facts (e.g. the public eSPI error code 0x02); their
# blindness is the CAPTURE-TIME policy's job (a `### Skill:` section is a GENERAL
# pattern by construction, verified blindness-clean on the live 83-lesson corpus).
_DESIGN_ID_RE = re.compile(
    r"\b(?:"
    r"cvdp_[A-Za-z0-9_]+"               # CVDP cid (cvdp_copilot_<x>_0007)
    r"|Prob\d+(?:_[A-Za-z0-9]+)*"       # VerilogEval ProbNNN[_name]
    r"|circuit\d+"                       # VerilogEval circuitN family
    r"|freq_div[a-z]+"                   # RTLLM frequency dividers
    r"|verified_[A-Za-z0-9_]+"           # RTLLM golden filenames
    r"|kmap\d+"                          # K-map problem leafs
    r")\b",
    re.IGNORECASE,
)


def _scrub_design_identifiers(text: str) -> str:
    """Neutralise benchmark design identifiers so the author-facing digest carries
    no design-name→solution association (blindness-preserving). See _DESIGN_ID_RE
    for scope (structured dataset ids, case-insensitive) and its honest limit
    (bare leafs / standalone constants are the capture-time policy's domain)."""
    return _DESIGN_ID_RE.sub("a benchmark design", text)

# The provenance line names a PLUGIN SOURCE file, and this head is written into
# a RUN TREE. No spelling of that path can resolve from a run tree: the citation
# resolver's ladder walks the citing document's directory up to the scan root
# (`benchmark-data/ic` by default) and stops there, so it never reaches
# `vibe-ic-marketplace/plugins/...`. Writing it as a bare backticked path
# therefore made every rendered digest carry a citation that could not resolve
# from where it was cited — 10 of the 38 pre-existing unresolved citations
# counted in #1168, one per run that shipped a `lessons.md`. The path stays
# fully readable; it is no longer spelled as a citation of a shipped artefact,
# and the head now says outright that it is not in this tree.
_DIGEST_HEAD = (
    "# Captured-lesson digest (READ BEFORE AUTHORING)\n\n"
    "Rendered deterministically from the general-pattern `### Skill:` sections\n"
    "of the IC-expert corpus — plugin source, NOT shipped in this run tree:\n"
    "vibe-ic-marketplace/plugins/vibe-ic/agents/ic-expert-agent.md\n"
    "These are chip-AGNOSTIC patterns captured\n"
    "from prior close-loop recoveries — no design identifiers, no oracle data —\n"
    "so reading them preserves blindness while preventing already-captured\n"
    "recoveries from recurring.\n\n"
    "MANDATORY (#733 — staged != consumed): BEFORE authoring EACH design you MUST\n"
    "(1) open this digest, (2) keyword-match the design GENRE against each\n"
    "section's '**When to apply**' line, and (3) APPLY every matched\n"
    "genre-convention section. Section 4-E: apply ONLY unless the spec states\n"
    "otherwise.\n\n")


def render_lesson_digest(run_p: Path,
                         expert_md: Path = EXPERT_AGENT_MD) -> int:
    """Render every ACTIVE `### Skill:` section (retired `### ~~Skill:`
    strikethrough sections excluded) of ``expert_md`` into ``run_p/lessons.md``.

    Deterministic extraction — no LLM. Returns the number of lessons written
    (0 if the corpus file is missing or has no active lessons; the file is NOT
    written in that case).

    NOTE (2026-07-02): the IC Expert DB is DELIBERATELY *not* appended into this
    same digest. A/B measurement on 94 hard CVDP designs showed that folding the
    DB knowledge into the ONE author's already-267KB digest LOWERED single-shot
    recovery (38 → 31) — the extra text diluted attention. The DB's value is
    COMPLEMENTARY (a DUAL-TRACK second author), not additive to one digest:
    general-blind ∪ DB-informed = 51 (+13). So the DB is surfaced separately via
    `render_ic_expert_db_digest` to an INDEPENDENT second-track author whose
    result cross-checks the first — see design_one_shot_runner's dual-track WAIVE.
    """
    if not expert_md.is_file():
        return 0
    lessons: list[str] = []
    cur: list[str] | None = None
    for line in expert_md.read_text(errors="replace").splitlines():
        if line.startswith("### "):
            if cur:
                lessons.append("\n".join(cur).rstrip())
            cur = [line] if line.startswith("### Skill:") else None
            continue
        if line.startswith("## ") or line.startswith("# "):
            if cur:
                lessons.append("\n".join(cur).rstrip())
            cur = None
            continue
        if cur is not None:
            cur.append(line)
    if cur:
        lessons.append("\n".join(cur).rstrip())
    if not lessons:
        return 0
    body = _scrub_design_identifiers("\n\n".join(lessons))
    run_p.mkdir(parents=True, exist_ok=True)
    (run_p / "lessons.md").write_text(_DIGEST_HEAD + body + "\n")
    return len(lessons)


def render_ic_expert_db_digest(run_p: Path, prompt_text: str, k: int = 5) -> int:
    """Render the RELEVANT IC Expert DB design-class knowledge for this design's
    prompt into ``run_p/ic_expert_db.md`` — a SEPARATE artifact for an
    INDEPENDENT dual-track (second) author, NOT folded into the main lessons
    digest (measured to dilute a single author; see render_lesson_digest note).
    Best-effort: returns 0 (no file written) if the DB / query module is absent
    or nothing matches. Deterministic — the LLM only consumes the result."""
    if not prompt_text or not prompt_text.strip():
        return 0
    try:
        import ic_expert_db_query as _db  # sibling program (general-core)
        hits = _db.query(prompt_text, k=k)
    except Exception:  # noqa: BLE001
        return 0
    if not hits:
        return 0
    run_p.mkdir(parents=True, exist_ok=True)
    (run_p / "ic_expert_db.md").write_text(_db.render(hits))
    return len(hits)
