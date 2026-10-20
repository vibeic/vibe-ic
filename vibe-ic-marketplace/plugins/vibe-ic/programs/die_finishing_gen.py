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
         --die-width <X span> --die-height <Y span>` with PDK_ROOT and PDK in
         the environment. Four flags; that is the whole contract, and this
         program uses it unchanged. (To vibeic-eda 0.3.79 upstream passed
         DIE_AREA[2]/[3], the far corner, equal to the spans only for a die at
         the origin; from 0.3.83 it passes x1-x0 / y1-y0, which `die_size`
         here always computed.)
  NOT TAKEN (reported) upstream's corner move. From 0.3.83, for a die NOT at
         the origin upstream moves what the script drew to DIE_AREA's
         lower-left (`place_sealring.py`; `offset_x/offset_y` on its second
         path). This program does not: the script draws from (0,0). Every
         DIEAREA in the published corpus is at (0,0) (3 of 3, measured
         2026-09-28), so it has not been exercised, and the ring verifier is
         what would see a ring drawn off the die.
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

WHEN IT DOES NOT RUN AT ALL. A seal ring is a DIE structure, and so is the
die-level marker layer the generator draws it under. When the design's own
declaration answers `deliverable=HARDMACRO` this step is SKIPPED BY THAT
DECLARATION, recorded and named — the parent die the macro is placed in owns
its ring and its markers. See `_hardmacro_skip` for the measurement that made
this explicit (vibe-ic#2112).

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

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import hashlib
import json
import math
import os
import re
import sys
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _atomic_artefact import write_json as atomic_write_json  # vibe-ic#1082
from _atomic_artefact import write_text as atomic_write_text
from _atomic_artefact import write_text as _atomic_write_text

try:
    from . import _klayout_launch as _kl                     # type: ignore
    from . import _seal_ring_margin as _srm                  # type: ignore
    from . import _tapeout_declaration as _td                # type: ignore
except ImportError:                                          # standalone gate
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _klayout_launch as _kl                            # type: ignore
    import _seal_ring_margin as _srm                         # type: ignore
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
#: WHAT THIS MODULE MIRRORS FROM UPSTREAM, AND WHAT PINS IT THERE
#:
#: The header above says the seal-ring INTERFACE is taken from upstream
#: unchanged — four flags, and a named skip on the same unset variable. That is
#: a contract with a tool this module does not own, and a contract stated only
#: in prose is one nothing re-reads.
UPSTREAM_MIRROR: Dict[str, str] = {
    "upstream": "librelane/steps/klayout.py",
    "mirrors": (
        "the seal-ring generator contract: the four-flag command line, the "
        "PDK-scoped script variable whose absence is a named skip, and the "
        "second code path that additionally exports the tool search path so "
        "the technology definition loads."),
    "pinned_by": (
        "tests/test_upstream_mirror_klayout_sealring.py"
        "::test_upstream_sealring_contract_is_the_one_this_module_drives"),
}


_ENV_SCRIPT = "KLAYOUT_SEALRING_SCRIPT"
#: The path every PDK config.tcl that declares the variable actually builds:
#: `$PDK_ROOT/$PDK/libs.tech/klayout/tech/scripts/sealring.py`. This is PDK
#: STRUCTURE, not a PDK name — it resolves for any PDK laid out that way and
#: for none that is not.
_PDK_SCRIPT_REL = "libs.tech/klayout/tech/scripts/sealring.py"
_MAGIC_PROVIDER_GLOB = "libs.tech/magic/seal_ring_generator/*seal*ring*.py"
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
_FORMS = ("pya-cli", "klayout-rd", "magic-positional")


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


#: SECTION 2C OF THE TAPE-OUT DECLARATION — where a design that has no shuttle
#: operator writes down what an operator's template would otherwise have
#: pinned. `_tapeout_declaration.py` derived these three questions FROM this
#: program — its own note on `seal_ring_script` says "Read by
#: `die_finishing_gen`" — and until vibe-ic#1410/cpath nothing here read them
#: back. A design that had answered all three was driven as though it had
#: answered none.
_DECL_REQUIRED = "seal_ring_required"
_DECL_SCRIPT = "seal_ring_script"
_DECL_MARKER = "seal_ring_marker_layer"
#: Section 2A, and the ONE question outside 2C this program reads. See
#: `die_size` for why it is the LAST source there and not the first.
_DECL_DIE_AREA = "die_area_um"
#: Section 2A's FIRST question — "is what leaves this flow a DIE that will be
#: fabricated, or a HARDMACRO that somebody else will place?" — and the one
#: that decides whether section 2C is a question this delivery owes an answer
#: to at all. See `_hardmacro_skip`.
_DECL_DELIVERABLE = "deliverable"
_DECL_SOURCE = f"{_td.DECLARATION_REL}:answers"

#: Appended to a no-generator skip when the design DECLARED a ring is
#: required. Written once so both branches say the same thing.
_REQUIRED_AND_ABSENT = (
    ". THE DESIGN DECLARED THAT ONE IS REQUIRED: `seal_ring_required` is true "
    "in its tape-out declaration, so this is not a not-applicable — it is the "
    "step being unable to build a ring the design says it must have. No "
    "`die_finishing.SKIPPED.txt` is written and the step's declared outputs "
    "stay unsatisfied, which is what makes the flow report it")


def _declaration(project: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    """(the answers this program reads, why-the-file-could-not-be-read).

    FIVE keys, not three: section 2C's whole set, plus TWO from section 2A —
    `die_area_um` (see `die_size` for why that one is read here and why it is
    the LAST source when it is) and `deliverable`, which decides whether
    section 2C applies to this delivery at all (see `_hardmacro_skip`).

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
            for k in (_DECL_REQUIRED, _DECL_SCRIPT, _DECL_MARKER,
                      _DECL_DIE_AREA, _DECL_DELIVERABLE)}, None


def _declared(answers: Dict[str, Any], key: str) -> Optional[Any]:
    """The answer to `key`, or None when it is unanswered. Never a default."""
    v = answers.get(key)
    return v if _td.is_answered(v) else None


#: Recorded on the hardmacro skip so a reader can tell WHICH question this
#: step declined, not merely that it declined one.
SKIPPED_BY_DELIVERABLE = "SKIPPED_BY_DECLARATION:deliverable"


def _hardmacro_skip(decl: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The skip a HARDMACRO delivery earns, or None when this is a die.

    A SEAL RING IS A DIE STRUCTURE, and so is the die-level marker layer the
    generator draws it under. A hardmacro is delivered INTO somebody else's
    die; that parent die owns its ring and its die-level markers, and a macro
    that carries its own is carrying a second one into a die that already has
    one. The declaration's own schema says exactly this and has since it was
    written: every question of section 2C is declared
    `required_for=(DELIVERABLE_DIE,)`, so on a hardmacro `seal_ring_required`
    is NOT_APPLICABLE rather than unanswered — and until vibe-ic#2112 nothing
    on this side read `deliverable` back.

    MEASURED, vibe-ic#2112, on a front-door run of a design whose own step
    0.5ic had ALREADY said "it is delivered, not fabricated ... needs no pad
    ring, seal ring or submission check": the ring was built into the shipped
    GDS anyway and brought a die-sized guard-ring marker with it, so the
    sign-off deck evaluated the whole routed design as guard-ring metal —
    GR.4 1,299,340 + GR.2 24,652 + GR.6 1,022 of 1,359,528 violations, 97.5%
    of the sign-off DRC total, against a layout whose own contribution is
    34,514.

    `marker=True`: this is `_skip`'s "considered and legitimately does not
    apply", the same class as "this PDK ships no generator", so it earns
    `die_finishing.SKIPPED.txt`.

    AN ANSWERED `seal_ring_required` DOES NOT SILENCE THIS AND DOES NOT
    OVERRIDE IT. `deliverable` is the stronger fact — `_tapeout_declaration`
    routes the whole delivery off it — and 2C is inapplicable to a hardmacro
    by that same module's schema. So the answer is CARRIED into the skip,
    named, in `seal_ring_required_not_applicable`, rather than either obeyed
    or dropped: a reader who wrote `true` there sees that it was read, and
    sees why a hardmacro still ships no die ring.
    """
    delivery = _declared(decl, _DECL_DELIVERABLE)
    if delivery != _td.DELIVERABLE_HARDMACRO:
        return None
    required = _declared(decl, _DECL_REQUIRED)
    extra: Dict[str, Any] = {"deliverable": delivery,
                             "skipped_by": SKIPPED_BY_DELIVERABLE,
                             "declaration": dict(decl)}
    tail = ""
    if required is not None:
        extra["seal_ring_required_not_applicable"] = required
        tail = (f". The declaration also answers {_DECL_REQUIRED}={required!r}"
                f", which is a question section {_td.SECTION_SEAL_RING} asks "
                f"only of a {_td.DELIVERABLE_DIE} "
                f"(`required_for=({_td.DELIVERABLE_DIE},)` in "
                f"`_tapeout_declaration.QUESTIONS`); it is read and reported "
                f"here, and it does not make a macro into a die")
    return _skip(
        f"the design's own tape-out declaration answers "
        f"{_DECL_DELIVERABLE}={_td.DELIVERABLE_HARDMACRO} in "
        f"{_td.DECLARATION_REL}: what leaves this flow is a macro somebody "
        f"else places, not a die that will be fabricated. A seal ring and the "
        f"die-level marker layer it is drawn under belong to the PARENT die, "
        f"which owns them; a hardmacro that carries its own would carry a "
        f"second ring into a die that already has one, and its die-sized "
        f"marker would put the whole delivery inside the die-level rules of "
        f"the sign-off deck. So no ring is inserted and none is claimed — a "
        f"DECLARED not-applicable, not an absence of evidence" + tail,
        marker=True, **extra)


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
      3. the design's own tape-out declaration (`seal_ring_script`) — taken as
         given when absolute, and otherwise ALSO tried joined to
         `$PDK_ROOT/$PDK`, because a declared script path is normally relative
         to the PDK root (that is how it appears in the PDK tree). `source`
         records which of the two forms hit.
      4. `$KLAYOUT_SEALRING_SCRIPT` — LibreLane's own PDK variable
      5. `$PDK_ROOT/$PDK/` + the conventional script path

    STEP 3 IS THE NEW ONE and it sits THERE on purpose. The bridge config is
    the PDK integration's own answer and outranks the design's; the environment
    variable and the constructed conventional path are both weaker than
    something a human wrote down about THIS die, so the declaration outranks
    them. A shuttle design that answers nothing resolves exactly as it did
    before this step existed, because an unanswered field never returns a
    value.

    Explicit selections are not checked here: the resolved runner owns their
    existence. Default provider-family discovery asks the PDK authority reader
    in that same selected environment; it never substitutes a host PDK for an
    unreachable container.
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
        decl_script = decl_script.strip()
        # A DECLARED SCRIPT PATH IS USUALLY RELATIVE TO THE PDK ROOT, because
        # that is how it appears in the PDK tree and it is the only form that is
        # a fact about the DIE rather than about one machine's filesystem:
        #     seal_ring_script: libs.tech/klayout/tech/scripts/sealring.py
        # Returning it verbatim made exactly that form unresolvable, and because
        # this step OUTRANKS the $PDK_ROOT/$PDK probe below, answering the field
        # correctly was worse than leaving it blank. MEASURED, same project,
        # same declaration, same layout, only the program version differing:
        #     4-step resolver (no declaration step)  -> rc 0, seal PASS
        #     5-step resolver, field answered        -> rc 2, DISCLOSED_SKIP
        #     5-step resolver, field UNANSWERED      -> rc 0, seal PASS
        # So try the declared value AS GIVEN first — an operator who wrote an
        # absolute path meant it — and only then joined to the PDK root, saying
        # in `source` which form actually hit. Existence is still decided by the
        # runner, not here, so a declared script that resolves in NEITHER form
        # still reaches the same DISCLOSED_SKIP it does today: this widens which
        # spellings can be FOUND, never what counts as found.
        _decl_src = f"{_DECL_SOURCE}.{_DECL_SCRIPT}"
        if os.path.isabs(decl_script):
            return decl_script, _decl_src, tried
        # THE DESIGN'S OWN PDK, NEVER THE CONTAINER'S (G17/C9).
        #
        # This used to read `pdk_root or os.environ.get("PDK_ROOT")` and
        # `pdk or os.environ.get("PDK")`. When a caller supplied neither, the
        # DECLARATION was silently joined against whatever PDK the execution
        # environment happened to export — and the environment is not a
        # statement about this design.
        #
        # MEASURED in the pinned runner image
        # (ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…): it exports
        # `PDK_ROOT=/foss/pdks` and `PDK=ihp-sg13g2`, and
        # `/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/scripts/sealring.py`
        # EXISTS. So a design declaring a relative seal-ring script resolved to
        # ANOTHER FOUNDRY'S sealring.py, reported as
        # "(joined to $PDK_ROOT/$PDK)" — a confident answer about a file the
        # design never named. That is the same defect class as `_magicrc_for`
        # choosing a technology in alphabetical order.
        #
        # THE PROBE PATH BELOW IS UNTOUCHED. Step 5 — the fall-through when the
        # design declares NOTHING — still consults the environment, because
        # there the environment is the only thing that has spoken.
        # `test_CONTROL_an_unanswered_field_still_falls_through_to_the_pdk_probe`
        # pins that arm and it must stay byte-identical.
        #
        # AND NOTHING IS NARROWED ABOUT WHAT COUNTS AS FOUND: a declared script
        # that resolves in neither form still returns unchanged and still
        # reaches the same DISCLOSED_SKIP. What is removed is a spelling that
        # could only ever be right by coincidence.
        _root = pdk_root
        _name = pdk
        if _root and _name:
            joined = f"{_root.rstrip('/')}/{_name}/{decl_script.lstrip('/')}"
            if os.path.exists(joined):
                tried.append(joined)
                return joined, f"{_decl_src} (joined to $PDK_ROOT/$PDK)", tried
        return decl_script, _decl_src, tried
    tried.append(f"${_ENV_SCRIPT}")
    env_script = os.environ.get(_ENV_SCRIPT)
    if env_script:
        return env_script, f"${_ENV_SCRIPT}", tried
    root = pdk_root or os.environ.get("PDK_ROOT")
    name = pdk or os.environ.get("PDK")
    if root and name:
        cand = f"{root.rstrip('/')}/{name}/{_PDK_SCRIPT_REL}"
        tried.append(cand)
        from _pdk_layer_authority import _query
        volume = Path(root) / name
        # Ask the same filesystem the ordinary PDK reader uses. Explicit
        # script/bridge/declaration/environment precedence above is unchanged.
        try:
            if not _query(Path(cand), "is_file"):
                tried.append(str(volume / _MAGIC_PROVIDER_GLOB))
                candidates = [str(p) for p in _query(volume, "glob", _MAGIC_PROVIDER_GLOB)
                              if _query(Path(p), "is_file")]
                if len(candidates) == 1:
                    tried.extend(candidates)
                    return candidates[0], "$PDK_ROOT/$PDK/" + _MAGIC_PROVIDER_GLOB, tried
                if len(candidates) > 1:
                    raise ValueError("ambiguous seal-ring providers; declare --script: "
                                     + ", ".join(candidates))
        except OSError as exc:
            raise ValueError(f"seal-ring provider discovery unavailable: {exc}") from exc
        return cand, "$PDK_ROOT/$PDK/" + _PDK_SCRIPT_REL, tried
    tried.append("$PDK_ROOT/$PDK/" + _PDK_SCRIPT_REL
                 + " (PDK_ROOT/PDK not set)")
    return None, "", tried


PROVIDER_TARGET_REL = "input/submission_template/provider_target.json"


def provider_target(project: Path) -> Optional[Dict[str, Any]]:
    path = Path(project) / PROVIDER_TARGET_REL
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not value.get("provider"):
        raise ValueError(f"{path}: the selected provider is missing")
    target = value.get("technical_target")
    dims = target.get("dimensions_um") if isinstance(target, dict) else None
    if (not isinstance(dims, list) or len(dims) != 2
            or any(isinstance(x, bool) or not isinstance(x, (int, float))
                   or not math.isfinite(x) or x <= 0 for x in dims)):
        raise ValueError(f"{path}: engineering dimensions are not positive finite spans")
    return value


def built_die_rectangle(project: Path, declared: Optional[Dict[str, Any]] = None
                        ) -> Tuple[Optional[List[float]], str]:
    """The built DIEAREA, or the declared rectangle when no DEF exists.

    A GDS bounding box is not a die boundary: pre-existing core/outline
    geometry can keep it full-sized even when an imported ring is too small.
    """
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
            if m:
                scale = float(u.group(1)) if u else 1000.0
                return ([int(m.group(i)) / scale for i in (1, 2, 3, 4)],
                        f"DIEAREA of {d.relative_to(project)}")
    rect = _declared(declared or {}, _DECL_DIE_AREA)
    if (isinstance(rect, (list, tuple)) and len(rect) == 4
            and all(isinstance(c, (int, float)) and not isinstance(c, bool)
                    and math.isfinite(c) for c in rect)
            and rect[2] > rect[0] and rect[3] > rect[1]):
        return [float(c) for c in rect], f"{_DECL_SOURCE}.{_DECL_DIE_AREA}"
    return None, "no DEF DIEAREA or answered die_area_um"


def die_size(project: Path, gds: Path,
             width: Optional[float],
             height: Optional[float],
             declared: Optional[Dict[str, Any]] = None
             ) -> Tuple[Optional[float], Optional[float], str]:
    """(width_um, height_um, source).

    The floorplan's own DIEAREA is preferred over the GDS bounding box: the
    bbox is whatever geometry happens to reach furthest, which on a die with
    an outline marker or an overhanging label is not the die.

    THE DECLARATION IS THE LAST SOURCE, NOT THE FIRST, and the order is the
    whole reason it can be added at all (vibe-ic#1410/cpath). A DEF's DIEAREA
    is the die that was BUILT; `die_area_um` is the die that was AGREED. The
    ring must fit the layout it is being added to, so where both exist the
    built one wins and this changes nothing for any project that has a DEF —
    which is every project that has ever reached this step. Where they
    DISAGREE that is a real defect. The Magic seal-ring producer refuses the
    disagreement before promotion; 37.5ic's general precheck independently
    compares the finished layout against the declaration.

    What it DOES close: a self-tape-out that streamed a GDS and carries no DEF
    used to reach "no DIEAREA found; caller must pass --die-width/--die-height"
    and skip, while the number it needed was written down two directories away.
    """
    if width and height:
        return float(width), float(height), "--die-width/--die-height"
    profile = provider_target(project)
    if profile is not None:
        width, height = profile["technical_target"]["dimensions_um"]
        return float(width), float(height), PROVIDER_TARGET_REL + ".technical_target.dimensions_um (engineering target, not a reservation)"
    rect, rect_source = built_die_rectangle(project, declared)
    if rect is not None:
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if w > 0 and h > 0:
            suffix = (f" {rect} (no DEF DIEAREA on this tree)"
                      if rect_source.startswith(_DECL_SOURCE) else "")
            return w, h, rect_source + suffix
    return None, None, ("no DIEAREA found in any DEF and "
                        f"{_DECL_SOURCE}.{_DECL_DIE_AREA} is "
                        f"{_td.NOT_DETERMINED}; caller must pass "
                        "--die-width/--die-height")


def pdk_dir_of_script(script: str, pdk_root: Optional[str],
                     pdk: Optional[str]) -> Tuple[Optional[str], str]:
    """(the PDK directory the generator belongs to, how it was reached).

    The DECLARED `$PDK_ROOT/$PDK` first, because that is the pair the rest of
    the flow already passes around. Failing that, the generator's own path: a
    PDK puts its tools under `<pdk>/libs.tech/...`, so the head of that split
    IS the PDK directory — structure, not a name, and it resolves for any PDK
    laid out that way and for none that is not.
    """
    if pdk_root and pdk:
        return f"{str(pdk_root).rstrip('/')}/{pdk}", "$PDK_ROOT/$PDK"
    head, sep, _tail = str(script or "").partition("/libs.tech/")
    if sep and head:
        return head, f"the head of {script} at /libs.tech/"
    return None, (f"neither $PDK_ROOT/$PDK nor the generator path {script!r} "
                  f"locates a PDK directory, so the deck could not be read")


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


def detect_form_source(script: str, text: str) -> Tuple[str, str]:
    """Classify a provider from bytes read in the selected PDK environment."""
    if _PYA_CLI_MARKER in text:
        return "pya-cli", f"the script declares {_PYA_CLI_MARKER}"
    if (re.search(r"\bwidth\s+height\s+target_dir\b", text)
            and "-outer" in text and "-keep" in text
            and re.search(r"def\s+generate_sealring\s*\(", text)):
        return "magic-positional", "the provider declares width height target_dir and -outer/-keep"
    if "/libs.tech/magic/" in str(script).replace("\\", "/"):
        return "unsupported", "the Magic provider does not declare a supported invocation interface"
    return "klayout-rd", (f"the script does not declare {_PYA_CLI_MARKER}, so it "
                          "is driven as a KLayout batch script")


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
    return detect_form_source(script, text)


def derive_tech(runner, script: str) -> Tuple[Optional[str], str]:
    """The PDK's KLayout technology name, from the PDK's OWN .lyt beside the
    script (`<pdk>/libs.tech/klayout/tech/*.lyt`), or (None, why).

    LibreLane computes this by string-editing the PDK name. Reading the
    technology file the PDK itself ships is the same answer from the authority
    that owns it, and it keeps working for a PDK whose name does not encode it.
    """
    techdir = str(Path(script).parent.parent)
    lister = getattr(runner, "list_files", None)
    if callable(lister):
        # Listed by the runner DIRECTLY (no shell). A container runner's
        # `run_argv` goes through the image's LOGIN shell, whose profile
        # prints `[INFO] Final PATH/PYTHONPATH variable: ...` on stdout.
        # MEASURED (vibeic-eda 0.3.85, gf180mcuD): `ls <tech>/*.lyt` through
        # it gave three lines for one .lyt, and this refused with "more than
        # one KLayout technology file (osic-multitool, python, gf180mcu.lyt)".
        found = lister(techdir, ".lyt")
        rc, lyts = (0, list(found)) if found is not None else (1, [])
    else:
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
    it passes the Y span as `width` and the X span as `height` (DIE_AREA[3]
    and DIE_AREA[2] to vibeic-eda 0.3.79; upstream now states it is that
    PDK's own naming), i.e. transposed against the first. That is reproduced rather than corrected — this program
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


def _sha256_file(path: Path) -> Optional[str]:
    """sha256 of `path`, or None when it cannot be read.

    None is a THIRD STATE and callers must treat it as one: "I could not
    digest this" is not "the digest did not match".
    """
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _project_rel(path: Path, project: Path) -> str:
    """`path` spelled relative to the project root when it is inside it.

    A record that a CHECKER must resolve owes it a project-relative spelling;
    an absolute one is a second thing to translate. Falls back to the absolute
    spelling rather than inventing a relative one for a path that is genuinely
    outside the tree.
    """
    try:
        return str(Path(path).resolve().relative_to(Path(project).resolve()))
    except (ValueError, OSError):
        return str(path)


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
    # The ring can target a different provider die size from the routed core.
    # Carry its measured outer extent into the finished DEF, while preserving
    # every routed instance, net and pin at its existing coordinates.
    ol, ob, orr, ot = extent["outer"]["um"]
    diearea = (f"DIEAREA ( {round(ol * scale)} {round(ob * scale)} ) "
               f"( {round(orr * scale)} {round(ot * scale)} ) ;")
    text, dieareas = re.subn(r"\bDIEAREA\b[^;]*;", diearea, text)
    if dieareas != 1:
        return False, "the routed DEF must declare exactly one DIEAREA"
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

#: Where the DESIGN states its own packaging answer. `package_info: null` beside
#: `no_package_in_input: true` is a DECLARATION that this design has no package --
#: not the absence of one. Read from the phase-1 doc track, i.e. the design INPUT.
_L1_REL = "phase1/generated_docs/L1_DATASHEET.json"


def design_declares_no_package(project: Optional[Path]) -> Optional[str]:
    """The design's own answer to the packaging question, or None if it gave none.

    The config is not the only place this can be settled. MEASURED on spm run20:
    `L1_DATASHEET.json` carries `package_info: null` AND
    `no_package_in_input: true`, and the step-0.5ic / operator answers carry a
    typed `absent_reason` -- "nothing in L1-L9 names an operator, a slot, a
    submission template or a package" -- with an absence-of-evidence citation.
    That is an ANSWER, and reading it as silence is the mistake #2118 cost:
    a declared absence is not a missing declaration.

    By this function's own table below, `packaging declared and not CoB` is
    NOT_APPLICABLE. A design that declares it has no package is declared and not
    CoB, so the half settles as NOT_APPLICABLE instead of sitting NOT_DETERMINED
    forever -- which is what tiered the whole `die_finishing` document INCOMPLETE
    while its own verdict said PASS and its own reason said the die-ID half "does
    not gate the seal ring".

    Returns the citation when the design declares no package, else None. Only a
    POSITIVE declaration counts: an absent or unreadable L1, or one that simply
    omits the keys, returns None and the half stays NOT_DETERMINED.
    """
    if project is None:
        return None
    try:
        doc = json.loads((Path(project) / _L1_REL).read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    fields = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
    if fields.get("no_package_in_input") is not True:
        return None
    if fields.get("package_info") is not None:
        return None
    return (f"{_L1_REL} declares no_package_in_input=true with package_info=null: "
            f"the design states it has no package, so it is not a chip-on-board "
            f"submission")


#: R-0929-DIEID-BASIS, verbatim: the basis a DIE with no operator records.
DIE_ID_NO_OPERATOR_BASIS = "no operator die-ID requirement for deliverable DIE"


def operator_route(project: Optional[Path]) -> Optional[str]:
    """The declaration's route (SELF_TAPEOUT / SHUTTLE / IP), or None.

    Read through `_tapeout_declaration.declared_route_on_disk` -- the one
    predicate the declaration's producer used -- so a retained slot catalogue
    beside an owner self-tape-out DIE is not mistaken for an operator. Any
    unreadable or undeclared state is None: never a guessed route."""
    if project is None:
        return None
    project = Path(project)
    slots = project / _td.SLOTS_REL
    has_slots = slots.is_dir() and any(slots.glob("*.yaml"))
    try:
        route, _why = _td.declared_route_on_disk(project, has_slots)
    except Exception:  # noqa: BLE001 -- a contradictory route decides nothing here
        return None
    return route if route in (_td.ROUTE_SELF_TAPEOUT, _td.ROUTE_SHUTTLE,
                              _td.ROUTE_IP) else None


def die_id_state(cfg: Dict[str, Any],
                 ring_check: Optional[Dict[str, Any]],
                 project: Optional[Path] = None) -> Dict[str, Any]:
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

    profile = provider_target(project) if project is not None else None
    if (profile is not None and profile.get("provider") == "wafer.space"
            and profile["technical_target"].get("packaging") in
            ("bare_die", "non-CoB bare-die technical profile")):
        return {**base, "packaging": "bare_die", "state": "NOT_APPLICABLE",
                "packaging_basis": PROVIDER_TARGET_REL,
                "reason": "wafer.space non-CoB bare-die profile; operator ID cells are required only for CoB, not this engineering target"}

    if not isinstance(packaging, str) or not packaging.strip():
        # R-0929-DIEID-BASIS: die ID is OPERATOR-specific (the shuttle
        # operator's generate_id). Which operator -- if any -- is the
        # declaration's route, so that is read FIRST: a self-tape-out DIE has
        # no operator and so no die-ID requirement (NOT_APPLICABLE on that
        # basis, not on "no package"); a declared operator keeps the
        # requirement owed until its packaging is declared.
        route = operator_route(project)
        if route == _td.ROUTE_SELF_TAPEOUT:
            return {**base, "state": "NOT_APPLICABLE",
                    "packaging_basis": DIE_ID_NO_OPERATOR_BASIS,
                    "route": route,
                    "reason": (
                        "die identification is NOT_APPLICABLE: "
                        f"{DIE_ID_NO_OPERATOR_BASIS}. The declaration "
                        f"({_td.DECLARATION_REL}) selects route {route!r} -- "
                        "deliverable DIE with no shuttle operator -- and die "
                        "identification is the operator's requirement (its "
                        f"generate_id places its cells only for {_COB!r}). It "
                        "does not gate the seal ring.")}
        if route == _td.ROUTE_SHUTTLE:
            return {**base, "state": "NOT_DETERMINED", "route": route,
                    "reason": (
                        "an operator template was ingested (route "
                        f"{route!r}), so the operator's die-identification "
                        "requirement is OWED: it is conditional on the "
                        "packaging choice, which is not declared. Declare "
                        "die_finishing.die_id.packaging in the PDK-bridge "
                        f"config ({_COB!r} for chip-on-board) to settle this "
                        "half. It does not gate the seal ring.")}
        _declared = design_declares_no_package(project)
        if _declared:
            return {**base, "state": "NOT_APPLICABLE",
                    "packaging_basis": _declared,
                    "reason": (
                        "die identification is NOT_APPLICABLE: the design itself "
                        "declares it has no package, so this is not a "
                        f"chip-on-board submission ({_declared}). The operator's "
                        "generate_id places its four cells only for "
                        f"{_COB!r} and is a silent no-op otherwise, so there is "
                        "nothing here to require. It does not gate the seal "
                        "ring.")}
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
        report: Optional[str], sealed_by: Optional[str] = None,
        sealed_by_record: Optional[str] = None,
        sealed_by_error: Optional[str] = None,
        magic_geometry: Any = None) -> Dict[str, Any]:
    """``sealed_by``: a GDS some other caller of the SAME PDK generator already
    produced from ``gds`` (step 26.5ic on LibreLane `KLayout.SealRing`).  It
    takes the place of this program's own invocation and nothing else: the
    declaration (HARDMACRO skip, required ring), the verification of the
    output layout, the band, the die id and the report are unchanged, so the
    tool's output is judged exactly as ours is.  ``sealed_by_record`` names the
    producer's own record (bound by sha256 in the report).
    ``sealed_by_error``: that producer REFUSED; the report says so through the
    same no-output path, and this program never falls back to its own run."""
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
                               "die_id": die_id_state(cfg, ring_check,
                                                      project=project)}
        state = seal.get("state")
        for stale in (fin_def, skip_marker):
            if stale.is_file():
                stale.unlink()
        artefacts: Dict[str, Any] = {}
        if state == "DISCLOSED_SKIP" and seal.get("marker"):
            try:
                skip_marker.parent.mkdir(parents=True, exist_ok=True)
                # ATOMIC. This marker is a ROUTER: its existence tells every
                # downstream reader that die finishing did not run. A truncated
                # one still exists and still routes.
                _atomic_write_text(
                    skip_marker,
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
    # WHAT LEAVES THIS FLOW DECIDES WHETHER SECTION 2C IS EVEN ASKED, so it is
    # read FIRST — before the "started and abandoned" refusal below, which
    # would otherwise fail a hardmacro for leaving a question unanswered that
    # the declaration's own schema never asks of it. vibe-ic#2112.
    hardmacro = _hardmacro_skip(decl)
    if hardmacro is not None:
        return done(hardmacro)
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

    try:
        script, src, tried = resolve_script(project, script, pdk_root, pdk, decl)
    except ValueError as exc:
        return done({"state": "FAIL", "rule": "SEALRING_PROVIDER_UNRESOLVED",
                     "reason": str(exc)})
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
    if form not in _FORMS:
        return done({"state": "FAIL", "rule": "SEALRING_PROVIDER_INTERFACE_UNSUPPORTED",
                     "reason": form_why, "script": script})
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

    w, h, die_src = die_size(project, gds_path, width, height, decl)
    if not w or not h:
        return done(_skip(f"cannot determine the die size: {die_src}",
                          script=script, script_source=src))

    if form == "magic-positional":
        geometry = magic_geometry if magic_geometry is not None else cfg.get("magic_geometry")
        if isinstance(geometry, str):
            try:
                geometry = json.loads(geometry)
            except ValueError:
                geometry = None
        finite = lambda v: (not isinstance(v, bool) and isinstance(v, (int, float))
                            and math.isfinite(v))
        if (not isinstance(geometry, dict)
                or set(geometry) != {"size_convention", "provider_size_um", "offset_um"}
                or geometry.get("size_convention") not in ("chip", "outer")
                or not isinstance(geometry.get("provider_size_um"), list)
                or len(geometry["provider_size_um"]) != 2
                or not all(finite(v) and v > 0 for v in geometry["provider_size_um"])
                or not isinstance(geometry.get("offset_um"), list)
                or len(geometry["offset_um"]) != 2
                or not all(finite(v) for v in geometry["offset_um"])):
            return done({"state": "FAIL", "rule": "MAGIC_GEOMETRY_AUTHORITY_REQUIRED",
                         "reason": "magic-positional requires explicit magic_geometry with "
                                   "size_convention chip|outer, positive finite provider_size_um[2], "
                                   "and finite offset_um[2]; whole-DIE dimensions are never a provider frame default"})

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
    if sealed_by_error and not sealed_by:
        seal["producer"] = "librelane:KLayout.SealRing"
        rc, sout, serr = 1, "", f"the LibreLane producer refused: {sealed_by_error}"
    elif sealed_by:
        # The generator already ran elsewhere; its output is staged exactly
        # where ours would have been written, then measured like ours.
        produced = Path(sealed_by)
        seal["producer"] = "librelane:KLayout.SealRing"
        seal["sealed_by"] = {"path": str(produced),
                             "sha256": _sha256_file(produced)}
        if sealed_by_record:
            seal["sealed_by"]["record"] = str(sealed_by_record)
            seal["sealed_by"]["record_sha256"] = _sha256_file(Path(sealed_by_record))
        rc, sout, serr = 0, "", ""
        if produced.is_file():
            shutil.copyfile(produced, staged)
        else:
            rc = 1
            serr = f"sealed-by GDS not found: {produced}"
    else:
        if form == "magic-positional":
            adapter = _kl.find_engine("sealring", "magic_provider.py")
            if adapter is None:
                return done({"state": "FAIL", "reason": "sealring/magic_provider.py adapter not found"})
            if not runner.covers(adapter):
                local = rep.parent / "magic_provider.py"
                atomic_write_text(local, Path(adapter).read_text())
                adapter = local
            provider_report = rep.parent / "magic_provider.json"
            if provider_report.is_file():
                provider_report.unlink()
            geometry_source = ("--magic-geometry" if magic_geometry is not None
                               else f"{_BRIDGE_CFG}:{_BRIDGE_KEY}.magic_geometry")
            penv = dict(env, MAGIC_PROVIDER_SCRIPT=str(script),
                        MAGIC_PROVIDER_PYTHON=python, MAGIC_PROVIDER_IN=str(gds_path),
                        MAGIC_PROVIDER_OUT=str(staged), MAGIC_PROVIDER_REPORT=str(provider_report),
                        MAGIC_PROVIDER_GEOMETRY=json.dumps(geometry),
                        MAGIC_PROVIDER_GEOMETRY_SOURCE=geometry_source)
            rc, sout, serr = runner.run(adapter, penv,
                path_keys=("MAGIC_PROVIDER_IN", "MAGIC_PROVIDER_OUT", "MAGIC_PROVIDER_REPORT"),
                timeout=3600)
            seal["provider_adapter_rc"] = rc
            if provider_report.is_file():
                try:
                    seal["provider_run"] = json.loads(provider_report.read_text())
                except (OSError, ValueError) as exc:
                    seal["provider_report_error"] = str(exc)
            seal["whole_die_dimensions_um"] = [w, h]
            seal["magic_geometry"] = geometry
            seal["magic_geometry_source"] = geometry_source
            if rc != 0:
                seal["state"] = "FAIL"
                seal["generator_rc"] = rc
                seal["reason"] = "Magic provider invocation/import refused; see provider_run and tool output"
                seal["generator_output"] = ((sout or "") + (serr or ""))[-2000:]
                return done(seal)
        else:
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

    # ── WHAT THIS CORE OWES THE RING (vibe-ic#2122) ───────────────────────
    # Read from the PDK's OWN deck, in the same environment the generator just
    # ran in, and handed to the verifier so the opening is measured while both
    # layouts are open. An unreadable deck is a NAMED NOT_MEASURED carried into
    # the report — never a default clearance, which would be this flow deciding
    # where the foundry's ring goes.
    _pdk_dir, _pdk_dir_why = pdk_dir_of_script(script, pdk_root, pdk)
    if _pdk_dir:
        _clear_um, _clear_why = _srm.guard_ring_clearance_um(
            _pdk_dir, _srm.shell_from_argv(runner.run_argv))
    else:
        _clear_um, _clear_why = None, _pdk_dir_why
    seal["core_clearance_source"] = _clear_why
    if _clear_um is None:
        seal["core_clearance_not_measured"] = _clear_why

    vrep = rep.parent / "sealring_verify.json"
    venv = {"SEAL_IN": str(gds_path), "SEAL_OUT": str(staged),
            "SEAL_REPORT": str(vrep)}
    if _clear_um is not None:
        venv["SEAL_CORE_CLEARANCE_UM"] = f"{float(_clear_um):f}"
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
        if form == "magic-positional":
            expected_box, expected_source = built_die_rectangle(project, decl)
            extent = ring_check.get("ring_extent") or {}
            outer = (extent.get("outer") or {}).get("um")
            input_box = ring_check.get("die_box_um")
            declared_box = _declared(decl, _DECL_DIE_AREA)
            # The verifier proves annulus topology around the INPUT geometry.
            # A small ring around a small core can pass that test while the
            # rest of the built die remains outside it; the final GDS bbox may
            # still equal DIEAREA because its old geometry supplies the edges.
            # Compare the RING'S OWN measured outer edge to the built die.
            seal["ring_die_extent"] = {
                "expected_um": expected_box, "expected_source": expected_source,
                "measured_ring_outer_um": outer,
                "measured_input_gds_um": input_box,
                "answered_die_area_um": declared_box,
                "comparison_tolerance_um": 0.0001,
            }
            if (expected_box is None or not isinstance(outer, list)
                    or len(outer) != 4
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                               and math.isfinite(v) for v in outer)
                    or any(abs(a - b) > 0.0001
                           for a, b in zip(outer, expected_box))):
                seal["state"] = "FAIL"
                seal["rule"] = "SEAL_RING_DIE_EXTENT_MISMATCH"
                seal["reason"] = (
                    f"the Magic ring's own outer extent {outer} um does not "
                    f"match the built die rectangle {expected_box} um "
                    f"({expected_source}); whole-GDS bounding box and ring "
                    "topology alone cannot prove die-edge enclosure")
                seal["gds_out_unpromoted"] = str(staged)
                return done(seal, ring_check)
            if (not isinstance(input_box, list) or len(input_box) != 4
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                               and math.isfinite(v) for v in input_box)
                    or input_box[0] < outer[0] - 0.0001
                    or input_box[1] < outer[1] - 0.0001
                    or input_box[2] > outer[2] + 0.0001
                    or input_box[3] > outer[3] + 0.0001):
                seal["state"] = "FAIL"
                seal["rule"] = "SEAL_RING_INPUT_OUTSIDE_DIE"
                seal["reason"] = (
                    f"original input GDS geometry {input_box} um is not fully "
                    f"contained by the Magic ring's measured outer edge {outer} um; "
                    "a stale DEF cannot authorize sealing only part of the die")
                seal["gds_out_unpromoted"] = str(staged)
                return done(seal, ring_check)
            if declared_box is not None and (
                    not isinstance(declared_box, (list, tuple))
                    or len(declared_box) != 4
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                               and math.isfinite(v) for v in declared_box)
                    or any(abs(a - b) > 0.0001
                           for a, b in zip(declared_box, expected_box))):
                seal["state"] = "FAIL"
                seal["rule"] = "SEAL_RING_DECLARED_DIE_MISMATCH"
                seal["reason"] = (
                    f"answered die area {declared_box} um disagrees with built "
                    f"die rectangle {expected_box} um ({expected_source}); "
                    "a ring matching only one authority cannot be promoted")
                seal["gds_out_unpromoted"] = str(staged)
                return done(seal, ring_check)
            seal["ring_die_extent"]["state"] = "PASS"
        # ── REFUSE TO SEAL A CORE THAT IS ALREADY IN THE BAND ──────────────
        # MEASURED (vibe-ic#2122 / vibeic-eda#189) on one gf180mcuD die: the
        # same generator and the same deck gave 16 violations for the ring on
        # an empty 503 um die and 1,359,531 for that ring around this run's own
        # core, which filled the die to its edge — 19,826 core shapes inside
        # the 16 um band. Moving the core in by band + clearance took it to 0.
        # The ring, the generator and the deck were all correct; the die was
        # too small by exactly that margin, and this step sealed it in place
        # and reported `seal_ring.state = PASS`.
        #
        # So a core inside band + clearance is REFUSED, naming the clearance,
        # the deck that states it and the extent that offends — not sealed. A
        # FAIL leaves no `die_finished.def` and no SKIPPED marker (see `done`),
        # so the step's required outputs stay unsatisfied and the flow says so,
        # which is the correct answer for a die that cannot be finished.
        _cc = ring_check.get("core_clearance") or {}
        _n = _cc.get("encroaching_polygons")
        if _cc.get("state") == "MEASURED" and isinstance(_n, int) and _n > 0:
            _keep = _cc.get("keep_box_um")
            _worst = _cc.get("worst_encroachment_um") or {}
            _over = ", ".join(
                f"{k.replace('_um', '')} by {v} um"
                for k, v in sorted(_worst.items()) if isinstance(v, (int, float))
                and v > 0) or "on at least one edge"
            _lay = sorted(_cc.get("encroaching_by_layer") or [],
                          key=lambda d: -float(d.get("area_um2") or 0))
            _worst_lay = "; ".join(
                f"{d['layer']} {d['polygons']} shape(s) {d['area_um2']} um^2"
                for d in _lay[:5]) or "none named"
            seal["state"] = "FAIL"
            seal["reason"] = (
                f"this core reaches into the seal ring's own keep-out and is "
                f"NOT sealed. The ring the PDK's generator built has its inner "
                f"edge at {_cc.get('ring_inner_um')} um, and "
                f"{_clear_why} — so the core may occupy no more than "
                f"{_keep} um. It reaches outside that rectangle by {_over}: "
                f"{_n} merged region(s), {_cc.get('encroaching_area_um2')} "
                f"um^2, on {len(_lay)} of the ring's own layer(s) — "
                f"{_worst_lay}"
                + (" (5 worst by area shown)" if len(_lay) > 5 else "")
                + f". Sealing it in place would put the ring's marker on top "
                f"of prime-die geometry and every shape in the band would be "
                f"in violation; the die must be sized so the core ends at "
                f"least (ring band + {_cc.get('clearance_um')} um) from every "
                f"die edge (vibe-ic#2122).")
            seal["core_clearance"] = _cc
            seal["gds_out_unpromoted"] = str(staged)
            return done(seal, ring_check)
        if _cc:
            seal["core_clearance"] = _cc
            if _cc.get("state") == "MEASURED" and _cc.get("population_empty"):
                # DISCLOSED, not judged. A zero over an empty population is
                # "nothing was measured", and it reads exactly like "the core
                # stands back" unless somebody says which one it is.
                seal["core_clearance_population_empty"] = (
                    f"the layout this ring was added to carries nothing on any "
                    f"of the ring's own layers {_cc.get('ring_layers')}, so "
                    f"the 0 above is an EMPTY POPULATION and not a measured "
                    f"clearance — nothing on those layers could encroach "
                    f"because there is nothing on them")
        # PROMOTE ONLY A VERIFIED RING. An unverified sealed layout is never
        # swapped in: the sign-off DRC/LVS would then be measuring geometry
        # nothing has confirmed is a seal ring.
        if in_place:
            # R-0915-162 — A CONSUMED STAGING FILE IS NOT A MISSING OUTPUT.
            #
            # `staged.replace(dest)` is a rename: after it, the staging path is
            # GONE BY DESIGN and its bytes live under `dest`. But this record
            # still names the staging path (in `argv`, and in the generator's
            # own `ring_check`), and a reader that only sees "this path is not
            # on disk" cannot tell a promoted ring from an output that was
            # never written. MEASURED on spm run23:
            # `project_outputs_in_tree_check` blocked on
            # `/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds (NOT found
            # on disk)` while `seal_ring.state` was PASS, `generator_rc` 0 and
            # `ring_check.verdict` PASS -- the ring had succeeded and the
            # staging file had been consumed into `spm.gds`.
            #
            # So the producer states the consumption, and states it in a form
            # a reader can VERIFY rather than trust: the destination it went
            # to, and the sha256 of the staged bytes taken BEFORE the rename.
            # A consumer can then confirm the bytes are still there under the
            # final name. Recording only "it was consumed" would be a claim;
            # recording the digest makes it a measurement.
            _staged_sha = _sha256_file(staged)
            staged.replace(dest)
            # THE STAGING PATH IS NAMED TOO, and that is not decoration. A
            # consumption record that says only "something was consumed into
            # dest" would let a consumer exempt ANY missing path in this
            # document. Naming the path this record is about keeps the
            # exemption pinned to the one reference it earned.
            seal["consumed_staged"] = _project_rel(staged, project)
            seal["consumed_into"] = _project_rel(dest, project)
            if _staged_sha:
                seal["staged_sha256"] = _staged_sha
            else:
                # NAMED, not silently omitted. Without the digest the
                # consumption cannot be verified, and a consumer must keep its
                # finding rather than take the claim on faith.
                seal["staged_sha256_unavailable"] = (
                    f"could not read {_project_rel(staged, project)} to digest "
                    f"it before the promotion, so this consumption is stated "
                    f"but NOT verifiable")
        seal["gds_out"] = str(dest)
        seal["state"] = "PASS"
    else:
        seal["state"] = "FAIL"
        seal["reason"] = ring_check.get(
            "reason", "the generated layout does not carry a seal ring")
        seal["gds_out_unpromoted"] = str(staged)
    return done(seal, ring_check)


def _release_file(path: Path) -> Dict[str, Any]:
    path = Path(path).resolve()
    digest = _sha256_file(path)
    if digest is None:
        raise ValueError(f"provider release evidence is unreadable: {path}")
    return {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}


def read_admitted_release(project: Path, record_path: Path) -> Dict[str, Any]:
    """Read this producer's provider assembly, never an arbitrary GDS path.

    This admits a layout and its actual operator-precheck lineage. It does not
    supply missing final-GDS LVS/STA or claim a purchased/accepted submission.
    Those remain the existing sign-off and delivery consumers' responsibility.
    """
    project = Path(project).resolve()
    record_path = Path(record_path)
    if not record_path.is_absolute():
        record_path = project / record_path
    record = json.loads(record_path.read_text())
    if (record.get("producer") != "die_finishing_gen"
            or record.get("kind") != "provider_die_assembly"
            or record.get("verdict") != "PASS"):
        raise ValueError("provider assembly was not admitted by its producer")
    required = {"source_admission", "source_stream", "raw_gds", "seal_report",
                "sealed_gds", "instruction", "official_precheck", "finished_def"}
    if not required.issubset(record["basis"]["files"]):
        raise ValueError("provider assembly evidence is incomplete")
    for item in record["basis"]["files"].values():
        if _release_file(Path(item["path"])) != item:
            raise ValueError(f"provider release evidence changed: {item['path']}")
    if _release_file(Path(record["output"]["path"])) != record["output"]:
        raise ValueError("the provider release GDS changed")
    official = json.loads(Path(record["basis"]["files"]["official_precheck"]["path"]).read_text())
    if (official.get("verdict") != "PASS" or official.get("returncode") != 0
            or official.get("all_steps_requested") is not True
            or official.get("input_unchanged") is not True
            or len(official.get("steps", [])) != 16
            or official.get("output") != record["output"]):
        raise ValueError("the current operator precheck does not admit this release")
    for index, step in enumerate(official["steps"]):
        if step.get("state_out") != record["basis"]["files"].get(f"official_state_{index + 1}"):
            raise ValueError("operator completion evidence differs from the assembly")
    return {"gds": Path(record["output"]["path"]),
            "sha256": record["output"]["sha256"],
            "report": record_path.resolve(),
            "source_project": Path(record["source_project"]),
            "basis": record["basis"], "scope": "provider_die_assembly"}


def publish_provider_release(project: Path, record_path: Path, *,
                             source_project: Path, instruction: Path,
                             precheck: Path, finishing: Path,
                             fill_report: Optional[Path] = None,
                             current_signoff: Optional[Dict[str, Any]] = None):
    """Publish real finishing -> fill -> full operator-precheck evidence."""
    import _gds_admission as admission

    project, source_project = Path(project).resolve(), Path(source_project).resolve()
    old = json.loads(admission.admission_path(source_project).read_text())
    old_gds = source_project / old["gds_relpath"]
    if not admission.admitted_gds(source_project, old_gds):
        raise ValueError("the source design has no current GDS admission")
    stream_report = source_project / "reports/phase3/fill_librelane.json"
    stream = json.loads(stream_report.read_text())["default_stream"]
    raw = _release_file(Path(stream["stream"]))
    if (raw["sha256"] != stream["stream_sha256"]
            or raw["sha256"] not in old["gds_members"].values()):
        raise ValueError("the unsealed source is not the admitted stream checkpoint")
    seal_doc = json.loads(Path(finishing).read_text())
    seal = seal_doc["seal_ring"]
    clearance = seal.get("core_clearance") or seal.get("ring_check", {}).get("core_clearance", {})
    if (seal.get("state") != "PASS" or Path(seal["gds_in"]).resolve() != Path(raw["path"])
            or clearance.get("state") != "MEASURED"
            or clearance.get("population_empty") is not False
            or clearance.get("encroaching_polygons") != 0):
        raise ValueError("the new assembly has no measured clear seal-ring evidence")
    sealed = _release_file(Path(seal["gds_out"]))
    files = {"source_admission": _release_file(admission.admission_path(source_project)),
             "source_stream": _release_file(stream_report),
             "raw_gds": raw, "seal_report": _release_file(finishing), "sealed_gds": sealed,
             "instruction": _release_file(instruction), "official_precheck": _release_file(precheck)}
    official = json.loads(Path(precheck).read_text())
    if (official.get("producer") != "wafer_space_precheck"
            or official.get("returncode") != 0 or official.get("verdict") != "PASS"
            or official.get("input_unchanged") is not True
            or official.get("all_steps_requested") is not True
            or len(official.get("expected_steps", [])) != 16
            or len(official.get("steps", [])) != 16):
        raise ValueError("the complete official provider precheck did not pass")
    if fill_report is not None:
        fill = json.loads(Path(fill_report).read_text())
        if (fill.get("verdict") != "PASS"
                and not (fill.get("verdict") == "PARTIAL" and fill.get("promoted_on_foundry_floor"))):
            raise ValueError("the density fill was not admitted by its producer")
        if Path(fill["gds_in"]).resolve() != Path(sealed["path"]):
            raise ValueError("the filler did not consume this sealed assembly")
        precheck_input = _release_file(Path(fill["gds_out"]))
        files["fill_report"] = _release_file(fill_report)
        files["filled_gds"] = precheck_input
    else:
        precheck_input = sealed
    if official["input"] != precheck_input:
        # A normal complete Default stream can include its PDK filler before
        # density top-up. Reuse that existing exact chain, never invent one.
        from librelane_fill_dfm import validate_default_stream
        normal = validate_default_stream(source_project)
        current = _release_file(old_gds)
        if official["input"] != current or normal.get("canonical_sha256") != current["sha256"]:
            raise ValueError("the operator did not check this assembly revision")
        files["filled_gds"] = current
    for index, step in enumerate(official["steps"]):
        state = step.get("state_out")
        if state is None or _release_file(Path(state["path"])) != state:
            raise ValueError(f"operator step {index + 1} lacks current completion evidence")
        files[f"official_state_{index + 1}"] = state
    final = _release_file(Path(official["output"]["path"]))
    if official["output"] != final:
        raise ValueError("the operator's final layout changed")
    owner = json.loads(Path(instruction).read_text())
    target = owner["technical_target"]
    if owner.get("provider") != "wafer.space" or target["slot"] != official["slot"]:
        raise ValueError("the requested engineering target differs from the operator run")
    if official["packaging"] != "bare_die" or official.get("assigned_id") is not None:
        raise ValueError("this bare-die engineering release cannot claim an assigned ID")
    from provider_bond_pad_edge import measure
    edge_path = project / "reports/phase3/bond_pad_edge_distance.json"
    edge = measure(project, Path(final["path"]), profile_path=instruction)
    atomic_write_json(edge_path, edge)
    # This technical lineage feeds later signoff; packaging review remains
    # disclosed here and is resolved by final readiness. Measured FAIL refuses.
    if edge["verdict"] not in ("PASS", "MANUAL_REVIEW"):
        raise ValueError("bond_pad_edge_distance: " + edge["verdict"] + ": " + edge["reason"])
    files["bond_pad_edge_distance"] = _release_file(edge_path)
    finished_def = project / "phase3/stage3/pnr/provider_die_finished.def"
    ok, why = write_finished_def(Path(seal_doc["artefacts"]["routed_def_in"]), finished_def,
                                 seal["ring_check"]["ring_extent"])
    if not ok:
        raise ValueError(why)
    files["finished_def"] = _release_file(finished_def)
    record = {"producer": "die_finishing_gen", "kind": "provider_die_assembly",
              "verdict": "PASS", "source_project": str(source_project), "input": raw,
              "output": final,
              "basis": {"files": files, "current_signoff": current_signoff or {},
                        "provider": "wafer.space", "slot": official["slot"], "CoB": False,
                        "engineering_target": target, "platform_accepted": False,
                        "bond_pad_edge_distance": edge,
                        "official_precheck_report": files["official_precheck"],
                        "official_revision": official["official_entry"],
                        "provider_precheck": {
                            "provider": "wafer.space", "slot": official["slot"], "cob": False,
                            "engineering_target": True, "status": "PASS", "accepted": False,
                            "layout_sha256": final["sha256"],
                            "official_revision": official["official_entry"],
                            "source": files["official_precheck"],
                            "options": {"slot": official["slot"], "cob": False,
                                        "assigned_id": None, "all_steps_requested": True},
                            "files": [*files.values()]},
                        "die_id": {"state": "NOT_APPLICABLE",
                                   "reason": "wafer.space bare-die non-CoB profile; ID cells are required only for CoB",
                                   "assigned_id": None}}}
    record_path = Path(record_path)
    if not record_path.is_absolute():
        record_path = project / record_path
    atomic_write_json(record_path, record)
    return read_admitted_release(project, record_path)


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
    ap.add_argument("--magic-geometry", default=None,
                    help="explicit JSON size_convention, provider_size_um, offset_um; "
                         "provider frame is separate from the unchanged whole-DIE constraint")
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
    ap.add_argument("--sealed-by", default=None,
                    help="a GDS the same PDK generator already produced from "
                         "--gds (LibreLane KLayout.SealRing); verified, not re-run")
    ap.add_argument("--sealed-by-record", default=None,
                    help="the producer's own record, bound by sha256")
    ap.add_argument("--sealed-by-error", default=None,
                    help="the producer refused; report it, never run our own")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--publish-provider-precheck")
    ap.add_argument("--source-project")
    ap.add_argument("--provider-instruction")
    ap.add_argument("--fill-report")
    ap.add_argument("--release-record", default="reports/phase3/provider_die_assembly.json")
    ap.add_argument("--strict", action="store_true",
                    help="treat a disclosed skip as a FAIL (tapeout sign-off)")
    ns = ap.parse_args(argv)

    project = Path(ns.project_dir).resolve()
    if ns.publish_provider_precheck:
        try:
            release = publish_provider_release(
                project, Path(ns.release_record), source_project=Path(ns.source_project),
                instruction=Path(ns.provider_instruction), precheck=Path(ns.publish_provider_precheck),
                finishing=Path(ns.report) if ns.report else project / _REPORT_REL,
                fill_report=Path(ns.fill_report) if ns.fill_report else None)
            print(json.dumps(release, indent=2, default=str))
            return PASS
        except Exception as exc:
            print(f"die_finishing_gen: provider release refused: {exc}", file=sys.stderr)
            return FAIL
    try:
        res = run(project, ns.gds, ns.script, ns.form, ns.tech, ns.pdk_root,
                  ns.pdk, ns.python, ns.marker, ns.die_width, ns.die_height,
                  ns.out, ns.in_place, ns.report, sealed_by=ns.sealed_by,
                  sealed_by_record=ns.sealed_by_record,
                  sealed_by_error=ns.sealed_by_error,
                  magic_geometry=ns.magic_geometry)
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
