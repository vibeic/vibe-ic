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
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _container_exec as _ce  # noqa: E402 — the ONE guarded docker-exec argv
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated
import _a6_drc_authority as _auth  # noqa: E402 — q1: whose word stands
import _atomic_artefact as _aa  # noqa: E402 — publish complete reports

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


def _layout_source(bdir: Path, block: str) -> Optional[Path]:
    """Return the fixed A5 layout view this producer actually grades."""
    return _find_gds(bdir, block) or (
        bdir / "layout.mag" if (bdir / "layout.mag").is_file() else None)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _layout_identity(bdir: Path, netlist: Path) -> Tuple[str, str]:
    """A5's layout vs the netlist LVS would compare (see
    `_analog_producer_common.layout_netlist_identity`)."""
    import _analog_producer_common as _pc  # noqa: PLC0415
    if not (bdir / "layout_provenance.json").is_file():
        return ("UNVERIFIED", "no layout_provenance.json")
    return _pc.layout_identity_of_block(bdir, netlist)


def _find_source_netlist(bdir: Path, block: str) -> Optional[Path]:
    for pat in (f"{block}.sp", f"{block}.spice", f"{block}.cir",
                "*.sp", "*.spice"):
        hits = sorted(bdir.glob(pat))
        if hits:
            return hits[0]
    return None


# ── minimal container helpers (self-contained; real-run only) ───────────────

