"""Unit tests for enhancement_emit.py — the driver of the
benchmark-enhancement-capture closed loop (v0.1.35).

Eight cases cover the four-bucket routing + per-step target resolution:
  1. Bucket A is routed to the program file declared in CAPTURE_ROUTING.json
  2. Bucket B is routed to the skill file declared in CAPTURE_ROUTING.json
  3. Bucket C emits a YAML backlog with the expected ORGANIC- prefix + schema fields
  4. Bucket D emits a discard log (never silently drops)
  5. Same-bucket records targeting DIFFERENT steps land in DIFFERENT output files
  6. Same-bucket records targeting the SAME step are concatenated into ONE file
  7. Unknown step IDs fall back to the default_routing.bucket_B_skill_file
  8. Summary JSON records every target file touched for review
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from _published_corpus import corpus_root, needs_corpus

SCRIPT = Path(__file__).parent.parent / "enhancement_emit.py"
ROUTING = Path(__file__).parent.parent.parent / "benchmark" / "CAPTURE_ROUTING.json"
assert SCRIPT.exists(), f"missing program: {SCRIPT}"
assert ROUTING.exists(), f"missing routing table: {ROUTING}"


def run(tmp_path: Path, records: list) -> dict:
    rec_file = tmp_path / "recoveries.json"
    rec_file.write_text(json.dumps(records))
    out_dir = tmp_path / "candidates"
    r = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--records", str(rec_file),
         "--out-dir", str(out_dir)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"emit failed: {r.stderr}\n{r.stdout}"
    summary = json.loads((out_dir / "summary.json").read_text())
    return {"out_dir": out_dir, "summary": summary}


# ── 1. Bucket A routes to the program file declared in the routing table ──
def test_bucket_A_routes_per_step(tmp_path):
    rec = [{
        "step": "phase2.rtl_gen",
        "design": "div_16bit", "bucket": "A",
        "rule_name": "restoring-div-remainder-width",
        "docstring": "Restoring division remainder needs `dividend_width` + 1 bits.",
        "expected_signal": "WARN", "fix_action": "Widen remainder reg",
    }]
    res = run(tmp_path, rec)
    # routing for phase2.rtl_gen → programs/rtl_hygiene_lint.py
    a_files = res["summary"].get("bucket_A_files", [])
    assert any("rtl_hygiene_lint" in f for f in a_files), \
        f"phase2.rtl_gen Bucket A should route to rtl_hygiene_lint; got {a_files}"


# ── 2. Bucket B routes to the skill file declared in the routing table ──
def test_bucket_B_routes_per_step(tmp_path):
    rec = [{
        "step": "phase3.pnr_setup_repair",
        "design": "sha256", "bucket": "B", "why_not_bucket_a": "needs NL/convention pattern recognition no regex captures", 
        "skill_title": "PnR setup repair pattern",
        "pattern": "PnR must run `repair_design` + `repair_timing` -setup, not just hold-fix.",
        "when": "any OpenROAD PnR template",
        "what": "add the repair chain", "example": "the hash-core design reached -102 then +10 ns",
        "generality": "universal across OpenROAD-driven PnR",
    }]
    res = run(tmp_path, rec)
    # routing for phase3.pnr_setup_repair → skills/sta-review/SKILL.md
    b_files = res["summary"].get("bucket_B_files", [])
    assert b_files, "Bucket B file not emitted"
    targets = {entry["target"] for entry in b_files}
    assert "skills/sta-review/SKILL.md" in targets, \
        f"phase3.pnr_setup_repair Bucket B should route to sta-review; got {targets}"


# ── 3. Bucket C emits YAML with ORGANIC- prefix + required schema fields ──
def test_bucket_C_emits_backlog_yaml(tmp_path):
    rec = [{
        "step": "analog.A4_corner_sweep",
        "design": "u_hawaii_adc", "bucket": "C", "why_not_bucket_a": "needs NL/convention pattern recognition no regex captures", 
        "title": "Add converter-family templates",
        "pattern": "no ngspice template for adc / `delta_sigma`",
        "suggested_fix": "ship templates",
        "backlog_slug": "a4-converter-template",
        "backlog_type": "enhancement", "severity": "P1",
        "component": "program:analog_real_corner_sweep",
        "session_context": "captured from an analog-converter rerun",
    }]
    res = run(tmp_path, rec)
    files = res["summary"].get("bucket_C_files", [])
    assert files and files[0].startswith("ORGANIC-"), \
        f"Bucket C should emit ORGANIC-prefixed yaml; got {files}"
    yaml_text = (Path(res["summary"]["bucket_C_dir"]) / files[0]).read_text()
    for required in ("type:", "severity:", "component:", "title:", "pattern:",
                     "suggested_fix:", "id:", "submitted_at:"):
        assert required in yaml_text, f"backlog yaml missing field: {required}"


# ── 4. Bucket D produces a discard log (no silent drops) ──
def test_bucket_D_records_discard(tmp_path):
    rec = [{
        "step": "phase2.rtl_gen",
        "design": "ProbXX_only", "bucket": "D",
        "why_discard": "encodes the specific hidden TB convention; pure overfit.",
    }]
    res = run(tmp_path, rec)
    d_file = res["summary"].get("bucket_D_file")
    assert d_file, "Bucket D file must be emitted"
    body = Path(d_file).read_text()
    assert "ProbXX_only" in body and "overfit" in body, \
        "Bucket D log must record the discard reason for honesty"


# ── 5. Same-bucket DIFFERENT-step records land in DIFFERENT output files ──
def test_same_bucket_different_steps_split(tmp_path):
    rec = [
        {"step": "phase3.pnr_setup_repair", "design": "sha256", "bucket": "B", "why_not_bucket_a": "needs NL/convention pattern recognition no regex captures", 
         "skill_title": "PnR repair", "pattern": "x", "when": "y",
         "what": "z", "example": "e", "generality": "g"},
        {"step": "analog.A2_topology", "design": "u_hawaii_adc", "bucket": "B", "why_not_bucket_a": "needs NL/convention pattern recognition no regex captures", 
         "skill_title": "ΔΣ topology", "pattern": "x", "when": "y",
         "what": "z", "example": "e", "generality": "g"},
    ]
    res = run(tmp_path, rec)
    targets = {e["target"] for e in res["summary"]["bucket_B_files"]}
    assert "skills/sta-review/SKILL.md" in targets, "phase3 route lost"
    assert "skills/analog-topology-select/SKILL.md" in targets, "analog route lost"
    assert len(targets) >= 2, f"different steps must land in different files; got {targets}"


# ── 6. Same-bucket SAME-step records concatenate into ONE output file ──
def test_same_bucket_same_step_concatenate(tmp_path):
    rec = [
        {"step": "phase2.rtl_gen", "design": "A", "bucket": "B", "why_not_bucket_a": "needs NL/convention pattern recognition no regex captures", 
         "skill_title": "Skill A", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g"},
        {"step": "phase2.rtl_gen", "design": "B", "bucket": "B", "why_not_bucket_a": "needs NL/convention pattern recognition no regex captures", 
         "skill_title": "Skill B", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g"},
    ]
    res = run(tmp_path, rec)
    b_files = res["summary"]["bucket_B_files"]
    assert len(b_files) == 1, \
        f"two B records on same step should yield 1 file; got {len(b_files)}"
    body = Path(b_files[0]["patch"]).read_text()
    assert "Skill A" in body and "Skill B" in body, \
        "both records must be in the single per-step file"


# ── 7. Unknown step ID falls back to default_routing.bucket_B_skill_file ──
def test_unknown_step_falls_back_to_default(tmp_path):
    rec = [{
        "step": "made.up.step", "design": "X", "bucket": "B", "why_not_bucket_a": "needs NL/convention pattern recognition no regex captures", 
        "skill_title": "Default fallback test", "pattern": "p", "when": "w",
        "what": "x", "example": "e", "generality": "g",
    }]
    res = run(tmp_path, rec)
    targets = {e["target"] for e in res["summary"]["bucket_B_files"]}
    routing = json.loads(ROUTING.read_text())
    default_skill = routing["default_routing"]["bucket_B_skill_file"]
    assert default_skill in targets, \
        f"unknown step should fall back to {default_skill}; got {targets}"


# ── 8. Summary records every target file the session would touch (audit trail) ──
def test_summary_records_routing_used(tmp_path):
    rec = [
        {"step": "phase3.pnr_setup_repair", "design": "sha256", "bucket": "B", "why_not_bucket_a": "needs NL/convention pattern recognition no regex captures", 
         "skill_title": "X", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g"},
        {"step": "phase3.drc", "design": "sha256", "bucket": "B", "why_not_bucket_a": "needs NL/convention pattern recognition no regex captures", 
         "skill_title": "Y", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g"},
    ]
    res = run(tmp_path, rec)
    routing_used = res["summary"].get("routing_used", {})
    used_B = set(routing_used.get("bucket_B", []))
    assert {"skills/sta-review/SKILL.md", "skills/drc-fix/SKILL.md"} <= used_B, \
        f"summary must list every touched skill file; got {used_B}"


# ── v0.1.39 audit Finding 1 tests — honesty enforcement ──────────────────────
import importlib.util
_emit_spec = importlib.util.spec_from_file_location("enhancement_emit", str(SCRIPT))
_emit_mod = importlib.util.module_from_spec(_emit_spec)
_emit_spec.loader.exec_module(_emit_mod)


def test_emit_skill_section_refuses_missing_skill_title():
    """Audit Finding 1: caller MUST supply a generic skill_title — never default
    to a benchmark design slug (the honesty-rule violation that polluted
    ic-expert-agent.md through v0.1.38)."""
    rec = {"design": "Prob089_ece241_2014_q5a",
           "pattern": "p", "when": "w", "what": "x", "example": "e",
           "generality": "g"}
    with pytest.raises(ValueError, match="skill_title"):
        _emit_mod.emit_skill_section(rec)


def test_emit_backlog_refuses_missing_backlog_slug():
    """Audit Finding 1: backlog filenames are permanent record; never default
    to a Prob ID slug."""
    rec = {"design": "Prob089", "title": "x", "pattern": "y",
           "suggested_fix": "z"}
    with pytest.raises(ValueError, match="backlog_slug"):
        _emit_mod.emit_backlog(rec, "2026-05-28")


# ── `pattern` is required AT EMIT, not only downstream ───────────────────────
#
# Two backlog-landing PRs an hour apart shipped a broken `pattern` on a
# required field — one byte-identical text copied off an unrelated defect, one
# empty. One cause: `backlog_slug` above RAISES when absent, while `pattern`
# was read as `rec.get("pattern", "")` and `_validate_general_text` returns
# early on a falsy value. An omitted pattern emitted well-formed YAML with an
# empty block and no error, while `backlog_sanitize_check.REQUIRED_FIELDS`
# demands the field of that very file. Required downstream, undefined upstream,
# unenforced here — so both ways of resolving it were available.

_PATTERNLESS = {"title": "A gate accepts what it should refuse",
                "suggested_fix": "Make the gate refuse.",
                "backlog_slug": "generic-issue-category"}

_REAL_PATTERN = ("A required field that is defaulted at its write site but "
                 "demanded by a downstream gate: the write succeeds, the "
                 "record looks complete, and the refusal lands on whoever "
                 "reads it next.")


def test_emit_backlog_refuses_missing_pattern():
    """Behavioural: emit must REFUSE, not write a plausible empty block."""
    with pytest.raises(ValueError, match="pattern"):
        _emit_mod.emit_backlog(dict(_PATTERNLESS), "2026-05-28")


@pytest.mark.parametrize("blank", ["", "   ", "\n", "  \n \t "])
def test_emit_backlog_refuses_blank_pattern(blank):
    """A whitespace-only pattern emits the identical empty YAML block an
    omitted one did, so it is the same defect and is refused the same way."""
    with pytest.raises(ValueError, match="pattern"):
        _emit_mod.emit_backlog(dict(_PATTERNLESS, pattern=blank), "2026-05-28")


def test_emit_backlog_refusal_defines_what_a_pattern_is():
    """A refusal that only says "required" is what produced the two defects:
    an author who meets an undefined required field resolves it by imitation
    or by leaving it blank. The message must state what the field IS."""
    with pytest.raises(ValueError) as ei:
        _emit_mod.emit_backlog(dict(_PATTERNLESS), "2026-05-28")
    msg = str(ei.value).lower()
    assert "class of defect" in msg, msg
    assert "different instance" in msg, msg
    assert "not a restatement of the title" in msg, msg
    assert "do not copy one from another record" in msg, msg


def test_emit_backlog_still_emits_when_a_pattern_is_present():
    """No-leak, in-suite: a refusal that breaks valid input is worse than the
    defect it prevents."""
    fname, body = _emit_mod.emit_backlog(
        dict(_PATTERNLESS, pattern=_REAL_PATTERN), "2026-05-28")
    assert fname == "ORGANIC-20260528-generic-issue-category.yaml"
    assert "pattern: |\n  A required field that is defaulted" in body


def test_emit_backlog_required_fields_refuse_symmetrically():
    """The mechanism itself: two required fields of one function, one
    behaviour. The control proves the record is otherwise emittable, so each
    refusal below is attributable to the field that was dropped."""
    good = dict(_PATTERNLESS, pattern=_REAL_PATTERN)
    _emit_mod.emit_backlog(dict(good), "2026-05-28")      # control: emits

    no_slug = dict(good)
    no_slug.pop("backlog_slug")
    with pytest.raises(ValueError, match="backlog_slug"):
        _emit_mod.emit_backlog(no_slug, "2026-05-28")

    no_pattern = dict(good)
    no_pattern.pop("pattern")
    with pytest.raises(ValueError, match="pattern"):
        _emit_mod.emit_backlog(no_pattern, "2026-05-28")


def test_module_schema_documents_pattern_where_backlogs_are_written():
    """The input schema listed `pattern` only under the Bucket-B (skill)
    fields. A Bucket-C author reading the backlog field block met a field
    that emit requires and the sanitize gate demands, and that the block they
    were reading did not name."""
    doc = _emit_mod.__doc__
    start = doc.index("# Bucket-C (backlog) fields:")
    end = doc.index("# Bucket-D fields:")
    assert '"pattern"' in doc[start:end], (
        "Bucket-C field block must list `pattern` — it is consumed there")


def test_both_authoring_skills_define_what_a_pattern_is():
    """Neither skill that tells an author to write a `pattern` defined one:
    one listed it as a bare name in an enumeration, the other showed a worked
    example — a shape to imitate, not a rule. Imitation is exactly what
    produced the copied text."""
    skills = SCRIPT.parent.parent / "skills"
    capture = (skills / "benchmark-enhancement-capture" / "SKILL.md").read_text()
    submit = (skills / "community-backlog-submit" / "SKILL.md").read_text()
    import re as _re
    for name, text in (("benchmark-enhancement-capture", capture),
                       ("community-backlog-submit", submit)):
        # Unwrap markdown blockquote continuations so a phrase that spans a
        # line break still matches: the assertion is about the sentence, not
        # about where the author happened to wrap it.
        low = _re.sub(r"\s+", " ", text.replace("\n>", " ")).lower()
        assert "what `pattern` must say" in low, (
            f"{name} must DEFINE the field, not only name or exemplify it")
        assert "recognise a **different** instance" in low, name
        assert "not a restatement of `title`" in low, name


def test_scrub_design_leak_removes_prob_ids():
    """Audit Finding 1: enumerated benchmark-identifier tokens are scrubbed
    from free-text fields no matter where they appear."""
    s = _emit_mod._scrub_design_leak(
        "RTLLM benchmarks use rst_n. See VerilogEval Prob089 for example.")
    assert "Prob089" not in s
    assert "RTLLM" not in s
    assert "VerilogEval" not in s
    assert "[identifiers anonymized" in s


def test_scrub_design_leak_removes_from_parentheticals():
    """Audit Finding 1: design leaf names like `radix2_div` aren't in any
    enumeration. v0.1.40 (re-audit NEW-4) narrowed the bracket-strip to
    require the bracket interior to look like an identifier list — so
    `(from <snake_case_id>)` is killed but legitimate technical brackets
    are preserved (verified in the next test)."""
    s = _emit_mod._scrub_design_leak("A divider design (from radix2_div): fix.")
    assert "radix2_div" not in s, f"radix2_div should be scrubbed, got: {s!r}"
    assert "(from radix2_div)" not in s
    assert "[identifiers anonymized" in s


def test_scrub_design_leak_preserves_legitimate_technical_brackets():
    """v0.1.40 (re-audit NEW-4 fix) — the v0.1.39 broad-strip damaged
    legitimate technical parentheticals like `(per IEEE 1364)` and
    `(e.g. mod-256)` that contain no design identifier. Confirm these are
    preserved AND no spurious anonymization marker is appended."""
    cases = [
        "A counter (e.g. mod-256) wraps at zero.",
        "Refer to (refs 1, 2) for the math.",
        "Pattern: timing-violation (per IEEE 1364).",
    ]
    for c in cases:
        s = _emit_mod._scrub_design_leak(c)
        assert s == c, f"legitimate bracket damaged: input={c!r} got={s!r}"
        assert "anonymized" not in s, f"spurious marker on clean text: {s!r}"


def test_emit_skill_section_refuses_leaky_title():
    """v0.1.42 (Round-4 audit fix) — combined structural rule on title.
    Refuses ALL of: snake_case, ProbNNN (case-insensitive), kebab-with-digit,
    camelCase/PascalCase, digit-embedded-in-lowercase."""
    leaky_titles = [
        "Moore latency in Prob089 sequence_detector",        # snake + Prob
        "Reset polarity (the radix2_div case)",              # snake
        "Width overflow in the freq_divbyeven design",       # snake
        "see asyn_fifo for example",                         # snake
        "Moore latency in Prob089",                          # Prob##
        # Round-4 NEW-2 bypasses now structurally caught:
        "Reset polarity (the radix2-div case)",              # kebab+digit
        "Width overflow in freqDivByEven design",            # camelCase
        "Issue in SequenceDetector module",                  # PascalCase
        "Issue in mux256to1 module",                         # digit-embedded
        "Issue in prob089 fsm",                              # lowercase prob
    ]
    for title in leaky_titles:
        rec = {"skill_title": title,
               "pattern": "p", "when": "w", "what": "x", "example": "e",
               "generality": "g"}
        with pytest.raises(ValueError, match="skill_title"):
            _emit_mod.emit_skill_section(rec)


def test_emit_skill_section_refuses_leaky_body_fields():
    """v0.1.42 (Round-4 NEW-4 fix — P0) — the structural rule applies to
    ALL 5 body fields (pattern, when, what, example, generality), not just
    title. A Round-4 reproducer (clean title + leaky pattern) would
    otherwise emit a fully-leaked artifact."""
    clean = {"skill_title": "Clean general pattern title",
             "pattern": "g", "when": "g", "what": "g", "example": "g",
             "generality": "g"}
    for field in ("pattern", "when", "what", "example", "generality"):
        rec = dict(clean)
        rec[field] = "A divider design (the radix2_div case): widening helps"
        with pytest.raises(ValueError, match=field):
            _emit_mod.emit_skill_section(rec)


def test_emit_skill_section_accepts_backticked_industry_identifiers():
    """v0.1.42 — the legitimate escape hatch: backtick-wrap a known
    industry identifier in markdown style and it passes through."""
    rec = {"skill_title": "active-low reset naming — accept `reset_n` and `rst_n` as equivalent",
           "pattern": "Wrap `always_ff` in backticks too.",
           "when": "Authoring any sequential design.",
           "what": "Use `posedge clk` form.",
           "example": "g",
           "generality": "g"}
    out = _emit_mod.emit_skill_section(rec)
    assert "`reset_n`" in out
    assert "`always_ff`" in out


def test_round_trip_existing_skill_titles():
    """v0.1.43 (Round-5 R5-5 tightening) — the structural rule must accept
    EVERY existing skill title already in ic-expert-agent.md. v0.1.42
    skipped titles containing ANY `→` character (R5-5 false-positive
    skip); v0.1.43 tightens to skip only the specific promotion markers
    (`~~Skill:` strikethrough OR `→ NOW A PROGRAM RULE`)."""
    import re as _re
    agent_md = Path(__file__).parent.parent.parent / "agents" / "ic-expert-agent.md"
    titles = []
    for line in agent_md.read_text().splitlines():
        m = _re.match(r"^### Skill: (.+)$", line)
        if not m:
            continue
        t = m.group(1).strip()
        # v0.1.43 R5-5: tighten skip to specific promotion markers ONLY.
        if t.startswith("~~"):
            continue
        if "→ NOW A PROGRAM" in t or "→ NOW A SCORER" in t:
            continue
        titles.append(t)
    assert len(titles) >= 20, f"sanity check: should find many titles, got {len(titles)}"
    refused = []
    for t in titles:
        try:
            _emit_mod._validate_general_text("skill_title", t)
        except ValueError as e:
            refused.append((t, str(e)[:200]))
    assert not refused, (
        f"structural rule refuses {len(refused)} existing in-tree skill "
        f"titles (NEW-1-style regression):\n" +
        "\n".join(f"  - {t!r}\n    → {w}" for t, w in refused))


def test_round_trip_existing_body_lines():
    """v0.1.43 (Round-5 R5-3 fix — P0) — extend the round-trip test to
    the 5 BODY fields of every in-tree skill section. The v0.1.42
    round-trip only validated titles; auditor found 18 in-tree body
    lines that the v0.1.42 rule wrongly refused. If body fields don't
    round-trip, the closed-loop amend path silently breaks on
    re-emission."""
    import re as _re
    agent_md = Path(__file__).parent.parent.parent / "agents" / "ic-expert-agent.md"
    md = agent_md.read_text()
    field_map = {
        "Pattern": "pattern",
        "When to apply": "when",
        "What to do": "what",
        "Worked pattern": "example",
        "Why this is GENERAL": "generality",
    }
    refused = []
    total = 0
    for label, field in field_map.items():
        # NON-GREEDY [^\n]*? so the colon match doesn't skip past Verilog
        # ternary colons inside backtick code spans.
        for m in _re.finditer(
                rf"\*\*{_re.escape(label)}\*\*[^\n]*?:\s*([^\n]*)", md):
            content = m.group(1).strip()
            if len(content) < 5:
                continue
            total += 1
            try:
                _emit_mod._validate_general_text(field, content)
            except ValueError as e:
                refused.append((field, content[:80], str(e)[:200]))
    assert total >= 50, f"sanity check: should find many body lines, got {total}"
    assert not refused, (
        f"v0.1.43 structural rule refuses {len(refused)} of {total} "
        f"existing in-tree body lines (Round-5 R5-3 regression):\n" +
        "\n".join(f"  - [{f}] {c!r}\n    → {w}" for f, c, w in refused[:10]))


def test_backtick_content_validates_no_silent_passthrough():
    """v0.1.43 (Round-5 R5-1 fix — P0) — the v0.1.42 backtick exemption
    was unconditional. v0.1.43 validates contents:
      - Single-identifier backticks (e.g. `radix2_div`) — REFUSE
      - Code-snippet backticks (multi-token with operators) — only Prob##/
        homoglyph/enumerated-family checks apply."""
    # Identifier-form refuses
    leaky_identifier_cases = [
        "Use `radix2_div` for example",
        "See `mux256to1` design",
        "Try `Prob089`",
        "See `prob089` (lowercase)",
    ]
    for c in leaky_identifier_cases:
        with pytest.raises(ValueError):
            _emit_mod._validate_general_text("pattern", c)
    # Code-snippet form (with spaces/operators) passes if no Prob/homoglyph
    code_snippet_cases = [
        "Use `assign MATCH = (state == DONE) && IN;`",
        "See `initial clk=X; always #(PERIOD/2) clk = ~clk;`",
        "Try `module #(.DATA_WIDTH(N)) u_dut (...)` instantiation",
    ]
    for c in code_snippet_cases:
        _emit_mod._validate_general_text("pattern", c)  # should not raise


def test_unicode_homoglyph_refused():
    """v0.1.43 (Round-5 R5-2 fix — P0) — fullwidth underscore, Cyrillic
    homoglyphs, ProbＮＮＮ in fullwidth digits all bypass the v0.1.42
    ASCII-anchored regex. v0.1.43 NFKC-normalizes + refuses mixed-script
    tokens."""
    attacks = [
        ("pattern", "radix2＿div"),       # fullwidth U+FF3F underscore
        ("pattern", "rаdix2_div"),       # Cyrillic а
        ("pattern", "рrоb089 issue"),    # Cyrillic homoglyphs
        ("pattern", "Prob０８９"),          # fullwidth digits ProbNNN
    ]
    for field, val in attacks:
        with pytest.raises(ValueError):
            _emit_mod._validate_general_text(field, val)


def test_industry_units_and_timing_accepted():
    """v0.1.43 (Round-5 R5-6/R5-7 fix) — common RF/analog units (`dBm`,
    `mAh`, `MHz`) and STA timing names (`t_setup`, `t_hold`) must pass
    without backticks (they're universal industry vocabulary)."""
    accepted = [
        "Signal is -3 dBm at the antenna",
        "Capacitance 1pF; clock 100MHz",
        "Check `t_setup` and `t_hold` violations",
        "FIFO `data_width` parameter",
        "Standard `next_state` FSM idiom",
    ]
    for c in accepted:
        _emit_mod._validate_general_text("pattern", c)  # should not raise


def test_emit_backlog_refuses_leaky_slug():
    """v0.1.41 (re-re-audit Issue 3 — structural allowlist).
    Slug allowlist = kebab-case only ([a-z0-9-]+); any of:
    - prob<digits> token  → Prob ID leak
    - underscore          → snake_case identifier leak
    - uppercase           → not a slug
    is refused structurally."""
    leaky_slugs = [
        "prob042-radix2-div-remainder",      # auditor's Prob## case
        "freq_div-issue",                     # auditor bypass 4 (underscore)
        "RTLLM-asyn-fifo-bug",                # uppercase + (after lower) — both fail
        "Prob089-issue",                      # uppercase + Prob##
    ]
    for slug in leaky_slugs:
        rec = {"title": "t", "pattern": "p", "suggested_fix": "f",
               "backlog_slug": slug}
        with pytest.raises(ValueError, match="backlog_slug"):
            _emit_mod.emit_backlog(rec, "2026-05-28")


def test_emit_backlog_accepts_kebab_with_digits():
    """The slug allowlist must still accept legitimate kebab-case with
    digits (e.g. 'a4-converter-template') — these are real backlog forms
    used by existing test fixtures."""
    legitimate_slugs = [
        "a4-converter-template",
        "rtl-hygiene-internal-reg-init",
        "smoke-c",
        "v2-spec-conformance-bug",
    ]
    for slug in legitimate_slugs:
        rec = {"title": "t", "pattern": "p", "suggested_fix": "f",
               "backlog_slug": slug}
        fname, body = _emit_mod.emit_backlog(rec, "2026-05-28")
        assert slug in fname, f"slug {slug!r} should land in filename"


def test_emit_skill_section_accepts_unicode_title():
    """Auditor pre-flight: ΔΣ topology is a legitimate analog skill title.
    The structural allowlist must allow Unicode letters (no underscore is
    the rule, not 'must be ASCII')."""
    rec = {"skill_title": "ΔΣ modulator topology — 2nd-order SC CIFB",
           "pattern": "p", "when": "w", "what": "x", "example": "e",
           "generality": "g"}
    out = _emit_mod.emit_skill_section(rec)
    assert "ΔΣ" in out


def test_emit_skill_section_accepts_clean_title():
    """A skill_title that's already general should pass through unchanged."""
    rec = {"skill_title": "Hidden-TB parameter override forces parameter declarations",
           "pattern": "p", "when": "w", "what": "x", "example": "e",
           "generality": "g"}
    out = _emit_mod.emit_skill_section(rec)
    assert "Hidden-TB parameter override" in out
    # No spurious anonymization marker on a clean title (header line only)
    header = out.split("**Pattern**:")[0]
    assert "anonymized" not in header


def test_scrub_design_leak_idempotent_on_clean_text():
    """A skill section that's already general should pass through unchanged
    (no spurious anonymization marker)."""
    clean = ("Pattern: a divider-class design that hardcoded width parameters. "
             "When to apply: any module the description names a width parameter.")
    s = _emit_mod._scrub_design_leak(clean)
    assert s == clean, f"clean text should be unchanged; got: {s}"
    assert "anonymized" not in s


# ---------------------------------------------------------------------------
# v0.2.15 — PROGRAM-FIRST gate (user directive: capture must enforce
# program-first). Bucket B/C downgrades require a non-empty why_not_bucket_a.
# ---------------------------------------------------------------------------
def test_program_first_bucket_a_and_d_need_no_justification():
    recs = [{"bucket": "A", "rule_name": "crc_width"},
            {"bucket": "D", "why_discard": "overfit to one TB"}]
    assert _emit_mod.check_program_first(recs) == []


def test_program_first_refuses_bucket_b_without_justification():
    off = _emit_mod.check_program_first([{"bucket": "B", "skill_title": "foo"}])
    assert len(off) == 1
    assert "why_not_bucket_a" in off[0]
    assert "foo" in off[0]


def test_program_first_refuses_bucket_c_without_justification():
    off = _emit_mod.check_program_first(
        [{"bucket": "C", "title": "ship rtl_gen", "why_not_bucket_a": "no"}])
    assert len(off) == 1


def test_program_first_accepts_justified_downgrade():
    recs = [{"bucket": "B", "skill_title": "handshake",
             "why_not_bucket_a": "requires NL convention recognition no regex captures"},
            {"bucket": "C", "title": "big",
             "why_not_bucket_a": "needs a new template library + corpus fixtures"}]
    assert _emit_mod.check_program_first(recs) == []


def test_program_first_gate_exits_nonzero(tmp_path):
    import subprocess
    rec = tmp_path / "r.json"
    rec.write_text(json.dumps([{"bucket": "B", "skill_title": "x"}]))
    prog = SCRIPT
    r = subprocess.run(
        [sys.executable, str(prog), "--records", str(rec),
         "--out-dir", str(tmp_path / "out")],
        capture_output=True, text=True)
    assert r.returncode == 1
    assert "PROGRAM-FIRST GATE FAILED" in r.stderr


def test_program_first_gate_bypass_flag(tmp_path):
    import subprocess
    rec = tmp_path / "r.json"
    rec.write_text(json.dumps([{"bucket": "B", "skill_title": "x", "step": "",
                                "pattern": "p", "when": "w", "what": "wh",
                                "example": "e", "generality": "g"}]))
    prog = SCRIPT
    r = subprocess.run(
        [sys.executable, str(prog), "--records", str(rec),
         "--out-dir", str(tmp_path / "out"), "--allow-unjustified-downgrade"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------
# #197 finding 1 — a Bucket-A record whose step has no `bucket_A_program`
# (either a LISTED step with an explicit null program layer, or an UNLISTED
# step that falls through to default_routing's null) must be reported as
# UNROUTED, never crash the batch with AttributeError('NoneType' … 'replace')
# and leave a partially-written output directory.
# ---------------------------------------------------------------------------
def _run_capture(tmp_path, records):
    rec_file = tmp_path / "recoveries.json"
    rec_file.write_text(json.dumps(records))
    out_dir = tmp_path / "candidates"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--records", str(rec_file),
         "--out-dir", str(out_dir)],
        capture_output=True, text=True, timeout=30)
    spath = out_dir / "summary.json"
    summary = json.loads(spath.read_text()) if spath.is_file() else None
    return r, summary, out_dir


def test_bucket_A_null_target_step_does_not_abort_batch(tmp_path):
    """#197 finding 1 — a batch mixing (a) a LISTED step with an explicit null
    program layer (analog.sizing_loop) and (b) an UNLISTED step (falls to
    default_routing null) must NOT abort. The well-routed Bucket-A record and a
    DIFFERENT-bucket record both still emit, and the two null-target records are
    reported as unrouted in summary.json + on stderr (never silently dropped)."""
    recs = [
        # (a) LISTED step whose entry declares an explicit null bucket_A_program
        {"step": "analog.sizing_loop", "design": "d1", "bucket": "A",
         "rule_name": "sizing-loop-convergence", "docstring": "doc",
         "expected_signal": "WARN", "fix_action": "x"},
        # (b) UNLISTED step → default_routing (bucket_A_program is null)
        {"step": "totally.unlisted.step", "design": "d2", "bucket": "A",
         "rule_name": "unlisted-rule", "docstring": "doc",
         "expected_signal": "WARN", "fix_action": "x"},
        # (c) a well-routed Bucket-A record — must still emit
        {"step": "phase2.rtl_gen", "design": "d3", "bucket": "A",
         "rule_name": "restoring-div-remainder-width", "docstring": "doc",
         "expected_signal": "WARN", "fix_action": "x"},
        # (d) a Bucket-B record — a DIFFERENT bucket must still emit too
        {"step": "phase3.drc", "design": "d4", "bucket": "B",
         "why_not_bucket_a": "needs NL/convention pattern recognition no regex captures",
         "skill_title": "DRC pattern", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g"},
    ]
    r, summary, _ = _run_capture(tmp_path, recs)
    assert r.returncode == 0, \
        f"batch must NOT abort on a null program target; rc={r.returncode}\n{r.stderr}"
    assert summary is not None, "summary.json must be written even with unrouted records"
    # (c) the well-routed record still emits
    assert any("rtl_hygiene_lint" in f for f in summary.get("bucket_A_files", [])), \
        f"the well-routed Bucket-A record must still emit; got {summary.get('bucket_A_files')}"
    # (d) the other bucket still emits
    assert any(e["target"] == "skills/drc-fix/SKILL.md"
               for e in summary.get("bucket_B_files", [])), \
        "a Bucket-B record must still emit while Bucket A has unrouted records"
    # the two null-target records are reported (not silently dropped)
    unrouted_steps = {u["step"] for u in summary.get("bucket_A_unrouted", [])}
    assert unrouted_steps == {"analog.sizing_loop", "totally.unlisted.step"}, \
        f"both null-target steps must be reported as unrouted; got {unrouted_steps}"
    # and surfaced on stderr for the human running the capture
    assert "unrouted" in r.stderr.lower() and "analog.sizing_loop" in r.stderr


def test_bucket_A_all_null_targets_completes_cleanly(tmp_path):
    """#197 finding 1 — even when EVERY Bucket-A record is null-target, the run
    completes (rc 0), writes summary.json, and reports them all as unrouted
    rather than raising / leaving a partial output dir."""
    recs = [
        {"step": "analog.sizing_loop", "design": "d1", "bucket": "A",
         "rule_name": "r1", "docstring": "doc",
         "expected_signal": "WARN", "fix_action": "x"},
        {"step": "another.unlisted", "design": "d2", "bucket": "A",
         "rule_name": "r2", "docstring": "doc",
         "expected_signal": "WARN", "fix_action": "x"},
    ]
    r, summary, _ = _run_capture(tmp_path, recs)
    assert r.returncode == 0, r.stderr
    assert summary is not None
    assert len(summary.get("bucket_A_unrouted", [])) == 2
    # no bucket_A output file was fabricated for a null target
    assert not summary.get("bucket_A_files"), \
        f"no bucket_A file should be written for null targets; got {summary.get('bucket_A_files')}"


def test_phase2_lec_routes_to_lec_program(tmp_path):
    """#197 finding 2 — a captured LEC / equivalence recovery now routes to the
    LEC checker program instead of falling through to the null default (which
    previously crashed the whole batch)."""
    recs = [{
        "step": "phase2.lec", "design": "d1", "bucket": "A",
        "rule_name": "lec-hierarchy-both-sides-staged", "docstring": "doc",
        "expected_signal": "ERROR", "fix_action": "flatten both sides"}]
    r, summary, _ = _run_capture(tmp_path, recs)
    assert r.returncode == 0, r.stderr
    a_files = summary.get("bucket_A_files", [])
    assert any("lec_equivalence_check" in f for f in a_files), \
        f"phase2.lec Bucket A must route to lec_equivalence_check; got {a_files}"
    assert not summary.get("bucket_A_unrouted"), \
        "phase2.lec must NOT be unrouted now that it has a routing entry"


# ═══════════════════════════════════════════════════════════════════════════
# #795 — the provenance fields this emitter stamps must be MEASUREMENTS.
#
# `plugin_version` was the literal "0.1.33" and `submitted_at`'s time-of-day
# was the literal midnight. Both are formatted like data, so a wrong value is
# invisible: no reader, and no gate, can tell a defaulted record from a
# measured one. `backlog_sanitize_check.py` requires `plugin_version` but only
# checks it is non-empty, and `tools/ci/staged_version_claim_check.py` exempts
# `community/backlogs/` from version-claim checking entirely.
#
# The tests below therefore REFUSE to be satisfied by a constant. Each one
# changes the thing the emitter is supposed to be reading and asserts the
# emitted value FOLLOWED it. Swapping one hardcoded constant for another
# cannot pass any of them.
# ═══════════════════════════════════════════════════════════════════════════
import datetime as _dt
import importlib as _importlib
import re as _re
import time as _time

_PROGRAMS_DIR = Path(__file__).resolve().parent.parent
if str(_PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS_DIR))
EMIT = _importlib.import_module("enhancement_emit")

# The single source of truth, read here INDEPENDENTLY of the program under
# test — the test must not learn the expected version from the code that is
# supposed to be reading it.
_PLUGIN_JSON = _PROGRAMS_DIR.parent / ".claude-plugin" / "plugin.json"


def _shipped_version() -> str:
    return json.loads(_PLUGIN_JSON.read_text())["version"]


def _bucket_c_record(**over) -> dict:
    rec = {
        "step": "phase2.rtl_gen", "design": "d1", "bucket": "C",
        "why_not_bucket_a": "needs judgement no predicate can make",
        "title": "a captured gap", "pattern": "a general pattern",
        "suggested_fix": "a general fix", "backlog_slug": "provenance-probe",
        "backlog_type": "bug", "severity": "P2",
        "component": "program:enhancement_emit",
        "session_context": "captured from a convergence run",
    }
    rec.update(over)
    return rec


def _yaml_field(body: str, key: str) -> str:
    for line in body.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip().strip('"')
    raise AssertionError(f"field {key!r} absent from emitted backlog:\n{body}")


def _fake_plugin_root(tmp_path: Path, version) -> Path:
    """A minimal plugin tree whose manifest declares `version`."""
    root = tmp_path / "fake_plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    doc = {"name": "vibe-ic"}
    if version is not None:
        doc["version"] = version
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps(doc))
    return root


