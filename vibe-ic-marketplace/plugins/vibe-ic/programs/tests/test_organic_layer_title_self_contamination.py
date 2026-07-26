"""ORGANIC — the plugin must never treat its OWN rendered layer-title heading
as evidence about the design.

DEFECT (measured on cell sha256 x gf180mcuD, plugin 1.5.85):
`phase1_dialogue_render` writes each layer heading from
`tools/phase1_engine/schema.LAYER_TITLES`, so every rendered doc contains

    ## L5 - Analog-Digital Interface (ADC/DAC, mixed-signal pads, PHY AFE)
           - NOT the vendor 'Analog Devices Inc.'

That line is a markdown heading, so `_v466_line_is_block_header` ranked it
ABOVE every prose hit and the `adc` / `dac` classes anchored on it. The
negation guard `_v0_1_62_analog_kw_negated` DOES correctly fire on the real
body sentence ("Purely digital synchronous block. No ADC, DAC, PHY AFE ..."),
but the emitter's `continue` advances to the next CLASS, never the next MATCH
- so the un-negated boilerplate occurrence won first and the negated real
sentence was never reached.

Result: two fabricated analog blocks on a pure-digital SHA-256 core, whose own
`evidence_paragraph` quotes the plugin's boilerplate verbatim. That drove an
entire A1-A9 analog track which wrote ngspice sizing/corner decks for hardware
that does not exist.

NARROWING (second pass). Recognising the boilerplate by SHAPE alone - any
`## L<n> -` heading - fixed the false positive by creating a false NEGATIVE.
The sole caller `gen_l5_adi_spec` runs this over the USER'S INPUT DOCS, and an
L-numbered heading is exactly the style this plugin's own layer scheme teaches
users to write, so a genuine mixed-signal spec whose ADC evidence sits under
`## L5 - ADC subsystem: 12-bit SAR ADC, 1 MSPS` was silently dropped. The
boilerplate is now recognised by its ACTUAL RENDERED TEXT - the heading counts
as the plugin's own only when the text after the layer code EQUALS that layer's
canonical `schema.LAYER_TITLES` entry.

BIDIRECTIONAL:
  * `test_boilerplate_heading_alone_is_not_evidence` - the DEFECT case, checked
    END-TO-END: post-fix the chosen match must land on the real rationale
    sentence, where the negation guard fires and the block is SUPPRESSED.
    Pre-fix it lands on the boilerplate heading, where the guard does not
    fire, so the block is EMITTED - and this test FAILS.
  * `test_genuine_analog_prose_still_detected` - a real mixed-signal doc must
    STILL be detected, so the guard cannot suppress true positives.
  * `test_user_l_numbered_heading_is_not_plugin_boilerplate` and
    `test_genuine_adc_heading_under_l_number_still_detected` - the FALSE
    NEGATIVE the shape-only rule introduced. Both FAIL against it.
  * `test_plugin_layer_titles_are_loaded` - PREMISE: the narrowed rule is
    driven by the real title table; if that table cannot be loaded the guard
    goes inert and the R2 defect returns unnoticed.
  * `test_negated_body_sentence_still_negated` - the pre-existing negation
    guard must be untouched.

CLOSING THE GAP (third pass). Whole-line equality against ONE table left two
measured holes; the predicate now sits between "too broad" and "too literal".

  HOLE A - the plugin has TWO layer-title tables and the guard knew ONE.
    `tools/phase1_engine/render._HUMAN_LAYER_TITLE` writes the FIRST LINE of
    every `L*_*.md` human doc (`title = _HUMAN_LAYER_TITLE.get(code, code)`
    then `f"# {title}"`), and its wording differs from `schema.LAYER_TITLES`
    for 10 of its 14 codes - L1 L2 L3 L5 L6 L8 L8R L9 L10 L13. Measured: the
    first line of `L5_ADI_SPEC.md`, `# L5 - Analog-Digital Interface`,
    returned False. INERT as measured (0 of those 14 titles matches any of the
    15 `_ANALOG_KEYWORDS` patterns, so no live fabrication) but a guard that
    knows half of what the plugin writes is one title edit from one.
    Covered by `test_human_layer_titles_are_loaded`,
    `test_human_doc_first_line_is_plugin_boilerplate`,
    `test_l5_human_doc_first_line_end_to_end_no_fabrication`.

  HOLE B - trivial mangling defeated equality, and each form was measured
    END-TO-END on the pure-digital document as REPRODUCING the original
    fabrication `analog_blocks == ['adc','dac']`: curly apostrophes, edited
    trailing punctuation, closed ATX (`## ... ##`), truncated / wrapped at a
    column, and a lowercased heading (the title body was casefolded but the
    LAYER CODE was not, so the fold was applied to 95% of the line and not
    the rest). Covered by
    `test_mangled_boilerplate_is_still_plugin_boilerplate` and
    `test_mangled_boilerplate_suppressed_end_to_end`.

  NOT closed, deliberately. A heading stripped of its leading `#` markers, or
    indented 4+ spaces (a CommonMark indented code block), is still not
    recognised. Both are indistinguishable from ordinary prose the user wrote,
    and widening to them would suppress a user's paragraph. Unchanged from the
    parent revision, so neither is a regression.

The truncation arm is ONE-DIRECTIONAL and floored, so closing those holes
cannot swing back to the old shape-only rule:
  * `test_canonical_title_plus_user_words_is_not_boilerplate` - a heading that
    EXTENDS a canonical title with the user's own words is the user's sentence.
  * `test_short_stub_heading_is_not_boilerplate` - a stub below the length
    floor may not claim a long canonical title by prefix.
  * `test_genuine_analog_body_under_human_doc_title_still_detected` - the
    second table must suppress the TITLE LINE only, never the body.
"""
import importlib.util
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


