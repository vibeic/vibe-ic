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


def _strip_backticks(text: str) -> str:
    """v0.1.42 — replace `code` spans with same-length whitespace.

    Backticks are the legitimate escape hatch for IC technical identifiers
    (e.g. `rst_n`, `always_ff`, `eda_cocotb`) that have meaning across
    designs, not just in one benchmark. After this strip, any underscore
    or Prob## that remains is, by definition, NOT bracketed by the caller
    as a known technical identifier — so it's either a legitimate phrase
    or a benchmark leak. The leak-detector runs on the stripped text.

    Offsets are preserved so a future caller computing line numbers from
    the stripped text gets correct results.
    """
    return _leak_re.sub(r"`[^`]*`", lambda m: " " * len(m.group()), text)


_INDUSTRY_TECH_ALLOWLIST = frozenset({
    # v0.1.42 — a tiny seed set of GENERAL Verilog/MCP identifiers that
    # legitimately appear in skill text without backticks. Keep this SHORT
    # and add to it only when a real round-trip test demands it. Each
    # entry must be a general-convention term (industry vocabulary) NOT a
    # benchmark design leaf-name. The structural rule (require backticks)
    # is the default; this allowlist is the exception, not the policy.
    "rst_n", "reset_n", "rst", "clk", "clk_n", "clk_p",
    "always_ff", "always_comb", "always_latch",
    "rtl_hygiene_lint", "spec_conformance_check", "chip_top",
    "eda_cocotb", "eda_lint", "eda_synth",
    "phase1_engine", "phase2_one_shot_runner", "phase3_one_shot_runner",
    "ic_class_registry", "benchmark_enhancement_capture",
    "test_runner", "harness_library",
})


