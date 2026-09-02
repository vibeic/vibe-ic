"""tests/test_v0_2_97_issue475_promoter_guard.py — ORGANIC-20260606 #475

Closes #475 (MEDIUM) — the L1.pin_table → L9 ports promoter swept
NON-port tokens into L9:

  * SDC constraint-directive keywords (`set_input_delay`,
    `set_output_delay`, `create_clock`, …) — each emitted as
    `mode=input`, evidence='promoted from L1.pin_table', because their
    embedded `input`/`output` substrings tricked the direction
    heuristic;
  * a standard-cell library-prefix token (a `*_fd_sc_*`-shaped name);

while the REAL direction-prefixed top ports (i_*/o_*) were dropped /
diluted.

Fix is chip-AGNOSTIC and threefold (all PATTERN-on-SHAPE, no vendor
literal):
  (a) deny SDC directive families (set_*_delay / create_clock /
      set_load / set_driving_cell / set_clock_* / …) inside
      `_is_real_port_token`;
  (b) deny the standard-cell library-prefix SHAPE (`\\w+_fd_sc_\\w+`,
      `\\w+_sc_<lib-tier>`) inside `_is_real_port_token`;
  (c) a positive port-like-evidence corroboration gate at the L9
      promoter callsite — promotion needs a direction-affix convention,
      a structured port-table-row source, or a recognisable
      functional-pin stem.

ACCEPTANCE: a fixture L1.pin_table contaminated with SDC directive
tokens + a library-prefix token ALONGSIDE real direction-prefixed ports
→ the promoted L9 contains ONLY the real ports; a clean port table is
unaffected.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
for _p in (str(PROGRAMS), str(PLUGIN_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from programs.phase1_one_shot_runner import (  # noqa: E402
    _is_real_port_token,
    _is_sdc_directive_token,
    _is_stdcell_lib_shape_token,
    _pin_has_port_like_evidence,
    gen_l9_integration_spec,
)

_GEN_DIR = Path("phase1") / "generated_docs"


def _seed_l1(project: Path, pin_table, ic_name="DEMO_TOP") -> None:
    gen = project / _GEN_DIR
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": ic_name, "pin_table": pin_table})
    )


def _read_l9(project: Path) -> dict:
    return json.loads(
        (project / _GEN_DIR / "L9_INTEGRATION_SPEC.json").read_text())


def _l9_port_names(l9: dict):
    ports = (l9.get("top_module_pins")
             or l9.get("top_ports")
             or l9.get("ports")
             or [])
    return [p.get("name") for p in ports if isinstance(p, dict)]


# ---------------------------------------------------------------------------
# Guard (a) — SDC directive family is a PATTERN class
# ---------------------------------------------------------------------------

def test_sdc_directive_family_rejected():
    for tok in (
        "set_input_delay", "set_output_delay", "set_max_delay",
        "set_min_delay", "create_clock", "create_generated_clock",
        "set_load", "set_driving_cell", "set_clock_latency",
        "set_clock_uncertainty", "set_false_path", "set_multicycle_path",
        "all_inputs", "all_outputs", "get_ports", "current_design",
    ):
        assert _is_sdc_directive_token(tok), tok
        assert not _is_real_port_token(tok, "DEMO_TOP"), (
            f"SDC directive {tok!r} must NOT be a real port token")


def test_sdc_guard_does_not_overmatch_real_ports():
    # `set_*` / `*_delay` style names that are NOT SDC directives must
    # still be allowed (no over-broad keyword grep).
    for tok in ("setup_done", "reset_n", "delay_count", "i_set",
                "delayed_data", "set_value"):
        assert not _is_sdc_directive_token(tok), tok


# ---------------------------------------------------------------------------
# Guard (b) — stdcell library-prefix SHAPE (pattern, not vendor literal)
# ---------------------------------------------------------------------------

def test_stdcell_lib_shape_rejected():
    # Synthetic process/variant names — SHAPE match only, no SKU.
    for tok in (
        "demo_fd_sc_hd", "proc_fd_sc_hdll", "xx_fd_sc_ls__1",
        "alpha_sc_hd", "beta_sc_hs", "gamma_sc_hdll",
    ):
        assert _is_stdcell_lib_shape_token(tok), tok
        assert not _is_real_port_token(tok, "DEMO_TOP"), (
            f"stdcell-lib-shaped {tok!r} must NOT be a real port token")


def test_stdcell_guard_does_not_overmatch_real_ports():
    for tok in ("scl", "scan_en", "schedule", "scl_io", "sc_data"):
        assert not _is_stdcell_lib_shape_token(tok), tok


def _deny_tokens():
    """The deny list, read as the file itself defines it."""
    text = (PROGRAMS / "tests" / "chip_deny_list.txt").read_text(
        encoding="utf-8")
    return [t for t in
            (ln.split("#", 1)[0].strip().lower() for ln in text.splitlines())
            if t]


def _denied_hits(text, token_re):
    return sorted({m.group(1).lower() for m in token_re.finditer(text)})


def _without_module_docstring(text):
    """The LOGIC only, which is what a `strict-logic` declaration scopes to.

    Cut with `ast`, not a regex: "the module docstring" has one unambiguous
    definition and a pattern for it would be a second, weaker one. The gate
    that reads the declaration only DISCLOSES it and ships no stripper of its
    own — enforcement is deliberately this lane's — so the cut is made here and
    nowhere else. Unparseable source keeps its whole text, which is the
    stricter reading and never the looser.
    """
    import ast
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    doc = ast.get_docstring(tree, clean=False)
    if not doc or not tree.body:
        return text
    node = tree.body[0]
    lines = text.splitlines(keepends=True)
    end = getattr(node, "end_lineno", None)
    if end is None:
        return text
    return "".join(lines[end:])


def test_the_matcher_here_is_the_canonical_one_and_not_a_second_copy():
    """THE RULE IS THE DENY LIST'S OWN, and this test used to break it.

    `chip_deny_list.txt` states its contract in its own header: "Matching is
    case-insensitive, **word-bounded (\\b)**", and the canonical
    implementation is `source_chip_agnostic_check._build_token_re`,
    `(?<![A-Za-z0-9_])(...)(?![A-Za-z0-9_])`. This test re-implemented the rule
    as a bare SUBSTRING (`line in src.lower()`) and was therefore STRICTER than
    the file it loads — not by decision, by re-implementation.

    MEASURED at `7903c1972305` on `phase1_doc_one_shot_runner.py`: the
    canonical matcher reports 0 hits, the substring one reports `['u_hawaii']`,
    and the single occurrence is inside a COMMENT that cites a run as
    provenance — `# Round 15 (u_hawaii_adc): a THIRD producer, ...` — not
    detection logic, which is what this file's own docstring says it guards.
    The hit is `u_hawaii` matching INSIDE `u_hawaii_adc`; the deny token is
    `u_hawaii`, and under the word-bounded rule the tree already accepts
    `u_hawaii_adc`. Aligning here changes no tree-wide policy: the canonical
    gate reports 0 hits over all 1357 top-level programs today.

    Whether the token OUGHT to be `u_hawaii_adc` is a deny-list question and is
    not settled here — the deny list is untouched. Doing it the other way
    round, dropping `u_hawaii` from the list to make one local test green,
    would blind the tree-wide guard to a real private codename.
    """
    import source_chip_agnostic_check as S
    header = (PROGRAMS / "tests" / "chip_deny_list.txt").read_text(
        encoding="utf-8").lower()
    assert "word-bounded" in header, (
        "the deny list no longer states the word-bounded rule this test "
        "delegates to; re-derive the contract before changing the matcher")
    rx = S._build_token_re(_deny_tokens())
    assert rx.search("u_hawaii ") and not rx.search("u_hawaii_adc"), (
        "the canonical matcher is no longer word-bounded, so delegating to it "
        "no longer means what this test says it means")


def test_no_denied_literal_in_source():
    """No deny-list codename in a program that CLAIMS the stricter rule.

    THE POPULATION IS BEHAVIOURAL, not a filename. It used to be one
    hand-typed path, which saw none of the other 1356 top-level programs and
    would have expired silently. `source_chip_agnostic_check` already
    maintains the registry this test wants: a program DECLARES `CHIP_AGNOSTIC:
    strict` / `strict-logic` in its own header, that gate READS the
    declaration, DISCLOSES it and explicitly does NOT enforce it — "the
    program's own test is the lane that can refuse". This is that lane.

    The promoter this file is about is scanned whether or not it declares,
    because that is the subject the rest of the module guards.

    Scanned WHOLE — comments and docstrings included — for every file except
    the ones declaring `strict-logic`, whose declaration says the docstring is
    stripped first. Nothing here is looser than what a file declared for
    itself.
    """
    import source_chip_agnostic_check as S
    rx = S._build_token_re(_deny_tokens())

    subjects = {PROGRAMS / "phase1_doc_one_shot_runner.py": "strict"}
    for f in sorted(PROGRAMS.glob("*.py")):
        text = f.read_text(encoding="utf-8", errors="replace")
        strictness, _off = S.declared_strictness_site(text)
        if strictness:
            subjects[f] = strictness
    assert len(subjects) > 1, (
        f"the declared-strict population collapsed to {len(subjects)}; a "
        "single-member denominator reads clean no matter what it holds")

    bad = {}
    for f, strictness in sorted(subjects.items()):
        text = f.read_text(encoding="utf-8", errors="replace")
        if strictness == "strict-logic":
            text = _without_module_docstring(text)
        hits = _denied_hits(text, rx)
        if hits:
            bad[f.name] = hits
    assert not bad, (
        f"denied literal(s) present in a program that declares the stricter "
        f"rule: {bad}")


# ---------------------------------------------------------------------------
# Guard (c) — positive port-like-evidence corroboration
# ---------------------------------------------------------------------------

def test_positive_evidence_direction_affix():
    assert _pin_has_port_like_evidence({"name": "i_clk"})
    assert _pin_has_port_like_evidence({"name": "o_data"})
    assert _pin_has_port_like_evidence({"name": "io_bus"})
    assert _pin_has_port_like_evidence({"name": "rst_n"})


def test_positive_evidence_structured_source():
    assert _pin_has_port_like_evidence(
        {"name": "zzqq", "extraction_strategy": "markdown_pipe_table"})
    assert _pin_has_port_like_evidence(
        {"name": "zzqq",
         "extraction_strategy": "rst_grid_interface_table"})
    assert _pin_has_port_like_evidence(
        {"name": "zzqq", "evidence": "pipe table row in pinout section"})


def test_positive_evidence_functional_stem():
    for nm in ("clk", "reset_n", "id_bus", "ddr_dq", "vbg", "ovp",
               "cs", "we", "data_bus"):
        assert _pin_has_port_like_evidence({"name": nm}), nm


def test_positive_evidence_rejects_uncorroborated_novel_junk():
    # A novel non-port token: no direction affix, no structured source,
    # no functional stem, only the generic 'promoted' placeholder.
    junk = {"name": "frobnicate_widget",
            "evidence": "promoted from L1.pin_table"}
    assert not _pin_has_port_like_evidence(junk)


# ---------------------------------------------------------------------------
# ACCEPTANCE — defect-artifact fixture, executed end-to-end
# ---------------------------------------------------------------------------

# The defect-artifact: an L1.pin_table shaped exactly like the issue's
# 現象 — SDC directive tokens + a library-prefix token (all carrying the
# generic 'promoted from L1.pin_table' evidence, all mislabelled
# mode=input) interleaved with the REAL direction-prefixed top ports.
_DEFECT_PIN_TABLE = [
    {"name": "set_input_delay",  "mode": "input",
     "evidence": "promoted from L1.pin_table"},
    {"name": "i_clk",            "mode": "input",
     "evidence": "markdown_pipe_table",
     "extraction_strategy": "markdown_pipe_table"},
    {"name": "set_output_delay", "mode": "input",
     "evidence": "promoted from L1.pin_table"},
    {"name": "i_rst_n",          "mode": "input",
     "evidence": "markdown_pipe_table",
     "extraction_strategy": "markdown_pipe_table"},
    {"name": "demo_fd_sc_hdll",  "mode": "input",
     "evidence": "promoted from L1.pin_table"},
    {"name": "o_data",           "mode": "output",
     "evidence": "markdown_pipe_table",
     "extraction_strategy": "markdown_pipe_table"},
    {"name": "create_clock",     "mode": "input",
     "evidence": "promoted from L1.pin_table"},
]
_REAL_PORTS = {"i_clk", "i_rst_n", "o_data"}
_JUNK_TOKENS = {"set_input_delay", "set_output_delay",
                "demo_fd_sc_hdll", "create_clock"}


def test_acceptance_contaminated_pin_table_yields_only_real_ports(
        tmp_path):
    """ACCEPTANCE end-state: the contaminated defect-artifact fixture,
    run through the real gen_l9_integration_spec promoter, yields L9
    ports == EXACTLY the real direction-prefixed ports; every SDC
    directive token and the library-prefix token is filtered."""
    _seed_l1(tmp_path, _DEFECT_PIN_TABLE)
    gen_l9_integration_spec(tmp_path, {}, l3={})
    l9 = _read_l9(tmp_path)
    names = set(_l9_port_names(l9))

    # END STATE (a): only the real ports survive.
    assert names == _REAL_PORTS, (
        f"L9 promoted set != real ports.\n"
        f"  got:  {sorted(names)}\n"
        f"  want: {sorted(_REAL_PORTS)}")
    # END STATE (b): NONE of the junk leaked.
    assert not (names & _JUNK_TOKENS), (
        f"junk token(s) leaked into L9: {sorted(names & _JUNK_TOKENS)}")


def test_acceptance_clean_port_table_unaffected(tmp_path):
    """Corpus-sweep guard: a clean port table (no contamination) is
    promoted verbatim — the new guards must not prune legitimate
    ports."""
    clean = [
        {"name": "clk",     "mode": "input"},
        {"name": "reset_n", "mode": "input"},
        {"name": "id_bus",  "mode": "inout"},
        {"name": "DDR_DQ",  "mode": "inout", "io_standard": "SSTL"},
        {"name": "ovp",     "mode": "input"},
        {"name": "we",      "mode": "input"},
    ]
    _seed_l1(tmp_path, clean, ic_name="CLEAN_TOP")
    gen_l9_integration_spec(tmp_path, {}, l3={})
    l9 = _read_l9(tmp_path)
    names = set(_l9_port_names(l9))
    # All six legitimate ports survive (DDR_DQ canonicalises lowercase).
    assert names == {"clk", "reset_n", "id_bus", "ddr_dq", "ovp", "we"}, (
        f"clean port table was altered: {sorted(names)}")


def test_acceptance_junk_only_table_yields_honest_empty(tmp_path):
    """If the upstream extractor picked the WRONG table/column and the
    pin_table holds ONLY junk, the promoter must emit an honest empty
    port list (no fabricated ports), not the junk."""
    junk_only = [
        {"name": "set_input_delay",  "mode": "input",
         "evidence": "promoted from L1.pin_table"},
        {"name": "set_output_delay", "mode": "input",
         "evidence": "promoted from L1.pin_table"},
        {"name": "demo_fd_sc_hd",    "mode": "input",
         "evidence": "promoted from L1.pin_table"},
    ]
    _seed_l1(tmp_path, junk_only, ic_name="JUNK_TOP")
    gen_l9_integration_spec(tmp_path, {}, l3={})
    l9 = _read_l9(tmp_path)
    assert _l9_port_names(l9) == [], (
        f"junk-only table fabricated ports: {_l9_port_names(l9)}")
