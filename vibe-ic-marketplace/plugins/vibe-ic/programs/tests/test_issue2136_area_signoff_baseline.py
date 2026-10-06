#!/usr/bin/env python3
"""vibe-ic#2136 — a standard-cell area ceiling measured on ONE technology must
not judge a run built on another; it must resolve per technology or refuse by
name.

Measured (lane rbsub4, confirmed unchanged by rbsub5): an L7 verification plan
states its baseline WITH its attribution --

    ### 7.4.1 Baseline (top=..., sky130_fd_sc_hd, TT corner)
    | stdcell area | **12,775 um^2** |

-- and then turns it into an absolute sign-off row that carries NO attribution
at all:

    | stdcell area | (0, baseline x 1.3] = <= 16,608 um^2 | gate |

The same design directed onto gf180mcuD mapped to 57,024.71 um^2 (2180 cells).
Against that row it is a 3.4x overshoot; against the row's own denominator it
is not a comparison at all. The lane declined to report pass/fail and said so.

BOTH DIRECTIONS ARE ASSERTED HERE, deliberately:
  * the run on the baseline's OWN technology must reproduce 16,608 with its
    source cited -- a fix that refuses everything is not a fix; and
  * the run on another technology must read NOT_DETERMINED BY NAME, never PASS
    and never FAIL, and must become judgeable again the moment a baseline
    measured in its OWN cell library exists.

THE MUTATION IS RUN HERE TOO: disabling the attribution test is exactly the
"fall back to the other technology's literal" defect, and the test asserts the
mutant reproduces 16,608 for the other technology while the shipped code does
not. A check that cannot fail is not a check.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import area_signoff_baseline as asb          # noqa: E402

PROG = PROGRAMS / "area_signoff_baseline.py"

#: The measured document's shape, with its real numbers. `LIB_A` is the open
#: standard-cell library the baseline was measured on; `LIB_B` / `PDK_B` are
#: the open technology the run was directed onto. Both are open PDKs.
LIB_A = "sky130_fd_sc_hd"
PDK_A = "sky130A"
LIB_B = "gf180mcu_fd_sc_mcu7t5v0"
PDK_B = "gf180mcuD"

#: The area the run on the OTHER technology actually mapped to.
MEASURED_B_UM2 = 57024.71

L7_DOC = f"""# L7 - Verification Plan

## 7.4 Quality Metrics

### 7.4.1 Baseline (top=`core`, memsize=1024, {LIB_A}, TT corner)

| metric | Baseline |
|---|---|
| stdcell count | **1,502** |
| stdcell area | **12,775 um^2** |
| die area | **34,269 um^2** |
| total power (TT) | **2.26 mW** |

### 7.4.2 Sign-off Acceptance Range

> The design should at least match baseline (area / power within baseline x 1.3).

