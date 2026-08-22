#!/usr/bin/env python3
"""The four corpus-READING hygiene gates after the corpus moved out (#1710).

WHY THIS FILE EXISTS
====================
v1.10.56 moved `benchmark-data/` to `vibeic/benchmark-data`. Four gates in
`tools/ci/repo_hygiene_gates.sh` were aimed at what it held, and every one of
them then refused:

    L-doc field producer      [SKIP] no corpus (benchmark-data/ic not found)   rc 2
    evidence citation resolves[SKIP] no scan root (benchmark-data/ic not found)rc 2
    citation routing is true  [CANNOT DETERMINE] no tracked CITATION_ROUTING.txt rc 2
    L4 -> SystemRDL disposition [SKIP] no L4_REGMAP.json under <repo>          rc 2

Every refusal was CORRECT for what the gate was asked — a check that could not
look has not passed, and `run` in `_gate_dispatch.sh` maps rc 2 to FAIL. What was
wrong is WHERE they were told to look.

WHERE EACH SUBJECT WENT, because "the gate is broken" and "its subject moved" are
different diagnoses and only one of them is true here:

    L-doc field producer        its corpus (`benchmark-data/ic`) moved.
    evidence citation resolves  its corpus AND its debt register moved — the
                                register lives beside the data it describes.
    citation routing is true    ITS SUBJECT moved. Every CITATION_ROUTING.txt
                                ships INSIDE a published cell; the four that
                                existed were deleted by the same commits.
    L4 -> SystemRDL disposition ITS SUBJECT moved. All 199 tracked
                                `L4_REGMAP.json` were under `benchmark-data/`.

THE FOUR OUTCOMES, WHICH MUST NOT COLLAPSE INTO FEWER
=====================================================
    pointer set + unreadable        -> UNDETERMINED (rc 2). Never excused, with
                                       or without --corpus-may-be-absent.
    pointer set + present but NOT a
      git checkout                  -> UNDETERMINED (rc 2), for the gates that
                                       read git's INDEX. An empty `ls-files` is
                                       "I could not look", not "there are none".
    nothing anywhere + the CALL SITE
      opted in                      -> NO_CORPUS (rc 0). Nothing scanned, and
                                       NOTHING CLAIMED to have been scanned.
    nothing anywhere + nobody said  -> UNDETERMINED (rc 2). Unchanged.

EVERY CASE HERE IS PAIRED, and the pairing that matters most is the last group:
a corpus with a PLANTED DEFECT is supplied through $VIBE_IC_BENCHMARK_DATA with
`--corpus-may-be-absent` set, and every gate must still return rc 1. A change
that only proved "the gates stopped blocking" would pass just as well against
gates that had been deleted.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
REPO = PROGRAMS.parents[3]
L_DOC = PROGRAMS / "l_doc_field_producer_check.py"
EVIDENCE = PROGRAMS / "evidence_citation_resolves_check.py"
ROUTING = PROGRAMS / "citation_routing_is_true_check.py"
L4 = PROGRAMS / "l4_systemrdl_export.py"
ENV = "VIBE_IC_BENCHMARK_DATA"


def _run(prog: Path, *args: str, env_tree: str | None = None):
    """Invoke a gate the way CI does — as a process, reading only its rc.

    The exit code is the entire contract with `_gate_dispatch.sh`; a test that
    imported `main()` and asserted on returned objects would leave the rc free
    to be anything, which is how a gate that had stopped gating once kept eight
    green tests.
    """
    env = dict(os.environ)
    env.pop(ENV, None)                      # never inherit the developer's own
    if env_tree is not None:
        env[ENV] = env_tree
    r = subprocess.run([sys.executable, str(prog), *args], env=env,
                       capture_output=True, text=True, timeout=300)
    return r.returncode, (r.stdout + r.stderr)


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *a], check=True, timeout=120,
                   capture_output=True)


def _commit(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-Af")
    _git(root, "commit", "-qm", "corpus")


def _empty_register(tmp_path: Path) -> str:
    """An explicitly-empty baseline, so a FAIL below is about the planted defect
    and not about whatever the shipped register happens to hold today."""
    p = tmp_path / "register.json"
    p.write_text(json.dumps({"known": []}))
    return str(p)


# ---------------------------------------------------------------------------
# corpora. Each carries ONE planted defect of the shape its gate exists for,
# and each has a byte-identical CLEAN twin — without the twin, "the gate
# failed" is compatible with a gate that fails on every corpus it is handed.
# ---------------------------------------------------------------------------
_L4_DOC = {
    "schema_version": 2, "doc_class": "regmap", "ic_name": "unit_under_test",
    "register_map_present": True,
    "registers": [{
        "name": "CTRL", "address": "0x00", "address_int": 0, "width_bits": 32,
        "access": "RW", "description": "control",
        "fields": [{"field_name": "EN", "bits": "0", "msb": 0, "lsb": 0,
                    "access": "RW", "description": "enable"}],
    }],
}


def _corpus(tmp_path: Path, name: str, *, defect: bool,
            as_checkout: bool = True) -> Path:
    """A clone-shaped corpus. `defect=True` plants one of each measured shape:

      * an L-doc whose `power_domains` field is PRESENT and EMPTY in every
        document — the #312 family, a consumer reading what nobody writes;
      * a RESULT.md citing a `proof.log` the tree does not ship — #361;
      * a CITATION_ROUTING.txt row claiming RESOLVES for a file a reader of the
        published cell cannot follow — #448's own failure mode;
      * an L4 register key with no row in DISPOSITION — #377 item B.
    """
    root = tmp_path / name
    cell = root / "ic" / "spm" / "v1.9.96_pdkX"
    docs = cell / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (cell / "reports").mkdir()

    (docs / "L21_POWER.json").write_text(json.dumps(
        {"layer": "L21",
         "fields": {"power_domains": [] if defect else [{"name": "vdd"}]}}))

    l4 = json.loads(json.dumps(_L4_DOC))
    if defect:
        l4["registers"][0]["an_unclassified_key"] = 1
    (docs / "L4_REGMAP.json").write_text(json.dumps(l4))

    (cell / "RESULT.md").write_text("see `proof.log` for the run\n")
    if not defect:
        (cell / "proof.log").write_text("log\n")

    (cell / "reports" / "r.json").write_text('{"verdict": "PASS"}\n')
    cited = "gone.log" if defect else "real.log"
    if not defect:
        (cell / "reports" / "real.log").write_text("log\n")
    (cell / "CITATION_ROUTING.txt").write_text(
        f"# routing\nreports/r.json :: {cited} RESOLVES\n")

    if as_checkout:
        _commit(root)
    return root


@pytest.fixture()
def planted(tmp_path: Path) -> Path:
    return _corpus(tmp_path, "corpus-defect", defect=True)


@pytest.fixture()
def clean(tmp_path: Path) -> Path:
    return _corpus(tmp_path, "corpus-clean", defect=False)


# ===========================================================================
# 1. THE LOAD-BEARING PAIR: a planted defect in a SUPPLIED corpus still FAILS,
#    with the opt-in set. If the rc 2 -> rc 0 widening had been bought by
#    weakening the gates, these four are the tests that would have gone green
#    with it.
# ===========================================================================
def test_l_doc_still_fails_on_a_field_nobody_populates(planted, tmp_path):
    rc, out = _run(L_DOC, "--corpus-may-be-absent",
                   "--baseline", _empty_register(tmp_path),
                   env_tree=str(planted))
    assert rc == 1, (
        f"--corpus-may-be-absent reached a corpus that IS present and excused a "
        f"field read by a checker that no document populates\n{out}")
    assert "power_domains" in out, "the offending field must be named"


def test_evidence_still_fails_on_a_dangling_citation(planted):
    rc, out = _run(EVIDENCE, "--corpus-may-be-absent", env_tree=str(planted))
    assert rc == 1, f"a dangling citation in a supplied corpus was excused\n{out}"
    assert "proof.log" in out, "the offending citation must be named"


def test_routing_still_fails_on_a_false_RESOLVES(planted):
    rc, out = _run(ROUTING, "--root", str(REPO), "--corpus-may-be-absent",
                   env_tree=str(planted))
    assert rc == 1, f"a false RESOLVES row in a supplied corpus was excused\n{out}"
    assert "gone.log" in out, "the offending row must be named"


def test_l4_still_fails_on_an_unclassified_key(planted):
    rc, out = _run(L4, "audit-corpus", "--root", str(REPO),
                   "--corpus-may-be-absent", env_tree=str(planted))
    assert rc == 1, f"an unclassified L4 key in a supplied corpus was excused\n{out}"
    assert "an_unclassified_key" in out, "the offending key must be named"


# ===========================================================================
# 2. THE CONTROLS. The same shape with nothing wrong with it passes, so the
#    four FAILs above are about the defect and not about the corpus being
#    somewhere unusual.
# ===========================================================================
def test_l_doc_passes_a_clean_supplied_corpus(clean, tmp_path):
    rc, out = _run(L_DOC, "--corpus-may-be-absent",
                   "--baseline", _empty_register(tmp_path), env_tree=str(clean))
    assert rc == 0, out
    assert "NO_CORPUS" not in out, "a present corpus was reported as absent"
    assert "1 L-doc(s)" in out, (
        f"the denominator must be stated — a verdict over an unstated "
        f"population is unfalsifiable\n{out}")


def test_evidence_passes_a_clean_supplied_corpus(clean):
    rc, out = _run(EVIDENCE, "--corpus-may-be-absent", env_tree=str(clean))
    assert rc == 0, out
    assert "NO_CORPUS" not in out, out
    assert "file(s) enumerated" in out, (
        f"the enumerated population must be printed beside the contributing "
        f"one\n{out}")


def test_routing_passes_a_clean_supplied_corpus(clean):
    rc, out = _run(ROUTING, "--root", str(REPO), "--corpus-may-be-absent",
                   env_tree=str(clean))
    assert rc == 0, out
    assert "1 tracked record(s)" in out, out


def test_l4_passes_a_clean_supplied_corpus(clean):
    rc, out = _run(L4, "audit-corpus", "--root", str(REPO),
                   "--corpus-may-be-absent", env_tree=str(clean))
    assert rc == 0, out
    assert "1 of 1 published" in out, (
        f"the scanned/published counts must both be printed: this program has "
        f"already reported '0 of 201 documents -> PASS' once\n{out}")


# ===========================================================================
# 3. NOTHING ANYWHERE + the caller said so -> NO_CORPUS, rc 0, and it SAYS
#    nothing was scanned. This is the case that unblocks the removal.
# ===========================================================================
@pytest.mark.parametrize("prog,args", [
    (L_DOC, ()),
    (EVIDENCE, ()),
    (ROUTING, ("--root", str(REPO))),
    (L4, ("audit-corpus", "--root", str(REPO))),
])
def test_no_corpus_with_the_flag_is_rc0_and_says_it_scanned_nothing(prog, args):
    rc, out = _run(prog, *args, "--corpus-may-be-absent")
    assert rc == 0, out
    assert "NO_CORPUS" in out, out
    assert "NOTHING WAS SCANNED" in out, \
        "an rc 0 must not read as a scan that happened"
    assert "[PASS]" not in out, "a scan that did not happen was spelled as a pass"


# ===========================================================================
# 4. …AND WITHOUT THE FLAG THEY ALL STILL BLOCK. The half that makes case 3
#    mean something: the relaxation is OPT-IN AT THE CALL SITE, never a new
#    default.
# ===========================================================================
@pytest.mark.parametrize("prog,args", [
    (L_DOC, ()),
    (EVIDENCE, ()),
    (ROUTING, ("--root", str(REPO))),
    (L4, ("audit-corpus", "--root", str(REPO))),
])
def test_without_the_flag_an_absent_corpus_is_still_undetermined(prog, args):
    rc, out = _run(prog, *args)
    assert rc == 2, f"the relaxation must be opt-in\n{out}"
    assert "NO_CORPUS" not in out, out


# ===========================================================================
# 5. A BROKEN POINTER IS NEVER EXCUSED — not even with the flag. "Somebody said
#    where the corpus is and was wrong" is a different event from "there is
#    none", and a mistyped path or a no-op CI fetch step must not go green.
# ===========================================================================
@pytest.mark.parametrize("prog,args", [
    (L_DOC, ()),
    (EVIDENCE, ()),
    (ROUTING, ("--root", str(REPO))),
    (L4, ("audit-corpus", "--root", str(REPO))),
])
def test_a_broken_pointer_is_undetermined_even_with_the_flag(prog, args, tmp_path):
    rc, out = _run(prog, *args, "--corpus-may-be-absent",
                   env_tree=str(tmp_path / "nowhere"))
    assert rc == 2, f"a set-and-wrong pointer must never be waved through\n{out}"
    assert "UNDETERMINED" in out and ENV in out, out
    assert "NO_CORPUS" not in out, \
        "a broken pointer was laundered as an absent corpus"


# ===========================================================================
# 6. A DIRECTORY IS NOT A CHECKOUT — the fatal an adversarial reviewer found in
#    the first version of the v1.10.60 fix, pinned here for the two gates in
#    this set that read git's INDEX.
#
#    The corpus lives in its own repository now, so a tarball fetch, an archive
#    export, a dead `git clone` or a worktree without `.git` all produce a tree
#    that is PRESENT and has no index. Over it `git ls-files` returns nothing,
#    and reading that as "there are none" is a FAILED FETCH CERTIFYING A TREE —
#    strictly worse than NO_CORPUS, which at least states nothing was scanned.
#
#    BOTH ARMS, built byte-identically except for `git init`.
# ===========================================================================
def test_evidence_a_present_but_unversioned_corpus_is_undetermined(tmp_path):
    loose = _corpus(tmp_path, "loose", defect=True, as_checkout=False)
    rc, out = _run(EVIDENCE, "--corpus-may-be-absent", env_tree=str(loose))
    assert rc == 2, (
        f"a corpus that is PRESENT and carries the defect was judged from the "
        f"DISK, where an untracked local artefact can satisfy a citation the "
        f"published tree does not ship\n{out}")
    assert "not a git checkout" in out, out
    assert "[PASS]" not in out, out
    assert "NO_CORPUS" not in out, (
        "a present-but-unversioned corpus was laundered as an absent one; "
        "the corpus is right there")


def test_routing_a_present_but_unversioned_corpus_is_undetermined(tmp_path):
    loose = _corpus(tmp_path, "loose", defect=True, as_checkout=False)
    rc, out = _run(ROUTING, "--root", str(REPO), "--corpus-may-be-absent",
                   env_tree=str(loose))
    assert rc == 2, out
    assert "not a git checkout" in out, out
    assert "NO_CORPUS" not in out, out


def test_the_checkout_arm_of_the_same_corpus_still_catches_the_defect(tmp_path):
    """NO-LEAK for the two above: the identical tree WITH `git init` is judged
    and FAILs, so the rc 2 is about the missing index and not about the fixture."""
    checkout = _corpus(tmp_path, "checkout", defect=True, as_checkout=True)
    rc, out = _run(EVIDENCE, "--corpus-may-be-absent", env_tree=str(checkout))
    assert rc == 1, out
    assert "proof.log" in out, out


# ===========================================================================
# 7. AN EMPTY RESULT IS NOT A ZERO. Each gate is handed a corpus that IS there
#    and holds nothing it can read, and must refuse rather than roll a verdict
#    up over an empty population.
# ===========================================================================
def test_l_doc_refuses_a_corpus_with_no_L_doc(tmp_path):
    # No `git init`: this gate never reads the index, it counts VALUES inside
    # documents with an rglob, so a loose directory is a tree it can honestly
    # answer about — and the honest answer over zero documents is a refusal.
    empty = tmp_path / "empty"
    (empty / "ic").mkdir(parents=True)
    rc, out = _run(L_DOC, "--corpus-may-be-absent", env_tree=str(empty))
    assert rc == 2, (
        f"0 documents scanned against N fields read is a comparison against "
        f"nothing; it must not report a verdict\n{out}")
    assert "UNDETERMINED" in out, out
    assert "[PASS]" not in out and "[FAIL]" not in out, out


def test_l_doc_refuses_when_no_checker_reads_anything(tmp_path, clean):
    """The other side of the same comparison. `--programs` aimed at a directory
    with no `*_check.py` finds ZERO readers, so no field can be found and the
    gate printed PASS having analysed nothing."""
    nothing = tmp_path / "no-programs"
    nothing.mkdir()
    rc, out = _run(L_DOC, "--corpus-may-be-absent", "--programs", str(nothing),
                   env_tree=str(clean))
    assert rc == 2, f"zero readers must be 'I could not look'\n{out}"
    assert "NOTHING to look for" in out, out


def test_evidence_refuses_a_scan_root_it_enumerated_nothing_from(tmp_path):
    empty = tmp_path / "empty-ec"
    (empty / "ic").mkdir(parents=True)
    (empty / "unrelated.txt").write_text("x\n")
    _commit(empty)
    rc, out = _run(EVIDENCE, "--corpus-may-be-absent", env_tree=str(empty))
    assert rc == 2, f"a verdict was rolled up over an empty population\n{out}"
    assert "[PASS]" not in out, out


def test_l4_refuses_a_corpus_whose_documents_are_all_unreadable(tmp_path):
    """`audit-corpus` used to `continue` past every unparseable document, see
    zero keys, find nothing unclassified and print PASS. This program's own
    history records that exact shape: 'audit-corpus found 0 of 201 documents
    -> PASS'."""
    bad = tmp_path / "unreadable"
    d = bad / "ic" / "spm" / "v1.9.96_pdkX" / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    (d / "L4_REGMAP.json").write_text("{ not json")
    _commit(bad)
    rc, out = _run(L4, "audit-corpus", "--root", str(REPO),
                   "--corpus-may-be-absent", env_tree=str(bad))
    assert rc == 2, f"a corpus that could not be parsed was certified\n{out}"
    assert "NONE of them parsed" in out, out
    assert "[PASS]" not in out, out


