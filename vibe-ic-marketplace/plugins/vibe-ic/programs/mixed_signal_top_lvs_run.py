#!/usr/bin/env python3
"""mixed_signal_top_lvs_run.py — REAL top-level mixed-signal merge +
LVS (flow-completeness review P1-2; M1 was a PASS-on-presence stub).

What it does (chip-AGNOSTIC; PDK paths derived from --pdk):
  1. MERGE: digital sign-off GDS + every analog hardmacro GDS into
     `phase3/mixed_signal/top_merged.gds` via a KLayout batch script
     (cells coexist in one layout; the digital DEF's macro instances
     resolve against the merged cell names). Skipped when the merged
     GDS already exists.
  2. EXTRACT: Magic `extract all` + `ext2spice lvs` (hierarchy
     preserved — macros stay subckts) on the merged GDS, with the
     PDK's own magicrc.
  3. COMPARE: netgen LVS of the extracted netlist vs the gate-level
     netlist + the hardmacro Verilog stubs (A8 emits them), using the
     PDK's netgen setup. The verdict comes from netgen's REAL compare.
  4. EMIT: `reports/analog/mixed_signal/merge.json` (the M1 gate /
     M4 rollup artifact) with verdict from the LVS result, plus
     `reports/analog/mixed_signal/top_lvs.json` + the netgen report.

Honesty rules: missing tool/tech/unreachable-project → SKIP rc 2 with
the named gap (the M1 gate then reports the merge as NOT LVS-verified
— it never PASSes on presence again); a real netgen mismatch → FAIL
rc 1.

FRESHNESS, NOT PRESENCE (2026-08-01). Every step's success test used to
be "does the output file exist on the HOST". Those files survive a
`cp -a` from another run in another directory, so an invocation in
which NO tool executed emitted, verbatim:

    "verdict": "FAIL", "compared": true,
    "reason": "netgen top-level LVS did not match — real compare ran
               on the merged GDS; design/extraction defect"

while `ext2spice_merged.log` and `top_lvs.rpt` kept mtimes from two
runs earlier. `mixed_signal_merge_check` — M1's BLOCKING gate — reads
that file. Here the stale verdict happened to be FAIL, so the cost was
a wasted round; a stale PASS carried the same way is a false clean by
the identical mechanism. Each tool step now requires its OWN log to
have been (re)written by THIS invocation and to carry the completion
marker the tool prints on success, and `compared` is set from that
rather than assumed. A reused `top_merged.gds` is reported by name in
`merge_provenance` instead of passing as this run's own work.

ENFORCEMENT: advisory
  This is a PRODUCER, not a verdict. It is invoked in M1's
  `advisory_program_exit_zero` slot and dispatched non-blocking from
  `vibe_ic_one_shot_runner` (M1-d4, 2026-07 — before that nothing
  invoked it at all, so M1's declared `top_merged.gds` and the
  `top_lvs.json` its gate demands were never written on any automated
  run and M1 could only come back MISSING). The BLOCKING verdict on
  the merge belongs to `mixed_signal_merge_check`, which reads the
  `top_lvs.json` written here — so nothing is certified without a real
  netgen compare, and an environment failure here does not become a
  second, duplicate blocking FAIL. NOTE: `flow_gate_enforcement_audit`
  reports this as ENFORCED because a runner does invoke it inline; that
  classification is about WIRING, and for a producer inline invocation
  means "it runs", not "it can block".

Usage:
    python3 mixed_signal_top_lvs_run.py <project> --top chip_top
        [--container vibeic-eda] [--pdk sky130A]
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402
import lvs_verdict_tokens as _lvt  # noqa: E402  — #524 shared verdict tokens

TOOLS_IN_CONTAINER = "/foss/tools"
PDKS_IN_CONTAINER = "/foss/pdks"

_KLAYOUT_MERGE_PY = """\
import pya, os
ly = pya.Layout()
ly.read(os.environ["DIGITAL_GDS"])
for g in os.environ["MACRO_GDS"].split(";"):
    if g.strip():
        ly.read(g.strip())
