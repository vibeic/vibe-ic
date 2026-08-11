"""tests/test_input_doc_pdk_claim_vs_installed_pdk.py

A design-input document asserted, as a fact, that its PDK ships no ngspice
corner library, and mandated that every corner result disclose a hand-written
standin in consequence. The installed PDK shipped sectioned corner libraries
for every device class. Nothing in the flow noticed, because the false claim
UNDERSTATED — it labelled real foundry sections as approximations — and every
honesty gate here watches the overstating direction.

These tests pin the gate that decides such claims against the installed tree.
Every fixture PDK is SYNTHETIC: invented family names, invented device classes,
invented section names. That is not squeamishness about naming a real PDK — it
is the load-bearing property under test. A gate that passed these fixtures by
recognising a real foundry's library names would fail them, because none of
these names exist anywhere but in this file.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_PROGRAMS = _HERE.parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import input_doc_pdk_claim_vs_installed_pdk_check as gate  # noqa: E402


# ── fixture builders ───────────────────────────────────────────────────────

def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def sectioned_pdk(root: Path, family: str = "alphanode") -> Path:
    """An installed PDK that DOES ship sectioned corner libraries.

    Both the device classes (`Blk`, `Rsr`) and the section names (`grade_nom`,
    `grade_low`, ...) are invented. If the gate can report this tree's corner
    vocabulary, it read the tree.
    """
    models = root / family / "libs.tech" / "ngspice" / "models"
    _write(models / "cornerBlk.lib",
           ".lib grade_nom\n.include blk.mod\n.endl\n"
           ".lib grade_low\n.include blk.mod\n.endl\n"
           ".lib grade_high\n.include blk.mod\n.endl\n")
    _write(models / "cornerRsr.lib",
           ".lib rsr_nom\n.endl\n.lib rsr_wide\n.endl\n")
    _write(models / "devices_blk.lib", ".subckt blk_a d g s b\n.ends\n")
    return root


def bare_pdk(root: Path, family: str = "alphanode") -> Path:
    """An installed PDK that genuinely ships NO corner library — the same
    family name, so only the tree's contents can tell the two apart."""
    models = root / family / "libs.tech" / "ngspice" / "models"
    _write(models / "devices_blk.lib", ".subckt blk_a d g s b\n.ends\n")
    return root


ABSENCE_DOC = (
    "# Constraints\n"
    "\n"
    "- AlphaNode has **no public ngspice corner lib** -> corner sims use\n"
    "  documented LEVEL=1 standin models (modeled, not silicon sign-off).\n"
    "  Must be stated in every corner result.\n"
)


def project_with(tree: Path, doc_body: str,
                 rel: str = "input/docs/L9_CONSTRAINTS.md") -> Path:
    _write(tree / rel, doc_body)
    return tree


def run_gate(tree: Path, pdks_root: Path) -> dict:
    return gate.run(Path(tree), str(pdks_root))


# ── the defect this gate exists for ────────────────────────────────────────

def test_false_absence_claim_is_contradicted_by_the_installed_tree(tmp_path):
    """The #904 shape: the document denies an artefact the image ships."""
    pdks = sectioned_pdk(tmp_path / "pdks")
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    rep = run_gate(tree, pdks)

    assert rep["verdict"] == "FAIL", rep
    assert rep["counts"]["contradicted"] == 1, rep["counts"]
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CONTRADICTED"]
    # names the document, the line, the claim and the contradicting artefact
    assert claim["document"] == "input/docs/L9_CONSTRAINTS.md"
    assert claim["line"] == 3
    assert "no public ngspice corner lib" in claim["claim"]
    assert any(p.endswith("cornerBlk.lib") for p in claim["evidence"]), claim
    assert any(p.endswith("cornerRsr.lib") for p in claim["evidence"]), claim


