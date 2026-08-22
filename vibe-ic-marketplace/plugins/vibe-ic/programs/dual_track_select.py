#!/usr/bin/env python3
"""dual_track_select.py — deterministic DUAL-TRACK convergence selector.

The dual-track pattern (ORGANIC #716; IC Expert DB measurement 2026-07-02):
two INDEPENDENT authors produce candidate RTL for the same design — a PRIMARY
attempt (the general spec-to-rtl digest) and a SECOND-track attempt (guided by
the IC Expert DB design-class knowledge). Their pass-sets are complementary
(measured union 38→51 on 94 hard CVDP designs), so the win comes from KEEPING
WHICHEVER candidate the verification PASSes — not from trusting one author.

This program is the DETERMINISTIC "keep the passing one" step: the selection is
made by a gate/verifier, never by an author self-report. Two tiers, honest about
what each can prove:

  * FUNCTIONAL tier — a functional verify command is supplied (an official
    scorer / a cocotb TB / a full-stack TB). Each candidate is run; the FIRST
    that PASSes wins (ground truth). This is where the +13 union lift is real.
  * STRUCTURAL tier — no functional oracle (the general Phase-1 path with only a
    spec). Fall back to a structural gate (iverilog elaborate + optional
    hygiene/conformance): pick a candidate that passes structurally; on a tie
    (all pass or all fail) keep the PRIMARY, because the primary single-track is
    the stronger prior (measured 38 vs 31). It does NOT claim functional
    correctness — it only avoids regressing below the primary.

chip-AGNOSTIC. The verify command is injected; this module owns only the
run-each-candidate + pick-the-passing-one logic.

Usage:
    dual_track_select.py --candidate primary=<file> --candidate db=<file> \\
        [--verify-cmd '<cmd with {rtl} placeholder>'] [--verify-pass-rc 0] \\
        [--structural-only] [--json OUT]
    # prints the winning candidate label + path; exit 0 if any selected.
"""
from __future__ import annotations
import argparse, json, os, shlex, subprocess, sys
from pathlib import Path
from typing import List, Optional, Tuple

_IVERILOG = "iverilog"


#: "I could not look" is NOT a verdict (vibe-ic#1332).
#:
#: Both probes below used to answer `bool`, and a bare `except` folded a MISSING
#: TOOL into `False` — the same value as "the tool ran and rejected this RTL".
#: On a host without `iverilog`, `select()` then reported `winner_label: None`
#: with the note "no candidate elaborates", which is indistinguishable from
#: "both candidates are broken RTL". Dual-track convergence discards a perfectly
#: good primary attempt because the host lacked a compiler.
#:
#: The repo already fixed this shape once: `_vacuous_exit.py` exists so a gate's
#: "could not look" never shares an exit code with its verdict, and 20 collection
#: ERRORs elsewhere refuse rather than vote — "iverilog not available — the gate
#: cannot enforce; refusing to emit ungated responses (#528)". This program
#: refused nothing; it silently voted FAIL.
#:
#: So the answer is three-valued. `None` means UNCHECKABLE and never counts as a
#: rejection. A timeout is `None` too: an answer that never arrived is not a
#: "no" — that is the same conflation one layer along.
ELABORATED, REJECTED, UNCHECKABLE = True, False, None


def _probe(argv: List[str], timeout: int) -> Tuple[Optional[bool], str]:
    """Run a blocking probe. -> (ELABORATED|REJECTED|UNCHECKABLE, reason)."""
    try:
        cp = subprocess.run(argv, capture_output=True, text=True,
                            timeout=timeout)
    except FileNotFoundError:
        return UNCHECKABLE, f"{argv[0]!r} is not on PATH"
    except PermissionError:
        return UNCHECKABLE, f"{argv[0]!r} is present but not executable"
    except subprocess.TimeoutExpired:
        return UNCHECKABLE, f"{argv[0]!r} did not answer within {timeout}s"
    except OSError as exc:                              # noqa: BLE001
        return UNCHECKABLE, f"{argv[0]!r} could not be run: {exc}"
    return (ELABORATED if cp.returncode == 0 else REJECTED,
            f"exit {cp.returncode}")


def _elaborates(rtl: Path, timeout: int = 120) -> Tuple[Optional[bool], str]:
    """Structural floor: does it elaborate under iverilog -g2012?

    Three answers, never two — see the note above.
    """
    # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build); fixed budget adequate — not an open-ended EDA generator
    return _probe([_IVERILOG, "-g2012", "-o", os.devnull, str(rtl)], timeout)


def _run_verify(cmd_tpl: str, rtl: Path, pass_rc: int,
                timeout: int) -> Tuple[Optional[bool], str]:
    """Functional oracle. Same three answers, for the same reason: a verify
    command that is not installed did not FAIL the candidate."""
    cmd = cmd_tpl.replace("{rtl}", str(rtl))
    argv = shlex.split(cmd)
    if not argv:
        return UNCHECKABLE, "empty --verify-cmd"
    got, why = _probe(argv, timeout)
    if got is UNCHECKABLE:
        return got, why
    return (ELABORATED if int(why.split()[-1]) == pass_rc else REJECTED, why)


