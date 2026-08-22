"""A gate that writes into the corpus it audits must be LOUD, not invisible.

MEASURED 2026-08-04. One controlled A/B run of `flow_compliance_check` with
`cwd=` inside published trees rewrote 77 tracked files and left 64 untracked
plus 22 IGNORED artefacts.  The ignored class is why this cost hours: `git
status` does not show it, so the leftovers were invisible while still being
read by the next gate — and they failed `step FAIL bubbles up` and `gates are
host-independent` inside two `gatekeeper_review` runs, on a PR that had nothing
to do with either.

Every test here sources the REAL `_gate_dispatch.sh` and drives the REAL
`run`/`_dispatch`, for the reason that file's own header gives: a fixture copy
of the dispatch code would drift from the code CI runs.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"
_HYGIENE = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"

#: Every fixture gate returns instantly; this only stops a hung one from taking
#: the pytest session down (#542). It must stay UNDER the 60 s ceiling
#: `ci_harness_timeout_ceiling_check` enforces, or the bound cannot fire as a
#: TEST failure — pytest kills the whole session at 180 s first, taking every
#: other file in the subset with it. Measured on this tree: the slowest call
#: below is the hygiene script's `--list` at 0.03 s, so 55 keeps ~1800x
#: headroom.
_T = 55

#: The two corpus-scanning gates driven for real in the write audit below.
#: MEASURED at 0.15 s and 0.09 s over the whole published corpus; the 600 s I
#: first wrote was decoration, and decoration above the ceiling is a bound that
#: can never fire.
_CORPUS_GATE_T = 55


def _corpus_repo(tmp_path: Path, *, gitignore: str = "") -> Path:
    """A throwaway repo with a `benchmark-data/` corpus and one tracked file."""
    r = tmp_path / "repo"
    (r / "benchmark-data" / "ic" / "cell").mkdir(parents=True)
    (r / "benchmark-data" / "ic" / "cell" / "kept.txt").write_text("x\n")
    if gitignore:
        (r / ".gitignore").write_text(gitignore)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    return r


def _script(root: Path, gate_lines: str) -> Path:
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    s = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    s.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        """) + gate_lines + "\ngate_dispatch_finish\n")
    return s


def _run(root: Path, gate_lines: str, record: Path = None):
    argv = ["bash", str(_script(root, gate_lines))]
    if record is not None:
        argv += ["--summary-json", str(record)]
    return subprocess.run(argv, cwd=str(root), capture_output=True, text=True,
                          timeout=_T)


def _writer(root: Path, name: str, rel: str) -> Path:
    p = root / f"{name}.py"
    p.write_text(
        "import pathlib\n"
        f"t = pathlib.Path({str(root)!r}) / {rel!r}\n"
        "t.parent.mkdir(parents=True, exist_ok=True)\n"
        "t.write_text('leftover\\n')\n"
        "print('PASS (1 item examined)')\n")
    return p


def _reader(root: Path, name: str = "reader") -> Path:
    p = root / f"{name}.py"
    p.write_text("print('PASS (1 item examined)')\n")
    return p


def test_a_gate_that_writes_into_the_corpus_is_caught_and_named(tmp_path):
    r = _corpus_repo(tmp_path)
    _writer(r, "w", "benchmark-data/ic/cell/stray.json")
    out = _run(r, f'run "a writer" "$ROOT" python3 "{r}/w.py"\n')
    text = out.stdout + out.stderr
    assert out.returncode == 1, (
        "a gate that changed the corpus mid-run was reported as a pass:\n"
        + text)
    assert "WROTE INTO THE CORPUS" in text, text
    assert "a writer" in text, (
        "the writer is not NAMED — a count cannot tell a reader which gate "
        f"poisoned the tree for everything after it:\n{text}")
    assert "stray.json" in text, (
        "the guard did not say WHICH path appeared:\n" + text)


def test_an_IGNORED_leftover_is_caught(tmp_path):
    """THE CASE THAT COST THE HOURS.

    `git status` alone does not see an ignored path, so a guard built on it
    reports clean over exactly the leftovers it exists to find. This fixture's
    write lands on a `.gitignore`d name; without `--ignored` the snapshot before
    and after are identical and this test fails.
    """
    r = _corpus_repo(tmp_path, gitignore="*.log\n")
    _writer(r, "w", "benchmark-data/ic/cell/reports/audit/run.log")
    out = _run(r, f'run "an invisible writer" "$ROOT" python3 "{r}/w.py"\n')
    text = out.stdout + out.stderr
    assert out.returncode == 1, (
        "an IGNORED corpus write went unreported — this is precisely the "
        f"class that failed two gatekeeper_review runs:\n{text}")
    assert "WROTE INTO THE CORPUS" in text and "an invisible writer" in text


