"""Routed-DEF population evidence must survive the corpus split and sharding."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Sequence

import pytest


PROGRAMS = Path(__file__).resolve().parents[1]
REPO = PROGRAMS.parents[3]
HELPER = REPO / "tools" / "ci" / "routed_def_corpus.py"
SHIPPED_HYGIENE = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
DISPATCH = REPO / "tools" / "ci" / "_gate_dispatch.sh"
ATTEST = PROGRAMS / "gate_process_attestation.py"
HDF = PROGRAMS / "hygiene_finding_delta.py"
ENV = "VIBE_IC_BENCHMARK_DATA"

# Completion evidence decides these tests.  An elapsed-time expiry would not
# prove either that git's index was read or that the dispatcher finished.
pytestmark = pytest.mark.timeout(0)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True,
        capture_output=True, text=True)


def _external(tmp_path: Path) -> Path:
    root = tmp_path / "published"
    root.mkdir()
    _git(root, "init", "-q")
    return root


def _routed(root: Path, design: str, version: str, *, tracked: bool) -> Path:
    path = (root / "ic" / design / version / "phase3" / "stage3" / "pnr"
            / "routed.def")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("VERSION 5.8 ;\nEND DESIGN\n", encoding="utf-8")
    if tracked:
        _git(root, "add", str(path.relative_to(root)))
    return path.resolve()


def _helper(pointer: str | None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop(ENV, None)
    if pointer is not None:
        env[ENV] = pointer
    return subprocess.run(
        ["python3", str(HELPER), "--repo", str(REPO)],
        cwd=str(REPO), env=env, capture_output=True, text=True)


def test_external_population_is_read_only_from_the_git_index(tmp_path):
    external = _external(tmp_path)
    tracked = _routed(external, "logic", "v1", tracked=True)
    untracked = _routed(external, "leftover", "v9", tracked=False)

    proc = _helper(str(external))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.splitlines() == [str(tracked)]
    assert str(untracked) not in proc.stdout, (
        "an untracked leftover entered the hygiene denominator; discovery "
        "must use the producer repository's index, not a filesystem walk")
    assert f"{ENV} overrides" in proc.stderr


def test_trusted_manifest_binds_population_argv_and_owned_receipts(tmp_path):
    external = _external(tmp_path)
    _routed(external, "logic", "v1", tracked=True)
    _git(external, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "corpus")
    sha = _git(external, "rev-parse", "HEAD").stdout.strip()
    output = tmp_path / "trusted-manifest.json"

    proc = subprocess.run([
        "python3", str(HELPER), "--repo", str(REPO),
        "--trusted-manifest", str(output), "--checkout", str(external),
        "--subject-repo", str(REPO), "--benchmark-sha", sha,
    ], cwd=str(REPO), capture_output=True, text=True)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    doc = json.loads(output.read_text(encoding="utf-8"))
    assert set(doc) == {
        "schema", "complete", "origin", "benchmark_data_sha", "corpora",
        "execution_receipts",
    }
    assert doc["schema"] == 1 and doc["complete"] is True
    assert doc["benchmark_data_sha"] == sha
    items = doc["corpora"][0]["items"]
    assert len(items) == 1 and items[0]["ordinal"] == 1
    assert items[0]["path"] == (
        "ic/logic/v1/phase3/stage3/pnr/routed.def")
    assert items[0]["mode"] == "100644"
    assert len(items[0]["gates"]) == 4
    receipts = doc["execution_receipts"]
    assert [row["label"] for row in receipts] == [
        row["label"] for row in items[0]["gates"]]
    assert all(row["complete"] is True
               and row["argv_sha256"] == gate["argv_sha256"]
               and row["returncode"] == row["owned"]["rc"]
               and row["owned"]["protocol"] == 1
               and row["owned"]["outcome"] == "natural"
               and row["owned"]["problem"] is None
               and row["owned"]["census_ok"] is True
               and row["owned"]["final_descendants"] == []
               for row, gate in zip(receipts, items[0]["gates"]))


def _transition_subject(root: Path, *, activate: bool) -> Path:
    """Materialize the exact checker/dispatcher bytes at a distinct root."""
    programs = root / "vibe-ic-marketplace/plugins/vibe-ic/programs"
    shutil.copytree(
        PROGRAMS, programs,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
    ci = root / "tools/ci"
    ci.mkdir(parents=True)
    shutil.copy2(DISPATCH, ci / DISPATCH.name)
    shutil.copy2(HELPER, ci / HELPER.name)
    gate = ci / "repo_hygiene_gates.sh"
    producer = (
        'GATE_DISPATCH_ATTEST_POPULATION=1 gate_dispatch_over '
        '"published cells carrying a routed DEF" _per '
        'python3 "$HERE/routed_def_corpus.py" --repo "$ROOT"'
        if activate else
        'gate_dispatch_over "published cells carrying a routed DEF" _per true'
    )
    gate.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -uo pipefail
        ROOT={str(root)!r}
        HERE="$ROOT/tools/ci"
        PG="$ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs"
        PLUGIN="$ROOT/vibe-ic-marketplace/plugins/vibe-ic"
        . "$HERE/_gate_dispatch.sh"
        gate_dispatch_init "$@"
        _per() {{
          local def="$1" cell design
          cell="${{def%/phase3/stage3/pnr/routed.def}}"
          design="$(basename "$(dirname "$cell")")"
          uncheckable_until 2027-02-28 "fixture has no macro LEF"
          run_tolerating_uncheckable "macro OBS not crossed ($design)" \
            "$PLUGIN" python3 programs/macro_obs_geometry_intersect_check.py "$cell"
          uncheckable_until 2027-02-28 "fixture may have no DRC evidence"
          run_tolerating_uncheckable "DRC PASS is not vacuous ($design)" \
            "$ROOT" python3 "$PG/drc_vacuous_pass_check.py" "$cell"
          uncheckable_until 2027-02-28 "fixture may have no step reports"
          run_tolerating_uncheckable "inner FAILs reach the verdict ($design)" \
            "$ROOT" python3 "$PG/step_internal_fail_bubble_up_check.py" "$cell"
          uncheckable_until 2027-02-28 "fixture has no preceding same-PDK run"
          run_tolerating_uncheckable "new tool diagnostic id ($design)" \
            "$PLUGIN" python3 programs/tool_diagnostic_id_gate.py "$cell"
        }}
        {producer}
        gate_dispatch_finish
        """), encoding="utf-8")
    gate.chmod(0o755)
    return gate


def test_shipped_hygiene_activates_the_attested_external_routed_producer():
    source = SHIPPED_HYGIENE.read_text(encoding="utf-8")
    callsite = re.compile(
        r'GATE_DISPATCH_ATTEST_POPULATION=1 gate_dispatch_over\s*\\\s*'
        r'"published cells carrying a routed DEF"\s*\\\s*'
        r'_per_published_cell_gates\s*\\\s*'
        r'python3 "\$HERE/routed_def_corpus\.py" --repo "\$ROOT"',
        re.MULTILINE,
    )
    assert callsite.search(source), (
        "the activation tree still enumerates only in-repo benchmark-data; "
        "the SHA-bound /corpus snapshot would be reported as an empty loop")