def _docker_exec_raw(container: str, cmd: str, timeout: int = 60
                     ) -> Tuple[int, str, str]:
    """A SHORT, bounded probe inside the container. Correct for `test -e` and
    `command -v`: a probe that cannot answer in a minute IS broken, and its
    failure decides nothing about a design. Also the callback the progress
    watchdog uses for its own CPU / identity / reap probes, which must never
    recurse back through the supervisor they are measuring.

    A TIMEOUT IS NOT rc 127. That collapse is the whole reason this helper was
    rewritten: `except Exception: return 127` mapped a SLOW tool onto the POSIX
    "command not found" code, and this file's own note at `_tool_on_path`
    records what A6 then reports for `rc=127, no report` -- "no parseable DRC
    result". A slow engine and an ABSENT engine were byte-identical to every
    reader. They are now 124 and 127.
    """
    try:
        r = subprocess.run(_ce.docker_exec_argv(container, "bash", "-lc", cmd),
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        return 124, out, f"PROBE TIMEOUT after {timeout}s: {exc}"
    except Exception as exc:                        # noqa: BLE001
        return 127, "", str(exc)


def _docker_exec(container: str, cmd: str, timeout: int = 600, *,
                 marker: Optional[str] = None,
                 log_path: Optional[Path] = None) -> Tuple[int, str, str]:
    """Run `cmd` in the container.

    marker=None -> `_docker_exec_raw`: the SHORT bounded probe path.
    marker set  -> the plugin-wide PROGRESS-STALL WATCHDOG
    (`_docker_watchdog.run_docker_supervised`), with NO wall-clock ceiling: a
    physical-verification run that is still making forward progress runs to
    completion however long that legitimately takes, and only one that has
    STOPPED moving is killed (rc `_watchdog.RC_STALLED`).

    WHY THIS FILE NEEDED ITS OWN FIX. It rolled a private `docker exec` helper
    -- a bare `subprocess.run(timeout=600)` with no supervision, no
    container-side backstop (so a fired timeout ORPHANED the klayout inside the
    container) and an `except Exception` that returned 127. `loop_watchdog_
    compliance_check` could not see it: the binary name comes from a runtime
    `_tool_on_path` lookup, so the argv carries no static long-tool literal for
    its class-(a) scan to match. The engine's own ABSENCE is still detected the
    way it always was, by `_tool_on_path` returning None BEFORE the run.
    chip/tool-AGNOSTIC.
    """
    if marker is None:
        return _docker_exec_raw(container, cmd, timeout)
    try:
        import sys as _sys
        if str(PROGRAMS_DIR) not in _sys.path:
            _sys.path.insert(0, str(PROGRAMS_DIR))
        import _docker_watchdog as _dw
    except Exception:                               # noqa: BLE001
        # DEGRADE LOUDLY, NEVER SILENTLY: if the supervisor cannot be imported
        # the run still happens, on the bounded path, and the caller can see
        # from the rc which path it took.
        return _docker_exec_raw(container, cmd, timeout)
    try:
        return _dw.run_docker_supervised(
            container, cmd, marker, docker_exec_raw=_docker_exec_raw,
            log_path=log_path)
    except Exception as exc:                        # noqa: BLE001
        # THE OLD HELPER SWALLOWED EVERYTHING INTO rc 127, and removing that
        # must not silently turn an unexpected launch error into a traceback
        # out of a physical-verification step. `run_supervised` maps a missing
        # binary to 127 itself; what can still escape is an OSError from the
        # spawn (permissions, no fds). Those ARE "the tool could not be run",
        # so 127 is the right code for them and the exception text says which.
        # A TIMEOUT can no longer arrive here at all — that was the defect.
        return 127, "", f"supervised launch failed: {exc!r}"


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


def _count_lyrdb_categories(text: str) -> int:
    """Rules the report actually GRADED. Only the count leaves this function
    (NDA hygiene) — never a rule name."""
    return len(re.findall(r"<category>", text or ""))


def _klayout_run(binc: str, deck: str, gds: str, block: str, container: str,
                 report_host: Path, extra_rd: str = "") -> Tuple[int, str]:
    """One `klayout -b -r` of one runset, with ONE retry on a non-zero exit.

    The retry is recorded by the caller, never hidden: the image's KLayout
    has been MEASURED to segfault in its deep-shape-store destructor after
    writing a complete report (1 in 5 runs of one extra-rules deck on one
    block). A second failure stands and the run is no evidence."""
    deck_c = _to_container_path(container, deck)
    gds_c = _to_container_path(container, gds)
    rpt_c = _to_container_path(container, str(report_host))
    cmd = (f"{shlex.quote(binc)} -b -r {shlex.quote(deck_c)} "
           f"-rd input={shlex.quote(gds_c)} "
           f"-rd report={shlex.quote(rpt_c)} "
           f"-rd topcell={shlex.quote(block)}{extra_rd}")
    tail = ""
    rcs = []
    for _attempt in range(2):
        # SUPERVISED BY PROGRESS. The marker is the deck path, which is
        # already in the argv, so the watchdog can find this job's process
        # tree in the container and read its CPU. No ceiling: a DRC that is
        # still working is never cut off, and one that has stopped moving is.
        rc, out, err = _docker_exec(container, cmd, marker=deck_c)
        rcs.append(rc)
        tail = (out + err)[-300:]
        if rc == 0:
            break
    return rcs[-1], tail if len(rcs) == 1 else f"{tail} (exit codes {rcs})"


def _klayout_drc_runner(deck: str, gds: str, block: str, container: str,
                        report_host: Path) -> Tuple[Optional[int], Dict[str, Any]]:
    """Run an open-PDK KLayout DRC runset on the block GDS — the main runset
    AND every extra-rules runset the PDK ships beside it (q1).

    `klayout -b -r <deck> -rd input=<gds> -rd report=<rdb> -rd topcell=<block>`
    is the runset convention those decks declare (`$input` / `$report` /
    `$topcell`). Returns (violations, meta); None when the engine or the report
    is missing, so the caller keeps its existing waiver path rather than
    inventing a verdict.

    THE EXTRA RUNSET (`_a6_drc_authority.EXTRA_RUNSET_GLOB`, beside the main
    deck). The PDK's own DRC driver runs it by default; this runner did not,
    so a rule only it grades (MEASURED on ihp-sg13g2: `MIM.e`, `M2.d`) was
    graded by no deck in A6 at all. Present but silent is no evidence.
    """
    binc = _tool_on_path(container, "klayout")
    if binc is None:
        return None, {"reason": "klayout engine not on container PATH"}
    rc, tail = _klayout_run(binc, deck, gds, block, container, report_host)
    if not report_host.is_file():
        return None, {"reason": f"klayout produced no report (rc={rc})",
                      "tail": tail}
    text = report_host.read_text(errors="replace")
    graded = _count_lyrdb_categories(text)
    if graded == 0 or rc != 0:
        # A REPORT THAT GRADED NOTHING IS NOT A CLEAN REPORT — the same law
        # the SVRF branch below already carries, which this branch did not.
        # A KLayout runset OPENS its report before it grades anything, so a
        # deck that aborts mid-run still leaves a well-formed database on
        # disk with zero categories and zero items. Counting only `<item>`
        # read that as `violations: 0, result: PASS`, and the block was
        # certified DRC-clean by a run that never evaluated a rule.
        #
        # MEASURED: the design's own staged deck resolves a tech-JSON beside
        # the PDK tree it was copied from; staged alone that path does not
        # exist, the deck raises, and the 474-byte report it leaves behind
        # has 0 categories. A real run of the same deck on the same GDS
        # grades 560. Both produced `violations: 0` here.
        return None, {"reason": (f"DRC report graded {graded} rule(s) at "
                                 f"rc={rc} — an unread deck, not a clean "
                                 f"block"),
                      "method": "klayout_runset", "rc": rc,
                      "tail": tail}
    violations = _count_lyrdb_items(text)
    passes = {str(deck): _auth.lyrdb_text_rules(text)}
    extra_meta: List[Dict[str, Any]] = []
    threads = max(1, min(8, os.cpu_count() or 1))
    for ex in _auth.extra_runsets(Path(deck).parent):
        rpt = report_host.parent / f"drc.{ex.stem}.lyrdb"
        erc, etail = _klayout_run(
            binc, str(ex), gds, block, container, rpt,
            f" -rd run_mode=deep -rd threads={threads}")
        etext = rpt.read_text(errors="replace") if rpt.is_file() else ""
        erules = _auth.lyrdb_text_rules(etext)
        if erc != 0 or not erules["graded"]:
            return None, {"reason": (
                f"{_auth.EXTRA_RUNSET_GRADED_NOTHING}: the extra runset "
                f"{ex.name} graded {len(erules['graded'])} rule(s) at "
                f"rc={erc} — present but silent is NOT_MEASURED, never "
                f"clean"), "method": "klayout_runset", "rc": erc,
                "tail": etail}
        rec: Dict[str, Any] = {"runset": ex.name,
                               "report": rpt.name,
                               "rules_graded": len(erules["graded"]),
                               "violations": erules["violations"]}
        if erules["violations"]:
            # WHAT A DEEP COUNT COUNTS: one marker per unique cell. The flat
            # count (every instance) is disclosed beside it; the verdict is
            # the same either way.
            frpt = report_host.parent / f"drc.{ex.stem}.flat.lyrdb"
            frc, _ = _klayout_run(binc, str(ex), gds, block, container, frpt,
                                  f" -rd run_mode=flat -rd threads={threads}")
            rec["flat_counts"] = (
                _auth.lyrdb_text_rules(frpt.read_text(errors="replace"))
                ["violations"] if frc == 0 and frpt.is_file()
                else f"NOT_MEASURED (rc={frc})")
        extra_meta.append(rec)
        passes[str(ex)] = erules
        violations += sum(erules["violations"].values())
    authoritative = _auth.merge_passes(passes)
    # RULES GRADED = DISTINCT RULES ACROSS EVERY RUNSET. `_count_lyrdb_
    # categories` counts every `<category>` tag, and each violation `<item>`
    # carries one too, so on a report with hits it over-counts (MEASURED:
    # 846 for 560 + 272 graded rules and 14 items).
    meta: Dict[str, Any] = {"method": "klayout_runset", "rc": rc,
                            "rules_pass": len(authoritative["graded"])
                            or graded}
    if extra_meta:
        meta["extra_runsets"] = extra_meta
    meta["authoritative"] = authoritative
    return violations, meta


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
    rc, out, err = _docker_exec(container, cmd, marker=deck_c,
                                log_path=report_host)
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


# ── LVS engine dispatch ─────────────────────────────────────────────────────
#
# THE DEFECT THIS CLOSES, MEASURED. The LVS arm fired on the mere PRESENCE of a
# resolved `lvs_deck` and then ignored it, running a generic geometric
# extraction whose device recognition is driven by a built-in EXAMPLE layer map
# ("a common 180nm-style GDS numbering"). On any PDK whose layer numbers differ
# — i.e. on any PDK but the one the example was drawn from — that extraction
# recognizes nothing, `top_circuit()` is None, and the arm died inside the
# container with an AttributeError that reached the caller as `rc=1`. So the
# deck the resolver had just resolved was never run, and the block never got an
# LVS verdict: A6 reported "no parseable LVS result — the tool has not run",
# which was true, and gave no hint that a sign-off engine for that exact deck
# was sitting on PATH.
#
# The fix is the same shape as the DRC one above: run the deck with the engine
# that can read it. A KLayout LVS runset declares `$input` / `$schematic` /
# `$topcell` / `$report` exactly as the DRC runset declares its own variables.
_KLAYOUT_LVS_SUFFIXES = (".lvs", ".lylvs")
_NETGEN_LVS_SUFFIXES = (".tcl",)


def lvs_deck_kind(deck: str) -> str:
    """`klayout` | `netgen` | `svrf` | `unknown` — from the deck's extension."""
    suf = Path(str(deck or "")).suffix.lower()
    if suf in _KLAYOUT_LVS_SUFFIXES:
        return "klayout"
    if suf in _NETGEN_LVS_SUFFIXES:
        return "netgen"
    if suf in _SVRF_DECK_SUFFIXES:
        return "svrf"
    return "unknown"


_LVS_MATCH_RE = re.compile(r"Congratulations!\s*Netlists match", re.I)
_LVS_NOMATCH_RE = re.compile(r"Netlists don.t match", re.I)


def lvs_runset_verdict(stdout: str) -> Optional[str]:
    """`MATCH` | `MISMATCH` | None, from a KLayout LVS runset's own output.

    None when the run said NEITHER — an aborted deck must not be read as a
    verdict in either direction (the deck aborts on an unreadable schematic
    before it compares anything, and that is silence, not a mismatch).
    """
    if _LVS_MATCH_RE.search(stdout or ""):
        return "MATCH"
    if _LVS_NOMATCH_RE.search(stdout or ""):
        return "MISMATCH"
    return None


#: A SPICE element card opens with the device letter of its class. The
#: comparison-side source netlist is already in element form — that is what
#: `analog_lvs_comparison_prep.device_calls_to_elements` produced — so the
#: block's device count is the number of those cards inside its `.subckt`.
#: This is a COUNT and nothing else: no device name, no net, no geometry
#: leaves the netlist, which is the same NDA line `comp.json` already holds.
_SPICE_ELEMENT_CARD = re.compile(r"^[MQRCDLJKVIEFGHXT]\S*\s", re.I)


def source_device_count(text: str, block: str) -> Optional[int]:
    """How many device cards the comparison-side netlist declares for `block`.

    None when the netlist carries no `.subckt <block>` — an absent count must
    read as absent, never as zero: a converter whose LVS says `0 devices` and
    one whose LVS could not find the subcircuit are not the same finding, and
    only one of them is a design problem.
    """
    inside = False
    n = 0
    for line in (text or "").splitlines():
        st = line.strip()
        if st.lower().startswith(".subckt"):
            parts = st.split()
            inside = len(parts) > 1 and parts[1].lower() == block.lower()
            continue
        if inside and st.lower().startswith(".ends"):
            return n
        if inside and _SPICE_ELEMENT_CARD.match(st):
            n += 1
    return n if inside else None


def _klayout_lvs_runset_runner(deck: str, gds: str, netlist: str, block: str,
                               container: str, work: Path
                               ) -> Tuple[Optional[str], Dict[str, Any]]:
    """Run a PDK's own KLayout LVS runset on the block, comparison-side prepared.

    The two comparison-side copies (a netlist in element form without the model
    libraries, and a layout whose top cell keeps only its declared ports as
    text) are built by `analog_lvs_comparison_prep`; the design's own netlist
    and GDS are never modified. NUMBERS ONLY — the verdict plus device counts,
    never netlist content.
    """
    binc = _tool_on_path(container, "klayout")
    if binc is None:
        return None, {"reason": "klayout engine not on container PATH"}
    try:
        import analog_lvs_comparison_prep as _prep
    except Exception as exc:                                  # pragma: no cover
        return None, {"reason": f"comparison-side prep unavailable: {exc}"}
    work.mkdir(parents=True, exist_ok=True)
    src_text = Path(netlist).read_text(errors="replace")
    ports = _prep.declared_ports(src_text, block)
    if not ports:
        return None, {"reason": (f"block netlist declares no .subckt {block} "
                                 f"port list — nothing to bind pins to")}
    cmp_sp = work / f"{block}_lvs_source.spice"
    topology_path = Path(netlist).parent / "topology.json"
    try:
        topology_bytes = (topology_path.read_bytes()
                          if not _prep.role_models(src_text) and topology_path.is_file() else None)
        if topology_bytes is None:
            prepared, stats = _prep.prepare_source_netlist(src_text, block)
        else:
            prepared, stats = _prep.prepare_source_netlist(src_text, block,
                                                           topology=json.loads(topology_bytes))
    except (ValueError, TypeError) as exc:
        return None, {"reason": f"comparison topology unavailable: {exc}"}
    if topology_bytes is not None:
        import hashlib
        stats["topology_source"] = {"path": str(topology_path.resolve()),
                                    "sha256": hashlib.sha256(topology_bytes).hexdigest()}
    cmp_sp.write_text(prepared)

    cmp_gds = work / f"{block}_lvs_layout.gds"
    script = work / f"{block}_port_only.py"
    script.write_text(_prep.PORT_ONLY_LAYOUT_SCRIPT)
    rc_p, out_p, err_p = _docker_exec(
        container,
        marker=_to_container_path(container, str(script)),
        cmd=f"{shlex.quote(binc)} -b -r "
        f"{shlex.quote(_to_container_path(container, str(script)))} "
        f"-rd gds={shlex.quote(_to_container_path(container, gds))} "
        f"-rd out={shlex.quote(_to_container_path(container, str(cmp_gds)))} "
        f"-rd ports={shlex.quote(chr(10).join(ports))}")
    if not cmp_gds.is_file():
        return None, {"reason": f"comparison-side layout not written (rc={rc_p})",
                      "tail": (out_p + err_p)[-300:]}

    db = work / f"{block}.lvsdb"
    # WHERE THE EXTRACTED NETLIST GOES, SAID OUT LOUD. Unset, the runset
    # derives the path from the active cellview's filename — which in batch
    # mode is empty, so it lands beside the process's own working directory
    # and the write is refused. MEASURED on this campaign's blocks:
    #
    #   ERROR: RuntimeError: Unable to open file: /home/<your-user>//ldo_extracted.cir
    #          (errno=13) in Netlist::write in Executable::cleanup
    #
    # That exception is raised in the runset's CLEANUP, after the verdict is
    # printed and before the LVS database is written — so the arm reported
    # `mismatch` and named an `.lvsdb` that does not exist. The verdict was
    # right and the only artefact that could say WHY was never created.
    ext_cir = work / f"{block}_extracted.cir"
    rc, out, err = _docker_exec(
        container,
        marker=_to_container_path(container, str(db)),
        cmd=f"{shlex.quote(binc)} -b -r "
        f"{shlex.quote(_to_container_path(container, deck))} "
        f"-rd input={shlex.quote(_to_container_path(container, str(cmp_gds)))} "
        f"-rd topcell={shlex.quote(block)} "
        f"-rd schematic={shlex.quote(_to_container_path(container, str(cmp_sp)))} "
        f"-rd report={shlex.quote(_to_container_path(container, str(db)))} "
        f"-rd target_netlist="
        f"{shlex.quote(_to_container_path(container, str(ext_cir)))} "
        f"-rd run_mode=deep")
    verdict = lvs_runset_verdict((out or "") + (err or ""))
    if verdict is None:
        return None, {"reason": f"LVS runset reported no verdict (rc={rc})",
                      "tail": ((out or "") + (err or ""))[-300:]}
    # A verdict without its denominators is not a finding. `mismatch` with
    # both device counts absent cannot tell the next reader whether 256
    # devices met 256 with one net wrong, or met nothing at all — and this
    # runner was publishing exactly that, because only the OTHER LVS runner
    # collected the counts. The source side is free: it is the netlist this
    # runner just prepared. The layout side is not available from this engine
    # path — the runset's own report is a KLayout LVS database, not a device
    # tally — so it is reported ABSENT WITH ITS REASON rather than as a bare
    # null that reads like "not applicable".
    return verdict, {"method": "klayout_lvs_runset", "rc": rc,
                     "declared_ports": len(ports),
                     "device_calls_rewritten": stats["device_calls_rewritten"],
                     "source_devices": source_device_count(prepared, block),
                     "extracted_netlist": (str(ext_cir) if ext_cir.is_file()
                                           else None),
                     "layout_devices": None,
                     "layout_devices_absent_because": (
                         "the klayout LVS runset reports a verdict and an "
                         "LVS database, not an extracted device tally. The "
                         "klayout_pdk_lvs comparer does produce one, but "
                         "only for a PDK whose own layer numbering is "
                         "staged: run without a layermap it refuses by name "
                         "(`NO CIRCUIT -- the layer map recognized no "
                         "device`), which is correct and is not a "
                         "substitute for the count"),
                     "report": str(db)}


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
        container, marker=klvs_c, cmd=base + f"python3 {shlex.quote(klvs_c)} extract "
        f"{shlex.quote(gds_c)} --out {shlex.quote(layout_c)} "
        f"--threads {threads}{lm}")
    if not layout_sp.is_file() or layout_sp.stat().st_size == 0:
        return None, {"reason": f"klayout extraction produced no netlist "
                                f"(rc={_rc_e})", "tail": (_out_e + _err_e)[-300:]}
    rc_c, out_c, err_c = _docker_exec(
        container, marker=klvs_c, cmd=base + f"python3 {shlex.quote(klvs_c)} compare "
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
    # THE HEADER NAMED ONE ENGINE WHATEVER RAN. Every report this function
    # has ever written opens "native svrfdrc (staged foundry .rule deck)" —
    # including the ones the KLayout branch produced, whose own `method:`
    # line two lines down says `klayout_runset`. A reader who takes the first
    # line at face value attributes the number to an engine and a deck format
    # that were not used. The engine is `meta['method']`, so the header says
    # that and nothing else.
    method = meta.get("method", "svrf_native")
    lines = [
        f"# {block} per-block DRC — engine: {method} "
        f"(the staged sign-off deck this engine reads)",
        f"# numbers only — NDA hygiene; no rule names / geometry. The "
        f"engine's own per-rule report is kept beside this file"
        + (f" as {meta['raw_report']}" if meta.get("raw_report") else ""),
        f"rules_pass: {meta.get('rules_pass', 0)}",
        f"rules_skip: {meta.get('rules_skip', 0)}",
        f"violations: {violations}",
        f"result: {verdict}",
        *([f"layout_path: {meta['layout_path']}",
           f"layout_sha256: {meta['layout_sha256']}"]
          if meta.get("layout_path") and meta.get("layout_sha256") else []),
        "",
    ]
    # WHICH ENGINE GRADED WHICH RULE. The count above is now two engines'
    # and a reader must be able to take it apart: the sign-off deck's own
    # number, and the rules it does not grade at all, graded by the engine
    # that does. Rule IDS only, never geometry — the same NDA hygiene as the
    # rest of this report.
    se = meta.get("second_engine")
    if isinstance(se, dict):
        lines[-1:] = [
            f"# second engine: {se.get('engine', '?')} — adjudicates ONLY "
            f"rules the sign-off deck does not grade, and only violations "
            f"attributed to this flow's own paint",
            f"second_engine_result: {se.get('result', 'MEASURED')}",
            f"second_engine_violations: {se.get('violations', 0)}",
            f"second_engine_rules_adjudicated: "
            f"{','.join(sorted((se.get('own_paint_rules_the_signoff_deck_does_not_grade') or {}))) or '-'}",
            f"second_engine_rules_deferred_to_signoff_deck: "
            f"{','.join(sorted((se.get('deferred_to_signoff_deck') or {}))) or '-'}",
            f"second_engine_rules_reported_not_verdicted: "
            f"{','.join(sorted((se.get('reported_not_verdicted') or {}))) or '-'}",
            f"# {se.get('coverage', 'coverage not stated')}",
            "",
        ]
        dis = se.get("engine_disagreements") or {}
        if dis:
            lines[-1:] = [
                "# engine disagreements (q1): the deck graded the rule and "
                "fired 0; deferred only behind a capability control",
                f"second_engine_uncontrolled_disagreements: "
                f"{','.join(sorted(dis.get('uncontrolled_disagreements') or {})) or '-'}",
                f"second_engine_engine_artefact: "
                f"{','.join(sorted(dis.get('engine_artefact') or {})) or '-'}",
                f"second_engine_deferred_by_capability_control: "
                f"{','.join(sorted(dis.get('deferred_by_capability_control') or {})) or '-'}",
                "",
            ]
    # THE EXTRA-RULES RUNSET(S), by name, with what they fired (rule ids and
    # counts only): the authoritative deck is the main runset PLUS these.
    for ex in meta.get("extra_runsets") or []:
        lines[-1:] = [
            f"extra_runset: {ex.get('runset')} graded "
            f"{ex.get('rules_graded')} violations "
            f"{sum((ex.get('violations') or {}).values())} "
            f"({','.join(f'{r}={n}' for r, n in sorted((ex.get('violations') or {}).items())) or '-'}; "
            f"deep-mode markers per unique cell)",
            *([f"extra_runset_flat_counts: "
               f"{','.join(f'{r}={n}' for r, n in sorted(ex['flat_counts'].items())) or '-'}"]
              if isinstance(ex.get("flat_counts"), dict) else []),
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
        **({"layout_path": meta["layout_path"],
            "layout_sha256": meta["layout_sha256"]}
           if meta.get("layout_path") and meta.get("layout_sha256") else {}),
        # An absent count is absent for a REASON, and the reason belongs next
        # to it. Without this the artefact carries `null` and a reader cannot
        # tell an engine that does not produce the number from a block that
        # has none.
        **({"counts_absent_because": meta["layout_devices_absent_because"]}
           if meta.get("layout_devices") is None
           and meta.get("layout_devices_absent_because") else {}),
        # A MISMATCH VERDICT WITH NO PATH TO ITS EVIDENCE IS A DEAD END. The
        # engine's own database and extracted netlist are where the next
        # reader finds WHICH nets and devices did not pair; both are named
        # here, and each is named only when it is actually on disk.
        **({"lvs_database": meta["report"]}
           if meta.get("report") and Path(str(meta["report"])).is_file()
           else {}),
        **({"extracted_netlist": meta["extracted_netlist"]}
           if meta.get("extracted_netlist") else {}),
        **({"layout_netlist_identity": meta["layout_netlist_identity"]}
           if meta.get("layout_netlist_identity") else {}),
        "note": ("device-level LVS (bulk-normalize + pin-fix); numbers only — "
                 "NDA hygiene, no netlist content"),
    }, indent=2) + "\n")
    return comp