def test_contradiction_reports_the_section_vocabulary_it_scraped(tmp_path):
    """The corner vocabulary in the report is READ from the tree.

    These section names exist in no PDK on earth. A gate carrying a typed list
    of section names could not produce them, which is the point: the list is a
    promise that no PDK will ever name one differently.
    """
    pdks = sectioned_pdk(tmp_path / "pdks")
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    rep = run_gate(tree, pdks)

    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CONTRADICTED"]
    found = set()
    for names in claim["sections_discovered"].values():
        found.update(names)
    assert {"grade_nom", "grade_low", "grade_high"} <= found, found
    assert {"rsr_nom", "rsr_wide"} <= found, found


def test_the_installed_tree_decides_not_a_table_in_the_gate(tmp_path):
    """Same document, same PDK NAME, two different installed trees.

    This is the property the issue is about. The claim was false because of
    what was on disk, and a gate that answered from a table of what PDKs
    contain would be a second copy of the same unverified claim. Change the
    image, change the answer.
    """
    doc = ABSENCE_DOC
    rich = run_gate(project_with(tmp_path / "a", doc),
                    sectioned_pdk(tmp_path / "pdks_rich"))
    bare = run_gate(project_with(tmp_path / "b", doc),
                    bare_pdk(tmp_path / "pdks_bare"))

    assert rich["verdict"] == "FAIL", rich
    assert bare["verdict"] == "PASS", bare
    assert bare["counts"]["corroborated"] == 1, bare["counts"]


# ── PAIRED GUARD: a true claim must stay green ─────────────────────────────

def test_true_absence_claim_stays_green(tmp_path):
    """A document telling the truth about the installed PDK is not a finding."""
    pdks = bare_pdk(tmp_path / "pdks")
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    rep = run_gate(tree, pdks)

    assert rep["verdict"] == "PASS", rep
    assert rep["counts"]["contradicted"] == 0
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CORROBORATED"]
    assert claim["evidence_count"] == 0


def test_true_exclusivity_claim_stays_green(tmp_path):
    """"ships only <x>" is true when the tree holds exactly that one."""
    pdks = tmp_path / "pdks"
    _write(pdks / "betanode" / "libs.ref" / "cells" / "lib"
           / "BetaNodeCells_typical.lib", "library (BetaNodeCells) { }\n")
    tree = project_with(
        tmp_path / "proj",
        "| Corner | BetaNode ships only the typical corner lib "
        "(BetaNodeCells_typical.lib) - single-corner sign-off, declared |\n")

    rep = run_gate(tree, pdks)

    assert rep["verdict"] == "PASS", rep
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CORROBORATED"]
    assert claim["evidence"][0].endswith("BetaNodeCells_typical.lib")


def test_exclusivity_claim_is_contradicted_by_an_unnamed_sibling_variant(tmp_path):
    """"only typical" is false once the tree ships a sibling the claim omits.

    The family is detected structurally — stems sharing every token but the
    last — so the gate never needs to know that `slow` names a corner.
    """
    pdks = tmp_path / "pdks"
    libdir = pdks / "betanode" / "libs.ref" / "cells" / "lib"
    _write(libdir / "BetaNodeCells_typical.lib", "library (t) { }\n")
    _write(libdir / "BetaNodeCells_slow.lib", "library (s) { }\n")
    tree = project_with(
        tmp_path / "proj",
        "| Corner | BetaNode ships only the typical corner lib "
        "(BetaNodeCells_typical.lib) - single-corner sign-off, declared |\n")

    rep = run_gate(tree, pdks)

    assert rep["verdict"] == "FAIL", rep
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CONTRADICTED"]
    assert claim["evidence"] == [str(libdir / "BetaNodeCells_slow.lib")], claim
    assert "slow" in claim["reason"]


# ── PAIRED GUARD: quiet trees must stay quiet ──────────────────────────────

def test_tree_with_no_input_documents_is_not_applicable(tmp_path):
    pdks = sectioned_pdk(tmp_path / "pdks")
    (tmp_path / "proj").mkdir()

    rep = run_gate(tmp_path / "proj", pdks)

    assert rep["verdict"] == "NOT_APPLICABLE"
    assert rep["reason"] == "no_input_documents"


