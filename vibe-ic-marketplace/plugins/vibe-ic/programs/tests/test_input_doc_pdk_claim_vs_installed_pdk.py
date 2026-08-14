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
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_PROGRAMS = _HERE.parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _container_exec  # noqa: E402
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

def test_an_absent_installed_pdk_root_is_not_a_pass(tmp_path):
    """No image mounted means nothing was checked — not that all is well.

    The reason token is `absent`, not `unreadable`: this root was never opened,
    so nothing about its readability was learned (#1491). The tier is what
    matters and it is unchanged — NOT_APPLICABLE, nothing corroborated.
    """
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    rep = run_gate(tree, tmp_path / "does_not_exist")

    assert rep["verdict"] == "NOT_APPLICABLE", rep
    assert rep["reason"].startswith("installed_pdk_root_absent"), rep
    assert rep["installed_pdk_root_state"] == gate.ROOT_ABSENT, rep
    assert rep["counts"]["corroborated"] == 0


def test_the_vacuous_run_names_the_backend_that_never_ran(tmp_path):
    """#981: the WIRED call site passes no `--container`, so on a host with no
    local PDK tree this branch is the only one that ever fires — and the
    container backend, with the `-L` dereference #964 exists for, is not merely
    undecided, it is NOT EXECUTED. Measured 2026-08-11 on the wired invocation
    at tools/ci/repo_hygiene_gates.sh: rc 2, VACUOUS, 0 documents scanned.

    A rc-2 that says only "I could not look" lets a reader assume the gate is
    whole and merely idle. It says which half never ran, so the untested half
    is a fact in the report rather than something a reviewer has to notice.
    """
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    rep = run_gate(tree, tmp_path / "does_not_exist")

    assert rep["installed_pdk_source"] == "local", rep
    assert rep["backend_not_exercised"] == ["container"], rep
    assert "container backend was NOT exercised" in rep["reason"], rep


def test_a_container_run_does_not_claim_an_unexercised_backend(tmp_path):
    """PAIRED GUARD: the disclosure is a measurement, not a decoration. A run
    that DID go through the container backend must not carry it."""
    calls = []

    def lister(path):
        calls.append(path)
        return []

    rep = gate.run(project_with(tmp_path / "proj", ABSENCE_DOC),
                   "/nowhere", container="a-container",
                   lister=lister, reader=lambda p: None, walker=lambda p: [])

    assert calls, "the injected backend was never consulted"
    assert rep["installed_pdk_source"] == "container:a-container", rep
    assert rep["backend_not_exercised"] == [], rep
    assert "NOT exercised" not in rep["reason"], rep


# ── #1491: four environments printed one sentence ──────────────────────────
#
# `entries()` returns [] for a root that is absent, for a root that is present
# and holds no PDK, for a root that cannot be opened, and for a backend that
# never ran at all. Measured on one host at one commit before the fix, all four
# printed `installed_pdk_root_unreadable` and all four were VACUOUS_PASS — so a
# reader comparing two verdicts of the same tree had nothing in either output
# telling them what differed.
#
# These fixtures build the four environments directly. No container is needed:
# the backend-unavailable arm injects the gate's OWN failure shape rather than
# asking whether this host happens to run docker, which is the property under
# test rather than an obstacle to it.


def test_a_root_that_holds_no_pdk_is_not_reported_as_unreadable(tmp_path):
    """The 8HD-9 environment from the issue: `/foss/pdks` EXISTS, is readable,
    and holds no PDK. It was read. Saying "unreadable" of a directory that was
    successfully listed is a false statement in the gate's own report."""
    empty_root = tmp_path / "pdks"
    empty_root.mkdir()
    (empty_root / "versions.txt").write_text("x\n")
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    rep = run_gate(tree, empty_root)

    assert rep["installed_pdk_root_state"] == gate.ROOT_READ, rep
    assert rep["reason"].startswith("installed_pdk_root_holds_no_pdk"), rep
    assert "unreadable" not in rep["reason"], rep
    assert rep["verdict"] == "NOT_APPLICABLE", rep


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="mode 000 does not stop root, so the stimulus this "
                           "asserts on cannot be created here")
