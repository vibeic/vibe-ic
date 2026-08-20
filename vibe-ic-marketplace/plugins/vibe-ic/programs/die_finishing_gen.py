#!/usr/bin/env python3
"""die_finishing_gen.py — Step 26.5ic producer: the PDK's own seal ring, and
the die-identification half's honest state.

WHAT GAP THIS CLOSES
--------------------
The flow had no chip-finishing track. It streamed a die out and signed it off
with no seal ring, and nothing anywhere said so. MEASURED 2026-08-19, by the
external authority rather than by this repo's own opinion: wafer.space's
precheck container, run against a GDS this flow published, refused at stage 3
of 16 —

    [Error]: Layer 'GUARD_RING_MK' is not used.
             wafers.space requires a seal ring (guard ring) around the die.

Stages 4-16 had never executed, so nothing downstream of that line was known
about any die this flow has ever produced.

TWO HALVES, TWO SOURCES, NEVER ONE VERDICT
-------------------------------------------
Step 26.5ic is die FINISHING, not just the ring:

  seal ring   the PDK ships its own generator and this program CALLS it. It
              contains no ring geometry: width, layer stack, corner
              construction and slot pattern are foundry data. A PDK that ships
              no generator is a NAMED disclosed skip, mirroring LibreLane's
              `KLayout.SealRing`, which says "KLAYOUT_SEALRING_SCRIPT is
              unset ... This step will be skipped" rather than pretending.
  die id      four shuttle-owned cells whose provenance is NOT YET DETERMINED.
              Until it is, this half reports NOT_DETERMINED — it must not
              report clean, and it must not fail the seal ring for its own
              absence. The two states are written to separate keys of the
              report so no consumer can average them.

WHY THE VERDICT IS A MEASUREMENT, NOT AN EXIT CODE
--------------------------------------------------
MEASURED on the gf180mcuD PDK shipped in this project's EDA image: the PDK's
own `sealring.py` is present, but the PCell library it imports is not shipped
in that PDK version. The script prints "Error: Couldn't load the seal ring
library." and calls `sys.exit()` with no argument — so it exits **0** and
writes **no output file**. Trusting the exit status would have recorded a seal
ring that does not exist, on a PDK that ships the script. So the ring is
verified by diffing the layouts (`sealring/sealring_verify.py`) and the exit
code is only ever additional evidence.

WHAT IS TAKEN FROM UPSTREAM, AND WHERE THIS GOES FURTHER
--------------------------------------------------------
Read out of `librelane/steps/klayout.py` in the pinned image, not remembered:

  TAKEN  the interface. `KLayout.SealRing.run_generic` is exactly
         `python3 <KLAYOUT_SEALRING_SCRIPT> --input <gds> --output <gds>
         --die-width <DIE_AREA[2]> --die-height <DIE_AREA[3]>` with PDK_ROOT
         and PDK in the environment. Four flags; that is the whole contract,
         and this program uses it unchanged.
  TAKEN  the skip. Upstream: "KLAYOUT_SEALRING_SCRIPT is unset.
         KLayout.SealRing may not be supported for the {PDK} PDK. This step
         will be skipped." Same shape here, PDK named, plus the list of
         locations searched — "unset" is only checkable if the reader is told
         where it was looked for.
  TAKEN  the second code path. `run_ihp_sg13g2` drives the script as a KLayout
         batch job and additionally sets KLAYOUT_PATH so the technology
         definition loads. Both are reproduced, KLAYOUT_PATH included.
  TAKEN  generator and checker are SEPARATE, and the checker is what fails the
         flow (upstream: KLayout.Density then Checker.KLayoutDensity). This
         program only produces; `die_finishing_check` is the gate.

  BETTER upstream selects between its two paths by PDK NAME. This program reads
         the interface the script itself DECLARES (does it accept
         `--die-width`?), so a PDK that is renamed, forked or vendored under a
         different name is still driven correctly, and a PDK nobody wrote a
         branch for is driven correctly the first time. MEASURED on the two PDK
         scripts in the pinned image: the option appears once in the pya-cli
         one and zero times in the KLayout-batch one.
  BETTER upstream derives the KLayout technology name by string-editing the PDK
         name. This reads `<name>` out of the PDK's own `.lyt`, which is the
         authority that owns it, and REFUSES when a PDK ships more than one
         rather than guessing.
  BETTER upstream emits NO METRIC. `KLayout.SealRing.run` and both of its
         branches return an empty MetricsUpdate — three `return views_updates,
         {}` in the class — so a LibreLane run cannot tell a die that was
         sealed from a die whose PDK had no script, and neither can its
         reports. This program writes reports/phase3/die_finishing.json on
         every path, with the seal-ring and die-identification halves in
         separate keys.
  BETTER upstream trusts the script's exit status. The measured gf180mcuD case
         below exits 0 having written nothing; this program diffs the layouts.

  ABSENT UPSTREAM, reported as a finding rather than searched for further:
         LibreLane has no die-identification step at all, and no shuttle
         precheck. The die-id cells are the SHUTTLE's, not the PDK's and not
         LibreLane's, so there is nothing upstream to copy for that half — which
         is part of why it is NOT_DETERMINED rather than merely unimplemented.

WHERE IT RUNS. At stream-out, after the layer merge and BEFORE the fill passes,
the density checks and the sign-off DRC/LVS consume the GDS — LibreLane's own
chip-flow order (SealRing -> Filler -> Density). Adding the ring after Step 31
would mean the die Step 31 verified is not the die that ships.

chip/PDK-AGNOSTIC: the script path, the invocation form, the technology name,
the guard-ring marker layer and the die-id cell list are all INPUTS. No
foundry, PDK, vendor or design literal appears here.

    die_finishing_gen <project_dir> [--gds G] [--script S] [--form F] [--tech T]
                      [--pdk-root R] [--pdk P] [--python PY] [--marker L/D]
                      [--die-width W] [--die-height H] [--out O | --in-place]
                      [--report R] [--json J] [--strict]
    main(argv) -> int : 0 sealed / 1 FAIL / 2 DISCLOSED SKIP
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _atomic_artefact import write_json as atomic_write_json  # vibe-ic#1082
from _atomic_artefact import write_text as atomic_write_text

try:
    from . import _klayout_launch as _kl                     # type: ignore
    from . import _tapeout_declaration as _td                # type: ignore
except ImportError:                                          # standalone gate
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _klayout_launch as _kl                            # type: ignore
    import _tapeout_declaration as _td                       # type: ignore

PASS, FAIL, SKIP = 0, 1, 2

#: Lines an EDA container launcher prints before the tool it launched says
#: anything. They come FIRST, which is the reason the quoting below takes the
#: last line rather than the first — see `_last_said`.
_LAUNCHER_NOISE = ("[INFO]", "[WARN]", "[DEBUG]")


def _last_said(text: str, limit: int = 200) -> str:
    """The line of `text` most likely to say what went wrong.

    Quoting the FIRST line was wrong in the one case this reason exists for.
    Measured: a PDK whose seal-ring PCell library is missing prints
    `Error: Couldn't load the seal ring library.` and exits 0 — but the
    container launcher has already printed two banner lines ahead of it, so the
    diagnosis read "it exited 0 and said: [INFO] Final PATH variable: ...". The
    banner is not what went wrong, and a reason that quotes it sends the reader
    to the wrong place.

    A tool says what failed LAST, so this takes the last non-empty line, and
    skips the launcher banners when the last line is one of them. The full
    output is carried separately in `generator_output` either way; this only
    decides which line the human-readable reason quotes.
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    for ln in reversed(lines):
        if not ln.startswith(_LAUNCHER_NOISE):
            return ln[:limit]
    return lines[-1][:limit]