def _validate_general_text(field_name: str, value: str,
                            *, allow_underscores: bool = False) -> str:
    """v0.1.42 (Round-4 audit fix) — universal structural check applied to
    EVERY field that becomes plugin content (title, slug, body fields).

    Round-4 auditor's verdict: the v0.1.41 inversion only protected
    title+slug; the 5 free-text body fields (pattern, when, what, example,
    generality) still leaked. v0.1.42 applies the same structural rule to
    all 7 fields, with a meaningful escape hatch:

      Backtick-wrapped identifiers ARE allowed.
      Bare underscore identifiers (snake_case) NOT in the industry-tech
        allowlist ARE refused.
      Case-insensitive `prob\\d+` ANYWHERE — refused.
      Enumerated benchmark family names (RTLLM / VerilogEval-* / CVDP /
        MetRex / etc.) — refused.
      Any single token > 25 chars without a space — refused.

    The escape hatch means a skill author who wants to discuss `rst_n` as
    an industry convention can write `` `rst_n` `` in markdown style;
    the bare snake_case `radix2_div` (a benchmark leaf name) is refused
    structurally. The rule applies symmetrically across the 7 fields so
    a Round-5 auditor cannot produce a clean-title + dirty-body leak.

    Raises ValueError citing the structural violation; caller MUST fix
    the input (either by wrapping a legitimate identifier in backticks
    OR by rewriting in general-pattern language).
    """
    if not value:
        return value
    # Backtick-wrapped identifiers are exempt (the caller's positive
    # declaration that this is a known technical term, not a benchmark
    # leaf-name).
    text = _strip_backticks(value)
    # 1. Snake-case identifiers OUTSIDE the industry allowlist.
    for m in _leak_re.finditer(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b", text):
        tok = m.group()
        if tok.lower() in _INDUSTRY_TECH_ALLOWLIST:
            continue
        raise ValueError(
            f"{field_name} contains a bare underscore-bearing identifier "
            f"({tok!r}); refusing. Per benchmark-enhancement-capture "
            f"honesty rule (v0.1.42 structural rule): if {tok!r} is a "
            f"legitimate industry-convention term (rst_n, always_ff), "
            f"wrap it in markdown backticks: `{tok}`. If {tok!r} is a "
            f"benchmark design leaf-name (radix2_div, freq_divbyeven), "
            f"rewrite the {field_name} to describe the GENERAL pattern "
            f"without naming the specific design.")
    # 1b. v0.1.42 (Round-4 NEW-2 bypass) — digit-embedded-in-lowercase
    #     token: matches `radix2div`, `mux256to1`, `freqdivbyeven`. Require
    #     2+ letters BEFORE digit so legit short forms like `1st` /
    #     `2nd` (ordinal English) and `a4converter` (one-letter prefix) are
    #     not refused.
    for m in _leak_re.finditer(r"\b[a-z]{2,}\d+[a-z][A-Za-z0-9]*\b", text):
        tok = m.group()
        if tok in _INDUSTRY_TECH_ALLOWLIST:
            continue
        raise ValueError(
            f"{field_name} contains a digit-embedded-in-lowercase "
            f"identifier ({tok!r}); refusing. This shape matches benchmark "
            f"design leaf-names (mux256to1, radix2div). Wrap in backticks "
            f"if legitimate: `{tok}` — or rewrite as general pattern.")
    # 1c. v0.1.42 (Round-4 NEW-2 bypass) — camelCase / PascalCase compound
    #     identifier: `[a-z][A-Z][a-z]` boundary inside a single token, like
    #     `freqDivByEven`, `SequenceDetector`. Even legitimate Verilog
    #     identifiers like `TopModule` should be wrapped in backticks in
    #     skill text (markdown best practice).
    for m in _leak_re.finditer(r"\b[A-Za-z]*[a-z][A-Z][a-z]+[A-Za-z0-9]*\b", text):
        tok = m.group()
        if tok in _INDUSTRY_TECH_ALLOWLIST:
            continue
        raise ValueError(
            f"{field_name} contains a camelCase/PascalCase compound "
            f"identifier ({tok!r}); refusing. Wrap in backticks if "
            f"legitimate: `{tok}` — or rewrite as space-separated words.")
    # 1d. v0.1.42 (Round-4 NEW-2 bypass) — kebab-case identifier where the
    #     LEADING token is letters+digit shape: `radix2-div`, `mux256-to-1`,
    #     `m2014-q4`. Require 2+ leading letters so single-letter `a4-`
    #     prefixes (`a4-converter-template`) pass — those are conventional
    #     analog-class slugs (A4 = analog phase-4). The reverse form
    #     `2nd-order` (ordinal English) is not matched because it starts
    #     with digit.
    for m in _leak_re.finditer(
            r"\b[a-z]{2,}\d+(?:-[a-z0-9]+){1,}\b", text):
        tok = m.group()
        if tok in _INDUSTRY_TECH_ALLOWLIST:
            continue
        raise ValueError(
            f"{field_name} contains a kebab-case identifier with a "
            f"digit-bearing token ({tok!r}); refusing. This shape matches "
            f"benchmark design leaf-names. Wrap in backticks if legitimate: "
            f"`{tok}`, or rewrite without the digit-bearing token.")
    # 2. Prob## case-insensitive.
    pm = _leak_re.search(r"\bprob\d+\b", text, _leak_re.IGNORECASE)
    if pm:
        raise ValueError(
            f"{field_name} contains a benchmark Prob ID ({pm.group()!r}); "
            f"refusing. Skill content must describe general patterns, not "
            f"specific benchmark problems.")
    # 3. Enumerated benchmark-family tokens (RTLLM / VerilogEval-* / CVDP /
    #    MetRex / ResBench / RTL-Repo / PyHDL-Eval).
    em = _leak_re.search(_DESIGN_LEAK_PATTERN, text, _leak_re.IGNORECASE)
    if em:
        raise ValueError(
            f"{field_name} contains a benchmark family name "
            f"({em.group()!r}); refusing. Describe the general convention "
            f"without naming the source benchmark.")
    # 4. Over-long contiguous alphanumeric token (likely a concatenated
    #    identifier like 'radix2divbyeven' or 'freqdivbyeven').
    for tok in _leak_re.findall(r"[A-Za-z][A-Za-z0-9]+", text):
        if len(tok) > 25:
            raise ValueError(
                f"{field_name} contains an over-long contiguous token "
                f"({tok!r}, {len(tok)} chars) — likely a concatenated "
                f"identifier. Insert spaces or wrap in backticks.")
    # 5. Field-specific shape — slug must be kebab-case AFTER all leak
    #    checks pass.
    if field_name == "backlog_slug":
        if not _leak_re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError(
                f"backlog_slug must be kebab-case "
                f"([a-z0-9-], no uppercase, no underscore): {value!r}")
        for tok in value.split("-"):
            # Note: prob\d+ check at step 2 already catches `prob089`. The
            # NEW-3 Round-4 case `prob-089-issue` has separate `prob` and
            # `089` tokens; the `\bprob\d+\b` check at step 2 won't match
            # split tokens. Catch the dispersed Prob## here:
            if tok == "prob" or _leak_re.fullmatch(r"prob\d+", tok):
                raise ValueError(
                    f"backlog_slug token {tok!r} suggests a benchmark "
                    f"Prob ID (possibly separated by dashes): {value!r}.")
    return value


def _refuse_if_leaks(field_name: str, value: str) -> str:
    """v0.1.42 — thin wrapper preserving v0.1.41 callsites. The structural
    work moved to `_validate_general_text` which is applied to all 7 fields.
    """
    return _validate_general_text(field_name, value)


def _refuse_if_leaks_v0141_DEPRECATED(field_name: str, value: str) -> str:
    """v0.1.41 (re-re-audit Issue 3 fix — STRUCTURAL ALLOWLIST INVERSION).

    Auditor's verdict on v0.1.40's denylist approach: 'every round of audit
    will keep finding leaks of the same shape with different prefixes,
    because the cost of a denylist is unbounded and the cost of an allowlist
    is bounded by the legitimate-input set, which is small.'

    For caller-supplied `skill_title` and `backlog_slug` (which become the
    section header and the permanent backlog filename), we now use a
    STRUCTURAL ALLOWLIST keyed to the legitimate input shape:

      skill_title — a human-readable section header.
        Allowed: Unicode letters (so ΔΣ topology works), digits, space,
                 dash, comma, period, semicolon, colon, apostrophe,
                 forward slash, parens.
        Forbidden: underscore (rules out snake_case identifiers like
                   radix2_div / freq_divbyeven / asyn_fifo).
        Forbidden: ProbNNN sequence (rules out Prob089 / Prob042).
        Forbidden: any single token > 25 chars without a space (rules
                   out concatenated identifiers like radix2divbyeven).

      backlog_slug — a kebab-case filename slug.
        Allowed: lowercase ASCII letters, digits, dashes.
        Forbidden: underscore, uppercase, prob-as-prefix (kebab-token
                   matching `^prob\\d+`).
        Each kebab-token must be <= 25 chars.

    The rule is structural — `radix2_div` fails on 'has underscore'
    regardless of whether 'radix2_div' is a current or future benchmark
    design name. No enumeration to maintain.

    Raises ValueError with the structural violation cited; caller fixes
    the input rather than relying on a regex scrub to remove pieces.
    """
    if not value:
        return value
    if field_name == "skill_title":
        # Forbid underscore-separated identifiers (snake_case).
        if _leak_re.search(r"\w_\w", value):
            raise ValueError(
                f"skill_title contains a benchmark-design identifier "
                f"(underscore-separated identifier — likely an RTL "
                f"module/signal name): {value!r}. Per benchmark-enhancement-"
                f"capture honesty rule (structural allowlist v0.1.41), the "
                f"skill_title must describe the GENERAL pattern in human-"
                f"readable English (use spaces or dashes, not underscores). "
                f"Suggested form: 'Moore latency anomaly in benchmark FSM' "
                f"instead of 'Moore latency in Prob089_ece241_2014_q5a'.")
        # Forbid ProbNNN sequence.
        if _leak_re.search(r"\bProb\d+", value):
            raise ValueError(
                f"skill_title contains a benchmark Prob ID: {value!r}. "
                f"Per benchmark-enhancement-capture honesty rule (structural "
                f"allowlist v0.1.41), skill section headers must not name "
                f"specific benchmark designs. Rewrite as a general pattern "
                f"description.")
        # Forbid over-long token without a space (concatenated identifier).
        for token in _leak_re.split(r"[\s\-]", value):
            if len(token) > 25:
                raise ValueError(
                    f"skill_title contains a single token of length "
                    f"{len(token)} ({token!r}) — likely a concatenated "
                    f"identifier, not a human-readable phrase. Use spaces "
                    f"or dashes between words.")
        return value
    if field_name == "backlog_slug":
        # Must be kebab-case only.
        if not _leak_re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError(
                f"backlog_slug must be kebab-case ([a-z0-9-], no uppercase, "
                f"no underscore): {value!r}. Per benchmark-enhancement-"
                f"capture honesty rule (structural allowlist v0.1.41), the "
                f"slug becomes a permanent filename + YAML id. Rewrite as "
                f"a generic kebab-case category, e.g. 'rtl-hygiene-"
                f"internal-reg-init'.")
        for token in value.split("-"):
            if _leak_re.fullmatch(r"prob\d+", token):
                raise ValueError(
                    f"backlog_slug contains a Prob ID token ({token!r}): "
                    f"{value!r}. Rewrite as a generic category not naming "
                    f"the originating benchmark.")
            if len(token) > 25:
                raise ValueError(
                    f"backlog_slug token {token!r} is {len(token)} chars — "
                    f"likely a concatenated identifier. Use shorter dashed "
                    f"tokens describing the issue category.")
        return value
    # Generic field — fall back to the previous (denylist-scrub) behavior.
    # Used by emit_discard_note for the why_discard prose etc.
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
    name = _validate_general_text("skill_title", name)
    # v0.1.42 (Round-4 audit fix) — the structural rule applies to ALL 5
    # body fields, not just title. A Round-4 reproducer (clean title +
    # `radix2_div` in pattern) would otherwise emit a leaked artifact.
    pattern = _validate_general_text("pattern", rec.get("pattern", ""))
    when = _validate_general_text("when", rec.get("when", ""))
    what = _validate_general_text("what", rec.get("what", ""))
    example = _validate_general_text("example", rec.get("example", ""))
    generality = _validate_general_text("generality", rec.get("generality", ""))
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
    pattern = _validate_general_text("pattern", rec.get("pattern", ""))
    docstring = _validate_general_text("docstring", rec.get("docstring", ""))
    fix_action = _validate_general_text("fix_action", rec.get("fix_action", ""))
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
    slug = _validate_general_text("backlog_slug", slug)
    slug = _slug(slug)
    fname = f"ORGANIC-{today.replace('-','')}-{slug}.yaml"
    indent = "  "
    # v0.1.42 — structural validation across body fields (Round-4 NEW-4 fix).
    pat = _validate_general_text("pattern", rec.get("pattern", "")).replace("\n", "\n" + indent)
    fix = _validate_general_text("suggested_fix", rec.get("suggested_fix", "")).replace("\n", "\n" + indent)
    ctx = _validate_general_text("session_context", rec.get("session_context", ""))
    body = (
        f"type: {rec.get('backlog_type', 'enhancement')}\n"
        f"severity: {rec.get('severity', 'P2')}\n"
        f"component: {rec.get('component', '')}\n"
        f"plugin_version: \"{rec.get('plugin_version', '0.1.33')}\"\n\n"
        f"title: >-\n  {_validate_general_text('title', rec.get('title', ''))}\n\n"
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