def _transition_summary(gate: Path, checkout: Path, sha: str,
                        output: Path) -> subprocess.CompletedProcess[str]:
    root = gate.parents[2]
    attest = output.with_suffix(".attest.jsonl")
    env = os.environ.copy()
    env.update({
        ENV: str(checkout),
        "GATEKEEPER_BENCHMARK_DATA_SHA": sha,
        "GATEKEEPER_HYGIENE_JOBS": "1",
        "GATE_DISPATCH_ATTESTATION_HELPER": str(
            root / "vibe-ic-marketplace/plugins/vibe-ic/programs" /
            "gate_process_attestation.py"),
        "GATE_DISPATCH_ATTESTATION_FILE": str(attest),
    })
    return subprocess.run(
        ["bash", str(gate), "--summary-json", str(output)],
        cwd=str(root), env=env, capture_output=True, text=True)


def test_real_distinct_root_receipts_authorize_only_the_exact_transition(
        tmp_path):
    """Parent A2 receipts and candidate B2 attestations agree by semantics.

    The two benchmark worktrees and the trusted/subject program roots are all
    distinct.  A candidate-local routed DEF is planted as the laundering
    control: bound mode must still scan only the externally attested checkout.
    """
    benchmark_a = _external(tmp_path)
    _routed(benchmark_a, "logic", "v1", tracked=True)
    _git(benchmark_a, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "corpus")
    sha = _git(benchmark_a, "rev-parse", "HEAD").stdout.strip()
    benchmark_b = tmp_path / "published-b"
    _git(tmp_path, "clone", "-q", str(benchmark_a), str(benchmark_b))

    base_root = tmp_path / "phase1-base"
    candidate_root = tmp_path / "phase2-candidate"
    base_gate = _transition_subject(base_root, activate=False)
    candidate_gate = _transition_subject(candidate_root, activate=True)
    _routed(candidate_root / "benchmark-data", "candidate_fake", "v9",
            tracked=False)
    base_record = tmp_path / "base.json"
    candidate_record = tmp_path / "candidate.json"
    base_run = _transition_summary(base_gate, benchmark_a, sha, base_record)
    candidate_run = _transition_summary(
        candidate_gate, benchmark_b, sha, candidate_record)
    assert base_run.returncode == 2, base_run.stdout + base_run.stderr
    # This deliberately tiny DEF has no macro LEF/reports/baseline, so all
    # four real checkers truthfully return rc 2.  The dispatcher preserves
    # those as bounded NOT_CHECKED rows and the micro-suite itself is
    # DECIDED-NOTHING (rc 2); HDF may still authorize the declaration
    # transition because it exact-compares the parent receipts and never
    # mistakes those rows for PASS.
    assert candidate_run.returncode == 2, (
        candidate_run.stdout + candidate_run.stderr)

    base_doc = json.loads(base_record.read_text(encoding="utf-8"))
    candidate_doc = json.loads(candidate_record.read_text(encoding="utf-8"))
    assert base_doc["corpus_inputs"] == {"benchmark_data_sha": sha}
    assert base_doc["declared"] == base_doc["ran"] == 1
    assert base_doc["process_attestations"] == []
    assert candidate_doc["corpora"][0]["items"] == 1
    assert candidate_doc["declared"] == candidate_doc["ran"] == 4
    assert len(candidate_doc["process_attestations"]) == 4
    assert not any("candidate_fake" in row["label"]
                   for row in candidate_doc["gates"])

    evidence = tmp_path / "trusted-transition.json"
    parent = subprocess.run([
        "python3", str(HELPER), "--repo", str(REPO),
        "--trusted-manifest", str(evidence),
        "--checkout", str(benchmark_a),
        "--subject-repo", str(candidate_root),
        "--benchmark-sha", sha,
    ], cwd=str(REPO), capture_output=True, text=True)
    assert parent.returncode == 0, parent.stdout + parent.stderr

    compared = subprocess.run([
        "python3", str(HDF), "--base", str(base_record),
        "--candidate", str(candidate_record),
        "--base-host", "same-host", "--candidate-host", "same-host",
        "--trusted-transition-evidence", str(evidence),
    ], cwd=str(REPO), capture_output=True, text=True)
    assert compared.returncode == 0, compared.stdout + compared.stderr
    assert "exact corpus transition" in compared.stdout


def test_an_indexed_but_unmaterialized_def_is_undetermined(tmp_path):
    external = _external(tmp_path)
    routed = _routed(external, "logic", "v1", tracked=True)
    routed.unlink()

    proc = _helper(str(external))

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stdout == ""
    assert "index publishes" in proc.stderr
    assert "not complete corpus evidence" in proc.stderr


def test_an_indexed_routed_def_symlink_is_not_a_corpus_file(tmp_path):
    external = _external(tmp_path)
    outside = tmp_path / "mutable-outside.def"
    outside.write_text("VERSION 5.8 ;\nEND DESIGN\n", encoding="utf-8")
    routed = (external / "ic/logic/v1/phase3/stage3/pnr/routed.def")
    routed.parent.mkdir(parents=True)
    routed.symlink_to(outside)
    _git(external, "add", str(routed.relative_to(external)))

    proc = _helper(str(external))

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stdout == ""
    assert "mode 120000" in proc.stderr
    assert "not a materialized regular file" in proc.stderr


@pytest.mark.parametrize("kind", ["missing", "non_git"])
def test_a_broken_or_non_git_pointer_is_undetermined_not_empty(
        tmp_path, kind):
    pointer = tmp_path / kind
    if kind == "non_git":
        (pointer / "ic").mkdir(parents=True)

    proc = _helper(str(pointer))

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stdout == "", "producer diagnostics must not become corpus items"
    assert "UNDETERMINED" in proc.stderr
    assert "NO_CORPUS" not in proc.stderr
    if kind == "non_git":
        assert "not a git checkout" in proc.stderr


def test_an_unconfigured_moved_corpus_is_explicit_no_corpus():
    """Still NO_CORPUS, still never a pass — and no longer rc 0.

    `_corpus_location.refuse(may_be_absent=True)` answers rc 0 because for most
    gates "the published tree is not in this repository" is not a finding
    against anything, and vibe-ic#1764 deliberately left that opt-in standing.
    THIS PROGRAM IS A POPULATION PRODUCER, where rc 0 already means something
    else: "I read an index and it publishes none".  So the absent corpus leaves
    with its own code and the dispatcher gives it its own row.
    """
    proc = _helper(None)

    assert proc.returncode == _no_corpus_rc(), proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        "an absent corpus exited 0 with an empty stdout, which is exactly what "
        "a corpus that WAS read and holds no routed DEF exits with — the two "
        "states are byte-indistinguishable to gate_dispatch_over (vibe-ic#1764)")
    assert proc.stdout == ""
    assert "NO_CORPUS" in proc.stderr and "NOTHING WAS SCANNED" in proc.stderr
    # It must NAME what it looked for, or "not found" is unactionable.
    assert "benchmark-data" in proc.stderr and ENV in proc.stderr
    assert "MEASURED EMPTY" not in proc.stderr


# --- vibe-ic#1764: an ABSENT corpus and a MEASURED-EMPTY one -----------------
#
# State A  nothing at benchmark-data/, VIBE_IC_BENCHMARK_DATA unset
#          -> nothing was opened              -> the ABSENCE of a measurement
# State B  a corpus resolved, its index carries no routed DEF
#          -> it WAS read, and it holds none  -> a measurement, whose value is 0
#
# Both were `rc 0, 0 items` and both got the one row `corpus … is EMPTY —
# nothing was checked over it`. Both are still NOT CHECKED and both still
# BLOCK; what changed is that they no longer share a sentence. Every assertion
# below is pinned in BOTH directions on purpose: a test that only exercises one
# state leaves the collapse half-alive, because the collapse is a statement
# about a PAIR.

