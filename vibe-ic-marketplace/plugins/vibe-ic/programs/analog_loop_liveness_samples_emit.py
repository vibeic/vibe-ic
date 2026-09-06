#!/usr/bin/env python3
"""analog_loop_liveness_samples_emit.py — the samples `analog_loop_liveness_check`
eats, exported from the transient the analog runner ALREADY simulated.

WHY THIS PROGRAM EXISTS
-----------------------
`analog_loop_liveness_check` landed with a real CLI, a real judgement and NO
CALLER. It could not honestly acquire one, because nothing in `programs/`
emitted the thing it reads. Its input is a per-timepoint waveform set —
`{node: [values...]}` plus a time vector — and the A-track's own simulation
step, `analog_real_corner_sweep`, writes SCALARS: the `.measure.json` sidecar
and the `corner_results.json` record. A gate declared over a population nobody
can produce is a vacuous pass on every design, which is the exact shape that
gate was written to refuse:

    "a null result is only evidence if the thing that would have produced a
     non-null result was RUNNING"

So the missing half is a PRODUCER, and this is it. It does not simulate
anything new: it takes the deck `analog_real_corner_sweep` already wrote and
already ran (the deck AND its ngspice invocation log must both be on disk —
the same `#438(a)` rule that step uses to claim `simulator_run: true`), adds
ONE `wrdata` of the declared liveness nodes to that same transient, and exports
the columns.

WHERE THE NODE LIST COMES FROM — NOT FROM HERE
----------------------------------------------
`analog_a2_topology_emit` declares, per block type, the `{role: net}` map that
says which nets answer the liveness question, under its own
`LIVENESS_NODES_KEY`. That constant and that table are IMPORTED, never
restated: this file contains no design's net name, and a block type whose entry
declares no liveness nodes is an HONEST GAP (rc 2), not a failure.

FAIL-CLOSED, IN FOUR PLACES, AND WHY EACH ONE MATTERS
-----------------------------------------------------
Writing an EMPTY or PARTIAL samples file would hand the checker a population it
cannot read and buy a PASS — the vacuous pass, one layer down. So:

  1. NO TRANSIENT ON DISK. No deck with a `tran` card and a sibling ngspice
     log means the analog runner never simulated this block. Refuse, and name
     the directory that was searched and what was in it.
  2. A DECLARED NODE THAT THE DECK DOES NOT DRAW. The net is resolved against
     the deck's own `.subckt` structure. Not found, drawn in two subckts, or
     drawn in a subckt instantiated more than once → refuse and name the net.
     A probe pointed at a net that does not exist reports ABSENT and every
     window reads as dead — a red for the wrong reason.
  3. A TIME VECTOR THAT DOES NOT LINE UP. `wrdata` emits one (scale, value)
     column pair PER VECTOR. Every scale column must agree, point for point.
     They disagree only if the vectors came from different sweeps, and a
     per-node judgement over misaligned time is arithmetic on nothing.
  4. FEWER THAN TWO ROWS. One point is not a window.

On ANY refusal the samples file is not written, and a stale one from an earlier
run is REMOVED — an old file is exactly as good as an empty one to a checker
that cannot tell how old it is.

chip-AGNOSTIC. No design, block, net, PDK, vendor or part name appears here.
Every net is read from the A2 declaration; every path is read from the project.

    analog_loop_liveness_samples_emit.py PROJECT --block B
        [--container NAME] [--deck PATH] [--out PATH] [--json REPORT]

exit 0 → samples written; `checker_argv` in the report is the command to run
exit 1 → no such project / block (nothing was examined)
exit 2 → HONEST GAP: nothing was produced, and the report says exactly what
         was missing. NEVER an empty samples file.
exit 64 → usage error (see `_analog_producer_common`)
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated
import _atomic_artefact as _aa                      # noqa: E402
import _analog_producer_common as _pc               # noqa: E402
import analog_a2_topology_emit as _a2               # noqa: E402
import analog_real_corner_sweep as _rcs             # noqa: E402
import _designs_root as _dr                         # noqa: E402

PRODUCER = "analog_loop_liveness_samples_emit"
SCHEMA = 1

#: The checker this produces for. Named ONCE, and used both to build the argv
#: and to locate the program on disk.
CHECKER = "analog_loop_liveness_check"

#: Role (A2's word) → the checker's own flag. Both halves are other programs'
#: vocabulary; neither is invented here. The roles are the three
#: `analog_a2_topology_emit._group_invariants` admits; the flags are the three
#: `analog_loop_liveness_check.main` declares. `test_analog_loop_liveness_wiring`
#: EXECUTES the argv built from this table against the shipped checker, so a
#: rename on either side is a red rather than a silently dropped condition.
ROLE_TO_CHECKER_FLAG = {
    "reset": "--reset-node",
    "feedback": "--dac-node",
    "decision": "--decision-node",
}

#: The key the checker reads its time vector under (`--time-key` default).
TIME_KEY = "t"

#: Emitted beside the block's other A-track artefacts.
SAMPLES_NAME = "loop_liveness_samples.json"
VERDICT_NAME = "loop_liveness.json"

#: The infix this program stamps into the two files it leaves in the runner's
#: own `sizing_loop/`: the probe deck and the `wrdata` dump. It is also the
#: exclusion in `runner_transients` — without it a second run would find its
#: OWN probe deck in the directory it searches for the runner's, and export a
#: window from a deck this program wrote rather than from one the runner ran.
PROBE_INFIX = ".liveness"

_SUBCKT_RE = re.compile(r"^\s*\.subckt\s+(\S+)\s*(.*)$", re.I)
_ENDS_RE = re.compile(r"^\s*\.ends\b", re.I)
_CONTROL_RE = re.compile(r"^\s*\.control\b", re.I)
_ENDC_RE = re.compile(r"^\s*\.endc\b", re.I)
_TRAN_LINE_RE = re.compile(r"^\s*tran\s+\S+", re.I)


class Refusal(Exception):
    """An honest gap: nothing produced, and `self.args[0]` says what was
    missing. Never raised for a condition the checker itself should judge."""


# ── the declaration ───────────────────────────────────────────────────────
def declared_liveness_nodes(ir: Dict[str, Any]) -> Dict[str, str]:
    """`{role: net}` for this block, from A2 — the IR first, its library
    second. Neither spelling is restated here: both are read under
    `analog_a2_topology_emit.LIVENESS_NODES_KEY`.

    The IR is preferred because it is the artefact that survived A2's port
    binding; the library entry is the fallback for an IR emitted before the
    key was carried into it.
    """
    live = ir.get(_a2.LIVENESS_NODES_KEY)
    if isinstance(live, dict) and live:
        return {str(k): str(v) for k, v in live.items()}
    entry = _a2.LIBRARY.get(str(ir.get("block_type") or "")) or {}
    live = entry.get(_a2.LIVENESS_NODES_KEY)
    if isinstance(live, dict) and live:
        return {str(k): str(v) for k, v in live.items()}
    return {}


# ── the transient the runner already ran ──────────────────────────────────
def runner_transients(block_dir: Path) -> List[Path]:
    """Every deck under the block's `sizing_loop/` that IS a transient AND
    that the analog runner really executed.

    "Really executed" is the sibling `.ngspice.log`, which is
    `analog_real_corner_sweep`'s own rule for claiming `simulator_run: true`
    (#438(a)). A deck with no log is a deck that was written and not run, and
    exporting a waveform from it would be this program simulating something
    nobody asked for.
    """
    sl = block_dir / "sizing_loop"
    if not sl.is_dir():
        return []
    out = []
    for sp in sorted(sl.glob("*.sp")):
        if sp.name.endswith(PROBE_INFIX + ".sp"):
            continue                 # this program's own probe deck, not the
        log = sp.with_suffix(".ngspice.log")     # runner's transient
        if not log.is_file():
            continue
        try:
            text = sp.read_text(errors="replace")
        except OSError:
            continue
        if _rcs.tran_stop_ns(text) is None:
            continue
        out.append(sp)
    # The nominal knob-sweep deck first when there is one: it is the point the
    # sized verdict is taken at. Everything else keeps its sorted order.
    out.sort(key=lambda p: (0 if p.name.startswith("run_") else 1, p.name))
    return out


def _searched_detail(block_dir: Path) -> str:
    sl = block_dir / "sizing_loop"
    if not sl.is_dir():
        return f"{sl} does not exist"
    decks = sorted(sl.glob("*.sp"))
    logs = sorted(sl.glob("*.ngspice.log"))
    return (f"{sl} holds {len(decks)} deck(s) and {len(logs)} ngspice log(s); "
            f"none of them is a transient the runner executed")


# ── net → ngspice vector ──────────────────────────────────────────────────
def _blocks(deck: str) -> Tuple[Dict[str, List[str]], List[str]]:
    """(`{subckt: lines}`, top-level lines). A nested `.subckt` is attributed
    to its innermost enclosing definition, which is where its nets live."""
    subckts: Dict[str, List[str]] = {}
    top: List[str] = []
    stack: List[str] = []
    for raw in deck.splitlines():
        line = raw.split("*", 1)[0] if raw.lstrip().startswith("*") else raw
        m = _SUBCKT_RE.match(line)
        if m:
            name = m.group(1)
            stack.append(name)
            subckts.setdefault(name, []).append(line)
            continue
        if _ENDS_RE.match(line):
            if stack:
                stack.pop()
            continue
        (subckts.setdefault(stack[-1], []) if stack else top).append(line)
    return subckts, top


def _tokens(lines: List[str]) -> set:
    out = set()
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("*") or s.startswith("."):
            continue
        out.update(t.lower() for t in s.split() if "=" not in t)
    return out


def resolve_vector(deck: str, net: str) -> str:
    """The ngspice vector name for `net` in `deck`, or raise `Refusal`.

    Top level → `v(net)`. Inside exactly one `.subckt` that is instantiated
    exactly once at top level → `v(xinst.net)`. Anything else is ambiguous and
    is refused BY NAME: a probe pointed at the wrong node reads DEAD for every
    window, which is a red the design did not earn.
    """
    subckts, top = _blocks(deck)
    n = net.lower()
    if n in _tokens(top):
        return f"v({n})"
    owners = [name for name, lines in subckts.items() if n in _tokens(lines)]
    if not owners:
        raise Refusal(
            f"the declared liveness net {net!r} is drawn nowhere in the deck: "
            f"neither at top level nor in any of its "
            f"{len(subckts)} .subckt definition(s) "
            f"({', '.join(sorted(subckts)) or 'none'}). Exporting a vector "
            f"that does not exist would report ABSENT and read as a dead loop")
    if len(owners) > 1:
        raise Refusal(
            f"the declared liveness net {net!r} is drawn in "
            f"{len(owners)} subckts ({', '.join(sorted(owners))}); which "
            f"instance's copy the liveness question is about is not something "
            f"this program may decide")
    owner = owners[0]
    insts = [ln.strip().split()[0].lower() for ln in top
             if ln.strip() and not ln.strip().startswith(("*", "."))
             and ln.strip().split()[0][:1].lower() == "x"
             and ln.strip().split()[-1].lower() == owner.lower()]
    if len(insts) != 1:
        raise Refusal(
            f"the declared liveness net {net!r} lives in .subckt {owner!r}, "
            f"which the deck instantiates {len(insts)} time(s) at top level "
            f"({', '.join(insts) or 'none'}); a liveness probe needs exactly "
            f"one instance to point at")
    return f"v({insts[0]}.{n})"


# ── the probe deck ────────────────────────────────────────────────────────
def probe_deck(deck: str, vectors: List[str], out_path: str) -> str:
    """`deck` with ONE `wrdata` added to its existing transient.

    Nothing else is touched: same circuit, same stimulus, same `tran` card,
    same corner. The measurement this exports is the measurement the analog
    runner already took — which is the whole claim this producer makes.
    """
    lines = deck.splitlines()
    in_control = False
    for i, ln in enumerate(lines):
        if _CONTROL_RE.match(ln):
            in_control = True
            continue
        if in_control and _ENDC_RE.match(ln):
            break
        if in_control and _TRAN_LINE_RE.match(ln):
            body = " ".join(vectors)
            return "\n".join(lines[:i + 1]
                             + [f"wrdata {out_path} {body}"]
                             + lines[i + 1:]) + "\n"
    raise Refusal(
        "the deck has no `tran` line inside a `.control` block, so there is "
        "no transient here to export the declared nodes from")


def parse_wrdata(text: str, n_vectors: int) -> Tuple[List[float],
                                                     List[List[float]]]:
    """`wrdata` writes a (scale, value) COLUMN PAIR per vector. Returns the
    single time vector and one value list per vector, after proving that every
    scale column agrees point for point — they can only disagree if the
    columns came from different sweeps, and a verdict over misaligned time is
    arithmetic on nothing."""
    rows: List[List[float]] = []
    for ln in text.splitlines():
        parts = ln.split()
        if len(parts) != 2 * n_vectors:
            continue
        try:
            rows.append([float(x) for x in parts])
        except ValueError:
            continue
    if len(rows) < 2:
        raise Refusal(
            f"the transient produced {len(rows)} usable sample row(s) for "
            f"{n_vectors} vector(s); one point is not a window and no "
            f"liveness condition can be measured over it")
    t = [r[0] for r in rows]
    for k in range(1, n_vectors):
        col = [r[2 * k] for r in rows]
        if col != t:
            bad = next(i for i, (a, b) in enumerate(zip(t, col)) if a != b)
            raise Refusal(
                f"the time column of vector {k} disagrees with vector 0 at "
                f"row {bad} ({col[bad]} vs {t[bad]}); the columns did not "
                f"come from one sweep and cannot be judged against one window")
    return t, [[r[2 * k + 1] for r in rows] for k in range(n_vectors)]


# ── the run ───────────────────────────────────────────────────────────────
def emit(project: Path, block: str, container: str,
         deck_path: Optional[Path], out_path: Optional[Path]
         ) -> Tuple[int, Dict[str, Any]]:
    rec: Dict[str, Any] = {"producer": PRODUCER, "schema": SCHEMA,
                           "block": block, "consumer": CHECKER}
    bdir = project / "phase3" / "analog" / block
    ir_path = bdir / "topology.json"
    if not ir_path.is_file():
        rec.update(verdict="NO_INPUT",
                   reason=f"no A2 topology IR at {ir_path}")
        return _pc.RC_NO_INPUT, rec

    ir = json.loads(ir_path.read_text())
    roles = declared_liveness_nodes(ir)
    rec["block_type"] = ir.get("block_type")
    rec["liveness_nodes_declared"] = roles
    rec["liveness_nodes_key"] = _a2.LIVENESS_NODES_KEY
    if not roles:
        rec.update(verdict="NOT_DECLARED",
                   reason=(f"block type {ir.get('block_type')!r} declares no "
                           f"`{_a2.LIVENESS_NODES_KEY}` in "
                           f"analog_a2_topology_emit, so there is no loop "
                           f"whose liveness this could measure. NOT a "
                           f"failure: the question was never asked of this "
                           f"circuit class"))
        return _pc.RC_HONEST_GAP, rec

    samples_out = out_path or (bdir / SAMPLES_NAME)
    try:
        decks = ([deck_path] if deck_path else runner_transients(bdir))
        if not decks:
            raise Refusal(
                f"the analog runner has not simulated a transient for this "
                f"block: {_searched_detail(bdir)}. A liveness window has to "
                f"come from a run that happened")
        deck_file = decks[0]
        deck = deck_file.read_text(errors="replace")
        rec["deck"] = str(deck_file)
        rec["deck_sha256"] = _pc.file_digest(deck_file)
        rec["tran_stop_ns"] = _rcs.tran_stop_ns(deck)

        # The rail is exported too, so `--vdd` is MEASURED off the same window
        # rather than left at the checker's default. Both of the checker's
        # thresholds are fractions of it.
        rail = str((ir.get("rails") or {}).get("vdd") or "")
        order = sorted(roles)                    # deterministic column order
        nets = [roles[r] for r in order] + ([rail] if rail else [])
        vectors = [resolve_vector(deck, n) for n in nets]
        rec["vectors"] = dict(zip(nets, vectors))

        if not _rcs._ngspice_available(container):
            raise Refusal(
                f"ngspice is not reachable in container {container!r}, so the "
                f"declared nodes cannot be exported from the deck the runner "
                f"ran. Nothing is written: an empty samples file would buy "
                f"the checker a PASS over a population that was never read")
        host_root = _dr.resolve_host_root(project, container)
        wr_host = deck_file.with_suffix(PROBE_INFIX + ".wrdata")
        wr_cont = _rcs._container_path(container, host_root, wr_host)
        probe_host = deck_file.with_suffix(PROBE_INFIX + ".sp")
        _aa.write_text(probe_host, probe_deck(deck, vectors, wr_cont))
        probe_cont = _rcs._container_path(container, host_root, probe_host)
        ngspice = _rcs._resolve_ngspice(container)
        cp = _rcs._docker(
            container,
            f"{shlex.quote(ngspice)} -b {shlex.quote(probe_cont)} 2>&1",
            timeout=_rcs.sim_deadline_s(deck))
        rec["ngspice_rc"] = cp.returncode
        if not wr_host.is_file():
            tail = "\n".join((cp.stdout or "").splitlines()[-8:])
            raise Refusal(
                f"ngspice exited {cp.returncode} and wrote no waveform file "
                f"for the declared nodes. Last lines:\n{tail}")
        t, cols = parse_wrdata(wr_host.read_text(errors="replace"),
                               len(vectors))

        samples: Dict[str, Any] = {TIME_KEY: t}
        for net, col in zip(nets, cols):
            samples[net] = col
        _aa.write_json(samples_out, samples)
        rec["samples"] = str(samples_out)
        rec["sample_count"] = len(t)
        rec["window_s"] = t[-1] - t[0]

        argv = ["--samples-json", str(samples_out),
                "--time-key", TIME_KEY]
        for role in order:
            flag = ROLE_TO_CHECKER_FLAG.get(role)
            if flag:
                argv += [flag, roles[role]]
        if rail:
            vdd = max(samples[rail])
            rec["vdd_measured"] = vdd
            rec["vdd_source"] = (f"max of {rail!r} over the same window "
                                 f"(rails.vdd in the A2 IR)")
            argv += ["--vdd", repr(vdd)]
        rec["verdict"] = "EMITTED"
        rec["checker_argv"] = argv
        return _pc.RC_OK, rec
    except Refusal as exc:
        # A stale samples file is exactly as good as an empty one to a checker
        # that cannot tell how old it is.
        if samples_out.is_file():
            samples_out.unlink()
            rec["stale_samples_removed"] = str(samples_out)
        rec.update(verdict="REFUSED", reason=str(exc))
        return _pc.RC_HONEST_GAP, rec


def main(argv: Optional[List[str]] = None) -> int:
    ap = _pc.ProducerArgumentParser(
        prog=PRODUCER, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--block", required=True)
    ap.add_argument("--container", default=_pin.default_container_name())
    ap.add_argument("--deck", type=Path, default=None,
                    help="the transient deck to export from. Default: the "
                         "one analog_real_corner_sweep wrote AND ran.")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    project = a.project.resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return _pc.RC_NO_INPUT
    rc, rec = emit(project, a.block, a.container, a.deck, a.out)
    print(json.dumps(rec, indent=2))
    if a.json:
        _aa.write_text(a.json, json.dumps(rec, indent=2) + "\n")
    if rc == _pc.RC_HONEST_GAP:
        print(_pc.honest_gap_line(PRODUCER, rec.get("reason", "")),
              file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