def test_a_MODIFIED_TRACKED_corpus_file_is_caught(tmp_path):
    """The third shape: not a new path, an overwritten one. 77 tracked files
    were rewritten in the measured A/B."""
    r = _corpus_repo(tmp_path)
    _writer(r, "w", "benchmark-data/ic/cell/kept.txt")
    out = _run(r, f'run "a rewriter" "$ROOT" python3 "{r}/w.py"\n')
    assert out.returncode == 1, out.stdout + out.stderr
    assert "WROTE INTO THE CORPUS" in out.stdout + out.stderr


def test_a_read_only_gate_passes(tmp_path):
    """CONTROL. Without it, a guard that fails everything passes every test
    above and stops the hygiene lane dead."""
    r = _corpus_repo(tmp_path)
    _reader(r)
    out = _run(r, f'run "a reader" "$ROOT" python3 "{r}/reader.py"\n')
    assert out.returncode == 0, out.stdout + out.stderr
    assert "WROTE INTO THE CORPUS" not in out.stdout + out.stderr
    assert "all 1 gate(s) passed" in out.stdout, out.stdout


def test_a_write_OUTSIDE_the_corpus_is_not_a_finding(tmp_path):
    """The guard's subject is the corpus, not the tree. A gate that writes its
    own report elsewhere is doing the RIGHT thing and must not be punished for
    it — that is the redirect this guard's message recommends."""
    r = _corpus_repo(tmp_path)
    _writer(r, "w", "build/report.json")
    out = _run(r, f'run "an outside writer" "$ROOT" python3 "{r}/w.py"\n')
    assert out.returncode == 0, out.stdout + out.stderr
    assert "WROTE INTO THE CORPUS" not in out.stdout + out.stderr


def test_a_declared_producer_is_allowed_and_still_recorded(tmp_path):
    """A genuine producer declares itself in the wrapper NAME, the same way a
    gate that may refuse declares itself with `run_tolerating_uncheckable`."""
    r = _corpus_repo(tmp_path)
    _writer(r, "w", "benchmark-data/ic/cell/produced.json")
    out = _run(r, f'run_writing_the_corpus "a producer" "$ROOT" '
                  f'python3 "{r}/w.py"\n')
    assert out.returncode == 0, out.stdout + out.stderr
    assert "WROTE INTO THE CORPUS" not in out.stdout + out.stderr


def test_the_record_keeps_a_corpus_write_out_of_passed(tmp_path):
    """A consumer reads the record, not the log. `wrote_corpus` is its own
    bucket: the gate may well have found nothing, and what it DID was change
    the tree every later gate reads. Folding it into either `passed` or
    `failed` loses the distinction a reader needs."""
    r = _corpus_repo(tmp_path)
    _writer(r, "w", "benchmark-data/ic/cell/stray.json")
    _reader(r)
    rec = tmp_path / "rec.json"
    _run(r, (f'run "a writer" "$ROOT" python3 "{r}/w.py"\n'
             f'run "a reader" "$ROOT" python3 "{r}/reader.py"\n'), record=rec)
    doc = json.loads(rec.read_text())
    assert doc["declared"] == 2, doc
    assert doc["wrote_corpus"] == 1, doc
    assert doc["passed"] == 1, doc
    states = {g["label"]: g["state"] for g in doc["gates"]}
    assert states["a writer"] == "WROTE_CORPUS", states
    assert states["a reader"] == "PASS", states


def test_the_rollup_names_the_writers(tmp_path):
    """Any other failure in the same run may be about the leftovers rather than
    about the commit, so the roll-up has to say a write happened at all."""
    r = _corpus_repo(tmp_path)
    _writer(r, "w", "benchmark-data/ic/cell/stray.json")
    out = _run(r, f'run "a writer" "$ROOT" python3 "{r}/w.py"\n')
    line = [ln for ln in (out.stdout + out.stderr).splitlines()
            if "WROTE INTO" in ln and "repo_hygiene_gates:" in ln]
    assert line and "a writer" in line[0], (
        "the roll-up does not name the gate that modified the corpus:\n"
        + out.stdout + out.stderr)


