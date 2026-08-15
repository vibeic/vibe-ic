#!/usr/bin/env python3
"""`sta` and `openroad` must offer the same timing engine.

WHY THIS EXISTS
===============
The image ships two ways to run static timing analysis, and on 2026-07-30 they
disagreed about what the toolchain can do:

    openroad built-in     10 of 10 vibeic superset commands present
    standalone `sta`       0 of 10

The built-in engine is our `vibeic/sta-timing-eco` code, compiled from the
`src/sta` submodule. The standalone binary is upstream's, byte-identical to the
one in `hpretl/iic-osic-tools` — it is never copied out of the build, so the
base image's copy survives and is what `/foss/tools/bin/sta` resolves to
(vibeic-eda#8).

The consequence is invisible from either side. A flow step that shells out to
`sta` gets an engine with no crosstalk delta-delay, no path-based analysis, no
noise screening. Nothing errors: the commands are simply absent, and an absent
Tcl command in a script that does not call it looks exactly like a working
install. The version strings actively mislead — `openroad` reports 2.7.0 from a
hardcoded bazel genrule while carrying current code, `sta` reports 3.1.0 from a
June build that has none of it, so the engine reporting the LOWER version is the
current one.

WHAT IT REFUSES TO DO
=====================
* Pass because it could not ask. No docker, no image, a container that failed to
  start — all rc 2 with the reason named. A parity check that cannot run has not
  found parity.
* Pass on an empty probe list. Zero commands checked trivially yields zero
  disagreements, which is the shape this whole gate exists to reject.
* Report a command missing from BOTH engines as a disagreement. That is a stale
  probe list, not a packaging fault, and it is reported separately so the list
  gets fixed instead of the gate being ignored.

Exit: 0 the two agree, 1 they do not, 2 could not check.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Dict, List, Tuple

RC_AGREE, RC_DISAGREE, RC_CANNOT_CHECK = 0, 1, 2

DEFAULT_IMAGE = "ghcr.io/vibeic/vibeic-eda:0.3.2"

#: Commands that exist ONLY on `vibeic/sta-timing-eco`, taken from its diff
#: against upstream master rather than from memory. Every one must be reachable
#: from BOTH entry points; a command missing from both is a stale list, not a
#: finding (see `--probe`).
SUPERSET_COMMANDS = (
    "crosstalk_delta_delay", "crosstalk_eco", "multi_scenario_merge",
    "noise_glitch_peak", "propagate_activity", "propagated_noise",
    "report_pba", "timing_window_overlap", "useful_skew", "whatif_eco",
)

_PROBE_TCL = """\
set cmds {{{cmds}}}
foreach c $cmds {{
  if {{[llength [info commands $c]] || [llength [info commands sta::$c]]}} {{
    puts "HAVE $c"
  }} else {{
    puts "MISS $c"
  }}
}}
"""


def _run(argv: List[str], timeout: int = 180) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "docker not found"
    except (OSError, subprocess.SubprocessError) as exc:
        return 126, "", f"{type(exc).__name__}: {exc}"


def _probe(image: str, entrypoint: str, commands: Tuple[str, ...],
           positional: bool) -> Tuple[Dict[str, bool], str]:
    """{command: present} for one engine, or ({}, reason).

    `positional` is not cosmetic and is not guessed: `openroad` takes the script
    after `-exit`, `sta` takes it positionally (from each binary's own -help).
    Passing openroad's form to sta yields NO OUTPUT AT ALL — silently — which
    would read as "no commands present" and manufacture a disagreement. The
    empty-output guard below exists because I hit exactly that.
    """
    import tempfile
    from pathlib import Path
    tcl = _PROBE_TCL.format(cmds=" ".join(commands))
    with tempfile.TemporaryDirectory() as d:
        Path(d, "probe.tcl").write_text(tcl, encoding="utf-8")
        args = (["-no_init", "/w/probe.tcl"] if positional
                else ["-no_init", "-exit", "/w/probe.tcl"])
        rc, out, err = _run(["docker", "run", "--rm", "-v", f"{d}:/w",
                             "--entrypoint", entrypoint, image, *args],
                            timeout=300)
    if rc == 127:
        return {}, "docker is not installed"
    seen = {c: False for c in commands}
    got_any = False
    for line in (out or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in ("HAVE", "MISS"):
            got_any = True
            seen[parts[1]] = parts[0] == "HAVE"
    if not got_any:
        return {}, (f"{entrypoint} produced no probe output (rc={rc}): "
                    f"{(err or out).strip()[:160]}")
    return seen, ""


#: A two-flop design through an inverter. Small enough to run in seconds, real
#: enough that a divergent engine gives different numbers.
_EQUIV_V = """\
module top (input clk, input d, output q);
  wire n1, n2;
  sky130_fd_sc_hd__dfxtp_1 f1 (.CLK(clk), .D(d),  .Q(n1));
  sky130_fd_sc_hd__inv_1   i1 (.A(n1),   .Y(n2));
  sky130_fd_sc_hd__dfxtp_1 f2 (.CLK(clk), .D(n2), .Q(q));
endmodule
"""

#: `openroad`'s `read_verilog` goes through OpenROAD's database and needs a tech
#: LEF; `sta`'s is OpenSTA's own reader and liberty alone suffices. Same command
#: name, different prerequisite — the discovery that killed the wrapper idea in
#: vibeic-eda#8. The LEF reads are harmless under `sta`, so one script serves
#: both.
_EQUIV_TCL = """\
set K /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd
catch {read_lef $K/techlef/sky130_fd_sc_hd__nom.tlef}
catch {read_lef $K/lef/sky130_fd_sc_hd.lef}
read_liberty $K/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog /w/top.v
link_design top
create_clock -name clk -period 10 [get_ports clk]
set_input_delay 1.0 -clock clk [get_ports d]
set_output_delay 1.0 -clock clk [get_ports q]
puts "EQ_MAX [format %.9f [sta::worst_slack -max]]"
puts "EQ_MIN [format %.9f [sta::worst_slack -min]]"
"""


def _equivalence(image: str) -> Tuple[Dict[str, str], str]:
    """{engine: "max|min"} — the same timing question asked of both.

    Command PRESENCE is not equivalence. vibeic-eda#8 measured 20/20 core
    commands in both engines and then found `read_verilog` requiring a tech LEF
    in one and not the other — a name that matched while the thing behind it did
    not. A gate that only counts names would pass an image whose two engines
    compute different numbers, which is the failure it exists to prevent.
    """
    import tempfile
    from pathlib import Path
    out: Dict[str, str] = {}
    with tempfile.TemporaryDirectory() as d:
        Path(d, "top.v").write_text(_EQUIV_V, encoding="utf-8")
        Path(d, "eq.tcl").write_text(_EQUIV_TCL, encoding="utf-8")
        for entry, positional in (("openroad", False), ("sta", True)):
            args = (["-no_init", "/w/eq.tcl"] if positional
                    else ["-no_init", "-exit", "/w/eq.tcl"])
            rc, so, se = _run(["docker", "run", "--rm", "-v", f"{d}:/w",
                               "--entrypoint", entry, image, *args], timeout=300)
            vals = {}
            for line in (so or "").splitlines():
                pr = line.split()
                if len(pr) == 2 and pr[0] in ("EQ_MAX", "EQ_MIN"):
                    vals[pr[0]] = pr[1]
            if len(vals) != 2:
                return {}, (f"{entry} did not produce both slack values "
                            f"(rc={rc}): {(se or so).strip()[:160]}")
            out[entry] = f"{vals['EQ_MAX']}|{vals['EQ_MIN']}"
    return out, ""


def check(image: str, commands: Tuple[str, ...], *, equivalence: bool = True) -> dict:
    if not commands:
        return {"error": "no commands to probe; a check of zero commands finds "
                         "zero disagreements and cannot report parity"}
    # `sta` takes the script positionally, `openroad` after -exit. Established
    # from each binary's own -help rather than assumed.
    ored, err1 = _probe(image, "openroad", commands, positional=False)
    if err1:
        return {"error": f"openroad: {err1}"}
    sta, err2 = _probe(image, "sta", commands, positional=True)
    if err2:
        return {"error": f"sta: {err2}"}

    eq_err, eq_vals = "", {}
    if equivalence:
        eq_vals, eq_err = _equivalence(image)

    only_openroad = sorted(c for c in commands if ored.get(c) and not sta.get(c))
    only_sta = sorted(c for c in commands if sta.get(c) and not ored.get(c))
    neither = sorted(c for c in commands if not ored.get(c) and not sta.get(c))
    return {"image": image, "probed": len(commands),
            "openroad_present": sum(1 for c in commands if ored.get(c)),
            "sta_present": sum(1 for c in commands if sta.get(c)),
            "only_openroad": only_openroad, "only_sta": only_sta,
            "in_neither": neither,
            "equivalence": eq_vals, "equivalence_error": eq_err,
            "equivalent": bool(eq_vals) and len(set(eq_vals.values())) == 1}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--image", default=DEFAULT_IMAGE)
    ap.add_argument("--baseline", default=None,
                    help="JSON register of ALREADY-KNOWN divergences. Only NEW "
                         "ones fail; the recorded set is reported every run so "
                         "it stays visible rather than becoming permission.")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    res = check(a.image, SUPERSET_COMMANDS)
    if a.json:
        from pathlib import Path
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(
            {"program": "sta_engine_parity_check", **res}, indent=2) + "\n",
            encoding="utf-8")

    if "error" in res:
        print(f"[NOT CHECKED] {res['error']}. This is NOT 'the engines agree'.",
              file=sys.stderr)
        return RC_CANNOT_CHECK

    # Behaviour, reported before the name comparison because a name-only PASS is
    # exactly what this half exists to stop being sufficient.
    if res.get("equivalence_error"):
        print(f"[NOT CHECKED] the equivalence run did not complete: "
              f"{res['equivalence_error']}. Command presence alone is NOT "
              f"parity — vibeic-eda#8 had 20/20 names matching while one of "
              f"them behaved differently.", file=sys.stderr)
        return RC_CANNOT_CHECK
    if res.get("equivalence") and not res.get("equivalent"):
        print(f"[FAIL] the two engines computed DIFFERENT timing for the same "
              f"design in {res['image']}:", file=sys.stderr)
        for eng, v in sorted(res["equivalence"].items()):
            mx, _, mn = v.partition("|")
            print(f"    {eng:9s} worst_slack max={mx} min={mn}", file=sys.stderr)
        print("  The command surface can still match while this differs; that is "
              "why it is measured separately.", file=sys.stderr)
        return RC_DISAGREE

    if res["in_neither"]:
        # The probe list has drifted from the fork. Say so rather than letting
        # it quietly shrink the denominator.
        print(f"  {len(res['in_neither'])} probed command(s) are in NEITHER "
              f"engine — the list is stale, not the packaging: "
              f"{', '.join(res['in_neither'])}", file=sys.stderr)

    # A gate that fails on a KNOWN, un-fixable-from-here defect blocks every
    # landing until someone deletes the gate. The register makes the existing
    # divergence visible on every run while letting a NEW one still stop a
    # landing — which is the case this exists to catch. The recorded set is
    # printed, never silently subtracted: a debt nobody sees becomes permission.
    known_or, known_sta = set(), set()
    if a.baseline:
        from pathlib import Path
        bp = Path(a.baseline)
        if bp.exists():
            try:
                b = json.loads(bp.read_text())
                known_or = set(b.get("only_openroad") or [])
                known_sta = set(b.get("only_sta") or [])
            except (OSError, ValueError) as exc:
                print(f"[NOT CHECKED] baseline {bp} unreadable: {exc}. A "
                      f"register that cannot be read is not an empty register.",
                      file=sys.stderr)
                return RC_CANNOT_CHECK
    new_or = [c for c in res["only_openroad"] if c not in known_or]
    new_sta = [c for c in res["only_sta"] if c not in known_sta]
    recorded = len(res["only_openroad"]) - len(new_or) + \
               len(res["only_sta"]) - len(new_sta)
    if recorded:
        print(f"  {recorded} divergence(s) recorded as known debt "
              f"(vibeic-eda#8): openroad has them, sta does not.",
              file=sys.stderr)
    if a.baseline and not (new_or or new_sta):
        # The equivalence result belongs here too. Without it this line reads as
        # a clean bill while saying nothing about the half that actually
        # compares BEHAVIOUR — which is the half the name comparison cannot
        # substitute for.
        eq = ""
        if res.get("equivalent"):
            eq = (" Both compute identical timing (worst_slack max="
                  + next(iter(res["equivalence"].values())).split("|")[0] + ").")
        print(f"[PASS] no NEW divergence between the two engines in "
              f"{res['image']} ({recorded} recorded).{eq}", file=sys.stderr)
        return RC_AGREE
    if a.baseline:
        res = {**res, "only_openroad": new_or, "only_sta": new_sta}

    if res["only_openroad"] or res["only_sta"]:
        print(f"[FAIL] the two timing engines in {res['image']} do not agree.",
              file=sys.stderr)
        print(f"  openroad has {res['openroad_present']}/{res['probed']}, "
              f"sta has {res['sta_present']}/{res['probed']}", file=sys.stderr)
        if res["only_openroad"]:
            print(f"  in openroad but NOT in sta ({len(res['only_openroad'])}): "
                  f"{', '.join(res['only_openroad'])}", file=sys.stderr)
            print("  A flow step shelling out to `sta` gets an engine without "
                  "these, and nothing errors — the commands are simply absent.",
                  file=sys.stderr)
        if res["only_sta"]:
            print(f"  in sta but NOT in openroad ({len(res['only_sta'])}): "
                  f"{', '.join(res['only_sta'])}", file=sys.stderr)
        return RC_DISAGREE

    eqnote = ""
    if res.get("equivalent"):
        mx = next(iter(res["equivalence"].values())).split("|")[0]
        eqnote = f" and compute identical timing (worst_slack max={mx})"
    print(f"[PASS] both engines expose the same {res['probed']} command(s)"
          f"{eqnote} in {res['image']}.", file=sys.stderr)
    return RC_AGREE


if __name__ == "__main__":
    sys.exit(main())