def test_input_documents_making_no_pdk_claim_are_not_turned_red(tmp_path):
    """A gate is only worth having if it can also be quiet."""
    pdks = sectioned_pdk(tmp_path / "pdks")
    tree = project_with(
        tmp_path / "proj",
        "# Constraints\n\n- Target clock period 10 ns.\n"
        "- Multi-corner sign-off required at every process corner.\n"
        "- Core utilisation 45%.\n")

    rep = run_gate(tree, pdks)

    assert rep["verdict"] == "NOT_APPLICABLE", rep
    assert rep["reason"] == "no_decidable_pdk_claim"
    assert rep["claims"] == []


def test_a_requirement_is_not_an_assertion_about_the_pdk(tmp_path):
    """"must sign off at every corner" names a corner vocabulary and asserts
    nothing about what the PDK ships. It carries no quantifier, so it is never
    a candidate — not an UNDECIDED, not a claim at all."""
    pdks = sectioned_pdk(tmp_path / "pdks")
    tree = project_with(
        tmp_path / "proj",
        "- AlphaNode sign-off must cover every process corner and temperature."
        "\n")

    rep = run_gate(tree, pdks)

    assert rep["claims"] == [], rep["claims"]


# ── silence must never read as agreement ───────────────────────────────────

def test_unreadable_installed_pdk_root_is_not_a_pass(tmp_path):
    """No image mounted means nothing was checked — not that all is well."""
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    rep = run_gate(tree, tmp_path / "does_not_exist")

    assert rep["verdict"] == "NOT_APPLICABLE", rep
    assert rep["reason"] == "installed_pdk_root_unreadable"
    assert rep["counts"]["corroborated"] == 0


def test_claim_about_an_uninstalled_pdk_is_silence_not_agreement(tmp_path):
    """A PDK the image does not carry cannot corroborate anything."""
    pdks = sectioned_pdk(tmp_path / "pdks", family="alphanode")
    tree = project_with(
        tmp_path / "proj",
        "- GammaNode has no public ngspice corner lib -> standin models.\n")

    rep = run_gate(tree, pdks)

    assert rep["counts"]["corroborated"] == 0, rep
    assert rep["counts"]["contradicted"] == 0, rep
    assert rep["verdict"] == "NOT_APPLICABLE"


def test_adjacent_clause_does_not_manufacture_a_contradiction(tmp_path):
    """A true denial must not be contradicted by a noun in the next clause.

    Measured on a real document on this gate's first run: "<PDK> has no LVS
    deck -> waive; structural CDL check optional" was reported as contradicted
    by a `.cdl` file, because the whole line was read as the denial's subject
    matter. The quantifier governs its neighbourhood, not its table row.
    """
    pdks = tmp_path / "pdks"
    _write(pdks / "alphanode" / "libs.tech" / "cdl" / "AlphaCells.cdl",
           "* netlist\n")
    tree = project_with(
        tmp_path / "proj",
        "| LVS | AlphaNode has **no LVS deck** (lvs_deck=null) -> waived "
        "honestly; a structural CDL check is optional |\n")

    rep = run_gate(tree, pdks)

    assert rep["counts"]["contradicted"] == 0, rep["claims"]


def test_a_bare_denial_of_a_whole_format_is_undecided(tmp_path):
    """A denial with no word saying WHICH artefacts it denies is refused.

    "ships no lib" denies some file of a format, and a listing cannot settle
    that. The gate's first run answered such a claim by matching every file of
    the format, which is how a true statement about a staged macro came back
    contradicted by an unrelated standard-cell file.
    """
    pdks = sectioned_pdk(tmp_path / "pdks")
    tree = project_with(tmp_path / "proj", "- AlphaNode ships no lib.\n")

    rep = run_gate(tree, pdks)

    assert rep["counts"]["contradicted"] == 0, rep["claims"]
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "UNDECIDED"]
    assert "cannot localise" in claim["reason"], claim