def test_the_local_prober_separates_a_read_error_from_an_empty_directory(
        tmp_path):
    """`_local_file_lister` returns [] for both. Only the prober can tell them
    apart, and it carries the OS's own message so "I could not look" names its
    reason instead of being a category."""
    empty = tmp_path / "empty"
    empty.mkdir()
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        assert gate._local_file_lister(str(locked)) == []
        assert gate._local_file_lister(str(empty)) == []
        state, detail = gate._local_prober(str(locked))
    finally:
        locked.chmod(0o755)

    assert state == gate.ROOT_UNREADABLE, (state, detail)
    assert detail, "a read error that names no reason is not a disclosure"
    assert gate._local_prober(str(empty)) == (gate.ROOT_READ, "")


def test_a_root_that_cannot_be_opened_says_so_and_says_why(tmp_path):
    """The genuine read error, which now has the `unreadable` token to itself.

    The state is injected through the gate's own `prober` seam rather than
    through file modes, so this asserts the same thing whether or not the run
    happens to be root — a test whose verdict moves with the environment is
    the defect it would be guarding.
    """
    rep = gate.run(project_with(tmp_path / "proj", ABSENCE_DOC),
                   str(tmp_path / "pdks"),
                   prober=lambda p: (gate.ROOT_UNREADABLE, "Permission denied"))

    assert rep["installed_pdk_root_state"] == gate.ROOT_UNREADABLE, rep
    assert rep["reason"].startswith("installed_pdk_root_unreadable"), rep
    assert "Permission denied" in rep["reason"], rep
    assert rep["installed_pdk_root_probe"] == "Permission denied", rep
    assert rep["verdict"] == "NOT_APPLICABLE", rep