doc = _load("phase1_doc_one_shot_runner")

# byte-for-byte the heading the renderer emits for L5 (schema.LAYER_TITLES)
_L5_HEADING = ("## L5 — Analog-Digital Interface (ADC/DAC, mixed-signal pads, "
               "PHY AFE) — NOT the vendor 'Analog Devices Inc.'")
_ADC_PAT = doc._ANALOG_KEYWORDS["adc"]
_DAC_PAT = doc._ANALOG_KEYWORDS["dac"]

# REAL-SPEC headings a user writes in their OWN input doc, in the very
# L-numbered style this plugin's layer scheme teaches. None of them is the
# plugin's boilerplate; every one of them is design evidence. The shape-only
# rule `^#{1,6}\s*L\d+[A-Za-z]?\s*[dash]` suppressed all three.
_REAL_SPEC_HEADINGS = (
    "## L5 - ADC subsystem: 12-bit SAR ADC, 1 MSPS",
    "## L5 — Analog front end (12-bit SAR ADC)",
    "### L2 - ADC channel budget",
)


def test_boilerplate_heading_alone_is_not_evidence():
    """THE DEFECT CASE, asserted END-TO-END.

    The emitter's decision is `match, then suppress if negated`. Pre-fix the
    chosen match sits on the plugin's own heading, where the negation guard
    does NOT fire -> block EMITTED (the fabrication). Post-fix the heading is
    excluded, so the chosen match lands on the real rationale sentence, where
    the guard DOES fire -> block SUPPRESSED. Assert exactly that pipeline."""
    text = "\n".join([
        _L5_HEADING,
        "",
        "- no_analog_in_input: True",
        "- rationale: Purely digital synchronous block. No ADC, DAC, PHY "
        "AFE, analog pad or mixed-signal interface of any kind.",
    ])
    for name, pat in (("adc", _ADC_PAT), ("dac", _DAC_PAT)):
        m = doc._v466_best_class_match(text, pat)
        assert m is not None, f"{name}: expected the rationale match"
        ls, le = doc._v466_line_bounds(text, m.start())
        line = text[ls:le]
        assert not doc._v466_line_is_plugin_layer_title(line), (
            f"{name} still anchored on plugin boilerplate: {line!r}")
        assert doc._v0_1_62_analog_kw_negated(text, m.start(), m.end()), (
            f"{name}: chosen match is not negated -> block would be EMITTED "
            f"on line {line!r}")


def test_heading_is_recognised_as_plugin_boilerplate():
    assert doc._v466_line_is_plugin_layer_title(_L5_HEADING)
    # ...and an ordinary design heading is NOT suppressed
    assert not doc._v466_line_is_plugin_layer_title(
        "## Analog front end — 12-bit SAR ADC")
    assert not doc._v466_line_is_plugin_layer_title("| adc | 12-bit | ")