def test_emitted_plugin_version_tracks_the_manifest_it_reads(tmp_path,
                                                             monkeypatch):
    """A record with no `plugin_version` must carry the version READ from
    `.claude-plugin/plugin.json`. Proven by pointing the emitter at a manifest
    declaring a version no constant in the tree could be, and requiring the
    emitted value to follow it — twice, to two different values."""
    for declared in ("7.0.1", "42.13.9"):
        monkeypatch.setattr(EMIT, "PLUGIN_ROOT",
                            _fake_plugin_root(tmp_path / declared, declared))
        _fname, body = EMIT.emit_backlog(_bucket_c_record(), "2026-08-04")
        assert _yaml_field(body, "plugin_version") == declared, (
            f"emitted plugin_version must be the manifest's {declared!r}; "
            f"got:\n{body}")


def test_emitted_plugin_version_is_the_real_shipped_version():
    """Against the REAL plugin tree (no monkeypatching), an undated capture
    carries the shipped version — not any of the constants this emitter or its
    siblings have historically stamped."""
    _fname, body = EMIT.emit_backlog(_bucket_c_record(), "2026-08-04")
    got = _yaml_field(body, "plugin_version")
    assert got == _shipped_version(), (
        f"emitted plugin_version {got!r} != shipped {_shipped_version()!r}")
    # Negative control: the historical constants, written out as literals so
    # that deleting one cannot silently delete its own coverage.
    for stale in ("0.1.33", "0.1.34", "0.1.50", "0.1.51", "0.1.2", "0.101"):
        assert got != stale, (
            f"emitted plugin_version is the hardcoded constant {stale!r} — a "
            f"constant is not a measurement")