def _unreachable_container_backends(monkeypatch, rc=125,
                                    stderr="Error: No such container: c"):
    """The gate's REAL container backend against a `docker exec` that fails.

    Substituting at `subprocess.run` means the gate's own command strings, its
    own rc handling and its own probe parsing are all exercised — the failure
    is injected where docker would produce it, not where the gate would be
    convenient to fake.
    """
    def fake_run(cmd, **kw):
        assert cmd[:2] == ["docker", "exec"], cmd
        return subprocess.CompletedProcess(cmd, rc, "", stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_a_container_that_never_answered_is_not_an_empty_pdk_root(tmp_path,
                                                                  monkeypatch):
    """#1491's core defect. `docker exec` never ran; the gate reported the
    installed PDK ROOT as unreadable and exited 2, so a `--container` naming a
    container that is down, misnamed or absent was indistinguishable from a
    host that simply has no PDK."""
    _unreachable_container_backends(monkeypatch)
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    rep = gate.run(tree, "/foss/pdks", container="c")

    assert rep["installed_pdk_root_state"] == gate.ROOT_BACKEND_UNAVAILABLE, rep
    assert rep["reason"].startswith("container_backend_unavailable"), rep
    assert "No such container" in rep["reason"], rep


def test_a_named_backend_that_never_ran_is_not_reported_as_exercised(
        tmp_path, monkeypatch):
    """The disclosure #981 added was computed from the ARGV — "a container was
    named, therefore the container backend ran". It is computed from what
    actually ran now, so wiring `--container` cannot be inert and look
    exercised at the same time."""
    _unreachable_container_backends(monkeypatch)

    rep = gate.run(project_with(tmp_path / "proj", ABSENCE_DOC),
                   "/foss/pdks", container="c")

    assert rep["backend_not_exercised"] == ["container"], rep


def test_a_named_backend_that_could_not_be_reached_refuses_rather_than_skips(
        tmp_path, monkeypatch):
    """A host with no installed PDK is NOT_APPLICABLE — a fact about the
    machine. A caller passing `--container <name>` has ASSERTED an environment,
    and when that environment does not answer the gate has not found nothing
    applicable, it has failed to run. Same call `cvdp_gate` made for an absent
    `iverilog` (#1345): the check that COULD NOT RUN must not be the quieter of
    the two."""
    _unreachable_container_backends(monkeypatch)

    rep = gate.run(project_with(tmp_path / "proj", ABSENCE_DOC),
                   "/foss/pdks", container="c")

    assert rep["verdict"] == "FAIL", rep
    assert rep["failure_kind"] == "environment", rep


def test_a_pdkless_host_still_skips_rather_than_failing(tmp_path):
    """PAIRED GUARD for the refusal above, and the reason it is narrow. The
    WIRED call site passes no `--container`, so this is the branch every CI run
    takes; turning it red would be a verdict about the machine. It stays rc 2,
    exactly as before."""
    rep = run_gate(project_with(tmp_path / "proj", ABSENCE_DOC),
                   tmp_path / "does_not_exist")

    assert rep["verdict"] == "NOT_APPLICABLE", rep
    assert "failure_kind" not in rep, rep


def test_every_uncheckable_environment_gets_its_own_reason_token(tmp_path,
                                                                 monkeypatch):
    """The defect stated as one assertion: four environments, four tokens.

    Before #1491 this collected `{'installed_pdk_root_unreadable'}` — one
    element for four worlds, which is the whole finding.
    """
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    absent = run_gate(tree, tmp_path / "nope")

    empty = tmp_path / "empty"
    empty.mkdir()
    holds_no_pdk = run_gate(tree, empty)

    unreadable = gate.run(
        tree, str(tmp_path / "locked"),
        prober=lambda p: (gate.ROOT_UNREADABLE, "Permission denied"))

    _unreachable_container_backends(monkeypatch)
    unreached = gate.run(tree, "/foss/pdks", container="c")

    tokens = {r["reason"].split(" (")[0]
              for r in (absent, holds_no_pdk, unreadable, unreached)}
    assert len(tokens) == 4, tokens


def test_the_container_round_trip_carries_a_container_side_deadline():
    """A client-side `timeout=` bounds the local docker client only; the tool
    inside keeps running as an orphan. #1491 routed this gate's round trip
    through `_container_exec`, so the deadline runs as the tool's parent INSIDE
    the container and can signal it — and the total client bound stays under
    the 60s per-call ceiling `ci_harness_timeout_ceiling_check` derives from
    the 180s session bound, so one wedged container cannot take the session
    down with it."""
    argv = _container_exec.container_deadline_argv(
        "c", "true", gate._CONTAINER_DEADLINE_S)

    assert argv[:3] == ["docker", "exec", "c"], argv
    assert "timeout" in argv, argv
    assert str(gate._CONTAINER_DEADLINE_S) in argv, argv
    assert (gate._CONTAINER_DEADLINE_S
            + _container_exec.CLIENT_GRACE_S) <= 60, gate._CONTAINER_DEADLINE_S


def test_a_container_deadline_expiry_is_not_an_empty_pdk_root(tmp_path,
                                                              monkeypatch):
    """The same conflation one exit code over: coreutils `timeout` reports 124
    when it killed the tool. A killed run has no verdict, so it must not be
    recorded as a root that was read and found empty."""
    _unreachable_container_backends(
        monkeypatch, rc=_container_exec.TIMEOUT_EXPIRED_RC, stderr="")

    rep = gate.run(project_with(tmp_path / "proj", ABSENCE_DOC),
                   "/foss/pdks", container="c")

    assert rep["installed_pdk_root_state"] == gate.ROOT_BACKEND_UNAVAILABLE, rep
    assert rep["verdict"] == "FAIL", rep
    assert "deadline" in rep["reason"], rep


def test_the_environment_is_printed_on_a_run_that_decides_something(tmp_path):
    """#1491 measured `[FAIL]` over 134 documents and `VACUOUS_PASS` over 0
    from one tree on one host, with nothing in either output naming what
    differed. The line is printed on EVERY run, including the ones that go
    well: a disclosure that appears only with bad news teaches a reader to
    read its absence as good news."""
    pdks = sectioned_pdk(tmp_path / "pdks")
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    proc, rep = _cli(tree, pdks, tmp_path)

    assert proc.returncode == 1, proc.stdout
    env = [ln for ln in proc.stdout.splitlines()
           if ln.startswith("[ENVIRONMENT]")]
    assert len(env) == 1, proc.stdout
    assert f"root={pdks}" in env[0], env
    assert "backend=local" in env[0], env
    assert f"state={gate.ROOT_READ}" in env[0], env
    assert "installed_pdks=1" in env[0], env


def test_the_environment_is_printed_on_a_run_that_decides_nothing(tmp_path):
    """PAIRED GUARD: the arm the issue actually compared against."""
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    proc, rep = _cli(tree, tmp_path / "does_not_exist", tmp_path)

    assert proc.returncode == 2, proc.stdout
    env = [ln for ln in proc.stdout.splitlines()
           if ln.startswith("[ENVIRONMENT]")]
    assert len(env) == 1, proc.stdout
    assert f"state={gate.ROOT_ABSENT}" in env[0], env
    assert "not_exercised=container" in env[0], env


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
    local shell. Same commands, same parsing, a tree the test can build.

    Patches `subprocess.run` on the MODULE OBJECT rather than through a
    re-export on the gate. #1491 routed the gate's `docker exec` through
    `_container_exec.run_in_container` — the repo's sanctioned site, which puts
    the deadline container-side so an expiry kills the tool instead of
    orphaning it — so the call no longer issues from this gate's own namespace.
    Patching the module both of them import keeps the substitution in exactly
    one place and keeps these tests driving the gate's REAL command strings.
    """
    real_run = subprocess.run

    def fake_run(cmd, **kw):
        assert cmd[:2] == ["docker", "exec"], cmd
        return real_run(["bash", "-lc", cmd[-1]], **kw)

    monkeypatch.setattr(subprocess, "run", fake_run)
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


def test_the_walk_visits_each_real_directory_once_when_a_link_points_back_up(
        tmp_path):
    """The realpath visited-set, asserted on the property it actually has.

    THIS TEST USED TO BE UNABLE TO FAIL. It was named for the cycle guard and
    asserted only that `cornerBlk.lib` appeared somewhere in the result, which
    is true whether the guard is there or not. Measured 2026-08-11 on this very
    fixture: delete the visited-set, leave `followlinks=True` and every other
    line intact, and the whole file was still 33 passed / rc 0.

    It terminated for a reason that has nothing to do with this repo. Linux
    refuses at about forty symlink levels, `os.walk` swallows the resulting
    error, and the recursion stops there. Same fixture, both walkers:

        shipped         1 path
        guard deleted  42 paths, the deepest 171 components long

    So the property is not "the call returns" — an unguarded walk returns too.
    It is that a directory already walked under one name is not walked again
    under another, and the observable form of that is that EVERY REAL FILE
    APPEARS EXACTLY ONCE. The 42 paths are 42 readings of one file, so
    resolving them collapses the set and the duplicates are the defect made
    visible. That assertion does not care where the OS gives up, which is the
    point: it is about the guard, not about the kernel's patience.
    """
    pdks = tmp_path / "pdks"
    models = pdks / "alphanode" / "libs.tech" / "ngspice" / "models"
    _write(models / "cornerBlk.lib", ".lib grade_nom\n.endl\n")
    (models / "loop").symlink_to(pdks / "alphanode")

    found = gate._local_walker(str(pdks / "alphanode"))

    assert any(p.endswith("cornerBlk.lib") for p in found), found
    reals = [os.path.realpath(p) for p in found]
    repeated = sorted({r for r in reals if reals.count(r) > 1})
    assert not repeated, (
        f"{len(found)} path(s) resolve to {len(set(reals))} real file(s) — the "
        f"walk re-entered a directory it had already visited: {repeated}")
    # and the cycle was cut at the link, not tens of levels down inside it
    assert len(found) == 1, found


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


# ── #981: a check that narrows its population and reports over the whole ──
#
# The docstring promises a UNIVERSAL — "every DIRECTORY the claim named holds
# files of that format" — and the code narrowed with an INTERSECTION against the
# UNION of those directories. One productive qualifier therefore kept the gate
# answering while another named directory held nothing of the format at all, and
# the answer was CORROBORATED, which is the only route to rc 0.


def _two_directory_pdk(tmp_path: Path, corner_dir: str) -> Path:
    """A PDK whose `.lib` sits in exactly one of the two directories a claim
    of the form "no <a> <b> corner lib" names. `ngspice/` always exists and
    always holds a file, so it is a real directory either way — what varies is
    whether it holds one of the CLAIMED FORMAT."""
    pdks = tmp_path / "pdks"
    _write(pdks / "betanode" / "libs.tech" / "ngspice" / "models"
           / "devices_blk.spice", "* models\n")
    _write(pdks / "betanode" / corner_dir / "BetaCells_typical.lib",
           "library (t) { }\n")
    return pdks


_TWO_DIR_CLAIM = "- BetaNode has no public ngspice corner lib -> standin.\n"


def test_agreement_is_withheld_when_one_named_directory_holds_none_of_it(
        tmp_path):
    """#981: the union let one productive qualifier answer for both.

    `public/` holds the only `.lib`; `ngspice/` holds none. The claim names
    BOTH, so agreeing with it is a statement about both — and the gate never
    read one of them. Measured on origin/main: CORROBORATED / PASS / rc 0.
    """
    pdks = _two_directory_pdk(tmp_path, "public")
    tree = project_with(tmp_path / "proj", _TWO_DIR_CLAIM)

    proc, rep = _cli(tree, pdks, tmp_path)

    assert rep["counts"]["corroborated"] == 0, rep["claims"]
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "UNDECIDED"]
    assert claim["directory_qualifiers"] == ["ngspice", "public"], claim
    assert claim["directory_qualifiers_without_that_format"] == ["ngspice"], claim
    assert rep["verdict"] == "NOT_APPLICABLE", rep
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    combined = proc.stdout + proc.stderr
    assert any(ln.startswith("VACUOUS_PASS") for ln in combined.splitlines())


def test_the_withheld_agreement_is_still_shown_to_the_reader(tmp_path):
    """A refusal that hides what it would have said is a refusal nobody can
    check. The reason the gate declined to give is kept under its own key, and
    it is not counted anywhere."""
    pdks = _two_directory_pdk(tmp_path, "public")
    rep = run_gate(project_with(tmp_path / "proj", _TWO_DIR_CLAIM), pdks)

    (claim,) = rep["claims"]
    assert claim["corroboration_withheld"], claim
    assert "never checked there" in claim["reason"], claim
    assert claim["examined_by_directory"] == {"ngspice": 0, "public": 1}, claim


def test_a_claim_over_two_populated_directories_is_still_corroborated(tmp_path):
    """PAIRED GUARD, and the one that decides whether #981 is a fix or a ban.
    Same sentence, same two directories, and now BOTH hold files of the claimed
    format and neither names the denied word. The universal is satisfied, so
    the claim must still be CORROBORATED and still rc 0."""
    pdks = _two_directory_pdk(tmp_path, "public")
    _write(pdks / "betanode" / "libs.tech" / "ngspice" / "models"
           / "devices_blk.lib", "library (d) { }\n")
    tree = project_with(tmp_path / "proj", _TWO_DIR_CLAIM)

    proc, rep = _cli(tree, pdks, tmp_path)

    assert rep["verdict"] == "PASS", rep
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CORROBORATED"]
    assert "directory_qualifiers_without_that_format" not in claim, claim
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)


def test_a_contradiction_in_a_sibling_directory_survives_the_universal(tmp_path):
    """The asymmetry, pinned. A denial is FALSIFIED by one artefact in any ONE
    named directory and CONFIRMED only by having read all of them, so the
    universal may gate agreement and may NOT gate contradiction.

    This is not hypothetical. Measured against the real installed PDKs
    2026-08-11, the corpus' own false claim names two directories, one of which
    holds ZERO files of the claimed format (`{'library': 0, 'ngspice': 32}`).
    Applying the universal before the verdict would have converted a true
    CONTRADICTED into UNDECIDED and stopped the gate reporting a false claim.
    """
    pdks = tmp_path / "pdks"
    _write(pdks / "betanode" / "library" / "notes.txt", "prose\n")
    _write(pdks / "betanode" / "libs.tech" / "ngspice" / "models"
           / "cornerBlk.lib", ".lib grade_nom\n.endl\n")
    tree = project_with(
        tmp_path / "proj",
        "- BetaNode has no public ngspice corner library -> standin.\n")

    proc, rep = _cli(tree, pdks, tmp_path)

    assert rep["verdict"] == "FAIL", rep
    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CONTRADICTED"]
    assert claim["examined_by_directory"] == {"library": 0, "ngspice": 1}, claim
    assert any(p.endswith("cornerBlk.lib") for p in claim["evidence"]), claim
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)


def test_the_pass_reason_counts_every_directory_it_names(tmp_path):
    """#981b: the PASS reason was built from ALL of `dir_quals` and carried ONE
    total, so it printed "the claim holds over the 1 file(s) of that format
    under ngspice/public" when ngspice contributed zero — a sentence whose
    subject is a set the gate never examined.

    A PASS must say how much it looked at, so it says so PER DIRECTORY: every
    directory the reason names carries its own count, and a zero is therefore
    written down where the reader is instead of being averaged away.
    """
    pdks = _two_directory_pdk(tmp_path, "public")
    _write(pdks / "betanode" / "libs.tech" / "ngspice" / "models"
           / "devices_blk.lib", "library (d) { }\n")
    rep = run_gate(project_with(tmp_path / "proj", _TWO_DIR_CLAIM), pdks)

    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CORROBORATED"]
    by_dir = claim["examined_by_directory"]
    assert set(by_dir) == set(claim["directory_qualifiers"]), claim
    for name, count in by_dir.items():
        assert count > 0, claim
        assert re.search(rf"\b{re.escape(name)} \({count}\)", claim["reason"]), (
            f"{name} is named in the reason without the count it contributed: "
            f"{claim['reason']!r}")


def test_a_single_directory_claim_still_states_its_denominator(tmp_path):
    """The one-directory case keeps the disclosure the house rule requires —
    the count is stated, not implied by the absence of a second name."""
    pdks = bare_pdk(tmp_path / "pdks")
    rep = run_gate(project_with(tmp_path / "proj", ABSENCE_DOC), pdks)

    (claim,) = [c for c in rep["claims"] if c["verdict"] == "CORROBORATED"]
    assert claim["examined_by_directory"] == {"ngspice": 1}, claim
    assert "ngspice (1)" in claim["reason"], claim


# ── #981: two more decisions on this file that no test could kill ──────────


def test_a_one_letter_acronym_fragment_is_not_a_word_anyone_denies(tmp_path):
    """`_MIN_LOOKUP_FRAGMENT` had no test: set it to 0 and the file was still
    33 passed. It is the rule that stops a single stray letter of an uppercase
    run from matching a claim — `lookup_tokens` deliberately emits BOTH
    readings of an ambiguous boundary, so without a floor the left reading of
    `ABat` contributes the bare letter `a` to the vocabulary a denial is
    matched against."""
    frags = gate.lookup_tokens("cornerABat")

    assert {"abat", "bat"} <= frags, frags
    assert "a" not in frags, frags


def test_a_qualifier_must_come_from_inside_the_pdk_not_from_where_it_is_mounted(
        tmp_path):
    """`_rel_components` taking components RELATIVE to the PDK directory had no
    test either: make it absolute and the file was still 33 passed. The mount
    path is chosen by whoever installed the image, so a word in it is not a
    word the claim supplied — and with #981 it would additionally read as a
    directory that holds every file, silently satisfying the universal."""
    pdks = bare_pdk(tmp_path / "public" / "pdks")
    tree = project_with(tmp_path / "proj", ABSENCE_DOC)

    rep = run_gate(tree, pdks)

    (claim,) = rep["claims"]
    assert claim["directory_qualifiers"] == ["ngspice"], (
        "a component of the mount path was taken for a qualifier the claim "
        f"supplied: {claim.get('directory_qualifiers')}")
    assert claim["examined_by_directory"] == {"ngspice": 1}, claim


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
