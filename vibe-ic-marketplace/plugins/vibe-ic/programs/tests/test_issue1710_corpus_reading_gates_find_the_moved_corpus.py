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

import _corpus_location as _corpus_loc
import _pytest_progress_plugin
import citation_routing_is_true_check as _routing_gate
import evidence_citation_resolves_check as _evidence_gate
import l4_systemrdl_export as _l4_gate
import l_doc_field_producer_check as _l_doc_gate
import repo_hygiene_parallel as _parallel

PROGRAMS = Path(__file__).resolve().parents[1]
REPO = PROGRAMS.parents[3]
L_DOC = PROGRAMS / "l_doc_field_producer_check.py"
EVIDENCE = PROGRAMS / "evidence_citation_resolves_check.py"
ROUTING = PROGRAMS / "citation_routing_is_true_check.py"
L4 = PROGRAMS / "l4_systemrdl_export.py"
ENV = "VIBE_IC_BENCHMARK_DATA"
OWNED = PROGRAMS / "_owned_process_supervisor.py"


def _atomic_owned(argv, *, env):
    """Run one intentionally indivisible fixture operation to final zero."""
    rc, body, problem = _parallel._run(
        list(argv), REPO, env, stall_grace_s=float("inf"), atomic=True)
    if problem:
        raise AssertionError(
            "OWNED_CHILD_NORECORD: " + problem + "\n" + body[-5000:])
    return rc, body


def _arg_value(args: tuple[str, ...], option: str, default: str) -> str:
    try:
        return args[args.index(option) + 1]
    except (ValueError, IndexError):
        return default


def _resolved_ic_corpus(module_file: str, supplied: Path | None
                        ) -> Path | None:
    here = Path(module_file).resolve()
    # vibe-ic#1710 — THE PARENT'S PLAN MUST USE THE CHILD'S RESOLUTION. This
    # re-implemented the gates' unbounded `here.parents` walk, so on a host whose
    # $HOME carries a `benchmark-data/` the pytest-side manifest was computed over
    # THAT tree while the (now bounded) gate worked over the supplied corpus. The
    # counts then disagreed and the run died as a progress-protocol violation
    # (`child reached natural return before completing its finite manifest
    # (1146/1366)`) rather than as anything about the corpus. One seam, both sides.
    named = _corpus_loc.default_named(here, "benchmark-data/ic")
    if named.is_dir():
        return named
    candidate = supplied / "ic" if supplied is not None else None
    return candidate if candidate is not None and candidate.is_dir() else None


def _progress_plan(prog: Path, args: tuple[str, ...], env_tree: str | None
                   ) -> tuple[str, list[str]]:
    """Trusted pytest-side finite manifest for the exact checker invocation."""
    supplied = Path(env_tree).resolve() if env_tree is not None else None
    if prog == L_DOC:
        programs = Path(_arg_value(args, "--programs", str(PROGRAMS)))
        corpus = _resolved_ic_corpus(_l_doc_gate.__file__, supplied)
        units = (_l_doc_gate.semantic_progress_units(programs, corpus)
                 if corpus is not None else [])
        return _l_doc_gate.PROGRESS_SCOPE, units
    if prog == EVIDENCE:
        corpus = _resolved_ic_corpus(_evidence_gate.__file__, supplied)
        units = (_evidence_gate.semantic_progress_units(
            corpus, write_baseline="--write-baseline" in args,
            require_checkout=(supplied is not None and
                              corpus == supplied / "ic"))
                 if corpus is not None else [])
        return _evidence_gate.PROGRESS_SCOPE, units
    if prog == ROUTING:
        root = Path(_arg_value(args, "--root", "."))
        units = _routing_gate.semantic_progress_units(root, supplied)
        return _routing_gate.PROGRESS_SCOPE, units
    if prog == L4:
        # A set-and-broken pointer returns before even the repository root is
        # walked.  Otherwise audit-corpus adds the supplied corpus to --root.
        if supplied is not None and not supplied.is_dir():
            units = []
        else:
            root = Path(_arg_value(args, "--root", str(REPO)))
            units = _l4_gate.semantic_progress_units(
                root, [supplied] if supplied is not None else [])
        return _l4_gate.PROGRESS_SCOPE, units
    raise AssertionError(f"no semantic progress plan for {prog}")


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
    scope, units = _progress_plan(prog, args, env_tree)
    rc, out, problem = _parallel._run(
        [sys.executable, str(prog), *args], REPO, env,
        semantic_progress_scope=scope,
        semantic_progress_units=units,
        domain_progress_callback=_pytest_progress_plugin.domain_progress)
    return rc, out + (("\n" + problem) if problem else "")


