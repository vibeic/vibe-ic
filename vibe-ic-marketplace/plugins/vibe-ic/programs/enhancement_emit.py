#!/usr/bin/env python3
"""enhancement_emit.py — driver for the benchmark-enhancement-capture skill.

Takes a recoveries.json listing (step, design, before-state, after-state,
ai-reasoning, bucket) records and produces concrete artifacts ROUTED PER STEP
via benchmark-harness/CAPTURE_ROUTING.json:
  - markdown fragments appended to the RIGHT skill file per step
    (ic-expert-agent.md for design judgment; sta-review for timing;
     drc-fix for DRC; analog-topology-select for analog; etc.) (Bucket B)
  - python patch sketches targeting the RIGHT program file per step
    (rtl_hygiene_lint.py for RTL hygiene; phase3_one_shot_runner.py for
     PnR; analog_a2_topology_select_check.py for analog A2; etc.) (Bucket A)
  - YAML backlog entries for community/backlogs/ (Bucket C)
  - a discard log for Bucket D entries

The actual program/skill modifications are NEVER applied automatically — this
script just emits candidates for human review (Bucket A) or direct append
(Bucket B / C). Bucket A patches require a corpus-sweep verification before
being merged, per the skill's honesty rule.

recoveries.json schema (v0.1.35+):
  [{
    "step": "phase3.pnr_setup_repair",     # canonical step ID (see CAPTURE_ROUTING.json)
    "design": "sha256",
    "bucket": "A" | "B" | "C" | "D",
    # Bucket-B (skill section) fields:
    "skill_title": "...",
    "pattern": "...",
    "when": "...",
    "what": "...",
    "example": "...",
    "generality": "...",
    # Bucket-A (program rule) fields:
    "rule_name": "...",
    "docstring": "...",
    "expected_signal": "WARN"|"ERROR"|"AUTO-FIX",
    "fix_action": "...",
    # Bucket-C (backlog) fields:
    "title": "...",
    "suggested_fix": "...",
    "backlog_slug": "...",
    "backlog_type": "bug"|"enhancement",
    "severity": "P0"|"P1"|"P2"|"P3",
    "component": "...",
    "session_context": "...",
    # Bucket-D fields:
    "why_discard": "..."
  }, ...]

Usage:
    python3 enhancement_emit.py --records recoveries.json --out-dir candidates/
"""
from __future__ import annotations
import argparse, json, datetime, sys
from pathlib import Path

ROUTING_FILE = Path(__file__).resolve().parent.parent / "benchmark-harness" / "CAPTURE_ROUTING.json"


def _load_routing() -> dict:
    if not ROUTING_FILE.is_file():
        return {"steps": {}, "default_routing": {
            "bucket_A_program": None,
            "bucket_B_skill_file": "agents/ic-expert-agent.md",
        }}
    return json.loads(ROUTING_FILE.read_text())


def route_for(step: str, routing: dict) -> dict:
    """Return the target paths for a given step ID, with default fallback."""
    return routing.get("steps", {}).get(step, routing.get("default_routing", {}))


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")[:80]


# v0.1.39 (audit Finding 1 fix) — DESIGN_LEAK_PATTERN matches benchmark-design
# identifiers that the honesty rule forbids in Bucket-B skill text:
#   - VerilogEval Prob IDs:  ProbNNN_…  (e.g. Prob089_ece241_2014_q5a)
#   - benchmark family tags: RTLLM, VerilogEval-{v2,Human,Machine}, CVDP, MetRex, …
# When matched, emit_skill_section sanitizes them OUT of the worked-pattern field
# so the captured skill stays general regardless of what the caller passed.
_DESIGN_LEAK_PATTERN = (
    r"\bProb\d+[A-Za-z0-9_]*"                                              # ProbNNN_xxx
    r"|\b(?:RTLLM|VerilogEval(?:-(?:v[12]|Human|Machine))?|CVDP|MetRex|ResBench|RTL-Repo|PyHDL-Eval)\b"
)
import re as _leak_re  # local alias to avoid clobbering caller's `re` if any