_ABSENT_RC_DECL = re.compile(r"^GATE_DISPATCH_ABSENT_RC=(\d+)$", re.MULTILINE)


def _no_corpus_rc() -> int:
    """The producer's own constant, imported rather than typed here."""
    namespace: dict = {}
    for line in HELPER.read_text(encoding="utf-8").splitlines():
        if line.startswith("NO_CORPUS_RC"):
            exec(line, namespace)          # noqa: S102 - a literal assignment
            return int(namespace["NO_CORPUS_RC"])
    raise AssertionError(
        "tools/ci/routed_def_corpus.py declares no NO_CORPUS_RC, so an absent "
        "corpus has no exit code of its own and must be reaching "
        "gate_dispatch_over as the empty one (vibe-ic#1764)")


def test_the_absent_exit_code_is_one_number_in_two_languages():
    """A shell constant and a Python constant that must agree is what drifts."""
    declared = _ABSENT_RC_DECL.search(DISPATCH.read_text(encoding="utf-8"))
    assert declared, (
        "the dispatcher declares no GATE_DISPATCH_ABSENT_RC, so it cannot tell "
        "'no corpus was opened' from 'a corpus was read and holds none'")
    assert int(declared.group(1)) == _no_corpus_rc()
    # Neither may collide with a code that already means something else: 0 is
    # a measured population, 2 is UNDETERMINED, 1 is a finding.
    assert _no_corpus_rc() not in (0, 1, 2)


def _subject_repo(tmp_path: Path) -> Path:
    """The minimum tree `routed_def_corpus.main()` needs, carrying NO corpus."""
    root = tmp_path / "subject"
    programs = root / "vibe-ic-marketplace/plugins/vibe-ic/programs"
    programs.mkdir(parents=True)
    shutil.copy2(PROGRAMS / "_corpus_location.py",
                 programs / "_corpus_location.py")
    assert not (root / "benchmark-data").exists()
    return root


def _read_but_empty_corpus(tmp_path: Path) -> Path:
    """A resolved corpus whose INDEX carries no routed DEF — state B.

    The index is deliberately NOT empty. A checkout that tracks nothing at all
    would leave "git had nothing to say" as an alternative explanation for the
    zero, and the state under test is the one where git was asked, answered,
    and the answer contains no `*/*/phase3/stage3/pnr/routed.def`.
    """
    root = _external(tmp_path)
    published = root / "ic" / "logic" / "v1" / "phase3" / "stage3" / "pnr"
    published.mkdir(parents=True)
    (published.parent.parent / "reports" / "drc").mkdir(parents=True)
    (published.parent.parent / "reports" / "drc" / "summary.txt").write_text(
        "0 violations\n", encoding="utf-8")
    _git(root, "add", "-A")
    listed = _git(root, "ls-files").stdout.split()
    assert listed and not any(x.endswith("routed.def") for x in listed), listed
    return root


def test_an_absent_corpus_and_a_read_but_empty_one_do_not_share_a_verdict(
        tmp_path):
    """The producer half of vibe-ic#1764, pinned on BOTH states at once."""
    subject = _subject_repo(tmp_path)
    corpus = _read_but_empty_corpus(tmp_path)

    def run(pointer):
        env = os.environ.copy()
        env.pop(ENV, None)
        env.pop("GATEKEEPER_BENCHMARK_DATA_SHA", None)
        if pointer is not None:
            env[ENV] = pointer
        return subprocess.run(
            ["python3", str(HELPER), "--repo", str(subject)],
            cwd=str(subject), env=env, capture_output=True, text=True)

    absent = run(None)                    # state A
    empty = run(str(corpus))              # state B

    # Neither produced an item, and that is the whole trap: the population is
    # the same integer and the states are not the same state.
    assert absent.stdout == empty.stdout == ""

    # 1. DIFFERENT VERDICTS.
    assert empty.returncode == 0, empty.stdout + empty.stderr
    assert absent.returncode == _no_corpus_rc(), absent.stdout + absent.stderr
    assert absent.returncode != empty.returncode, (
        "an absent corpus and a corpus that was read and holds none still "
        "exit with the same code, so gate_dispatch_over cannot tell a "
        "measurement of zero from the absence of a measurement")

    # 2. DIFFERENT MESSAGES, each naming the thing that makes it that state.
    assert "NO_CORPUS" in absent.stderr
    assert "NOTHING WAS SCANNED" in absent.stderr
    assert "benchmark-data" in absent.stderr, "it must name what it looked for"
    assert "MEASURED EMPTY" not in absent.stderr

    assert "MEASURED EMPTY" in empty.stderr
    assert str(corpus.resolve()) in empty.stderr, (
        "the empty corpus must NAME the index it read; 'it was empty' about an "
        "unnamed tree is not a measurement anybody can check")
    assert "NO_CORPUS" not in empty.stderr
    assert "NOTHING WAS SCANNED" not in empty.stderr

    # 3. NEITHER IS A PASS, and neither is UNDETERMINED-by-broken-pointer.
    assert absent.returncode != 2 and empty.returncode != 2
    assert "UNDETERMINED" not in absent.stderr


def test_the_dispatcher_gives_absent_and_empty_different_rows(tmp_path):
    """The dispatcher half: two states, two rows, both still blocking.

    Driven through the REAL producer and the REAL `_gate_dispatch.sh`, because
    the defect was that these two states are byte-indistinguishable AT THE
    DISPATCHER — a fixture that hand-picks an exit code could not have shown it.
    """
    subject = _subject_repo(tmp_path)
    corpus = _read_but_empty_corpus(tmp_path)
    producer = f'python3 {str(HELPER)!r} --repo {str(subject)!r}'
    empty_label = ('corpus "an observed corpus" is EMPTY — nothing was '
                   'checked over it')
    absent_label = ('corpus "an observed corpus" was NOT FOUND — nothing was '
                    'opened to check')

    empty_root = tmp_path / "run-empty"
    absent_root = tmp_path / "run-absent"
    empty_root.mkdir()
    absent_root.mkdir()
    e_proc, e_doc, e_att, e_prog = _dispatch_run(
        empty_root, producer, empty_label, "empty", pointer=str(corpus))
    a_proc, a_doc, a_att, a_prog = _dispatch_run(
        absent_root, producer, absent_label, "absent", pointer=None)

    # THE ROWS ARE DIFFERENT — the label is the gate's identity, so this is the
    # assertion the whole issue is about.
    assert [g["label"] for g in e_doc["gates"]] == [empty_label], e_doc["gates"]
    assert [g["label"] for g in a_doc["gates"]] == [absent_label], a_doc["gates"]
    assert empty_label != absent_label
    assert not any(g["label"] == empty_label for g in a_doc["gates"]), (
        "a corpus nothing opened is still reported as the corpus that was read "
        "and holds none (vibe-ic#1764)")

    # …and so is the expansion state a machine consumer reads.
    assert e_doc["corpora"] == [{"name": "an observed corpus", "items": 0,
                                 "gates": 1, "expansion": "EXPANDED"}]
    assert a_doc["corpora"] == [{"name": "an observed corpus", "items": 0,
                                 "gates": 1, "expansion": "NO_CORPUS"}]

    # …and the sentence a human reads.
    e_text = e_proc.stdout + e_proc.stderr
    a_text = a_proc.stdout + a_proc.stderr
    assert "EMPTY CORPUS" in e_text and "CORPUS NOT FOUND" not in e_text
    assert "CORPUS NOT FOUND" in a_text and "EMPTY CORPUS" not in a_text
    assert "ABSENCE of a measurement" in a_text
    assert "CORPUS PRODUCER FAILED" not in a_text, (
        "an absent corpus is not a broken producer; the producer worked and "
        "reported, correctly, that there was nothing to open")

    # NEITHER BECOMES A PASS. Both are unexempted, process-attested, blocking
    # NOT_CHECKED rows and both refuse the run — this is what #1763 relies on.
    for proc, doc, att, prog, label in (
            (e_proc, e_doc, e_att, e_prog, empty_label),
            (a_proc, a_doc, a_att, a_prog, absent_label)):
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert doc["gates"][0]["state"] == "NOT_CHECKED"
        assert doc["not_checked_unexempted"] == [label]
        assert doc["gates"][0]["exempt_until"] is None
        assert doc["wiring_errors"] == []
        assert len(att) == len(prog) == 1
        assert att[0]["label"] == label
        assert att[0]["complete"] is True
        assert att[0]["returncode"] == 2
        assert prog[0]["semantic_sha256"] == att[0]["semantic_sha256"]

    # The two attested bodies differ, so the evidence a landing keeps is not
    # the same evidence for the two states either.
    assert e_att[0]["semantic_sha256"] != a_att[0]["semantic_sha256"]