def test_author_supplied_plugin_version_is_never_overridden(tmp_path,
                                                            monkeypatch):
    """The fix must not overwrite author intent: a record that STATES its
    version emits exactly that, even though the running plugin is a different
    version entirely."""
    monkeypatch.setattr(EMIT, "PLUGIN_ROOT",
                        _fake_plugin_root(tmp_path, "42.13.9"))
    _fname, body = EMIT.emit_backlog(
        _bucket_c_record(plugin_version="1.2.96"), "2026-08-04")
    assert _yaml_field(body, "plugin_version") == "1.2.96"


def test_unreadable_manifest_emits_visibly_non_data(tmp_path, monkeypatch):
    """When the version cannot be READ, the emitted value must be visibly
    non-data — it fails the first time anyone sorts by it. A plausible semver
    fallback would never fail, which is the whole defect."""
    for root in (tmp_path / "absent",                       # no manifest at all
                 _fake_plugin_root(tmp_path, None)):        # manifest, no field
        monkeypatch.setattr(EMIT, "PLUGIN_ROOT", root)
        got = EMIT.resolved_plugin_version()
        assert got == "unknown", f"expected a non-data marker; got {got!r}"
        assert not _re.match(r"^\d+\.\d+\.\d+$", got), (
            f"fallback {got!r} is semver-shaped — indistinguishable from a "
            f"measured version")
        _fname, body = EMIT.emit_backlog(_bucket_c_record(), "2026-08-04")
        assert _yaml_field(body, "plugin_version") == "unknown"


