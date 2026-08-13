#!/usr/bin/env python3
"""The final filename exists ONLY IF the step completed. #1082.

THE CENTRAL TEST USES A REAL SIGKILL, in a real subprocess, against a real file.
`open(path,'w')` truncates at open, so the defect is not a race that needs luck
to hit — it is deterministic, and so is its absence after the fix. A test that
simulated the crash by raising an exception would have proved something weaker:
`finally` blocks run on exceptions and do NOT run on SIGKILL, and the whole point
of the rename is to survive the case no handler can reach.

Every assertion is paired. "leaves nothing behind" is trivially satisfiable by a
writer that never writes at all, so each crash case has a success twin from the
same helper.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN / "programs"))
import _atomic_output as AO  # noqa: E402

REPO = PLUGIN.parents[2]

#: Inner subprocess bound for every call site in this file. vibe-ic#1241.
#:
#: WHY IT IS ONE NAME AND NOT TWO NUMBERS: the two call sites here carried 120s
#: and 600s, and both are ABOVE the 60s harness ceiling. A bound over the
#: ceiling can outlive the 180s harness timeout, which kills the SESSION rather
#: than the test — so the number was a promise the harness would not keep, and
#: the two sites could drift apart again the moment one was edited.
#:
#: MEASURED, not guessed — the issue is explicit that this is a per-test
#: judgement and that lowering a bound to the ceiling and calling it fixed is
#: not one. Observed on this tree, `pytest --durations`:
#:
#:     test_the_shared_report_writer_now_publishes_atomically   0.09 s  (was 600 s)
#:     the `_sigkill_writer` sites (SIGKILL of a 6-line script) 0.02 s  (was 120 s)
#:     whole file, 16 tests                                     0.82 s
#:
#: 30 s is ~330x the slowest observed call and half the ceiling, so it is a
#: real bound with real headroom rather than a number chosen to satisfy a gate.
#: Neither test is a candidate for the issue's other remedy — "move it out of
#: the targeted subset if it genuinely needs longer" — because neither needs
#: longer; they are among the fastest tests in the tree.
_BOUND_S = 30

# A writer that opens its target, writes a PARTIAL document, and is SIGKILLed.
# `mode` selects which helper it uses; "direct" is the shipped idiom #1082 is
# about, and is the control that the crash is reachable at all.
_KILLER = r'''
import os, sys
sys.path.insert(0, {programs!r})
import _atomic_output as AO
target, mode = sys.argv[1], sys.argv[2]
if mode == "direct":
    fh = open(target, "w")            # TRUNCATES / CREATES NOW
    fh.write('{{"partial": ')
    fh.flush()
    os.kill(os.getpid(), 9)
elif mode == "atomic":
    with AO.atomic_output(target) as tmp:
        fh = open(tmp, "w")
        fh.write('{{"partial": ')
        fh.flush()
        os.kill(os.getpid(), 9)
'''


def _sigkill_writer(tmp_path: Path, mode: str, name: str = "report.json"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / f"killer_{mode}.py"
    script.write_text(_KILLER.format(programs=str(PLUGIN / "programs")))
    target = tmp_path / name
    r = subprocess.run([sys.executable, str(script), str(target), mode],
                       capture_output=True, text=True, timeout=_BOUND_S)
    return target, r


# ===========================================================================
# THE DEFECT, AND THE FIX, BOTH BY SIGKILL
# ===========================================================================
def test_THE_DEFECT_a_direct_write_leaves_a_partial_under_the_final_name(tmp_path):
    """The control. Without this, the fix below is a fix for nothing.

    This is the shipped idiom in 577 of the plugin's declared-output writers,
    measured on v1.10.33 with `os.replace` appearing in exactly 0 of them. If
    this test ever fails, the platform stopped truncating at open and #1082's
    premise needs re-deriving rather than repairing.
    """
    target, r = _sigkill_writer(tmp_path, "direct")
    assert r.returncode == -9, f"the writer was not SIGKILLed: {r.returncode}"
    assert target.exists(), (
        "a direct write that was killed mid-write left NO file, so this "
        "platform does not have the defect #1082 describes")
    body = target.read_text()
    assert body == '{"partial": ', repr(body)
    # ...and it is indistinguishable from a complete artefact to any consumer
    # that only asks whether the path exists.
    with pytest.raises(json.JSONDecodeError):
        json.loads(body)


def test_THE_FIX_an_atomic_write_killed_mid_write_leaves_NOTHING(tmp_path):
    """Same crash, same signal, same partial bytes — no final name."""
    target, r = _sigkill_writer(tmp_path, "atomic")
    assert r.returncode == -9, r.returncode
    assert not target.exists(), (
        f"a killed atomic write left {target.name} behind with "
        f"{target.read_text()!r}; the rename must not have been the last step")
    # The temp IS left, and that is the point: the evidence survives under a
    # name nothing downstream opens.
    temps = sorted(tmp_path.glob(AO.atomic_output_tmp_glob()))
    assert temps, "the partial bytes vanished entirely; the temp should remain"


def test_PAIRED_a_SUCCESSFUL_atomic_write_does_land(tmp_path):
    """The twin. "leaves nothing" is satisfied by a writer that never writes."""
    target = tmp_path / "ok.json"
    AO.atomic_write_json(target, {"a": 1})
    assert target.is_file() and json.loads(target.read_text()) == {"a": 1}
    assert not list(tmp_path.glob(AO.atomic_output_tmp_glob())), \
        "the temp file was not cleaned up by the rename"


# ===========================================================================
# THE TWO SEMANTICS ARE NOT INTERCHANGEABLE
# ===========================================================================
def test_a_finally_CANNOT_deliver_the_ORFS_semantics_under_SIGKILL(tmp_path):
    """WHY THE TRAP BELONGS IN THE SUPERVISOR. This test found a design error.

    The first version of `_atomic_output` translated ORFS's `trap … EXIT` as a
    `try/finally` inside the writer, on the reasoning that a log should survive a
    crash. It does not work, and this is the measurement that showed it: a
    `finally` does not run in a process that received SIGKILL, so the log was
    simply missing. ORFS's trap works because it lives in the PARENT SHELL, which
    outlives the step.

    Kept as the standing statement of that bound. If someone reintroduces a
    writer-side `finally` for this, this test is the reason not to.
    """
    target, r = _sigkill_writer(tmp_path / "f", "atomic", "step.log")
    assert r.returncode == -9, r.returncode
    assert not target.exists(), (
        "nothing inside the dying process published the log, which is the point")
    assert sorted(p.name for p in (tmp_path / "f").glob(AO.atomic_output_tmp_glob())), \
        "the partial bytes must survive under the temp name for the supervisor"


def test_the_SUPERVISOR_promotes_a_log_and_sweeps_a_declared_output(tmp_path):
    """`promote_orphan_temps` is ORFS's trap, in the place it can actually run.

    Both directions in one call, because the whole value is that it treats the
    two artefact classes DIFFERENTLY: promoting everything would republish the
    partial declared output #1082 exists to suppress, and sweeping everything
    would throw away the failed run's log.
    """
    root = tmp_path / "proj"
    (root / "reports").mkdir(parents=True)
    log_tmp = root / "reports" / "step.log.tmp.4242"
    out_tmp = root / "reports" / "metrics.json.tmp.4242"
    log_tmp.write_text("partial log line\n")
    out_tmp.write_text('{"partial": ')

    res = AO.promote_orphan_temps(root)

    assert res["promoted"] == ["reports/step.log"], res
    assert (root / "reports" / "step.log").read_text() == "partial log line\n"
    assert res["swept"] == ["reports/metrics.json.tmp.4242"], res
    assert not (root / "reports" / "metrics.json").exists(), (
        "the partial declared output was promoted to its final name — that is "
        "the lie #1082 removes")
    assert not out_tmp.exists(), "the swept temp is still there"


def test_an_exception_inside_the_block_publishes_nothing(tmp_path):
    """The reachable-handler case, distinct from SIGKILL and also covered."""
    target = tmp_path / "boom.json"
    with pytest.raises(RuntimeError):
        with AO.atomic_output(target) as tmp:
            tmp.write_text("half")
            raise RuntimeError("step died")
    assert not target.exists(), "an exception published the artefact anyway"
    assert not list(tmp_path.glob(AO.atomic_output_tmp_glob())), \
        "the temp was left behind on an exception the writer could see"


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
def test_BaseException_also_publishes_nothing(tmp_path, exc):
    """`except Exception` would have let Ctrl-C promote a partial artefact."""
    target = tmp_path / f"b_{exc.__name__}.json"
    with pytest.raises(exc):
        with AO.atomic_output(target) as tmp:
            tmp.write_text("half")
            raise exc()
    assert not target.exists()


def test_a_block_that_writes_nothing_is_an_ERROR_not_an_empty_file(tmp_path):
    """A writer that produced no bytes must not leave a final name behind.

    The tempting alternative — rename whatever is there, including nothing — is
    how a 0-byte declared output gets published, which is the same lie in a
    different costume.
    """
    target = tmp_path / "none.json"
    with pytest.raises(FileNotFoundError) as e:
        with AO.atomic_output(target):
            pass
    assert "without writing" in str(e.value)
    assert not target.exists()


def test_an_existing_artefact_survives_a_failed_rewrite(tmp_path):
    """The old bytes stay readable when the new write dies. `open('w')` would
    have destroyed them at open, before the new content existed."""
    target = tmp_path / "keepme.json"
    target.write_text('{"good": true}')
    with pytest.raises(RuntimeError):
        with AO.atomic_output(target) as tmp:
            tmp.write_text('{"bad"')
            raise RuntimeError("died")
    assert json.loads(target.read_text()) == {"good": True}


# ===========================================================================
# THE ATOMICITY PRECONDITION
# ===========================================================================
def test_the_temp_file_is_a_sibling_of_the_target(tmp_path):
    """`os.replace` is atomic only within one filesystem.

    A `/tmp` temp renamed onto a project path degrades to a copy — reopening the
    partial-write window this module closes. Same-directory is the precondition,
    not a preference.
    """
    target = tmp_path / "sub" / "x.json"
    seen = {}
    with AO.atomic_output(target) as tmp:
        seen["tmp"] = tmp
        tmp.write_text("{}")
    assert seen["tmp"].parent == target.parent, (
        f"temp {seen['tmp']} is not a sibling of {target}; the rename would "
        f"cross a filesystem boundary and stop being atomic")


def test_the_temp_name_carries_the_pid(tmp_path):
    """Two processes writing one target must not share a temp file."""
    target = tmp_path / "p.json"
    with AO.atomic_output(target) as tmp:
        assert str(os.getpid()) in tmp.name, tmp.name
        tmp.write_text("{}")


def test_json_is_serialised_before_anything_is_opened(tmp_path):
    """The cheap half of the fix: an unserialisable value cannot truncate."""
    target = tmp_path / "u.json"
    target.write_text('{"previous": true}')
    with pytest.raises(TypeError):
        AO.atomic_write_json(target, {"bad": object()})
    assert json.loads(target.read_text()) == {"previous": True}
    assert not list(tmp_path.glob(AO.atomic_output_tmp_glob()))


def test_sweep_removes_stale_temps_and_is_not_automatic(tmp_path):
    """A killed writer leaves its temp, deliberately. Sweeping is opt-in.

    Deleting files as a side effect of importing a module is how a debugging
    session loses the evidence it was about to read.
    """
    (tmp_path / "a.json.tmp.999").write_text("partial")
    (tmp_path / "keep.json").write_text("{}")
    gone = AO.sweep_stale_temps(tmp_path)
    assert gone == ["a.json.tmp.999"], gone
    assert (tmp_path / "keep.json").exists(), "the sweep took a real artefact"


# ===========================================================================
# THE ADOPTION, ON A REAL GATE
# ===========================================================================
_CELL = REPO / "benchmark-data" / "ic" / "spm" / "v1.9.96_gf180mcuD"


@pytest.mark.skipif(not _CELL.is_dir(), reason="published cell absent")
def test_the_shared_report_writer_now_publishes_atomically(tmp_path):
    """`eda_report_audit` is the declared-output writer behind SIX sign-off
    gates (drc / antenna / em / ir_drop / sta / lvs `_report_check`), so the
    invariant lands for all six at one site.

    Driven through the SHIPPED CLI, because the exit code and the file on disk
    are the product — not a return value read out of an import.
    """
    out = tmp_path / "sta.json"
    prog = PLUGIN / "programs" / "sta_report_check.py"
    r = subprocess.run(
        [sys.executable, str(prog), str(_CELL), "--mode", "sta",
         "--json", str(out)],
        capture_output=True, text=True, timeout=_BOUND_S)
    assert r.returncode == 0, (r.returncode, r.stdout[-400:], r.stderr[-400:])
    assert out.is_file() and json.loads(out.read_text()), out
    assert not list(tmp_path.glob(AO.atomic_output_tmp_glob())), \
        "the gate left a temp file behind"


def test_the_shared_writer_actually_calls_the_helper():
    """Static, and paired with the behavioural test above on purpose.

    The behavioural test would still pass if the helper were bypassed and the
    write happened to succeed — a successful direct write is indistinguishable
    from a successful atomic one. This asserts the call SITE, which is the part
    that decides what happens on the unsuccessful path.
    """
    src = (PLUGIN / "programs" / "eda_report_audit.py").read_text()
    assert "_atomic_output.atomic_write_text(args.json" in src, (
        "eda_report_audit no longer routes its declared output through "
        "_atomic_output; six sign-off gates lost the #1082 invariant")
    assert "Path(args.json).write_text(report_json)" not in src, (
        "the direct write is back alongside the atomic one")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