def _scrub_design_leak(text: str) -> str:
    """Strip benchmark-design-identifier leaks from free-text fields.

    Layered strategy (each layer catches what the prior one missed):

      Layer 1 — known-leak parentheticals. Drop ONLY brackets whose lead-in
        is an attribution keyword AND whose contents look like an
        identifier (or an enumerated benchmark token). This preserves
        legitimate spec text like "(e.g. mod-256)" / "(per IEEE 1364)"
        that doesn't contain identifiers. The narrower rule was added in
        v0.1.40 after the v0.1.39 broad-strip damaged technical content
        (re-audit NEW-4 fix).

      Layer 2 — enumerated benchmark-identifier tokens (ProbNNN_…, RTLLM,
        VerilogEval-{v2,Human,Machine,…}, CVDP, MetRex, ResBench,
        RTL-Repo, PyHDL-Eval) anywhere they appear.

      Layer 3 — design-name shapes that aren't in any enumeration. Strict
        heuristic: an identifier of >=2 underscore-separated lowercase
        tokens (e.g. radix2_div, sequence_detector, freq_divbyeven,
        adder_pipe_64bit) appearing in `(from X)` / `(captured by X)` /
        `(refs X)` / `worked example: X:` contexts. Added in v0.1.40 —
        catches design leaf names that no enumeration can list. Outside
        attribution contexts, snake_case identifiers are technical RTL
        signal/module names that should NOT be touched.

    Honest about scrubbing — appends an `[anonymized]` marker so the reader
    can see the sanitisation happened. chip-AGNOSTIC.
    """
    if not text:
        return text
    original = text
    # Layer 1 — narrow attribution-bracket strip. v0.1.40 (re-audit NEW-4)
    # requires the bracket interior to look like an identifier list (alphanum
    # + `_` + commas + whitespace + Prob-or-bench token) so legitimate spec
    # parentheticals like "(per IEEE 1364)" and "(e.g. mod-256)" survive.
    # Identifier-shape: contains at least one token matching either an
    # enumerated bench token OR a 2+-underscore-separated identifier.
    _ATTR_LEAD = r"(?:from|captured\s+by|worked\s+(?:miss|example))\s+"
    _IDENT_INSIDE = (r"[A-Za-z0-9_,\s\-]*"
                     r"(?:" + _DESIGN_LEAK_PATTERN +
                     r"|[a-z][a-z0-9]*(?:_[a-z0-9]+){1,})"
                     r"[A-Za-z0-9_,\s\-]*")
    text = _leak_re.sub(
        r"\(\s*" + _ATTR_LEAD + _IDENT_INSIDE + r"\)",
        "", text, flags=_leak_re.IGNORECASE)
    # Layer 2 — enumerated tokens anywhere outside (…).
    text = _leak_re.sub(_DESIGN_LEAK_PATTERN, "", text, flags=_leak_re.IGNORECASE)
    # Layer 3 — design leaf names in `Worked example:` / `Refs:` style prose
    # (no parenthesis). Only fires in explicit attribution contexts.
    text = _leak_re.sub(
        r"(?i)(worked\s+(?:miss|example)|refs?)\s*[:\-]\s*[a-z][a-z0-9_]*(?:_[a-z0-9]+){1,}",
        r"\1: [anonymized]", text)
    text = _leak_re.sub(r"\s{2,}", " ", text)
    text = _leak_re.sub(r"\s+([,.;:])", r"\1", text)
    text = text.strip()
    if text != original:
        text += "  [identifiers anonymized per benchmark-enhancement-capture honesty rule]"
    return text


def _refuse_if_leaks(field_name: str, value: str) -> str:
    """v0.1.40 (re-audit F1 補洞) — for caller-supplied `skill_title` and
    `backlog_slug`: do NOT silently scrub (those become the section header /
    filename; silent scrub would corrupt them). Instead RAISE with a clear
    error so the caller fixes the input.

    A skill_title like "Moore latency in Prob089" is exactly the
    sloppy-caller failure mode the prior audit called out. We refuse rather
    than scrub.
    """
    if not value:
        return value
    scrubbed = _scrub_design_leak(value)
    if scrubbed != value:
        raise ValueError(
            f"{field_name} contains a benchmark-design identifier "
            f"({value!r}); refusing to write it to a permanent artifact. "
            f"Per benchmark-enhancement-capture honesty rule, the {field_name} "
            f"must describe the GENERAL pattern, not the originating "
            f"benchmark design. Suggested rewrite: {scrubbed!r}")
    return value