def test_a_producer_that_claims_absence_and_prints_items_is_a_failure(tmp_path):
    """The quiet row may not be worn by a partial population.

    `exit 3` means "I opened nothing". A producer that also printed items has
    contradicted itself, and the safe reading of a contradiction is the one
    that says the denominator is unknown — never the one that says nobody
    looked, which would let a truncated population past as an absence.
    """
    label = 'corpus "an observed corpus" producer FAILED — denominator unknown'
    proc, doc, attestations, progress = _dispatch_run(
        tmp_path, "bash -c 'printf %s\\n /a/routed.def; exit 3'", label,
        "contradiction")
    text = proc.stdout + proc.stderr

    assert proc.returncode == 2, text
    assert "CORPUS PRODUCER FAILED" in text
    assert "CORPUS NOT FOUND" not in text
    assert doc["corpora"][0]["expansion"] == "PRODUCER_FAILED"
    assert doc["corpora"][0]["items"] == 1
    assert label in [g["label"] for g in doc["gates"]]


def test_two_versions_of_one_design_refuse_before_duplicate_gate_owners(
        tmp_path):
    external = _external(tmp_path)
    _routed(external, "logic", "v1", tracked=True)
    _routed(external, "logic", "v2", tracked=True)

    proc = _helper(str(external))

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stdout == ""
    assert "more than one routed-DEF version" in proc.stderr
    assert "two-phase identity migration" in proc.stderr


def _dispatch_script(root: Path, producer: str, *, preamble: str = "") -> Path:
    script = root / "gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT={str(root)!r}
        . {str(DISPATCH)!r}
        gate_dispatch_init "$@"
        _body() {{ run "per item ($1)" "$ROOT" true; }}
        {preamble}gate_dispatch_over "an observed corpus" _body {producer}
        gate_dispatch_finish
        """), encoding="utf-8")
    return script


def _dispatch_run(root: Path, producer: str, owned_label: str,
                  stem: str, *, attest_population: bool = True,
                  preamble: str = "", also_owned: Sequence[str] = (),
                  pointer: str | None = None):
    script = _dispatch_script(root, producer, preamble=preamble)
    labels = root / f"{stem}.labels"
    labels.write_text("\n".join([owned_label, *also_owned]) + "\n",
                      encoding="utf-8")
    summary = root / f"{stem}.summary.json"
    attest = root / f"{stem}.attest.jsonl"
    progress = root / f"{stem}.progress.jsonl"
    env = os.environ.copy()
    # The corpus pointer is set HERE and nowhere else, so a developer who has
    # one exported cannot decide which state a producer under test observes.
    env.pop(ENV, None)
    env.pop("GATEKEEPER_BENCHMARK_DATA_SHA", None)
    if pointer is not None:
        env[ENV] = pointer
    env.update({
        "GATEKEEPER_HYGIENE_JOBS": "1",
        "GATE_DISPATCH_ATTESTATION_HELPER": str(ATTEST),
        "GATE_DISPATCH_ATTESTATION_FILE": str(attest),
        "GATE_DISPATCH_PROGRESS_FILE": str(progress),
    })
    if attest_population:
        env["GATE_DISPATCH_ATTEST_POPULATION"] = "1"
    else:
        env.pop("GATE_DISPATCH_ATTEST_POPULATION", None)
    proc = subprocess.run(
        ["bash", str(script), "--shard", "0/2", "--shard-labels",
         str(labels), "--summary-json", str(summary)],
        cwd=str(root), env=env, capture_output=True, text=True)
    doc = json.loads(summary.read_text(encoding="utf-8"))
    attestations = ([json.loads(line) for line in attest.read_text().splitlines()]
                    if attest.is_file() else [])
    progress_rows = ([json.loads(line) for line in progress.read_text().splitlines()]
                     if progress.is_file() else [])
    return proc, doc, attestations, progress_rows


def test_empty_population_has_one_shard_owner_attestation_and_progress(tmp_path):
    label = ('corpus "an observed corpus" is EMPTY — nothing was checked '
             'over it')
    owner = _dispatch_run(tmp_path, "true", label, "owner")
    other = _dispatch_run(tmp_path, "true", "a different label", "other")

    proc, doc, attestations, progress = owner
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert doc["gates"][0]["state"] == "NOT_CHECKED"
    assert doc["not_checked_unexempted"] == [label]
    assert doc["wiring_errors"] == []
    assert len(attestations) == len(progress) == 1
    assert attestations[0]["complete"] is True
    assert attestations[0]["label"] == label
    assert attestations[0]["returncode"] == 2
    assert progress[0]["semantic_sha256"] == attestations[0]["semantic_sha256"]

    proc, doc, attestations, progress = other
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["gates"][0]["state"] == "OTHER_SHARD"
    assert attestations == progress == []


def test_default_empty_population_preserves_legacy_no_process_shape(tmp_path):
    """Phase 1 installs the primitive without changing main's declaration."""
    label = ('corpus "an observed corpus" is EMPTY — nothing was checked '
             'over it')
    proc, doc, attestations, progress = _dispatch_run(
        tmp_path, "true", label, "legacy", attest_population=False)

    # With no ordinary gate this synthetic-only micro-suite still refuses for
    # DECIDED NOTHING, exactly as legacy did.  In the real hygiene suite the
    # ordinary decided rows make the phase-1 aggregate rc0 (pinned separately).
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert doc["declared"] == 1
    assert doc["gates"] == [{
        "label": label,
        "state": "NOT_CHECKED",
        "seconds": 0,
        "corpus": "an observed corpus",
        "corpus_item": 0,
        "corpus_items": 0,
        "exempt_until": None,
        "exempt_reason": None,
        "exemption_expired": False,
        "scope": None,
    }]
    assert doc["not_checked_unexempted"] == [label]
    assert attestations == progress == []