# ── the second engine, and the rules the sign-off deck does not grade ────
#
# THE DEFECT THIS CLOSES, MEASURED (ihp-sg13g2, image 0.3.46, u_hawaii_adc).
# A6's verdict is the staged KLayout runset's, and that runset does not grade
# every rule the PDK writes. On this PDK the MiM capacitor family is almost
# entirely absent — `%include rule_decks/beol/6_11_mim.drc` is commented out
# in the shipped deck, so of MIM.a..MIM.i the 560 graded categories contain
# only `MIM.c` and `MIM.d`. "0 violations of 560 rules" was therefore SILENCE
# about the capacitor, not a clean bill: while it said that, `delta_sigma`
# carried eight `Via4 cannot contact MiM cap bottom plate (MIM.i)` — this
# flow's OWN paint on the capacitor's plate — and magic, which does grade
# MIM.i, was the only engine in the image that could see them.
#
# So a rule the sign-off deck DOES NOT GRADE AT ALL is adjudicated by the
# engine that does. Two conditions, and both are necessary:
#
#   * the rule is absent from the sign-off deck's own graded category set —
#     where both engines grade a rule the SIGN-OFF engine is the authority
#     and the second engine's disagreement is a separate question (measured:
#     the two engines count rectangles and polygons differently);
#   * the second engine attributes the violating geometry to THIS FLOW'S OWN
#     PAINT. A rule the PDK's own gencell breaks when generated ALONE is the
#     PDK's business and no routing change removes it — it is reported, never
#     verdicted. Measured on `ldo`: 60 rectangles of `M2.d`, a rule the
#     KLayout deck also does not grade, every one of them inside the PDK's
#     own cells. Verdicting those would fail every block on this PDK for a
#     cell nobody in this flow drew.
#
# Nothing here names a rule, a family, a layer or a PDK: the join key is the
# rule id the PDK itself writes in both engines' output, and the attribution
# is `analog_a6_drc_attribute`'s, which is read, never re-implemented.

