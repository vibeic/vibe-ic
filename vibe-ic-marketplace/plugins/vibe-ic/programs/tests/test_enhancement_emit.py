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

SCRIPT = Path(__file__).parent.parent / "enhancement_emit.py"
ROUTING = Path(__file__).parent.parent.parent / "benchmark-harness" / "CAPTURE_ROUTING.json"
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
        "design": "sha256", "bucket": "B",
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
        "design": "u_hawaii_adc", "bucket": "C",
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
        {"step": "phase3.pnr_setup_repair", "design": "sha256", "bucket": "B",
         "skill_title": "PnR repair", "pattern": "x", "when": "y",
         "what": "z", "example": "e", "generality": "g"},
        {"step": "analog.A2_topology", "design": "u_hawaii_adc", "bucket": "B",
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
        {"step": "phase2.rtl_gen", "design": "A", "bucket": "B",
         "skill_title": "Skill A", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g"},
        {"step": "phase2.rtl_gen", "design": "B", "bucket": "B",
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
        "step": "made.up.step", "design": "X", "bucket": "B",
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
        {"step": "phase3.pnr_setup_repair", "design": "sha256", "bucket": "B",
         "skill_title": "X", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g"},
        {"step": "phase3.drc", "design": "sha256", "bucket": "B",
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