def test_failed_producer_is_a_distinct_blocking_attested_result(tmp_path):
    label = 'corpus "an observed corpus" producer FAILED — denominator unknown'
    proc, doc, attestations, progress = _dispatch_run(
        tmp_path, "bash -c 'exit 7'", label, "failed")
    text = proc.stdout + proc.stderr

    assert proc.returncode == 2, text
    assert "CORPUS PRODUCER FAILED" in text
    assert "EMPTY CORPUS" not in text
    assert doc["corpora"][0]["expansion"] == "PRODUCER_FAILED"
    assert doc["gates"][0]["state"] == "NOT_CHECKED"
    assert doc["not_checked_unexempted"] == [label]
    assert len(attestations) == len(progress) == 1
    assert attestations[0]["returncode"] == 2


# --------------------------------------------------------------------------
# THE ROUTED-DEF CORPUS IS EMPTY, AND THE RULE THAT KEEPS THAT HONEST WAS
# ITSELF UNPINNED.
#
# Adjudicated 2026-08-21 (`docs/findings/2026-08-21-routed-def-corpus-is-empty-
# adjudication.md`): every published cell this corpus ever selected was
# WITHDRAWN from `https://github.com/vibeic/benchmark-data` on 2026-08-20,
# because not one of the four was a pass. So the population is 0, the row is
# `NOT CHECKED (rc 2, BLOCKING; no exemption)`, and that is CORRECT rather than
# a defect to be closed.
#
# The rule that makes it correct is absolute: an empty corpus stays rc 2 NOT
# CHECKED and must never become a pass. There is exactly ONE way it could stop
# blocking — buying the dated tolerance a human may buy for an ordinary gate —
# and exactly one mechanism refuses that: the mode-2 arm in `_dispatch`.
#
# MEASURED: deleting that arm left the whole suite green. Nothing anywhere
# asserted it, so the four lines standing between this corpus and a silently
# exempted row were a free edit. These two tests are that assertion.
# --------------------------------------------------------------------------

_EMPTY_LABEL = ('corpus "an observed corpus" is EMPTY — nothing was checked '
                'over it')


def test_a_population_refusal_cannot_buy_an_uncheckable_exemption(tmp_path):
    """An exemption over an empty population is a WIRING ERROR, not tolerance.

    Without the mode-2 arm the exemption is simply consumed and RECORDED, which
    is worse than it looks: `gate_dispatch_finish` counts a NOT_CHECKED row as
    unexempted only when `GATE_EX_UNTIL` is empty, so a recorded date removes
    the row from `not_checked_unexempted` and the run stops blocking on it.
    The wiring error is the only thing left refusing the run.
    """
    # ONE ORDINARY DECIDED GATE, and it is load-bearing. Without it the
    # micro-suite refuses for DECIDED NOTHING whatever the exemption does, and
    # the test would pass over a run that never exercised the rule. With it the
    # sweep has a verdict, so an exemption that IS accepted reaches the
    # `notchecked != 0` branch — which exits 0. That is the real consequence in
    # the real hygiene set, where ~70 rows decide.
    decided = "an ordinary decided gate"
    proc, doc, _attestations, _progress = _dispatch_run(
        tmp_path, "true", _EMPTY_LABEL, "exempted", also_owned=(decided,),
        preamble=(f'run "{decided}" "$ROOT" true\n        '
                  'uncheckable_until 2099-01-01 "an empty corpus is not a '
                  'reason to stop looking"\n        '))
    text = proc.stdout + proc.stderr
    states = {gate["label"]: gate for gate in doc["gates"]}

    assert states[decided]["state"] == "PASS", doc
    assert states[_EMPTY_LABEL]["state"] == "NOT_CHECKED", doc
    assert "cannot consume an uncheckable exemption" in text, (
        "an empty population accepted a dated exemption; the one mechanism "
        "keeping 'never a pass' true has been removed")
    assert any("cannot consume an uncheckable exemption" in str(err)
               for err in doc["wiring_errors"]), doc["wiring_errors"]
    # THE OUTCOME, not only the sentence: a sweep whose only unchecked row is
    # the empty corpus must still refuse. Accepting the exemption makes this 0.
    assert proc.returncode == 2, text
    # THE HAZARD, REPAIRED (vibe-ic#1770) AND PINNED FROM THE OTHER SIDE.
    # These two lines pinned the defect as current behaviour: the refused date
    # WAS recorded on the row and the row DID leave `not_checked_unexempted`,
    # leaving the wiring error as the whole defence. `_dispatch` now clears the
    # exemption it refuses, so the same two facts are asserted in the direction
    # the dispatcher's own message claims -- nothing downstream may read this
    # row as one that legitimately bought tolerance.
    assert states[_EMPTY_LABEL]["exempt_until"] is None, doc
    assert states[_EMPTY_LABEL]["exempt_reason"] is None, doc
    assert states[_EMPTY_LABEL]["exemption_expired"] is False, doc
    assert doc["not_checked_unexempted"] == [_EMPTY_LABEL], doc


def test_the_shipped_producer_over_an_empty_corpus_blocks_and_never_passes(
        tmp_path):
    """State B end to end: a corpus that IS read and publishes no routed DEF.

    `_external` is a real git checkout with an empty index — which is exactly
    what `vibeic/benchmark-data` is for this corpus since the 2026-08-20
    withdrawal. Driven through the SHIPPED producer rather than a `true` stub,
    so the pinned outcome belongs to the program the hygiene script wires.
    """
    external = _external(tmp_path)
    # No commit: `_index_paths` reads git's INDEX, and an initialised checkout
    # with an empty index is precisely "a corpus that was read and holds none".
    (external / "ic").mkdir()
    producer = (f"env VIBE_IC_BENCHMARK_DATA={str(external)!r} "
                f"python3 {str(HELPER)!r} --repo {str(REPO)!r}")

    proc, doc, attestations, _progress = _dispatch_run(
        tmp_path, producer, _EMPTY_LABEL, "shipped")
    text = proc.stdout + proc.stderr

    # The producer looked, and found none. That is rc 0 with an empty
    # population — NOT a producer failure, and NOT a pass.
    assert doc["corpora"][0]["items"] == 0
    assert doc["corpora"][0]["expansion"] == "EXPANDED"
    assert doc["gates"][0]["state"] == "NOT_CHECKED"
    assert doc["not_checked_unexempted"] == [_EMPTY_LABEL], doc
    assert doc["gates"][0]["exempt_until"] is None
    assert proc.returncode == 2, text
    assert attestations and attestations[0]["returncode"] == 2

    # THE ATTESTED BODY MUST STAY HOST-INDEPENDENT. `gatekeeper-verify-merge.sh`
    # compares the two arms' semantic records BYTE FOR BYTE, so an absolute path
    # or a producer diagnostic reaching the attestation would make a correct
    # transition fail on nothing but a differing tmpdir. `_gate_dispatch.sh`
    # deliberately does not re-execute the producer for the refusal, and the
    # producer's own explanation of its measured zero goes to stderr — this is
    # the assertion that both stay true.
    blob = json.dumps(attestations)
    assert str(external) not in blob and str(tmp_path) not in blob, blob
    assert "0 routed DEF(s)" not in blob and "EMPTY POPULATION" not in blob, blob