_CHECK = "die_finishing"
#: Written by this program on EVERY path; READ (never overwritten in
#: place) by `die_finishing_check`, which is the step gate.
_PRODUCER = "die_finishing_gen"

#: Where the sign-off GDS lives. `phase3/stage3/pnr` FIRST and deliberately:
#: that is the artefact Step 31's DRC and LVS actually read, and Step 37's
#: `phase3/stage4/gds` copy is only published when it is byte-identical to it.
#: Sealing the published copy instead would seal the die AFTER its evidence.
_GDS_GLOBS = (
    "phase3/stage3/pnr/*.gds",
    "phase3/stage4/gds/*.gds",
)
#: LibreLane's own PDK variable, so an environment already configured for the
#: canonical open-source flow needs no second declaration here.
_ENV_SCRIPT = "KLAYOUT_SEALRING_SCRIPT"
#: The path every PDK config.tcl that declares the variable actually builds:
#: `$PDK_ROOT/$PDK/libs.tech/klayout/tech/scripts/sealring.py`. This is PDK
#: STRUCTURE, not a PDK name — it resolves for any PDK laid out that way and
#: for none that is not.
_PDK_SCRIPT_REL = "libs.tech/klayout/tech/scripts/sealring.py"
_BRIDGE_CFG = "input/pdk/bridge/signoff_config.json"
_BRIDGE_KEY = "die_finishing"
_CFG_GLOBS = (
    "signoff/die_finishing.json",
    "input/pdk/bridge/die_finishing.json",
)
_REPORT_REL = "reports/phase3/die_finishing.json"
#: The step's two declared marker artefacts. Exactly one is written, and
#: neither is written on a FAIL: a die that could not be finished must not
#: leave a "finished" artefact behind, and it was not skipped either.
_DEF_REL = "phase3/stage3/pnr/die_finished.def"
_SKIPPED_REL = "phase3/stage3/pnr/die_finishing.SKIPPED.txt"
#: The packaging value that makes die identification REQUIRED. Measured on the
#: operator's own `generate_id.py`: its whole four-cell block sits behind
#: `if cob:` and `--cob` is `action="store_true"`, default OFF.
_COB = "cob"
_ROUTED_DEF_GLOBS = ("phase3/stage3/pnr/routed.def",
                     "phase3/stage3/pnr/*.def")

#: The two invocation shapes LibreLane implements for PDK seal-ring scripts.
#: `pya-cli` is its `run_generic` default; `klayout-rd` is the KLayout-batch
#: form. Declared, never guessed: silently retrying the other shape when one
#: produces nothing is how a wrong invocation becomes a false PASS.
_FORMS = ("pya-cli", "klayout-rd")


def _first(project: Path, globs) -> Optional[Path]:
    for g in globs:
        hits = sorted(p for p in project.glob(g)
                      if p.is_file() and not p.name.endswith(".sealed.gds"))
        if hits:
            return hits[0]
    return None


def _skip(reason: str, marker: bool = False, **extra) -> Dict[str, Any]:
    """A disclosed skip, and WHETHER IT COUNTS AS THE STEP HAVING AN ANSWER.

    `marker=True` means "die finishing was considered and legitimately does not
    apply here" — the PDK ships no seal-ring generator. That is a DECIDED
    outcome and it earns `die_finishing.SKIPPED.txt`, the artefact the flow
    declares as the alternative to a finished die.

    `marker=False` (the default) means "the step could not run": no streamed
    GDS, no KLayout, no die size, unreachable paths. Those are absences of the
    step's own INPUTS or of the environment, and they must NOT leave a
    "skipped" marker behind, because the flow reads that marker as the step
    having produced one of its two declared outcomes.

    MEASURED, which is why this distinction exists at all: run against a
    published run tree carrying no `phase3/stage3/pnr` at all, the earlier
    version wrote `die_finishing.SKIPPED.txt` for "cannot determine the die
    size", and `flow_compliance_check` then reported Step 26.5ic as
    VACUOUS-PASS on a tree that never produced a die. An upstream failure had
    been converted into this step looking fine.
    """
    return {"state": "DISCLOSED_SKIP", "reason": reason, "marker": marker,
            **extra}


def _bridge(project: Path) -> Dict[str, Any]:
    """The project's declared seal-ring config, or {}."""
    bridge = project / _BRIDGE_CFG
    if bridge.is_file():
        try:
            declared = json.loads(bridge.read_text()).get(_BRIDGE_KEY)
        except (ValueError, OSError):
            declared = None
        if isinstance(declared, dict):
            return declared
    found = _first(project, _CFG_GLOBS)
    if found:
        try:
            got = json.loads(found.read_text())
        except (ValueError, OSError):
            return {}
        if isinstance(got, dict):
            return got
    return {}