def test_submitted_at_is_a_measurement_not_a_constant_time():
    """`submitted_at` must be the real instant of submission. Negative control
    per the issue: two invocations made seconds apart must NOT emit the same
    value — a constant time-of-day emits the same string forever."""
    _f1, b1 = EMIT.emit_backlog(_bucket_c_record(), "2026-08-04")
    _time.sleep(1.05)
    _f2, b2 = EMIT.emit_backlog(_bucket_c_record(), "2026-08-04")
    t1, t2 = _yaml_field(b1, "submitted_at"), _yaml_field(b2, "submitted_at")
    assert t1 != t2, (
        f"two submissions a second apart emitted the same instant {t1!r} — "
        f"the field is a constant, not a measurement")
    parsed = _dt.datetime.fromisoformat(t2)
    assert parsed.tzinfo is not None, f"{t2!r} carries no UTC offset"
    delta = abs((_dt.datetime.now().astimezone() - parsed).total_seconds())
    assert delta < 120, (
        f"emitted submitted_at {t2!r} is {delta:.0f}s from now — not the "
        f"instant of submission")


def test_submitted_at_follows_the_instant_it_is_given():
    """Injecting the instant proves the field is rendered FROM it (and pins the
    exact midnight string the emitter used to hardcode)."""
    inst = _dt.datetime(2026, 8, 4, 7, 38, 43,
                        tzinfo=_dt.timezone(_dt.timedelta(hours=8)))
    _fname, body = EMIT.emit_backlog(_bucket_c_record(), "2026-08-04", inst)
    assert _yaml_field(body, "submitted_at") == "2026-08-04T07:38:43+08:00"
    assert "2026-08-04T00:00:00+08:00" not in body, \
        "the hardcoded midnight is back"