def test_a_corpus_that_was_read_and_holds_none_says_so(tmp_path):
    """The state the landing path is IN was the one that printed nothing.

    `gatekeeper_review` binds the corpus before the hygiene set runs, so the
    blocking row on `main` comes from a corpus that WAS opened. That branch
    emitted only the resolution note and exited: the less informative outcome
    (no corpus anywhere) got a full sentence with a cause and a remedy, and the
    more informative one got silence. rc, stdout and the blocking are unchanged
    by this; only the reader gains the sentence.
    """
    external = _external(tmp_path)
    (external / "ic").mkdir()

    proc = _helper(str(external))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout == "", "prose on stdout would become a corpus item"
    assert "0 routed DEF(s)" in proc.stderr, (
        "a corpus that was read and holds none said nothing about it")
    assert "EMPTY POPULATION, not a clean one" in proc.stderr
    assert "phase3/stage3/pnr/routed.def" in proc.stderr, (
        "the sentence must name what a member looks like")
    # NOT the absent-corpus sentence: this corpus exists and was read.
    assert "NO_CORPUS" not in proc.stderr
    assert "UNDETERMINED" not in proc.stderr

def test_the_shipped_hygiene_script_reports_this_checkout_as_NOT_FOUND(tmp_path):
    """The state this repository is ACTUALLY in, pinned end to end.

    Everything above drives the producer and the dispatcher directly, over a
    corpus a fixture built. This one runs the SHIPPED
    `tools/ci/repo_hygiene_gates.sh` against THIS checkout, because the defect
    vibe-ic#1764 filed was not that a fixture said the wrong thing — it was that
    main's own hygiene run did, on every developer machine with no pointer set.

    `--list` drives the real `_dispatch` and writes the record through the same
    path a real run uses, so this measures the shipped wiring without paying for
    a gate execution.
    """
    if (REPO / "benchmark-data" / "ic").is_dir():
        pytest.skip("this checkout carries a corpus of its own, so it is in "
                    "state B and cannot exercise state A")
    record = tmp_path / "record.json"
    env = os.environ.copy()
    env.pop(ENV, None)
    env.pop("GATEKEEPER_BENCHMARK_DATA_SHA", None)
    proc = subprocess.run(
        ["bash", str(SHIPPED_HYGIENE), "--list", "--summary-json", str(record)],
        cwd=str(REPO), env=env, capture_output=True, text=True)
    assert proc.returncode == 0, (proc.stdout[-2000:] + proc.stderr[-2000:])

    doc = json.loads(record.read_text(encoding="utf-8"))
    corpus = "published cells carrying a routed DEF"
    assert [c for c in doc["corpora"] if c["name"] == corpus] == [
        {"name": corpus, "items": 0, "gates": 1, "expansion": "NO_CORPUS"}], (
        doc["corpora"])

    labels = [g["label"] for g in doc["gates"] if g.get("corpus") == corpus]
    assert labels == [
        f'corpus "{corpus}" was NOT FOUND — nothing was opened to check'], labels
    assert not any("is EMPTY" in label for label in labels), (
        "the shipped hygiene script still reports a corpus that nothing opened "
        "under the row for a corpus that WAS read and holds none — this is the "
        "exact sentence vibe-ic#1764 was filed about, on the real wiring")


# --- vibe-ic#1764: the ONE place the refusal could become a pass ------------
#
# `gate_dispatch_finish` refuses rc 2 in both states, and the issue said so. But
# `repo_hygiene_parallel._summary_rc` — the CLOSING rc of the parallel hygiene
# DAG — waives exactly one unexempted NOT_CHECKED: the phase-1 bootstrap row for
# a corpus that was READ and publishes nothing. Because an absent corpus arrived
# wearing that row's label and that row's `expansion`, the waiver covered it too,
# and `_summary_rc` returned 0 over a corpus nothing opened.
#
# RE-MEASURED 2026-08-22, this host, real producer through real
# `_gate_dispatch.sh`, on the commit before the fix and on the tree that carries
# it:
#
#     81cd5321b (before)  ABSENT -> _summary_rc 0    read-empty -> 0
#     a4caccefe (after)   ABSENT -> _summary_rc 2    read-empty -> 0
#
# LATENT, NOT LIVE, and this comment does not pretend otherwise: the only
# production caller of `repo_hygiene_parallel` binds the corpus before the set
# and refuses rc 2 if it cannot, so state A never reached the waiver in a real
# review or landing. `gate_dispatch_finish` -- the closing rc of the shipped
# `repo_hygiene_gates.sh` that `lane_hygiene` runs -- measured 2 in BOTH states
# on BOTH commits, so no lane's exit code moved. What is pinned here is that the
# waiver no longer DEPENDS on that one binding being right.
#
# This is the assertion that makes "do not make either state a pass" true, so it
# is driven end to end. A hand-built record cannot show it: on `origin/main` the
# defect is precisely that the absent state is HANDED the empty row's label, and
# a fixture that types the right label in has already fixed the bug it is testing.

_REAL_CORPUS = "published cells carrying a routed DEF"