#: A rule id as a PDK writes it — `MIM.i`, `M2.d`, `V1.c1` — taken from the
#: LAST parenthesised token of an engine's message.
_RULE_ID_RE = re.compile(r"\(([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)\)")


def rule_id(message: str) -> Optional[str]:
    """The PDK's own rule id inside an engine's message, or None."""
    hits = _RULE_ID_RE.findall(message or "")
    return hits[-1] if hits else None


def graded_rule_ids(lyrdb_text: str) -> set:
    """Every rule the sign-off deck actually GRADED, by id, from its own
    report. A deck that produced no report grades nothing this function will
    claim — "could not read it" is not "read it and it was empty"."""
    return {c.strip() for c in
            re.findall(r"<category>\s*<name>(.*?)</name>", lyrdb_text or "",
                       re.S) if c.strip()}


def unadjudicated_rules(attribution: Dict[str, Any], graded: set
                        ) -> Dict[str, int]:
    """{rule id: violating rectangles} for rules the sign-off deck does not
    grade AND the second engine attributes to this flow's own paint.

    Reads `analog_a6_drc_attribute`'s report; both conditions above must
    hold, and a rule whose id cannot be read is NOT counted — it is returned
    by `unreadable_rule_messages` so a reader is told what was skipped rather
    than handed a silent zero."""
    out: Dict[str, int] = {}
    own = ((attribution or {}).get("by_class_and_rule") or {}).get("LAYOUT") or {}
    for message, count in own.items():
        rid = rule_id(message)
        if rid is None or rid in graded:
            continue
        out[rid] = out.get(rid, 0) + int(count)
    return out