def test_rule_sketch_header_carries_the_version_it_was_emitted_at(tmp_path,
                                                                  monkeypatch):
    """The Bucket-A sketch header stamps a version too — the third constant in
    this file. It must track the manifest like the other two."""
    monkeypatch.setattr(EMIT, "PLUGIN_ROOT",
                        _fake_plugin_root(tmp_path, "42.13.9"))
    sketch = EMIT.emit_program_rule_sketch({
        "rule_name": "a-captured-rule", "pattern": "a general pattern",
        "docstring": "a general docstring", "fix_action": "a general fix",
        "expected_signal": "ERROR"})
    assert "v42.13.9" in sketch, f"sketch header ignores the manifest:\n{sketch}"
    assert "v0.1.34" not in sketch, "the hardcoded sketch version is back"


def test_end_to_end_emit_stamps_no_stale_constant(tmp_path):
    """Through the real CLI: the emitted backlog carries the shipped version and
    an id whose date is derived from the SAME instant as submitted_at."""
    res = run(tmp_path, [_bucket_c_record()])
    body = (Path(res["summary"]["bucket_C_dir"]) /
            res["summary"]["bucket_C_files"][0]).read_text()
    assert _yaml_field(body, "plugin_version") == _shipped_version()
    stamped = _dt.datetime.fromisoformat(_yaml_field(body, "submitted_at"))
    assert stamped.tzinfo is not None
    assert _yaml_field(body, "id").split("-")[1] == \
        stamped.date().isoformat().replace("-", "")
# ── #798 — the backtick leak guard must not refuse legitimate names ──────────
#
# What the guard is FOR: keeping BENCHMARK DESIGN identifiers out of captured
# plugin content. A true positive is a design leaf-name (`radix2_div`,
# `mux256to1`, `ece241_2014_q5a`), a Prob ID, a benchmark family name, or one
# of those with its separators stripped to evade the shape rules
# (`radix2divbyeven`).
#
# Two predicates in `_check_backtick_content` fired on things that are none of
# those. Both are pinned below in BOTH directions: the false positive must stop
# firing AND the structurally-adjacent true positive must still fire. The
# negative half is the load-bearing one — a false positive costs a re-run, a
# leaking exemption ships a defect as PASS.


def _backtick_verdict(tok: str):
    """None if the guard accepts `tok` backtick-wrapped, else the message."""
    try:
        _emit_mod._check_backtick_content("fix_action", f"see `{tok}`")
        return None
    except ValueError as e:
        return str(e)


def test_backtick_guard_accepts_every_plugin_program_filename():
    """#798 — the corpus sweep the issue asked for. The plugin's naming
    convention is `descriptive_name_check.py`, which is long BY DESIGN; the
    total-length cap refused 348 of 1105 (31.49%), so a capture record could
    not name the file it was about for a third of the plugin."""
    names = sorted(p.name for p in _PROGRAMS_DIR.glob("*.py"))
    assert len(names) > 900, \
        f"corpus sanity: expected the full programs/ dir, got {len(names)}"
    refused = [(n, _backtick_verdict(n)) for n in names if _backtick_verdict(n)]
    assert not refused, (
        f"{len(refused)}/{len(names)} of the plugin's own program filenames "
        f"are refused when backtick-wrapped:\n" +
        "\n".join(f"  - `{n}` -> {w[:130]}" for n, w in refused[:8]))


def test_backtick_guard_is_not_a_catch22_for_program_filenames():
    """#798 — the bare-text rule's own remedy IS the backtick form, so the two
    rules together must not make a name unwritable in every form. The bare form
    is (correctly) refused with an instruction to backtick it; the backticked
    form must then be accepted."""
    name = "declared_pdk_is_the_pdk_used_check.py"
    with pytest.raises(ValueError, match="wrap it in markdown backticks"):
        _emit_mod._validate_general_text("fix_action", f"Add the rule to {name}.")
    _emit_mod._validate_general_text("fix_action", f"Add the rule to `{name}`.")


def test_backtick_guard_still_refuses_separator_stripped_concatenation():
    """#798 NEGATIVE (load-bearing) — the narrowed rule measures the longest
    UNBROKEN alphanumeric run instead of the total token length. Each fixture
    below is derived mechanically from its accepted partner by deleting the
    separators and nothing else, so the two members differ in exactly the
    property that defines 'concatenated'. Accepted member must pass; derived
    member must STILL be refused, and refused BY THE CONCATENATION RULE."""
    import re as _re
    accepted = [
        "chip_clock_toggle_divider_when_master_already_target_check.py",
        "doc_consistency_no_unresolved_conflicts_check.py",
        "fixed_point_substractor_and_divider",
    ]
    # Digit-free by construction: the derived concatenation must be refused by
    # the CONCATENATION rule, so no fixture may also match the digits-in-the-
    # middle shape rule — otherwise the assertion below would pass for the
    # wrong reason.
    assert not any(ch.isdigit() for n in accepted for ch in n), \
        "fixtures must be digit-free so only the concatenation rule can fire"
    for name in accepted:
        assert len(name) > 30, f"fixture must exceed the old 30-char cap: {name}"
        assert _backtick_verdict(name) is None, (
            f"separator-bearing name must be accepted at any total length: "
            f"`{name}` -> {_backtick_verdict(name)}")
        concat = _re.sub(r"[^A-Za-z0-9]", "", name)
        assert len(concat) > 30, (
            f"the derived concatenation must still sit outside the 30-char "
            f"budget for this pair to prove anything: {concat!r}")
        w = _backtick_verdict(concat)
        assert w is not None, (
            f"separator-stripped concatenation must STILL be refused: "
            f"`{concat}` (derived from `{name}`)")
        assert "unbroken alphanumeric run" in w, (
            f"`{concat}` must be refused BY THE CONCATENATION RULE, not by "
            f"accident of another rule; got: {w[:200]}")
    # The invariant is not limited to the >30 class: a short benchmark
    # leaf-name must not become writable by deleting its separator either.
    # (`counter_12` was never caught; `counter12` was, and must stay so.)
    # NOTE: digit-free leaf-names (`freq_divbyeven` -> `freqdivbyeven`) are
    # accepted by BOTH origin/main and this branch — no backtick rule covers
    # that class. Pre-existing gap, recorded here so this list is not read as
    # a claim of complete coverage.
    for short in ("counter12", "adder16bit", "radix2div"):
        assert _backtick_verdict(short) is not None, \
            f"separator-stripped leaf-name `{short}` must still be refused"