def test_the_denied_word_must_be_adjacent_to_the_format_word(tmp_path):
    """Measured on a real bilingual document: the nearest Latin token to the
    format word sat a whole clause away, and reading it as the modifier turned
    a true statement about a staged macro into a claim about the PDK. The
    modifier is required to be adjacent in characters, not merely nearest."""
    pdks = tmp_path / "pdks"
    _write(pdks / "alphanode" / "libs.ref" / "cells" / "gds"
           / "AlphaCells.gds", "\x00gds\n")
    tree = project_with(
        tmp_path / "proj",
        "| note | staged macro on the AlphaNode platform is a standard "
        "placeholder):無真實電晶體 GDS、無 compiler 簽核 |\n")

    rep = run_gate(tree, pdks)

    assert rep["counts"]["contradicted"] == 0, rep["claims"]
    assert all(c["verdict"] == "UNDECIDED" for c in rep["claims"]), rep["claims"]


def test_undecided_is_never_counted_as_agreement(tmp_path):
    """A run whose every claim is UNDECIDED is vacuous, not a pass."""
    pdks = sectioned_pdk(tmp_path / "pdks")
    tree = project_with(
        tmp_path / "proj",
        "- AlphaNode ships no widget of any kind worth naming here.\n")

    rep = run_gate(tree, pdks)

    assert rep["verdict"] == "NOT_APPLICABLE", rep
    assert rep["counts"]["corroborated"] == 0


# ── exit-code contract (vibe-ic#901: rc 0 must not read as a quiet pass) ───

def _cli(tree: Path, pdks: Path, tmp_path: Path):
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable,
         str(_PROGRAMS / "input_doc_pdk_claim_vs_installed_pdk_check.py"),
         str(tree), "--pdks-root", str(pdks), "--json", str(out)],
        # 60s = the ci_harness_timeout_ceiling ceiling (180s harness bound / 3).
        # This file landed at 120s in #949 and put the gate over its ceiling on
        # the very day it was wired. Measured 2026-08-11: the whole file runs in
        # 0.68s.
        capture_output=True, text=True, timeout=60)
    return proc, json.loads(out.read_text())


@pytest.mark.parametrize("build,verdict,rc", [
    ("contradicted", "FAIL", 1),
    ("corroborated", "PASS", 0),
    ("vacuous", "NOT_APPLICABLE", 2),
])
def test_exit_code_is_routed_from_the_gates_own_verdict(tmp_path, build,
                                                        verdict, rc):
    tree = tmp_path / "proj"
    if build == "contradicted":
        pdks = sectioned_pdk(tmp_path / "pdks")
        project_with(tree, ABSENCE_DOC)
    elif build == "corroborated":
        pdks = bare_pdk(tmp_path / "pdks")
        project_with(tree, ABSENCE_DOC)
    else:
        pdks = sectioned_pdk(tmp_path / "pdks")
        tree.mkdir()

    proc, rep = _cli(tree, pdks, tmp_path)

    assert rep["verdict"] == verdict, rep
    assert proc.returncode == rc, (proc.returncode, proc.stdout, proc.stderr)


def test_vacuous_run_emits_the_sentinel_the_consumer_actually_reads(tmp_path):
    """vibe-ic#901: six gates disclose NOT_APPLICABLE in JSON the consumer
    never parses and exit 0, so an empty tree certifies as a pass. This gate
    exits 2 AND emits the `VACUOUS_PASS:` token the consumer matches at line
    start, so neither channel can be the only one."""
    pdks = sectioned_pdk(tmp_path / "pdks")
    tree = tmp_path / "proj"
    tree.mkdir()

    proc, rep = _cli(tree, pdks, tmp_path)

    assert proc.returncode == 2
    combined = proc.stdout + proc.stderr
    assert any(ln.startswith("VACUOUS_PASS")
               for ln in combined.splitlines()), combined
    assert rep["verdict"] == "NOT_APPLICABLE"


def test_report_states_what_it_cannot_decide(tmp_path):
    """The gate is required to be honest about its own boundary in the same
    document that carries its verdict."""
    pdks = sectioned_pdk(tmp_path / "pdks")
    rep = run_gate(project_with(tmp_path / "proj", ABSENCE_DOC), pdks)

    assert rep["decides"]
    assert len(rep["does_not_decide"]) >= 3
    assert any("not installed" in s for s in rep["does_not_decide"])


