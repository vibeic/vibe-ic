"""The review gate resolves the published corpus, or it refuses — loudly.

WHY THIS FILE EXISTS
====================
`tools/ci/repo_hygiene_gates.sh:591` wires the corpus "published cells carrying
a routed DEF" with `GATE_DISPATCH_ATTEST_POPULATION=1`, so a population of ZERO
is a dispatcher-owned BLOCKING refusal (`tools/ci/_gate_dispatch.sh:1270-1275`)
that no `uncheckable_until` may excuse (`_dispatch` mode 2, ll. 637-641).
v1.10.56 moved those cells into their own repository, so on an ordinary checkout
the population IS zero — and `gatekeeper_review.py`, the program a maintainer
runs before every push, never resolved that repository at all.

MEASURED on this host, clean `origin/main` 3199e9b3, 2026-08-20:

    pointer UNSET  75 of 80 decided, 71 passed, 4 failed, 5 NOT CHECKED, 239s
                   -- and the routed-DEF corpus EMPTY and BLOCKING
                      (that row now reads NOT FOUND and BLOCKING: with the
                      pointer unset nothing was OPENED, and vibe-ic#1764
                      stopped that state borrowing the sentence for a corpus
                      that WAS read and holds none. Still blocking, still
                      never a pass; only the sentence moved.)
    pointer SET    77 of 83 decided, 73 passed, 4 failed, 6 NOT CHECKED, 241s
                   -- `published-evidence index honest` FAILS: a real, committed
                      INDEX.md staleness the empty corpus hid outright

So four minutes were spent to reach a verdict about nothing, and the run named
neither the cause nor the remedy.

WHAT THESE TESTS PIN
====================
1. An unresolvable corpus is rc 2 (ERROR), never rc 0 and never rc 1, in each
   of the four ways it can be unresolvable: absent everywhere, a pointer that is
   set and wrong, a present tree that is not a git checkout, and a git checkout
   that is not the published-cell repository.
2. The refusal happens BEFORE the set runs — proven by a side effect the
   fixture script leaves on disk, not by a plausible-looking message.
3. A resolvable corpus is BOUND: the child sees both `VIBE_IC_BENCHMARK_DATA`
   and `GATEKEEPER_BENCHMARK_DATA_SHA`, the latter equal to that checkout's
   HEAD. The bound SHA is what stops `_corpus_location.resolve()` from
   preferring some candidate-local shadow (`_corpus_location.py:137-156`), and
   it is what reaches the record as `corpus_inputs.benchmark_data_sha`.

NEGATIVE CONTROL, which is the point of 2 and 3: every assertion here is about
an OBSERVED side effect of the child process, so a gate that returned the right
sentence without consulting anything, or consulted the corpus without passing it
on, is red.

chip-AGNOSTIC: pure environment/path/git plumbing. No design, PDK or vendor
literal.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


GR = _load("gatekeeper_review")


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
def _isolate(monkeypatch, tmp_path: Path) -> None:
    """No ambient corpus. HOME is redirected so the DEFAULT slot cannot resolve
    from whatever the developer running the suite happens to keep in theirs."""
    monkeypatch.delenv(GR._CORPUS_ENV, raising=False)
    monkeypatch.delenv(GR._CORPUS_CHECKOUT_ENV, raising=False)
    monkeypatch.delenv(GR._CORPUS_BOUND_SHA_ENV, raising=False)
    empty_home = tmp_path / "home"
    empty_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(empty_home))


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def _corpus_checkout(root: Path, with_ic: bool = True) -> Path:
    """A git checkout shaped like the published-corpus repository."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root.parent, "init", "-q", root.name)
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    if with_ic:
        cell = root / "ic" / "d" / "v" / "phase3" / "stage3" / "pnr"
        cell.mkdir(parents=True)
        (cell / "routed.def").write_text("DESIGN d ;\nEND DESIGN\n")
    else:
        (root / "README").write_text("not the corpus\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "corpus")
    return root


def _witness_script(root: Path, witness: Path) -> Path:
    """A stand-in for the real hygiene set, at the path the gate looks for.

    Deliberately NOT passed through the `script=` seam: that seam skips the
    corpus binding on purpose (a fixture script wires no corpus), so a test that
    used it would not exercise the code under test at all.
    """
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    script.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -uo pipefail
        out=""
        while [ $# -gt 0 ]; do
          case "$1" in
            --summary-json) out="$2"; shift 2 ;;
            *) shift ;;
          esac
        done
        python3 - "$out" {str(witness)!r} <<'PY'
        import json, os, sys
        summary, witness = sys.argv[1], sys.argv[2]
        with open(witness, "w", encoding="utf-8") as fh:
            json.dump({{k: os.environ.get(k)
                       for k in ("VIBE_IC_BENCHMARK_DATA",
                                 "GATEKEEPER_BENCHMARK_DATA_SHA")}}, fh)
        if summary:
            with open(summary, "w", encoding="utf-8") as fh:
                json.dump({{"declared": 1, "seconds": 0,
                            "wiring_errors": [],
                            "gates": [{{"label": "w", "state": "PASS"}}]}}, fh)
        PY
        """), encoding="utf-8")
    script.chmod(0o755)
    return script


# --------------------------------------------------------------------------
# 1. every unresolvable shape is rc 2, and the set is NOT run
# --------------------------------------------------------------------------
def _unresolvable_cases(tmp_path: Path):
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "ic").mkdir()
    not_the_corpus = _corpus_checkout(tmp_path / "other", with_ic=False)
    return [
        ("absent everywhere", None),
        ("set and wrong", str(tmp_path / "no-such-clone")),
        ("present but not a git checkout", str(loose)),
        ("a checkout that is not the corpus", str(not_the_corpus)),
    ]


def test_every_unresolvable_corpus_is_an_ERROR_and_the_set_never_runs(
        tmp_path, monkeypatch):
    for label, pointer in _unresolvable_cases(tmp_path):
        root = tmp_path / f"repo_{abs(hash(label))}"
        witness = tmp_path / f"witness_{abs(hash(label))}.json"
        _witness_script(root, witness)
        _isolate(monkeypatch, tmp_path)
        if pointer is not None:
            monkeypatch.setenv(GR._CORPUS_ENV, pointer)

        res = GR.repo_hygiene_gate(root)

        assert res.rc == 2, (
            f"[{label}] an unresolvable published corpus reported rc {res.rc}: "
            f"{res.summary}. rc 0 would certify a scan that did not happen and "
            f"rc 1 would claim a finding against the tree; neither is true.")
        assert not witness.exists(), (
            f"[{label}] the hygiene set RAN before the corpus was resolved — "
            f"four minutes to report the consequence instead of the cause")
        assert "NOTHING WAS SCANNED" in res.summary, res.summary
        assert "git clone" in res.summary, (
            f"[{label}] the refusal names no remedy: {res.summary}")


def test_a_broken_pointer_does_not_read_like_an_absent_corpus(
        tmp_path, monkeypatch):
    """`_corpus_location.py:26-29` — set-and-wrong is a broken configuration.

    Both are rc 2, so the exit code cannot tell them apart; the SENTENCE has to,
    because the remedies differ (fix the pointer vs. clone the repository).
    """
    root = tmp_path / "repo"
    _witness_script(root, tmp_path / "w.json")

    _isolate(monkeypatch, tmp_path)
    absent = GR.repo_hygiene_gate(root).summary

    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(GR._CORPUS_ENV, str(tmp_path / "typo"))
    wrong = GR.repo_hygiene_gate(root).summary

    assert "both unset" in absent, absent
    assert "set and wrong is a broken configuration" in wrong, wrong
    assert absent != wrong


# --------------------------------------------------------------------------
# 2. a resolvable corpus is BOUND, and the child is what proves it
# --------------------------------------------------------------------------
@pytest.mark.parametrize("slot", ["env", "checkout_env", "default_home"])
def test_a_resolvable_corpus_binds_the_pointer_AND_its_head_sha(
        tmp_path, monkeypatch, slot):
    corpus = _corpus_checkout(tmp_path / f"corpus_{slot}")
    head = subprocess.run(["git", "-C", str(corpus), "rev-parse", "HEAD"],
                          capture_output=True, text=True,
                          check=True).stdout.strip()
    root = tmp_path / f"repo_{slot}"
    witness = tmp_path / f"seen_{slot}.json"
    _witness_script(root, witness)

    _isolate(monkeypatch, tmp_path)
    if slot == "env":
        monkeypatch.setenv(GR._CORPUS_ENV, str(corpus))
    elif slot == "checkout_env":
        monkeypatch.setenv(GR._CORPUS_CHECKOUT_ENV, str(corpus))
    else:
        home = tmp_path / f"home_{slot}"
        home.mkdir(exist_ok=True)
        os.symlink(corpus, home / GR._CORPUS_DEFAULT_DIRNAME)
        monkeypatch.setenv("HOME", str(home))

    res = GR.repo_hygiene_gate(root)

    assert witness.exists(), (
        f"[{slot}] a resolvable corpus did not reach the set at all: "
        f"{res.summary}")
    seen = json.loads(witness.read_text())
    assert seen["VIBE_IC_BENCHMARK_DATA"] == str(corpus.resolve()), seen
    assert seen["GATEKEEPER_BENCHMARK_DATA_SHA"] == head, (
        f"[{slot}] the corpus was resolved but not BOUND. Without the SHA, "
        f"_corpus_location.resolve() prefers whatever candidate-local tree a "
        f"gate's own ancestor walk finds, and the pointer is silently not "
        f"followed: {seen}")


def test_the_binding_survives_the_progress_attestation_path(
        tmp_path, monkeypatch):
    """`progress_out` used to be the ONLY reason a child env was built.

    It rebuilt the env from `os.environ` and would have dropped the binding.
    """
    corpus = _corpus_checkout(tmp_path / "corpus_p")
    root = tmp_path / "repo_p"
    witness = tmp_path / "seen_p.json"
    _witness_script(root, witness)
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(GR._CORPUS_ENV, str(corpus))

    GR.repo_hygiene_gate(root, progress_out=tmp_path / "progress.jsonl")

    seen = json.loads(witness.read_text())
    assert seen["VIBE_IC_BENCHMARK_DATA"] == str(corpus.resolve()), seen
    assert seen["GATEKEEPER_BENCHMARK_DATA_SHA"], seen


# --------------------------------------------------------------------------
# 3. the seam stays a seam
# --------------------------------------------------------------------------
def test_the_unit_test_seam_still_needs_no_corpus(tmp_path, monkeypatch):
    """`script=` is the fixture seam and it wires no corpus by construction.

    Making it require one would break every existing hygiene fixture test for a
    reason that has nothing to do with what they assert.
    """
    root = tmp_path / "repo_seam"
    witness = tmp_path / "seam.json"
    script = _witness_script(root, witness)
    _isolate(monkeypatch, tmp_path)

    res = GR.repo_hygiene_gate(root, script=script)

    assert witness.exists(), res.summary
    assert res.rc == 0, res.summary


def test_a_missing_hygiene_script_is_still_reported_before_the_corpus(
        tmp_path, monkeypatch):
    """A tree that wires no hygiene set has a different, older answer.

    Ordering matters: "this tree has no hygiene set" must not be reported as
    "your corpus is missing", which would send a reader to fix the wrong thing.
    """
    _isolate(monkeypatch, tmp_path)
    res = GR.repo_hygiene_gate(tmp_path / "no-such-tree")
    assert res.rc == -1, res.summary
    assert "not present under" in res.summary, res.summary


# --------------------------------------------------------------------------
# 4. vibe-ic#1789 -- the declared stall grace must reach the runner that shards
# --------------------------------------------------------------------------
# `_HYGIENE_STALL_GRACE_S` documents itself as "the shared progress watchdog"
# and was shared with nobody: it governed the supervisor this module wraps
# around the COORDINATOR, while the coordinator supervised each SHARD with
# `repo_hygiene_parallel.DEFAULT_STALL_GRACE_S` = 300 s. Two watchdogs, 6x
# apart, one of them chosen here and never sent.
#
# It is not a tuning question. The shard is launched with `--progress`, so
# `_owned_process_supervisor` sets `output_progress=False` and the ONLY thing
# that renews the lease is one attestation row per COMPLETED GATE -- so the
# bound is "no single gate may take longer than the grace", and this repo's own
# `hygiene_gate_profile.json` records single gates at 646 s and 2556 s.
# MEASURED on clean main fd8dec469 in the pinned image: 2 of 8 shards killed at
# rc 199, 75 of the 80 reported "wiring errors" were that kill's fallout, and
# the tier's answer was "the set certifies NOTHING" about the HOST, not about
# the tree.
def _witness_parallel(root: Path, witness: Path) -> Path:
    """A stand-in for the parallel runner, at the path the gate prefers."""
    programs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    runner = programs / "repo_hygiene_parallel.py"
    runner.write_text(textwrap.dedent(f"""\
        import json, sys
        argv = sys.argv[1:]
        with open({str(witness)!r}, "w", encoding="utf-8") as fh:
            json.dump(argv, fh)
        out = argv[argv.index("--summary-json") + 1]
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({{"declared": 1, "seconds": 0, "wiring_errors": [],
                        "gates": [{{"label": "w", "state": "PASS"}}]}}, fh)
        """), encoding="utf-8")
    return runner


def test_the_declared_stall_grace_reaches_the_sharding_runner(
        tmp_path, monkeypatch):
    """ARM A. The number this module declares is the number the shards get."""
    corpus = _corpus_checkout(tmp_path / "corpus_sg")
    root = tmp_path / "repo_sg"
    _witness_script(root, tmp_path / "seen_sg.json")
    argv_seen = tmp_path / "argv_sg.json"
    _witness_parallel(root, argv_seen)
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(GR._CORPUS_ENV, str(corpus))

    res = GR.repo_hygiene_gate(root)

    assert argv_seen.exists(), (
        f"the parallel runner was not the one invoked: {res.summary}")
    argv = json.loads(argv_seen.read_text())
    assert "--stall-grace" in argv, (
        "the coordinator was supervised with a declared grace and then "
        f"supervised its own shards with a different, unstated one: {argv}")
    assert argv[argv.index("--stall-grace") + 1] == str(
        GR._HYGIENE_STALL_GRACE_S), argv


def test_a_caller_supplied_stall_grace_is_the_one_forwarded(
        tmp_path, monkeypatch):
    """ARM B -- the control.

    Arm A is satisfiable by hard-coding the literal 1800 at the call site,
    which would leave a caller's own grace governing one watchdog and not the
    other -- the same defect wearing a different number.
    """
    corpus = _corpus_checkout(tmp_path / "corpus_sg2")
    root = tmp_path / "repo_sg2"
    _witness_script(root, tmp_path / "seen_sg2.json")
    argv_seen = tmp_path / "argv_sg2.json"
    _witness_parallel(root, argv_seen)
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(GR._CORPUS_ENV, str(corpus))

    GR.repo_hygiene_gate(root, stall_grace=1234)

    argv = json.loads(argv_seen.read_text())
    assert argv[argv.index("--stall-grace") + 1] == "1234", argv


def test_the_shell_fallback_is_not_given_a_flag_it_has_no_parser_for(
        tmp_path, monkeypatch):
    """ARM C -- the other control.

    `tools/ci/repo_hygiene_gates.sh` accepts no `--stall-grace`. Forwarding it
    there would make every tree without the parallel runner refuse on an
    unknown argument, which is a new failure bought with the fix for an old one.
    """
    corpus = _corpus_checkout(tmp_path / "corpus_sg3")
    root = tmp_path / "repo_sg3"
    witness = tmp_path / "seen_sg3.json"
    _witness_script(root, witness)
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(GR._CORPUS_ENV, str(corpus))

    res = GR.repo_hygiene_gate(root)

    assert witness.exists(), res.summary
    assert res.rc == 0, res.summary