def rules_by_disposition(attribution: Dict[str, Any], graded: set
                         ) -> Dict[str, Dict[str, int]]:
    """Every rule the second engine reported, split by WHAT IS DONE WITH IT.

    Three dispositions, and the record carries all three by MEMBERSHIP so a
    reader is never left inferring one from a total:

      `adjudicated`  the sign-off deck does not grade it and the geometry is
                     this flow's own paint — it counts.
      `deferred`     the sign-off deck DOES grade it, so the sign-off
                     engine's answer stands and this one is not a verdict.
      `reported`     the sign-off deck does not grade it and the geometry is
                     not this flow's to change (the PDK's own gencell, or a
                     placement/interaction class) — surfaced, never a
                     verdict. MEASURED: 60 rectangles of one such rule on
                     `ldo` and 816 on `delta_sigma`, none of which any
                     artefact in this flow used to mention at all.
    """
    out: Dict[str, Dict[str, int]] = {"adjudicated": {}, "deferred": {},
                                      "reported": {}}
    for cls, rules in ((attribution or {}).get("by_class_and_rule") or {}).items():
        for message, count in (rules or {}).items():
            rid = rule_id(message)
            if rid is None:
                continue
            if rid in graded:
                key = "deferred"
            elif cls == "LAYOUT":
                key = "adjudicated"
            else:
                key = "reported"
            out[key][rid] = out[key].get(rid, 0) + int(count)
    return {k: dict(sorted(v.items())) for k, v in out.items()}


