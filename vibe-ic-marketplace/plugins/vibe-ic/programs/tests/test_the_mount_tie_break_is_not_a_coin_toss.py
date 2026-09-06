"""`docker inspect`'s mount ordering is unstable; the mapping must not be.

THE DEFECT, MEASURED (lane rbspm2, issue #2061 / R-02, R-03).
`_container_mounts` sorted mounts by source length, `reverse=True`. Python's sort
is STABLE, so two mounts whose sources are the SAME LENGTH kept whatever order
`docker inspect` emitted — and that order is not stable: measured over 50 calls
per container, the host-unreadable `/foss/designs` won the tie **18 %** of the
time on one container and **10 %** on another.

`_to_container_path` returns the FIRST covering mount, so consumers that must
read the mapped file ON THE HOST (`dfm_screen_check` resolves via cuts from the
LEFs the run's pnr tcl names) sometimes got a path that exists only inside the
container. TWO RUNS OF ONE TREE PUBLISHED OPPOSITE VERDICTS: `3550 vias
UNRESOLVED / redundancy UNMEASURED` versus `resolved, single_cut_fraction 1.0,
VIA_REDUNDANCY_LOW`. A verdict that flips on a coin toss is worse than either
answer, because nothing in the record says a toss happened.

MUTATIONS THESE MUST KILL:
  * Restoring `sort(key=lambda t: len(t[0]), reverse=True)` fails
    `test_both_daemon_orderings_give_one_answer` — the two fake orderings then
    disagree, which is the defect exactly.
  * Dropping the host-existence term (keeping only a total order) fails
    `test_the_tie_prefers_the_destination_a_host_reader_can_open`.
  * Dropping the third key fails `test_the_order_is_total_even_when_both_exist`.
"""

import sys
import subprocess
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402


def _fake_inspect(monkeypatch, pairs):
    """Make `docker inspect` return exactly `pairs`, in that order."""
    R._CONTAINER_MOUNTS_CACHE.clear()
    out = "".join(f"{s}|{d}\n" for s, d in pairs)

    def _run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, out, "")
    monkeypatch.setattr(R.subprocess, "run", _run)


def test_both_daemon_orderings_give_one_answer(monkeypatch, tmp_path):
    """THE WHOLE POINT. Same two mounts, both emission orders, ONE mapping."""
    host = tmp_path / "onhost"          # exists on this host
    host.mkdir()
    # equal-length SOURCES — this is the tie the daemon used to decide
    src_a, src_b = "/lane/aaaa", "/lane/bbbb"
    assert len(src_a) == len(src_b)
    pairs = [(src_a, str(host)), (src_b, "/foss/designs_absent_here")]

    _fake_inspect(monkeypatch, pairs)
    first = R._container_mounts("c")
    _fake_inspect(monkeypatch, list(reversed(pairs)))
    second = R._container_mounts("c")
    assert first == second, (first, second)


def test_the_tie_prefers_the_destination_a_host_reader_can_open(monkeypatch,
                                                                tmp_path):
    host = tmp_path / "readable"
    host.mkdir()
    for order in ([("/lane/aaaa", "/foss/nope_absent"), ("/lane/bbbb", str(host))],
                  [("/lane/bbbb", str(host)), ("/lane/aaaa", "/foss/nope_absent")]):
        _fake_inspect(monkeypatch, order)
        got = R._container_mounts("c")
        assert got[0][1] == str(host), got


def test_the_order_is_total_even_when_both_exist(monkeypatch, tmp_path):
    """Two equal-length sources whose destinations BOTH exist must still
    resolve identically on every call — no residual dependence on the daemon."""
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    d1.mkdir(); d2.mkdir()
    pairs = [("/lane/aaaa", str(d1)), ("/lane/bbbb", str(d2))]
    _fake_inspect(monkeypatch, pairs)
    a = R._container_mounts("c")
    _fake_inspect(monkeypatch, list(reversed(pairs)))
    b = R._container_mounts("c")
    assert a == b, (a, b)


def test_longest_source_still_wins(monkeypatch, tmp_path):
    """THE CONTROL. The nested-mount rule is unchanged: a longer source must
    still beat a shorter one, even when the shorter one's destination exists
    and the longer one's does not."""
    host = tmp_path / "shallow"
    host.mkdir()
    _fake_inspect(monkeypatch, [("/lane", str(host)),
                                ("/lane/deep/deeper", "/foss/absent")])
    got = R._container_mounts("c")
    assert got[0][0] == "/lane/deep/deeper", got
    # and the translation follows it
    assert R._to_container_path("/lane/deep/deeper/x.lef", "c") == \
        "/foss/absent/x.lef"


def test_the_translation_is_stable_end_to_end(monkeypatch, tmp_path):
    """The property a consumer actually depends on."""
    host = tmp_path / "onhost"
    host.mkdir()
    pairs = [("/lane/aaaa", str(host)), ("/lane/bbbb", "/foss/absent")]
    _fake_inspect(monkeypatch, pairs)
    one = R._to_container_path("/lane/aaaa/x.lef", "c")
    _fake_inspect(monkeypatch, list(reversed(pairs)))
    two = R._to_container_path("/lane/aaaa/x.lef", "c")
    assert one == two == f"{host}/x.lef", (one, two)


def test_the_tie_break_is_not_a_bare_length_sort():
    """A structural guard: the defect was `sort(key=len, reverse=True)` leaving
    the tie to the daemon. It must not come back."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert "out.sort(key=lambda t: len(t[0]), reverse=True)" not in src
    assert "def _mount_rank" in src
