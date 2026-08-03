"""A staged PDK must yield a NAME, or the flow must refuse to proceed.

WHAT WAS MEASURED
=================
On a real run `phase1/pdk_staging_read.json` recorded

    "staged_identifier": null
    "reason": "enablement files were read but no PDK identifier could be
               derived from their paths: neither the open-PDK token table
               nor the foundry-context rule ... matched"

after the extractor had read 27 staged enablement files. The flow could
STAGE a process it could not NAME. `declared_pdk_is_the_pdk_used_check`
reads exactly that record to learn what the design targets, so the null
propagated straight into the sign-off gate as an unanswerable question —
and a run with no library named in a log then exited rc=2 NOT CHECKED.

WHY THE OLD TIERS COULD NOT ANSWER
==================================
Both path tiers test the tokenised PATH against a CLOSED NAME LIST:
`_OPEN_PDK_TOKEN_RE` (open PDKs) or `_FOUNDRY_CTX_RE` (six commercial
foundries). A staged tree whose directory and file names carry neither
token yields nothing however completely it is staged. Widening the list
is one reactive entry per PDK encountered; the next PDK fails the same
way.

WHAT THIS PINS
==============
  A. the enablement's OWN header is a third evidence source, and it
     names a PDK no list contains;
  B. the derived value is a VERBATIM prefix of names the files declare —
     nothing is invented, and a set that agrees on nothing usable is
     REFUSED (the negative controls);
  C. the two path tiers are untouched: every identifier they could
     already produce is byte-identical, so the change can only turn a
     null into a value;
  D. an unnameable staged PDK is DISCLOSED as such and FAILS the
     sign-off gate instead of exiting rc=2 NOT CHECKED.

Chip-AGNOSTIC. The rules encode the Liberty grammar's `library` keyword
and a stop-list of words every PDK has. Every fixture name here is
synthetic; no vendor, foundry, SKU or part literal appears.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import declared_pdk_is_the_pdk_used_check as GATE   # noqa: E402
import phase1_doc_one_shot_runner as P1             # noqa: E402


def _lib(name: str, extra: str = "") -> str:
    """A minimal but structurally real Liberty header."""
    return (f"/* generated */\nlibrary ({name}) {{\n"
            f"  delay_model : table_lookup;\n{extra}}}\n")


def _stage(project: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = project / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return project


def _docs(project: Path, text: str) -> Path:
    d = project / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(text)
    return project


def _emit(project: Path) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        P1._emit_l19_to_l23_skeletons(project)
    return buf.getvalue()


def _disclosure(project: Path) -> dict:
    return json.loads(
        (project / "phase1" / P1.PDK_STAGING_READ_FILENAME).read_text())


# ── A. the enablement's own header names a PDK no list contains ───────────

def test_declared_library_header_names_an_unlisted_pdk(tmp_path):
    """THE ACCEPTANCE SHAPE. Paths carry no listed token; the headers do
    the naming, and the identifier is the family the corners share."""
    p = _docs(tmp_path, "# Core\nA 32-bit integer core. No process named.\n")
    _stage(p, {
        "input/pdk/liberty/stdcells_bci.lib": _lib("qh24fx090ul_bci"),
        "input/pdk/liberty/stdcells_typ.lib": _lib("qh24fx090ul_typ"),
        "input/pdk/liberty/stdcells_wci.lib": _lib("qh24fx090ul_wci"),
    })
    d = P1._staged_pdk_identifier_detail(p)
    assert d["identifier"] == "qh24fx090ul"
    assert d["kind"] == "declared_library_name"
    assert len(d["evidence"]) == 3
    assert d["source"] == "input/pdk/liberty/stdcells_bci.lib"


def test_the_premise_holds_the_old_tiers_really_cannot_answer(tmp_path):
    """Guard the premise: neither path tier can see this design at all,
    so the identifier below can only have come from the header."""
    p = _docs(tmp_path, "# Core\nA 32-bit integer core.\n")
    _stage(p, {"input/pdk/liberty/stdcells_typ.lib": _lib("qh24fx090ul_typ")})
    files = P1._staged_pdk_enablement_files(p)
    words = " ".join(P1._PATH_WORD_SPLIT_RE.sub(" ", f) for f in files)
    assert P1._OPEN_PDK_TOKEN_RE.search(words) is None
    assert not [m for m in P1._FOUNDRY_CTX_RE.finditer(words)
                if P1._foundry_match_trustworthy(
                    words[max(0, m.start() - 24):m.end()])]
    assert P1._staged_pdk_identifier(p)[0] == "qh24fx090ul_typ"


def test_it_reaches_l19_and_the_extractor_end_to_end(tmp_path):
    """The value has to arrive where the gate reads it, not just exist."""
    p = _docs(tmp_path, "# Core\nA 32-bit integer core.\n")
    _stage(p, {
        "input/pdk/liberty/a_typ.lib": _lib("qh24fx090ul_typ"),
        "input/pdk/liberty/b_wci.lib": _lib("qh24fx090ul_wci"),
    })
    tok, snippet, src, line = P1._extract_pdk_target_with_provenance(p)
    assert tok == "qh24fx090ul"
    assert src == "input/pdk/liberty/a_typ.lib"
    assert snippet == src           # a staged answer: the file is the evidence
    assert line is None             # ...and has no line in the prose sense


def test_a_single_declared_library_is_its_own_identifier(tmp_path):
    """One Liberty file is still a name. Nothing about the family rule
    requires more than one corner to be staged."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, {"input/pdk/lib/only.lib": _lib("bx31hp_sc9t")})
    assert P1._staged_pdk_identifier(p)[0] == "bx31hp_sc9t"