def test_genuine_analog_prose_still_detected():
    """TRUE-POSITIVE GUARD. The suppression must be limited to the plugin's
    own heading grammar - a real mixed-signal spec must still be detected,
    even when the boilerplate heading is also present."""
    text = "\n".join([
        _L5_HEADING,
        "",
        "- adc_type: 12-bit SAR ADC, 1 MSPS, single-ended input",
        "- reference: on-chip bandgap voltage reference feeds the ADC",
    ])
    m = doc._v466_best_class_match(text, _ADC_PAT)
    assert m is not None, "suppressed a GENUINE analog block"
    line = text[doc._v466_line_bounds(text, m.start())[0]:
                doc._v466_line_bounds(text, m.start())[1]]
    assert "adc_type" in line or "bandgap" in line, (
        f"matched the wrong line: {line!r}")


def test_plugin_layer_titles_are_loaded():
    """PREMISE GUARD. The narrowed rule compares against the plugin's REAL
    rendered titles (`tools/phase1_engine/schema.LAYER_TITLES`). If that table
    cannot be loaded the comparison can never match, the suppression silently
    goes inert and the R2 self-contamination defect returns with a green
    suite. Assert the premise instead of trusting it."""
    schema_titles = doc._v466_load_layer_titles()
    assert schema_titles, (
        "schema.LAYER_TITLES unreachable — the self-contamination guard "
        "would be inert")
    assert schema_titles.get("L5", "").strip()
    titles = doc._v466_plugin_layer_titles()
    assert titles, "no canonical layer titles loaded at all"
    assert "L5" in titles and titles["L5"], titles.get("L5")
    # the boilerplate constant above must still BE the rendered heading
    assert doc._v466_norm_layer_title_cmp(
        _L5_HEADING.split("L5", 1)[1].lstrip(" —–-")) in titles["L5"], (
        titles["L5"])


def test_user_l_numbered_heading_is_not_plugin_boilerplate():
    """FALSE-NEGATIVE GUARD, at the predicate. A user's own L-numbered heading
    carries the user's own words and is NOT the plugin's boilerplate."""
    for h in _REAL_SPEC_HEADINGS:
        assert not doc._v466_line_is_plugin_layer_title(h), (
            f"suppressed a REAL spec heading as boilerplate: {h!r}")
    # ...while the plugin's own full L5 heading still IS boilerplate
    assert doc._v466_line_is_plugin_layer_title(_L5_HEADING)


def test_genuine_adc_heading_under_l_number_still_detected():
    """FALSE-NEGATIVE GUARD, end-to-end and ON A HEADING (not in a bullet).

    The evidence sits on the heading itself, exactly as it does in a real
    mixed-signal spec, and the plugin's own boilerplate heading is present in
    the same doc. The chosen match must land on the USER'S heading."""
    for h in _REAL_SPEC_HEADINGS:
        text = "\n".join([
            _L5_HEADING,
            "",
            h,
            "",
            "Sampled at 1 MSPS from a 3.3 V single-ended source.",
        ])
        m = doc._v466_best_class_match(text, _ADC_PAT)
        assert m is not None, (
            f"suppressed a GENUINE analog heading, no evidence left: {h!r}")
        ls, le = doc._v466_line_bounds(text, m.start())
        assert text[ls:le] == h, (
            f"expected the match on {h!r}, got {text[ls:le]!r}")


def test_negated_body_sentence_still_negated():
    """The pre-existing negation guard must be unchanged by this fix."""
    neg = "Purely digital block. No ADC, DAC, PHY AFE, analog pad."
    i = neg.index("ADC")
    assert doc._v0_1_62_analog_kw_negated(neg, i, i + 3)
    pos = "12-bit SAR ADC, 1 MSPS, single-ended input"
    j = pos.index("ADC")
    assert not doc._v0_1_62_analog_kw_negated(pos, j, j + 3)


# ── CLOSING THE GAP — HOLE A: the plugin's SECOND title table ──────────
# `tools/phase1_engine/render.render_human_docs` writes the FIRST LINE of
# every `L*_*.md` human doc as `f"# {_HUMAN_LAYER_TITLE[code]}"`. Those 14
# lines are the plugin's own boilerplate exactly as the schema headings are,
# and their wording differs from `schema.LAYER_TITLES` for 10 codes, so a
# guard keyed on the schema table alone did not recognise them.
_HUMAN_DOC_FIRST_LINES = {
    "L1":  "# L1 — Datasheet",
    "L2":  "# L2 — Functional Requirements",
    "L3":  "# L3 — Command Protocol",
    "L4":  "# L4 — Register Map",
    "L5":  "# L5 — Analog-Digital Interface",
    "L6":  "# L6 — Control Logic",
    "L7":  "# L7 — Test & Debug",
    "L8":  "# L8 — Timing & Waveform",
    "L8R": "# L8R — RTL Constants",
    "L9":  "# L9 — Integration Spec",
    "L10": "# L10 — Test Cases",
    "L11": "# L11 — Calibration",
    "L12": "# L12 — Behavioral Sequences",
    "L13": "# L13 — Lab Calibration (Phase 1: contract; Phase 2: evidence)",
}

