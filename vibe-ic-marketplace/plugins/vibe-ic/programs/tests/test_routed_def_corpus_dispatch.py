"""Routed-DEF population evidence must survive the corpus split and sharding."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

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


def _dispatch_script(root: Path, producer: str) -> Path:
    script = root / "gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT={str(root)!r}
        . {str(DISPATCH)!r}
        gate_dispatch_init "$@"
        _body() {{ run "per item ($1)" "$ROOT" true; }}
        gate_dispatch_over "an observed corpus" _body {producer}
        gate_dispatch_finish
        """), encoding="utf-8")
    return script


def _dispatch_run(root: Path, producer: str, owned_label: str,
                  stem: str, *, attest_population: bool = True,
                  pointer: str | None = None):
    script = _dispatch_script(root, producer)
    labels = root / f"{stem}.labels"
    labels.write_text(owned_label + "\n", encoding="utf-8")
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