# ── the discovery contract ─────────────────────────────────────────────────

def test_installed_pdk_list_comes_from_the_directory_listing(tmp_path):
    pdks = tmp_path / "pdks"
    sectioned_pdk(pdks, family="alphanode")
    sectioned_pdk(pdks, family="deltanode")
    (pdks / "versions.txt").write_text("x\n")

    rep = run_gate(project_with(tmp_path / "proj", ABSENCE_DOC), pdks)

    assert rep["installed_pdks"] == ["alphanode", "deltanode"], rep


# ── #964: a PDK installed as a SYMLINK is part of the population ───────────
#
# The container backend listed with `ls -1p`, and `-p` appends the trailing
# slash to REAL directories only; `discover_installed_pdks` keeps an entry only
# if it carries that slash. An image that installs a PDK as a link into a
# versioned package store therefore had that PDK outside the population — and a
# claim about it was dropped at extraction, so it got neither a decision nor the
# UNDECIDED the report's own `does_not_decide` promises.
#
# These exercise the container backend's REAL command strings against a REAL
# symlink by running them in a local shell instead of `docker exec`. No
# container is needed and no command string is asserted on: what is tested is
# whether the commands can SEE a link.


def _shell_backends(monkeypatch):
    """The gate's own container backend, with `docker exec` swapped for a
    local shell. Same commands, same parsing, a tree the test can build."""
    real_run = subprocess.run

    def fake_run(cmd, **kw):
        assert cmd[:2] == ["docker", "exec"], cmd
        return real_run(["bash", "-lc", cmd[-1]], **kw)

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    return gate.docker_backends("container-name-is-never-used")


def _linked_pdk(tmp_path: Path, family: str = "gammanode") -> Path:
    """A pdks root whose PDK is a LINK into a store outside that root."""
    store = tmp_path / "store"
    sectioned_pdk(store, family=f"{family}-1.0")
    pdks = tmp_path / "pdks"
    pdks.mkdir(parents=True, exist_ok=True)
    sectioned_pdk(pdks, family="alphanode")
    (pdks / family).symlink_to(store / f"{family}-1.0")
    return pdks


def test_a_pdk_installed_as_a_symlink_is_in_the_population(tmp_path, monkeypatch):
    """#964: the listing must dereference, or the PDK is silently not there."""
    pdks = _linked_pdk(tmp_path)
    lister, reader, walker = _shell_backends(monkeypatch)

    rep = gate.run(project_with(tmp_path / "proj", ABSENCE_DOC), str(pdks),
                   lister=lister, reader=reader, walker=walker)

    assert rep["installed_pdks"] == ["alphanode", "gammanode"], rep


def test_a_true_claim_about_a_symlinked_pdk_is_still_corroborated(
        tmp_path, monkeypatch):
    """PAIRED GUARD for #964: bringing the link into the population must let
    the gate DECIDE it, not merely count it. A population that grows but
    answers nothing is a ban dressed as a fix."""
    pdks = tmp_path / "pdks"
    pdks.mkdir(parents=True)
    bare_pdk(tmp_path / "store", family="gammanode-1.0")
    (pdks / "gammanode").symlink_to(tmp_path / "store" / "gammanode-1.0")
    tree = project_with(
        tmp_path / "proj",
        "- GammaNode has no public ngspice corner lib -> standin models.\n")
    lister, reader, walker = _shell_backends(monkeypatch)

    rep = gate.run(tree, str(pdks), lister=lister, reader=reader, walker=walker)

    assert rep["installed_pdks"] == ["gammanode"], rep
    assert rep["verdict"] == "PASS", rep
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CORROBORATED"]
    assert claim["subject_pdk"] == "gammanode"


def test_a_false_claim_about_a_symlinked_pdk_is_contradicted(tmp_path,
                                                             monkeypatch):
    """The population fix is only worth having if the walk follows too: the
    bulk walker has to open a start path that is itself a link."""
    pdks = _linked_pdk(tmp_path)
    tree = project_with(
        tmp_path / "proj",
        "- GammaNode has no public ngspice corner lib -> standin models.\n")
    lister, reader, walker = _shell_backends(monkeypatch)

    rep = gate.run(tree, str(pdks), lister=lister, reader=reader, walker=walker)

    assert rep["verdict"] == "FAIL", rep
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CONTRADICTED"]
    assert claim["subject_pdk"] == "gammanode"
    assert any(p.endswith("cornerBlk.lib") for p in claim["evidence"]), claim


