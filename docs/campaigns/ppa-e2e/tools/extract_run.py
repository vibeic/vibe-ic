#!/usr/bin/env python3
"""Drive the SHIPPED _ppa backends/domain modules over one phase-3 run tree.

This is a CALLER of the machinery, not a modification of it. It exists because
(measured, see RESULT.md FINDING F-2) `ppa_metric_extract.py --backend TOOL`
refuses to drive any backend, and only `_ppa/backends/openroad.py` and
`_ppa/timing.py` ship a CLI -- so yosys proxy area and the power split have no
shipped entry point. Every record below is produced by the shipped library
function; nothing here parses a tool.

Usage: extract_run.py <run-dir> <out-dir> [--label L]
Exit codes follow docs/PPA_INTERFACES.md §1.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

PLUGIN = Path("/home/reyerchu/_jppae2e/wt/vibe-ic-marketplace/plugins/vibe-ic")
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

from _ppa.backends import openroad as or_be           # noqa: E402
from _ppa.backends import yosys as ys_be              # noqa: E402
from _ppa import power as ppower                      # noqa: E402
from _ppa import canonical_json as cj                 # noqa: E402


def _power_pvt_scope(run, rep):
    """(extra_scope, why) -- the PVT + mode the power axis's REQUIRED_SCOPE needs.

    process / voltage / temperature come from the SHIPPED liberty-stem parser;
    mode comes from the design's own pvt_matrix.json, and only when it declares
    exactly one (two would make the attribution an invention). Anything that
    cannot be established is simply absent -- never a sentinel.
    """
    from _ppa.backends import opensta as _osta
    extra, why = {}, []
    lib = None
    for r in (rep.get("metrics") or []) if isinstance(rep, dict) else []:
        lib = (r.get("scope") or {}).get("liberty") or lib
    lib = lib or (rep.get("liberty") if isinstance(rep, dict) else None)
    if lib is None:
        src = rep.get("source") if isinstance(rep, dict) else None
        lib = (src or {}).get("liberty") if isinstance(src, dict) else None
    if lib:
        pvt = _osta.parse_liberty_pvt(str(lib))
        for k, v in (("process", pvt.process), ("voltage_v", pvt.voltage_v),
                     ("temperature_c", pvt.temperature_c)):
            if v is not None:
                extra[k] = v
        why.append(f"process/voltage/temperature from opensta.parse_liberty_pvt({lib!r})")
        if pvt.gaps:
            why.append(f"parser gaps: {pvt.gaps}")
    else:
        why.append("no liberty name in the power report: PVT NOT_MEASURED, not guessed")
    pvtm = run / "phase2" / "stage2" / "constraints" / "pvt_matrix.json"
    if pvtm.is_file():
        try:
            modes = json.loads(pvtm.read_text()).get("modes")
        except Exception:
            modes = None
        if isinstance(modes, list) and len(set(map(str, modes))) == 1:
            extra["mode"] = str(modes[0])
            why.append(f"mode from {pvtm.name} (exactly one declared)")
        else:
            why.append(f"{pvtm.name} declares {modes!r}: mode not attributable")
    else:
        why.append("no pvt_matrix.json: mode NOT_MEASURED")
    return extra, "; ".join(why)


def _derive_power_stage(run, rpt):
    """(stage, why) derived from the power session's OWN declared inputs.

    Reads the tcl the runner drove (and the report's provenance header) for the
    netlist that was linked and whether any SPEF was read. A power number is
    scoped by what it was computed ON, not by which directory it was filed in.
    """
    import re as _re
    tcls = [run / "reports" / "phase3" / "power_spm.tcl",
            run / "phase3" / "stage3" / "sta" / "power_spm.tcl"]
    tcl = next((t for t in tcls if t.is_file()), None)
    netlist, spef = None, False
    if tcl is not None:
        txt = tcl.read_text(errors="ignore")
        m = _re.search(r"^\s*read_verilog\s+(\S+)", txt, _re.M)
        if m:
            netlist = m.group(1)
        spef = bool(_re.search(r"^\s*read_spef\b", txt, _re.M))
        src = f"{tcl.relative_to(run)}"
    else:
        txt = rpt.read_text(errors="ignore")
        m = _re.search(r"^#\s*netlist:\s*(\S+)", txt, _re.M)
        netlist = m.group(1) if m else None
        src = f"{rpt.relative_to(run)} provenance header"
    if netlist is None:
        # None, NOT the word "unknown". The sentence beside it already said the
        # stage "is not asserted" while the token returned asserted one:
        # `"unknown" == "unknown"`, so two runs whose stage nobody could derive
        # reached `check_scope_parity` as two runs measured at the SAME stage.
        # The producer omits the key on None; the reason travels in `why`.
        return None, (f"{src} declares no linked netlist; the stage a "
                      "power number belongs to cannot be established, so "
                      "it is not asserted")
    n = netlist.replace(str(run), "").lstrip("/")
    if "/pnr/" in n or "routed" in n or "_pnr" in n:
        return (("post_route_extracted" if spef else "post_route_no_extraction"),
                f"{src} links {n}" + (" and reads a SPEF" if spef else
                                      " and reads NO SPEF"))
    if "stage2/synth" in n or n.endswith("_synth.v"):
        return "synth", (f"{src} links {n}, the PRE-PnR synthesis netlist, and "
                         f"reads {'a' if spef else 'NO'} SPEF -- so this number "
                         "is a synthesis-stage estimate whatever directory it "
                         "was filed in")
    return None, f"{src} links {n}, which this deriver does not classify"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run"); ap.add_argument("out"); ap.add_argument("--label", default="")
    a = ap.parse_args(argv)
    run, out = Path(a.run).resolve(), Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not run.is_dir():
        print(f"[CANNOT CHECK] {run} is not a directory", file=sys.stderr); return 2

    problems, wrote = [], {}

    # ---- 1. OpenROAD: physical area / route / DRV / antenna, per stage ------
    pnr = run / "phase3" / "stage3" / "pnr"
    if pnr.is_dir():
        r = subprocess.run([sys.executable, str(PROGRAMS / "_ppa/backends/openroad.py"),
                            "--run-dir", str(pnr), "--json", str(out / "openroad.json")],
                           capture_output=True, text=True, timeout=600, cwd=str(PROGRAMS))
        wrote["openroad"] = r.returncode
        if r.returncode != 0:
            problems.append(f"openroad backend rc={r.returncode}: {r.stderr.strip()[:300]}")
    else:
        problems.append(f"no pnr dir at {pnr}: NOT_MEASURED, not zero")

    # ---- 2. Timing: one row per (check, corner, clock) view ----------------
    r = subprocess.run([sys.executable, str(PROGRAMS / "_ppa/timing.py"), str(run),
                        "--json", str(out / "timing.json")],
                       capture_output=True, text=True, timeout=600, cwd=str(PROGRAMS))
    wrote["timing"] = r.returncode
    if r.returncode != 0:
        problems.append(f"timing rc={r.returncode}: {r.stderr.strip()[:300]}")

    # ---- 3. Power: split + ACTIVITY BASIS, via _ppa/power.py ---------------
    prpt = run / "reports" / "phase3" / "power.rpt"
    if prpt.is_file():
        rep = ppower.read_power_report(prpt)
        if rep is None:
            problems.append(f"[CANNOT CHECK] {prpt} could not be parsed as a power report")
        else:
            # The stage is DERIVED from the report's OWN provenance line, never
            # asserted from the directory it was filed in. See RESULT.md F-7:
            # this flow files a power report under reports/phase3/ whose text
            # says "post-PnR netlist" while its `netlist:` line names the
            # PRE-PnR synthesis netlist and no SPEF is read.
            stage, why = _derive_power_stage(run, prpt)
            # RESULT.md F-8: _ppa/benchmark.REQUIRED_SCOPE["power_mw"] demands
            # (stage, mode, process, voltage_v, temperature_c, activity_basis),
            # but _ppa/power.py emits only stage + activity_basis + the liberty
            # FILE NAME. The PVT is recoverable from that name by the shipped
            # _ppa/backends/opensta.parse_liberty_pvt, which power.py does not
            # call. Supplied here through the module's own `extra_scope` hook,
            # using the shipped parser -- nothing is invented.
            extra, pvt_why = _power_pvt_scope(run, rep)
            doc = ppower.power_document(rep, stage=stage, scenario="default",
                                        extra_scope=extra)
            doc["stage_derivation"] = why
            doc["pvt_scope_derivation"] = pvt_why
            (out / "power.json").write_text(json.dumps(doc, indent=2) + "\n")
            wrote["power"] = 0
            if stage != "post_route_extracted":
                problems.append(
                    (f"power stage DERIVED as {stage!r}: {why}" if stage
                     else f"power stage NOT ESTABLISHED, so `scope.stage` is "
                          f"omitted rather than named: {why}"))
    else:
        problems.append(f"no power report at {prpt}: NOT_MEASURED, not zero")

    # ---- 4. Yosys PROXY area (kept apart from physical area) ---------------
    slog = run / "phase2" / "stage2" / "synth" / "synth.log"
    if slog.is_file():
        text = slog.read_text(errors="ignore")
        recs = []
        for stage, kind in (("synth_generic", "generic"), ("synth_mapped", "mapped")):
            recs.extend(ys_be.records_from_stat(text, stage=stage, kind=kind,
                                                path=str(slog.relative_to(run))))
        (out / "yosys_proxy_area.json").write_text(
            json.dumps({"schema": "vibeic.ppa.metric_set.v1", "records": recs}, indent=2) + "\n")
        wrote["yosys"] = 0
    else:
        problems.append(f"no synth log at {slog}: proxy area NOT_MEASURED, not zero")

    summary = {"schema": "vibeic.ppae2e.extraction.v1", "run": str(run),
               "label": a.label, "wrote": wrote, "problems": problems}
    (out / "extraction.json").write_text(json.dumps(summary, indent=2) + "\n")
    for p in problems:
        print(p, file=sys.stderr)
    print(f"extract[{a.label}]: wrote={wrote} problems={len(problems)}")
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
