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
    proc = _helper(None)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout == ""
    assert "NO_CORPUS" in proc.stderr and "NOTHING WAS SCANNED" in proc.stderr


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
                  preamble: str = "", also_owned: Sequence[str] = ()):
    script = _dispatch_script(root, producer, preamble=preamble)
    labels = root / f"{stem}.labels"
    labels.write_text("\n".join([owned_label, *also_owned]) + "\n",
                      encoding="utf-8")
    summary = root / f"{stem}.summary.json"
    attest = root / f"{stem}.attest.jsonl"
    progress = root / f"{stem}.progress.jsonl"
    env = os.environ.copy()
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
    # AND THE HAZARD ITSELF, asserted so it cannot quietly change shape: the
    # date IS recorded on the row and the row DOES leave `not_checked_unexempted`.
    # `_dispatch` appends the pending exemption before it judges it, so nothing
    # downstream can tell this row from one that legitimately bought tolerance.
    # The wiring error is the whole defence, which is why it is worth a test.
    assert states[_EMPTY_LABEL]["exempt_until"] == "2099-01-01", doc
    assert doc["not_checked_unexempted"] == [], doc


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