def test_a_symlinked_subdirectory_inside_a_pdk_is_walked(tmp_path):
    """Same defect one level down, on the LOCAL backend: an image that links
    only part of a PDK into a store left the walk stopping at the link, so a
    fully installed PDK read as empty — which this gate reports as unreadable,
    i.e. silence, not a decision."""
    pdks = tmp_path / "pdks"
    _write(pdks / "alphanode" / "libs.tech" / "placeholder.txt", "x\n")
    store = tmp_path / "store" / "models"
    _write(store / "cornerBlk.lib", ".lib grade_nom\n.endl\n")
    (pdks / "alphanode" / "libs.tech" / "ngspice").symlink_to(store)
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    rep = run_gate(tree, pdks)

    assert rep["verdict"] == "FAIL", rep
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CONTRADICTED"]
    assert any(p.endswith("cornerBlk.lib") for p in claim["evidence"]), claim


def test_the_walk_terminates_when_a_link_points_back_up_the_tree(tmp_path):
    """Following links can cycle; the walk must still return."""
    pdks = tmp_path / "pdks"
    models = pdks / "alphanode" / "libs.tech" / "ngspice" / "models"
    _write(models / "cornerBlk.lib", ".lib grade_nom\n.endl\n")
    (models / "loop").symlink_to(pdks / "alphanode")

    found = gate._local_walker(str(pdks / "alphanode"))

    assert any(p.endswith("cornerBlk.lib") for p in found), found


# ── #965: a lookup that cannot settle a claim must not settle it ───────────


def test_a_denied_word_hidden_in_an_uppercase_run_is_found(tmp_path):
    """#965: the denied word sat inside an uppercase run of a file stem.

    `tokens()` splits camelCase at a lower/digit -> upper boundary only, so a
    stem like `<word><RUN><tail>` yielded `<word>` + `<run><tail>` and the run
    on its own was never a token. The lookup missed, and the miss fell straight
    through to CORROBORATED — the gate AGREED with a false claim about the very
    files it cites as evidence under a differently-worded one.

    The fix is a rule about letter case, not a case for this tree: wherever an
    uppercase run abuts a lowercase run, both readings of the boundary count.
    """
    pdks = tmp_path / "pdks"
    models = pdks / "alphanode" / "libs.tech" / "ngspice" / "models"
    _write(models / "cornerBLKhv.lib", ".lib grade_nom\n.endl\n")
    _write(models / "cornerBLKlv.lib", ".lib grade_low\n.endl\n")
    tree = project_with(
        tmp_path / "proj",
        "- AlphaNode has no public ngspice blk lib -> standin models.\n")

    rep = run_gate(tree, pdks)

    assert rep["verdict"] == "FAIL", rep
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CONTRADICTED"]
    assert claim["denied_artefact"] == ["blk"], claim
    assert sorted(Path(p).name for p in claim["evidence"]) == [
        "cornerBLKhv.lib", "cornerBLKlv.lib"], claim


def test_both_readings_of_an_uppercase_run_boundary_are_emitted(tmp_path):
    """The boundary is genuinely ambiguous without a lexicon — `ABChv` is
    `abc`+`hv`, `ABCDef` is `abc`+`def` — so the lookup keeps both readings
    instead of guessing. `tokens()` keeps its single ordered reading, because
    sibling-family detection reads token POSITIONS."""
    assert {"abc", "hv"} <= gate.lookup_tokens("wordABChv")
    assert {"abc", "def"} <= gate.lookup_tokens("ABCDef")
    assert gate.tokens("wordABChv") == ["word", "abchv"]