#: Section 2C of the tape-out declaration, which is where a design that has no
#: shuttle operator writes down what an operator's template would otherwise
#: have pinned. `_tapeout_declaration.py` derived those three questions FROM
#: this program — its own note on `seal_ring_script` says "Read by
#: `die_finishing_gen`" — and until vibe-ic#1410/cpath nothing here read them
#: back. A design that had answered all three was driven as though it had
#: answered none.
#: Appended to a no-generator skip when the design DECLARED a ring is
#: required. Written once so both branches say the same thing.
_REQUIRED_AND_ABSENT = (
    ". THE DESIGN DECLARED THAT ONE IS REQUIRED: `seal_ring_required` is true "
    "in its tape-out declaration, so this is not a not-applicable — it is the "
    "step being unable to build a ring the design says it must have. No "
    "`die_finishing.SKIPPED.txt` is written and the step's declared outputs "
    "stay unsatisfied, which is what makes the flow report it")

_DECL_REQUIRED = "seal_ring_required"
_DECL_SCRIPT = "seal_ring_script"
_DECL_MARKER = "seal_ring_marker_layer"
_DECL_SOURCE = f"{_td.DECLARATION_REL}:answers"


def _declaration(project: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    """(the three section-2C answers, why-the-file-could-not-be-read).

    An ABSENT declaration is `({}, None)`: this program predates the
    declaration and must keep working on a tree that has none. A declaration
    that EXISTS and could not be parsed is `({}, why)` — the caller refuses on
    it rather than proceeding, because "I could not read it" and "I read it and
    it said nothing" must never produce the same verdict.

    Every value is passed through `_tapeout_declaration.answer`, so a field
    left `NOT_DETERMINED` comes back as the sentinel and never as a plausible
    default.
    """
    path = project / _td.DECLARATION_REL
    if not path.is_file():
        return {}, None
    doc, why = _td.load(path)
    if doc is None:
        return {}, why
    if not isinstance(doc, dict):
        return {}, f"{_td.DECLARATION_REL}: the top level is not a mapping"
    return {k: _td.answer(doc, k)
            for k in (_DECL_REQUIRED, _DECL_SCRIPT, _DECL_MARKER)}, None


def _declared(answers: Dict[str, Any], key: str) -> Optional[Any]:
    """The answer to `key`, or None when it is unanswered. Never a default."""
    v = answers.get(key)
    return v if _td.is_answered(v) else None


def resolve_script(project: Path, explicit: Optional[str],
                   pdk_root: Optional[str],
                   pdk: Optional[str],
                   declared: Optional[Dict[str, Any]] = None
                   ) -> Tuple[Optional[str], str, List[str]]:
    """(script, source, tried) — the PDK's seal-ring generator.

    Order, first hit wins, every step named in `tried` so an absence is a
    STATEMENT about specific locations rather than a shrug:
      1. `--script`
      2. the project's PDK-bridge declaration (`sealring.script`)
      3. the design's own tape-out declaration (`seal_ring_script`)
      4. `$KLAYOUT_SEALRING_SCRIPT` — LibreLane's own PDK variable
      5. `$PDK_ROOT/$PDK/` + the conventional script path

    STEP 3 IS THE NEW ONE and it sits THERE on purpose. The bridge config is
    the PDK integration's own answer and outranks the design's; the environment
    variable and the constructed conventional path are both weaker than
    something a human wrote down about THIS die, so the declaration outranks
    them. A shuttle design that answers nothing resolves exactly as it did
    before this step existed, because an unanswered field never returns a
    value.

    Existence is NOT checked here. The script lives wherever KLayout lives,
    which may be inside a container with no host counterpart, so only the
    resolved runner can answer that (see `KLayoutRunner.exists`).
    """
    tried: List[str] = []
    if explicit:
        return explicit, "--script", tried
    cfg = _bridge(project)
    tried.append(f"{_BRIDGE_CFG}:{_BRIDGE_KEY}.script")
    if isinstance(cfg.get("script"), str) and cfg["script"]:
        return cfg["script"], f"{_BRIDGE_CFG}:{_BRIDGE_KEY}.script", tried
    tried.append(f"{_DECL_SOURCE}.{_DECL_SCRIPT}")
    decl_script = _declared(declared or {}, _DECL_SCRIPT)
    if isinstance(decl_script, str) and decl_script.strip():
        return decl_script.strip(), f"{_DECL_SOURCE}.{_DECL_SCRIPT}", tried
    tried.append(f"${_ENV_SCRIPT}")
    env_script = os.environ.get(_ENV_SCRIPT)
    if env_script:
        return env_script, f"${_ENV_SCRIPT}", tried
    root = pdk_root or os.environ.get("PDK_ROOT")
    name = pdk or os.environ.get("PDK")
    if root and name:
        cand = f"{root.rstrip('/')}/{name}/{_PDK_SCRIPT_REL}"
        tried.append(cand)
        return cand, "$PDK_ROOT/$PDK/" + _PDK_SCRIPT_REL, tried
    tried.append("$PDK_ROOT/$PDK/" + _PDK_SCRIPT_REL
                 + " (PDK_ROOT/PDK not set)")
    return None, "", tried


def die_size(project: Path, gds: Path,
             width: Optional[float],
             height: Optional[float]) -> Tuple[Optional[float], Optional[float], str]:
    """(width_um, height_um, source).

    The floorplan's own DIEAREA is preferred over the GDS bounding box: the
    bbox is whatever geometry happens to reach furthest, which on a die with
    an outline marker or an overhanging label is not the die.
    """
    if width and height:
        return float(width), float(height), "--die-width/--die-height"
    for pat in ("phase3/stage3/pnr/routed.def", "phase3/stage3/pnr/*.def",
                "**/*.def"):
        for d in sorted(project.glob(pat)):
            if not d.is_file():
                continue
            try:
                text = d.read_text(errors="ignore")
            except OSError:
                continue
            m = re.search(r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*"
                          r"\(\s*(-?\d+)\s+(-?\d+)\s*\)", text)
            u = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", text)
            if not m:
                continue
            scale = float(u.group(1)) if u else 1000.0
            x0, y0, x1, y1 = (int(m.group(i)) for i in (1, 2, 3, 4))
            return ((x1 - x0) / scale, (y1 - y0) / scale,
                    f"DIEAREA of {d.relative_to(project)}")
    return None, None, "no DIEAREA found; caller must pass --die-width/--die-height"


#: What a `pya-cli` script DECLARES. LibreLane's generic caller passes
#: `--die-width`, so a script that accepts that option is one it can drive and a
#: script that does not is not. Reading the tool's own declared interface is the
#: discriminator here, rather than the PDK's NAME (which is what LibreLane
#: branches on): a name says nothing checkable about how a file wants to be
#: called, and a PDK that renames itself would silently change how it is driven.
#: MEASURED on the two PDK seal-ring scripts in this project's EDA image: the
#: option appears once in the pya-cli one and zero times in the KLayout-batch one.
_PYA_CLI_MARKER = "--die-width"


def _read_remote(runner, path: str, limit: int = 200) -> Optional[str]:
    """First `limit` lines of `path` IN THE RUNNER'S environment, or None."""
    rc, out, _ = runner.run_argv(["head", "-n", str(limit), str(path)], {},
                                timeout=120)
    return out if rc == 0 else None


def detect_form(runner, script: str) -> Tuple[str, str]:
    """(form, why) — how this PDK script wants to be invoked.

    Fails toward `klayout-rd` ONLY when the script was read and did not declare
    the CLI option; an UNREADABLE script keeps the documented default so a
    transient read failure cannot silently change the invocation.
    """
    text = _read_remote(runner, script)
    if text is None:
        return "pya-cli", ("could not read the script to detect its interface; "
                           "kept the default pya-cli form")
    if _PYA_CLI_MARKER in text:
        return "pya-cli", f"the script declares {_PYA_CLI_MARKER}"
    return "klayout-rd", (f"the script does not declare {_PYA_CLI_MARKER}, so it "
                          "is driven as a KLayout batch script")


def derive_tech(runner, script: str) -> Tuple[Optional[str], str]:
    """The PDK's KLayout technology name, from the PDK's OWN .lyt beside the
    script (`<pdk>/libs.tech/klayout/tech/*.lyt`), or (None, why).

    LibreLane computes this by string-editing the PDK name. Reading the
    technology file the PDK itself ships is the same answer from the authority
    that owns it, and it keeps working for a PDK whose name does not encode it.
    """
    techdir = str(Path(script).parent.parent)
    rc, out, _ = runner.run_argv(
        ["sh", "-c", f"ls {techdir}/*.lyt 2>/dev/null"], {}, timeout=60)
    lyts = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    if rc != 0 or not lyts:
        return None, f"no KLayout technology file (*.lyt) beside the script in {techdir}"
    if len(lyts) > 1:
        return None, ("the PDK ships more than one KLayout technology file "
                      f"({', '.join(Path(x).name for x in lyts)}); declare "
                      "--tech to say which one drives the seal ring")
    text = _read_remote(runner, lyts[0], limit=80) or ""
    m = re.search(r"<name>\s*([^<\s][^<]*?)\s*</name>", text)
    if not m:
        return None, f"{lyts[0]} declares no <name>"
    return m.group(1), f"<name> of {lyts[0]}"


def _emit_argv(form: str, runner, script: str, py: str, tech: Optional[str],
               gds_c: str, out_c: str, w: float, h: float) -> List[str]:
    """The PDK generator's command line, in the form LibreLane uses for it.

    `pya-cli` mirrors `KLayout.SealRing.run_generic`; `klayout-rd` mirrors
    `run_ihp_sg13g2`. The width/height ORDER of the second one is upstream's:
    it passes `width=DIE_AREA[3]` and `height=DIE_AREA[2]`, i.e. transposed
    against the first. That is reproduced rather than corrected — this program
    drives the PDK's script, and quietly disagreeing with the reference caller
    about its own arguments is not a fix, it is a second opinion nobody asked
    for. It is recorded in the report so a PDK integrator can see it.
    """
    if form == "klayout-rd":
        return [runner.klayout_bin(), "-zz", "-nc", "-n", str(tech),
                "-r", script,
                "-rd", f"width={h:f}", "-rd", f"height={w:f}",
                "-rd", f"input={gds_c}", "-rd", f"output={out_c}"]
    return [py, script,
            "--input", gds_c, "--output", out_c,
            "--die-width", f"{w:f}", "--die-height", f"{h:f}"]


# ── the finished-die DEF ────────────────────────────────────────────────────

_BLOCKAGE_TAG = "# vibe-ic die-finishing: seal-ring band (placement blockage)"


def _def_scale(text: str) -> float:
    m = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", text)
    return float(m.group(1)) if m else 1000.0


def seal_ring_bands(extent: Dict[str, Any]) -> Optional[List[List[float]]]:
    """The four micron rectangles the ring occupies, from its MEASURED outer
    and inner edges. Returns None when either edge was not measured — a band
    derived from a nominal ring width would be this program inventing the
    foundry data it is careful not to invent anywhere else."""
    try:
        ol, ob, orr, ot = extent["outer"]["um"]
        il, ib, ir, it = extent["inner"]["um"]
    except (KeyError, TypeError, ValueError):
        return None
    # STRICT on every side: a ring has a non-zero band on all four, and a
    # degenerate one would emit zero-area placement blockages into the finished
    # die — a DEF statement about nothing, which is worse than no statement.
    if not (ol < il < ir < orr and ob < ib < it < ot):
        return None
    return [[ol, ob, orr, ib],        # bottom
            [ol, it, orr, ot],        # top
            [ol, ib, il, it],         # left
            [ir, ib, orr, it]]        # right


def write_finished_def(routed: Path, out: Path,
                       extent: Dict[str, Any]) -> Tuple[bool, str]:
    """Carry the routed DEF forward as the FINISHED die, with the seal-ring
    band declared as a placement blockage.

    WHY A BLOCKAGE AND NOT A COPY. The ring itself is GDS geometry — the PDK's
    generator writes it into the layout, and a DEF cannot hold it. What the DEF
    CAN state truthfully is the consequence: a band of the die is now occupied
    by foundry structure and nothing may be placed in it. That is a real,
    machine-readable fact derived from the ring this run actually measured, and
    it is what a downstream ECO placement or fill pass needs to know. A DEF
    that were merely `routed.def` under a new name would be a stub claiming to
    be a finished die, which is the defect shape this step exists to remove.
    """
    bands = seal_ring_bands(extent)
    if bands is None:
        return False, ("the seal ring's inner/outer edges were not measured, "
                       "so the finished-die DEF cannot state the band honestly")
    try:
        text = routed.read_text(errors="ignore")
    except OSError as exc:
        return False, f"cannot read the routed DEF: {exc}"
    if "END DESIGN" not in text:
        return False, f"{routed.name} has no END DESIGN section"
    scale = _def_scale(text)
    rects = [f"    - PLACEMENT RECT ( {round(x0 * scale)} {round(y0 * scale)} ) "
             f"( {round(x1 * scale)} {round(y1 * scale)} ) ;"
             for x0, y0, x1, y1 in bands]

    m = re.search(r"^BLOCKAGES\s+(\d+)\s*;\s*$", text, re.M)
    if m:
        end = text.find("END BLOCKAGES", m.end())
        if end < 0:
            return False, "the routed DEF opens BLOCKAGES and never ends it"
        merged = (text[:m.start()]
                  + f"BLOCKAGES {int(m.group(1)) + len(rects)} ;\n"
                  + text[m.end():end].rstrip("\n") + "\n"
                  + _BLOCKAGE_TAG + "\n" + "\n".join(rects) + "\n"
                  + text[end:])
    else:
        at = text.index("END DESIGN")
        merged = (text[:at] + f"BLOCKAGES {len(rects)} ;\n" + _BLOCKAGE_TAG
                  + "\n" + "\n".join(rects) + "\nEND BLOCKAGES\n\n"
                  + text[at:])
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, merged)
    except OSError as exc:
        return False, f"cannot write the finished-die DEF: {exc}"
    return True, f"{len(rects)} seal-ring placement blockage(s)"