def test_a_lib_suffix_that_is_not_liberty_is_skipped_not_guessed(tmp_path):
    """SPICE model libraries are also named `.lib`. They declare no
    `library(...)` header, and the tier must not fall back to the
    FILENAME when the header is absent."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, {
        "input/pdk/spice/models_ff.lib": ".lib ff\n.param x=1\n.endl\n",
        "input/pdk/spice/models_ss.lib": ".lib ss\n.param x=2\n.endl\n",
        "input/pdk/liberty/cells_typ.lib": _lib("bx31hp_sc9t_typ"),
    })
    names = dict(P1._declared_library_names(
        p, P1._staged_pdk_enablement_files(p)))
    assert list(names) == ["input/pdk/liberty/cells_typ.lib"]
    # The SPICE files contributed nothing, so the one Liberty header is
    # the whole evidence and the identifier is that name verbatim — no
    # corner suffix is stripped on the strength of a single sample.
    assert P1._staged_pdk_identifier(p)[0] == "bx31hp_sc9t_typ"


def test_the_pdk_root_outranks_a_local_addition(tmp_path):
    """A design routinely stages one vendor hardmacro next to the PDK.
    Roots are consulted in sorted order, so `input/pdk` answers before
    `input/pdk_local` and a local IP never becomes the process."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, {
        "input/pdk/liberty/c_typ.lib": _lib("bx31hp_sc9t_typ"),
        "input/pdk/liberty/c_wci.lib": _lib("bx31hp_sc9t_wci"),
        "input/pdk_local/otp/o_ff.lib": _lib("zz0128x8ka_ff"),
        "input/pdk_local/otp/o_ss.lib": _lib("zz0128x8ka_ss"),
        "input/pdk_local/otp/o_tt.lib": _lib("zz0128x8ka_tt"),
    })
    d = P1._staged_pdk_identifier_detail(p)
    assert d["identifier"] == "bx31hp_sc9t"
    assert all(e["file"].startswith("input/pdk/") for e in d["evidence"])


def test_a_local_root_alone_still_yields_a_name(tmp_path):
    """When `input/pdk_local` is the ONLY staged root it is read: the
    rule is root ORDER, not a privileged directory name."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, {"input/pdk_local/sram/m.lib": _lib("qr45sram_2048x39")})
    assert P1._staged_pdk_identifier(p)[0] == "qr45sram_2048x39"


# ── B. NEGATIVE CONTROLS — nothing is invented ───────────────────────────

def test_no_liberty_header_anywhere_still_yields_nothing(tmp_path):
    """THE PRIMARY NEGATIVE CONTROL. A staged tree the tier cannot read
    must stay null. If this ever passes a name, the tier is guessing."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, {
        "input/pdk/spice/models.lib": ".lib tt\n.param x=1\n.endl\n",
        "input/pdk/lef/tech.lef": "VERSION 5.8 ;\nLAYER NW\n  TYPE MASTERSLICE ;\nEND NW\n",
        "input/pdk/magic/t.tech": "tech\n format 33\n scmos\nend\n",
    })
    d = P1._staged_pdk_identifier_detail(p)
    assert d["identifier"] is None and d["kind"] is None


def test_library_names_that_agree_on_nothing_are_refused(tmp_path):
    """Two unrelated families in ONE root, same file count. There is no
    honest answer, so there is no answer — a coin-flip between them
    would be the silent-wrong-value #457 exists to refuse."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, {
        "input/pdk/a1.lib": _lib("aa11xx_typ"),
        "input/pdk/b1.lib": _lib("bb22yy_typ"),
    })
    assert P1._library_family(["aa11xx_typ", "bb22yy_typ"]) == ""
    assert P1._staged_pdk_identifier(p)[0] is None


def test_a_generic_family_word_is_not_an_identifier(tmp_path):
    """"cells", "library", "tech" — every PDK on earth has them, so a
    family that collapses to one identifies no process."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, {
        "input/pdk/x.lib": _lib("cells_ff"),
        "input/pdk/y.lib": _lib("cells_ss"),
    })
    assert P1._library_family(["cells_ff", "cells_ss"]) == ""
    assert P1._staged_pdk_identifier(p)[0] is None