def unreadable_rule_messages(attribution: Dict[str, Any]) -> List[str]:
    """Messages the second engine produced whose rule id this program cannot
    read. NOT_MEASURED, never a default."""
    own = ((attribution or {}).get("by_class_and_rule") or {}).get("LAYOUT") or {}
    return sorted(m for m in own if rule_id(m) is None)


#: The tier a second-engine record carries when the engine did not grade
#: anything. A reader routes on this; `reason` is the sentence they act on.
SECOND_ENGINE_NOT_MEASURED = "NOT_MEASURED"


def second_engine_not_measured(reason: str = "", *, container: str = "",
                               refusal: str = "") -> Dict[str, Any]:
    """The record for "the second engine did not grade anything", BY NAME.

    ONE SHAPE, ONE PLACE — vibe-ic#2156. This record used to be composed in the
    caller with a fixed sentence, and the runner's own `why` was dropped on the
    floor one frame below (`attribution, why = run(...)` and then
    `if attribution is None: return None`). So every way the engine could fail
    to run — an absent container, a docker that would not start, and a container
    running bytes other than the pinned ones — reached the report as the same
    sentence, and the wrong-image case did not reach it at all: a
    `ContainerImageMismatch` is a `RuntimeError` and nothing on this path caught
    it, so it escaped `run_block_pv` and took the whole A6 producer down.

    `refusal` is set exactly when the engine was REFUSED rather than merely
    unavailable — the container was reached and it is the wrong image — and it
    carries the refusal `_eda_pin` composed, which names both digests. "I could
    not look" and "I looked and was refused" are different facts and this keeps
    them different.
    """
    record: Dict[str, Any] = {
        "engine": "magic drc(full)",
        "result": SECOND_ENGINE_NOT_MEASURED,
        "reason": reason or ("the second engine could not run; the rules "
                             "the sign-off deck does not grade are "
                             "UNGRADED, not clean"),
    }
    if container:
        record["container"] = container
    if refusal:
        record["refusal"] = _pin.CONTAINER_IMAGE_MISMATCH
        record["refusal_detail"] = refusal
        record["required_digest"] = _pin.IMAGE_DIGEST
    return record


def second_engine_drc(project: Path, block: str, container: str,
                      lyrdb_text: str, *, runner: Optional[Callable] = None,
                      klayout: Optional[Dict[str, Any]] = None,
                      capability_runner: Optional[Callable] = None,
                      roundtrip_runner: Optional[Callable] = None
                      ) -> Dict[str, Any]:
    """Grade, with the second engine, the rules the sign-off deck does not.

    ALWAYS RETURNS A RECORD. When the engine could not grade anything the record
    is `second_engine_not_measured(...)` — `result` is NOT_MEASURED and `reason`
    is the runner's own sentence — so the caller states what happened instead of
    crediting silence as cleanliness, and instead of stating one fixed sentence
    for every different way it failed (vibe-ic#2156).
    """
    run = runner
    if run is None:
        def run(proj, blk, ctn):
            # The attribution program is INVOKED, not re-implemented and not
            # partially re-spelled: its own CLI carries its own magicrc
            # default, so no PDK path literal appears in this file.
            import analog_a6_drc_attribute as _attr
            import tempfile as _tf
            host = Path(_tf.mkdtemp(prefix="a6_second_engine."))
            out = host / "attribution.json"
            try:
                _attr.main([str(proj), "--block", blk,
                            "--container", ctn, "--json", str(out)])
                if not out.is_file():
                    return None, "the attribution program wrote no report"
                return json.loads(out.read_text()), ""
            except _ce.ContainerImageMismatch as exc:
                # A REFUSAL, NOT AN ABSENCE, and never an escape. The guarded
                # argv builder raises this when the container it was asked for
                # runs bytes other than the pinned ones; the refusal already
                # names the container and BOTH digests, so it is relayed
                # verbatim rather than summarised.
                return None, str(exc)
            except (OSError, ValueError, SystemExit) as exc:
                return None, f"the second engine did not run: {exc}"
            finally:
                shutil.rmtree(host, ignore_errors=True)
    attribution, why = run(str(project), block, container)
    if attribution is None:
        why = str(why or "")
        return second_engine_not_measured(
            why, container=container,
            refusal=why if _pin.CONTAINER_IMAGE_MISMATCH in why else "")
    if isinstance(attribution.get("blocks"), dict):
        attribution = attribution["blocks"].get(block, attribution)
    # THE AUTHORITATIVE GRADED SET is every KLayout runset's (main + extra,
    # q1) when the caller measured them; else the one report it was handed.
    kl = klayout or _auth.lyrdb_text_rules(lyrdb_text)
    graded = (set(kl.get("graded") or []) if klayout
              else graded_rule_ids(lyrdb_text))
    adjudicated = unadjudicated_rules(attribution, graded)
    disp = rules_by_disposition(attribution, graded)
    disagreement = engine_disagreements(
        project, block, container, kl, disp["deferred"],
        capability_runner=capability_runner,
        roundtrip_runner=roundtrip_runner)
    uncontrolled = disagreement.get("uncontrolled_disagreements") or {}
    return {
        "engine": "magic drc(full)",
        "signoff_rules_graded": len(graded),
        "own_paint_rules_the_signoff_deck_does_not_grade":
            dict(sorted(adjudicated.items())),
        "violations": sum(adjudicated.values()) + sum(
            int(v["count"]) for v in uncontrolled.values()),
        **({"engine_disagreements": disagreement} if disagreement else {}),
        "deferred_to_signoff_deck": disp["deferred"],
        "reported_not_verdicted": disp["reported"],
        "unreadable_rule_messages": unreadable_rule_messages(attribution),
        "attribution_result": attribution.get("result"),
        "note": ("only rules the sign-off deck does not grade AT ALL, and "
                 "only violations this engine attributes to the flow's own "
                 "paint, are adjudicated here; a rule the PDK's own gencell "
                 "breaks alone is `reported_not_verdicted`, and a rule the "
                 "deck does grade is `deferred_to_signoff_deck`"),
        # WHAT A ZERO HERE DOES AND DOES NOT MEAN. This engine reports the
        # rules that FIRED; it does not enumerate the rules it checked and
        # passed. So an empty `own_paint_rules_…` is "this engine found none
        # of its own-paint kind", NOT "every rule the sign-off deck skips was
        # graded and is clean" — the one is a measurement and the other is
        # the silence this whole path exists to stop being read as a verdict.
        # The sign-off deck's graded set IS enumerable and is the number
        # above; this engine's is not, and saying so is cheaper than a reader
        # assuming it.
        "coverage": ("this engine reports rules that FIRED; it does not list "
                     "rules it graded and passed, so an absent rule is NOT "
                     "evidence that it was graded and clean"),
    }