| metric | accepted range | sign-off gate |
|---|---|---|
| stdcell count (informational) | baseline x [0.5, 2.0] = [751, 3004] | no |
| stdcell area | (0, baseline x 1.3] = <= 16,608 um^2 | yes |
| total power (TT) | (0, baseline x 1.3] = <= 2.94 mW | yes |
"""


def _docs(text=L7_DOC):
    return [("input/docs/L7_verification_plan.md", text)]


# ── the baseline's OWN technology: reproduced, with its source ─────────────
def test_the_baselines_own_technology_reproduces_the_stated_ceiling():
    rep = asb.resolve_texts(_docs(), [LIB_A, PDK_A])
    assert rep["determined"] is True
    assert rep["tier"] == asb.DECLARED_BASELINE_TIER
    assert rep["threshold_um2"] == 16608.0
    assert rep["baseline_um2"] == 12775.0
    assert rep["ratio"] == 1.3
    # The document's own rounding is SHOWN, not silently reconciled: the
    # product is 16,607.5 and the document states 16,608.
    assert rep["derived_um2"] == 16607.5
    # The value never travels without its source.
    assert rep["source"] == "input/docs/L7_verification_plan.md"
    assert rep["line"] == 21
    assert "16,608" in rep["row"]
    assert LIB_A in rep["baseline_attribution"]
    assert rep["matched_name"] == LIB_A


def test_the_pdk_name_alone_resolves_the_library_keyed_baseline():
    """A caller that knows only the PDK still reaches a library-attributed
    baseline: a PDK and its library are one technology family, and requiring
    equality would make them two."""
    rep = asb.resolve_texts(_docs(), [PDK_A])
    assert rep["determined"] is True
    assert rep["threshold_um2"] == 16608.0


# ── another technology: refused BY NAME, never PASS and never FAIL ─────────
def test_another_technology_is_not_determined_by_name():
    rep = asb.resolve_texts(_docs(), [LIB_B, PDK_B])
    assert rep["determined"] is False
    assert rep["tier"] == asb.NOT_DETERMINED_TIER
    assert rep["reason"] == "baseline_not_attributed_to_this_technology"
    assert rep["threshold_um2"] is None
    # The refusal is ACTIONABLE: it says what the document DID attribute to.
    assert any(LIB_A in a for a in rep["attributions_seen"])
    assert rep["would_have_stated"]
    assert rep["disclosure"] == asb.NOT_DETERMINED_DISCLOSURE
    # It also says a sign-off WAS stated, so "no rule" and "no denominator for
    # this run" are not collapsed into one silence.
    assert rep["signoff_row_found"] is True


def test_a_cross_technology_verdict_is_neither_pass_nor_fail():
    rep = asb.resolve_texts(_docs(), [LIB_B, PDK_B])
    v = asb.verdict(rep, MEASURED_B_UM2)
    assert v["verdict"] == asb.NOT_DETERMINED
    assert v["verdict"] != asb.PASS
    assert v["verdict"] != asb.FAIL
    assert v["threshold_um2"] is None


def test_the_same_area_on_its_own_technology_is_judged_again():
    """The refusal must be about the DENOMINATOR, not a blanket refusal.

    Given a reference netlist measured in this run's OWN cell library, the same
    57,024.71 um^2 becomes a real comparison -- and it passes, which is the
    engineering answer the cross-technology row could never give.
    """
    rep = asb.resolve_texts(_docs(), [LIB_B, PDK_B],
                            reference_area_um2=48000.0,
                            reference_area_cite="baseline/metrics.json::area")
    assert rep["determined"] is True
    assert rep["tier"] == asb.DERIVED_REFERENCE_TIER
    assert rep["threshold_um2"] == 62400.0
    assert rep["baseline_um2"] == 48000.0
    assert "baseline/metrics.json::area" in rep["note"]
    assert asb.verdict(rep, MEASURED_B_UM2)["verdict"] == asb.PASS
    # ... and a genuinely oversized design on its own technology still FAILs,
    # so the derived tier is a gate and not a rubber stamp.
    assert asb.verdict(rep, 70000.0)["verdict"] == asb.FAIL


# ── THE MUTATION: fall back to the other technology's literal ──────────────
def test_mutation_falling_back_to_the_literal_reproduces_the_defect(
        monkeypatch):
    """Disable the attribution test and #2136 comes straight back.

    This is the whole fix in one assertion: the ONLY thing standing between the
    other technology's run and the 16,608 literal is `same_family` refusing to
    call two families one. With it mutated to accept anything, the resolver
    hands the other technology a ceiling measured on the first -- the exact
    defect. Unmutated, it refuses.
    """
    clean = asb.resolve_texts(_docs(), [LIB_B, PDK_B])
    assert clean["threshold_um2"] is None

    monkeypatch.setattr(asb, "same_family", lambda a, b: True)
    mutant = asb.resolve_texts(_docs(), [LIB_B, PDK_B])
    assert mutant["threshold_um2"] == 16608.0, (
        "the mutation must reproduce the defect; if it does not, this test is "
        "not exercising the guard it claims to")
    assert asb.verdict(mutant, MEASURED_B_UM2)["verdict"] == asb.FAIL


def test_the_family_rule_separates_families_and_unites_a_pdk_with_its_library():
    assert asb.same_family(LIB_A, PDK_A) is True
    assert asb.same_family(LIB_B, PDK_B) is True
    assert asb.same_family(LIB_A, LIB_B) is False
    assert asb.same_family(PDK_A, PDK_B) is False
    # A family token too short to be distinctive is never matched by prefix.
    assert asb.same_family("ab", "abc") is False


# ── the technology-keyed table tier ────────────────────────────────────────
KEYED_DOC = f"""# L7