# the 10 the schema-only guard did NOT recognise (the other 4 happen to share
# their wording with `schema.LAYER_TITLES`, so they matched by coincidence)
_HUMAN_ONLY_CODES = ("L1", "L2", "L3", "L5", "L6", "L8", "L8R", "L9",
                     "L10", "L13")


# ── CLOSING THE GAP — HOLE B: harmless mangling of the rendered heading ──
# Each of these was measured END-TO-END on the pure-digital document as
# reproducing the ORIGINAL fabrication, `analog_blocks == ['adc','dac']`.
_MANGLED_BOILERPLATE = {
    # doc extraction / editors substitute curly quotes for straight ones
    "curly_apostrophes":
        "## L5 — Analog-Digital Interface (ADC/DAC, mixed-signal pads, "
        "PHY AFE) — NOT the vendor ‘Analog Devices Inc.’",
    # a human edits the final period away
    "edited_trailing_punct":
        "## L5 — Analog-Digital Interface (ADC/DAC, mixed-signal pads, "
        "PHY AFE) — NOT the vendor 'Analog Devices Inc'",
    # the CLOSED ATX heading form
    "closed_atx":
        "## L5 — Analog-Digital Interface (ADC/DAC, mixed-signal pads, "
        "PHY AFE) — NOT the vendor 'Analog Devices Inc.' ##",
    # truncated / wrapped at a column (here 60)
    "truncated_col60":
        "## L5 — Analog-Digital Interface (ADC/DAC, mixed-signal pads",
    # a pipeline that lowercases headings. The title body was already
    # casefolded; the LAYER CODE was not, so folding one and not the other
    # let the whole rendered boilerplate walk straight back in.
    "lowercased_line":
        "## l5 — analog-digital interface (adc/dac, mixed-signal pads, "
        "phy afe) — not the vendor 'analog devices inc.'",
}

_PURE_DIGITAL_BODY = (
    "\n"
    "- no_analog_in_input: True\n"
    "- rationale: Purely digital synchronous block. No ADC, DAC, PHY "
    "AFE, analog pad or mixed-signal interface of any kind."
)


def _emit_l5(tmp_path, docs):
    """Drive the REAL emitter and return the REAL emitted L5 content."""
    (tmp_path / "input" / "docs").mkdir(parents=True, exist_ok=True)
    for fname, txt in docs.items():
        (tmp_path / "input" / "docs" / fname).write_text(txt, encoding="utf-8")
    doc.gen_l5_adi_spec(tmp_path, dict(docs))
    out = tmp_path / "phase1" / "generated_docs" / "L5_ADI_SPEC.json"
    return json.loads(out.read_text(encoding="utf-8"))


def _blocks(content):
    return sorted(str(b.get("type"))
                  for b in (content.get("analog_blocks") or []))


def test_human_layer_titles_are_loaded():
    """PREMISE GUARD for the SECOND table. If
    `render._HUMAN_LAYER_TITLE` cannot be read, every human-doc first line
    silently stops being recognised as the plugin's own and HOLE A reopens
    with a green suite. Assert the premise, do not trust it."""
    human = doc._v466_load_human_layer_titles()
    assert human, ("render._HUMAN_LAYER_TITLE unreachable — the human-doc "
                   "half of the self-contamination guard would be inert")
    for code, line in _HUMAN_DOC_FIRST_LINES.items():
        assert code in human, f"{code} missing from _HUMAN_LAYER_TITLE"
        # the fixture line must still BE what render_human_docs writes
        assert line == f"# {human[code]}", (line, human[code])
    # ...and both tables must reach the combined canonical set
    titles = doc._v466_plugin_layer_titles()
    for code in _HUMAN_ONLY_CODES:
        body = doc._v466_strip_layer_code_prefix(code, human[code])
        assert doc._v466_norm_layer_title_cmp(body) in titles.get(code, ()), (
            f"{code}: human-doc title absent from the canonical set")