def engine_disagreements(project: Path, block: str, container: str,
                         klayout: Dict[str, Any], deferred: Dict[str, int], *,
                         capability_runner: Optional[Callable] = None,
                         roundtrip_runner: Optional[Callable] = None
                         ) -> Dict[str, Any]:
    """The rules this engine fired that an authoritative deck GRADED and fired
    0 on — and whether that deferral is earned (q1).

    A deck's 0 on a rule is only evidence if the deck can fire that rule, so
    each disagreement needs the capability control: the same deck fires it on
    the PDK's own unit FAIL testcase. One that does not is `uncontrolled` and
    COUNTS; one that does is deferred, and is an ENGINE_ARTEFACT when the
    bare-device GDS round trip also holds. Empty when the engines agree."""
    dis = _auth.disagreements(klayout, deferred)
    if not dis:
        return {}
    decks = list((klayout.get("passes") or {}).keys())
    cap = (capability_runner or _native_capability)(
        project, block, container, sorted(dis), decks)
    rt = (roundtrip_runner or _native_roundtrip)(
        project, block, container, sorted(dis), decks)
    auth = _auth.authority(klayout, dis, (), cap, rt)
    return {k: auth[k] for k in ("deferred_by_capability_control",
                                 "engine_artefact",
                                 "deferred_not_engine_artefact",
                                 "uncontrolled_disagreements",
                                 "blocking_codes")}


def _unit_testcase_dir(project: Path, block: str, container: str,
                       main_deck: str) -> Optional[str]:
    """Where the PDK's DRC unit testcases are, as a container path: beside
    the staged deck when they were staged, else beside the SAME deck in the
    PDK the block's layout was drawn with (A5's `layout_provenance.json`)."""
    host = Path(main_deck).parent / _auth.UNIT_TESTCASE_DIR
    if host.is_dir():
        return _to_container_path(container, str(host))
    try:
        import analog_a7_post_layout_emit as _a7
        tech = _a7.layout_tech(block_dir(project, block) or Path("."))
    except (ValueError, OSError):
        return None
    libs = tech.parents[1]
    # SUPERVISED BY PROGRESS, like every non-probe call here: a walk of the
    # PDK tree is not a `test -e`. The marker is the tree, already in argv.
    rc, out, _ = _docker_exec(
        container, f"find {shlex.quote(str(libs))} -name "
                   f"{shlex.quote(Path(main_deck).name)} -path '*drc*' "
                   f"2>/dev/null | sort | head -1", marker=str(libs))
    found = (out or "").strip().splitlines()
    if rc != 0 or not found:
        return None
    return str(Path(found[-1]).parent / _auth.UNIT_TESTCASE_DIR)


def _native_capability(project: Path, block: str, container: str,
                       rules: List[str], decks: List[str]
                       ) -> Dict[str, Dict[str, Any]]:
    """Run every authoritative deck on the PDK's unit testcases that name a
    disagreeing rule, in the EDA container. Reports land in this producer's
    own work area (`phase3/extracted/analog/_capability`)."""
    none = {r: _auth.capability_record(r, [], {}) for r in rules}
    binc = _tool_on_path(container, "klayout") if decks else None
    unit = (_unit_testcase_dir(project, block, container, decks[0])
            if binc else None)
    if not unit:
        return {r: dict(v, result=_auth.CAP_NOT_MEASURED,
                        reason="no klayout or no PDK unit testcase dir")
                for r, v in none.items()}
    rc, out, _ = _docker_exec(
        container, f"python3 -c {shlex.quote(_auth.UNIT_LABEL_SCRIPT)} "
                   f"{shlex.quote(unit)}", marker=unit)
    labels = _auth.parse_unit_labels(out) or {}
    work = project / "phase3" / "extracted" / "analog" / "_capability"
    work.mkdir(parents=True, exist_ok=True)
    results: Dict[str, Optional[Dict[str, Any]]] = {}
    out_rec: Dict[str, Dict[str, Any]] = {}
    for rule in rules:
        tcs = _auth.testcases_for_rule(labels, rule)
        for tc in tcs:
            if tc in results:
                continue
            top = (labels.get(tc) or {}).get("top") or []
            if len(top) != 1:
                results[tc] = None
                continue
            passes: Dict[str, Any] = {}
            for i, d in enumerate(decks):
                rpt = work / f"{Path(tc).stem}.{Path(d).stem}.lyrdb"
                src = f"{unit}/{tc}"
                deck_c = _to_container_path(container, d)
                rpt_c = _to_container_path(container, str(rpt))
                ok = False
                for _attempt in range(2):
                    rc2, _o, _e = _docker_exec(
                        container,
                        f"{shlex.quote(binc)} -b -r {shlex.quote(deck_c)} "
                        f"-rd input={shlex.quote(src)} "
                        f"-rd report={shlex.quote(rpt_c)} "
                        f"-rd topcell={shlex.quote(top[0])} "
                        f"-rd run_mode=deep -rd threads=4", marker=deck_c)
                    if rc2 == 0 and rpt.is_file():
                        ok = True
                        break
                rules_i = (_auth.lyrdb_text_rules(rpt.read_text(
                    errors="replace")) if ok else None)
                if not rules_i or not rules_i["graded"]:
                    passes = {}
                    break
                passes[d] = rules_i
            results[tc] = _auth.merge_passes(passes) if passes else None
        out_rec[rule] = _auth.capability_record(rule, tcs, results)
    return out_rec


