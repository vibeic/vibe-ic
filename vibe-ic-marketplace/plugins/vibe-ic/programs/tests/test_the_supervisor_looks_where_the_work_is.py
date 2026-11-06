"""A child told to work INSIDE a container must be supervised inside it.

MEASURED on spm x gf180mcuD, run8 (2026-09-21, image 0.3.67): the `gds` step's
own extras carry

    die_finishing: false
    die_finishing_note: "die finishing did NOT complete: STALLED: no forward
    progress across 12 consecutive looks (15.00s apart, 195.2s elapsed);
    signals readable: cpu,io,output; cmd: ... die_finishing_gen.py ..."

and the work that call was doing had ALREADY produced
`phase3/stage3/pnr/spm.sealed.gds` (95,414,116 B) and
`reports/phase3/sealring_verify.json` — `pdk_seal_ring_present`, top cell
chip_top, ring 0..3162 um outer / 16..3146 um inner, 201,182 um2 added, core
clearance MEASURED with 0 encroaching polygons, `verdict: PASS`. Only
`reports/phase3/die_finishing.json` was never written: the process was reaped
between the verify and the write. `die_finishing_check` then exited rc=2
("die_finishing_gen has not run"), `tapeout_precheck` booked
UNDETERMINED/General.SealRing, and a die that HAS a verified seal ring carried
that as one of five sign-off FAILs.

The supervisor was not wrong about what it could see. `_progress_run`'s own
header states this shape (vibe-ic#2083) and ships the remedy: the host-side
python client's CPU, I/O and output all sit flat while KLayout computes inside
the container, so a caller that knows where its work lives injects a probe that
looks THERE. Three call sites in the runner hand their child
`VIBEIC_EDA_CONTAINER=<container>` and then watched only the client.

Both directions are tested: a quiet child whose CONTAINER work advances is not
reaped, and a child that has genuinely stopped everywhere still is.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _progress_run as _pr  # noqa: E402

#: Fast supervision for the two behavioural arms: the stall window is
#: `stall_looks * poll_s`, and `poll_s` is floored at twice this host's own
#: measured spawn cost, so the window is short but never below what the host
#: can actually observe.
_FAST = dict(stall_looks=3, poll_s=0.2, capture_output=True, text=True)
#: Longer than the stall window above by a wide margin, so "not reaped" is a
#: statement about the supervisor and not about the child finishing first.
_QUIET_CHILD = [sys.executable, "-c", "import time; time.sleep(6)"]


def _advancing():
    """A channel that reports real movement, like a busy container tree."""
    state = {"n": 0.0}

    def factory(signals):
        def probe(_proc):
            state["n"] += 1.0
            signals["container"] = True
            return state["n"]
        return probe
    return factory


def _flat(readable=True):
    """A channel that is readable and reports NOTHING moving."""
    def factory(signals):
        def probe(_proc):
            if not readable:
                return None
            signals["container"] = True
            return 7.0                      # same score at every look
        return probe
    return factory


# --------------------------------------------------------------- the wiring





def test_every_call_site_that_names_a_container_supervises_inside_it():
    """The invariant, not the three instances: any runner function that hands
    its child `VIBEIC_EDA_CONTAINER` must also supervise through that
    container. A fourth such call site added without the probe fails here."""
    tree = ast.parse((PROGRAMS / "phase3_one_shot_runner.py").read_text())
    offenders, checked = [], 0
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        src = ast.dump(fn)
        if "VIBEIC_EDA_CONTAINER" not in src:
            continue
        for call in [c for c in ast.walk(fn) if isinstance(c, ast.Call)]:
            f = call.func
            if not (isinstance(f, ast.Attribute)
                    and isinstance(f.value, ast.Name) and f.value.id == "_pr"
                    and f.attr.startswith("run")):
                continue
            checked += 1
            if not any(k.arg == "progress_probe" for k in call.keywords):
                offenders.append(f"{fn.name}:{call.lineno}")
    assert checked >= 3, f"expected the three known call sites, saw {checked}"
    assert offenders == [], (
        "these calls tell the child which container to work in and then "
        f"supervise only the host client: {offenders}")


# ------------------------------------------------------- both directions

@pytest.mark.timeout(0)
def test_a_quiet_child_whose_container_work_advances_is_not_reaped():
    """The defect, as a test. The child burns no CPU, writes nothing and does
    no I/O — every host-side signal is flat — but the injected channel moves,
    so the supervisor waits and the child completes."""
    cp = _pr.run(_QUIET_CHILD, progress_probe=_advancing(), **_FAST)
    assert cp.returncode == 0


@pytest.mark.timeout(0)
def test_a_child_that_has_genuinely_stopped_is_still_reaped():
    """The other direction, and the one that must not be lost: nothing moves
    on any channel, inside the container or out, so the stall still fires."""
    with pytest.raises(_pr.Stalled) as exc:
        _pr.run(_QUIET_CHILD, progress_probe=_flat(), **_FAST)
    assert "no forward progress" in str(exc.value)


@pytest.mark.timeout(0)
def test_the_best_effort_form_reports_that_stall_as_an_rc_not_an_exception():
    """What the three call sites actually use, so the arm above is the one
    that reaches them."""
    cp = _pr.run_best_effort(_QUIET_CHILD, progress_probe=_flat(), **_FAST)
    assert cp.returncode == _pr.RC_STALLED
    assert "no forward progress" in cp.stderr


@pytest.mark.timeout(0)
def test_the_added_channel_can_only_make_it_more_patient():
    """`fuse_probes` is a disjunction: an unreadable or motionless container
    channel must not erase a host signal that IS moving. The child here burns
    CPU while the injected channel stays flat, and it is not reaped."""
    busy = [sys.executable, "-c",
            "import time\nt=time.time()\nwhile time.time()-t < 3: pass"]
    cp = _pr.run(busy, progress_probe=_flat(), **_FAST)
    assert cp.returncode == 0
    cp = _pr.run(busy, progress_probe=_flat(readable=False), **_FAST)
    assert cp.returncode == 0
