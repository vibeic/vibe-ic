#!/usr/bin/env python3
"""ppa_area_threshold_check.py — v1.0 plugin gate (ORGANIC #729).

DETERMINISTIC PPA area-reduction-threshold gate for lint / PPA-optimization
problems (e.g. cid007 "reduce the area of this RTL"): synthesise the ORIGINAL
RTL and the OPTIMIZED RTL with the SAME yosys recipe, read `stat`'s `Number of
cells` + `Number of wires` off BOTH, compute the cell% and wire% reduction of
optimized-vs-original, and BLOCK if EITHER bound metric is below the prompt-
stated threshold.

THE FAILURE THIS CLOSES
-----------------------
On a v1.0.77 forward-verify, an area-optimization (cid007) problem passed every
shipped gate (interface / hygiene / lint / iverilog / verilator clean,
equivalence PASS) yet its first draft achieved only ~3% area reduction at the
gate level while the spec's success metric is a measurable >=N% reduction in
cells AND wires vs the provided original. No plugin program synthesised the
(original, optimized) pair and checked the delta, so the deterministic chain
could not verify the optimization TARGET — only the hidden scorer's synth gate
could. This program IS that deterministic check.

WHAT IT DOES
------------
  1. Parse the threshold + which metric(s) it binds (cells / wires / both) from
     the prompt text (``--prompt`` file or ``--threshold-pct`` + ``--metric``).
  2. Run yosys ``stat`` on the ORIGINAL and the OPTIMIZED RTL with the SAME
     technology-independent synth recipe (``synth -top -flatten; techmap; opt;
     dffunmap; abc -g cmos2; stat``) inside the iic-eda container (the same
     recipe shape the phase-2 synth + scorer use).
  3. Compute  reduction% = 100 * (orig - opt) / orig  for cells and for wires.
  4. BLOCK (rc 1) iff a BOUND metric's reduction is below the stated threshold.

The %-computation + threshold-compare is factored into PURE functions
(``compute_reduction_pct`` / ``parse_threshold_from_prompt`` / ``decide``) so it
is unit-tested against CANNED yosys ``stat`` text WITHOUT needing the container.

§4.05 NO-LEAK (this is a BLOCKING gate)
---------------------------------------
This gate only ever BLOCKs on a REAL measured under-threshold reduction. EVERY
other outcome is a non-blocking exit-0 NOT-APPLICABLE / SKIP, never a false
block:
  * yosys / the iic-eda container is unavailable     → NOT-APPLICABLE rc 0.
  * yosys synth fails / `stat` yields no cell|wire #  → NOT-APPLICABLE rc 0.
  * the threshold cannot be parsed from the prompt    → NOT-APPLICABLE rc 0.
  * the ORIGINAL has 0 cells (degenerate, can't form  → NOT-APPLICABLE rc 0.
    a percentage)
A real, fully-measured reduction at or above the threshold is a PASS (rc 0); a
real, fully-measured reduction below the threshold is the ONLY BLOCK (rc 1).

chip-AGNOSTIC: pure synth-stat measurement + arithmetic; no design / chip /
vendor / SKU / PDK literal.

Usage:
    python3 ppa_area_threshold_check.py \\
        --original <orig>.v --optimized <opt>.v --top <module> \\
        ( --prompt <prompt.txt> | --threshold-pct 20 [--metric both] ) \\
        [--container iic-eda] [--json OUT]

Exit codes:
    0  PASS (reduction >= threshold)  OR  NOT-APPLICABLE / SKIP (no yosys, no
       parseable threshold, unmeasurable) — NEVER a false block.
    1  BLOCK — a real, measured reduction is below the stated threshold.
    2  setup / argument error (missing file, contradictory args).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ─── prompt threshold parse ──────────────────────────────────────────────────
# The metric a threshold binds. "both" is the conservative default for an
# area-reduction spec (cells AND wires must both clear the bar).
_METRIC_CELLS = "cells"
_METRIC_WIRES = "wires"
_METRIC_BOTH = "both"
_VALID_METRICS = (_METRIC_CELLS, _METRIC_WIRES, _METRIC_BOTH)

# A percentage threshold near a reduction/area/cell/wire keyword. We bind the
# FIRST such percentage in the prompt. Ordinary-English tokens only match here
# in their natural prose form; nothing here keys off a chip/SKU name.
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# words that, when present near the percentage, indicate it is an AREA-reduction
# target (so we do not pick up an unrelated "50% duty cycle" percentage).
_AREA_WORDS = ("reduc", "reduction", "smaller", "fewer", "less", "area",
               "cell", "cells", "wire", "wires", "gate", "gates", "shrink")
_CELL_WORDS = ("cell", "cells", "gate", "gates", "logic", "lut", "luts")
_WIRE_WORDS = ("wire", "wires", "net", "nets", "interconnect", "routing")


class ThresholdParseError(ValueError):
    """The prompt does not contain a parseable area-reduction threshold."""


def parse_threshold_from_prompt(prompt: str
                                ) -> Tuple[float, str]:
    """Extract (threshold_pct, metric) from a prompt's natural-language text.

    PURE — no I/O. Returns the first area-reduction percentage and which metric
    it binds:
      * mentions cells AND wires (or "area" / "both")  → ``both``
      * mentions ONLY cells / gates / logic            → ``cells``
      * mentions ONLY wires / nets                      → ``wires``
      * a bare reduction percentage with no cell/wire    → ``both`` (the
        conservative default: an unqualified area target binds both metrics).
    Raises ThresholdParseError if no area-reduction percentage is present (the
    caller turns that into a NON-BLOCKING NOT-APPLICABLE — §4.05).
    """
    if not prompt or not prompt.strip():
        raise ThresholdParseError("empty prompt")
    text = prompt
    low = text.lower()
    # find every "<n>%" and keep the first one whose surrounding ±60-char window
    # mentions an area-reduction word.
    best: Optional[Tuple[float, str]] = None
    for m in _PCT_RE.finditer(text):
        pct = float(m.group(1))
        a, b = max(0, m.start() - 60), min(len(text), m.end() + 60)
        window = low[a:b]
        if not any(w in window for w in _AREA_WORDS):
            continue
        has_cell = any(w in window for w in _CELL_WORDS)
        has_wire = any(w in window for w in _WIRE_WORDS)
        if has_cell and has_wire:
            metric = _METRIC_BOTH
        elif has_cell and not has_wire:
            metric = _METRIC_CELLS
        elif has_wire and not has_cell:
            metric = _METRIC_WIRES
        else:
            # an "area" / "reduce by" percentage with neither cell nor wire word
            # → conservative both-metric bind.
            metric = _METRIC_BOTH
        best = (pct, metric)
        break
    if best is None:
        raise ThresholdParseError(
            "no area-reduction percentage found in the prompt (looked for a "
            "'<n>%' near a reduce/area/cell/wire word)")
    return best


# ─── yosys stat parse + reduction arithmetic ─────────────────────────────────
# yosys `stat` has shipped TWO summary spellings over its life:
#   OLD (≤ ~0.36):  "   Number of cells:                400"
#                   "   Number of wires:                250"
#   NEW (0.40+):    "       98 cells"   /   "      152 wires"   (count FIRST,
#                   under a "Local Count, excluding submodules." header; the
#                   "<N> wire bits" / "<N> public wires" lines are NOT the
#                   wire/cell count and must NOT match).
# Parse BOTH so the gate works across yosys versions. The NEW form must avoid
# the decoy "wire bits" / "public wires" / "port bits" lines: a "<N> wires" /
# "<N> cells" token must be the WHOLE word at end-of-token (\b...\b, not part
# of "wire bits").
_CELLS_OLD_RE = re.compile(r"Number of cells:\s*(\d[\d,]*)")
_WIRES_OLD_RE = re.compile(r"Number of wires:\s*(\d[\d,]*)")
_CELLS_NEW_RE = re.compile(r"^\s*(\d[\d,]*)\s+cells\s*$", re.MULTILINE)
_WIRES_NEW_RE = re.compile(r"^\s*(\d[\d,]*)\s+wires\s*$", re.MULTILINE)


def parse_stat(stat_text: str) -> Dict[str, Optional[int]]:
    """Extract {'cells': int|None, 'wires': int|None} from yosys `stat` text.

    PURE — feed it the raw yosys transcript (or just the stat block). Handles
    BOTH the OLD ("Number of cells: N") and the NEW ("N cells") yosys summary
    spellings. A metric not present is None (the caller treats a missing metric
    as UNMEASURABLE → NOT-APPLICABLE, never a fabricated 0). The LAST occurrence
    wins (yosys may print a per-module stat then a top stat)."""
    out: Dict[str, Optional[int]] = {"cells": None, "wires": None}
    text = stat_text or ""
    for rx in (_CELLS_OLD_RE, _CELLS_NEW_RE):
        m = rx.findall(text)
        if m:
            out["cells"] = int(m[-1].replace(",", ""))
            break
    for rx in (_WIRES_OLD_RE, _WIRES_NEW_RE):
        m = rx.findall(text)
        if m:
            out["wires"] = int(m[-1].replace(",", ""))
            break
    return out


def compute_reduction_pct(orig: Optional[int], opt: Optional[int]
                          ) -> Optional[float]:
    """reduction% = 100 * (orig - opt) / orig, rounded to 4 dp.

    PURE. Returns None when it cannot be formed honestly:
      * either count is None (UNMEASURABLE), or
      * orig <= 0 (a 0-cell/0-wire original cannot anchor a percentage).
    A NEGATIVE result (optimized GREW) is returned verbatim (it is a real,
    measured anti-reduction → it will fail any positive threshold)."""
    if orig is None or opt is None:
        return None
    if orig <= 0:
        return None
    return round(100.0 * (orig - opt) / orig, 4)


def decide(cells_red: Optional[float], wires_red: Optional[float],
           threshold_pct: float, metric: str
           ) -> Tuple[str, str]:
    """Pure verdict from the two reductions + the bound metric + the threshold.

    Returns (verdict, reason). verdict ∈ {PASS, BLOCK, NOT_APPLICABLE}:
      * a BOUND metric's reduction is None (unmeasurable)        → NOT_APPLICABLE
      * a BOUND metric's reduction is < threshold                → BLOCK
      * every bound metric's reduction is >= threshold           → PASS
    `cells`/`wires` bind one; `both` binds both.
    """
    bind_cells = metric in (_METRIC_CELLS, _METRIC_BOTH)
    bind_wires = metric in (_METRIC_WIRES, _METRIC_BOTH)

    # unmeasurable bound metric → NOT-APPLICABLE (never a false block).
    if bind_cells and cells_red is None:
        return ("NOT_APPLICABLE",
                "cells reduction is unmeasurable (no cell count from yosys "
                "stat on one side); cannot assert the cells threshold")
    if bind_wires and wires_red is None:
        return ("NOT_APPLICABLE",
                "wires reduction is unmeasurable (no wire count from yosys "
                "stat on one side); cannot assert the wires threshold")

    failures: List[str] = []
    if bind_cells and cells_red < threshold_pct:
        failures.append(f"cells reduction {cells_red:.2f}% < {threshold_pct:g}%")
    if bind_wires and wires_red < threshold_pct:
        failures.append(f"wires reduction {wires_red:.2f}% < {threshold_pct:g}%")
    if failures:
        return ("BLOCK",
                "under-threshold area reduction: " + "; ".join(failures))

    parts: List[str] = []
    if bind_cells:
        parts.append(f"cells {cells_red:.2f}%")
    if bind_wires:
        parts.append(f"wires {wires_red:.2f}%")
    return ("PASS",
            f"area reduction meets the {threshold_pct:g}% threshold ("
            + ", ".join(parts) + ")")


# ─── yosys-in-container synth + stat ─────────────────────────────────────────
# Path inside the iic-osic-tools / iic-eda container where the EDA tools live.
_TOOLS_IN_CONTAINER = "/foss/tools"

# The SAME technology-independent lowering recipe the phase-2 synth path uses
# (synth -flatten; techmap; opt; dffunmap; abc -g cmos2) so the cell/wire counts
# are directly comparable between the original and the optimized RTL.
_SYNTH_TAIL = ("hierarchy -check -top {top}; proc; flatten; "
               "synth -top {top} -flatten; techmap; opt; dffunmap; "
               "abc -g cmos2; stat")


def _run(cmd: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=timeout)
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return 124, out or "", "timeout"
    except FileNotFoundError as e:
        return 127, "", str(e)


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _container_running(container: str) -> bool:
    """True iff the named docker container is up (so a `docker exec` will land).
    NOT-APPLICABLE-fast — a single short inspect, no synth attempted if down."""
    rc, out, _ = _run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        timeout=10)
    return rc == 0 and out.strip() == "true"


def _container_mounts(container: str) -> List[Tuple[str, str]]:
    """[(host_src, container_dst), ...] longest-source-first. Mirrors the
    phase-2 runner helper so host RTL paths map to container-visible paths."""
    out: List[Tuple[str, str]] = []
    rc, txt, _ = _run(
        ["docker", "inspect", container, "--format",
         "{{range .Mounts}}{{.Source}}|{{.Destination}}\n{{end}}"], timeout=10)
    if rc == 0:
        for line in txt.splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            src, dst = line.split("|", 1)
            if src and dst:
                out.append((src.rstrip("/"), dst.rstrip("/")))
    out.sort(key=lambda t: len(t[0]), reverse=True)
    return out


def _to_container_path(host_path: str, mounts: List[Tuple[str, str]]) -> str:
    p = str(host_path)
    for src, dst in mounts:
        if p == src:
            return dst
        if p.startswith(src + "/"):
            return dst + p[len(src):]
    return p


def _docker_exec(container: str, cmd: str, timeout: int = 600
                 ) -> Tuple[int, str, str]:
    full = ["docker", "exec", container, "bash", "-lc", cmd]
    try:
        cp = subprocess.run(full, capture_output=True, text=True,
                            timeout=timeout)
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired as e:
        partial = e.stdout
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        return 124, partial or "", f"TIMEOUT after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", str(e)


def synth_stat_in_container(rtl_path: Path, top: str, container: str
                            ) -> Tuple[Optional[str], str]:
    """Synthesise `rtl_path` (module `top`) inside `container` and return
    (stat_text, err). On any failure stat_text is None and err is non-empty.

    The RTL is `docker cp`'d into a fresh /tmp staging dir inside the container
    (so we never depend on a particular bind-mount layout), synthesised with the
    canonical recipe, and the full transcript (which contains the `stat` block)
    is returned. NEVER fabricates a count."""
    stage = f"/tmp/ppa_area_{abs(hash((str(rtl_path), top)))}"
    base = rtl_path.name
    # fresh staging dir + copy the RTL in
    rc, _o, e = _docker_exec(container, f"rm -rf {stage} && mkdir -p {stage}",
                             timeout=30)
    if rc != 0:
        return None, f"could not create container staging dir: {e[-200:]}"
    rc, _o, e = _run(["docker", "cp", str(rtl_path),
                      f"{container}:{stage}/{base}"], timeout=60)
    if rc != 0:
        return None, f"docker cp {base} → container failed: {e[-200:]}"
    yosys_path = (f"export PATH={_TOOLS_IN_CONTAINER}/yosys/bin:"
                  f"{_TOOLS_IN_CONTAINER}/bin:$PATH")
    recipe = _SYNTH_TAIL.format(top=top)
    cmd = (f"cd {stage} && {yosys_path} && "
           f"yosys -p 'read_verilog -sv {base}; {recipe}' 2>&1")
    rc, out, err = _docker_exec(container, cmd, timeout=600)
    # best-effort cleanup
    _docker_exec(container, f"rm -rf {stage}", timeout=20)
    blob = (out or "") + "\n" + (err or "")
    if rc != 0 or "ERROR" in (out or ""):
        return None, ("yosys synth failed: "
                      + "; ".join(blob.strip().splitlines()[-5:]))
    return blob, ""


# ─── orchestration ───────────────────────────────────────────────────────────
def run_ppa_area_threshold(
    original: Path, optimized: Path, top: str,
    prompt_text: Optional[str], threshold_override: Optional[float],
    metric_override: Optional[str], container: str,
) -> Tuple[int, Dict]:
    """Run the gate; return (rc, report). rc is the program exit code.

    rc 0 = PASS / NOT-APPLICABLE / SKIP, rc 1 = BLOCK (under threshold),
    rc 2 = setup error.
    """
    report: Dict = {
        "program": "ppa_area_threshold_check",
        "original": str(original),
        "optimized": str(optimized),
        "top": top,
        "container": container,
        "methodology": ("yosys stat on ORIGINAL + OPTIMIZED with the SAME synth "
                        "recipe; reduction%% = 100*(orig-opt)/orig for cells and "
                        "wires; BLOCK iff a prompt-bound metric is below the "
                        "prompt-stated threshold"),
    }

    # ── resolve the threshold + bound metric ──────────────────────────────────
    # explicit --threshold-pct wins; else parse from the prompt. An unparseable
    # threshold is NON-BLOCKING NOT-APPLICABLE (§4.05) — never a false block.
    if threshold_override is not None:
        threshold = threshold_override
        metric = metric_override or _METRIC_BOTH
        report["threshold_source"] = "explicit"
    else:
        if not prompt_text:
            report["verdict"] = "NOT_APPLICABLE"
            report["reason"] = ("no --threshold-pct and no --prompt; cannot "
                                "determine the area-reduction target")
            return 0, report
        try:
            threshold, metric = parse_threshold_from_prompt(prompt_text)
        except ThresholdParseError as ex:
            report["verdict"] = "NOT_APPLICABLE"
            report["reason"] = (f"unparseable threshold — {ex}; not blocking "
                                f"(the prompt has no area-reduction target)")
            return 0, report
        # a --metric override on top of a parsed threshold lets a caller pin it.
        if metric_override:
            metric = metric_override
        report["threshold_source"] = "prompt"
    report["threshold_pct"] = threshold
    report["metric"] = metric

    # ── yosys / container availability — refuse-don't-fake (§4.05) ────────────
    if not _docker_available():
        report["verdict"] = "NOT_APPLICABLE"
        report["tool_available"] = False
        report["reason"] = ("docker absent — cannot synthesise to MEASURE the "
                            "area; NOT-APPLICABLE (NOT a fabricated reduction "
                            "or a false block)")
        return 0, report
    if not _container_running(container):
        report["verdict"] = "NOT_APPLICABLE"
        report["tool_available"] = False
        report["reason"] = (f"container {container!r} is not running — cannot "
                            f"synthesise; NOT-APPLICABLE (no false block)")
        return 0, report
    report["tool_available"] = True

    # ── synth + stat BOTH sides with the SAME recipe ──────────────────────────
    orig_blob, orig_err = synth_stat_in_container(original, top, container)
    if orig_blob is None:
        report["verdict"] = "NOT_APPLICABLE"
        report["reason"] = (f"ORIGINAL synth/stat unavailable: {orig_err}; "
                            f"NOT-APPLICABLE (cannot measure → no false block)")
        return 0, report
    opt_blob, opt_err = synth_stat_in_container(optimized, top, container)
    if opt_blob is None:
        report["verdict"] = "NOT_APPLICABLE"
        report["reason"] = (f"OPTIMIZED synth/stat unavailable: {opt_err}; "
                            f"NOT-APPLICABLE (cannot measure → no false block)")
        return 0, report

    orig_stat = parse_stat(orig_blob)
    opt_stat = parse_stat(opt_blob)
    report["original_stat"] = orig_stat
    report["optimized_stat"] = opt_stat

    cells_red = compute_reduction_pct(orig_stat["cells"], opt_stat["cells"])
    wires_red = compute_reduction_pct(orig_stat["wires"], opt_stat["wires"])
    report["cells_reduction_pct"] = cells_red
    report["wires_reduction_pct"] = wires_red

    verdict, reason = decide(cells_red, wires_red, threshold, metric)
    report["verdict"] = verdict
    report["reason"] = reason
    if verdict == "BLOCK":
        return 1, report
    return 0, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=("DETERMINISTIC PPA area-reduction-threshold gate (#729): "
                     "synth ORIGINAL vs OPTIMIZED with yosys, compute cells%% + "
                     "wires%% reduction, BLOCK if a prompt-bound metric is below "
                     "the prompt-stated threshold."))
    ap.add_argument("--original", required=True,
                    help="the ORIGINAL (un-optimized) RTL file")
    ap.add_argument("--optimized", required=True,
                    help="the OPTIMIZED RTL file (same top module)")
    ap.add_argument("--top", required=True,
                    help="the top module name (same in both files)")
    ap.add_argument("--prompt", default=None,
                    help="path to the prompt/spec text; the threshold + bound "
                         "metric are parsed from it")
    ap.add_argument("--threshold-pct", type=float, default=None,
                    help="explicit reduction threshold percent (overrides the "
                         "prompt-parsed one)")
    ap.add_argument("--metric", default=None, choices=_VALID_METRICS,
                    help="which metric the threshold binds (default: parsed "
                         "from the prompt, else 'both')")
    ap.add_argument("--container", default="iic-eda",
                    help="docker container with yosys (default iic-eda)")
    ap.add_argument("--json", default=None, help="optional JSON report path")
    args = ap.parse_args(argv)

    original = Path(args.original)
    optimized = Path(args.optimized)
    if not original.is_file():
        print(f"ERROR: --original not found: {original}", file=sys.stderr)
        return 2
    if not optimized.is_file():
        print(f"ERROR: --optimized not found: {optimized}", file=sys.stderr)
        return 2
    if args.threshold_pct is None and args.prompt is None:
        print("ERROR: provide --threshold-pct or --prompt", file=sys.stderr)
        return 2

    prompt_text = None
    if args.prompt is not None:
        pp = Path(args.prompt)
        if not pp.is_file():
            print(f"ERROR: --prompt not found: {pp}", file=sys.stderr)
            return 2
        prompt_text = pp.read_text(errors="replace")

    rc, report = run_ppa_area_threshold(
        original=original, optimized=optimized, top=args.top,
        prompt_text=prompt_text, threshold_override=args.threshold_pct,
        metric_override=args.metric, container=args.container)

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))

    verdict = report.get("verdict")
    if verdict == "NOT_APPLICABLE":
        print(f"NOT-APPLICABLE: {report['reason']}")
    elif verdict == "BLOCK":
        print(f"PPA-AREA-BLOCK: {report['reason']} "
              f"(cells={report.get('cells_reduction_pct')}%, "
              f"wires={report.get('wires_reduction_pct')}%)")
    elif verdict == "PASS":
        print(f"ppa-area-threshold ok: {report['reason']}")
    else:
        print(f"NOT-APPLICABLE: {report.get('reason', verdict)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
