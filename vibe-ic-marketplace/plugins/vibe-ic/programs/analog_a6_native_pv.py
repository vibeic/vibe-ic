#!/usr/bin/env python3
"""analog_a6_native_pv.py — A6 per-block PHYSICAL-VERIFICATION producer
(consume the resolver's staged sign-off decks; run native DRC + LVS).

The A6 gate (analog_a6_block_pv_check) is a CONSUMER: it reads a block's
`drc.report` / `comp.json` and passes iff DRC violations == 0 AND LVS == match.
Until v1.4.27 nothing PRODUCED that evidence except a deterministic stub. This
module wires the PRODUCER side so that, when the v1.4.24 native PDK resolver
resolves the project's STAGED sign-off decks (rung 1 custom PDK / rung 2
installed), A6 actually EXECUTES:

  * DRC — the PROVEN native `svrfdrc` buddy (the same NATIVE C++ engine that ran
          spm's 4533-rule chip-level Calibre `.rule` sign-off, baked into
          vibeic-eda) on the BLOCK GDS with the STAGED SVRF DRC deck.
  * LVS — the PROVEN `klayout_pdk_lvs.py` device-level compare (spm MATCH
          methodology: bulk-normalize + pin-fix), the BLOCK source SPICE netlist
          vs the transistors extracted from the BLOCK GDS.

Both fire ONLY when the resolver hands over the decks / the block GDS is present;
otherwise the caller's existing waiver / deferred / stub path stands. A violating
block FAILS A6 honestly (no false-clean). Reports NUMBERS ONLY (NDA hygiene) —
never rule names / geometry / netlist content, never real foundry deck content.

The two engines are INJECTABLE (`drc_runner` / `lvs_runner`) so the producer →
gate wiring + honest FAIL propagation is tested deterministically without a
container; the defaults invoke the real in-container engines.

chip-AGNOSTIC: no chip / vendor / SKU literal; discovers engines on PATH.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

PROGRAMS_DIR = Path(__file__).resolve().parent
_SVRFDRC_BIN = "svrfdrc"


# ── block-dir / artefact discovery ──────────────────────────────────────────

def block_dir(project: Path, block: str) -> Optional[Path]:
    for cand in (project / "phase3" / "analog" / block,
                 project / "analog" / block):
        if cand.is_dir():
            return cand
    return None


def _find_gds(bdir: Path, block: str) -> Optional[Path]:
    for pat in (f"{block}.gds", "layout.gds", f"{block}.gds.gz", "*.gds"):
        hits = sorted(bdir.glob(pat))
        if hits:
            return hits[0]
    return None


def _find_source_netlist(bdir: Path, block: str) -> Optional[Path]:
    for pat in (f"{block}.sp", f"{block}.spice", f"{block}.cir",
                "*.sp", "*.spice"):
        hits = sorted(bdir.glob(pat))
        if hits:
            return hits[0]
    return None


# ── minimal container helpers (self-contained; real-run only) ───────────────

def _docker_exec(container: str, cmd: str, timeout: int = 600
                 ) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(["docker", "exec", container, "bash", "-lc", cmd],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or "", r.stderr or ""
    except Exception as exc:                        # noqa: BLE001
        return 127, "", str(exc)


def _to_container_path(container: str, host_path: str) -> str:
    """Best-effort host→container mapping: verbatim when the bind-mount
    preserves the absolute path (modern `-v $PWD:$PWD` workflow), else the
    legacy `/foss/designs/` scheme. Verbatim is the common case for vibeic-eda."""
    p = str(Path(host_path).resolve())
    rc, _out, _err = _docker_exec(container, f"test -e {shlex.quote(p)}", 30)
    if rc == 0:
        return p
    # fall back to the legacy designs mount using the tail path component
    return p  # verbatim is the vibeic-eda convention; keep the absolute path


def _tool_on_path(container: str, tool: str) -> Optional[str]:
    """The tool's absolute path inside the container, or None.

    THE LAST LINE, not the whole stdout. The pinned EDA image's entrypoint
    prints two `[INFO] Final PATH variable: ...` banner lines to STDOUT before
    the command's own output, so `command -v klayout` comes back as a
    three-line blob. Returning that blob passed `is not None`, so every caller
    believed the tool was present, and then ran it shell-quoted as ONE
    argument: `rc=127`, no report, and A6 reported "no parseable DRC result".
    Measured on the pinned image for BOTH engines (`svrfdrc` and `klayout`),
    which is why the native per-block DRC path had never produced evidence
    there. A path never contains a newline, so the last non-empty line is the
    answer and the banner is discarded.
    """
    binname = os.environ.get("VIBE_IC_SVRFDRC_BIN", tool) \
        if tool == _SVRFDRC_BIN else tool
    rc, out, _err = _docker_exec(container, f"command -v {shlex.quote(binname)}",
                                 30)
    if rc != 0:
        return None
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    return (lines[-1] if lines else binname)


def _parse_svrf_tally(text: str) -> Tuple[int, int, int]:
    """Parse a svrfdrc report → (fails, passes, skips). Per-rule result lines
    (`FAIL …` / `PASS …` / `SKIP …`); `#` header/tally lines ignored. Counts
    ONLY (no rule names surfaced — NDA hygiene)."""
    fails = passes = skips = 0
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        v = s.split()[0]
        if v == "FAIL":
            fails += 1
        elif v == "PASS":
            passes += 1
        elif v == "SKIP":
            skips += 1
    return fails, passes, skips


# ── deck KIND, and why this dispatch exists ─────────────────────────────────
#
# THE DEFECT THIS CLOSES, MEASURED. The resolver's `drc_deck` axis globs
# `input/pdk/klayout/*.drc` — correctly, because a KLayout DRC runset is what an
# OPEN PDK actually ships. The only DRC ENGINE wired here was `svrfdrc`, which
# reads SVRF (`.rule`). Handed an open PDK's KLayout-DSL runset it does not
# crash: it derives the layers, finds **0 rules**, and writes a report whose
# tally is empty. A6 then reports `A6_PV_DRC_NO_EVIDENCE` — correctly refusing
# it, and fail-closed, so nothing was ever falsely certified clean. But the
# design's own staged deck had been resolved and handed over, and the block
# never got a DRC run at all.
#
# Measured on one block, same GDS, same container: `svrfdrc` on the open PDK's
# runset -> "0 layers, 122 derivations, 0 rules", empty tally, A6 NO_EVIDENCE;
# the same runset under `klayout -b -r` -> 4 real violations in 5 s.
#
# So the fix is not a new capability and not a new tool — both engines were
# already on PATH in the pinned image. It is a DISPATCH: run the deck with the
# engine that can read it.
_SVRF_DECK_SUFFIXES = (".rule", ".svrf")
_KLAYOUT_DECK_SUFFIXES = (".drc", ".lydrc")


def deck_kind(deck: str) -> str:
    """`svrf` | `klayout` | `unknown` — from the deck's own extension.

    Extension, not content sniffing: the resolver's axes are themselves
    extension-keyed (`calibre/*DRC*.rule` vs `klayout/*.drc`), so keying the
    engine the same way keeps ONE definition of what a deck is. `unknown`
    is reported and refused rather than guessed at, because running a deck
    under the wrong engine is exactly the silent-zero this fixes.
    """
    suf = Path(str(deck or "")).suffix.lower()
    if suf in _SVRF_DECK_SUFFIXES:
        return "svrf"
    if suf in _KLAYOUT_DECK_SUFFIXES:
        return "klayout"
    return "unknown"


def _count_lyrdb_items(text: str) -> int:
    """Violations in a KLayout RDB report. `<item>` elements are the
    violations; the categories they name are NOT surfaced (NDA hygiene —
    NUMBERS ONLY, same contract as the SVRF tally)."""
    return len(re.findall(r"<item>", text or ""))


def _klayout_drc_runner(deck: str, gds: str, block: str, container: str,
                        report_host: Path) -> Tuple[Optional[int], Dict[str, Any]]:
    """Run an open-PDK KLayout DRC runset on the block GDS.

    `klayout -b -r <deck> -rd input=<gds> -rd report=<rdb> -rd topcell=<block>`
    is the runset convention those decks declare (`$input` / `$report` /
    `$topcell`). Returns (violations, meta); None when the engine or the report
    is missing, so the caller keeps its existing waiver path rather than
    inventing a verdict.
    """
    binc = _tool_on_path(container, "klayout")
    if binc is None:
        return None, {"reason": "klayout engine not on container PATH"}
    deck_c = _to_container_path(container, deck)
    gds_c = _to_container_path(container, gds)
    rpt_c = _to_container_path(container, str(report_host))
    cmd = (f"{shlex.quote(binc)} -b -r {shlex.quote(deck_c)} "
           f"-rd input={shlex.quote(gds_c)} "
           f"-rd report={shlex.quote(rpt_c)} "
           f"-rd topcell={shlex.quote(block)}")
    rc, out, err = _docker_exec(container, cmd)
    if not report_host.is_file():
        return None, {"reason": f"klayout produced no report (rc={rc})",
                      "tail": (out + err)[-300:]}
    text = report_host.read_text(errors="replace")
    return _count_lyrdb_items(text), {"method": "klayout_runset", "rc": rc}


# ── default (real, in-container) engine runners ─────────────────────────────

def _default_drc_runner(deck: str, gds: str, block: str, container: str,
                        report_host: Path) -> Tuple[Optional[int], Dict[str, Any]]:
    """Run the block GDS against the staged DRC deck, under the engine that
    deck's own format requires.

    An SVRF (`.rule`) deck goes to the native `svrfdrc` buddy exactly as
    before; a KLayout (`.drc`) runset goes to `klayout -b -r`. A deck of
    neither kind is REFUSED by name rather than handed to whichever engine
    happens to be first — see `deck_kind`. Returns (violations, meta);
    violations is None when the engine / report is unavailable (caller then
    leaves the existing waiver/stub path). NUMBERS ONLY."""
    kind = deck_kind(deck)
    if kind == "klayout":
        return _klayout_drc_runner(deck, gds, block, container, report_host)
    if kind == "unknown":
        return None, {"reason": (
            "staged DRC deck is neither an SVRF (.rule/.svrf) nor a KLayout "
            "(.drc/.lydrc) deck; refusing to guess an engine, because running "
            "a deck under the wrong one yields a rule-less report rather than "
            "an error"),
            "deck_suffix": Path(str(deck)).suffix}
    binc = _tool_on_path(container, _SVRFDRC_BIN)
    if binc is None:
        return None, {"reason": "svrfdrc engine not on container PATH"}
    deck_c = _to_container_path(container, deck)
    gds_c = _to_container_path(container, gds)
    rpt_c = _to_container_path(container, str(report_host))
    cmd = f"{shlex.quote(binc)} {shlex.quote(deck_c)} {shlex.quote(gds_c)} " \
          f"{shlex.quote(rpt_c)} --cell={shlex.quote(block)}"
    rc, out, err = _docker_exec(container, cmd)
    if not report_host.is_file():
        return None, {"reason": f"svrfdrc produced no report (rc={rc})",
                      "tail": (out + err)[-300:]}
    fails, passes, skips = _parse_svrf_tally(report_host.read_text(errors="replace"))
    if fails + passes + skips == 0:
        # A REPORT THAT GRADED NOTHING IS NOT A CLEAN REPORT. `0 FAIL` out of
        # `0 rules` is indistinguishable, by count alone, from a block that
        # passed every rule — and it is the shape a deck the engine could not
        # read produces. Measured: handed an open PDK's KLayout runset,
        # `svrfdrc` writes a well-formed report saying "0 rules" with an empty
        # tally; crediting that as 0 violations certified a block that a real
        # run of the same deck found 4 violations in. Return no-evidence so the
        # caller keeps its waiver path instead of publishing a false clean.
        return None, {"reason": ("DRC report graded 0 rules — the deck "
                                 "produced no rule results, so this is an "
                                 "unread deck, not a clean block"),
                      "method": "svrf_native", "rc": rc}
    return fails, {"method": "svrf_native", "rules_pass": passes,
                   "rules_skip": skips, "rc": rc}


def _default_lvs_runner(gds: str, netlist: str, block: str, container: str,
                        ext_dir: Path, layermap: Optional[str] = None
                        ) -> Tuple[Optional[str], Dict[str, Any]]:
    """Device-level LVS via klayout_pdk_lvs.py: extract the block GDS to a
    transistor SPICE netlist, then NetlistComparer-compare it against the block
    source netlist (bulk-normalize + pin-fix). Returns (verdict, meta). verdict
    is None when klayout is unavailable. NUMBERS ONLY (device counts, no netlist
    content)."""
    if _tool_on_path(container, "klayout") is None:
        return None, {"reason": "klayout not on container PATH"}
    klvs = PROGRAMS_DIR / "klayout_pdk_lvs.py"
    if not klvs.is_file():
        return None, {"reason": "klayout_pdk_lvs.py not shipped"}
    ext_dir.mkdir(parents=True, exist_ok=True)
    layout_sp = ext_dir / f"{block}_layout.spice"
    cmp_json = ext_dir / f"{block}_compare.json"
    klvs_c = _to_container_path(container, str(klvs))
    gds_c = _to_container_path(container, gds)
    layout_c = _to_container_path(container, str(layout_sp))
    src_c = _to_container_path(container, netlist)
    cmp_c = _to_container_path(container, str(cmp_json))
    threads = os.cpu_count() or 8
    lm = f" --layermap {_to_container_path(container, layermap)}" if layermap else ""
    base = "export QT_QPA_PLATFORM=offscreen && "
    power = os.environ.get("VIBE_IC_ANALOG_LVS_POWER", "VDD")
    ground = os.environ.get("VIBE_IC_ANALOG_LVS_GROUND", "VSS")
    _rc_e, _out_e, _err_e = _docker_exec(
        container, base + f"python3 {shlex.quote(klvs_c)} extract "
        f"{shlex.quote(gds_c)} --out {shlex.quote(layout_c)} "
        f"--threads {threads}{lm}")
    if not layout_sp.is_file() or layout_sp.stat().st_size == 0:
        return None, {"reason": f"klayout extraction produced no netlist "
                                f"(rc={_rc_e})", "tail": (_out_e + _err_e)[-300:]}
    rc_c, out_c, err_c = _docker_exec(
        container, base + f"python3 {shlex.quote(klvs_c)} compare "
        f"{shlex.quote(layout_c)} --source {shlex.quote(src_c)} "
        f"--top {shlex.quote(block)} --power {shlex.quote(power)} "
        f"--ground {shlex.quote(ground)} --out {shlex.quote(cmp_c)}")
    m = re.search(r"LVS_COMPARE\s+(\{.*\})", out_c or "")
    if not m:
        return None, {"reason": f"klayout compare produced no verdict "
                                f"(rc={rc_c})", "tail": (out_c + err_c)[-300:]}
    try:
        cd = json.loads(m.group(1))
    except ValueError:
        return None, {"reason": "klayout compare verdict not JSON"}
    verdict = cd.get("verdict")
    return verdict, {"method": "klayout_pdk_lvs",
                     "layout_devices": cd.get("layout", {}).get("devices"),
                     "source_devices": cd.get("source", {}).get("devices")}


# ── the producer ────────────────────────────────────────────────────────────

def _write_drc_report(bdir: Path, block: str, violations: int,
                      meta: Dict[str, Any]) -> Path:
    """Write the block `drc.report` the A6 gate consumes. NUMBERS ONLY — the
    violation count + pass/skip tallies, never rule names / geometry."""
    rpt = bdir / "drc.report"
    verdict = "PASS" if violations == 0 else "FAIL"
    lines = [
        f"# {block} per-block DRC — native svrfdrc (staged foundry .rule deck)",
        f"# method: {meta.get('method', 'svrf_native')} "
        f"(numbers only — NDA hygiene; no rule names / geometry)",
        f"rules_pass: {meta.get('rules_pass', 0)}",
        f"rules_skip: {meta.get('rules_skip', 0)}",
        f"violations: {violations}",
        f"result: {verdict}",
        "",
    ]
    rpt.write_text("\n".join(lines))
    return rpt


def _write_lvs_report(bdir: Path, block: str, verdict: str,
                      meta: Dict[str, Any]) -> Path:
    """Write the block `comp.json` the A6 gate consumes (result: match|mismatch).
    NUMBERS ONLY — device counts, never netlist content."""
    matched = str(verdict).upper() == "MATCH"
    comp = bdir / "comp.json"
    comp.write_text(json.dumps({
        "block": block,
        "result": "match" if matched else "mismatch",
        "method": meta.get("method", "klayout_pdk_lvs"),
        "layout_devices": meta.get("layout_devices"),
        "source_devices": meta.get("source_devices"),
        "note": ("device-level LVS (bulk-normalize + pin-fix); numbers only — "
                 "NDA hygiene, no netlist content"),
    }, indent=2) + "\n")
    return comp


def run_block_pv(project: Path, block: str, res: Dict[str, Any],
                 container: str = "vibeic-eda", *,
                 drc_runner: Optional[Callable] = None,
                 lvs_runner: Optional[Callable] = None,
                 gds_finder: Optional[Callable] = None,
                 netlist_finder: Optional[Callable] = None,
                 layermap: Optional[str] = None) -> Dict[str, Any]:
    """Produce REAL per-block DRC + LVS evidence when the resolver resolves the
    staged sign-off decks (rung 1/2). Writes `drc.report` + `comp.json` into the
    block dir (the A6 gate then verdicts on them). Returns a status dict:

        {"ran": bool, "reason": str,
         "drc": {"executed", "violations", "verdict", "report"} | None,
         "lvs": {"executed", "verdict", "report"} | None}

    Only fires the DRC path when `res['drc_deck']` is resolved AND a block GDS is
    present; only the LVS path when the decks are resolved (`lvs_deck` present)
    AND both a block GDS and a block source netlist are present. Otherwise leaves
    the caller's existing waiver / stub path untouched. NUMBERS ONLY."""
    project = Path(project)
    bdir = block_dir(project, block)
    if bdir is None:
        return {"ran": False, "reason": f"no block dir for {block}",
                "drc": None, "lvs": None}
    res = res or {}
    gds_finder = gds_finder or (lambda b, blk: _find_gds(b, blk))
    netlist_finder = netlist_finder or (lambda b, blk: _find_source_netlist(b, blk))
    gds = gds_finder(bdir, block)
    netlist = netlist_finder(bdir, block)

    drc_result: Optional[Dict[str, Any]] = None
    lvs_result: Optional[Dict[str, Any]] = None
    ran = False
    reasons: List[str] = []

    # ── DRC: staged SVRF deck + block GDS → native svrfdrc ──
    drc_deck = res.get("drc_deck")
    if not drc_deck:
        reasons.append("no staged DRC deck resolved")
    elif gds is None:
        reasons.append("no block GDS for DRC")
    else:
        runner = drc_runner or (
            lambda deck, g, blk, ctn: _default_drc_runner(
                deck, g, blk, ctn, bdir / "drc.report"))
        violations, meta = runner(str(drc_deck), str(gds), block, container)
        if violations is None:
            reasons.append(f"DRC engine unavailable: {meta.get('reason', '?')}")
        else:
            _write_drc_report(bdir, block, int(violations), meta or {})
            ran = True
            drc_result = {"executed": True, "violations": int(violations),
                          "verdict": "PASS" if violations == 0 else "FAIL",
                          "report": str((bdir / "drc.report").relative_to(project))}

    # ── LVS: block source netlist vs block GDS → klayout_pdk_lvs compare ──
    lvs_deck = res.get("lvs_deck")
    if not lvs_deck:
        reasons.append("no staged LVS deck resolved")
    elif gds is None:
        reasons.append("no block GDS for LVS")
    elif netlist is None:
        reasons.append("no block source netlist for LVS")
    else:
        runner = lvs_runner or (
            lambda g, nl, blk, ctn: _default_lvs_runner(
                g, nl, blk, ctn, project / "phase3" / "extracted" / "analog" / blk,
                layermap))
        verdict, meta = runner(str(gds), str(netlist), block, container)
        if verdict is None:
            reasons.append(f"LVS engine unavailable: {meta.get('reason', '?')}")
        else:
            _write_lvs_report(bdir, block, str(verdict), meta or {})
            ran = True
            matched = str(verdict).upper() == "MATCH"
            lvs_result = {"executed": True,
                          "verdict": "match" if matched else "mismatch",
                          "report": str((bdir / "comp.json").relative_to(project))}

    return {"ran": ran,
            "reason": ("; ".join(reasons) if not ran
                       else "native per-block PV executed"),
            "drc": drc_result, "lvs": lvs_result}