def _git(cwd: Path, completed: int, total: int, *a: str) -> None:
    # Each git command is one intentionally indivisible fixture transition.
    # Natural exit/final-zero owns completion; the finite five-step builder
    # relays a real checkpoint after every completed operation.
    rc, body = _atomic_owned(
        ["git", "-C", str(cwd), *a], env=dict(os.environ))
    assert rc == 0, f"git {' '.join(a)} exited {rc}:\n{body[-3000:]}"
    _pytest_progress_plugin.domain_progress(
        "issue1710-git-fixture", completed, total)


def _commit(root: Path) -> None:
    commands = (
        ("init", "-q"),
        ("config", "user.email", "t@t"),
        ("config", "user.name", "t"),
        ("add", "-Af"),
        ("commit", "-qm", "corpus"),
    )
    for completed, command in enumerate(commands, 1):
        _git(root, completed, len(commands), *command)


def test_atomic_child_preserves_a_natural_nonzero_result():
    rc, body = _atomic_owned(
        [sys.executable, "-c",
         "import sys; print('MEASURED_CHILD_RED'); sys.exit(7)"],
        env=dict(os.environ))
    assert rc == 7
    assert "MEASURED_CHILD_RED" in body


def test_atomic_child_with_live_descendant_is_norecord_after_cleanup(tmp_path):
    """Natural root exit cannot erase unfinished owned work."""
    pid_file = tmp_path / "escaped.pid"
    grandchild = "import time; time.sleep(30)"
    child = (
        "import pathlib,subprocess,sys\n"
        f"p=subprocess.Popen([sys.executable,'-c',{grandchild!r}], "
        "start_new_session=True)\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))\n")
    with pytest.raises(AssertionError, match="OWNED_CHILD_NORECORD"):
        _atomic_owned([sys.executable, "-c", child], env=dict(os.environ))
    escaped_pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(escaped_pid, 0)