@pytest.mark.parametrize("names,why", [
    (["4501_ff", "4501_ss"], "a bare number names a date or a rev, not a process"),
    (["a_ff", "a_ss"], "a family below the minimum length identifies nothing"),
])
def test_families_without_identity_are_refused(names, why):
    assert P1._library_family(names) == "", why


def test_the_family_is_a_verbatim_prefix_of_what_was_read(tmp_path):
    """THE ANTI-INVENTION INVARIANT. Whatever comes out must appear,
    character for character, at the start of a name the files declare."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, {
        "input/pdk/liberty/p_bci.lib": _lib("qh24fx090ul_bci"),
        "input/pdk/liberty/p_typ.lib": _lib("qh24fx090ul_typ"),
    })
    d = P1._staged_pdk_identifier_detail(p)
    assert d["identifier"]
    assert all(e["declared_library"].startswith(d["identifier"])
               for e in d["evidence"])
    for e in d["evidence"]:
        assert e["declared_library"] in (p / e["file"]).read_text()


def test_the_family_is_stable_when_more_corners_are_staged(tmp_path):
    """STABILITY. Adding another corner of the same library must not move
    the identifier — a character-wise common prefix would have."""
    base = {"input/pdk/liberty/p_typ.lib": _lib("qh24fx090ul_typ")}
    p1 = _stage(_docs(tmp_path / "a", "# B\nx\n"), dict(base))
    p2 = _stage(_docs(tmp_path / "b", "# B\nx\n"), dict(
        base, **{"input/pdk/liberty/p_wci.lib": _lib("qh24fx090ul_wcix"),
                 "input/pdk/liberty/p_bci.lib": _lib("qh24fx090ul_bci")}))
    assert P1._staged_pdk_identifier(p2)[0] == "qh24fx090ul"
    assert P1._staged_pdk_identifier(p1)[0].startswith("qh24fx090ul")


def test_derivation_is_deterministic(tmp_path):
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, {
        "input/pdk/liberty/z_wci.lib": _lib("qh24fx090ul_wci"),
        "input/pdk/liberty/a_typ.lib": _lib("qh24fx090ul_typ"),
    })
    first = P1._staged_pdk_identifier_detail(p)
    for _ in range(3):
        assert P1._staged_pdk_identifier_detail(p) == first


# ── C. the path tiers are untouched ──────────────────────────────────────

def test_path_token_still_wins_and_is_labelled_as_such(tmp_path):
    """A design the old tiers could already answer keeps that answer."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, {"input/pdk/liberty/sky130_fd_sc_hd__tt_025C_1v80.lib":
               _lib("sky130_fd_sc_hd__tt_025C_1v80")})
    d = P1._staged_pdk_identifier_detail(p)
    assert d["identifier"] == "sky130"          # the PATH token, not the header
    assert d["kind"] == "path_token"


def test_prose_still_wins_over_a_declared_header(tmp_path):
    """ORDERING CONTRACT, unchanged: the staged read is a fallback."""
    p = _docs(tmp_path, "Implemented on sky130A with the HD cells.\n")
    _stage(p, {"input/pdk/liberty/c.lib": _lib("qh24fx090ul_typ")})
    tok, _snip, src, _line = P1._extract_pdk_target_with_provenance(p)
    assert tok == "sky130a"
    assert src.endswith("spec.md")


def test_a_design_that_stages_nothing_keeps_its_honest_null(tmp_path):
    p = _docs(tmp_path, "# Adder\nA 32-bit ripple-carry adder.\n")
    assert P1._extract_pdk_target_with_provenance(p) == (None, None, None, None)
    _emit(p)
    assert not (p / "phase1" / P1.PDK_STAGING_READ_FILENAME).exists()


# ── D. an unnameable staged PDK is disclosed, and it FAILS ───────────────

def test_disclosure_records_the_tier_and_its_evidence(tmp_path):
    p = _docs(tmp_path, "# Core\nA 32-bit integer core.\n")
    _stage(p, {
        "input/pdk/liberty/p_typ.lib": _lib("qh24fx090ul_typ"),
        "input/pdk/liberty/p_wci.lib": _lib("qh24fx090ul_wci"),
    })
    _emit(p)
    rec = _disclosure(p)
    assert rec["staged_identifier"] == "qh24fx090ul"
    assert rec["staged_identifier_kind"] == "declared_library_name"
    assert rec["staged_pdk_unnameable"] is False
    assert {e["declared_library"] for e in rec["staged_identifier_evidence"]} \
        == {"qh24fx090ul_typ", "qh24fx090ul_wci"}