### Baseline standard-cell area, per technology

| Std-cell library | stdcell area baseline (um^2) |
|---|---|
| `{LIB_A}` | 12,775 um^2 |
| `gf180mcu_*` | 48,000 um^2 |

Area is accepted within baseline x 1.3.
"""


def test_a_technology_keyed_table_answers_per_technology():
    a = asb.resolve_texts([("input/docs/L7_plan.md", KEYED_DOC)], [LIB_A])
    b = asb.resolve_texts([("input/docs/L7_plan.md", KEYED_DOC)], [PDK_B])
    assert a["tier"] == asb.DECLARED_PDK_TABLE_TIER
    assert b["tier"] == asb.DECLARED_PDK_TABLE_TIER
    assert a["threshold_um2"] == pytest.approx(16607.5)
    assert b["threshold_um2"] == pytest.approx(62400.0)
    # Two technologies, two answers, from one document. That is the fix.
    assert a["threshold_um2"] != b["threshold_um2"]


# ── refusals that are not this issue's refusal ─────────────────────────────
def test_the_run_technology_must_be_supplied():
    rep = asb.resolve_texts(_docs(), [])
    assert rep["determined"] is False
    assert rep["reason"] == "run_technology_not_supplied"


def test_a_document_with_no_area_signoff_states_no_denominator():
    rep = asb.resolve_texts([("input/docs/L7_plan.md", "# L7\n\nNo areas.\n")],
                            [LIB_A])
    assert rep["determined"] is False
    assert rep["reason"] == "no_area_signoff_stated"
    assert rep["signoff_row_found"] is False


def test_two_baselines_for_this_technology_that_disagree_refuse():
    doc = L7_DOC + f"""
### 7.4.3 Second baseline ({LIB_A}, other corner)

| metric | Baseline |
|---|---|
| stdcell area | **9,000 um^2** |
"""
    rep = asb.resolve_texts([("input/docs/L7_plan.md", doc)], [LIB_A])
    assert rep["determined"] is False
    assert rep["reason"] == "declared_baseline_ambiguous"
    assert rep["threshold_um2"] is None


def test_a_baseline_with_no_acceptance_rule_is_not_a_threshold():
    doc = f"""# L7

### Baseline ({LIB_A}, TT corner)

| metric | Baseline |
|---|---|
| stdcell area | **12,775 um^2** |
"""
    rep = asb.resolve_texts([("input/docs/L7_plan.md", doc)], [LIB_A])
    assert rep["determined"] is False
    assert rep["reason"] == "no_acceptance_rule"


def test_a_retired_row_is_not_a_declaration():
    """vibe-ic#712 -- a row a document retires must not be published as a spec."""
    doc = L7_DOC.replace(
        "| stdcell area | **12,775 um^2** |",
        "| stdcell area | **12,775 um^2** -- this row is no longer used |")
    rep = asb.resolve_texts([("input/docs/L7_plan.md", doc)], [LIB_A])
    assert rep["baseline_um2"] is None
    assert rep["determined"] is False


def test_die_and_core_area_rows_are_not_standard_cell_area():
    """The die comparison belongs to `area_total_vs_budget_check`; reading a
    die figure as a cell ceiling is a different number with a different rule."""
    got = asb.parse_area_statements(L7_DOC, source="d")
    assert len(got["baselines"]) == 1
    assert got["baselines"][0]["value_um2"] == 12775.0


# ── the L7 emitter's disclosure ────────────────────────────────────────────
def _project(tmp_path: Path, fields: dict) -> Path:
    p = tmp_path / "proj"
    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"fields": fields}, indent=2) + "\n")
    return p


def test_l7_records_the_baseline_it_used_and_its_source(tmp_path):
    proj = _project(tmp_path, {"pdk_target": PDK_A})
    block = asb.for_l7(proj, _docs())
    assert block is not None
    assert block["determined"] is True
    assert block["threshold_um2"] == 16608.0
    assert block["source"] == "input/docs/L7_verification_plan.md"
    assert block["tier"] == asb.DECLARED_BASELINE_TIER
    assert block["run_technology"]["candidates"] == [PDK_A]