def test_atomic_policy_rejects_a_progress_log_before_launch(tmp_path):
    marker = tmp_path / "child-launched"
    result_path = tmp_path / "owned-result.json"
    progress_path = tmp_path / "progress.log"
    progress_path.touch()
    proc = subprocess.run(
        [sys.executable, str(OWNED), "--result", str(result_path),
         "--cwd", str(REPO), "--stall-grace", "1", "--poll", ".1",
         "--atomic", "--progress", str(progress_path), "--",
         sys.executable, "-c",
         f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        cwd=str(REPO), capture_output=True, text=True)
    assert proc.returncode == 2
    assert "not allowed with argument" in proc.stderr
    assert not marker.exists() and not result_path.exists()


def test_atomic_api_rejects_a_progress_log_before_launch(tmp_path):
    import _owned_process_supervisor as owned  # noqa: PLC0415

    marker = tmp_path / "api-child-launched"
    progress_path = tmp_path / "progress.log"
    progress_path.touch()
    record = owned.run_owned(
        [sys.executable, "-c",
         f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        REPO, dict(os.environ), progress_path=progress_path,
        stall_grace_s=1, poll_s=.1, output_progress=False)
    assert record.rc == 2
    assert record.launched is False
    assert record.outcome == "policy_refused"
    assert "INVALID_PROGRESS_POLICY" in str(record.problem)
    assert not marker.exists()


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


def test_each_real_checker_relays_its_exact_finite_manifest(
        clean, tmp_path, monkeypatch):
    calls = [
        (L_DOC, ("--corpus-may-be-absent", "--baseline",
                 _empty_register(tmp_path))),
        (EVIDENCE, ("--corpus-may-be-absent",)),
        (ROUTING, ("--root", str(REPO), "--corpus-may-be-absent")),
        (L4, ("audit-corpus", "--root", str(REPO),
              "--corpus-may-be-absent")),
    ]
    for prog, args in calls:
        relayed = []
        monkeypatch.setattr(
            _pytest_progress_plugin, "domain_progress",
            lambda scope, completed, total:
                relayed.append((scope, completed, total)))
        scope, units = _progress_plan(prog, args, str(clean))
        rc, out = _run(prog, *args, env_tree=str(clean))
        assert rc == 0, out
        assert relayed == [
            (scope, completed, len(units))
            for completed in range(1, len(units) + 1)
        ], (prog.name, units, relayed, out)


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


def test_routing_repository_index_failure_finishes_its_exact_progress_fsm(
        tmp_path):
    loose_root = tmp_path / "not-a-repository"
    loose_root.mkdir()
    rc, out = _run(ROUTING, "--root", str(loose_root),
                   "--corpus-may-be-absent")
    assert rc == 2, out
    assert "git could not list tracked files" in out, out
    assert "SEMANTIC_PROGRESS_NORECORD" not in out, (
        "the exact index-attempt unit was omitted from the child protocol")


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


# ── vibe-ic#1710 — the resolution must be a fact about the REPOSITORY ───────
def _fake_repo(tmp_path: Path) -> Path:
    """A checkout-shaped tree, with a corpus sitting ABOVE it."""
    outer = tmp_path / "outer"
    (outer / "benchmark-data" / "ic").mkdir(parents=True)     # the stranger
    repo = outer / "checkout"
    (repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs").mkdir(
        parents=True)
    return repo


def test_default_named_never_leaves_the_repository(tmp_path):
    """THE HOST-DEPENDENCE THIS FILE IS NAMED FOR.

    The three corpus-reading gates resolved their default root with an
    UNBOUNDED `here.parents` walk, which does not stop at the checkout. On a
    machine whose $HOME happens to carry a `benchmark-data/`, the gate scanned
    THAT tree and `resolve()` then declined the caller's pointer in favour of
    it — so the same commit produced different verdicts on different machines.
    MEASURED on main a4caccefe, same host, two clones: 15 failed under a
    checkout below $HOME (which carried a benchmark-data/) and 42 passed under
    one below /var/tmp (which did not).

    Bounded at the repository root, the stranger above the checkout is
    invisible and the answer depends only on the repository.
    """
    repo = _fake_repo(tmp_path)
    start = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    got = _corpus_loc.default_named(start, "benchmark-data/ic")
    assert not got.is_absolute() or repo in got.parents, (
        f"resolution escaped the repository: {got}")
    assert (tmp_path / "outer" / "benchmark-data" / "ic") != got, (
        "the corpus ABOVE the checkout was adopted — this is the host "
        "dependence the bound exists to remove")
    assert got == Path("benchmark-data/ic"), (
        "a repo that carries no corpus must return the LITERAL relative path, "
        "so resolve() follows the pointer and refuse() can name what it looked "
        f"for; got {got}")


def test_default_named_prefers_the_repositorys_OWN_corpus(tmp_path):
    """The bound must not break the in-repo case: a checkout that DOES carry
    the tree resolves to its own copy, not to the stranger above it."""
    repo = _fake_repo(tmp_path)
    (repo / "benchmark-data" / "ic").mkdir(parents=True)
    start = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    got = _corpus_loc.default_named(start, "benchmark-data/ic")
    assert got == repo / "benchmark-data" / "ic", got


def test_repo_root_stops_at_the_marker(tmp_path):
    """`vibe-ic-marketplace/` is the marker, not `.git` — a tarball export and
    a worktree without its gitdir are still the tree the gate is about."""
    repo = _fake_repo(tmp_path)
    start = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    assert _corpus_loc.repo_root(start) == repo
    assert _corpus_loc.repo_root(tmp_path) is None