def test_backtick_guard_accepts_industry_vocabulary_via_the_allowlist():
    """#798 — the digit-shape rule refused 11 of this plugin's own 86 shipped
    `*_protocol_synth.py` names (12.8%) plus ordinary encoding vocabulary.
    Those false positives are cleared through the ALLOWLIST, not by narrowing
    the rule: `ddr4` and `lemmings1` are the same shape, so any narrowing that
    admits one admits the other (see the floor test below)."""
    accepted = [
        # this plugin's own shipped protocol names
        "ddr4", "ddr5", "gddr6", "hbm3", "lpddr5", "usb4", "rs485", "psi5",
        "jesd204", "arinc429", "milstd1553",
        # ordinary encoding / bus / numeric-format vocabulary
        "crc32", "sha256", "base64", "utf8", "axi4", "usb3", "int8", "float32",
        # public PDKs — issue #798's second reported false positive
        "asap7", "nangate45", "freepdk45", "sg13g2", "sky130A", "gf180mcuD",
    ]
    refused = [(t, _backtick_verdict(t)) for t in accepted if _backtick_verdict(t)]
    assert not refused, (
        "industry vocabulary refused as a benchmark leaf-name:\n" +
        "\n".join(f"  - `{t}` -> {w[:130]}" for t, w in refused))


#: #798 — the count of `verilogeval_v2/problems.list` LEAF-names (the
#: `ProbNNN_` prefix stripped, i.e. the name a leaking author actually writes)
#: that the digit-shape rule refuses on origin/main. Narrowing that rule to
#: "require an alphabetic tail after the digits" was authored and reverted
#: here because it drops this to 38 — `lemmings1`, `kmap4`, `circuit10`,
#: `fsm3`, `vector5`, `popcount255`, `rule110`, `lfsr32`, `dff8`, `count10`,
#: `shift18` and 36 more. These floors exist so the next narrowing cannot be
#: silent. RAISING them is fine; lowering one is a coverage loss that must be
#: argued in the PR, not absorbed.
#:
#: SCOPE — both of these pin the DIGIT-SHAPE rule and NOTHING ELSE. All 85 and
#: all 91 are refused with "benchmark-leaf-name shape"; no VerilogEval leaf-name
#: has an unbroken alphanumeric run over 30 characters, so deleting the
#: run-length cap outright leaves both numbers untouched. Do not read a green
#: `_VE_LEAF_*` as evidence about the run-length cap — see
#: `_CVDP_LEAF_RUN_FLOOR` for the constant that covers that rule.
_VE_LEAF_FLOOR = 85
_VE_LEAF_CONCAT_FLOOR = 91

#: #798 — the CVDP DESIGN leaf-name floor, and the one number in this change
#: that went DOWN. Over the 229 unique CVDP design leaf-names (a cell id minus
#: its `cvdp_<track>_` prefix and `_NNNN` ordinal, harvested from tracked paths
#: AND file contents) origin/main catches 14 and this branch catches 8. The six
#: freed are all separator-bearing names longer than 30 characters, which the
#: old total-length cap refused as a side effect:
#:     arithmetic_progression_generator        (32)
#:     configurable_digital_low_pass_filter    (36)
#:     reed_solomon_encoder_and_decoder        (32)
#:     secure_read_write_register_bank         (31)
#:     sequencial_binary_to_one_hot_decoder    (36)
#:     write_through_data_direct_mapped_cache  (38)
#: This is DISCLOSED, not repaired. No length or shape discriminator exists —
#: `configurable_digital_low_pass_filter` is 36 chars and
#: `declared_pdk_is_the_pdk_used_check.py` is 37 — and restoring the cap
#: re-creates the 31.49% catch-22 that is the defect being fixed. The class is
#: unguarded by design at the identifier level; the CELL IDS carrying these
#: names remain fully caught by the family branch (126 of the 126 cell ids
#: `git ls-files` yields from tracked PATHS — see the harvest definition in
#: `enhancement_emit.py`; contents are excluded because this commit's own tests
#: add cell-id literals and a contents-inclusive count would measure itself).
#: The floor is here so the NEXT change cannot lower it without saying so.
#:
#: SCOPE — this constant pins the DIGIT-SHAPE rule's residue, NOT the
#: run-length cap that this commit authored. All 8 survivors are refused with
#: "benchmark-leaf-name shape"; replace `if len(longest) > 30:` with
#: `if False:` and this is still 8, because no raw CVDP leaf-name has an
#: unbroken run over 30 characters — the six the cap freed are 31-38 chars only
#: in TOTAL. A green `_CVDP_LEAF_FLOOR` is therefore no evidence at all about
#: the run-length cap; `_CVDP_LEAF_RUN_FLOOR` below is.
_CVDP_LEAF_FLOOR = 8

#: #798 — the floor that the RUN-LENGTH CAP itself owns, and the reason it is
#: measured on the separator-STRIPPED corpus: strip the separators and the six
#: freed names become unbroken runs again (`writethroughdatadirectmappedcache`
#: is 33 characters), which is exactly the concatenation the cap exists to
#: refuse. Counted by RULE ATTRIBUTION — only refusals whose message says
#: "unbroken alphanumeric run" count — so a broadening of the digit-shape rule
#: can never silently satisfy this floor on the run-length rule's behalf.
#: Deleting the cap takes it 3 -> 0.
_CVDP_LEAF_RUN_FLOOR = 3

#: #798 — the same separator-stripped corpus counted in aggregate: 14
#: digit-shape + the 3 above. Held at its origin/main value of 17 (there the 3
#: came from the total-length cap), which is what makes it the non-weakening
#: pin for concatenation. Deleting the run-length cap takes it 17 -> 14.
_CVDP_LEAF_CONCAT_FLOOR = 17


def _repo_root():
    """Walk up to the checkout that carries `benchmark-data/`. Resolving by a
    fixed number of `.parent`s silently skipped this whole corpus test when it
    was off by one — and a skipped floor test looks exactly like a passing
    one."""
    for d in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
        if (d / "benchmark-data" / "evaluation").is_dir():
            return d
    return None


# ── WHERE THE BENCHMARK CORPORA LIVE NOW ────────────────────────────────────
# The datasets these negative controls are measured against — the VerilogEval-v2
# problem list, the RTLLM `pass_at_1.json` runs, and the tracked paths that
# carry CVDP cell ids — moved out of this repository with the rest of the
# published benchmark data (vibeic/benchmark-data). Nothing about the FLOORS
# changed: they are still counted over the same names, so they are resolved
# here through `_published_corpus` instead of through this checkout alone.
#
# MEASURED on this branch, which is why the harvest is a UNION of the two trees
# rather than a swap of one for the other — the ids live on BOTH sides, in
# plugin source comments and fixtures as well as in benchmark run dirs:
#
#     tracked-PATH cvdp cell ids   vibe-ic  96   benchmark-data  63   union 126
#     cvdp design leaf-names       vibe-ic 226   benchmark-data 182   union 229
#
# 126 and 229 are exactly `_CVDP_CELL_ID_PATH_CORPUS_FLOOR` and the 229 the
# docstrings above quote, so the union restores the corpus the floors were
# measured on rather than re-cutting it to fit.
def _corpus_tree():
    """The published benchmark-data tree, or None when there is none here."""
    return corpus_root()


def _harvest_trees():
    """Every distinct git tree to harvest cvdp ids from: this checkout, plus
    the benchmark-data corpus when it is a SEPARATE checkout (in a tree that
    still carries the corpus in-repo, `git ls-files` already covers it and
    listing it twice would only walk the same files again)."""
    trees = []
    repo = _repo_root()
    if repo is not None:
        trees.append(repo)
    corpus = _corpus_tree()
    if corpus is not None:
        inside = repo is not None and (
            corpus == repo or repo in corpus.resolve().parents)
        if not inside:
            trees.append(corpus)
    return trees


def _verilogeval_leaf_names():
    import re as _re2
    corpus = _corpus_tree()
    src = corpus / "evaluation/verilogeval_v2/problems.list"
    assert src.is_file(), (
        f"the published benchmark corpus is present at {corpus} but the "
        f"corpus this floor is measured against is missing: {src}")
    probs = [l.strip() for l in src.read_text().splitlines() if l.strip()]
    return probs, [_re2.sub(r"^Prob\d+_", "", p) for p in probs]


def _cvdp_design_leaf_names():
    """Cell id minus its `cvdp_<track>_` prefix and `_NNNN` ordinal — the
    DESIGN name, which is what a leaking author writes when the record is
    about the design rather than the dataset row."""
    import re as _re4, subprocess as _sp
    trees = _harvest_trees()
    if not trees:
        pytest.skip("benchmark-data/ not in this checkout (plugin-only install)")
    # Harvest over every GIT-TRACKED file, not just benchmark-data/: these ids
    # also appear in plugin source comments and fixtures, and scoping the sweep
    # narrower than the reported measurement would pin a floor against a
    # different corpus than the one the change was measured on (182 vs 229).
    cell = _re4.compile(r"cvdp_(?:copilot|agentic)_([A-Za-z0-9_]*?)_\d{4}")
    leaves = set()
    for root in trees:
        try:
            # 30s, not 120: `ci_harness_timeout_ceiling_check` caps an inner
            # subprocess bound at harness//3 = 60s, because a longer one
            # outlives the 180s pytest harness and kills the SESSION instead of
            # the test. Measured here: 0.01s for 21216 tracked files.
            tracked = _sp.run(["git", "-C", str(root), "ls-files"],
                              capture_output=True, text=True,
                              timeout=30).stdout.split()
        except (OSError, _sp.SubprocessError):  # pragma: no cover - env-dependent
            pytest.skip("git not available to enumerate the tracked corpus")
        if not tracked:
            pytest.skip("not a git checkout — cannot enumerate the tracked corpus")
        for rel in tracked:
            leaves.update(cell.findall(rel))
            f = root / rel
            try:
                if f.is_file() and f.stat().st_size <= 4_000_000:
                    leaves.update(cell.findall(f.read_text(errors="ignore")))
            except OSError:
                pass
    return sorted(x for x in leaves if x)