ly.write(os.environ["MERGED_OUT"])
print("KLAYOUT_MERGE_DONE", os.environ["MERGED_OUT"])
"""

_MAGIC_EXT_TCL = """\
crashbackups stop
gds readonly true
gds rescale false
gds read $env(GDS)
load $env(TOP)
select top cell
extract all
ext2spice lvs
ext2spice -o $env(SPICE_OUT)
puts "MAGIC_EXT2SPICE_DONE $env(SPICE_OUT)"
quit -noprompt
"""


def _docker_exec_raw(container, cmd, timeout=600):
    """Simple bounded wall-clock exec (monkeypatch surface for tests) — for
    short probes. Long tool runs use `_docker_exec(..., marker=...)` → the
    progress-stall watchdog."""
    import subprocess
    if container not in ("", "host"):
        # OWN container-side deadline: a host timeout kills only the
        # `docker exec` CLIENT and ORPHANS the tool inside the container
        # (see `_docker_watchdog.wrap_with_container_timeout`).
        import _docker_watchdog as _dw
        full = ["docker", "exec", container, "bash", "-lc",
                _dw.wrap_with_container_timeout(cmd, timeout)]
    else:
        full = ["bash", "-lc", cmd]
    try:
        r = subprocess.run(full, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller
        return 1, "", str(exc)


def _docker_exec(container, cmd, timeout=600, *, marker=None, log_path=None):
    """marker=None → `_docker_exec_raw` (short probes). marker set → the shared
    progress-stall watchdog (`_docker_watchdog.run_docker_supervised`): a long,
    open-ended run (KLayout merge, Magic ext2spice, netgen LVS — hours on a big
    merged GDS) is killed ONLY on NO forward progress, never on a fixed
    estimate. `marker` is a token already in the tool's argv. chip/tool-AGNOSTIC.
    Still a monkeypatch surface for tests (fakes absorb marker via **_)."""
    if marker is None:
        return _docker_exec_raw(container, cmd, timeout)
    import _docker_watchdog as _dw
    return _dw.run_docker_supervised(
        container, cmd, marker, docker_exec_raw=_docker_exec_raw,
        log_path=log_path)


def _to_container_path(p, container):
    return str(p)


def _project_reachable(container, project):
    """True when `project` resolves to a directory INSIDE the container.

    `_to_container_path` hands the tool the HOST path verbatim. When the run
    root is outside the container's mounted tree every `docker exec` below
    fails to find its inputs — and, because each step's success test was
    "does the output file exist on the HOST", a run in which no tool executed
    was indistinguishable from one in which they all did (see the
    `_ran_fresh` note). Ask once, up front, and SKIP by name instead."""
    if container in ("", "host"):
        return True
    rc, _, _ = _docker_exec(
        container, f"test -d {shlex.quote(str(project))}", timeout=15)
    return rc == 0


def _ran_fresh(log_path, marker, before):
    """True when `log_path` was (re)written by THIS invocation AND carries the
    tool's own completion marker.

    MEASURED DEFECT (2026-08-01). One invocation rewrote its own TCL scripts at
    04:37:16 and emitted `"compared": true, "reason": "... real compare ran on
    the merged GDS"`, while `ext2spice_merged.log` kept its 01:53:56 mtime and
    `top_lvs.rpt` its 00:21:37 — magic and netgen never executed. The success
    test was `spice_out.is_file()`, and those files had been carried forward by
    `cp -a` from a run in a DIFFERENT directory. Presence of an output is
    evidence that A run once happened, never that THIS run happened.

    `before` is the mtime captured before the call (None when absent). A log
    that did not advance, or that advanced without the marker the tool prints
    on success, means the tool did not complete here."""
    try:
        st = log_path.stat()
    except OSError:
        return False
    if before is not None and st.st_mtime <= before:
        return False
    if st.st_size == 0:
        return False
    if not marker:
        return True
    try:
        return marker in log_path.read_text(errors="replace")
    except OSError:  # pragma: no cover - unreadable right after writing it
        return False


def _mtime_or_none(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _tool_ok(container, tool):
    rc, _, _ = _docker_exec(container, f"command -v {tool} >/dev/null 2>&1",
                            timeout=10)
    return rc == 0


# ── C5 — RESOLVE THE TOP CELL AND THE PDK FROM THE PROJECT, NEVER FROM A
#    DESIGN-SPECIFIC LITERAL. ───────────────────────────────────────────────
# MEASURED DEFECT (2026-07-31): `--top` defaulted to the literal `chip_top` and
# `--pdk` to the literal `sky130A`, and M1's ONLY call site
# (`flow/phase1_phase2_phase3.yaml` advisory_program_exit_zero) passes NEITHER.
# On a design whose top is `u_hawaii_adc` on `ihp-sg13g2` this made Magic run
# `load chip_top` against a merged GDS that does not contain that cell —
#   Reading "u_hawaii_adc". / Cell chip_top couldn't be read / Creating new cell
#   / Warning: There is nothing here to extract.
# — and the program blamed the extraction ("produced no netlist"). Worse, the
# `--pdk` literal survived the tech SKIP-guard because sky130A really IS
# installed in the container, so Magic would have extracted an IHP SG13G2
# layout with SKY130 layer definitions had the top name been right: a presence
# check standing in for a correctness check.
#
# Both are now DERIVED FROM THE DESIGN'S OWN ARTEFACTS, and when they cannot be
# derived the program SKIPs saying so instead of guessing. chip/PDK-AGNOSTIC:
# no design name, cell name or PDK name appears below.
_DEF_DESIGN_RE = re.compile(r"^\s*DESIGN\s+(\S+)\s*;", re.MULTILINE)
_PDK_ROOT_RE = re.compile(re.escape(PDKS_IN_CONTAINER) + r"/([^/\s\"']+)/")


def resolve_top(project: Path, requested: "str | None" = None):
    """Return (top_cell, source). chip-AGNOSTIC.

    The DEF's own `DESIGN <name> ;` line is the authoritative answer: it names
    the cell that was actually floorplanned, placed, routed and streamed out,
    and the merged GDS this program extracts is built from that stream-out. An
    EXPLICIT `--top` still wins (a caller that names one has asserted it), but
    it is reported with its source so a wrong one is visible in the report.
    Returns (None, reason) when nothing in the project answers.
    """
    if requested:
        return requested, "explicit --top"
    for d in sorted(_pl.pnr_dir(project).glob("*.def")):
        try:
            m = _DEF_DESIGN_RE.search(d.read_text(errors="replace"))
        except OSError:
            continue
        if m:
            return m.group(1), f"DEF DESIGN line ({d.name})"
    # Second lane: the synthesis product is named after the top by construction.
    for v in sorted(_pl.synth_dir(project).glob("*_synth.v")):
        return v.stem[: -len("_synth")], f"synth netlist stem ({v.name})"
    return None, ("no DEF carries a DESIGN line and no *_synth.v exists — the "
                  "project does not state its top cell")


def resolve_pdk(project: Path, requested: "str | None" = None):
    """Return (pdk_name, source). chip/PDK-AGNOSTIC.

    The PDK is read back off the design's OWN back-end artefacts — the PnR /
    extraction scripts and logs name their PDK root explicitly in every
    `read_lef` / `-rcfile` path. That is the PDK the layout under test was
    actually built with, so it is the only one whose layer definitions can
    correctly extract it. Returns (None, reason) when nothing answers, and the
    caller SKIPs — it must never fall back to some other design's PDK.
    """
    if requested:
        return requested, "explicit --pdk"
    counts: "dict[str, int]" = {}
    roots = [_pl.pnr_dir(project), _pl.extracted_dir(project),
             project / "phase3" / "stage3", project / "reports" / "phase3"]
    for root in roots:
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in (
                    ".tcl", ".log", ".json", ".rpt", ".sh"):
                continue
            try:
                txt = f.read_text(errors="replace")
            except OSError:
                continue
            for name in _PDK_ROOT_RE.findall(txt):
                counts[name] = counts.get(name, 0) + 1
    if not counts:
        return None, (f"no back-end artefact under this project names a "
                      f"{PDKS_IN_CONTAINER}/<pdk> root — the PDK this layout "
                      f"was built with is not recoverable from the project")
    # Most-cited root wins; ties broken by name so the choice is deterministic.
    best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return best, (f"back-end artefacts ({counts[best]} reference(s) to "
                  f"{PDKS_IN_CONTAINER}/{best}/)")


def netgen_lvs_script(sch_paths, layout_path, layout_top, sch_top,
                      setup_path, report_path) -> str:
    """The Tcl netgen actually consumes, built so it can be tested without one.

    netgen's `lvs` takes a TWO-element `{filename cellname}` list per side; its
    own source falls back to treating the whole string as ONE filename when the
    list length is not 2. The schematic side here is always the gate netlist
    plus one `.v` per analog hardmacro, i.e. always >= 2 files, so it can never
    be expressed as that pair directly.

    netgen's answer is to read the files into ONE netlist first --
    `readnet <format> <file> <fnum>` forces a file into the netlist already held
    in `fnum` -- and then identify that netlist's top cell as `{<fnum> <cell>}`,
    which `CommonParseCell` accepts precisely because the first element is an
    integer file number.

    The schematic side is `{$fnum <top>}` and NOT a bare cell name. A bare name
    is ambiguous exactly when LVS is doing its job: both sides normally hold a
    cell of the same name, and `lay_top` defaults to `top` whenever the layout
    has no `_flat` subckt. Measured against netgen 1.5.323: the bare name
    resolved to the layout's copy and netgen refused with "Both cells are in the
    same netlist: Cannot compare!" -- while still exiting cleanly and writing no
    report, which is the second reason the caller judges on the report's
    existence rather than on an exit code.

    Words are wrapped in Tcl braces, not shell-quoted: this is a Tcl script, and
    shell quoting would reach netgen verbatim. The layout pair is braced too --
    `lvs` runs `llength` on it, and Tcl's list parser raises "unmatched open
    quote in list" on a word carrying a stray quote.
    """
    def _tcl(word) -> str:
        return "{" + str(word) + "}"

    lines = [f"set fnum [readnet verilog {_tcl(sch_paths[0])}]"]
    lines += [f"readnet verilog {_tcl(p)} $fnum" for p in sch_paths[1:]]
    lines.append(
        f"lvs {_tcl(str(layout_path) + ' ' + str(layout_top))} "
        f"[list $fnum {_tcl(sch_top)}] {_tcl(setup_path)} {_tcl(report_path)}")
    return "\n".join(lines) + "\n"


def lvs_failure_verdict(report_written: bool, rc: int, transcript: str) -> dict:
    """Distinguish "netgen compared and found a mismatch" from "netgen never
    compared anything".

    Both used to return the same sentence: "real compare ran on the merged GDS;
    design/extraction defect". That attributed to the DESIGN a comparison that
    had not happened -- netgen was aborting in ReadNetlist, before either side
    was loaded -- and it pointed the reader at an LVS report the run had never
    written.

    netgen writes its report only after loading both sides and comparing them,
    so the report's existence is the evidence of whether a comparison occurred.
    Either way the verdict stays FAIL: an LVS that cannot run is not a pass.
    What changes is what is claimed about the design, and whether the reader is
    handed the tool output they need instead of a dangling report path.
    """
    if report_written:
        return {"verdict": "FAIL", "rc": 1, "compared": True,
                "reason": ("netgen top-level LVS did not match — real compare "
                           "ran on the merged GDS; design/extraction defect")}
    return {"verdict": "FAIL", "rc": 1, "compared": False,
            "reason": (f"netgen produced NO comparison (rc={rc}): it wrote no "
                       f"report, so neither side was compared. This is a "
                       f"tool/invocation failure, NOT a design or extraction "
                       f"defect — read the transcript before attributing "
                       f"anything to the design."),
            "transcript_tail": (transcript or "")[-800:]}


def run(project: Path, top: str, container: str, pdk: str,
        *, pdk_source: str = "", top_source: str = "") -> dict:
    # C5: `top`/`pdk` may be None when the project does not state them. That is
    # reported at the tech rung of the SKIP ladder below, NOT by refusing to
    # run — M1's wiring contract requires this producer to stay dispatchable.
    ms_dir = project / "phase3" / "mixed_signal"
    rpt_dir = project / "reports" / "analog" / "mixed_signal"
    merged = ms_dir / "top_merged.gds"

    # inputs --------------------------------------------------------------
    dig_cands = (sorted((_pl.gds_dir(project)).glob("*.gds"))
                 + sorted(_pl.pnr_dir(project).glob("*.gds")))
    digital_gds = next((g for g in dig_cands if top in g.stem), None) \
        or (dig_cands[0] if dig_cands else None)
    macro_gds = sorted(
        (project / "phase3" / "analog" / "hardmacro").rglob("*.gds"))
    macro_v = sorted(
        (project / "phase3" / "analog" / "hardmacro").rglob("*.v"))
    netlist = _pl.synth_dir(project) / f"{top}_synth.v"
    if not netlist.is_file():
        nl = sorted(_pl.synth_dir(project).glob("*.v"))
        netlist = nl[0] if nl else netlist

    missing_inputs = []
    if digital_gds is None:
        missing_inputs.append("digital GDS")
    if not macro_gds:
        missing_inputs.append("hardmacro GDS (A8)")
    if not netlist.is_file():
        missing_inputs.append("gate netlist")
    if missing_inputs:
        return {"verdict": "SKIP", "rc": 2,
                "reason": "inputs missing: " + ", ".join(missing_inputs)}

    missing_tools = [t for t in ("klayout", "magic", "netgen")
                     if not _tool_ok(container, t)]
    if missing_tools:
        return {"verdict": "SKIP", "rc": 2,
                "reason": ("tools missing in container: "
                           + ", ".join(missing_tools))}
    # A tool that exists but cannot see the design is not a tool that ran.
    if not _project_reachable(container, project):
        return {"verdict": "SKIP", "rc": 2,
                "reason": (f"project dir is not reachable inside container "
                           f"'{container}': {project} — the tools would run "
                           f"against paths that do not exist there and every "
                           f"output would be a carried-forward file, not a "
                           f"result of this run")}
    # ── C5: the tech rung. An unresolved top/PDK SKIPs HERE, naming which one
    # and why — it never falls back to some other design's PDK or cell name.
    # This is the rung "PDK tech missing" already occupies, so the SKIP ladder
    # keeps its shape and the producer stays dispatchable (M1's wiring
    # contract; guarded by tests/test_m1_top_lvs_producer_wiring.py).
    if not pdk or not top:
        unresolved = []
        if not top:
            unresolved.append(f"top cell ({top_source})")
        if not pdk:
            unresolved.append(f"PDK ({pdk_source})")
        return {"verdict": "SKIP", "rc": 2,
                "reason": ("cannot identify what to extract — "
                           + "; ".join(unresolved)),
                "top": top, "top_source": top_source,
                "pdk": pdk, "pdk_source": pdk_source}
    magicrc = f"{PDKS_IN_CONTAINER}/{pdk}/libs.tech/magic/{pdk}.magicrc"
    netgen_setup = (f"{PDKS_IN_CONTAINER}/{pdk}/libs.tech/netgen/"
                    f"{pdk}_setup.tcl")
    missing_tech = [p for p in (magicrc, netgen_setup)
                    if _docker_exec(container,
                                    f"test -f {shlex.quote(p)}",
                                    timeout=10)[0] != 0]
    if missing_tech:
        return {"verdict": "SKIP", "rc": 2,
                "reason": "PDK tech missing: " + ", ".join(missing_tech)}

    ms_dir.mkdir(parents=True, exist_ok=True)
    rpt_dir.mkdir(parents=True, exist_ok=True)

    # 1) merge ------------------------------------------------------------
    # A pre-existing top_merged.gds is REUSED, not re-derived — that is
    # deliberate (the merge is expensive) but it must be SAID, because a merged
    # GDS produced by something other than this program, in another directory,
    # is exactly what two rounds of M1 were judged on.
    merge_log = ms_dir / "merge.log"
    merge_provenance = "reused: top_merged.gds already present, merge not re-run"
    if not merged.is_file():
        merge_log_before = _mtime_or_none(merge_log)
        merge_py = ms_dir / "klayout_merge.py"
        merge_py.write_text(_KLAYOUT_MERGE_PY)
        env = (f"export DIGITAL_GDS={_to_container_path(digital_gds, container)} "
               f"MACRO_GDS=\"{';'.join(_to_container_path(g, container) for g in macro_gds)}\" "
               f"MERGED_OUT={_to_container_path(merged, container)} && ")
        # C5 pipefail — see the note at the Magic site below. Without it the rc
        # this branch reports is `tee`'s, so a KLayout that died mid-merge is
        # indistinguishable from one that merged nothing.
        cmd = (env + "set -o pipefail && " + f"klayout -b -r "
               f"{_to_container_path(merge_py, container)} 2>&1 | "
               f"tee {_to_container_path(ms_dir, container)}/merge.log")
        rc, out, err = _docker_exec(
            container, cmd, marker=_to_container_path(merge_py, container))
        if not merged.is_file() or merged.stat().st_size == 0 \
                or not _ran_fresh(merge_log, "KLAYOUT_MERGE_DONE",
                                  merge_log_before):
            return {"verdict": "FAIL", "rc": 1,
                    "reason": (f"KLayout merge did not complete in THIS run "
                               f"(rc={rc}); see phase3/mixed_signal/merge.log"),
                    "transcript_tail": (out + err)[-600:]}
        merge_provenance = "produced by this invocation"

    # 2) extract ----------------------------------------------------------
    spice_out = ms_dir / f"{top}_merged_extracted.sp"
    tcl = ms_dir / "ext2spice_merged.tcl"
    tcl.write_text(_MAGIC_EXT_TCL)
    # ── C5 pipefail — MEASURED, in this container, on 2026-07-31: ───────────
    #   $ bash -lc 'bash -c "exit 137" 2>&1 | tee /tmp/x; echo $?'          -> 0
    #   $ bash -lc 'set -o pipefail; bash -c "exit 137" 2>&1 | tee /tmp/x; echo $?' -> 137
    # `<tool> 2>&1 | tee <log>` reports TEE's exit status, so a tool that was
    # KILLED comes back rc=0 and every "was it killed or did it just produce
    # nothing?" branch downstream is unreachable. This is the exact mechanism
    # that made Step 31's sibling report `produced no extracted netlist (rc=0)`
    # about a Magic run that had been killed mid-DEF-read.
    cmd = ("set -o pipefail && "
           f"export GDS={_to_container_path(merged, container)} TOP={top} "
           f"SPICE_OUT={_to_container_path(spice_out, container)} && "
           f"cd {_to_container_path(ms_dir, container)} && "
           f"magic -dnull -noconsole -rcfile {shlex.quote(magicrc)} "
           f"{_to_container_path(tcl, container)} 2>&1 | "
           f"tee {_to_container_path(ms_dir, container)}/ext2spice_merged.log")
    ext_log = ms_dir / "ext2spice_merged.log"
    ext_log_before = _mtime_or_none(ext_log)
    rc, out, err = _docker_exec(
        container, cmd, marker=_to_container_path(tcl, container))
    if not spice_out.is_file() or spice_out.stat().st_size == 0:
        return {"verdict": "FAIL", "rc": 1,
                "reason": (f"Magic ext2spice on the MERGED GDS produced no "
                           f"netlist (rc={rc})"),
                "transcript_tail": (out + err)[-600:]}
    if not _ran_fresh(ext_log, "MAGIC_EXT2SPICE_DONE", ext_log_before):
        return {"verdict": "FAIL", "rc": 1,
                "reason": (f"Magic ext2spice did not complete in THIS run "
                           f"(rc={rc}): {ext_log.name} carries no "
                           f"MAGIC_EXT2SPICE_DONE from this invocation. The "
                           f"extracted netlist on disk is a carried-forward "
                           f"file and is NOT evidence about this run"),
                "transcript_tail": (out + err)[-600:]}
    lay_top = top
    sub_txt = spice_out.read_text(errors="replace")
    if re.search(rf"^\.subckt\s+{re.escape(top)}_flat\b", sub_txt,
                 re.IGNORECASE | re.MULTILINE):
        lay_top = f"{top}_flat"

    # 3) netgen LVS — schematic side = gate netlist + hardmacro .v stubs
    #
    # netgen's `lvs` takes a TWO-element `{filename cellname}` list per side. It
    # says so in its own source: if `llength` is not 2 it falls back to treating
    # the WHOLE string as one filename. This site used to join every schematic
    # file into one space-separated string and append the top cell, handing
    # netgen four or more elements, so netgen dutifully looked for a file
    # literally named "<netlist>.v <macro1>.v <macro2>.v <top>", failed to open
    # it, and never loaded the schematic side at all.
    #
    # That made M1 unpassable for EVERY design with an analog hardmacro — the
    # only kind of design M1 exists for — because the schematic side is always
    # the gate netlist plus one `.v` per macro, i.e. always >= 2 files.
    #
    # netgen's documented way to compare against several files is to read them
    # into ONE netlist first (`readnet <format> <file> <fnum>` forces a file
    # into the netlist already held in `fnum`) and then name the CELL, which
    # `lvs` resolves through `canonical` because it has already been read:
    # "A single <filename>, or any valid_cellname form if the file has already
    # been read."
    lvs_rpt = rpt_dir / "top_lvs.rpt"
    sch_paths = [_to_container_path(f, container) for f in [netlist] + macro_v]
    lvs_tcl = ms_dir / "top_lvs.tcl"
    lvs_tcl.write_text(netgen_lvs_script(
        sch_paths, _to_container_path(spice_out, container), lay_top, top,
        netgen_setup, _to_container_path(lvs_rpt, container)))
    cmd = (f"export PATH={TOOLS_IN_CONTAINER}/netgen/bin:"
           f"{TOOLS_IN_CONTAINER}/bin:$PATH && "
           f"netgen -batch source {_to_container_path(lvs_tcl, container)}")
    lvs_rpt_before = _mtime_or_none(lvs_rpt)
    rc, out, err = _docker_exec(
        container, cmd, marker=_to_container_path(spice_out, container))
    # netgen prints no completion token of its own; the report IT writes is the
    # marker, so freshness alone carries the claim here.
    if not _ran_fresh(lvs_rpt, "", lvs_rpt_before):
        return {"verdict": "FAIL", "rc": 1, "compared": False,
                "reason": (f"netgen did not write a top-level LVS report in "
                           f"THIS run (rc={rc}): {lvs_rpt.name} was not "
                           f"(re)written by this invocation. Nothing was "
                           f"compared — this is NOT an LVS mismatch"),
                "merge_provenance": merge_provenance,
                "transcript_tail": ((out or "") + (err or ""))[-600:]}
    blob = (out or "") + "\n" + (err or "") + "\n" + (
        lvs_rpt.read_text(errors="replace") if lvs_rpt.is_file() else "")
    # #524 — shared verdict classifier (adds 'failed pin matching', the netgen
    # property-error terminal FAIL, 失配 and the Final-result truncation guard,
    # all missing from the old inline copy) so this site can never drift from
    # the Step-31 gate again.
    lvs_pass = _lvt.classify(blob) == "MATCH"

    # 4) emit M1/M4 artifacts ----------------------------------------------
    top_lvs = {
        "program": "mixed_signal_top_lvs_run", "version": "1.0.0",
        "verdict": "PASS" if lvs_pass else "FAIL",
        "layout": str(merged.relative_to(project)),
        "layout_top": lay_top,
        "schematic": [str(netlist.relative_to(project))]
                     + [str(v.relative_to(project)) for v in macro_v],
        "extracted_netlist": str(spice_out.relative_to(project)),
        "lvs_report": str(lvs_rpt.relative_to(project)),
        "tool": "magic ext2spice + netgen (PDK setup)",
        "merge_provenance": merge_provenance,
    }
    (rpt_dir / "top_lvs.json").write_text(
        json.dumps(top_lvs, indent=2) + "\n")
    (rpt_dir / "merge.json").write_text(json.dumps({
        "gate": "mixed_signal_merge",
        "verdict": "PASS" if lvs_pass else "FAIL",
        "merged_gds": str(merged.relative_to(project)),
        "macros_merged": [str(g.relative_to(project)) for g in macro_gds],
        "top_lvs": top_lvs["verdict"],
        "note": ("top-level merged-GDS LVS executed (Magic extraction + "
                 "netgen vs gate netlist + hardmacro stubs) — the merge "
                 "claim is LVS-substantiated, not presence-only"),
    }, indent=2) + "\n")

    if lvs_pass:
        return {"verdict": "PASS", "rc": 0, **top_lvs}
    return {**lvs_failure_verdict(
        report_written=lvs_rpt.is_file() and lvs_rpt.stat().st_size > 0,
        rc=rc, transcript=(out or "") + (err or "")), **top_lvs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    # C5: default None, NOT a design-specific literal. An omitted value is
    # resolved from the project; an unresolvable one SKIPs saying so.
    ap.add_argument("--top", default=None)
    ap.add_argument("--container", default="vibeic-eda")
    ap.add_argument("--pdk", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project.is_dir():
        print(f"ERROR: not a directory: {args.project}", file=sys.stderr)
        return 1
    project = args.project.resolve()
    top, top_src = resolve_top(project, args.top)
    pdk, pdk_src = resolve_pdk(project, args.pdk)
    # Degrade loudly, never silently: say WHERE these came from, so a wrong one
    # is visible in the transcript instead of surfacing 40 lines later as
    # "Magic produced no netlist".
    #
    # An UNRESOLVED top or PDK must NOT short-circuit here. `run()` owns the
    # SKIP ladder (inputs → tools → tech), and M1's wiring contract is that this
    # producer is always dispatchable and always reports its own state; a
    # pre-emptive return would make it unreachable on a fresh project and break
    # that contract (caught by tests/test_m1_top_lvs_producer_wiring.py). The
    # unresolved case is therefore reported at the tech rung inside `run()`,
    # where "PDK tech missing" already lives — see `_UNRESOLVED_PDK`.
    print(f"TOP_RESOLVED {top or '<unresolved>'} (source: {top_src})")
    print(f"PDK_RESOLVED {pdk or '<unresolved>'} (source: {pdk_src})")
    rep = run(project, top, args.container, pdk, pdk_source=pdk_src,
              top_source=top_src)
    # ── C5: a SKIP is a VERDICT and must leave verdict evidence. ────────────
    # `run()` writes reports/analog/mixed_signal/top_lvs.json only on the
    # completed-compare path, so every SKIP rung (inputs / tools / tech /
    # unresolved-top-or-PDK) previously wrote NOTHING — and M1's gate, which
    # reads that file, then cannot tell "the producer skipped, and here is why"
    # from "the producer never ran at all". Those are different claims. Writing
    # the SKIP verdict here keeps M1's evidence contract intact for every exit
    # (guarded by tests/test_m1_top_lvs_producer_wiring.py, which proves the
    # declared producer really writes its verdict evidence) WITHOUT restoring
    # any guess about which PDK or which top cell the design uses.
    if rep.get("verdict") == "SKIP":
        _ev = project / "reports" / "analog" / "mixed_signal" / "top_lvs.json"
        _ev.parent.mkdir(parents=True, exist_ok=True)
        _ev.write_text(json.dumps(
            {k: v for k, v in rep.items() if k != "rc"},
            indent=2, ensure_ascii=False) + "\n")
    rep.setdefault("top", top)
    rep.setdefault("top_source", top_src)
    rep.setdefault("pdk", pdk)
    rep.setdefault("pdk_source", pdk_src)
    rc = rep.pop("rc")
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
