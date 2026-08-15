"""vibe-ic#1223 — the ratchet's population was a NAMING CONVENTION.

`step_internal_fail_bubble_up_check --corpus` is the only instrument that holds
a line on unacknowledged step-internal FAILs across the published corpus. It
recognised a run tree by its directory being CALLED `clean_run_*`. A run's name
is not what makes it published evidence; the tracked `reports/` tree under it
is, because that is the only thing :func:`audit` can read.

MEASURED on `1adbf3444` (v1.10.42), the commit this module was written against:

    tracked dirs owning a reports/**/*.json under benchmark-data/ic : 16
      matching clean_run_*  (the population the ratchet swept)      :  3
      NOT matching          (invisible to it)                       : 13

    findings the gate reported : name-based  5   artefact-based  22

Seventeen unacknowledged step-internal FAILs sat in published trees the ratchet
could not see, including all three of the largest published run trees in the
repo. #1015 opened at sixteen affected runs and grew; every one of the runs it
grew by arrived where the ratchet was not looking.

TWO PRs CONTESTED THIS FUNCTION AND THEY DISAGREED (that is why #1223 exists).
The other one kept the name pattern, on the measured objection that widening
makes both `ic/<design>` and `ic/<design>/<version>` admissible and therefore
DOUBLE-COUNTS the same artefacts. That objection is true of the admissibility
rule IT measured and false of this one, and the difference is not a matter of
opinion: an owner is the directory before the FIRST `reports` component, so
every tracked report file maps to exactly one owner and `audit` reads only
`<owner>/reports/**`. Verified across the whole corpus rather than argued —
1926 report files, 117 owners, 0 counted twice — and pinned below on a fixture
that builds the nesting deliberately.

WHAT SURVIVES FROM THE OTHER PR is its second finding: a count means nothing
without the set it was taken over. With the population defined by the artefact,
`--corpus benchmark-data` and `--corpus benchmark-data/ic` are genuinely
different questions (45 findings over 117 run trees vs 22 over 16), where the
name-based population made them agree by accident. So the baseline records
`corpus_population` and the gate refuses to ratchet one against the other.

EVERY CASE HERE IS BIDIRECTIONAL. A widening that admitted everything would
pass "the non-`clean_run_*` tree is swept" and destroy the gate, so each
property is asserted with its opposite beside it: the widened population still
excludes a directory with no reports, a narrower root still narrows, and a
planted unacknowledged FAIL in a widened tree must still turn the gate RED.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
GATE = PROGRAMS / "step_internal_fail_bubble_up_check.py"

if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import step_internal_fail_bubble_up_check as M  # noqa: E402

#: vibe-ic#1241 — the harness runs pytest at `--timeout=180` and kills the
#: SESSION, so any inner bound above 180 // 3 = 60s is a promise it will not
#: keep. MEASURED, not snapped to the ceiling: the slowest case here builds
#: four run trees and makes three gate calls, well under a second of wall time.
_GATE_TIMEOUT_S = 30


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True,
                          timeout=_GATE_TIMEOUT_S)


def _mk_run(corpus: Path, rel: str, n_findings: int = 0) -> Path:
    """A published run tree carrying `n_findings` unacknowledged FAILs.

    Unacknowledged by construction: no `waivers.json`, and no
    `reports/orchestrator/` or `reports/audit/` record naming these reports, so
    neither limb of the gate's acknowledgment rule can grant them.
    """
    d = corpus / rel / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "clean_gate.json").write_text(json.dumps({"verdict": "PASS"}))
    for i in range(1, n_findings + 1):
        (d / f"gate_{i}.json").write_text(json.dumps(
            {"verdict": "FAIL", "detail": f"synthetic unacknowledged fail {i}"}))
    return corpus / rel


# ------------------------------------------------------------- the defect

def test_a_published_run_tree_not_named_clean_run_is_swept(tmp_path):
    """THE HEADLINE. The largest published run tree under `ic/spm` carries 164
    tracked reports and it was invisible to this gate purely because of what
    its directory is called."""
    corpus = tmp_path / "bd"
    _mk_run(corpus, "ic/spm/v1_2_3_pdkA")
    _mk_run(corpus, "ic/sha256/clean_run_v1_20200101")

    swept = {p.relative_to(corpus).as_posix()
             for p in M._published_run_trees(corpus)}
    assert swept == {"ic/spm/v1_2_3_pdkA", "ic/sha256/clean_run_v1_20200101"}, swept
    assert "ic/spm/v1_2_3_pdkA" in swept, (
        "the tree not named clean_run_* is still outside the population")


def test_the_name_pattern_alone_would_have_missed_it(tmp_path):
    """The control for the test above: without it, that assertion could pass
    against a population that never excluded anything in the first place."""
    corpus = tmp_path / "bd"
    _mk_run(corpus, "ic/spm/v1_2_3_pdkA")
    _mk_run(corpus, "ic/sha256/clean_run_v1_20200101")

    by_name = {p.relative_to(corpus).as_posix()
               for p in corpus.rglob("clean_run_*") if p.is_dir()}
    by_artefact = {p.relative_to(corpus).as_posix()
                   for p in M._published_run_trees(corpus)}
    assert by_name == {"ic/sha256/clean_run_v1_20200101"}, by_name
    assert by_artefact - by_name == {"ic/spm/v1_2_3_pdkA"}, by_artefact


# -------------------------------------------------- the widening is bounded

def test_a_directory_with_no_reports_tree_is_not_a_run(tmp_path):
    """THE PAIRED GUARD. A population that admitted every directory would
    satisfy every test above and measure noise. The predicate is the ARTEFACT,
    so a design directory that publishes no reports is not in it."""
    corpus = tmp_path / "bd"
    _mk_run(corpus, "ic/spm/v1_2_3_pdkA")
    (corpus / "ic" / "spm" / "input").mkdir(parents=True)
    (corpus / "ic" / "spm" / "input" / "spec.md").write_text("not a report")
    (corpus / "ic" / "no_reports_here").mkdir(parents=True)

    swept = {p.relative_to(corpus).as_posix()
             for p in M._published_run_trees(corpus)}
    assert swept == {"ic/spm/v1_2_3_pdkA"}, swept


def test_a_narrower_root_still_narrows_the_widened_population(tmp_path):
    """`--corpus` must keep meaning what it says. A predicate that ignored
    where it was pointed would look like a fix and be a global sweep."""
    corpus = tmp_path / "bd"
    _mk_run(corpus, "ic/spm/v1_2_3_pdkA")
    _mk_run(corpus, "ic/sha256/clean_run_v1_20200101")

    one = {p.relative_to(corpus / "ic" / "spm").as_posix()
           for p in M._published_run_trees(corpus / "ic" / "spm")}
    assert one == {"v1_2_3_pdkA"}, one


def test_a_nested_run_root_does_not_double_count(tmp_path):
    """THE OTHER PR'S OBJECTION, ANSWERED WITH A FIXTURE.

    `ic/caravel_user_project` and its versioned sub-tree are BOTH published run
    trees in this repo and both carry findings. The claim
    was that admitting both counts the same artefacts twice. It does not: an
    owner is the directory before the FIRST `reports` component, and `audit`
    reads only `<owner>/reports/**`, which never contains a nested owner's
    reports. Asserted on the FILES, not on the total, so a coincidence of
    arithmetic cannot make it pass.
    """
    corpus = tmp_path / "bd"
    _mk_run(corpus, "ic/design", 1)                    # the design root
    _mk_run(corpus, "ic/design/v1_2_3_pdkA", 2)        # a run inside it

    trees = M._published_run_trees(corpus)
    rels = {p.relative_to(corpus).as_posix() for p in trees}
    assert rels == {"ic/design", "ic/design/v1_2_3_pdkA"}, rels

    seen: dict = {}
    for t in trees:
        for f in M._iter_report_files(t):
            key = f.resolve()
            assert key not in seen, (
                f"{key} was audited by both {seen.get(key)} and {t}")
            seen[key] = t
    rep = M.check_corpus(corpus)
    assert rep["findings_total"] == 3, rep
    assert rep["per_run"] == {"ic/design": 1, "ic/design/v1_2_3_pdkA": 2}, rep


# ------------------------------------------- the gate still goes red (BOTH ARMS)

def test_a_new_FAIL_in_a_widened_tree_turns_the_gate_RED(tmp_path):
    """THE PROOF THE WIDENING BUYS SOMETHING.

    A green bought by widening the denominator would be worse than the bug.
    This plants one unacknowledged FAIL in a published tree NOT named
    `clean_run_*` — the exact shape every one of #1015's growth runs took — and
    requires rc 1 GREW. Under the name-based population the same stimulus was
    rc 0 and the gate said nothing at all.
    """
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/spm/v1_2_3_pdkA")
    _mk_run(corpus, "ic/sha256/clean_run_v1_20200101")
    assert _run("--corpus", str(corpus), "--baseline", str(bl),
                "--write-baseline").returncode == 0
    assert json.loads(bl.read_text())["findings_total"] == 0

    green = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert green.returncode == 0, green.stdout + green.stderr

    _mk_run(corpus, "ic/spm/v1_2_3_pdkA", 1)           # the stimulus
    red = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert red.returncode == 1, (
        f"a new unacknowledged FAIL in a published tree that is not named "
        f"clean_run_* did not redden the gate\n{red.stdout}{red.stderr}")
    assert "GREW 0 -> 1" in red.stdout, red.stdout


def test_the_same_stimulus_was_invisible_to_the_name_based_population(tmp_path):
    """The red arm's control, and the whole reason #1015 kept growing.

    Reproduces `origin/main`'s predicate in-process — `corpus.rglob("clean_run_*")`
    — over the SAME tree and the SAME stimulus, and shows it reaching neither
    the run nor the finding. Without this the test above would not distinguish
    "the fix works" from "the gate was already red".
    """
    corpus = tmp_path / "bd"
    _mk_run(corpus, "ic/spm/v1_2_3_pdkA", 1)           # the stimulus
    _mk_run(corpus, "ic/sha256/clean_run_v1_20200101")

    by_name = [p for p in sorted(corpus.rglob("clean_run_*")) if p.is_dir()]
    assert all("spm" not in p.as_posix() for p in by_name), by_name
    assert sum(len(M.audit(p)[1]) for p in by_name) == 0, (
        "the name-based population would have seen the stimulus")
    assert M.check_corpus(corpus)["findings_total"] == 1


# --------------------------------------------- a count carries its population

def test_the_baseline_records_which_population_it_counted(tmp_path):
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/spm/v1_2_3_pdkA", 1)
    assert _run("--corpus", str(corpus), "--baseline", str(bl),
                "--write-baseline").returncode == 0
    doc = json.loads(bl.read_text())
    assert doc["corpus_population"] == corpus.resolve().name, doc
    assert doc["findings_total"] == 1, doc


def test_a_count_from_one_population_is_not_ratcheted_against_another(tmp_path):
    """rc 2, not a verdict. Answering PASS or FAIL here would be a judgement
    over a set that was never examined — the failure #1015 is named for, one
    level up."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/spm/v1_2_3_pdkA", 1)
    _mk_run(corpus, "other/thing", 5)
    assert _run("--corpus", str(corpus / "ic"), "--baseline", str(bl),
                "--write-baseline").returncode == 0

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}{r.stderr}"
    assert "NOT CHECKED" in r.stdout, r.stdout
    assert "GREW" not in r.stdout, r.stdout