def test_routing_refuses_a_corpus_carrying_none_of_its_subject(tmp_path):
    """A pointer that WAS set and led to a checkout tracking no record at all is
    a wrong pointer, not an absent corpus — the opt-in must not reach it."""
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "x.txt").write_text("x\n")
    _commit(bare)
    rc, out = _run(ROUTING, "--root", str(REPO), "--corpus-may-be-absent",
                   env_tree=str(bare))
    assert rc == 2, out
    assert "NO_CORPUS" not in out, out


# ===========================================================================
# 8. THE OVERRIDE IS ANNOUNCED. A gate that scans a tree other than the one on
#    its command line must say so — that silence is how a mis-aimed `--tree`
#    once reported "13/28 conformant" over a tree an absolute path found 8
#    failures in.
# ===========================================================================
@pytest.mark.parametrize("prog,args", [
    (L_DOC, ()),
    (EVIDENCE, ()),
    (ROUTING, ("--root", str(REPO))),
    (L4, ("audit-corpus", "--root", str(REPO))),
])
def test_the_tree_actually_scanned_is_named(prog, args, clean):
    rc, out = _run(prog, *args, "--corpus-may-be-absent", env_tree=str(clean))
    assert ENV in out, f"the pointer that took effect must be named\n{out}"
    assert str(clean) in out, f"the tree actually scanned must be named\n{out}"


# ===========================================================================
# 9. THE SHIPPED CALL SITES CARRY THE FLAG. Everything above tests the
#    programs; this tests the only lines that ever invoke them in production.
#    Without it all four programs could be perfect and all four gates still red.
# ===========================================================================
@pytest.mark.parametrize("prog", [
    "l_doc_field_producer_check.py",
    "evidence_citation_resolves_check.py",
    "citation_routing_is_true_check.py",
    "l4_systemrdl_export.py",
])
def test_the_hygiene_sweep_actually_passes_the_flag(prog):
    sweep = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
    if not sweep.is_file():
        pytest.skip(f"{sweep} not present in this checkout")
    lines = [ln for ln in sweep.read_text().splitlines()
             if prog in ln and not ln.strip().startswith("#")]
    assert lines, f"the hygiene sweep no longer invokes {prog} at all"
    assert all("--corpus-may-be-absent" in ln for ln in lines), (
        f"the sweep invokes {prog} without the flag, so a repo with no corpus is "
        f"still blocked:\n" + "\n".join(lines))