def test_an_unnameable_staged_pdk_says_so_and_shows_its_work(tmp_path):
    p = _docs(tmp_path, "# Core\nA 32-bit integer core.\n")
    _stage(p, {"input/pdk/spice/models.lib": ".lib tt\n.param x=1\n.endl\n"})
    log = _emit(p)
    rec = _disclosure(p)
    assert rec["staged_identifier"] is None
    assert rec["staged_pdk_unnameable"] is True
    assert rec["declared_library_names"] == []
    assert "CANNOT BE NAMED" in rec["reason"]
    assert "staged PDK enablement read but no identifier" in log


def test_a_capped_scan_says_so(tmp_path):
    """A refusal produced by a CAP is not a statement about the PDK.
    Measured on a real 15433-entry staged tree, the glob cap hid 11 of 62
    enablement files; the record must not leave the two indistinguishable."""
    p = _docs(tmp_path, "# Core\nA 32-bit integer core.\n")
    _stage(p, {"input/pdk/spice/models.lib": ".lib tt\n.endl\n"})
    assert P1._staged_pdk_scan_truncated(p) is False
    _emit(p)
    assert _disclosure(p)["enablement_scan_truncated"] is False

    big = _docs(tmp_path / "big", "# Core\nA 32-bit integer core.\n")
    over = P1._STAGED_PDK_MAX_FILES + 1
    _stage(big, {f"input/pdk/lib/c{i:04d}.lib": ".lib tt\n.endl\n"
                 for i in range(over)})
    assert P1._staged_pdk_scan_truncated(big) is True
    _emit(big)
    rec = _disclosure(big)
    assert rec["enablement_scan_truncated"] is True
    assert rec["staged_pdk_unnameable"] is True
    assert "artefact of the cap" in rec["reason"]


def test_the_gate_fails_an_unnameable_staged_pdk_instead_of_skipping(tmp_path):
    """THE REFUSAL. Before: no declared target and no library named in a
    log gave rc=2 NOT CHECKED — the condition that makes the question
    unanswerable also excused the answer."""
    run = tmp_path / "run"
    (run / "input" / "pdk").mkdir(parents=True)
    (run / "input" / "pdk" / "models.lib").write_text(".lib tt\n.endl\n")
    (run / "phase1").mkdir(parents=True)
    (run / "phase1" / "pdk_staging_read.json").write_text(json.dumps({
        "staged_identifier": None, "adopted_pdk_target": None,
        "staged_pdk_unnameable": True}))
    report = tmp_path / "gate.json"
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        rc = GATE.main([str(run), "--json", str(report)])
    assert rc == 1, buf.getvalue()
    rep = json.loads(report.read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["unnameable_staged_pdk"] is True
    assert "could not name" in rep["reason"]


def test_the_gate_still_reports_not_checked_when_nothing_was_staged(tmp_path):
    """rc=2 survives for the case it was written for: no target, no
    library loaded, and nothing staged that the flow failed to name."""
    run = tmp_path / "run"
    run.mkdir()
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        rc = GATE.main([str(run)])
    assert rc == 2, buf.getvalue()


def test_the_gate_can_now_answer_using_the_derived_identifier(tmp_path):
    """The point of naming it: the gate compares a real target against
    the libraries the tools loaded, instead of declining the question."""
    run = tmp_path / "run"
    (run / "input" / "pdk").mkdir(parents=True)
    (run / "input" / "pdk" / "c.lib").write_text(_lib("qh24fx090ul_typ"))
    (run / "phase1").mkdir(parents=True)
    (run / "phase1" / "pdk_staging_read.json").write_text(json.dumps({
        "staged_identifier": "qh24fx090ul", "adopted_pdk_target": None,
        "staged_pdk_unnameable": False}))
    (run / "logs").mkdir()
    (run / "logs" / "pnr.log").write_text(
        "reading /opt/pdk/qh24fx090ul_typ.lib\n"
        "reading /opt/pdk/qh24fx090ul_macro.lef\n")
    report = tmp_path / "gate.json"
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        rc = GATE.main([str(run), "--json", str(report)])
    assert rc == 0, buf.getvalue()
    rep = json.loads(report.read_text())
    assert rep["verdict"] == "PASS"
    assert rep["declared_target"] == "qh24fx090ul"
    assert rep["matching_libraries"]


def test_a_run_without_the_field_is_judged_on_the_evidence_it_has(tmp_path):
    """Backwards compatible: a record written before the field existed
    must not be read as a refusal."""
    run = tmp_path / "run"
    (run / "phase1").mkdir(parents=True)
    (run / "phase1" / "pdk_staging_read.json").write_text(json.dumps({
        "staged_identifier": None, "adopted_pdk_target": None}))
    assert GATE.unnameable_staged_pdk(run) is False
