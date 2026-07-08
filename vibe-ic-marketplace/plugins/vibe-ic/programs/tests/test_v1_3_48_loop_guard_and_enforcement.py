"""v1.3.48 — the SECOND face of the watchdog primitive (`loop_guard`) + the
AST enforcement gate (`loop_watchdog_compliance_check`).

Owner directive: "let watchdog be the common process for loop in the vibe-ic
plugin; force AI to use such watchdog for any loop." Two halves:

  * loop_guard — a bounded, no-progress-aware driver for an IN-PROCESS
    convergence / poll / retry loop. Proven here: converges-early,
    hits-max_iter, breaks-on-no-progress, single-shot, progress-keeps-alive,
    deterministic (injected clock → ms).
  * loop_watchdog_compliance_check — the gate. Proven here: a synthetic
    offender file (raw `openroad` subprocess + `while True: sleep`) FAILs; a
    properly guarded / annotated file PASSes; the REAL programs/ tree PASSes
    (green at introduction); and the precision guards (bounded for-loop and
    reused-cmd-var never false-positive; loop_guard iterable is not flagged;
    the annotation escape hatch works).
"""
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import _watchdog as W  # noqa: E402
import loop_watchdog_compliance_check as G  # noqa: E402


# ── loop_guard behaviours ────────────────────────────────────────────────
def test_loop_guard_hits_max_iter():
    g = W.loop_guard("x", max_iter=5)
    seen = [i for i in g]
    assert seen == [0, 1, 2, 3, 4]
    assert g.reason == "max_iter"
    assert g.iterations == 5


def test_loop_guard_single_shot():
    g = W.loop_guard("once", max_iter=1)
    seen = [i for i in g]
    assert seen == [0]
    assert g.reason == "max_iter"
    assert g.iterations == 1


def test_loop_guard_converges_early_on_break():
    g = W.loop_guard("conv", max_iter=100)
    for i in g:
        if i == 2:
            break
    assert g.reason == "converged"
    assert g.iterations == 3          # yielded 0,1,2


def test_loop_guard_breaks_on_no_progress():
    """progress_fn plateaus → after `stall_iters` consecutive non-improving
    iterations the guard stops with reason 'stalled', well before max_iter."""
    g = W.loop_guard("stall", max_iter=50, stall_iters=3,
                     progress_fn=lambda: 7.0)     # never improves
    count = sum(1 for _ in g)
    assert g.reason == "stalled"
    # baseline primed at 7.0; iters 1,2,3 each fail to improve → stop after 3.
    assert count == 3
    assert g.iterations == 3


def test_loop_guard_progress_keeps_it_alive_to_max_iter():
    state = {"p": 0.0}

    def prog():
        state["p"] += 1.0            # strictly increasing → always progress
        return state["p"]

    g = W.loop_guard("live", max_iter=6, stall_iters=2, progress_fn=prog)
    count = sum(1 for _ in g)
    assert count == 6
    assert g.reason == "max_iter"    # never stalled — progress each iteration


def test_loop_guard_stalls_after_progress_then_plateau():
    seq = iter([1.0, 2.0, 3.0] + [3.0] * 20)   # improves 3x then plateaus

    def prog():
        return next(seq)

    g = W.loop_guard("mix", max_iter=50, stall_iters=2, progress_fn=prog)
    n = sum(1 for _ in g)
    assert g.reason == "stalled"
    # baseline primed at 1.0; loop improves at iters 0,1 (→2.0,3.0), then 2 flat
    # readings (iters 2,3) trip stall_iters=2 → stops after yielding 0,1,2,3.
    assert n == 4


def test_loop_guard_none_progress_carried_forward_not_progress():
    seq = iter([None, 5.0, None, 5.0, None, 5.0, None])

    def prog():
        return next(seq, 5.0)

    # after the first real reading (5.0) the value never improves; None must
    # NOT count as progress → it stalls.
    g = W.loop_guard("noneflap", max_iter=50, stall_iters=3, progress_fn=prog)
    for _ in g:
        pass
    assert g.reason == "stalled"