def test_human_doc_first_line_is_plugin_boilerplate():
    """HOLE A, at the predicate. Every one of the 14 human-doc first lines is
    the plugin's own boilerplate. The 10 in `_HUMAN_ONLY_CODES` — including
    `# L5 — Analog-Digital Interface`, the first line of L5_ADI_SPEC.md —
    returned False against the schema-table-only guard, so this FAILS there."""
    for code, line in _HUMAN_DOC_FIRST_LINES.items():
        assert doc._v466_line_is_plugin_layer_title(line), (
            f"{code}: the plugin's own human-doc first line is not "
            f"recognised as boilerplate: {line!r}")


def test_l5_human_doc_first_line_end_to_end_no_fabrication(tmp_path):
    """HOLE A, driven through the REAL emitter on a realistic L5_ADI_SPEC.md
    (the human doc the plugin itself renders, fed back in as an input doc).
    No analog block may be fabricated, and no evidence may quote the
    plugin's own title line."""
    md = "\n".join([
        _HUMAN_DOC_FIRST_LINES["L5"],
        "",
        "_IC: **sample_core**  •  Class: `digital/crypto`  •  "
        "Source-of-truth: `L5_ADI_SPEC.json`_",
        "",
        "- **no_analog_in_input**: true",
        "- **rationale**: Purely digital synchronous block. No ADC, DAC, "
        "PHY AFE, analog pad or mixed-signal interface of any kind.",
        "",
    ])
    content = _emit_l5(tmp_path, {"L5_ADI_SPEC.md": md})
    assert _blocks(content) == [], _blocks(content)
    assert content.get("analog_blocks_detected") is False
    blob = json.dumps(content, ensure_ascii=False)
    assert _HUMAN_DOC_FIRST_LINES["L5"].lstrip("# ") not in blob, (
        "the plugin's own human-doc title leaked into L5 as evidence")


def test_mangled_boilerplate_is_still_plugin_boilerplate():
    """HOLE B, at the predicate. Curly apostrophes, edited trailing
    punctuation, the closed-ATX form and truncation are all harmless
    variation — none of them turns the plugin's own heading into design
    evidence. Every one of these returned False against literal equality."""
    for tag, heading in _MANGLED_BOILERPLATE.items():
        assert doc._v466_line_is_plugin_layer_title(heading), (
            f"{tag}: mangled boilerplate not recognised: {heading!r}")


def test_mangled_boilerplate_suppressed_end_to_end(tmp_path):
    """HOLE B, END-TO-END through the REAL emitter on the pure-digital
    document. Each mangled form measured `analog_blocks == ['adc','dac']`
    against literal equality — the ORIGINAL fabrication — and must now
    measure `[]`."""
    for i, (tag, heading) in enumerate(sorted(_MANGLED_BOILERPLATE.items())):
        proj = tmp_path / f"case_{i}"
        proj.mkdir()
        content = _emit_l5(
            proj, {"design_description.md": heading + _PURE_DIGITAL_BODY})
        assert _blocks(content) == [], (
            f"{tag}: fabricated {_blocks(content)} from the plugin's own "
            f"mangled heading {heading!r}")
        assert content.get("analog_blocks_detected") is False, tag


def test_wrapped_boilerplate_suppressed_end_to_end(tmp_path):
    """HOLE B, the WRAPPED (not merely truncated) form: the heading is split
    across two lines by a 60-column wrap, so the analog vocabulary sits on the
    heading's leading run while the remainder becomes an ordinary line."""
    full = ("## L5 — Analog-Digital Interface (ADC/DAC, mixed-signal pads, "
            "PHY AFE) — NOT the vendor 'Analog Devices Inc.'")
    wrapped = full[:60] + "\n" + full[60:]
    content = _emit_l5(
        tmp_path, {"design_description.md": wrapped + _PURE_DIGITAL_BODY})
    assert _blocks(content) == [], _blocks(content)
    assert content.get("analog_blocks_detected") is False


def test_canonical_title_plus_user_words_is_not_boilerplate():
    """ANTI-BROADENING GUARD. The truncation arm is ONE-DIRECTIONAL: the
    candidate may be a PREFIX of a canonical title (a heading that got cut),
    NEVER a canonical title followed by the user's own words. Otherwise
    closing HOLE A would silently swallow real specs written in the very
    heading style this plugin teaches."""
    for h in (
        "## L2 - Functional Requirements for the ADC front end",
        "## L5 - Analog-Digital Interface for our 12-bit SAR ADC",
        "## L10 - Test Cases for the DAC ramp",
        "## L1 - Datasheet of the 12-bit SAR ADC",
        # case-folding the layer code must not broaden anything either: the
        # title after it still has to BE a canonical title
        "## l5 - ADC subsystem: 12-bit SAR ADC, 1 MSPS",
        "## l2 - Functional Requirements for the ADC front end",
    ):
        assert not doc._v466_line_is_plugin_layer_title(h), (
            f"suppressed the USER'S own heading as boilerplate: {h!r}")