@needs_corpus
def test_backtick_guard_catches_cvdp_design_leaf_names_at_or_above_floor():
    """#798 NEGATIVE (load-bearing) — the corpus this change actually LOST
    coverage on, pinned so the loss is a number and not a surprise.

    The VerilogEval and RTLLM leaf-name floors both held at their origin/main
    values, which made it easy to read the change as costing no design-leaf
    coverage anywhere. It did: six CVDP design leaf-names were refused only
    because they exceeded the 30-character cap, and the run-based cap does not
    refuse them. See `_CVDP_LEAF_FLOOR` for the six and for why restoring the
    cap is not the answer.

    READ THE SCOPE NOTES ON THE CONSTANTS. `_CVDP_LEAF_FLOOR` is blind to the
    run-length cap this commit authored — delete that cap and it stays at 8.
    The cap's own floor is `_CVDP_LEAF_RUN_FLOOR`, asserted below on the
    separator-stripped corpus and attributed by refusal message."""
    leaves = _cvdp_design_leaf_names()
    assert len(leaves) > 150, f"corpus sanity: got {len(leaves)} CVDP leaf-names"
    caught = [x for x in leaves if _backtick_verdict(x)]
    assert len(caught) >= _CVDP_LEAF_FLOOR, (
        f"the guard now catches only {len(caught)}/{len(leaves)} CVDP design "
        f"leaf-names, below the {_CVDP_LEAF_FLOOR} floor. Newly freed: "
        f"{sorted(set(leaves) - set(caught))[:20]}")
    concat = sorted({x.replace("_", "") for x in leaves})
    caught_c = [c for c in concat if _backtick_verdict(c)]
    assert len(caught_c) >= _CVDP_LEAF_CONCAT_FLOOR, (
        f"separator-stripped CVDP leaf-names caught {len(caught_c)}/"
        f"{len(concat)}, below the {_CVDP_LEAF_CONCAT_FLOOR} floor")
    # The floor the RUN-LENGTH CAP owns. Attributed by refusal message so that
    # a broadening of the digit-shape rule cannot satisfy it by proxy: the
    # aggregate above would survive that substitution, this will not.
    by_run = [c for c in concat
              if "unbroken alphanumeric run" in (_backtick_verdict(c) or "")]
    assert len(by_run) >= _CVDP_LEAF_RUN_FLOOR, (
        f"the run-length cap refuses only {len(by_run)} separator-stripped "
        f"CVDP leaf-names, below the {_CVDP_LEAF_RUN_FLOOR} floor — the cap "
        f"has been weakened or deleted. Caught by it: {sorted(by_run)}")
    # The CELL IDs carrying these names must stay fully caught — that is what
    # keeps the identifier-level loss bounded rather than open-ended.
    for cell_id in ("cvdp_copilot_configurable_digital_low_pass_filter_0001",
                    "cvdp_copilot_write_through_data_direct_mapped_cache_0001"):
        w = _backtick_verdict(cell_id)
        assert w is not None and "benchmark family name" in w, \
            f"cell id `{cell_id}` must still be refused as a family leak; got {w}"


@needs_corpus
def test_backtick_guard_catches_verilogeval_leaf_names_at_or_above_floor():
    """#798 NEGATIVE (load-bearing) — the corpus that can actually MOVE when
    the digit rule changes.

    The obvious corpus, the full `ProbNNN_…` strings, is useless here: the
    `Prob\\d+` branch catches those unconditionally, so its 156/156 cannot
    budge no matter what the digit rule does. A corpus that a different rule
    catches unconditionally cannot measure the rule under test. The leaf-name
    is what a leaking author writes, and it is the shape this rule owns."""
    probs, leaves = _verilogeval_leaf_names()
    assert len(leaves) > 100, f"corpus sanity: got {len(leaves)} problems"
    # Control: the full ProbNNN_ strings are caught by a DIFFERENT branch, so
    # this number is insensitive to the rule under test. Asserted so the
    # distinction is visible rather than implied.
    assert all(_backtick_verdict(p) for p in probs), \
        "every full ProbNNN_ id must be caught (by the Prob branch)"

    caught = [l for l in leaves if _backtick_verdict(l)]
    assert len(caught) >= _VE_LEAF_FLOOR, (
        f"the digit-shape rule now catches only {len(caught)}/{len(leaves)} "
        f"benchmark leaf-names, below the {_VE_LEAF_FLOOR} floor. Lost: "
        f"{sorted(set(leaves) - set(caught))[:20]}")
    concat = [l.replace("_", "").replace("-", "") for l in leaves]
    caught_c = [c for c in concat if _backtick_verdict(c)]
    assert len(caught_c) >= _VE_LEAF_CONCAT_FLOOR, (
        f"separator-stripped leaf-names caught {len(caught_c)}/{len(concat)}, "
        f"below the {_VE_LEAF_CONCAT_FLOOR} floor")


def test_backtick_guard_still_refuses_lowercase_then_digits_leaf_names():
    """#798 NEGATIVE (load-bearing) — the shape this rule owns, pinned as
    literals drawn from the classes a narrowing would silently drop: names
    that TERMINATE at their digits (the 47 the reverted narrowing lost) and
    names that continue past them."""
    terminal_digit_leaves = (      # the class the reverted narrowing dropped
        "lemmings1", "kmap4", "circuit10", "fsm3", "vector5", "popcount255",
        "rule110", "lfsr32", "dff8", "count10", "shift18", "truthtable1",
        "edgedetect2", "gatesv100",
    )
    continues_past_digits = (      # the class it kept
        "radix2_div", "mux256to1", "radix2divbyeven",
        "parallel2serial", "serial2parallel", "ece241_2014_q5a",
        "ddr4phy", "usb4slave", "asap7cell", "crc32gen",
    )
    for leaf in terminal_digit_leaves + continues_past_digits:
        w = _backtick_verdict(leaf)
        assert w is not None and "benchmark-leaf-name shape" in w, \
            f"benchmark design leaf-name `{leaf}` must be refused; got {w}"
    # ...and the allowlisted vocabulary of the SAME shape still passes, so the
    # discriminator really is the finite list and not an accident.
    for ok in ("ddr4", "usb4", "asap7", "crc32"):
        assert _backtick_verdict(ok) is None, \
            f"allowlisted `{ok}` must be accepted; got {_backtick_verdict(ok)}"


def test_backtick_guard_still_refuses_absolute_taboos():
    """#798 NEGATIVE — relaxing the two identifier-shape rules must not touch
    the taboos that apply to identifier AND code-snippet form alike."""
    for tok, marker in (
            ("Prob089_ece241_2014_q5a", "benchmark family name"),
            ("prob068", "Prob ID"),
            ("RTLLM", "benchmark family name"),
            ("VerilogEval-v2", "benchmark family name"),
            ("CVDP", "benchmark family name"),
    ):
        w = _backtick_verdict(tok)
        assert w is not None, f"`{tok}` must be refused"
        assert marker in w, f"`{tok}` must be refused as {marker}; got {w[:200]}"


def test_backtick_guard_catches_cell_ids_by_family_not_by_length():
    """#798 NEGATIVE (load-bearing) — narrowing the length cap would have
    silently dropped 76 of the 126 CVDP cell ids that `git ls-files` yields
    from tracked PATHS (the harvest definition is spelled out at the top of
    `enhancement_emit.py`; file contents are excluded because this commit's
    own tests add cell-id literals). `\\bCVDP\\b` matched 0 of the 126 — `_` is
    a word character, so the boundary fails on both sides of
    `base_cvdp_..._0001` — and those 76 were refused only for being over 30
    characters, while the other 50 were accepted outright. A benchmark cell id
    must be refused for BEING a benchmark cell id — assert the rule that
    fires, not merely that something fires."""
    for cell in (
            "cvdp_copilot_scrambler_0001",
            "cvdp_copilot_cache_lru_0019",
            "cvdp_agentic_8x3_priority_encoder_0003",
            "base_cvdp_copilot_64b66b_encoder_0009",   # prefixed variants
            "ctx_cvdp_copilot_scrambler_0018",
            "enh_cvdp_copilot_scrambler_0009",
    ):
        w = _backtick_verdict(cell)
        assert w is not None, f"benchmark cell id `{cell}` must be refused"
        assert "benchmark family name" in w, (
            f"`{cell}` must be refused as a FAMILY leak, not by a length "
            f"accident; got: {w[:200]}")
    for prob in ("Prob089_ece241_2014_q5a", "base_Prob042_something"):
        w = _backtick_verdict(prob)
        assert w is not None and (
            "benchmark family name" in w or "Prob ID" in w), \
            f"`{prob}` must still be refused; got {w}"


#: #798 — the tracked-PATHS cell-id corpus size at the sha that authored this
#: change. A FLOOR, not an equality: the tree gains benchmark run dirs, so this
#: number only ever grows, and the claim that survives corpus growth is the
#: ratio, not the count. Present so the cardinal quoted in `enhancement_emit.py`
#: is re-derived by RUNNING the suite instead of trusted as prose.
_CVDP_CELL_ID_PATH_CORPUS_FLOOR = 126


def _cvdp_cell_ids_in_tracked_paths():
    """The harvest definition quoted in `enhancement_emit.py`, executable.
    PATHS ONLY — including file contents makes the corpus self-referential,
    since this module itself contains cell-id literals."""
    import re as _re5, subprocess as _sp2
    trees = _harvest_trees()
    if not trees:
        pytest.skip("benchmark-data/ not in this checkout (plugin-only install)")
    rx = _re5.compile(r"cvdp_(?:copilot|agentic)_[A-Za-z0-9_]*?_\d{4}")
    ids: set[str] = set()
    for root in trees:
        try:
            tracked = _sp2.run(["git", "-C", str(root), "ls-files"],
                               capture_output=True, text=True,
                               timeout=30).stdout.split()
        except (OSError, _sp2.SubprocessError):  # pragma: no cover - env-dependent
            pytest.skip("git not available to enumerate the tracked corpus")
        if not tracked:
            pytest.skip("not a git checkout — cannot enumerate the tracked corpus")
        for rel in tracked:
            ids.update(rx.findall(rel))
    return sorted(ids)