def test_a_library_and_its_own_pdk_are_one_technology_not_two(tmp_path):
    """A well-declared project states BOTH its std-cell library and its PDK.

    MEASURED on the first shape of this resolver: those are two different
    TOKENS for one technology, and grouping by token equality read them as two
    families and refused — which would have turned every properly-declared
    project into NOT_DETERMINED and made the fix inert on exactly the case it
    exists for. The refusal must be about naming two FAMILIES, not two names.
    """
    proj = _project(tmp_path, {"std_cell_library": LIB_A, "pdk_target": PDK_A})
    tech = asb.run_technology(proj)
    assert tech["ambiguous"] is False
    assert tech["candidates"] == [LIB_A, PDK_A]
    block = asb.for_l7(proj, _docs())
    assert block["determined"] is True
    assert block["threshold_um2"] == 16608.0


def test_the_baselines_citation_survives_the_ceilings_citation():
    """Provenance BESIDE the value, not only inside `note`.

    When the document states an absolute ceiling, `source`/`line` cite the
    ceiling row — so the baseline's own citation has to live in its own fields
    or a consumer would have to parse English to reach it.
    """
    rep = asb.resolve_texts(_docs(), [LIB_A])
    assert rep["line"] == 21                      # the ceiling row
    assert rep["baseline_line"] == 10             # the baseline row
    assert rep["baseline_source"] == "input/docs/L7_verification_plan.md"
    assert "12,775" in rep["baseline_row"]


def test_l7_refuses_when_the_project_names_two_technology_families(tmp_path):
    """The measured design's own shape: it names BOTH families and has chosen
    neither, so at L7-emission time no run technology is determined."""
    proj = _project(tmp_path, {"pdk_target": "sky130",
                               "pdk_target_alternates": ["sky130", "gf180mcu"]})
    block = asb.for_l7(proj, _docs())
    assert block is not None
    assert block["determined"] is False
    assert block["reason"] == "run_technology_ambiguous"
    assert block["threshold_um2"] is None
    assert block["run_technology"]["ambiguous"] is True


def test_l7_technology_citation_is_project_relative(tmp_path):
    """A generated L document must not freeze the machine's project root."""
    proj = _project(tmp_path, {"pdk_target": "sky130",
                               "pdk_target_alternates": ["gf180mcu"]})
    block = asb.for_l7(proj, _docs())
    assert block is not None
    source = block["run_technology"]["source"]
    assert source == "phase1/generated_docs/L19_CONSTRAINTS_PDK.json::fields.pdk_target"
    assert str(proj) not in json.dumps(block)


def test_l7_run_liberty_citation_does_not_embed_a_host_path(tmp_path):
    proj = _project(tmp_path, {"pdk_target": "sky130"})
    stats = proj / "phase2" / "stage2" / "synth" / "stats.json"
    stats.parent.mkdir(parents=True)
    liberty = "/opt/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/tt.lib"
    stats.write_text(json.dumps({"chip_area_unit_evidence": {"liberty": liberty}}))
    tech = asb.run_technology(proj)
    assert tech["source"] == "stats.json::chip_area_unit_evidence.liberty"
    assert liberty not in json.dumps(tech)


def test_l7_adds_no_key_when_the_design_declares_no_area_signoff(tmp_path):
    """MEMBERSHIP: an L7 document of a design that states no standard-cell area
    sign-off is byte-identical to what it was before this change."""
    proj = _project(tmp_path, {"pdk_target": PDK_A})
    assert asb.for_l7(proj, [("input/docs/L7_plan.md", "# L7\n\nNothing.\n")]) \
        is None


# ── the L7 roots this repository publishes ────────────────────────────────
def _published_l7_docs():
    root = PROGRAMS / "tests" / "fixtures"
    out = []
    for p in sorted(root.rglob("L7_*")):
        if p.is_file() and p.suffix.lower() in (".md", ".txt"):
            out.append(p)
    return out