def _hygiene_dag_record(tmp_path: Path, stem: str, pointer: str | None):
    """A real dispatch record over the REAL corpus name, plus one green gate.

    The green gate is load-bearing: `_summary_rc` returns 2 for a run that
    decided nothing at all, which would mask the waiver either way.
    """
    import repo_hygiene_parallel as P

    subject = _subject_repo(tmp_path / stem)
    root = tmp_path / f"run-{stem}"
    root.mkdir()
    script = root / "gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT={str(root)!r}
        . {str(DISPATCH)!r}
        gate_dispatch_init "$@"
        run 'a green gate' "$ROOT" python3 -c "print('[PASS] 1 item')"
        _body() {{ run "per cell ($1)" "$ROOT" true; }}
        GATE_DISPATCH_ATTEST_POPULATION=1 gate_dispatch_over \\
          {_REAL_CORPUS!r} _body python3 {str(HELPER)!r} --repo {str(subject)!r}
        gate_dispatch_finish
        """), encoding="utf-8")

    labels = root / "own.labels"
    summary = root / "summary.json"
    env = os.environ.copy()
    env.pop(ENV, None)
    env.pop("GATEKEEPER_BENCHMARK_DATA_SHA", None)
    if pointer is not None:
        env[ENV] = pointer
    env.update({
        "GATEKEEPER_HYGIENE_JOBS": "1",
        "GATE_DISPATCH_ATTESTATION_HELPER": str(ATTEST),
        "GATE_DISPATCH_ATTESTATION_FILE": str(root / "a.jsonl"),
        "GATE_DISPATCH_PROGRESS_FILE": str(root / "p.jsonl"),
        "GATE_DISPATCH_OWNED_LABELS_FILE": str(labels),
    })
    # Discover the row the dispatcher records, then own every gate, so this
    # single-shard run is complete and `_summary_rc` judges coverage, not
    # ownership.
    labels.write_text("", encoding="utf-8")
    subprocess.run(["bash", str(script), "--list", "--summary-json",
                    str(summary)], env=env, capture_output=True, text=True)
    listed = json.loads(summary.read_text(encoding="utf-8"))
    labels.write_text(
        "\n".join(g["label"] for g in listed["gates"]) + "\n", encoding="utf-8")

    proc = subprocess.run(["bash", str(script), "--summary-json", str(summary)],
                          env=env, capture_output=True, text=True)
    doc = json.loads(summary.read_text(encoding="utf-8"))
    return proc, doc, P._summary_rc(doc)


def test_an_absent_corpus_does_not_close_the_hygiene_dag_green(tmp_path):
    """Both states through the real wiring, and only one of them is waivable."""
    corpus = _read_but_empty_corpus(tmp_path)

    a_proc, a_doc, a_rc = _hygiene_dag_record(tmp_path, "absent", None)
    b_proc, b_doc, b_rc = _hygiene_dag_record(tmp_path, "empty", str(corpus))

    # Preconditions: both really are the zero-population, refused-at-finish row.
    assert a_proc.returncode == b_proc.returncode == 2
    assert a_doc["decided"] == b_doc["decided"] == 1
    for doc in (a_doc, b_doc):
        row = [c for c in doc["corpora"] if c["name"] == _REAL_CORPUS]
        assert len(row) == 1 and row[0]["items"] == 0, row

    # THE CRUX, asserted before any detail about HOW the two are told apart:
    # #1763's row keeps EXACTLY the phase-1 closing rc it has today...
    assert b_rc == 0, b_proc.stdout + b_proc.stderr
    # ...and the corpus nothing opened does not inherit that waiver.
    assert a_rc == 2, (
        "the parallel hygiene DAG closed GREEN (rc 0) over a corpus that was "
        "NEVER OPENED. The phase-1 bootstrap waiver in `_summary_rc` is written "
        "for a corpus that WAS read and publishes nothing; an absent corpus "
        "reached it wearing that row's label and that row's expansion, so the "
        "run reported enforcement over a measurement nobody took "
        f"(vibe-ic#1764). Got rc {a_rc}.\n{a_proc.stdout}{a_proc.stderr}")
    assert a_rc != b_rc

    # …and this is the distinction the waiver keys off.
    assert [c for c in a_doc["corpora"]
            if c["name"] == _REAL_CORPUS][0]["expansion"] == "NO_CORPUS"
    assert [c for c in b_doc["corpora"]
            if c["name"] == _REAL_CORPUS][0]["expansion"] == "EXPANDED"


# --- vibe-ic#1764: the RECORD consumer sections 5/5b did not sweep -----------
#
# The sweep asking whether the collapse was singular enumerated every program
# that reaches `_corpus_location.refuse` — the PRODUCER side. There is a second
# side: programs that read the dispatcher's `corpora` row back. Two were traced
# (`repo_hygiene_parallel._summary_rc`, `hygiene_finding_delta._validate_record`)
# and a third was not, because it is neither a producer nor a Python consumer:
#
#     tools/gatekeeper-verify-merge.sh:810  base_has_exact_legacy_routed_empty
#
# It decides whether the BASE arm is in the one state that authorises
# `build_trusted_transition_evidence` — the trusted parent enumerating and
# EXECUTING the routed corpus on the landing path. If an absent corpus could
# wear the row it accepts, the landing would build trusted transition evidence
# over a corpus nothing opened, which is this issue's defect at its most
# expensive point.
#
# MEASURED 2026-08-22, this host, real dispatcher, on `81cd5321b` (before the
# fix) and on this tree, the shipped predicate over records the real dispatcher
# wrote:
#
#     cell                          before                after
#     stub producer exit 3, SHA     PRODUCER_FAILED  ref  NO_CORPUS   refuses
#     no pointer, SHA bound         PRODUCER_FAILED  ref  PRODUCER_FAILED  ref
#     pointer -> read-empty, SHA    EXPANDED    AUTHORISES  EXPANDED  AUTHORISES
#     no pointer, no SHA            EXPANDED       refuses  NO_CORPUS   refuses
#     pointer -> read-empty, no SHA EXPANDED       refuses  EXPANDED    refuses
#
# THE VERDICT IS IDENTICAL IN EVERY CELL ON BOTH COMMITS. This consumer was
# never collapsed, and the answer is stated as the sweep found it rather than
# as a fix: it is held by two INDEPENDENT guards, and the second is the one the
# rest of this file's ruling supplies.
#
#   1. `_corpus_location` already refuses rc 2 UNDETERMINED for a bound SHA with
#      no checkout, so inside `gatekeeper-verify-merge.sh` — which exports
#      `GATEKEEPER_BENCHMARK_DATA_SHA` in both arms — state A cannot arise: it
#      is a broken configuration there, not an absent corpus.
#   2. Without that SHA the predicate refuses on `benchmark_data_sha` anyway.
#
# So this is a REGRESSION PIN, not a fix, and it is not red on `81cd5321b`.
# Saying otherwise would be the same overstatement this record already corrected
# once. What it pins is that the predicate keeps refusing an unopened corpus
# WITHOUT leaning on guard 1 — on the record itself, not on the pointer binding
# being right.
#
# WHICH BYTES DO THAT REFUSING. Re-measured at the branch head, because the
# first version of this comment named only one of them. There are TWO
# in-predicate guards -- the gate-label equality and the exact `expansion` dict
# -- and EACH REFUSES ON ITS OWN. That redundancy is why the end-to-end
# assertion below cannot police them: relax one and the other still refuses, so
# the record is still rejected and the assertion is still green. A guard that
# only bites once BOTH have fallen is half a guard.
#
# So `_shipped_authorizer` polices them individually, and the two layers are
# measured, not assumed. Mutations of the shipped predicate, each driven over
# the exact record case (2) builds -- `NO_CORPUS`, the NOT FOUND gate label,
# `benchmark_data_sha` MATCHING, so guard 1 is satisfied and cannot be what
# refuses:
#
#     widen the gate-label filter to accept NOT FOUND too   -> RED  "no longer
#         selects on g.get("label") == label"
#     widen `expansion` to accept NO_CORPUS, literal kept   -> RED  "now names
#         'NO_CORPUS'"   <- the literal survives an `or` branch, so only the
#         forbidden-spelling check sees this one
#     widen BOTH, both literals kept                        -> RED  (and the
#         substantive `assert 0 == 1` behind it)
#     drop `"expansion"` from the dict comparison           -> RED  "no longer
#         mentions '"expansion": "EXPANDED"'"
#     unmutated shipped bytes                               -> PASSES
#
# So no single-guard erosion is invisible any more, and the end-to-end
# assertion stays as the backstop for the case where both fall at once.

VERIFY_MERGE = REPO / "tools" / "gatekeeper-verify-merge.sh"
_AUTHORIZER = "base_has_exact_legacy_routed_empty"
#: Stands in for the immutable corpus commit the outer verifier measures once
#: and exports into BOTH arms.  Its only role here is equality.
_BOUND_SHA = "0123456789abcdef0123456789abcdef01234567"
_REAL_EMPTY_LABEL = f'corpus "{_REAL_CORPUS}" is EMPTY — nothing was checked over it'
_REAL_ABSENT_LABEL = (f'corpus "{_REAL_CORPUS}" was NOT FOUND — nothing was '
                      f'opened to check')


def _transition_base_record(tmp_path: Path, stem: str, producer: str,
                            pointer: str | None, sha: str | None) -> Path:
    """A base-arm summary record over the REAL corpus name, written by the
    real `_gate_dispatch.sh` at the legacy un-attested call site.

    Un-attested on purpose: `base_has_exact_legacy_routed_empty` requires the
    row to carry NO process attestation, which is the phase-1 bootstrap shape
    the base arm is in.  Building it any other way would test a record the
    predicate is not written for.
    """
    root = tmp_path / f"tr-{stem}"
    root.mkdir(parents=True)
    script = root / "gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT={str(root)!r}
        . {str(DISPATCH)!r}
        gate_dispatch_init "$@"
        _body() {{ run "per cell ($1)" "$ROOT" true; }}
        gate_dispatch_over {_REAL_CORPUS!r} _body {producer}
        gate_dispatch_finish
        """), encoding="utf-8")
    summary = root / "summary.json"
    env = os.environ.copy()
    env.pop(ENV, None)
    env.pop("GATEKEEPER_BENCHMARK_DATA_SHA", None)
    env["GATEKEEPER_HYGIENE_JOBS"] = "1"
    if pointer is not None:
        env[ENV] = pointer
    if sha is not None:
        env["GATEKEEPER_BENCHMARK_DATA_SHA"] = sha
    subprocess.run(["bash", str(script), "--summary-json", str(summary)],
                   env=env, capture_output=True, text=True)
    return summary