def test_loop_guard_injectable_clock_records_elapsed():
    ticks = iter([100.0, 137.0])
    g = W.loop_guard("clk", max_iter=2, clock=lambda: next(ticks))
    for _ in g:
        pass
    assert g.elapsed_s == 37.0


def test_loop_guard_rejects_bad_max_iter():
    with pytest.raises(ValueError):
        list(W.loop_guard("bad", max_iter=0))
    with pytest.raises(ValueError):
        list(W.loop_guard("bad", max_iter=3, stall_iters=0))


def test_loop_guard_stopped_early_property():
    g1 = W.loop_guard("a", max_iter=3)
    for i in g1:
        if i == 0:
            break
    assert g1.stopped_early is False          # caller converged
    g2 = W.loop_guard("b", max_iter=2)
    list(g2)
    assert g2.stopped_early is True           # hit the cap


# ── the enforcement gate: synthetic offenders + clean files ───────────────
def _write(tmp: Path, name: str, body: str) -> Path:
    p = tmp / name
    p.write_text(body)
    return p


def test_gate_flags_raw_long_subprocess(tmp_path):
    _write(tmp_path, "bad_sub.py",
           "import subprocess\n"
           "def f(x):\n"
           "    subprocess.run(['openroad', '-exit', x])\n")
    off = G.scan_programs(tmp_path)
    assert any(o.kind == "subprocess" and o.line == 3 for o in off), off


def test_gate_flags_while_true_sleep_poll(tmp_path):
    _write(tmp_path, "bad_loop.py",
           "import time\n"
           "def poll():\n"
           "    while True:\n"
           "        time.sleep(1)\n"
           "        if done():\n"
           "            break\n")
    off = G.scan_programs(tmp_path)
    assert any(o.kind == "while" for o in off), off


def test_gate_flags_docker_exec_long_tool_without_marker(tmp_path):
    _write(tmp_path, "bad_docker.py",
           "def run(c):\n"
           "    cmd = f'sta -no_init -exit {c}'\n"
           "    _docker_exec(c, cmd, timeout=1200)\n")
    off = G.scan_programs(tmp_path)
    assert any(o.kind == "docker_exec" for o in off), off


def test_gate_passes_marker_and_run_supervised_and_loop_guard(tmp_path):
    _write(tmp_path, "good.py",
           "def run(c):\n"
           "    cmd = f'sta -no_init -exit {c}'\n"
           "    _docker_exec(c, cmd, marker=cmd)\n"
           "    run_supervised(['yosys', '-s', 'x.ys'])\n"
           "def loop():\n"
           "    for i in loop_guard('r', max_iter=5):\n"
           "        do(i)\n")
    off = G.scan_programs(tmp_path)
    assert off == [], off


def test_gate_annotation_escape_hatch(tmp_path):
    _write(tmp_path, "annot.py",
           "import subprocess\n"
           "def f(x):\n"
           "    # watchdog-exempt: bounded single-file iverilog compile\n"
           "    subprocess.run(['iverilog', '-o', 'a.vvp', x])\n")
    assert G.scan_programs(tmp_path) == []


def test_gate_annotation_requires_nonempty_reason(tmp_path):
    _write(tmp_path, "annot_bare.py",
           "import subprocess\n"
           "def f(x):\n"
           "    # watchdog-exempt:\n"
           "    subprocess.run(['iverilog', '-o', 'a.vvp', x])\n")
    assert len(G.scan_programs(tmp_path)) == 1     # bare tag does not exempt


def test_gate_bounded_for_over_range_not_flagged(tmp_path):
    """A finite for-loop that launches a subprocess is bounded → the LOOP is
    not a class-(b) offense (the inner subprocess is judged by class (a))."""
    _write(tmp_path, "boundedfor.py",
           "import subprocess\n"
           "def f(items):\n"
           "    for it in items:\n"
           "        subprocess.run(['docker', 'ps'])\n")
    off = G.scan_programs(tmp_path)
    assert all(o.kind != "for" and o.kind != "while" for o in off), off
    assert off == []       # docker is benign argv0 → no (a) offense either