def test_published_l7_roots_membership_no_verdict_moves_off_its_own_ceiling():
    """Over every L7 document this repo publishes, the resolver reproduces the
    document's OWN stated ceiling for the technology the document names, and
    determines nothing for any other technology.

    Membership, not counts: every published root is visited and named.
    """
    docs = _published_l7_docs()
    assert docs, "no published L7 document found; this test would be vacuous"
    judged = {}
    for d in docs:
        text = d.read_text(errors="ignore")
        items = [(str(d.relative_to(PROGRAMS)), text)]
        rep_a = asb.resolve_texts(items, [LIB_A, PDK_A])
        rep_b = asb.resolve_texts(items, [LIB_B, PDK_B])
        judged[str(d.relative_to(PROGRAMS))] = (rep_a, rep_b)
        # No document may answer for a technology it never measured.
        if rep_b["determined"]:
            assert asb._text_names_family(
                str(rep_b["baseline_attribution"]), [LIB_B, PDK_B])
    # The one published root that carries a real sign-off table states its own
    # ceiling, and the resolver returns that number and no other.
    with_ceiling = {k: v for k, v in judged.items() if v[0]["determined"]}
    assert with_ceiling, "no published L7 root carries a resolvable ceiling"
    for name, (rep_a, _rep_b) in with_ceiling.items():
        assert str(int(rep_a["threshold_um2"])) or True
        # the resolved number is the one the document itself writes down
        digits = f"{rep_a['threshold_um2']:,.0f}"
        assert digits in rep_a["row"] or digits.replace(",", "") in rep_a["row"], (
            f"{name}: resolved {rep_a['threshold_um2']} is not the number the "
            f"document states in {rep_a['row']!r}")


def test_no_published_l7_document_gained_a_key():
    """MEMBERSHIP over the GENERATED L7 roots this repo publishes.

    The input-doc roots are covered above; these are the emitted ones. None of
    them declares a standard-cell area sign-off, so none of them may carry the
    new field -- their bytes did not move, and this asserts it by MEMBERSHIP
    (every published root is visited and named) rather than by a count.
    """
    roots = sorted((PROGRAMS / "tests" / "fixtures").rglob("L7_TEST_DEBUG.json"))
    assert roots, "no published L7_TEST_DEBUG.json found; this would be vacuous"
    carriers = [str(p.relative_to(PROGRAMS))
                for p in roots
                if asb.L7_FIELD in json.loads(p.read_text(errors="replace"))]
    assert not carriers, (
        "these published L7 documents gained a field they had no sign-off to "
        "disclose: " + ", ".join(carriers))


# ── the CLI contract ──────────────────────────────────────────────────────
def _cli(*args):
    cp = subprocess.run([sys.executable, str(PROG), *args],
                        capture_output=True, text=True)
    return cp


def test_cli_exit_codes_separate_not_determined_from_fail(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "L7_verification_plan.md").write_text(L7_DOC)
    ok = _cli("--docs-dir", str(d), "--library", LIB_A,
              "--measured-area-um2", "1000")
    assert ok.returncode == 0
    bad = _cli("--docs-dir", str(d), "--library", LIB_A,
               "--measured-area-um2", str(MEASURED_B_UM2))
    assert bad.returncode == 1
    nd = _cli("--docs-dir", str(d), "--library", LIB_B,
              "--measured-area-um2", str(MEASURED_B_UM2))
    assert nd.returncode == 2, (
        "a run with no valid denominator must exit 2 (NOT_DETERMINED), never "
        "1 (FAIL) -- the two are different findings")
    assert json.loads(nd.stdout)["verdict"]["verdict"] == asb.NOT_DETERMINED


# ── the L7 call site copies a RECORD; it interprets no sentence ───────────
#
# THE LANDING GATE REFUSED THIS BRANCH ONCE, correctly, and this is the pin.
# The first shape of the L7 block chose which documents to hand over with
# `_L7_FILE_KEYWORDS.search(<filename>)` INSIDE the comprehension that produced
# the texts. `prose_polarity_consulted_check` reads a search in a CONDITION as
# tainting the value it guards, so the block read as "choose which prose to
# believe, then publish it" in a function that consults no polarity — the
# #706/#711 shape. Measured on `eb5f863cb`: 210 offenders without it, 211 with,
# this name being the whole difference.
#
# The remedy was to stop choosing here. The corpus is handed over unfiltered and
# `area_signoff_baseline` — which consults `_prose_polarity` on every row and
# every prose line it reads — decides relevance by its OWN rules.
def _detector():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ppc_probe", PROGRAMS / "prose_polarity_consulted_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _is_blind(mod, src: str) -> bool:
    """The REAL predicate `scan` applies, over one synthetic function."""
    import ast
    tree = ast.parse(src)
    al = mod._aliases(tree)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return (mod._searches_prose(fn) and mod._writes_a_declared_value(fn)
            and not mod._consults_polarity(fn, al))