def _shipped_authorizer(tmp_path: Path, stem: str, record: Path) -> int:
    """Run the predicate's SHIPPED bytes, lifted out of the script verbatim.

    Copied rather than stubbed, and the extraction asserts what it took, so a
    rename or a restructure of the function fails loudly here instead of
    leaving this test silently measuring nothing.
    """
    text = VERIFY_MERGE.read_text(encoding="utf-8")
    match = re.search(rf"^{_AUTHORIZER}\(\) \{{\n.*?^\}}\n", text,
                      re.M | re.S)
    assert match, (
        f"{_AUTHORIZER} is no longer a top-level function in "
        f"{VERIFY_MERGE.name}; this test can no longer reach the shipped bytes")
    body = match.group(0)
    for required in ('"expansion": "EXPANDED"', "is EMPTY", "benchmark_data_sha"):
        assert required in body, (
            f"the landing-transition authorizer no longer mentions {required!r}. "
            f"It decides whether a base arm authorises trusted transition "
            f"evidence; keeping a corpus nothing opened out of that decision is "
            f"what these bytes do (vibe-ic#1764)")
    # BOTH guards must stay EQUALITIES, and this is asserted separately from the
    # substantive check below because the substantive check cannot see a single
    # widening: with two redundant guards, relaxing one leaves the other
    # refusing and the assertion green (measured -- see the matrix above). A
    # membership test in place of either `==` is the first half of the only
    # mutation that gets an unopened corpus through, so it fails HERE, on its
    # own, before it can be paired with the second half.
    for guard in ('g.get("label") == label',
                  '"expansion": "EXPANDED"}'):
        assert guard in body, (
            f"the landing-transition authorizer no longer selects on {guard!r}. "
            f"It is one of TWO independent guards that keep an absent-corpus "
            f"record out of `build_trusted_transition_evidence`; widening "
            f"either to a membership or subset test is invisible to the "
            f"end-to-end assertion below, because the other one still refuses "
            f"(vibe-ic#1764 §7)")
    # ...and neither guard may be widened by NAMING the absent-corpus state.
    # An `== "EXPANDED"` kept intact beside an `or ... == "NO_CORPUS"` still
    # carries both literals above, so only this catches it. The predicate has
    # no legitimate reason to mention either spelling: it authorises exactly
    # one state and that state is the READ-empty one. Bound stated honestly --
    # this reads the shipped text, so a widening that avoids both spellings
    # (an indirection through a variable) would pass here and is caught only by
    # the end-to-end assertion below, and only if BOTH guards fall.
    for forbidden in ("NO_CORPUS", "NOT FOUND"):
        assert forbidden not in body, (
            f"the landing-transition authorizer now names {forbidden!r}. It "
            f"authorises the trusted parent to enumerate and EXECUTE the routed "
            f"corpus, and the only state that may do so is a corpus that was "
            f"READ and publishes nothing. A corpus nothing opened must not be "
            f"reachable from these bytes at all (vibe-ic#1764)")
    driver = tmp_path / f"authorizer-{stem}.sh"
    driver.write_text(
        f"TRUSTED_REPO={str(REPO)!r}\nBENCHMARK_SHA={_BOUND_SHA!r}\n"
        + body + f"\n{_AUTHORIZER} {str(record)!r}\n", encoding="utf-8")
    return subprocess.run(["bash", str(driver)], capture_output=True,
                          text=True).returncode


def _corpus_row(record: Path) -> tuple[dict, list[str]]:
    doc = json.loads(record.read_text(encoding="utf-8"))
    rows = [c for c in doc["corpora"] if c["name"] == _REAL_CORPUS]
    assert len(rows) == 1, rows
    labels = [g["label"] for g in doc["gates"] if g.get("corpus") == _REAL_CORPUS]
    return rows[0], labels


def test_the_landing_transition_authorizer_never_accepts_an_unopened_corpus(
        tmp_path):
    """#1763's row keeps its authority; a corpus nothing opened never gains it."""
    corpus = _read_but_empty_corpus(tmp_path)
    subject = _subject_repo(tmp_path)
    real = f"python3 {str(HELPER)!r} --repo {str(subject)!r}"

    # (1) STATE B, the state the landing arms are actually in. This is #1763's
    # row and it must still authorise — a change that made the transition
    # un-buildable would be a regression dressed as caution.
    b_record = _transition_base_record(
        tmp_path, "b", real, str(corpus), _BOUND_SHA)
    b_row, b_labels = _corpus_row(b_record)
    assert b_row["expansion"] == "EXPANDED"
    assert b_labels == [_REAL_EMPTY_LABEL], b_labels
    assert _shipped_authorizer(tmp_path, "b", b_record) == 0, (
        "the base arm in the state #1763 adjudicated no longer authorises "
        "trusted transition evidence")

    # (2) A NO_CORPUS ROW CARRYING THE MATCHING BOUND SHA. The producer cannot
    # reach this state — see (3) — so the population is stubbed while the RECORD
    # stays the real dispatcher's. That is the whole point: with the SHA guard
    # satisfied -- asserted below, not assumed -- the refusal can only come
    # from what vibe-ic#1764 added: the corpus row's `expansion` and the gate
    # label that travels with it. Either alone refuses; see the matrix above.
    a_record = _transition_base_record(
        tmp_path, "a", "bash -c 'exit 3'", None, _BOUND_SHA)
    a_row, a_labels = _corpus_row(a_record)
    assert a_row["expansion"] == "NO_CORPUS", a_row
    assert a_labels == [_REAL_ABSENT_LABEL], a_labels
    # Guard 1 is SATISFIED here. Without this the refusal below would be
    # ambiguous -- a `benchmark_data_sha` mismatch refuses every record, and a
    # pin that cannot tell which guard fired is measuring nothing.
    assert (json.loads(a_record.read_text(encoding="utf-8"))
            .get("corpus_inputs", {}).get("benchmark_data_sha")) == _BOUND_SHA
    assert _shipped_authorizer(tmp_path, "a", a_record) == 1, (
        "a base arm whose corpus was NEVER OPENED authorised the trusted "
        "parent to enumerate and execute the routed corpus. The transition "
        "evidence would then be built over a measurement nobody took "
        "(vibe-ic#1764)")

    # (3) THE SECOND, INDEPENDENT GUARD, stated by measurement so that neither
    # is mistaken for the only one. Inside `gatekeeper-verify-merge.sh` the SHA
    # is exported in both arms, and a bound SHA with no checkout is a BROKEN
    # POINTER, not an absent corpus: `_corpus_location` refuses it rc 2 before
    # the question of which row to wear can arise.
    u_record = _transition_base_record(tmp_path, "u", real, None, _BOUND_SHA)
    u_row, _ = _corpus_row(u_record)
    assert u_row["expansion"] == "PRODUCER_FAILED", u_row
    assert _shipped_authorizer(tmp_path, "u", u_record) == 1

    # The three rows are three different states, which is the property this
    # whole file exists to keep.
    assert len({b_row["expansion"], a_row["expansion"],
                u_row["expansion"]}) == 3