# ── the die-identification half ─────────────────────────────────────────────

def die_id_state(cfg: Dict[str, Any],
                 ring_check: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The die-identification half, reported SEPARATELY and CONDITIONALLY.

    THE CONDITION IS THE WHOLE POINT, and it was measured on the operator's own
    tool. In `generate_id.py` the entire four-cell requirement sits behind
    `if cob:`, and `--cob` is `action="store_true"` — default OFF. So:

      * a CHIP-ON-BOARD submission is hard-blocked without the four cells;
      * a non-CoB submission passes the shuttle's precheck with none of them,
        and the operator's own script is a silent no-op on it.

    An UNCONDITIONAL gate here would therefore refuse correct non-CoB designs,
    and a gate that ignored the condition would credit a CoB design missing all
    four. Both are wrong, and the difference is a DECLARED INPUT — the
    packaging choice — which this flow does not yet carry anywhere. So the
    report always says WHICH CASE IT WAS IN:

      packaging = CoB, cells all present once   -> PRESENT
      packaging = CoB, any missing or duplicated-> ABSENT   (a real FAIL)
      packaging = CoB, no cell list declared    -> NOT_DETERMINED
      packaging declared and not CoB            -> NOT_APPLICABLE
      packaging not declared                    -> NOT_DETERMINED

    NOT_APPLICABLE and NOT_DETERMINED are deliberately neither PASS nor FAIL,
    and NEITHER may take a verified seal ring down with it. The cells
    themselves are the operator's, shipped pre-built by its project template —
    not the PDK's, not LibreLane's, and not this repository's to generate — so
    the cell list stays a declared input and nothing here invents one.
    """
    declared = cfg.get("die_id") if isinstance(cfg.get("die_id"), dict) else {}
    packaging = declared.get("packaging")
    cells = [c for c in (declared.get("cells") or []) if isinstance(c, str)]
    base = {"packaging": packaging, "cells": cells}

    if not isinstance(packaging, str) or not packaging.strip():
        return {**base, "state": "NOT_DETERMINED", "reason": (
            "the packaging choice is not declared, and the die-identification "
            "requirement is CONDITIONAL on it: the operator's own generate_id "
            "places its four cells only for a chip-on-board submission and is "
            "a silent no-op otherwise. Declare "
            "die_finishing.die_id.packaging in the PDK-bridge config "
            f"({_COB!r} for chip-on-board) to settle this half. It does not "
            "gate the seal ring.")}

    if packaging.strip().lower().replace("-", "_") != _COB:
        return {**base, "state": "NOT_APPLICABLE", "reason": (
            f"packaging is declared {packaging!r}, not {_COB!r}: the shuttle's "
            "die-identification cells are required only for a chip-on-board "
            "submission, so this half does not apply to this design. This is "
            "not a pass by silence — the condition was read and it did not "
            "hold.")}

    if not cells:
        return {**base, "state": "NOT_DETERMINED", "reason": (
            "packaging is chip-on-board, so die-identification cells ARE "
            "required — but which cells is the operator's declaration, not "
            "this flow's, and none is declared "
            "(die_finishing.die_id.cells). The requirement is known; the list "
            "is not.")}

    seen = (ring_check or {}).get("id_cells")
    if not isinstance(seen, dict):
        return {**base, "state": "NOT_DETERMINED", "reason": (
            "the layout was not inspected for the declared die-identification "
            "cells (no ring verification ran)")}
    missing = sorted(n for n in cells if not seen.get(n))
    # The operator's own script asserts `len(cell_insts) == 1` per cell, so a
    # cell instantiated twice is its failure too, not a detail.
    duplicated = sorted(n for n in cells
                        if isinstance(seen.get(n), int) and seen[n] > 1)
    if missing or duplicated:
        why = []
        if missing:
            why.append("absent: " + ", ".join(missing))
        if duplicated:
            why.append("instantiated more than once: " + ", ".join(duplicated))
        return {**base, "state": "ABSENT", "missing": missing,
                "duplicated": duplicated, "instances": dict(seen),
                "reason": ("this is a chip-on-board submission, so the "
                           "shuttle's die-identification cells are required, "
                           "and " + "; ".join(why))}
    return {**base, "state": "PRESENT", "instances": dict(seen),
            "reason": ("chip-on-board: every declared die-identification cell "
                       "is instantiated exactly once")}


# ── the run ─────────────────────────────────────────────────────────────────

def run(project: Path, gds: Optional[str], script: Optional[str],
        form: Optional[str], tech: Optional[str], pdk_root: Optional[str],
        pdk: Optional[str], python: str, marker: Optional[str],
        width: Optional[float], height: Optional[float],
        out: Optional[str], in_place: bool,
        report: Optional[str]) -> Dict[str, Any]:
    rep = Path(report) if report else (project / _REPORT_REL)
    if not rep.is_absolute():
        rep = project / rep
    cfg = _bridge(project)
    fin_def = project / _DEF_REL
    skip_marker = project / _SKIPPED_REL

    def done(seal: Dict[str, Any],
             ring_check: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Persist EVERY outcome, and write the ONE marker artefact that is
        true of it.

        Skips included: a skip that wrote nothing would reach the step gate as
        a generic "die_finishing_gen has not run on this project", losing the
        one thing a reader needs, which is WHY. A PDK that ships no generator
        and a run that never reached stream-out are different facts and must
        not arrive wearing the same sentence.

        NEITHER marker is written on a FAIL. A die that could not be finished
        must not leave a `die_finished.def` behind, and it was not skipped
        either — so the step's `required_outputs` stay unsatisfied and the
        flow reports it, which is the correct answer.
        """
        res: Dict[str, Any] = {"producer": _PRODUCER, "check": _CHECK,
                               "seal_ring": seal,
                               "die_id": die_id_state(cfg, ring_check)}
        state = seal.get("state")
        for stale in (fin_def, skip_marker):
            if stale.is_file():
                stale.unlink()
        artefacts: Dict[str, Any] = {}
        if state == "DISCLOSED_SKIP" and seal.get("marker"):
            try:
                skip_marker.parent.mkdir(parents=True, exist_ok=True)
                skip_marker.write_text(
                    "Die finishing did not run on this project.\n\n"
                    f"seal ring: {seal.get('reason')}\n"
                    f"die id:    {res['die_id'].get('reason')}\n")
                artefacts["skipped_marker"] = str(skip_marker)
            except OSError as exc:
                artefacts["skipped_marker_unwritable"] = str(exc)
        elif state == "PASS":
            routed = _first(project, _ROUTED_DEF_GLOBS)
            extent = (ring_check or {}).get("ring_extent") or {}
            if routed is None:
                seal["state"] = state = "FAIL"
                seal["reason"] = (
                    "the seal ring verified, but there is no routed DEF to "
                    "carry forward as the finished die (looked for "
                    + ", ".join(_ROUTED_DEF_GLOBS) + ")")
            else:
                ok, why = write_finished_def(routed, fin_def, extent)
                if ok:
                    artefacts["finished_def"] = str(fin_def)
                    artefacts["finished_def_note"] = why
                    artefacts["routed_def_in"] = str(routed)
                else:
                    seal["state"] = state = "FAIL"
                    seal["reason"] = why
        res["artefacts"] = artefacts
        try:
            rep.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(rep, res)
        except OSError as exc:                               # noqa: BLE001
            res.setdefault("report_unwritable", str(exc))
        return res

    declared_form = form or cfg.get("form")
    if declared_form and declared_form not in _FORMS:
        return done({"state": "FAIL",
                     "reason": f"unknown invocation form {declared_form!r} "
                               f"(known: {', '.join(_FORMS)})"})

    # ── SECTION 2C OF THE TAPE-OUT DECLARATION ────────────────────────────
    # Read BEFORE anything is resolved, because one of its answers can decide
    # the whole step and another changes what a skip is allowed to claim.
    decl, decl_why = _declaration(project)
    if decl_why:
        # The file EXISTS and could not be read. Not a skip: the three answers
        # are UNKNOWN rather than absent, and a step that cannot see its input
        # must say so rather than report a clean not-applicable.
        return done({"state": "FAIL",
                     "reason": f"the tape-out declaration exists and could "
                               f"not be read, so section "
                               f"{_td.SECTION_SEAL_RING} is unknown rather "
                               f"than unanswered: {decl_why}"})
    seal_required = _declared(decl, _DECL_REQUIRED)
    answered_2c = [k for k in (_DECL_REQUIRED, _DECL_SCRIPT, _DECL_MARKER)
                   if _declared(decl, k) is not None]
    if answered_2c and seal_required is None:
        # SOMEBODY WAS ASKED AND DID NOT ANSWER THE ONE QUESTION THE OTHER TWO
        # HANG OFF. "Is there a seal ring" is not a property of the layout —
        # `_tapeout_declaration.py` opens by saying so: it is "required by
        # whom?", and this field is the whom. A script or a marker layer
        # answered while this is left NOT_DETERMINED is a declaration that was
        # started and abandoned, which must not buy the exit code of a
        # declaration nobody was ever handed.
        return done({"state": "FAIL",
                     "reason": f"declaration section {_td.SECTION_SEAL_RING} "
                               f"was STARTED ({', '.join(sorted(answered_2c))} "
                               f"answered) and leaves {_DECL_REQUIRED!r} "
                               f"{_td.NOT_DETERMINED}. Nothing here decides "
                               f"for the design whether the party that takes "
                               f"this layout requires a ring; answer "
                               f"{_DECL_REQUIRED!r} in "
                               f"{_td.DECLARATION_REL}",
                     "declaration": dict(decl)})
    if seal_required is False:
        # A DECIDED OUTCOME, and the only source that can decide it is the
        # design. `marker=True`: this earns `die_finishing.SKIPPED.txt`, the
        # artefact the flow declares as the alternative to a finished die,
        # exactly as "this PDK ships no generator" does.
        return done(_skip(
            f"the design's own tape-out declaration answers "
            f"{_DECL_REQUIRED}=false in {_td.DECLARATION_REL}: the party that "
            f"takes this layout does not require a seal ring, so none is "
            f"inserted and none is claimed. This is a DECLARED "
            f"not-applicable, not an absence of evidence",
            marker=True, declaration=dict(decl)))

    tech = tech or cfg.get("tech")
    marker = marker or cfg.get("marker_layer") or _declared(decl, _DECL_MARKER)
    id_cells = [c for c in
                ((cfg.get("die_id") or {}).get("cells") or [])
                if isinstance(c, str)]

    script, src, tried = resolve_script(project, script, pdk_root, pdk, decl)
    if not script:
        # LibreLane's own wording for this case names the PDK and says the step
        # is skipped: "KLAYOUT_SEALRING_SCRIPT is unset. KLayout.SealRing may
        # not be supported for the {PDK} PDK. This step will be skipped."
        # Same shape, plus the list of locations searched, because "unset" is
        # only checkable if the reader is told where it was looked for.
        named = pdk or os.environ.get("PDK") or "this PDK"
        return done(_skip(
            f"no seal-ring generator is declared for the {named} PDK — die "
            "finishing may not be supported for it, so this step is SKIPPED "
            "and no ring is claimed (looked for: " + "; ".join(tried) + ")"
            + (_REQUIRED_AND_ABSENT if seal_required else ""),
            # THE MARKER TURNS ON WHAT THE DESIGN DECLARED, and this is the
            # `_skip` docstring's own distinction applied to a fact it could
            # not previously see. "This PDK ships no generator" is a legitimate
            # not-applicable ONLY while nobody has said a ring is required. A
            # design that answered `seal_ring_required=true` and got no ring is
            # the OTHER case — the step could not run — and must not leave
            # `die_finishing.SKIPPED.txt` behind, because the flow reads that
            # marker as the step having produced one of its two declared
            # outcomes and the die would ship unsealed against its own
            # declaration.
            marker=not seal_required, pdk=named, tried=tried,
            seal_ring_required=seal_required))

    gds_path = Path(gds) if gds else _first(project, _GDS_GLOBS)
    if gds_path is not None and not gds_path.is_absolute():
        gds_path = project / gds_path
    if gds_path is None or not gds_path.is_file():
        return done(_skip(
            "no streamed GDS to seal (looked for " + ", ".join(_GDS_GLOBS) + ")",
            script=script, script_source=src))

    runner = _kl.find_runner()
    if runner is None:
        return done(_skip(
            "no KLayout runner available (no strmrun/klayout on PATH and no "
            "KLayout in $VIBEIC_EDA_CONTAINER) — no seal ring was inserted",
            script=script, script_source=src))

    if not runner.exists(script):
        # WORDING IS LOAD-BEARING, and it turns on WHO named the path. A path
        # the PDK/project DECLARED and that is not there is a broken
        # declaration; the conventional `$PDK_ROOT/$PDK/...` path is one this
        # program constructed, and its absence means only that this PDK ships
        # no KLayout seal-ring generator. Measured on a real PDK: sky130A ships
        # the magic-based generator and no klayout one, and its LibreLane
        # config.tcl leaves KLAYOUT_SEALRING_SCRIPT commented out — the PDK
        # agrees. Saying "this PDK declares a generator ... but no such file
        # exists" about it would be this program mis-attributing its own guess.
        constructed = src.startswith("$PDK_ROOT/$PDK/")
        named = pdk or os.environ.get("PDK") or "this PDK"
        return done(_skip(
            (f"no seal-ring generator for the {named} PDK: nothing at the "
             f"conventional {script} in the {runner.kind} environment "
             f"({runner.detail}). Die finishing may not be supported for "
             f"{named}; this step is SKIPPED and no ring is claimed"
             if constructed else
             f"the seal-ring generator declared by {src} ({script}) does not "
             f"exist in the {runner.kind} environment ({runner.detail}) — "
             f"die finishing is SKIPPED for the {named} PDK and no ring is "
             "claimed")
            + (_REQUIRED_AND_ABSENT if seal_required else ""),
            # Same rule as the branch above: a declared-required ring that was
            # not built is the step failing to run, never a not-applicable.
            marker=not seal_required, pdk=named, script=script,
            script_source=src, tried=tried,
            seal_ring_required=seal_required))

    if declared_form:
        form, form_why = declared_form, "declared"
    else:
        form, form_why = detect_form(runner, script)
    tech_why = "declared" if tech else "not needed for this form"
    if form == "klayout-rd" and not tech:
        tech, tech_why = derive_tech(runner, script)
        if not tech:
            return done(_skip(
                "invocation form 'klayout-rd' needs the PDK's KLayout "
                f"technology name and none could be established: {tech_why} "
                f"(declare --tech or {_BRIDGE_CFG}:{_BRIDGE_KEY}.tech)",
                script=script, script_source=src, form=form,
                form_source=form_why))

    w, h, die_src = die_size(project, gds_path, width, height)
    if not w or not h:
        return done(_skip(f"cannot determine the die size: {die_src}",
                          script=script, script_source=src))

    engine = _kl.find_engine("sealring", "sealring_verify.py")
    if engine is None:
        return done({"state": "FAIL",
                     "reason": "sealring/sealring_verify.py engine not found"})

    rep.parent.mkdir(parents=True, exist_ok=True)
    if in_place:
        dest = gds_path
        staged = gds_path.with_suffix(".sealed.gds")
    else:
        dest = (Path(out) if out else gds_path.with_suffix(".sealed.gds"))
        if not dest.is_absolute():
            dest = project / dest
        staged = dest

    # Same materialisation the density-fill emitter does, for the same measured
    # reason: the engine resolves to a path under the plugin's OWN install,
    # which a per-run container mounts only if the caller happened to bind-mount
    # the plugin tree too. Copying the self-contained batch script beside the
    # report makes the SAME container that already runs DRC/LVS able to run it.
    if not runner.covers(engine):
        materialised = rep.parent / Path(engine).name
        atomic_write_text(materialised, Path(engine).read_text())
        engine = materialised
    for label, pth in (("GDS", gds_path), ("engine", engine),
                       ("output", staged.parent), ("report dir", rep.parent)):
        if not runner.covers(pth):
            return done(_skip(
                f"{label} path is not reachable by the KLayout runner "
                f"({runner.kind}: {runner.detail}): {pth}",
                script=script, script_source=src))

    seal: Dict[str, Any] = {
        "script": script, "script_source": src,
        "form": form, "form_source": form_why,
        "die_um": [w, h], "die_source": die_src,
        "runner": f"{runner.kind}:{runner.detail}", "gds_in": str(gds_path),
    }
    if form == "klayout-rd":
        seal["tech"] = tech
        seal["tech_source"] = tech_why
        seal["upstream_arg_transposition"] = (
            "width=<height>, height=<width> — reproduced from LibreLane "
            "KLayout.SealRing.run_ihp_sg13g2")

    if staged.is_file():
        staged.unlink()
    env = {}
    _root = pdk_root or os.environ.get("PDK_ROOT")
    _name = pdk or os.environ.get("PDK")
    for k, v in (("PDK_ROOT", _root), ("PDK", _name)):
        if v:
            env[k] = str(v)
    if form == "klayout-rd":
        # MIRRORS LibreLane `KLayout.SealRing.run_ihp_sg13g2`, which sets
        # KLAYOUT_PATH "so that KLayout can load the technology definition"
        # (klayout.py, in the 895+ block). It is set ONLY on this form, exactly
        # as upstream sets it only on that path — a batch script driven with
        # `-n <tech>` needs the technology search path; a `python3 <script>`
        # CLI does not, and adding it there would be a silent deviation from
        # the reference caller rather than a fix.
        kp = (f"{str(_root).rstrip('/')}/{_name}/libs.tech/klayout"
              if _root and _name
              else str(Path(script).parent.parent.parent))
        env["KLAYOUT_PATH"] = kp
        seal["klayout_path"] = kp
    argv = _emit_argv(form, runner, script, python, tech,
                      runner.cpath(gds_path), runner.cpath(staged), w, h)
    seal["argv"] = list(argv)
    rc, sout, serr = runner.run_argv(argv, env, timeout=3600)
    seal["generator_rc"] = rc
    tail = ((sout or "") + (serr or "")).strip()
    if tail:
        seal["generator_output"] = tail[-1200:]

    # THE EXIT CODE IS NOT THE VERDICT. Measured: a PDK script whose PCell
    # library is missing prints an error, calls `sys.exit()` with no argument
    # (so it exits 0) and writes nothing. The layouts are therefore diffed
    # whatever `rc` said, and rc is carried as evidence beside the measurement.
    if not staged.is_file():
        seal["state"] = "FAIL"
        seal["reason"] = (
            f"the PDK seal-ring generator ({script}) produced no output layout "
            f"at {staged} — it exited {rc}"
            + (f" and said: {_last_said(tail)}" if tail else "")
            + ". No ring was added; the die is unsealed.")
        return done(seal)

    vrep = rep.parent / "sealring_verify.json"
    venv = {"SEAL_IN": str(gds_path), "SEAL_OUT": str(staged),
            "SEAL_REPORT": str(vrep)}
    if marker:
        venv["SEAL_MARKER"] = str(marker)
    if id_cells:
        venv["SEAL_ID_CELLS"] = ",".join(id_cells)
    if vrep.is_file():
        vrep.unlink()
    vrc, vout, verr = runner.run(
        engine, venv, path_keys=("SEAL_IN", "SEAL_OUT", "SEAL_REPORT"),
        timeout=1800)
    if not vrep.is_file():
        seal["state"] = "FAIL"
        seal["reason"] = ("the seal-ring verifier produced no report "
                          f"(rc={vrc}) — the ring is unverified, so it is not "
                          "claimed")
        seal["verify_output"] = ((vout or "") + (verr or "")).strip()[-800:]
        return done(seal)
    try:
        ring_check = json.loads(vrep.read_text())
    except (ValueError, OSError) as exc:
        seal["state"] = "FAIL"
        seal["reason"] = f"seal-ring verifier report unreadable: {exc}"
        return done(seal)
    seal["ring_check"] = ring_check
    # The engine's raw report is now EMBEDDED above, so the scratch copy is
    # removed rather than left in `reports/` as a produced artefact no step
    # declares. An undeclared artefact is a thing nothing verifies and nothing
    # owns, which is the defect class this repository spends most of its gates
    # on; leaving one behind while adding a step would be careless.
    try:
        vrep.unlink()
    except OSError:
        pass

    if ring_check.get("verdict") == "PASS":
        # PROMOTE ONLY A VERIFIED RING. An unverified sealed layout is never
        # swapped in: the sign-off DRC/LVS would then be measuring geometry
        # nothing has confirmed is a seal ring.
        if in_place:
            staged.replace(dest)
        seal["gds_out"] = str(dest)
        seal["state"] = "PASS"
    else:
        seal["state"] = "FAIL"
        seal["reason"] = ring_check.get(
            "reason", "the generated layout does not carry a seal ring")
        seal["gds_out_unpromoted"] = str(staged)
    return done(seal, ring_check)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Step 26.5ic producer — run the PDK's own seal-ring "
                    "generator on the streamed GDS, verify the ring it "
                    "produced, and record the die-identification half's state.")
    ap.add_argument("project_dir", nargs="?", default=".")
    ap.add_argument("--gds", default=None)
    ap.add_argument("--script", default=None,
                    help="the PDK's seal-ring generator (default: resolved "
                         "from the PDK bridge config, $KLAYOUT_SEALRING_SCRIPT "
                         "or $PDK_ROOT/$PDK)")
    ap.add_argument("--form", default=None, choices=list(_FORMS),
                    help="invocation shape (default: read off the script)")
    ap.add_argument("--tech", default=None,
                    help="KLayout technology name (klayout-rd form only)")
    ap.add_argument("--pdk-root", default=None)
    ap.add_argument("--pdk", default=None)
    ap.add_argument("--python", default="python3")
    ap.add_argument("--marker", default=None,
                    help="'layer/datatype' of the PDK's guard-ring marker "
                         "layer; when given it must carry geometry")
    ap.add_argument("--die-width", type=float, default=None)
    ap.add_argument("--die-height", type=float, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--in-place", action="store_true",
                    help="replace the streamed GDS with the sealed layout")
    ap.add_argument("--report", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="treat a disclosed skip as a FAIL (tapeout sign-off)")
    ns = ap.parse_args(argv)

    project = Path(ns.project_dir).resolve()
    try:
        res = run(project, ns.gds, ns.script, ns.form, ns.tech, ns.pdk_root,
                  ns.pdk, ns.python, ns.marker, ns.die_width, ns.die_height,
                  ns.out, ns.in_place, ns.report)
    except Exception as exc:                                 # noqa: BLE001
        res = {"producer": _PRODUCER, "check": _CHECK,
               "seal_ring": {"state": "FAIL", "reason": f"gate error: {exc}"},
               "die_id": {"state": "NOT_DETERMINED",
                          "reason": "the run did not complete"}}

    if ns.json_out:
        o = Path(ns.json_out)
        if not o.is_absolute():
            o = project / o
        o.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(o, res)

    print(json.dumps(res, indent=2))
    state = (res.get("seal_ring") or {}).get("state")
    if state == "DISCLOSED_SKIP" and ns.strict:
        print(f"die_finishing_gen: FAIL — --strict: "
              f"{(res.get('seal_ring') or {}).get('reason')}")
        return FAIL
    if state == "DISCLOSED_SKIP":
        print("VACUOUS_PASS: no seal ring was inserted — "
              f"{(res.get('seal_ring') or {}).get('reason')}")
        return SKIP
    if state == "PASS":
        return PASS
    print("die_finishing_gen: FAIL — "
          f"{(res.get('seal_ring') or {}).get('reason')}")
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