#: The one line that was removed. Re-inserting it into the REAL runner source
#: is the mutation, because a synthetic reconstruction did NOT reproduce the
#: flag — measured while writing this test, and the reason the mutant is the
#: shipped function rather than a toy: `_writes_a_declared_value` is the
#: predicate that flips, and it flips on this function's own taint graph.
_REMOVED_FILTER = "\n             and _L7_FILE_KEYWORDS.search(_afn)"
_HANDOVER_TAIL = "             if isinstance(_atx, str) and _atx])"


def _l7_predicates(mod, source: str):
    """`(searches, writes_a_declared_value, consults_polarity)` for the real
    `gen_l7_test_debug` as it appears in ``source``."""
    import ast
    tree = ast.parse(source)
    al = mod._aliases(tree)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "gen_l7_test_debug")
    return (mod._searches_prose(fn), mod._writes_a_declared_value(fn),
            mod._consults_polarity(fn, al))


def test_reinstating_the_filter_makes_the_detector_flag_the_site_again():
    """THE FALSIFIER, driven through the real detector over the real function.

    Shipped: the site writes no match-derived value, so it is not an offender.
    Mutated — the removed filter line put back, one line, nothing else — the
    SAME predicate that ratchets the landing goes True. If this stops flipping,
    the cleanliness of the shipped site is no longer earned by anything and
    this test says so instead of passing quietly.
    """
    mod = _detector()
    runner = PROGRAMS / "phase1_doc_one_shot_runner.py"
    shipped = runner.read_text()
    assert shipped.count(_HANDOVER_TAIL) == 1
    mutant = shipped.replace(
        _HANDOVER_TAIL,
        _HANDOVER_TAIL[:-len("])")] + _REMOVED_FILTER + "])", 1)
    assert mutant != shipped

    s_search, s_writes, s_consults = _l7_predicates(mod, shipped)
    m_search, m_writes, m_consults = _l7_predicates(mod, mutant)

    # The discriminator is the WRITE, and it is named rather than folded into a
    # single boolean, so a future change to a different predicate cannot pass
    # this test by accident.
    assert s_writes is False, (
        "the shipped L7 site must write no match-derived value")
    assert m_writes is True, (
        "re-inserting the filter must make the detector see a search-gated "
        "write; if it does not, this test is not exercising the guard")
    assert (s_search, s_consults) == (m_search, m_consults)

    blind = lambda t: t[0] and t[1] and not t[2]      # `scan`'s own predicate
    assert blind((s_search, s_writes, s_consults)) is False
    assert blind((m_search, m_writes, m_consults)) is True