def _native_roundtrip(project: Path, block: str, container: str,
                      rules: List[str], decks: List[str]
                      ) -> Optional[Dict[str, Any]]:
    """ENGINE_ARTEFACT conditions ii/iii, measured by A6's own attribution
    program (`--gds-roundtrip`) with the same authoritative decks."""
    import analog_a6_drc_attribute as _attr
    dst = (project / "phase3" / "extracted" / "analog" / block
           / "a6_gds_roundtrip.json")
    dst.parent.mkdir(parents=True, exist_ok=True)
    argv = [str(project), "--block", block, "--container", container,
            "--json", str(dst), "--gds-roundtrip"]
    for r in rules:
        argv += ["--rule", r]
    for d in decks:
        argv += ["--klayout-deck", _to_container_path(container, d)]
    try:
        _attr.main(argv)
        doc = json.loads(dst.read_text())
    except (OSError, ValueError, SystemExit, RuntimeError) as exc:
        return {"result": "NOT_MEASURED", "reason": str(exc)}
    return doc.get("gds_roundtrip") or {"result": "NOT_MEASURED",
                                        "reason": doc.get("reason", "")}


def run_block_pv(project: Path, block: str, res: Dict[str, Any],
                 container: str = _pin.default_container_name(), *,
                 drc_runner: Optional[Callable] = None,
                 lvs_runner: Optional[Callable] = None,
                 gds_finder: Optional[Callable] = None,
                 netlist_finder: Optional[Callable] = None,
                 second_engine_runner: Optional[Callable] = None,
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
    layout = _layout_source(bdir, block)
    layout_meta = ({"layout_path": str(layout.relative_to(project)),
                    "layout_sha256": _sha256(layout)}
                   if layout is not None else {})

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
        # THE ENGINE'S OWN REPORT AND THE SUMMARY ARE TWO ARTEFACTS. They
        # were one path: the KLayout branch writes its RDB to the file it is
        # handed, and `_write_drc_report` then overwrote that file with the
        # six-line tally. The RDB is the ONLY per-rule evidence either engine
        # produces — which rule, how many, where — and every run destroyed it
        # the moment it was read. Measured on this campaign's two blocks: the
        # numbers 2780 and 264 survived, and the four rule names under them
        # had to be recovered by re-running the deck by hand. The raw report
        # keeps its own name beside the summary; nothing overwrites it.
        raw = bdir / ("drc.lyrdb" if deck_kind(str(drc_deck)) == "klayout"
                      else "drc.rawreport")
        runner = drc_runner or (
            lambda deck, g, blk, ctn: _default_drc_runner(
                deck, g, blk, ctn, raw))
        violations, meta = runner(str(drc_deck), str(gds), block, container)
        if violations is None:
            reasons.append(f"DRC engine unavailable: {meta.get('reason', '?')}")
        else:
            meta = dict(meta or {}, **layout_meta)
            if raw.is_file():
                meta["raw_report"] = str(raw.relative_to(project))
            # THE RULES THE SIGN-OFF DECK DOES NOT GRADE. See
            # `second_engine_drc`: a rule this deck never asks about is not
            # answered by its silence, and the engine that does ask is
            # evidence. Reported by MEMBERSHIP beside the deck's own graded
            # set, and NOT_MEASURED when the second engine cannot run.
            lyrdb_text = raw.read_text(errors="replace") if raw.is_file() else ""
            second = second_engine_drc(project, block, container, lyrdb_text,
                                       runner=second_engine_runner,
                                       klayout=meta.get("authoritative"))
            total = int(violations)
            # `second_engine_drc` always answers with a record now, and the
            # record says which tier it is. `or` covers an injected runner that
            # answers None outright, so a stub cannot put a bare None into the
            # report (vibe-ic#2156).
            second = second or second_engine_not_measured(container=container)
            meta["second_engine"] = second
            if second.get("result") != SECOND_ENGINE_NOT_MEASURED:
                total += int(second["violations"])
            _write_drc_report(bdir, block, total, meta)
            ran = True
            drc_result = {"executed": True, "violations": total,
                          "signoff_violations": int(violations),
                          "verdict": "PASS" if total == 0 else "FAIL",
                          "report": str((bdir / "drc.report").relative_to(project)),
                          "raw_report": meta.get("raw_report"),
                          "second_engine": meta["second_engine"]}

    # ── LVS: block source netlist vs block GDS → klayout_pdk_lvs compare ──
    lvs_deck = res.get("lvs_deck")
    if not lvs_deck:
        reasons.append("no staged LVS deck resolved")
    elif gds is None:
        reasons.append("no block GDS for LVS")
    elif netlist is None:
        reasons.append("no block source netlist for LVS")
    elif _layout_identity(bdir, netlist)[0] == "STALE":
        # A layout of an EARLIER netlist: comparing it says nothing about
        # this one (FX_A7_RCX_INVENTORY). The refusal is written where the
        # gate reads the verdict, so no older `comp.json` is left standing.
        _ident, _why = _layout_identity(bdir, netlist)
        _aa.write_json(bdir / "comp.json", {
            "block": block, "result": "refused",
            "rule": "A6_LAYOUT_NOT_OF_THIS_NETLIST",
            "layout_netlist_identity": {"state": _ident, "detail": _why},
            "note": "LVS not run: the layout is not of this netlist"},
            indent=2, ensure_ascii=True)
        reasons.append(f"A6_LAYOUT_NOT_OF_THIS_NETLIST: {_why}")
        lvs_result = {"executed": False, "verdict": "refused",
                      "rule": "A6_LAYOUT_NOT_OF_THIS_NETLIST", "detail": _why,
                      "report": str((bdir / "comp.json").relative_to(project))}
    else:
        _kind = lvs_deck_kind(str(lvs_deck))
        _work = project / "phase3" / "extracted" / "analog" / block
        if _kind == "klayout":
            runner = lvs_runner or (
                lambda g, nl, blk, ctn: _klayout_lvs_runset_runner(
                    str(lvs_deck), g, nl, blk, ctn, _work))
        else:
            runner = lvs_runner or (
                lambda g, nl, blk, ctn: _default_lvs_runner(
                    g, nl, blk, ctn, _work, layermap))
        verdict, meta = runner(str(gds), str(netlist), block, container)
        _ident, _why = _layout_identity(bdir, netlist)
        meta = dict(meta or {}, **layout_meta,
                    layout_netlist_identity={"state": _ident,
                                             "detail": _why})
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