def select(candidates: List[Tuple[str, Path]],
           verify_cmd: Optional[str] = None,
           verify_pass_rc: int = 0,
           timeout: int = 600) -> dict:
    """candidates: ordered [(label, path)], PRIMARY first (tie-break winner).
    Returns {tier, winner_label, winner_path, per_candidate, note}."""
    per = []
    # A tier that could not run its probe has NOT decided. `uncheckable` is
    # reported separately from `winner_label` so a reader can tell "nothing won"
    # from "nothing was measured" — they were the same JSON before #1332.
    # A MISSING FILE is a real answer, not an uncheckable one: the candidate was
    # examined and is absent.
    if verify_cmd:
        blocked = []
        for label, path in candidates:
            if not path.is_file():
                got, why = REJECTED, "candidate file does not exist"
            else:
                got, why = _run_verify(verify_cmd, path, verify_pass_rc, timeout)
            per.append({"label": label, "path": str(path),
                        "functional_pass": got, "why": why})
            if got is UNCHECKABLE:
                blocked.append(f"{label}: {why}")
            elif got is ELABORATED:
                return {"tier": "functional", "winner_label": label,
                        "winner_path": str(path), "per_candidate": per,
                        "uncheckable": False,
                        "note": "first candidate to PASS the functional verify (ground truth)"}
        if blocked and len(blocked) == len(candidates):
            return {"tier": "functional", "winner_label": None,
                    "winner_path": None, "per_candidate": per,
                    "uncheckable": True,
                    "note": "the functional verify could not be run for ANY "
                            "candidate, so nothing was measured — this is NOT "
                            "'no candidate passed': " + "; ".join(blocked)}
        return {"tier": "functional", "winner_label": None, "winner_path": None,
                "per_candidate": per, "uncheckable": False,
                "note": "no candidate passed the functional verify"}
    # STRUCTURAL tier — no functional oracle
    passing, blocked = [], []
    for label, path in candidates:
        if not path.is_file():
            got, why = REJECTED, "candidate file does not exist"
        else:
            got, why = _elaborates(path, timeout=min(timeout, 120))
        per.append({"label": label, "path": str(path),
                    "elaborates": got, "why": why})
        if got is UNCHECKABLE:
            blocked.append(f"{label}: {why}")
        elif got is ELABORATED:
            passing.append((label, path))
    if not passing and blocked and len(blocked) == len(candidates):
        return {"tier": "structural", "winner_label": None, "winner_path": None,
                "per_candidate": per, "uncheckable": True,
                "note": "the elaborator could not be run for ANY candidate, so "
                        "nothing was measured — this is NOT 'no candidate "
                        "elaborates': " + "; ".join(blocked)}
    if not passing:
        return {"tier": "structural", "winner_label": None, "winner_path": None,
                "per_candidate": per, "uncheckable": False,
                "note": "no candidate elaborates"}
    # tie-break: PRIMARY (first in the input order) wins — the stronger prior.
    for label, path in candidates:
        if any(label == l for l, _ in passing):
            return {"tier": "structural", "winner_label": label,
                    "winner_path": str(path), "per_candidate": per,
                    "uncheckable": False,
                    "note": "structural tier: elaborating candidate, PRIMARY-first "
                            "tie-break (does NOT prove functional correctness)"}
    return {"tier": "structural", "winner_label": None, "winner_path": None,
            "per_candidate": per, "uncheckable": False, "note": "unreachable"}


def _parse_candidate(s: str) -> Tuple[str, Path]:
    if "=" not in s:
        raise argparse.ArgumentTypeError(f"--candidate must be label=path: {s}")
    label, p = s.split("=", 1)
    return label, Path(p)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", action="append", type=_parse_candidate,
                    required=True, help="label=path; give PRIMARY first")
    ap.add_argument("--verify-cmd", default=None,
                    help="functional verify command; '{rtl}' is replaced per candidate")
    ap.add_argument("--verify-pass-rc", type=int, default=0)
    ap.add_argument("--structural-only", action="store_true",
                    help="force the structural tier even if --verify-cmd is given")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    vc = None if a.structural_only else a.verify_cmd
    rep = select(a.candidate, vc, a.verify_pass_rc, a.timeout)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(rep, indent=2))
    if rep["winner_label"]:
        print(f"WINNER [{rep['tier']}] {rep['winner_label']} -> {rep['winner_path']}")
        print(f"  {rep['note']}")
        return 0
    if rep.get("uncheckable"):
        # rc 2, following `_vacuous_exit`'s RC_PASS/RC_FAIL/RC_VACUOUS = 0/1/2.
        # Sharing rc 1 with NO_WINNER is the whole defect at the exit-code layer:
        # a caller that branches on the code would discard the primary track
        # because a tool was missing.
        print(f"UNCHECKABLE [{rep['tier']}] {rep['note']}")
        return 2
    print(f"NO_WINNER [{rep['tier']}] {rep['note']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