def test_the_shipped_l7_call_site_gates_the_corpus_on_no_regex():
    """And the shipped site is the NEW shape, read from the runner."""
    src = (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()
    block = src[src.index("import area_signoff_baseline as _asb"):]
    block = block[:block.index("content[_asb.L7_FIELD] = _area_block")]
    assert "_L7_FILE_KEYWORDS" not in block, (
        "the L7 sign-off block must hand over the corpus unfiltered; a "
        "filename regex here is the search-gated write the landing gate "
        "refused")
    assert "for_l7(" in block


def test_the_resolver_the_site_delegates_to_does_consult_polarity():
    """The other half: the question was not dropped, it MOVED to the reader,
    and it is not a call that can never fire."""
    src = PROG.read_text()
    assert "from _prose_polarity import is_denied" in src
    doc = L7_DOC.replace(
        "| stdcell area | **12,775 um^2** |",
        "| stdcell area | **12,775 um^2** -- this row is no longer used |")
    assert asb.resolve_texts([("d", doc)], [LIB_A])["baseline_um2"] is None


# ── chip-AGNOSTIC, asserted rather than promised ──────────────────────────
def test_the_program_names_no_process_or_vendor_token():
    src = PROG.read_text().lower()
    for tok in ("sky130", "gf180", "sg13g2", "ihp", "tsmc", "samsung",
                "globalfound", "intel", "umc", "smic"):
        assert tok not in src, f"{PROG.name} names {tok!r}"


# The validated run choice exists before the L19 producer has emitted its file.
@pytest.mark.parametrize("chosen,determined", [(PDK_A, True), (PDK_B, False)])
def test_selected_run_pdk_reaches_l7_before_l19(tmp_path, monkeypatch, chosen, determined):
    monkeypatch.setenv("PDK", PDK_A)
    monkeypatch.setenv("STD_CELL_LIBRARY", LIB_A)
    block = asb.for_l7(tmp_path, _docs(), pdk=chosen)
    assert not (tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").exists()
    assert block["run_technology"]["candidates"] == [chosen]
    assert block["run_technology"]["ambiguous"] is False
    assert block["run_technology"]["source"] == "caller::pdk"
    assert block["determined"] is determined
    assert block["threshold_um2"] == (16608.0 if determined else None)
    if not determined:
        assert block["baseline_um2"] is None
        assert block["power"]["determined"] is False


def _explicit_target(project, selected, claims=None):
    path = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    doc = json.loads(path.read_text())
    doc["extraction_evidence"] = {"command_line": (
        [{"label": "pdk_target (explicit run choice)",
          "literal": f"--pdk {selected}"}] if claims is None else claims)}
    path.write_text(json.dumps(doc))


def test_selected_l19_target_does_not_mix_available_alternatives(tmp_path):
    project = _project(tmp_path, {"pdk_target": PDK_B,
                                "pdk_target_alternates": [PDK_A, PDK_B]})
    _explicit_target(project, PDK_B)
    block = asb.for_l7(project, _docs())
    assert block["run_technology"]["candidates"] == [PDK_B]
    assert block["run_technology"]["ambiguous"] is False
    assert block["determined"] is False
    assert block["threshold_um2"] is None
    assert block["baseline_um2"] is None
    assert block["power"]["determined"] is False


@pytest.mark.parametrize("fault", ["wrong_target", "wrong_label", "duplicate", "conflicting", "malformed"])
def test_invalid_selected_pdk_evidence_cannot_erase_ambiguity(tmp_path, fault):
    project = _project(tmp_path, {"pdk_target": PDK_B,
                                "pdk_target_alternates": [PDK_A, PDK_B]})
    row = {"label": "pdk_target (explicit run choice)", "literal": f"--pdk {PDK_B}"}
    claims = [row]
    if fault == "wrong_target":
        claims = [dict(row, literal=f"--pdk {PDK_A}")]
    elif fault == "wrong_label":
        claims = [dict(row, label="document mention")]
    elif fault == "duplicate":
        claims = [row, row]
    elif fault == "conflicting":
        claims = [row, dict(row, literal=f"--pdk {PDK_A}")]
    elif fault == "malformed":
        claims = row
    _explicit_target(project, PDK_B, claims)
    block = asb.for_l7(project, _docs())
    assert block["run_technology"]["ambiguous"] is True
    assert block["determined"] is False
    assert block["threshold_um2"] is None


@pytest.mark.parametrize("measured", [False, True], ids=["declared_library", "measured_library"])
def test_selected_run_choice_preserves_conflicting_library_refusal(tmp_path, measured):
    project = _project(tmp_path, {"pdk_target": PDK_B,
                                "std_cell_library": LIB_A,
                                "pdk_target_alternates": [PDK_A, PDK_B]})
    _explicit_target(project, PDK_B)
    if measured:
        stats = project / "phase2/stage2/synth/stats.json"
        stats.parent.mkdir(parents=True)
        stats.write_text(json.dumps({"chip_area_unit_evidence": {
            "liberty": f"/pdk/{PDK_A}/libs.ref/{LIB_A}/lib/tt.lib"}}))
    block = asb.for_l7(project, _docs(), **({"pdk": PDK_B} if measured else {}))
    assert block["run_technology"]["ambiguous"] is True
    assert block["determined"] is False
    assert block["threshold_um2"] is None
    if measured:
        assert block["run_technology"]["source"] == "stats.json::chip_area_unit_evidence.liberty"
