#!/usr/bin/env python3
"""A checkout-write accusation needs an exclusive window, or it names the innocent.

`gate_host_independence_check.audit()` brackets each gate's drive with a
`git status` snapshot of THE WORKING CHECKOUT and charges the difference to
whichever gate was inside the bracket. `git status` is a fact about the TREE
and cannot name an author, so that attribution is sound only while this process
is the only one writing to the tree — and two shipping wirings break exactly
that premise:

  * `tools/gatekeeper-land.sh:112` runs `LANE_WIDTH=4` full-tier lanes —
    targeted tests, the corpus suite, this hygiene tier, the plugin audit —
    CONCURRENTLY IN ONE CHECKOUT. Another lane's in-flight write lands inside
    the bracket and is charged to a gate that never touched the file.
  * `tools/ci/repo_hygiene_gates.sh:2608` drives this with the outer sweep's
    attestation records, so Arm A is NOT re-run: the bracket then watches the
    working checkout for ~40 minutes while nothing of ours writes to it. Every
    path it can see belongs to somebody else and every finding it can file is
    false — there is no true positive on that path to lose.

The observed symptom was `3 of 131 probed corpus gate(s) ... 3
GATE_CORRUPTED_CHECKOUT` on one host and not another, briefly attributed to a
landing batch. `tools/gatekeeper-land.sh` "judges ABSOLUTELY — any red refuses",
so those three refused every landing until two batches were pushed with
`--no-verify`.

AND THE ACCUSATION IS NOT ONLY WRONG, IT IS DESTRUCTIVE. `_repair_checkout`
follows it with `git checkout -- <path>` on a file this process did not write,
which discards whatever the real writer was in the middle of doing. Every
"green" test below therefore also asserts that the peer lane's bytes SURVIVED;
a fix that stopped filing the finding but kept reverting the file would pass a
findings-only assertion and still eat another lane's work.

BOTH DIRECTIONS ARE ASSERTED HERE, because a detector that cannot say no is not
a detector:

  green  the same shape, the concurrent window DECLARED -> 0 findings, the
         peer's bytes intact, and the skipped attribution NAMED
  red    the same shape with the window not declared (a genuinely exclusive
         run) -> the finding still fires and still repairs, which is #1029's
         detector and it must not be retired
  red    a genuinely host-dependent gate is still caught WITH the window
         declared, so the fix did not buy silence
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import gate_host_independence_check as G  # noqa: E402
import gate_process_attestation as A  # noqa: E402

#: Every fixture gate here either returns instantly or waits on a file another
#: thread in this process is about to write, so this bound cannot be reached by
#: a healthy run. It stays under the 60 s ceiling
#: `ci_harness_timeout_ceiling_check` enforces.
_T = 30

#: How long a fixture waits for its counterpart before giving up. Reaching it
#: means the handshake broke, and the assertion that follows says so rather
#: than the test hanging until the harness kills it.
_SYNC_S = 20.0

_PEERS = 3          # + this probe = the four lanes `LANE_WIDTH=4` runs
_ORIGINAL = "committed bytes\n"


def _git(r: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(r), *args], check=True,
                   capture_output=True)


def _repo(tmp_path: Path, sync_dir: Path, *, sync_on_arm: str) -> Path:
    """A checkout with one READ-ONLY gate that hands control to the peers.

    `sync_on_arm` is `"checkout"` or `"worktree"`: the gate signals and then
    waits only while running in that tree, which is what makes the peers' write
    land INSIDE the bracket deterministically instead of by racing it. The two
    values are the two shipping wirings — a standalone run drives Arm A in the
    checkout, and the hygiene run reads Arm A out of a record and drives only
    Arm B.

    The handshake files live OUTSIDE the repo: a fixture that dirtied the tree
    it is measuring would be the defect under test.
    """
    r = tmp_path / "checkout"
    (r / "tools" / "ci").mkdir(parents=True)
    (r / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        'run "a read-only gate that writes nothing" "$ROOT" python3 quiet.py\n'
        'run "a second read-only gate" "$ROOT" python3 second.py\n')
    (r / "quiet.py").write_text(
        "import pathlib, sys, time\n"
        f"CHECKOUT = pathlib.Path({str(r)!r}).resolve()\n"
        f"SYNC = pathlib.Path({str(sync_dir)!r})\n"
        "here = pathlib.Path.cwd().resolve()\n"
        f"mine = (here == CHECKOUT) if {sync_on_arm!r} == 'checkout' "
        "else (here != CHECKOUT)\n"
        "if mine:\n"
        "    (SYNC / 'started').write_text('1')\n"
        f"    deadline = time.monotonic() + {_SYNC_S}\n"
        "    while time.monotonic() < deadline:\n"
        f"        if sum((SYNC / ('go%d' % i)).exists() "
        f"for i in range({_PEERS})) == {_PEERS}:\n"
        "            break\n"
        "        time.sleep(0.02)\n"
        "print('[PASS] 1 item examined')\n")
    (r / "second.py").write_text("print('[PASS] 1 item examined')\n")
    for i in range(_PEERS):
        (r / f"payload{i}.txt").write_text(_ORIGINAL)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    # The STIMULUS (#539): without an untracked path the two trees hold the
    # same bytes and the run is NO_STIMULUS rather than a comparison.
    (r / "stray.txt").write_text("x\n")
    return r


def _peer_lane(i: int, r: Path, sync_dir: Path) -> None:
    """One of the other three lanes, writing into the shared checkout.

    Models `lane_targeted` / `lane_corpus` / `lane_audit`: a stage that edits a
    tracked file in the middle of its own work. It does NOT restore, because
    the question is what the probe does to a write that is still IN FLIGHT.
    """
    deadline_reached = True
    import time as _t
    end = _t.monotonic() + _SYNC_S
    while _t.monotonic() < end:
        if (sync_dir / "started").exists():
            deadline_reached = False
            break
        _t.sleep(0.02)
    if deadline_reached:
        return
    (r / f"payload{i}.txt").write_text(f"lane {i} was in the middle of this\n")
    (sync_dir / f"go{i}").write_text("1")


def _run_with_peers(r: Path, sync_dir: Path, **audit_kw):
    threads = [threading.Thread(target=_peer_lane, args=(i, r, sync_dir),
                                daemon=True) for i in range(_PEERS)]
    for t in threads:
        t.start()
    try:
        return G.audit(r, timeout=_T, **audit_kw)
    finally:
        for t in threads:
            t.join(timeout=_SYNC_S)


def _kinds(res, kind: str):
    return [f for f in res.findings if f["kind"] == kind]


def _peer_bytes_survived(r: Path) -> int:
    return sum(1 for i in range(_PEERS)
               if (r / f"payload{i}.txt").read_text().startswith("lane "))


# --------------------------------------------------------------------------
# GREEN: the failing shape — four lanes, one checkout — with nothing wrong
# --------------------------------------------------------------------------
def test_four_lanes_in_one_checkout_produce_no_accusation(tmp_path, monkeypatch):
    """THE SHAPE THAT WENT RED IN PRODUCTION, with no defect in any gate."""
    sync = tmp_path / "sync"
    sync.mkdir()
    r = _repo(tmp_path, sync, sync_on_arm="checkout")
    monkeypatch.setenv("VIBEIC_CHECKOUT_CONCURRENT_LANES", str(_PEERS + 1))

    res = _run_with_peers(r, sync)

    assert _kinds(res, "GATE_CORRUPTED_CHECKOUT") == [], (
        "a write by one of the other three lanes was charged to a gate that "
        "never touched the file")
    assert _peer_bytes_survived(r) == _PEERS, (
        "`git checkout --` reverted another lane's in-flight work: not filing "
        "the finding is only half the fix")
    named = {label for label, _ in (res.unattributed or [])}
    assert "a read-only gate that writes nothing" in named, (
        "the skipped attribution has to be NAMED — a zero nobody looked for is "
        "the mirror of the false accusation it replaced")
    why = dict(res.unattributed or [])["a read-only gate that writes nothing"]
    assert "VIBEIC_CHECKOUT_CONCURRENT_LANES" in why, why


def test_the_shipping_wiring_never_opens_the_bracket_at_all(tmp_path):
    """Arm A comes from the outer record, so nothing of ours writes here.

    This is `repo_hygiene_gates.sh:2608` — `--jobs 8` with
    `GATE_DISPATCH_ATTESTATION_FILE` set. No declaration of the concurrent
    window is made, precisely because the point is that this path needs none:
    a bracket over a tree this drive never writes to has no true positive in it.
    """
    sync = tmp_path / "sync"
    sync.mkdir()
    r = _repo(tmp_path, sync, sync_on_arm="worktree")
    att = tmp_path / "outer.jsonl"
    for label, script in (("a read-only gate that writes nothing", "quiet.py"),
                          ("a second read-only gate", "second.py")):
        A.append_private_jsonl(att, A.process_attestation(
            label, "[PASS] 1 item examined\n", 0,
            G._expand(f"python3 {script}", r), roots=(r,)))

    res = _run_with_peers(r, sync, checkout_attestations=att)

    assert _kinds(res, "GATE_CORRUPTED_CHECKOUT") == [], res.findings
    assert res.verdict == "PASS", res.findings
    assert _peer_bytes_survived(r) == _PEERS, (
        "another lane's in-flight work was reverted by a probe that ran "
        "nothing in this tree")
    assert not (res.unattributed or []), (
        "nothing was skipped here: there was no write of ours to attribute, "
        "which is a different statement from `I could not tell`")


# --------------------------------------------------------------------------
# RED: the constructed violations. A check that cannot go red is not a check.
# --------------------------------------------------------------------------
def test_an_exclusive_run_still_files_and_still_repairs(tmp_path, monkeypatch):
    """THE CONTROL. Same fixture, same peers, window NOT declared.

    A run that really does own its checkout is `test_issue1029_the_killer_must
    _clean_up`'s subject, and the detector there must survive this change. If
    this test goes green, the fix bought silence rather than correctness.
    """
    sync = tmp_path / "sync"
    sync.mkdir()
    r = _repo(tmp_path, sync, sync_on_arm="checkout")
    monkeypatch.delenv("VIBEIC_CHECKOUT_CONCURRENT_LANES", raising=False)

    res = _run_with_peers(r, sync)

    corrupted = _kinds(res, "GATE_CORRUPTED_CHECKOUT")
    assert corrupted, (
        "a write inside an EXCLUSIVE window is this drive's by construction "
        "and must still be reported — see vibe-ic#1029")
    assert _peer_bytes_survived(r) == 0, (
        "and it must still be undone: a SIGKILLed gate's mutation is what the "
        "repair exists for")
    assert not (res.unattributed or []), (
        "the window WAS exclusive, so nothing may be filed as unattributed — "
        "a clean measurement reported as `I could not look` is the mirror of "
        "the false accusation, and it reached `parallel_audit` 6 gates out of "
        "6 before this assertion existed: " + repr(res.unattributed))


def test_a_genuinely_host_dependent_gate_is_still_caught_under_four_lanes(
        tmp_path, monkeypatch):
    """The fix must not make the PROBE quiet, only the accusation honest."""
    r = tmp_path / "counter"
    (r / "tools" / "ci").mkdir(parents=True)
    (r / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        'run "counter" "$ROOT" python3 counter.py\n')
    (r / "counter.py").write_text(
        "import pathlib\n"
        "print('PASS', len(list(pathlib.Path('.').glob('*.dat'))))\n")
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    (r / "left-over.dat").write_text("")        # the local state it reads
    monkeypatch.setenv("VIBEIC_CHECKOUT_CONCURRENT_LANES", "4")

    res = G.audit(r, timeout=_T)

    assert res.verdict == "FAIL", res
    assert _kinds(res, "HOST_DEPENDENT_VERDICT"), res.findings


# --------------------------------------------------------------------------
# the declaration itself
# --------------------------------------------------------------------------
def test_an_absent_declaration_means_one_lane_not_an_unknown(monkeypatch):
    """Absence must not be read as `probably concurrent`.

    That direction would retire the #1029 detector on every standalone run and
    print nothing while doing it. Both the unset and the unparseable case
    resolve to 1, which is the only value that keeps a red arm possible.
    """
    monkeypatch.delenv("VIBEIC_CHECKOUT_CONCURRENT_LANES", raising=False)
    assert G.declared_concurrent_lanes() == 1
    monkeypatch.setenv("VIBEIC_CHECKOUT_CONCURRENT_LANES", "")
    assert G.declared_concurrent_lanes() == 1
    monkeypatch.setenv("VIBEIC_CHECKOUT_CONCURRENT_LANES", "not a number")
    assert G.declared_concurrent_lanes() == 1
    monkeypatch.setenv("VIBEIC_CHECKOUT_CONCURRENT_LANES", "4")
    assert G.declared_concurrent_lanes() == 4


def test_two_drivers_on_one_checkout_cannot_be_inside_each_others_bracket(
        tmp_path, monkeypatch):
    """The claim is exclusive PER CHECKOUT and shared across processes.

    `parallel_audit --jobs N` gives every worker the same `repo_root`, and two
    independent invocations on one host land on the same tree too. Neither is
    covered by an environment variable, so the claim is a real lock.
    """
    monkeypatch.delenv("VIBEIC_CHECKOUT_CONCURRENT_LANES", raising=False)
    r = tmp_path / "one"
    r.mkdir()
    lock_root = tmp_path / "locks"
    with G._CheckoutClaim(r, want=True, wait_s=0.5,
                          lock_root=lock_root) as first:
        assert first.held
        with G._CheckoutClaim(r, want=True, wait_s=0.5,
                              lock_root=lock_root) as second:
            assert not second.held, (
                "two drivers held the same checkout at once, so each would "
                "charge the other's writes to its own gate")
            assert "another driver" in second.why, second.why
    assert first.held, (
        "`held` is the record the caller reads AFTER the window closes; "
        "resetting it on exit makes every attributed gate report itself as "
        "skipped")
    with G._CheckoutClaim(r, want=True, wait_s=0.5,
                          lock_root=lock_root) as third:
        assert third.held, "the claim was not released"


# --------------------------------------------------------------------------
# the second line of defence, from an independent measurement in this repo
# --------------------------------------------------------------------------
def test_a_path_written_again_after_the_drive_is_named_not_reverted(
        tmp_path, monkeypatch):
    """`docs/capture/2026-08-22-jcapsha/evidence/concurrent_repair`, item 1.

    That capture watched this function take a live editor's uncommitted line
    out of a tracked file twenty-six seconds after it was typed, with no
    message to the editor, and manufacture a `GATE_CORRUPTED_CHECKOUT` against
    a gate that had written nothing. Its first prescription is to re-read the
    path in the instant before `git checkout --` and refuse when it moved
    again, because a file written twice inside one drive is not a file only
    the child touched.

    The two reads are forced to disagree through `_path_digest` because there
    is no way to race a real second writer into that window on purpose. What
    is asserted is the CONSEQUENCE: the bytes are still there afterwards.
    """
    r = tmp_path / "r"
    r.mkdir()
    (r / "payload.txt").write_text(_ORIGINAL)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    (r / "payload.txt").write_text("an editor was part way through this\n")

    seen = {"n": 0}

    def moving_target(_path):
        seen["n"] += 1
        return f"digest-{seen['n']}"

    monkeypatch.setattr(G, "_path_digest", moving_target)
    repaired, refused = G._repair_checkout(r, {}, "some gate")

    assert repaired == [], repaired
    assert any("written AGAIN" in x for x in refused), refused
    assert (r / "payload.txt").read_text().startswith("an editor"), (
        "the editor's uncommitted work was discarded anyway")


def test_a_path_that_stayed_put_is_still_repaired(tmp_path):
    """THE CONTROL for the test above. Without it the narrowing could be a
    blanket refusal, which retires the repair rather than aiming it."""
    r = tmp_path / "r"
    r.mkdir()
    (r / "payload.txt").write_text(_ORIGINAL)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    (r / "payload.txt").write_text("what the driven child wrote\n")

    repaired, refused = G._repair_checkout(r, {}, "some gate")

    assert repaired == ["payload.txt"], (repaired, refused)
    assert (r / "payload.txt").read_text() == _ORIGINAL


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