def emit_skill_section(rec: dict) -> str:
    # v0.1.39 (audit Finding 1) — REQUIRE skill_title; never default to the
    # design slug (which would inject the benchmark identifier into the section
    # header).
    name = rec.get("skill_title")
    if not name:
        raise ValueError(
            "emit_skill_section: rec missing 'skill_title' — refusing to "
            "default to design slug per benchmark-enhancement-capture honesty "
            "rule ('NEVER add a Bucket B skill section that names specific "
            "benchmark design identifiers'). Caller must supply a generic "
            "skill title describing the general PATTERN.")
    # v0.1.40 (re-audit F1 補洞) — title must itself be leak-free; refuse on
    # leaky title (a sloppy caller is the failure mode the prior audit
    # warned about).
    name = _refuse_if_leaks("skill_title", name)
    pattern = _scrub_design_leak(rec.get("pattern", ""))
    when = _scrub_design_leak(rec.get("when", ""))
    what = _scrub_design_leak(rec.get("what", ""))
    example = _scrub_design_leak(rec.get("example", ""))
    generality = _scrub_design_leak(rec.get("generality", ""))
    return (
        f"### Skill: {name}\n\n"
        f"**Pattern**: {pattern}\n\n"
        f"**When to apply**: {when}\n\n"
        f"**What to do**: {what}\n\n"
        f"**Worked pattern** (anonymized): {example}\n\n"
        f"**Why this is GENERAL**: {generality}\n\n"
        f"_Captured by benchmark-enhancement-capture {datetime.date.today().isoformat()}._\n"
    )


def emit_program_rule_sketch(rec: dict) -> str:
    # v0.1.39 (audit Finding 1) — drop the "Source: <design>" breadcrumb so the
    # in-tree program sketch is chip-AGNOSTIC. Pattern + docstring still capture
    # the lesson without naming the originating benchmark design.
    rname = _slug(rec.get("rule_name", "todo")).replace("-", "_")
    pattern = _scrub_design_leak(rec.get("pattern", ""))
    docstring = _scrub_design_leak(rec.get("docstring", ""))
    fix_action = _scrub_design_leak(rec.get("fix_action", ""))
    return (
        f"# v0.1.34+ — auto-captured by benchmark-enhancement-capture\n"
        f"# Pattern: {pattern}\n"
        f"# CORPUS-SWEEP REQUIRED before merging: zero false-positives across\n"
        f"# the open-benchmark corpora used by `score_iverilog_tb.py`.\n"
        f"\n"
        f"def rule_{rname}(sample_text, ports):\n"
        f"    \"\"\"{docstring}\"\"\"\n"
        f"    # Expected signal: {rec.get('expected_signal', 'WARN')}\n"
        f"    # Suggested fix action: {fix_action}\n"
        f"    return []  # list of findings — TODO implement\n"
    )


def emit_backlog(rec: dict, today: str):
    # v0.1.39 (audit Finding 1) — REQUIRE backlog_slug; never default to the
    # design slug. Backlog filenames become part of the repo's permanent
    # record; a Prob ID baked into a filename can never be silently scrubbed
    # later without breaking links.
    slug = rec.get("backlog_slug")
    if not slug:
        raise ValueError(
            "emit_backlog: rec missing 'backlog_slug' — refusing to default "
            "to design slug. Caller must supply a generic kebab-case slug "
            "describing the issue category (e.g. 'rtl-hygiene-internal-reg-"
            "init'), not the originating benchmark design name.")
    # v0.1.40 (re-audit F1 補洞) — slug becomes part of the permanent
    # filename and YAML id. Refuse on leaky slug.
    slug = _refuse_if_leaks("backlog_slug", slug)
    slug = _slug(slug)
    fname = f"ORGANIC-{today.replace('-','')}-{slug}.yaml"
    indent = "  "
    pat = _scrub_design_leak(rec.get("pattern", "")).replace("\n", "\n" + indent)
    fix = _scrub_design_leak(rec.get("suggested_fix", "")).replace("\n", "\n" + indent)
    ctx = _scrub_design_leak(rec.get("session_context", ""))
    body = (
        f"type: {rec.get('backlog_type', 'enhancement')}\n"
        f"severity: {rec.get('severity', 'P2')}\n"
        f"component: {rec.get('component', '')}\n"
        f"plugin_version: \"{rec.get('plugin_version', '0.1.33')}\"\n\n"
        f"title: >-\n  {_scrub_design_leak(rec.get('title', ''))}\n\n"
        f"pattern: |\n  {pat}\n\n"
        f"suggested_fix: |\n  {fix}\n\n"
        f"id: \"ORGANIC-{today.replace('-','')}-{slug}\"\n"
        f"submitted_at: \"{today}T00:00:00+08:00\"\n"
        f"session_context: >-\n  {ctx}\n"
    )
    return fname, body