@needs_corpus
def test_every_tracked_cell_id_is_refused_as_a_family_leak():
    """#798 NEGATIVE (load-bearing) — the corpus form of the test above, and
    the executable version of the cardinal quoted in `enhancement_emit.py`.

    origin/main catches 0 of these by family (`\\bCVDP\\b` never matches an
    underscore-glued tag) and refuses only the 76 that happen to exceed the
    30-char cap; this branch must refuse ALL of them, and for the family
    reason. The ratio is the claim, not the count — the count is a floor
    because the tree keeps gaining benchmark run dirs."""
    ids = _cvdp_cell_ids_in_tracked_paths()
    assert len(ids) >= _CVDP_CELL_ID_PATH_CORPUS_FLOOR, (
        f"the tracked-PATHS cell-id corpus collapsed to {len(ids)} ids, below "
        f"the {_CVDP_CELL_ID_PATH_CORPUS_FLOOR} floor — a shrunken corpus "
        f"makes a 100%-coverage claim vacuous")
    not_family = [i for i in ids
                  if "benchmark family name" not in (_backtick_verdict(i) or "")]
    assert not not_family, (
        f"{len(not_family)}/{len(ids)} tracked CVDP cell ids are NOT refused "
        f"as a family leak: {sorted(not_family)[:10]}")


def test_backtick_guard_accepts_the_plugins_own_benchmark_adapters():
    """#798 — a family tag also legitimately PREFIXES this plugin's thin
    benchmark adapters, which the open-benchmark doctrine says are correctly
    named that way. Catching cell ids must not re-create the false-positive
    class this issue is about."""
    adapters = [
        "cvdp_gate.py", "cvdp_solve_pipeline.py", "cvdp_task_router.py",
        "test_cvdp_task_router.py", "cvdp_context_interface_recover",
        "cvdp_phase1_entry.py", "cvdp_results.json",
        "score_rtllm.py", "score_verilogeval.py",
        "verilogeval_v2", "verilogeval_human", "verilogeval_machine",
    ]
    refused = [(a, _backtick_verdict(a)) for a in adapters
               if _backtick_verdict(a)]
    assert not refused, (
        "the plugin's own benchmark adapter filenames are refused:\n" +
        "\n".join(f"  - `{a}` -> {w[:130]}" for a, w in refused))
    # ...but the BARE family tag on its own is still a leak.
    for bare in ("CVDP", "RTLLM", "MetRex", "ResBench"):
        assert _backtick_verdict(bare) is not None, \
            f"the bare family tag `{bare}` must still be refused"
    # ...and so is a DATASET artifact. An adapter carries no dataset numbering
    # (`cvdp_gate.py`: none; `verilogeval_v2`: one digit); a dataset artifact
    # carries a cell ordinal or a release version. Both forms below were
    # refused on origin/main only because they exceeded the 30-char cap, so
    # without this branch the length fix would have quietly freed them.
    for dataset in (
            "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl",
            "cvdp_open_v110",
            "cvdp_copilot_scrambler_0001"):
        w = _backtick_verdict(dataset)
        assert w is not None and "benchmark family name" in w, \
            f"dataset artifact `{dataset}` must be refused as a family leak; got {w}"


def test_pdk_allowlist_category_pins_public_pdks_and_excludes_leaf_names():
    """#798 — a PDK name whose digits are followed by more letters (`sg13g2`,
    `sky130a`) is structurally identical to a design leaf-name, so the honest
    discriminator is a finite public list, not a heuristic. Pinned as literals
    plus a set-equality assertion: deleting an entry must break this test, not
    silently delete its own coverage."""
    import yaml as _yaml
    data = _yaml.safe_load(
        (_PROGRAMS_DIR / "industry_tech_allowlist.yaml").read_text())
    entries = set(data["categories"]["pdk_foundry"]["entries"])
    assert entries == {
        "asap7", "freepdk45", "gf180", "gf180mcu", "nangate45", "sg13g2",
        "sky130", "sky130a", "sky130b", "skywater", "tsmc",
    }, f"pdk_foundry entries changed without updating this pin: {sorted(entries)}"
    loaded = _emit_mod._load_industry_tech_allowlist()
    assert {"asap7", "sg13g2", "sky130a"} <= loaded
    # NEGATIVE: the allowlist is for foundry / PDK proper nouns only — a
    # benchmark design leaf-name must never be reachable through it.
    assert not ({"radix2_div", "freq_divbyeven", "asyn_fifo", "mux256to1"}
                & loaded), \
        "a benchmark design leaf-name must never enter the industry allowlist"


def test_vocabulary_allowlist_categories_are_pinned():
    """#798 — the digit-shape rule's false positives are cleared HERE rather
    than by narrowing the rule, so these two categories are load-bearing.
    Literals plus set equality: deleting an entry must break this test rather
    than silently delete its own coverage."""
    import yaml as _yaml
    data = _yaml.safe_load(
        (_PROGRAMS_DIR / "industry_tech_allowlist.yaml").read_text())
    cats = data["categories"]
    assert set(cats["protocol_generation"]["entries"]) == {
        "ahb3", "ahb5", "apb3", "apb4", "arinc429", "axi3", "axi4",
        "ddr3", "ddr4", "ddr5", "gddr6", "hbm3", "jesd204", "lpddr4",
        "lpddr5", "milstd1553", "pcie3", "pcie4", "pcie5", "psi5", "rs485",
        "usb2", "usb3", "usb4",
    }, "protocol_generation changed without updating this pin"
    assert set(cats["encoding_and_width"]["entries"]) == {
        "base64", "bf16", "crc8", "crc16", "crc32", "crc64",
        "float16", "float32", "float64", "fp8", "fp16", "fp32",
        "int8", "int16", "int32", "int64", "md5", "sha1", "sha256", "sha512",
        "uint8", "uint16", "uint32", "utf8", "utf16", "utf32",
    }, "encoding_and_width changed without updating this pin"


@needs_corpus
def test_industry_allowlist_never_contains_a_benchmark_leaf_name():
    """#798 NEGATIVE (load-bearing) — the allowlist is now the ONLY thing
    standing between `ddr4` (accepted) and `lemmings1` (refused), which have
    identical shape. So the allowlist must be checked against the benchmark
    corpora themselves, not merely against a handful of remembered examples:
    one careless entry silently un-guards a real design name.

    REACH — what this does and does not do, so the next reader does not
    over-trust it:

      * It is a COLLISION check, not a semantic gate. It catches an entry that
        IS a name in the corpora below. It would happily pass `alu32`,
        `radix4div`, `fifo16`, `uart16550` — plausible design leaf-names that
        simply are not in these datasets. That limitation is real and
        currently unexercised.
      * Corpus = VerilogEval-v2 (156) + RTLLM (50) + CVDP design leaf-names
        (227 — this test CASE-FOLDS, because allowlist lookup is
        case-insensitive, and folding merges `IIR_filter`/`iir_filter` and
        `AXI_stream_upscale`/`axi_stream_upscale` out of the 229 raw names the
        floor tests above count), each REQUIRED with its own floor (see below)
        and each unioned with its separator-stripped form. Adding a fourth
        benchmark widens the reach for free; nothing here is dataset-specific.
      * Blast radius of a smuggled entry is bounded: the allowlist is consulted
        AFTER the Prob-ID and benchmark-family taboos in
        `_check_backtick_content`, so no entry can ever un-guard a family or
        Prob leak — only the digit-shape and unbroken-run rules."""
    import json as _json, re as _re3
    loaded = _emit_mod._load_industry_tech_allowlist()
    assert len(loaded) > 40, f"allowlist sanity: got {len(loaded)} entries"
    corpus = _corpus_tree()

    # Once the corpus is present, every dataset in it is REQUIRED and carries
    # its OWN floor. The earlier shape guarded the VerilogEval and RTLLM reads
    # with `if …is_file():` under a single aggregate `len(leaves) > 150` that
    # CVDP alone (227 case-folded) already satisfied: removing either file left
    # this control GREEN with a third to two-thirds of its corpus gone
    # (measured 699 -> 619 -> 479 -> 398 names, PASS in all four states).
    # `dff8`, `lfsr32`, `count10` and `fsm3` are VerilogEval leaf-names of
    # exactly the shape this control exists to catch, so the missing corpus is
    # not a cosmetic loss. A dataset is now either present or a loud failure —
    # and "the whole corpus is elsewhere" is the SKIP on this test, which is a
    # different statement from "the corpus is here and a dataset is missing".
    ve_src = corpus / "evaluation/verilogeval_v2/problems.list"
    assert ve_src.is_file(), (
        f"the published benchmark corpus is present at {corpus} but the "
        f"VerilogEval corpus this negative control depends on is missing: "
        f"{ve_src}")
    ve_leaves = {_re3.sub(r"^Prob\d+_", "", l.strip()).lower()
                 for l in ve_src.read_text().splitlines() if l.strip()}

    # RTLLM by GLOB, not by one version-named run root: the tree carries seven
    # `pass_at_1.json` siblings under evaluation/rtllm/ and pinning a single
    # `run_cleanroom_v1388/` makes the whole corpus vanish the day that run dir
    # is pruned or renamed. Their union is the same 50-design set.
    rt_srcs = sorted((corpus / "evaluation/rtllm").rglob("pass_at_1.json"))
    assert rt_srcs, (
        f"the published benchmark corpus is present at {corpus} but no "
        f"evaluation/rtllm/**/pass_at_1.json exists under it — the RTLLM "
        f"corpus this negative control depends on is missing")
    rt_leaves: set[str] = set()
    for _p in rt_srcs:
        try:
            _doc = _json.loads(_p.read_text())
        except ValueError:  # pragma: no cover - a malformed sibling run
            continue
        for _r in (_doc.get("results", []) if isinstance(_doc, dict) else []):
            if isinstance(_r, dict) and "design" in _r:
                rt_leaves.add(str(_r["design"]).split("/")[-1].lower())

    cvdp_leaves = {x.lower() for x in _cvdp_design_leaf_names()}

    for _label, _got, _floor in (("VerilogEval-v2", ve_leaves, 156),
                                 ("RTLLM", rt_leaves, 50),
                                 ("CVDP design (case-folded)", cvdp_leaves,
                                  227)):
        assert len(_got) >= _floor, (
            f"the {_label} corpus this negative control is measured against "
            f"collapsed to {len(_got)} names, below its floor of {_floor}. A "
            f"shrunken corpus makes a collision check pass by having nothing "
            f"left to collide with")

    leaves = ve_leaves | rt_leaves | cvdp_leaves
    leaves |= {l.replace("_", "") for l in leaves}
    clash = sorted(loaded & leaves)
    assert not clash, (
        f"industry allowlist entries collide with benchmark design "
        f"leaf-names — each one silently un-guards that design: {clash}")