def test_short_stub_heading_is_not_boilerplate():
    """ANTI-BROADENING GUARD. A stub shorter than
    `_V466_MIN_TRUNCATED_TITLE` may not claim a long canonical title by
    prefix — otherwise `## L5 - Analog` would stop being the user's word."""
    assert doc._V466_MIN_TRUNCATED_TITLE >= 8
    for h in ("## L5 - Analog", "## L5 — ADC", "## L1 - Data",
              "## L99 — Something Entirely Ours with an ADC"):
        assert not doc._v466_line_is_plugin_layer_title(h), h


def test_genuine_analog_body_under_human_doc_title_still_detected(tmp_path):
    """TRUE-POSITIVE GUARD for the SECOND table. Recognising the human-doc
    title line must suppress THAT LINE only — a real mixed-signal body under
    it is still design evidence and must still be detected END-TO-END."""
    md = "\n".join([
        _HUMAN_DOC_FIRST_LINES["L5"],
        "",
        "- **adc_type**: 12-bit SAR ADC, 1 MSPS, single-ended input",
        "- **reference**: on-chip bandgap voltage reference, 1.204 V",
        "",
    ])
    content = _emit_l5(tmp_path, {"L5_ADI_SPEC.md": md})
    got = _blocks(content)
    assert "adc" in got, got
    assert content.get("analog_blocks_detected") is True


def test_user_l_numbered_heading_survives_all_analog_classes(tmp_path):
    """NON-REGRESSION of the already-confirmed half, END-TO-END. 18 genuine
    USER L-numbered headings covering all 15 `_ANALOG_KEYWORDS` classes, each
    run WITH and WITHOUT the plugin's own boilerplate present = 36 runs
    through the REAL emitter. ZERO may be suppressed; a single miss means the
    predicate has swung back toward the old shape-only rule."""
    user_headings = [
        ("adc", "## L5 - ADC subsystem: 12-bit SAR ADC, 1 MSPS"),
        ("adc", "### L2 - ADC channel budget at 3.3 V"),
        ("dac", "## L5 — DAC output stage: 10-bit current-steering DAC"),
        ("dac", "## L1 - digital-to-analog converter, 2.5 V full scale"),
        ("ldo", "## L5 - LDO regulator, 1.8 V out, 150 mA"),
        ("bandgap", "## L5 — Bandgap voltage reference, 1.204 V"),
        ("pll", "## L6 - PLL clock generator, 100 MHz VCO"),
        ("oscillator", "## L5 - RC oscillator trim, fOSC 8 MHz"),
        ("esd", "## L1 — ESD protection: 2 kV HBM clamp diode"),
        ("opamp", "## L5 - OTA operational amplifier, 60 dB gain"),
        ("delta_sigma", "## L5 — Delta-sigma modulator, OSR 128"),
        ("comparator", "## L6 - Comparator threshold 0.7 Vdd"),
        ("charge_pump", "## L5 — Charge-pump doubler, 5 V from 2.5 V"),
        ("sc_filter", "## L5 - Switched-capacitor filter, 1 MHz corner"),
        ("por", "## L5 — POR power-on-reset trip at 1.35 V"),
        ("pull", "## L1 - RPU pull-up bias network, 50 kΩ at 3.3 V"),
        ("trim", "## L11 — TRIM_OSC_FREQ trim register, 6-bit"),
        ("adc",
         "#### L10 - analog-to-digital converter test vectors, 1.8 V"),
    ]
    # the fixture must exercise EVERY analog class, or "zero misses" is cheap
    assert {c for c, _ in user_headings} == set(doc._ANALOG_KEYWORDS)
    ctx = "Measured at 3.3 V supply, 1.8 V reference, 25 degC, 150 mA load."
    misses = []
    runs = 0
    for i, (cls, heading) in enumerate(user_headings):
        for j, with_boilerplate in enumerate((True, False)):
            proj = tmp_path / f"probe_{i}_{j}"
            proj.mkdir()
            lines = ([_L5_HEADING, ""] if with_boilerplate else []) + [
                heading, "", ctx, ""]
            content = _emit_l5(proj, {"user_spec.md": "\n".join(lines)})
            runs += 1
            got = _blocks(content)
            if cls not in got:
                misses.append((cls, heading, with_boilerplate, got))
    assert runs == 36, runs
    assert not misses, misses