def test_the_recorded_population_still_ratchets_normally(tmp_path):
    """THE PAIRED GUARD for the refusal: a gate that refused every sweep would
    satisfy the test above and check nothing. Same root as the record must
    still PASS when nothing changed and FAIL when it grows."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/spm/v1_2_3_pdkA", 1)
    assert _run("--corpus", str(corpus), "--baseline", str(bl),
                "--write-baseline").returncode == 0

    same = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert same.returncode == 0, same.stdout + same.stderr

    _mk_run(corpus, "ic/spm/v1_2_3_pdkA", 2)
    grew = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert grew.returncode == 1, grew.stdout + grew.stderr
    assert "GREW 1 -> 2" in grew.stdout, grew.stdout


def test_a_baseline_without_a_population_still_ratchets(tmp_path):
    """"I do not know what it was measured over" is not "it disagrees".

    A record written before `corpus_population` existed must keep working
    exactly as it did; refusing it would turn a silent upgrade into an outage,
    and inventing a population for it would be the assumption this guard
    removes."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/spm/v1_2_3_pdkA", 1)
    assert _run("--corpus", str(corpus), "--baseline", str(bl),
                "--write-baseline").returncode == 0
    doc = json.loads(bl.read_text())
    doc.pop("corpus_population")
    bl.write_text(json.dumps(doc, indent=2) + "\n")

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOT CHECKED" not in r.stdout, r.stdout


def test_a_re_record_does_not_erase_a_hand_written_provenance_note(tmp_path):
    """The shipped baseline carries `_withdrawn_provenance`, which explains how
    its withdrawn entries were derived, and the writer does not author that
    key — so the command the gate TELLS the operator to run deleted it. Same
    rule as the ledger it sits beside (#1202): a re-record must not erase the
    record. Only `_`-prefixed keys survive, so no stale MEASUREMENT can."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/spm/v1_2_3_pdkA", 1)
    assert _run("--corpus", str(corpus), "--baseline", str(bl),
                "--write-baseline").returncode == 0
    doc = json.loads(bl.read_text())
    doc["_provenance"] = "hand-written, must survive"
    doc["runs_swept"] = 999                      # a stale MEASUREMENT
    bl.write_text(json.dumps(doc, indent=2) + "\n")

    assert _run("--corpus", str(corpus), "--baseline", str(bl),
                "--write-baseline").returncode == 0
    after = json.loads(bl.read_text())
    assert after["_provenance"] == "hand-written, must survive", after
    assert after["runs_swept"] == 1, (
        f"a stale measurement survived a re-record: {after}")
