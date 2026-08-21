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


def _elaborates(rtl: Path) -> bool:
    """Structural floor: does it elaborate under iverilog -g2012?"""
    try:
        # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build); fixed budget adequate — not an open-ended EDA generator
        cp = subprocess.run([_IVERILOG, "-g2012", "-o", os.devnull, str(rtl)],
                            capture_output=True, text=True, timeout=120)
        return cp.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _run_verify(cmd_tpl: str, rtl: Path, pass_rc: int, timeout: int) -> bool:
    cmd = cmd_tpl.replace("{rtl}", str(rtl))
    try:
        cp = subprocess.run(shlex.split(cmd), capture_output=True, text=True,
                            timeout=timeout)
        return cp.returncode == pass_rc
    except Exception:  # noqa: BLE001
        return False


def select(candidates: List[Tuple[str, Path]],
           verify_cmd: Optional[str] = None,
           verify_pass_rc: int = 0,
           timeout: int = 600) -> dict:
    """candidates: ordered [(label, path)], PRIMARY first (tie-break winner).
    Returns {tier, winner_label, winner_path, per_candidate, note}."""
    per = []
    # FUNCTIONAL tier
    if verify_cmd:
        for label, path in candidates:
            ok = path.is_file() and _run_verify(verify_cmd, path, verify_pass_rc, timeout)
            per.append({"label": label, "path": str(path), "functional_pass": ok})
            if ok:
                return {"tier": "functional", "winner_label": label,
                        "winner_path": str(path), "per_candidate": per,
                        "note": "first candidate to PASS the functional verify (ground truth)"}
        return {"tier": "functional", "winner_label": None, "winner_path": None,
                "per_candidate": per,
                "note": "no candidate passed the functional verify"}
    # STRUCTURAL tier — no functional oracle
    passing = []
    for label, path in candidates:
        ok = path.is_file() and _elaborates(path)
        per.append({"label": label, "path": str(path), "elaborates": ok})
        if ok:
            passing.append((label, path))
    if not passing:
        return {"tier": "structural", "winner_label": None, "winner_path": None,
                "per_candidate": per, "note": "no candidate elaborates"}
    # tie-break: PRIMARY (first in the input order) wins — the stronger prior.
    for label, path in candidates:
        if any(label == l for l, _ in passing):
            return {"tier": "structural", "winner_label": label,
                    "winner_path": str(path), "per_candidate": per,
                    "note": "structural tier: elaborating candidate, PRIMARY-first "
                            "tie-break (does NOT prove functional correctness)"}
    return {"tier": "structural", "winner_label": None, "winner_path": None,
            "per_candidate": per, "note": "unreachable"}


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
    print(f"NO_WINNER [{rep['tier']}] {rep['note']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