def test_a_qualifier_naming_a_directory_without_that_format_is_undecided(
        tmp_path):
    """#965, second instance: the claim names a directory, that directory is
    real and holds nothing of the claimed format, and the gate answered from
    the files of that format sitting somewhere else entirely — in the
    affirmative. Answering a different question is a refusal, not agreement."""
    pdks = tmp_path / "pdks"
    _write(pdks / "betanode" / "libs.ref" / "cells" / "lib"
           / "BetaCells_typical.lib", "library (t) { }\n")
    _write(pdks / "betanode" / "libs.tech" / "ngspice" / "models"
           / "devices_blk.spice", "* models\n")
    tree = project_with(
        tmp_path / "proj",
        "- BetaNode has no public ngspice corner lib -> standin models.\n")

    rep = run_gate(tree, pdks)

    assert rep["counts"]["corroborated"] == 0, rep["claims"]
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "UNDECIDED"]
    assert "ngspice" in claim["directory_qualifiers"], claim
    assert "holds no artefact of format" in claim["reason"], claim
    assert rep["verdict"] == "NOT_APPLICABLE", rep


def test_that_refusal_is_not_printed_as_a_pass(tmp_path):
    """The exit-code half of #965. CORROBORATED is the only route to a
    substantive rc 0, so tightening it has to be checked at the exit code or
    the tightening is decorative. A run whose only claim is now refused must
    exit 2 with the sentinel, never 0."""
    pdks = tmp_path / "pdks"
    _write(pdks / "betanode" / "libs.ref" / "cells" / "lib"
           / "BetaCells_typical.lib", "library (t) { }\n")
    _write(pdks / "betanode" / "libs.tech" / "ngspice" / "models"
           / "devices_blk.spice", "* models\n")
    tree = project_with(
        tmp_path / "proj",
        "- BetaNode has no public ngspice corner lib -> standin models.\n")

    proc, rep = _cli(tree, pdks, tmp_path)

    assert rep["verdict"] == "NOT_APPLICABLE", rep
    assert rep["reason"] == "all_claims_undecided", rep
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    combined = proc.stdout + proc.stderr
    assert any(ln.startswith("VACUOUS_PASS") for ln in combined.splitlines())


def test_a_true_denial_about_a_directory_that_holds_the_format_still_passes(
        tmp_path):
    """PAIRED GUARD for #965, and the one that decides whether this is a fix
    or a ban. The claim is TRUE, the directory it names is real AND holds files
    of the claimed format, and none of them carries the denied word under any
    reading. That is positive evidence, so it must still be CORROBORATED and
    still rc 0. A gate that only ever says no is not a check."""
    pdks = bare_pdk(tmp_path / "pdks")
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    proc, rep = _cli(tree, pdks, tmp_path)

    assert rep["verdict"] == "PASS", rep
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CORROBORATED"]
    assert "ngspice" in claim["directory_qualifiers"], claim
    assert "under" in claim["reason"] and "ngspice" in claim["reason"], claim
    assert claim["examined_count"] >= 1, claim
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)


def test_the_report_says_it_refuses_a_denial_about_an_empty_directory(tmp_path):
    """The new refusal is part of the gate's declared boundary, in the same
    document that carries its verdict."""
    pdks = sectioned_pdk(tmp_path / "pdks")

    rep = run_gate(project_with(tmp_path / "proj", ABSENCE_DOC), pdks)

    assert any("holds no artefact of the claimed format" in s
               for s in rep["does_not_decide"]), rep["does_not_decide"]


def test_no_pdk_library_name_is_hardcoded_in_the_gate():
    """The gate's source may carry assertion grammar; it may not carry a PDK's
    vocabulary. A library name typed here would be the very claim the gate
    exists to stop anyone making without looking."""
    src = (_PROGRAMS / "input_doc_pdk_claim_vs_installed_pdk_check.py").read_text()
    lowered = src.lower()
    for token in ("cornermos", "cornerres", "cornercap", "nangate",
                  "sky130", "gf180", "sg13", "asap7", "freepdk",
                  "mos_tt", "mos_ss", "mos_ff", "typical.lib"):
        assert token not in lowered, f"{token!r} hardcoded in the gate"