def test_gate_nearest_preceding_cmd_no_union_false_positive(tmp_path):
    """A cmd var reused for a long tool (marker'd) AND a short probe (marker-
    less) must NOT cross-contaminate: only the actual long-tool assignment is
    considered per call site."""
    _write(tmp_path, "reuse.py",
           "def run(c):\n"
           "    cmd = f'openroad -exit {c}'\n"
           "    _docker_exec(c, cmd, marker=cmd)\n"
           "    cmd = 'rm -rf /tmp/stage'\n"
           "    _docker_exec(c, cmd, timeout=20)\n")
    off = G.scan_programs(tmp_path)
    assert off == [], off


def test_gate_literal_presence_probe_not_flagged(tmp_path):
    """A literal tool PRESENCE probe (`command -v sta`) names the tool as an
    argument, not an invocation → must NOT be flagged (false-positive guard)."""
    _write(tmp_path, "probe.py",
           "def has(c):\n"
           "    cmd = 'command -v sta >/dev/null 2>&1'\n"
           "    return _docker_exec(c, cmd, timeout=10)[0] == 0\n")
    assert G.scan_programs(tmp_path) == []


def test_gate_argv_indirection_via_list_var_flagged(tmp_path):
    """`cmd = ['openroad', ...]; subprocess.run(cmd)` — argv indirection must
    still be flagged (false-negative guard)."""
    _write(tmp_path, "indirect.py",
           "import subprocess\n"
           "def f(x):\n"
           "    cmd = ['openroad', '-exit', x]\n"
           "    subprocess.run(cmd, capture_output=True)\n")
    off = G.scan_programs(tmp_path)
    assert any(o.kind == "subprocess" for o in off), off


def test_gate_infinite_iterator_with_subprocess_flagged(tmp_path):
    _write(tmp_path, "infinite.py",
           "import itertools, subprocess\n"
           "def f():\n"
           "    for i in itertools.count():\n"
           "        subprocess.run(['yosys', '-s', 'x.ys'])\n")
    off = G.scan_programs(tmp_path)
    assert any(o.kind == "for" for o in off), off


def test_gate_subprocess_inside_loop_guard_still_flagged(tmp_path):
    """loop_guard guards the LOOP, not the sub-process: a raw long-tool launch
    inside a guarded loop is still a class-(a) offense (no false-negative hole)."""
    _write(tmp_path, "inner.py",
           "import subprocess\n"
           "def f():\n"
           "    for i in loop_guard('r', max_iter=3):\n"
           "        subprocess.run(['openroad', '-exit', 'x'])\n")
    off = G.scan_programs(tmp_path)
    assert any(o.kind == "subprocess" for o in off), off


def test_gate_pure_parser_while_true_not_flagged(tmp_path):
    """A `while True` tokenizer/parser loop with neither sleep nor a
    sub-process cannot spin forever (bounded input) → not flagged."""
    _write(tmp_path, "parser.py",
           "def tok(s):\n"
           "    i = 0\n"
           "    while True:\n"
           "        if i >= len(s):\n"
           "            break\n"
           "        i += 1\n")
    assert G.scan_programs(tmp_path) == []


def test_gate_skips_watchdog_and_self(tmp_path):
    # files named like the primitive / the gate are never scanned.
    _write(tmp_path, "_watchdog.py",
           "import subprocess\n"
           "subprocess.run(['openroad', 'x'])\n")
    _write(tmp_path, "loop_watchdog_compliance_check.py",
           "import subprocess\n"
           "subprocess.run(['yosys', 'x'])\n")
    assert G.scan_programs(tmp_path) == []


# ── GREEN AT INTRODUCTION: the real programs/ tree passes ─────────────────
def test_real_programs_tree_is_watchdog_clean():
    off = G.scan_programs(PROG)
    assert off == [], (
        "the shipped programs/ tree must pass the gate at introduction; "
        f"offenders: {[(o.file, o.line, o.kind) for o in off]}")


def test_gate_cli_exit_codes(tmp_path, capsys):
    # clean dir → exit 0
    _write(tmp_path, "ok.py", "x = 1\n")
    assert G.main(["--programs-dir", str(tmp_path)]) == 0
    # offender → exit 1
    _write(tmp_path, "bad.py",
           "import subprocess\nsubprocess.run(['magic', '-dnull', 'x.tcl'])\n")
    assert G.main(["--programs-dir", str(tmp_path)]) == 1