def test_a_tree_with_no_corpus_says_the_guard_is_INACTIVE(tmp_path):
    """"I could not look" must never be indistinguishable from "nothing wrote"
    — the vacuous pass this repo removes from gates one at a time."""
    r = tmp_path / "nocorpus"
    (r / "tools" / "ci").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    _reader(r)
    out = _run(r, f'run "a reader" "$ROOT" python3 "{r}/reader.py"\n')
    assert "corpus-write guard NOT ACTIVE" in out.stderr, out.stderr
    assert out.returncode == 0, out.stdout + out.stderr


def test_the_real_hygiene_lane_writes_nothing_into_benchmark_data():
    """The audit that justified landing the guard BLOCKING, kept as a test.

    `--list` alone would prove nothing, so this drives real gates: the two
    corpus-scanning gates the lane wires over `benchmark-data/ic`. Both must
    leave the tree exactly as they found it.
    """
    def state():
        return subprocess.run(
            ["git", "-C", str(_REPO), "status", "--porcelain",
             "--ignored=traditional", "--", "benchmark-data"],
            capture_output=True, text=True, timeout=_T).stdout
    before = state()
    for prog, args in (("cross_layer_reference_check",
                        ["--corpus", str(_REPO / "benchmark-data" / "ic")]),
                       ("step_internal_fail_bubble_up_check",
                        ["--corpus", str(_REPO / "benchmark-data" / "ic")])):
        subprocess.run([sys.executable, str(_PROGRAMS / f"{prog}.py"), *args],
                       cwd=str(_REPO), capture_output=True, text=True,
                       timeout=_CORPUS_GATE_T)
        assert state() == before, (
            f"{prog} modified benchmark-data/ while auditing it")


def test_the_hygiene_lane_declares_a_host_independent_number_of_gates():
    """The 68 -> 169 inflation.

    The per-cell gates were fanned out by a glob over the WORKING DIRECTORY, so
    every run leftover carrying a routed DEF added three more. Measured on the
    main checkout: 1078 leftovers, 169 declared gates, 13 FAILs about the tree
    rather than the commit — reproduced identically on two unrelated PRs.

    Driven: a leftover cell is planted in a scratch clone, and the declared
    count must not move.
    """
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        clone = Path(td) / "c"
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        for rel in ("tools/ci/_gate_dispatch.sh", "tools/ci/repo_hygiene_gates.sh"):
            (clone / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_REPO / rel, clone / rel)
        cell = clone / "benchmark-data/ic/fam/tracked/phase3/stage3/pnr"
        cell.mkdir(parents=True)
        (cell / "routed.def").write_text("DESIGN t ;\nEND DESIGN\n")
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(clone), "config", k, v], check=True)
        subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(clone), "commit", "-qm", "b"],
                       check=True)

        def declared() -> int:
            rec = Path(td) / "rec.json"
            subprocess.run(["bash", str(clone / "tools/ci/repo_hygiene_gates.sh"),
                            "--list", "--summary-json", str(rec)],
                           cwd=str(clone), capture_output=True, text=True,
                           timeout=_T)
            return json.loads(rec.read_text())["declared"]

        base = declared()
        # An UNTRACKED leftover cell — the shape 1078 of them had.
        leftover = clone / "benchmark-data/ic/fam/leftover/phase3/stage3/pnr"
        leftover.mkdir(parents=True)
        (leftover / "routed.def").write_text("DESIGN l ;\nEND DESIGN\n")
        after = declared()

    assert after == base, (
        "an untracked run leftover changed how many gates this script says it "
        f"declares ({base} -> {after}); the denominator is a fact about the "
        "working directory rather than about the commit, which is the 68 -> "
        "169 inflation")