def emit_discard_note(rec: dict) -> str:
    # v0.1.39 (audit Finding 1) — discard log is an INTERNAL session record
    # (lives in candidates/, NOT shipped as plugin content), so keeping the
    # design name here is fine for audit traceability. But scrub the why-discard
    # prose so a copy-pasted discard reason can't smuggle a Prob ID into a
    # downstream Bucket-B section.
    return (f"- **{rec.get('design', '?')}**: "
            f"{_scrub_design_leak(rec.get('why_discard', 'no reason given'))}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--records", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()

    recs = json.loads(Path(a.records).read_text())
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    routing = _load_routing()

    by_bucket = {"A": [], "B": [], "C": [], "D": []}
    for r in recs:
        b = (r.get("bucket") or "D").upper()
        by_bucket.setdefault(b, []).append(r)

    summary = {"date": today, "totals": {k: len(v) for k, v in by_bucket.items()},
               "routing_used": {}}

    # v0.1.35+ — route Bucket A and Bucket B per `step` field
    if by_bucket["A"]:
        # group by target program file
        by_target: dict[str, list[dict]] = {}
        for r in by_bucket["A"]:
            tgt = route_for(r.get("step", ""), routing).get(
                "bucket_A_program", "programs/__unrouted__.py")
            by_target.setdefault(tgt, []).append(r)
        bucket_A_files = []
        for tgt, items in by_target.items():
            safe = tgt.replace("/", "_").replace(".py", "")
            p = out / f"bucket_A_{safe}_rule_sketches.py"
            chunks = [f"# Bucket A — program-rule sketches for {tgt}\n"
                      f"# Corpus-sweep REQUIRED before merging into {tgt}.\n"]
            for r in items:
                chunks.append(emit_program_rule_sketch(r))
            p.write_text("\n".join(chunks))
            bucket_A_files.append(str(p))
        summary["bucket_A_files"] = bucket_A_files
        summary["routing_used"]["bucket_A"] = list(by_target.keys())

    if by_bucket["B"]:
        by_target = {}
        for r in by_bucket["B"]:
            tgt = route_for(r.get("step", ""), routing).get(
                "bucket_B_skill_file", "agents/ic-expert-agent.md")
            by_target.setdefault(tgt, []).append(r)
        bucket_B_files = []
        for tgt, items in by_target.items():
            safe = tgt.replace("/", "_").replace(".md", "")
            p = out / f"bucket_B_{safe}_sections.md"
            chunks = [f"# Bucket B — skill sections to APPEND to {tgt}\n"]
            for r in items:
                chunks.append(emit_skill_section(r))
            p.write_text("\n".join(chunks))
            bucket_B_files.append({"target": tgt, "patch": str(p)})
        summary["bucket_B_files"] = bucket_B_files
        summary["routing_used"]["bucket_B"] = sorted({x["target"] for x in bucket_B_files})

    if by_bucket["C"]:
        d = out / "bucket_C_backlogs"
        d.mkdir(exist_ok=True)
        files = []
        for r in by_bucket["C"]:
            fname, body = emit_backlog(r, today)
            (d / fname).write_text(body)
            files.append(fname)
        summary["bucket_C_dir"] = str(d)
        summary["bucket_C_files"] = files

    if by_bucket["D"]:
        p = out / "bucket_D_discarded.md"
        chunks = [f"# Bucket D — discarded ({len(by_bucket['D'])} entries)\n"]
        for r in by_bucket["D"]:
            chunks.append(emit_discard_note(r))
        p.write_text("\n".join(chunks))
        summary["bucket_D_file"] = str(p)

    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