def test_the_tracked_cells_are_still_reached():
    """The paired half: a denominator that ignores the disk must not ignore the
    TRACKED cells too, or the fix above would be a silent coverage cut.

    DRIVEN ON A FIXTURE, NOT ON THIS CHECKOUT — and that is a repair, not a
    retreat. It used to count the per-cell gates the real lane declares over
    this repository and compare that to `git ls-files` on the same glob. Both
    sides are the same corpus, so the pairing says nothing whenever the corpus
    is empty: with the result cells moved to `vibeic/benchmark-data` it read
    `0 == 0 > 0` and failed, reporting a coverage cut in a fan-out that is
    perfectly intact. It was also a test whose STRENGTH depended on how many
    cells somebody had published that week.

    Two TRACKED cells are planted here instead, so the population is one this
    test chose and the expected count is a number rather than a hope. The
    untracked half — a leftover on the disk must NOT add a gate — is the
    sibling test above; together they pin both directions.
    """
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        clone = Path(td) / "c"
        (clone / "tools" / "ci").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        shutil.copy2(_LIB, clone / "tools/ci/_gate_dispatch.sh")
        shutil.copy2(_HYGIENE, clone / "tools/ci/repo_hygiene_gates.sh")
        for name in ("alpha", "beta"):
            cell = clone / f"benchmark-data/ic/fam/{name}/phase3/stage3/pnr"
            cell.mkdir(parents=True)
            (cell / "routed.def").write_text("DESIGN t ;\nEND DESIGN\n")
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(clone), "config", k, v], check=True)
        subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(clone), "commit", "-qm", "b"],
                       check=True)

        out = subprocess.run(
            ["bash", str(clone / "tools/ci/repo_hygiene_gates.sh"), "--list"],
            cwd=str(clone), capture_output=True, text=True, timeout=_T)
        assert out.returncode == 0, out.stderr
        percell = [ln for ln in out.stdout.splitlines()
                   if ln.startswith("macro OBS not crossed")]
        tracked = subprocess.run(
            ["git", "-C", str(clone), "ls-files", "--",
             "benchmark-data/ic/*/*/phase3/stage3/pnr/routed.def"],
            capture_output=True, text=True, timeout=_T).stdout.split()

    assert len(tracked) == 2, (
        "the fixture did not track the two cells it planted, so the assertion "
        f"below would be about nothing: {tracked}")
    assert len(percell) == len(tracked), (
        "the per-cell gates no longer cover every TRACKED cell: %d gate(s) "
        "for %d tracked routed.def" % (len(percell), len(tracked)))


# ==========================================================================
# THE MERGE GATE MUST NAME IT, NOT SHRUG AT IT
# ==========================================================================
def _gatekeeper_review():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gatekeeper_review", _PROGRAMS / "gatekeeper_review.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gatekeeper_review"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_merge_gate_reports_a_corpus_write_as_a_corpus_write():
    """The record names a WROTE_CORPUS gate and the script exits 1 with no
    FAIL.

    Before this state existed that combination fell through to "exited 1 while
    naming no failing gate" — an inconsistency message about a perfectly
    consistent record, pointing the reader away from the one thing that
    happened. Driven through the real verdict function.
    """
    GR = _gatekeeper_review()
    doc = {"declared": 2, "seconds": 3,
           "gates": [{"label": "a writer", "state": "WROTE_CORPUS"},
                     {"label": "a reader", "state": "PASS"}]}
    res = GR._hygiene_verdict(doc, script_rc=1)
    assert res.rc == 1, res
    assert "WROTE INTO the corpus" in res.summary, res.summary
    assert "a writer" in res.summary, res.summary
    assert "naming no failing gate" not in res.summary, res.summary


def test_a_corpus_write_is_the_headline_even_when_a_gate_also_failed():
    """Every gate after a write read a tree this run changed, so an
    accompanying FAIL may be about the leftovers — exactly the misattribution
    that nearly produced a REQUEST_CHANGES on an innocent PR. Both are
    reported; the write leads."""
    GR = _gatekeeper_review()
    doc = {"declared": 2, "seconds": 3,
           "gates": [{"label": "a writer", "state": "WROTE_CORPUS"},
                     {"label": "step FAIL bubbles up", "state": "FAIL"}]}
    res = GR._hygiene_verdict(doc, script_rc=1)
    assert res.rc == 1, res
    assert "step FAIL bubbles up" in res.summary, res.summary
    assert (res.summary.index("WROTE INTO the corpus")
            < res.summary.index("step FAIL bubbles up")), res.summary


def test_a_clean_record_is_unaffected():
    """CONTROL: the new branch must not change a run that has no corpus
    write."""
    GR = _gatekeeper_review()
    doc = {"declared": 1, "seconds": 1,
           "gates": [{"label": "a reader", "state": "PASS"}]}
    assert GR._hygiene_verdict(doc, script_rc=0).rc == 0
    doc["gates"] = [{"label": "a reader", "state": "FAIL"}]
    bad = GR._hygiene_verdict(doc, script_rc=1)
    assert bad.rc == 1 and "FAILED" in bad.summary, bad
