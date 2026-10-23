#!/usr/bin/env python3
"""analog_a5_layout_emit.py — A5's missing PRODUCER: it draws the layout.

WHY THIS PROGRAM EXISTS
-----------------------
A5 is the one step in the analog track that had no deterministic producer.
The plugin shipped a CHECKER (`analog_a5_layout_check`, "is geometry
present?"), a RECORD (`_analog_layout_matching`), and a stub in
`analog_one_shot_runner` that wrote 400 bytes of `x` as `layout.mag`. The
DRAWING was a hand-off to the `analog-layout` skill, and the skill had no
program behind it — so every run that needed a real analog layout authored
its own generator.

MEASURED (u_hawaii_adc / ihp-sg13g2, round 20). The generator one run
authored was hand-written in a scratch directory and copied forward for
eight rounds. It encoded "what is drawable" as the two widths it happened to
have probed, and refused a legal `w=1.0u l=0.5u` keeper — a device the PDK is
perfectly happy with (wmin 0.15 um) — with

    AssertionError: ('mp_mkp1', 'no leg tap level')

The refusal was not about the width at all: its bulk-tap scan walked UP from
the guard ring's B label, which on that device sits BELOW the ring leg, and a
25-lambda stride anchored on that label missed the only legal band by ONE
lambda. A predicted refusal, in a hand-authored script, blocked a measured
circuit fix.

THE CONTRACT
------------
INPUTS, all files, none of them a design:

  1. the A3 block netlist `phase3/analog/<block>/<block>.sp`, parsed for the
     subckt name, its port order, and per device (name, model, terminals,
     w, l, m). Nothing else is read from it. Section 4.05: the netlist is
     design INPUT; no oracle, golden or harness artefact is ever opened.
  2. the PDK's own gencell definitions and DRC deck, through
     `analog_a5_pdk_device_limits` — (lmin, wmin) per model, Metal1 minimum
     space, and a bulk-tap clearance floor built from those plus this
     emitter's OWN pad half-heights (pad size is the GENERATOR's choice, so
     the limits program takes it as an argument).
  3. a tool handle (container name / magic rcfile) — a path, not a behaviour.

OUTPUTS, exactly two, both under `phase3/analog/<block>/`:

  1. `layout.mag` and the streamed `<block>.gds`, carrying REAL placed
     geometry. `analog_a5_layout_check` already rejects an empty or
     stub-marked layout and keeps passing unchanged.
  2. `layout_provenance.json`: producer + version, block, device count, the
     resolved PDK limits WITH the file each came from, and a `deviations`
     list. A deviation is a structured record, not prose:
     {device, model, w, l, quantity, required, achieved, shortfall,
      adjudicator}.

THE INVARIANTS
--------------
I1  DRAWS WHAT THE LIMITS PERMIT. A geometry inside (lmin, wmin) is drawn. A
    width this emitter has not drawn before is NOT an error: there is no
    width list anywhere in this file. An emitter that refuses everything also
    refuses the bug.

I2  REFUSES SUB-MINIMUM BY NAME, NEVER BY ASSERTION. `w`/`l` below the PDK
    minimum exits non-zero naming the model, the value, the rule and the FILE
    the rule came from, BEFORE any probe. An AssertionError tuple is a
    contract violation.

I3  SEARCHES THE WHOLE STRUCTURE, NOT ONE DIRECTION. The bulk tap is chosen
    by scanning the ring leg's FULL extent on the PDK's own grid and taking
    the position of MAXIMUM clearance — never the first hit of a descending
    ladder of magic numbers, and never a walk in one direction from a label
    that may sit at either end. The same rule governs the escape lanes.

I4  RECORDS SHORTFALLS LOUDLY, AND NEVER GRADES. A clearance floor is a
    PREDICTION; the sign-off deck is the adjudicator. When the best available
    position is under the floor this emitter DRAWS it and writes a deviation
    naming device, quantity, required, achieved and shortfall — then A6
    decides. This program never prints a DRC verdict of its own and never
    silently downgrades a floor to make itself pass.

I5  DEGRADES LOUDLY, NEVER SILENTLY. An unreadable PDK, or an unreachable
    tool, is ENV_UNAVAILABLE with the file/tool named and a non-zero exit —
    never a built-in default and never a fabricated `layout.mag`. A structure
    that cannot host a tap at all is REFUSED by name, with the extent it
    measured, and nothing is written.

WHAT IS CHIP-AGNOSTIC HERE, AND HOW
-----------------------------------
No design, block, net or device name appears in this file, and no PDK family
name either. Everything PDK-specific is MEASURED:

  * the gencell namespace, the parameter names each gencell accepts, the
    device CLASS (mosfet / resistor / capacitor) and (lmin, wmin) come from
    the PDK's own `_defaults` procs, through `analog_a5_pdk_device_limits`;
  * lambda-per-micron comes from asking Magic itself, not from a constant;
  * a terminal's metal level is the lowest `metalN` plane whose rectangle
    covers the label point in the gencell's OWN output — so a capacitor
    terminal that lands on metal5 is routed as metal5 without this file ever
    naming a capacitor or a metal5;
  * the guard-ring layer is whatever layer the bulk label sits on.

The only numbers this file chooses are the ones the PDK does NOT state: the
wire width and via pad size of its own routing. They are CLI arguments, and
they are recorded in the provenance.

    analog_a5_layout_emit.py <project_dir> [--block B] [--container C]
                             [--magicrc PATH] [--pdk-root P] [--family F]

exit 0 → LAYOUT: OK          (layout.mag + <block>.gds + provenance written)
exit 1 → FORBIDDEN           (the PDK refuses this geometry, named) — OR the
                             layout this emitter drew SHORTS two routed nets,
                             with the witness path in the provenance
exit 2 → ENV_UNAVAILABLE     (PDK unreadable or tool unreachable, named)
exit 3 → REFUSED             (drawn structure cannot host the connection)
chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shlex
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082
import _gate_denominator as _den  # noqa: E402 — no clean list without a denominator
import _path_layout as _pl  # noqa: E402
import _analog_producer_common as _pc  # noqa: E402 — content identity
import analog_a5_pdk_device_limits as _lim  # noqa: E402
import pdk_family_identity as _pdk_identity  # noqa: E402
from _analog_a_check_common import load_block_list  # noqa: E402
import magic_gencell_layout_lib as _gl  # noqa: E402
from analog_hardmacro_gds_emit import Stage  # noqa: E402

PRODUCER = "analog_a5_layout_emit"
SCHEMA = 1

RC_OK = 0
RC_FORBIDDEN = 1
RC_ENV_UNAVAILABLE = 2
RC_REFUSED = 3

# The adjudicator of every clearance this emitter predicts. Named in each
# deviation so a reader never mistakes a prediction for a verdict.
ADJUDICATOR = "A6 per-block sign-off DRC deck (analog_a6_block_pv_check)"


class Refusal(RuntimeError):
    """I5 — a structure this emitter cannot draw. Named, with what was
    measured, and never an assertion tuple."""


# The two numbers the PDK does not state, because they are this generator's
# own choice of routing style. CLI-overridable; recorded in the provenance.
DEFAULT_WIRE_W_UM = 0.30
DEFAULT_VIA_PAD_HALF_UM = 0.15


def _resolved_tech_lef(stage: Stage, pdk_root: str, family: str,
                       *, asset_key: str = "tech_lef_glob"
                       ) -> Optional[str]:
    """Resolve the installed PDK's technology LEF through its registry.

    Phase 3/LibreLane already treats ``pdk_registry.json``'s
    ``tech_lef_glob`` as the authority for ``TECH_LEFS``.  A5 used a separate
    ``*tech*.lef`` probe, which missed the Sky130 registry asset (the shipped
    file is a ``.tlef``) and silently left every port at its zero-area label.
    Reuse the same declared relative glob here, including Ciel's
    content-addressed ``container_path_glob`` roots.  Multiple matches follow
    the registry resolver's deterministic sorted-first selection; no guessed
    filename or alternate PDK path is introduced.
    """
    try:
        registry = json.loads(
            (Path(__file__).with_name("pdk_registry.json")).read_text(
                encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entries = registry.get("pdks") if isinstance(registry, dict) else None
    if not isinstance(entries, list):
        return None
    entry = next((row for row in entries
                  if isinstance(row, dict) and row.get("name") == family),
                 None)
    if entry is None:
        # Preserve the shared family aliases before considering legacy paths.
        _canonical, entry = _pdk_identity.canonical_entry(family)
    if not entry:
        if asset_key != "tech_lef_glob":
            return None
        # A synthetic/legacy caller may provide a family that is deliberately
        # absent from the shipped registry (the unit seam uses ``x``).  Keep
        # that caller's existing explicit tech-LEF probe; production PDK names
        # still take the registry path above and never guess an asset.
        legacy_prefix = (pdk_root.rstrip("/") + "/" + family
                         + "/libs.ref/")
        legacy_arg = shlex.quote(legacy_prefix) + "*/lef/*tech*.lef"
        rc, out, _err = stage.sh(
            f"ls -1 {legacy_arg} 2>/dev/null | sort", timeout=120)
        if rc != 0:
            return None
        root_prefix = pdk_root.rstrip("/") + "/"
        for raw in sorted(out.splitlines()):
            candidate = raw.strip()
            if (candidate.startswith(root_prefix)
                    and stage.sh(f"test -f {shlex.quote(candidate)}",
                                 timeout=120)[0] == 0):
                return candidate
        return None
    if not isinstance(entry, dict):
        return None
    pattern = str(entry.get(asset_key) or "").strip()
    if not pattern:
        return None
    declared_root = str(entry.get("container_path_glob") or
                        entry.get("container_path") or "").strip()
    if not declared_root:
        return None
    # The command-line root is the mounted PDK root.  Preserve a registry
    # Ciel version suffix while replacing only its conventional /foss/pdks
    # prefix when tests or a caller mount the same image elsewhere.
    if declared_root.startswith("/foss/pdks/"):
        root = pdk_root.rstrip("/") + declared_root[len("/foss/pdks"):]
    else:
        root = declared_root
    full = root.rstrip("/") + "/" + pattern.lstrip("/")
    if not any(ch in full for ch in "*?["):
        rc, _out, _err = stage.sh(
            f"test -f {shlex.quote(full)}", timeout=120)
        return full if rc == 0 else None
    # The registry's suffix is shell glob syntax, but the caller-supplied PDK
    # root is a literal path and may contain spaces.  Quote that literal
    # prefix only, leaving the registry-owned suffix's ``*``/``?``/``[...]``
    # active.  Quoting the complete path would make a present Ciel asset look
    # absent; leaving the complete path raw would split a root such as
    # ``/tmp/pdk root``.  The canonical resolver uses the same composition.
    caller_prefix = pdk_root.rstrip("/") + "/"
    if full.startswith(caller_prefix):
        glob_arg = (shlex.quote(caller_prefix)
                    + full[len(caller_prefix):])
    else:
        # Registry entries normally compose below the command-line root.  For
        # an absolute registry root, quote its literal prefix through the first
        # metacharacter while preserving only the declared glob suffix.
        first_meta = min((i for i, ch in enumerate(full)
                          if ch in "*?["), default=-1)
        glob_arg = (shlex.quote(full) if first_meta < 0 else
                    shlex.quote(full[:first_meta]) + full[first_meta:])
    rc, out, _err = stage.sh(
        f"ls -1d {glob_arg} 2>/dev/null | sort", timeout=120)
    if rc != 0:
        return None
    mount_root = pdk_root.rstrip("/") + "/"
    for raw in sorted(out.splitlines()):
        candidate = raw.strip()
        if not candidate.startswith(mount_root):
            continue
        rc2, _o2, _e2 = stage.sh(
            f"test -f {shlex.quote(candidate)}", timeout=120)
        if rc2 == 0:
            return candidate
    return None


# ──────────────────────────────────────────────────────────────────────
# 1. the A3 netlist — design INPUT, and the only design this program reads
# ──────────────────────────────────────────────────────────────────────
_SUBCKT_RE = re.compile(r"(?is)^\.subckt\s+(\S+)([^\n]*)\n(.*?)^\.ends",
                        re.M)
_NUM_RE = re.compile(r"^([-+]?[0-9.]+(?:[eE][-+]?\d+)?)\s*([a-zA-Z]*)$")

# SPICE magnitude suffixes. A bare number in a device parameter is read as
# microns, which is what every analog netlist in this flow writes; the
# assumption is recorded in the provenance rather than left implicit.
_SUFFIX_UM = {"": 1.0, "u": 1.0, "um": 1.0, "n": 1e-3, "nm": 1e-3,
              "m": 1e3, "p": 1e-6, "meg": 1e6, "k": 1e9}


def _param_value(raw: str) -> Optional[float]:
    m = _NUM_RE.match(raw.strip())
    if not m:
        return None
    scale = _SUFFIX_UM.get(m.group(2).lower())
    if scale is None:
        return None
    return float(m.group(1)) * scale


def parse_netlist(sp: Path) -> Tuple[str, List[str], List[dict]]:
    """(subckt name, port order, devices). A device line is
    `x<name> <net>... <model> [k=v]...`: the parameters are the trailing
    `k=v` tokens, the model is the token before them, the rest are nets."""
    text = sp.read_text(errors="replace")
    m = _SUBCKT_RE.search(text)
    if not m:
        raise ValueError(f"{sp} declares no .subckt/.ends pair")
    block, portstr, body = m.group(1), m.group(2), m.group(3)
    ports = portstr.split()
    devs: List[dict] = []
    for line in body.splitlines():
        line = line.split("$")[0].strip()
        if not line or line[0] in "*.+":
            continue
        toks = line.split()
        if not toks[0].lower().startswith("x") or len(toks) < 3:
            continue
        pars: Dict[str, float] = {}
        i = len(toks)
        while i > 1 and "=" in toks[i - 1]:
            k, _, v = toks[i - 1].partition("=")
            val = _param_value(v)
            if val is not None:
                pars[k.lower()] = val
            i -= 1
        if i < 3:
            continue
        devs.append({"name": toks[0][1:], "model": toks[i - 1],
                     "nets": toks[1:i - 1], "pars": pars})
    return block, ports, devs


# ──────────────────────────────────────────────────────────────────────
# 2. the PDK — every number in this section comes out of a PDK file
# ──────────────────────────────────────────────────────────────────────
class PdkFacts:
    """What the PDK says, and which file said it."""

    def __init__(self) -> None:
        self.gencells: Dict[str, dict] = {}     # model -> defaults record
        self.mos_limits: Dict[str, Tuple[float, float]] = {}
        self.m1_space_um: Optional[float] = None
        self.deck: Dict[str, Dict] = {}
        self.sources: Dict[str, str] = {}
        # WHAT A DRAWN TYPE IS, out of the technology file that declares it.
        # See `analog_a5_pdk_device_limits.layer_identity` for the defect
        # this closes; `read_pdk` refuses rather than leave it None.
        self.layers: Optional["_lim.LayerIdentity"] = None
        # the tech LEF's ROUTING/CUT table (`tech_lef_layers`), or None
        self.tech_lef: Optional[List[dict]] = None
        self.tech_lef_sha256: Optional[str] = None
        self.core_pg: dict = {"result": "NOT_MEASURED",
                             "reason": "no resolved standard-cell LEF"}
        self.cell_lef_text: Optional[str] = None

    def limits_for(self, model: str) -> Tuple[Optional[float], Optional[float],
                                              Optional[str]]:
        """(lmin_um, wmin_um, file that stated them) or (None, None, None)."""
        rec = self.gencells.get(model)
        lmin = rec.get("lmin") if rec else None
        wmin = rec.get("wmin") if rec else None
        src = rec.get("source") if rec else None
        if model in self.mos_limits:
            # `fet_limits` takes the MINIMUM across every gencell block a
            # model appears in, which is what the PDK actually permits. It is
            # the authority wherever it speaks.
            flmin, fwmin = self.mos_limits[model]
            lmin = flmin if lmin is None else min(lmin, flmin)
            wmin = fwmin if wmin is None else min(wmin, fwmin)
            src = self.sources.get("gencell_tcl", src)
        return lmin, wmin, src


def _maxima_for(facts: "PdkFacts", model: str
                ) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """(lmax_um, wmax_um, the file that stated them) or (None, None, None).

    The mirror of `PdkFacts.limits_for`. A maximum the PDK does not state is
    ABSENT and nothing is checked against it — never a default."""
    rec = facts.gencells.get(model)
    if not rec:
        return None, None, None
    return rec.get("lmax"), rec.get("wmax"), rec.get("source")


def over_maxima(devs: Sequence[dict], facts: PdkFacts) -> List[dict]:
    """Every device the PDK's own gencell CANNOT DRAW AT THE SIZE ASKED FOR.

    THE DEFECT THIS CLOSES, MEASURED (u_hawaii_adc / ihp-sg13g2, image
    0.3.46).  `forbidden_geometries` above reads the PDK's stated MINIMA and
    refuses a device below them.  The same `_defaults` proc states MAXIMA and
    nobody read them.  A magic gencell asked for a geometry above its maximum
    does not refuse — it CLAMPS and draws.  So `delta_sigma`'s eight large
    MiM capacitors, asked for at l = 34.75 .. 629.08 um against the gencell's
    `lmax 30.0`, were every one of them drawn at l = 30 um: twelve netlist
    capacitors collapsed into TWO drawn cells, the largest device 21x smaller
    than the netlist asks for, DRC clean, the A5 gate PASS, magic
    DEVICE_ONLY — and the per-block LVS answering `mismatch` with no flow
    artefact able to say why.  The witness, from the PDK's own LVS
    cross-reference: 8 device pairs `MatchWithWarning`, every one a
    `cap_cmim`, differing in `l` alone, and the 11 mismatched nets are
    EXACTLY the nets those eight capacitors sit on.

    Returned as records, not raised: the layout is still drawn, because a
    reader repairing this needs the geometry.  The caller makes it BLOCKING
    (`blocking_deviations`), which is the difference between a wrong chip
    that looks right and one that says so."""
    out: List[dict] = []
    for dev in devs:
        lmax, wmax, src = _maxima_for(facts, dev["model"])
        for key, cap in (("l", lmax), ("w", wmax)):
            got = dev["pars"].get(key)
            if got is None or cap is None or got <= cap + 1e-9:
                continue
            out.append({
                "device": dev["name"], "model": dev["model"], "parameter": key,
                "requested_um": got, "pdk_maximum_um": cap, "source": src,
                # q6-a2-cap-osr: the bound is the Magic GENCELL's, which is
                # what this emitter draws through — on ihp-sg13g2 the foundry
                # states no side-length maximum at all (only MIM.g, an area),
                # so "PDK maximum" named the wrong authority.
                "detail": (f"{dev['name']} ({dev['model']}): {key}={got}u is "
                           f"above the Magic gencell maximum {key}max={cap}u "
                           f"({src}). The gencell does not refuse it — it "
                           f"CLAMPS to {cap}u and draws, so the drawn device "
                           f"is not the one this netlist asks for."),
            })
    return out


def read_pdk(stage: Stage, pdk_root: str, family: str,
             gencell_tcl: Optional[str], drc_tech: Optional[str],
             magic_tech: Optional[str] = None,
             tech_lef: Optional[str] = None
             ) -> Tuple[Optional[PdkFacts], str]:
    """Read every PDK fact this emitter needs, or say which file was
    unreadable. Never a default: a limit that cannot be read is ABSENT."""
    def read_source(paths: Sequence[str]) -> Tuple[str, str, str]:
        errors = []
        for path in paths:
            rc, text, err = stage.sh(f"cat {shlex.quote(path)}", timeout=120)
            if rc == 0 and text.strip():
                return path, text, ""
            errors.append(f"{path}: {(err or text).strip()[:160]}")
        return paths[0], "", "; ".join(errors)

    gp_paths = ([gencell_tcl] if gencell_tcl else
                _lim.pdk_file_candidates(pdk_root, family, "gencell"))
    dp_paths = ([drc_tech] if drc_tech else
                _lim.pdk_file_candidates(pdk_root, family, "drc"))
    tp_paths = ([magic_tech] if magic_tech else
                _lim.pdk_file_candidates(pdk_root, family, "magic"))
    gp, gtext, gerr = read_source(gp_paths)
    dp, dtext, derr = read_source(dp_paths)
    tp, ttext, terr = read_source(tp_paths)
    tech_dir = str(Path(gp).parent)

    facts = PdkFacts()
    facts.sources["gencell_tcl"] = gp
    facts.sources["drc_tech"] = dp
    facts.sources["magic_tech"] = tp

    if not gtext:
        return None, (f"ENV_UNAVAILABLE: the PDK gencell definitions are "
                      f"unreadable at {gp} ({gerr[:160]}). "
                      f"Device limits are DERIVED from the PDK; a limit this "
                      f"program cannot read is ABSENT, never a default.")
    facts.mos_limits = _lim.fet_limits(gtext)
    facts.gencells.update(_lim.gencell_defaults(gtext, gp))

    if not dtext:
        return None, (f"ENV_UNAVAILABLE: the PDK DRC deck is unreadable at "
                      f"{dp} ({derr[:160]}). The Metal1 "
                      f"spacing rule is DERIVED from it, never assumed.")
    facts.m1_space_um = _lim.m1_space_um(dtext)
    if facts.m1_space_um is None and ttext:
        # Split Magic PDKs put types/aliases and CIF units in the root
        # technology's includes, outside the selected DRC fragment.
        def tech_source(path: str) -> str:
            if path == tp:
                return ttext
            if path == dp:
                return dtext
            return read_source([path])[1]
        try:
            context = _lim.magic_technology_text(tp, tech_source)
        except (OSError, ValueError) as exc:
            return None, f"ENV_UNAVAILABLE: Magic technology context is unreadable: {exc}"
        facts.m1_space_um = _lim.m1_space_um(dtext, technology_text=context)
    facts.deck = _lim.deck_rules(dtext)
    if facts.m1_space_um is None:
        return None, (f"ENV_UNAVAILABLE: {dp} states no Metal1 minimum-space "
                      f"rule this program can read. The bulk-tap clearance "
                      f"floor is built on it and is not guessed.")

    # THE LAYER TABLE. Which conductor a gencell delivered a terminal on is
    # a question about what the drawn type IS, and the technology file is
    # the only thing that knows. It is required for the same reason the two
    # files above are: without it this emitter reads a TYPE NAME, and a PDK
    # that spells a capacitor's top plate `mimcapcontact` gets both of that
    # device's terminals painted onto its bottom plate.
    if not ttext:
        return None, (f"ENV_UNAVAILABLE: the PDK technology file is "
                      f"unreadable at {tp} ({terr[:160]}). "
                      f"Which conductor plane each drawn type occupies is "
                      f"DERIVED from it; reading the type's NAME instead is "
                      f"what shorts a capacitor whose plates are not spelled "
                      f"metalN.")
    facts.layers = _lim.layer_identity(ttext, tp)
    # Preserve the technology's raw contact heads.  LayerIdentity deliberately
    # canonicalises aliases for plane reasoning; the .mag writer still needs
    # the declared wiring-contact token (for example Sky130's mcon) so a body
    # tap reaches metal1 through the PDK interface.
    contact_heads = []
    for line in _lim._tech_sections(ttext).get("contact", []):
        toks = line.split()
        if len(toks) >= 3 and toks[0] != "stackable":
            contact_heads.append((toks[0], tuple(toks[1:])))
    facts.layers.contact_heads = contact_heads
    if not facts.layers.plane_of:
        return None, (f"ENV_UNAVAILABLE: {tp} declares no `types` section "
                      f"this program can read, so no drawn type has a plane. "
                      f"A conductor level is DERIVED, never assumed.")

    # Every OTHER gencell file the same technology directory ships — the
    # resistors and capacitors live there, and their `_defaults` procs state
    # their own minima and parameter names. Failing to list the directory is
    # not fatal: the MOS file above already answered, and a model with no
    # gencell entry is refused BY NAME later rather than silently drawn.
    rc, out, _ = stage.sh(f"ls {shlex.quote(tech_dir)}/*.tcl", timeout=120)
    if rc == 0:
        for path in sorted(set(out.split())):
            if path == gp:
                continue
            rc2, txt, _ = stage.sh(f"cat {shlex.quote(path)}", timeout=120)
            if rc2 == 0 and txt.strip():
                for model, rec in _lim.gencell_defaults(txt, path).items():
                    facts.gencells.setdefault(model, rec)

    # THE TECH LEF: which routing layers exist, their preferred directions and
    # their DC current density — what the macro's pins are placed and sized
    # by. Resolve the same registry-declared asset LibreLane records in
    # TECH_LEFS. NOT fatal: without it the pins cannot be derived, and the
    # record says so (`pins_basis`) instead of this emitter guessing a layer.
    lp = tech_lef
    if not lp:
        lp = _resolved_tech_lef(stage, pdk_root, family)
    if lp:
        rc, out, _ = stage.sh(f"cat {shlex.quote(lp)}", timeout=120)
        if rc == 0 and tech_lef_layers(out):
            facts.tech_lef = tech_lef_layers(out)
            facts.sources["tech_lef"] = lp
            facts.tech_lef_sha256 = hashlib.sha256(out.encode()).hexdigest()
    cp = _resolved_tech_lef(stage, pdk_root, family,
                            asset_key="cell_lef_glob")
    if cp:
        rc, text, _ = stage.sh(f"cat {shlex.quote(cp)}", timeout=120)
        if rc == 0 and text:
            import phase3_one_shot_runner as p3
            # Discovery reads the exact Stage bytes through the existing
            # normal-core parser. The snapshot is retained with the layout
            # so a portable A8 check can re-read it without a mounted PDK.
            import pdk_analog_layout_minima as families
            _canonical, entry = families.resolve_family(family)
            prefix = entry.get("metal_prefix")
            if prefix:
                with tempfile.TemporaryDirectory(prefix="a5_core_pg.") as tmp:
                    captured = Path(tmp) / "stdcell.lef"
                    captured.write_text(text, encoding="utf-8")
                    pg = p3._discover_pg_from_lef(str(captured), prefix)
                if pg:
                    power, ground, followpin, width = pg
                    facts.sources["cell_lef"] = cp
                    facts.cell_lef_text = text
                    facts.core_pg = {
                        "result": "MEASURED",
                        "method": "phase3_one_shot_runner._discover_pg_from_lef",
                        "source": cp,
                        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "metal_prefix": prefix,
                        "power_pin": power, "ground_pin": ground,
                        "followpin_layer": followpin, "rail_width_um": width,
                    }
    return facts, ""


def forbidden_geometries(devs: Sequence[dict], facts: PdkFacts) -> List[str]:
    """I2 — every sub-minimum geometry, named, with the rule and the FILE.

    Runs BEFORE any probe. A width this emitter has never drawn is not in
    here; only a width the PDK itself forbids is."""
    bad: List[str] = []
    for dev in devs:
        lmin, wmin, src = facts.limits_for(dev["model"])
        w, l = dev["pars"].get("w"), dev["pars"].get("l")
        if w is not None and wmin is not None and w < wmin - 1e-9:
            bad.append(f"{dev['name']}: w={w}u is below the PDK minimum "
                       f"wmin={wmin}u for {dev['model']} ({src})")
        if l is not None and lmin is not None and l < lmin - 1e-9:
            bad.append(f"{dev['name']}: l={l}u is below the PDK minimum "
                       f"lmin={lmin}u for {dev['model']} ({src})")
    return bad


# ──────────────────────────────────────────────────────────────────────
# 3. Magic — the tool handle, and the cell geometry it reports back
# ──────────────────────────────────────────────────────────────────────
_METAL_RE = re.compile(r"^m(?:etal)?(\d+)$")
_VIA_RE = re.compile(r"^(?:via|v)(\d+)$")
_SECTION_RE = re.compile(r"^<< (\S+) >>\n(.*?)(?=^<<)", re.S | re.M)
_FIXED_BBOX_RE = re.compile(
    r"string FIXED_BBOX (-?\d+) (-?\d+) (-?\d+) (-?\d+)")
_MAG_NAME_RE = re.compile(r"(?m)^([A-Za-z0-9_.+-]+\.mag)$")


def parse_cell(text: str, layers: Optional["_lim.LayerIdentity"] = None
               ) -> dict:
    """Geometry of one gencell child, in LAMBDA.

    The two coordinate spaces inside a `.mag` — `rect`/`use` following the
    file's own `magscale` header while `rlabel` is always internal units —
    are `magic_gencell_layout_lib`'s LAW #22, measured in the same campaign
    this emitter comes from. They are read THROUGH that library rather than
    re-derived here: a second copy of one measured fact is a second thing to
    keep true."""
    scale = _gl.mag_scale(text)

    sections: Dict[str, List[Tuple[int, int, int, int]]] = {}
    for sm in _SECTION_RE.finditer(text):
        name = sm.group(1)
        if name in ("checkpaint", "labels", "properties"):
            continue          # bookkeeping, not geometry
        # OUTWARD, never toward zero. A `magscale 1 2` gencell puts edges on
        # the HALF lambda, and `int()` pulls both of them toward zero: the
        # low edge rises, the high edge falls, and every rectangle this
        # emitter reads is up to a lambda SMALLER than the one the deck will
        # grade. That is the wrong direction for a number used as an
        # obstacle. MEASURED, after the island placer was already clearing
        # everything it could see: 30 M2.b violations left on one block, all
        # of them at a gap of 0.205 um against a 0.21 um rule — one half
        # lambda, and the placer had computed 0.21 and was satisfied. The
        # same law as `Geo.L`: a minimum is never rounded down, and neither
        # is the size of the thing you have to stay away from.
        sections[name] = [(int(math.floor(r[0])), int(math.floor(r[1])),
                           int(math.ceil(r[2])), int(math.ceil(r[3])))
                          for r in _gl.parse_rects_lambda(sm.group(2), scale)]

    def metal_level_at(x: int, y: int) -> int:
        """The HIGHEST metal the gencell itself already delivers at this
        label, read out of the gencell's own output.

        A terminal either sits on a conductor plane, or on a CONTACT type —
        and in Magic a contact IS its two residues plus the cut, so a
        contact carries the terminal up to the HIGHER of the two planes it
        joins.

        WHICH IS WHICH IS THE **PDK'S** ANSWER, not this file's. `layers` is
        the technology file's own `types`/`contact` table
        (`_lim.layer_identity`), and asking it is the whole repair: reading
        the section NAME instead gave every type this PDK does not spell
        `metalN`/`viaN` no level at all, so a MiM capacitor's top plate —
        delivered on `mimcapcontact`, a contact from the cap plate to metal6
        — read as the metal5 plane its BOTTOM plate occupies. Both terminals
        then landed on one conductor and the capacitor was shorted: 13 of
        them across u_hawaii_adc's two blocks, and the sign-off LVS answered
        `mismatch` with nothing in the flow able to say why. The same table
        answers `via4 metal4 metal5` -> 5, which is what the name-reading
        code already returned, so a PDK that does spell its conductors that
        way is unchanged.

        WITHOUT a table the NAMES are read, exactly as before. That path is
        unreachable from the producer — `read_pdk` refuses ENV_UNAVAILABLE
        when the technology file cannot be read — and exists so that the
        parser stays a pure function of one `.mag`.

        MEASURED, and the reason this takes the HIGHEST rather than the
        lowest: the PDK's own MOS gencell brings drain, source and gate up to
        metal2 through a stack of via1 cuts. Reading the terminal as metal1
        and painting a fresh via1 pad on top of those cuts produced 1096
        `exact_overlap v1/m1` errors — "this layer can't abut or partially
        overlap between subcells" — for connections the gencell had already
        made. Connecting at the top of what is already there makes no via at
        all where none is needed."""
        levels = []
        for name, rects in sections.items():
            if not any(r[0] <= x <= r[2] and r[1] <= y <= r[3]
                       for r in rects):
                continue
            if layers is not None and layers.knows(name):
                lvl = layers.level(name)
                if lvl is not None:
                    levels.append(lvl)
                continue
            mm = _METAL_RE.match(name)
            if mm:
                levels.append(int(mm.group(1)))
            vm = _VIA_RE.match(name)
            if vm:
                levels.append(int(vm.group(1)) + 1)
        return max(levels) if levels else 1

    labels = []
    for lab in _gl.parse_rlabels(text):
        lab = dict(lab)
        lab["level"] = metal_level_at(lab["x"], lab["y"])
        labels.append(lab)

    xs, ys = [], []
    for rects in sections.values():
        for r in rects:
            xs += [r[0], r[2]]
            ys += [r[1], r[3]]
    bbox = (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)
    fb = _FIXED_BBOX_RE.search(text)
    if fb:
        f = [int(_gl.to_lambda(int(v), scale)) for v in fb.groups()]
        bbox = (min(bbox[0], f[0]), min(bbox[1], f[1]),
                max(bbox[2], f[2]), max(bbox[3], f[3]))
    return {"labels": labels, "bbox": bbox, "sections": sections,
            "layers": layers}


def config_key(dev: dict) -> tuple:
    p = dev["pars"]
    return (dev["model"], p.get("w"), p.get("l"), int(p.get("m", 1) or 1))


def gencell_call(dev: dict, inst: str, facts: PdkFacts) -> str:
    """`magic::gencell <ns>::<model> <inst> ...`, passing ONLY the parameters
    this gencell declares. The namespace and the parameter list are the PDK's
    own, read from its `_defaults` proc."""
    rec = facts.gencells[dev["model"]]
    accepted = set(rec["params"])
    args = []
    for key in ("w", "l"):
        if key in accepted and dev["pars"].get(key) is not None:
            args += [key, _fmt(dev["pars"][key])]
    if "m" in accepted:
        args += ["m", str(int(dev["pars"].get("m", 1) or 1))]
    if "guard" in accepted:
        args += ["guard", "1"]
    return (f"magic::gencell {rec['namespace']}::{dev['model']} {inst} "
            + " ".join(args))


def _fmt(v: float) -> str:
    return f"{v:g}"


class MagicError(RuntimeError):
    pass


def magic_run(stage: Stage, magicrc: str, script: str, tag: str,
              marker: str, timeout: int = 3600) -> str:
    ok, err = stage.put_text(script, f"{tag}.tcl")
    if not ok:
        raise MagicError(f"cannot stage {tag}.tcl: {err}")
    rc, out, serr = stage.sh(
        f"cd {shlex.quote(stage.path or '.')} && "
        f"magic -dnull -noconsole -rcfile {shlex.quote(magicrc)} {tag}.tcl",
        timeout=timeout)
    blob = (out or "") + (serr or "")
    if marker not in blob:
        raise MagicError(f"magic did not reach {marker} (rc={rc}):\n"
                         f"{blob[-1800:]}")
    return blob


_LAMBDA_RE = re.compile(r"^A5SCALE (\d+) (\d+) (\d+)", re.M)


_USE_CELL_RE = re.compile(r"^use (\S+)\s+(\S+)\s*$", re.M)


def read_scale(blob: str) -> int:
    """Lambda per micron, from Magic's own answer.

    `box values` reports internal units and `tech lambda` reports the
    internal-to-lambda ratio, so the product of the two is the only place
    this program learns its working unit. There is no fallback: a scale this
    program cannot measure is ABSENT."""
    m = _LAMBDA_RE.search(blob)
    if not m:
        raise MagicError("magic did not report its own coordinate scale; "
                         "this emitter does not assume one")
    internal_per_1000um, la, lb = (int(m.group(1)), int(m.group(2)),
                                   int(m.group(3)))
    return (internal_per_1000um * la) // (lb * 1000)


def probe(stage: Stage, magicrc: str, devs: Sequence[dict], facts: PdkFacts
          ) -> Tuple[int, Dict[tuple, dict]]:
    """Pass 1. Generate every unique device configuration once, save the
    children, and read back their real geometry. Also asks Magic for its own
    lambda-per-micron, so no scale constant lives in this file.

    Returns (lambda_per_um, {config: cell record}). Each record carries the
    placement DELTA — the offset between the box position a gencell is
    invoked at and where the child actually lands — MEASURED from the probe
    block's own transforms rather than assumed."""
    layers = facts.layers
    order: List[tuple] = []
    seen = set()
    for dev in devs:
        k = config_key(dev)
        if k not in seen:
            seen.add(k)
            order.append(k)
    by_key = {config_key(d): d for d in devs}

    # The probe pitch is stated in microns so it does not need the scale the
    # same run is about to measure.
    pitch_um = 400
    lines = ["drc off",
             "cellname create a5probe", "load a5probe",
             "box 0um 0um 1000um 1000um",
             'puts "A5SCALE [lindex [box values] 2] [lindex [tech lambda] 0]'
             ' [lindex [tech lambda] 1]"']
    for i, key in enumerate(order):
        x = i * pitch_um
        lines.append(f"box {x}um 0um {x}um 0um")
        lines.append(gencell_call(by_key[key], f"p{i}", facts))
    lines += ["set cl [cellname list children a5probe]",
              "foreach c $cl { load $c ; save $c.mag }",
              "load a5probe", "save a5probe.mag",
              'puts "A5_PROBE_OK"', "quit -noprompt"]
    blob = magic_run(stage, magicrc, "\n".join(lines), "a5probe",
                     "A5_PROBE_OK")
    lam = read_scale(blob)

    host = Path(stage.host_tmp)
    ok, err = stage.get("a5probe.mag", host / "a5probe.mag")
    if not ok:
        raise MagicError(f"the probe block did not come back: {err}")
    ptext = (host / "a5probe.mag").read_text(errors="replace")
    # The probe block carries its OWN `magscale`, and whether Magic writes
    # one at all depends on the cells inside it — a block of MOS children
    # gets `magscale 1 2` and a block of capacitor children gets none. That
    # is the library's LAW #22 again, and reading the transforms raw made
    # every placement delta twice its true value, which put each device on
    # top of its neighbour.
    by_inst = _gl.parse_use_transforms(ptext)
    inst_cell = {inst: cell for cell, inst in _USE_CELL_RE.findall(ptext)}

    cells: Dict[tuple, dict] = {}
    for i, key in enumerate(order):
        if f"p{i}" not in by_inst or f"p{i}" not in inst_cell:
            raise MagicError(
                f"the PDK gencell for {key[0]} (w={key[1]} l={key[2]} "
                f"m={key[3]}) produced no cell in the probe block")
        tx, ty = by_inst[f"p{i}"]
        name = Path(inst_cell[f"p{i}"]).name
        dst = host / f"{name}.mag"
        ok, err = stage.get(f"{name}.mag", dst)
        if not ok:
            raise MagicError(f"gencell child {name}.mag did not come "
                             f"back: {err}")
        rec = parse_cell(dst.read_text(errors="replace"), layers)
        rec["cell"] = name
        rec["delta"] = (int(tx) - i * pitch_um * lam, int(ty))
        cells[key] = rec
    return lam, cells


# ──────────────────────────────────────────────────────────────────────
# 4. terminals — which drawn label answers to which netlist net
# ──────────────────────────────────────────────────────────────────────
def _base(name: str) -> str:
    """A gencell numbers the labels of a multi-finger device (`D0`, `D1`,
    ...); the finger index is not a terminal."""
    return re.sub(r"\d+$", "", name)


# The four SPICE MOS terminal letters, in SPICE's own terminal order. This is
# the SPICE/Magic device convention, not a chip, PDK or design fact: a
# subcircuit call `x<name> d g s b <model>` names them in this order and the
# gencell labels them with these letters.
_MOS_LETTERS = ("D", "G", "S", "B")

#: A terminal the gencell numbered — `R1`, `R2`, `C1`, `C2`. It is the
#: gencell saying "this one is in the sequence"; a label WITHOUT a number,
#: where every other label has one, is the terminal outside it. See
#: `terminal_map`.
_ORDINAL_TERMINAL_RE = re.compile(r"\d$")


def _extent(rects: Sequence[Tuple[int, int, int, int]]
            ) -> Tuple[int, int, int, int]:
    """The bounding box of a set of rectangles."""
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


def body_contact_layers(cell: dict) -> List[str]:
    """Every section of this gencell child that the PDK's OWN layer map
    declares to be a BODY connection, sorted.

    A body connection is a CONTACT — the technology file's `contact` section
    gives it two residues — at least one of whose residues sits on a plane
    that carries no routing level: diffusion, a well, a device plate. That is
    `LayerIdentity.device_electrode_contact`, and it is the technology file's
    answer rather than a name this program recognises. Measured on the three
    open PDKs in the pinned image, straight from each one's own `.tech`, with
    no name pattern anywhere: ihp-sg13g2 selects 20 of 26 declared contact
    types and declines its 6 vias; gf180mcuD 22 of 27; sky130A 24 of 28. The
    families disagree about the borderline cases — gf180mcuD calls its MiM
    contact metal-to-metal and ihp-sg13g2 does not — which is exactly the
    point: each PDK's file answers for itself.

    Empty when the cell carries no layer table, which is `ring_layer_of`'s
    signal to fall back to the geometry-only rule (see there)."""
    layers = cell.get("layers")
    if layers is None:
        return []
    return sorted(ly for ly in cell["sections"]
                  if layers.knows(ly) and layers.device_electrode_contact(ly))


def _ring_by_cell_coverage(cell: dict) -> Optional[str]:
    """The ORIGINAL rule, unchanged, kept for a cell with no layer table.

    It asks one geometric question of every section — does this layer's
    extent cover >= 90% of the CELL bounding box in both axes while filling
    only a fraction of its area? — and it is right about a bare ring and
    wrong about a ring inside a wider well (vibe-ic#2056 item 3). It is
    UNREACHABLE FROM THE PRODUCER, which always has the table (`read_pdk`
    refuses ENV_UNAVAILABLE without it), and exists so that `parse_cell`
    stays a pure function of one `.mag`: the same arrangement `parse_cell`
    already makes for metal levels."""
    bx1, by1, bx2, by2 = cell["bbox"]
    span_x, span_y = bx2 - bx1, by2 - by1
    if span_x <= 0 or span_y <= 0:
        return None
    best = None
    for layer, rects in cell["sections"].items():
        if len(rects) < 3:
            continue
        xs = [v for r in rects for v in (r[0], r[2])]
        ys = [v for r in rects for v in (r[1], r[3])]
        cover_x = (max(xs) - min(xs)) / span_x
        cover_y = (max(ys) - min(ys)) / span_y
        if cover_x >= 0.9 and cover_y >= 0.9:
            area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects)
            if area < 0.5 * span_x * span_y and (best is None
                                                 or area < best[1]):
                best = (layer, area)
    return best[0] if best else None


def ring_layer_of(cell: dict) -> Optional[str]:
    """The layer the device's guard ring is drawn on, or None.

    TWO QUESTIONS, AND ONLY ONE OF THEM IS GEOMETRY.

      1. WHICH LAYERS COULD BE A RING — the PDK's answer, through
         `body_contact_layers`: a ring is a body connection, so it is drawn
         on a contact type whose residues reach a non-routing plane.
      2. WHICH OF THOSE IS THE RING — geometry, asked only of that short
         list, and a different question from the one below: a ring is drawn
         as several BARS (>= 3 rectangles) that fill only a fraction of their
         own extent, and it ENCLOSES the cell's other body contacts, because
         that is what a guard ring is for.

    THE DEFECT THIS REPLACES, measured (vibe-ic#2129, the ROOT of #2056
    item 3). The old rule is `_ring_by_cell_coverage` above: it asked one
    geometric question of every section — does this layer cover >= 90% of the
    CELL bounding box in both axes? — and on this PDK's own gencell children
    the answer is no for the ring and yes for nothing, because the WELL
    rectangle the ring sits in is WIDER than the ring. It returned None on
    34 of 34 children across u_hawaii_adc's two analog blocks (8 in `ldo`,
    26 in `delta_sigma`; ihp-sg13g2, image sha256:1463dac58116, lambda
    100/um), so `build_plan`'s bulk-tap block never entered on ANY device and
    `choose_tap`, the tap-clearance floor and `bulk_tap_row_separation_lambda`
    were unreachable code on real silicon.

    The ring's coverage of the CELL was never the property that identifies
    it; the numbers say so. On `sg13_lv_nmos w=2 l=0.5` the substrate ring
    covers 0.730 x 0.815 of the cell — under the old 0.9 in both axes — while
    it covers 1.000 x 1.000 of the drain, source and gate contacts it
    encloses. ENCLOSURE OF THE OTHER BODY CONTACTS is the property, and it is
    scale-free: the well can be as wide as it likes.

    NOT A LABEL. The attempt refused at 8353c69a2 anchored the ring on the
    layer the bulk LABEL sits on; it ran the search and added 240 bulk-tap
    shortfalls the sign-off deck then contradicted, because a label is a name
    the gencell chose and not a statement about what the geometry IS. Nothing
    here reads a label. Measured through the general A1..A9 flow with this
    resolver in place: 560 rules graded, 0 violations, on BOTH blocks.

    NO PDK IS NAMED. Every input is either the technology file's own
    types/contact table or the gencell's own rectangles.

    Returns None when the child carries no such frame. A device with no body
    connection at all — this PDK's MiM capacitor draws one body contact as
    one solid rectangle — is a legitimate None, and `build_plan` records the
    difference between "no ring" and "not searched" rather than reporting
    either as silence."""
    cands = body_contact_layers(cell)
    if not cands:
        # No table (or a table that declares none of these types): the cell
        # is not a PDK gencell child this program probed, and the old
        # geometry-only rule is the only honest answer available.
        return _ring_by_cell_coverage(cell)
    frames: List[Tuple[str, int]] = []
    for layer in cands:
        rects = cell["sections"].get(layer) or []
        if len(rects) < 3:
            continue                       # a ring is drawn as bars
        ex = _extent(rects)
        span = (ex[2] - ex[0]) * (ex[3] - ex[1])
        if span <= 0:
            continue
        area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects)
        if area >= 0.5 * span:
            continue                       # a frame is hollow, not a plate
        others = [_extent(cell["sections"][o]) for o in cands
                  if o != layer and cell["sections"].get(o)]
        if not all(ex[0] <= o[0] and ex[1] <= o[1]
                   and ex[2] >= o[2] and ex[3] >= o[3] for o in others):
            continue                       # it does not enclose them
        frames.append((layer, area))
    if not frames:
        return None
    # Two frames can only both enclose each other with identical extents;
    # take the smaller-area one so the answer is a function of the bytes.
    return min(frames, key=lambda t: (t[1], t[0]))[0]


def terminal_map(dev: dict, cell: dict
                 ) -> Tuple[Dict[str, List[dict]], Optional[str], List[str]]:
    """({net: [labels]}, ring layer, unmapped netlist terminals).

    Two conventions, and both are read rather than assumed:

      * a device the PDK CLASSIFIES as a mosfet has its four terminals named
        by the SPICE MOS letters, matched by letter;
      * every other device's gencell emits its ports in the netlist's own
        terminal order, with the guard-ring terminal last — which is what the
        PDK's resistor and capacitor gencells were measured to do.

    WHICH LABEL IS THE TRAILING ONE, and the defect that rule had. It was
    found by asking `ring_layer_of` which layer the guard ring is on and
    taking the label sitting there. On this PDK's own gencell children that
    answer is NONE — the ring is inside a WELL rectangle wider than itself,
    so the ring fails the "encloses the cell" test it is judged by — and with
    no trailing label the netlist's terminals were zipped against the labels
    in the order the `.mag` happens to list them. The PDK's resistor lists
    them B, R1, R2 while SPICE calls it R1, R2, B, so every resistor's
    SUBSTRATE TAP was wired to a signal net and its two body terminals were
    each one position out.

    MEASURED on u_hawaii_adc (ihp-sg13g2, image 0.3.46). `xr1 vout vfb vss`
    mapped B->vout, R1->vfb, R2->vss, and `xr_bias vin nbias vss` mapped
    B->vin: the substrate is ONE node, so vin, vout, vfb and vss extracted
    as a single net carrying 20 device terminals — exactly |vin|+|vout|+|vss|
    of the source netlist — with a block-spanning substrate polygon on it.
    `ldo` extracted 6 nets and 10 devices for a netlist of 9 and 11, and the
    per-block LVS answered `mismatch`.

    So the trailing terminal is identified from the LABELS THEMSELVES, which
    is where the gencell already says it: a device whose terminals are named
    with an ORDINAL (`R1`, `R2`, `C1`, `C2`) and which has exactly ONE label
    without one has named that odd label as the terminal outside the
    sequence, and SPICE puts it last. A gencell whose labels are all ordinal
    (the capacitor's `C1`/`C2`) has no such label and is unchanged; a device
    whose ring `ring_layer_of` DOES find is unchanged; a mosfet never reaches
    here. After it: `ldo` extracts 9 nets and 11 devices and the LVS says
    `match`; `delta_sigma` goes 119 nets -> 122 for a netlist of 122, with
    294 devices on both sides and no merged net left.
    """
    ring = ring_layer_of(cell)
    labels = cell["labels"]
    nets = dev["nets"]
    out: Dict[str, List[dict]] = {}
    unmapped: List[str] = []

    if dev.get("class") == "mosfet" and len(nets) >= 4:
        for letter, net in zip(_MOS_LETTERS, nets):
            hits = [l for l in labels if _base(l["name"]) == letter]
            if hits:
                out.setdefault(net, []).extend(hits)
            else:
                unmapped.append(f"{letter}->{net}")
        return out, ring, unmapped

    ring_labels = [l for l in labels if ring and l["layer"] == ring]
    if not ring_labels:
        odd = [l for l in labels if not _ORDINAL_TERMINAL_RE.search(l["name"])]
        if len(odd) == 1 and len(labels) == len(nets) > 1:
            ring_labels = odd
    rest = [l for l in labels if l not in ring_labels]
    order = list(nets)
    if ring_labels and len(order) == len(rest) + 1:
        out.setdefault(order[-1], []).extend(ring_labels)
        order = order[:-1]
    for net, lab in zip(order, rest):
        out.setdefault(net, []).append(lab)
    for net in order[len(rest):]:
        unmapped.append(f"?->{net}")
    return out, ring, unmapped


def body_tap_contact_layer(layers) -> Optional[str]:
    """Return the PDK contact that joins local interconnect to metal1.

    Sky130 guard-ring labels are on ``psubdiffcont``/``nsubdiffcont``.
    Those device-contact types are not the metal1 routing plane: the gencell
    already supplies the local-interconnect residue, and the route needs the
    technology's own local-interconnect-to-metal1 contact before the normal
    via1 stack can leave the ring.  Derive that contact from the loaded tech
    table; never name ``mcon`` or another PDK alias here.
    """
    if layers is None:
        return None
    for contact, residues in layers.connects.items():
        planes = {layers.plane_of.get(r) for r in residues}
        if "locali" in planes and "metal1" in planes:
            return contact
    return None


def body_tap_metal_contact_layer(layers) -> Optional[str]:
    """Return the raw Magic contact that joins the tap's local residue to M1.

    ``LayerIdentity`` canonicalises Magic type aliases (Sky130 calls the
    locali plane ``viali``), but a wiring ``contact`` is a separate tile
    declared by the tech file.  Keep that declaration's head token so the
    emitted .mag contains the actual M1 contact rather than merely another
    locali tile.
    """
    if layers is None:
        return None
    for head, residues in getattr(layers, "contact_heads", ()):
        planes = {layers.plane_of.get(layers.canon.get(r, r))
                  for r in residues}
        if "locali" in planes and "metal1" in planes:
            return head
    return None


def body_tap_local_layer(layers) -> Optional[str]:
    """Return the local-interconnect residue required under the tap."""
    if layers is None:
        return None
    for contact, residues in layers.connects.items():
        planes = {layers.plane_of.get(r) for r in residues}
        if "locali" in planes and "metal1" in planes:
            return next((r for r in residues
                         if layers.plane_of.get(r) == "locali"), None)
    return None


def body_tap_direct_m1_layer(layers, ring_layer) -> Optional[str]:
    """Return a body-ring contact that already reaches Metal1.

    Some Magic technologies put the body contact directly between a device
    electrode (for example, diffusion) and ``metal1``.  Such a gencell needs
    no separate local-interconnect-to-M1 bridge.  This answer is derived from
    the loaded technology's canonical contact table and the ring layer found
    in the child cell; no contact or PDK alias is named here.
    """
    if layers is None or not ring_layer:
        return None
    ring = layers.canon.get(ring_layer, ring_layer)
    residues = layers.connects.get(ring)
    if not residues:
        return None
    ring_plane = layers.plane_of.get(ring)
    planes = {layers.plane_of.get(layers.canon.get(r, r))
              for r in residues}
    if (ring_plane and not _lim._PLANE_LEVEL_RE.match(ring_plane)
            and "metal1" in planes):
        return ring
    return None


# ──────────────────────────────────────────────────────────────────────
# 5. the bulk tap — I3, the search that must cover the whole structure
# ──────────────────────────────────────────────────────────────────────
def choose_tap(ring_rects: Sequence[Tuple[int, int, int, int]],
               others: Sequence[Tuple[int, int, int, int]],
               forbidden_rows: Sequence[Tuple[int, int]],
               pad_half: int) -> Optional[Tuple[int, int, int, bool]]:
    """(x, y, centre-to-centre clearance, row_constraint_met) — where on the
    guard ring to put the bulk tap.

    THE ROUND-20 DEFECT, and why this looks the way it does. The generator
    that failed searched in ONE direction — up from the bulk label — and on a
    narrow device that label sits at the BOTTOM of the ring leg, so two
    thirds of the leg was never examined. It then stepped in a 25-lambda
    stride anchored on that same label, and missed the one legal band by ONE
    lambda. Both are quantisation, not rules.

    So every bar of the ring is a candidate structure, the scan walks its
    full extent on the PDK's own grid (one lambda), and the position taken is
    the one of MAXIMUM clearance — never the first that clears a threshold,
    because a first-hit search cannot report how much room the structure
    actually had.

    `forbidden_rows` are the height bands the device's other terminals will
    escape through. A tap that lands inside one is legal against the tap
    clearance floor and still unroutable, so the scan prefers a position
    outside them; when the ring offers none it takes the best position
    anyway and says so, rather than refusing a device the PDK permits.

    The clearance returned is CENTRE-TO-CENTRE, which is what the limits
    program's floor (`m1_space + tap_pad_half + terminal_pad_half`) measures.
    """
    def scan(respect_rows: bool) -> Optional[Tuple[int, int, int]]:
        best: Optional[Tuple[int, int, int]] = None
        for (rx1, ry1, rx2, ry2) in ring_rects:
            vertical = (ry2 - ry1) >= (rx2 - rx1)
            cx, cy = (rx1 + rx2) // 2, (ry1 + ry2) // 2
            lo, hi = (ry1, ry2) if vertical else (rx1, rx2)
            # the pad must sit ON the bar, so its centre stays a pad-half in
            lo, hi = lo + pad_half, hi - pad_half
            if lo > hi:
                continue
            for pos in range(lo, hi + 1):
                x, y = (cx, pos) if vertical else (pos, cy)
                if respect_rows and any(r0 <= y <= r1
                                        for r0, r1 in forbidden_rows):
                    continue
                pad = (x - pad_half, y - pad_half, x + pad_half, y + pad_half)
                clear = min((box_separation(pad, o) + 2 * pad_half
                             for o in others), default=10 ** 9)
                if best is None or clear > best[2]:
                    best = (x, y, clear)
        return best

    hit = scan(True)
    if hit is not None:
        return hit[0], hit[1], hit[2], True
    hit = scan(False)
    if hit is None:
        return None
    return hit[0], hit[1], hit[2], False


def box_separation(a: Tuple[int, int, int, int],
                   b: Tuple[int, int, int, int]) -> int:
    """Separation between two rectangles, 0 when they touch or overlap.

    `max(dx, dy)` is deliberately CONSERVATIVE: it never exceeds the true
    corner-to-corner distance, so a clearance this program reports as short
    is never long in the deck. Reporting more shortfalls than the deck will
    is the safe direction for a producer that does not grade."""
    dx = max(b[0] - a[2], a[0] - b[2], 0)
    dy = max(b[1] - a[3], a[1] - b[3], 0)
    return max(dx, dy)


# ──────────────────────────────────────────────────────────────────────
# 5b. the routing geometry — every number the deck states, in lambda
# ──────────────────────────────────────────────────────────────────────
class Geo:
    """What the routing may be, per layer, resolved to lambda.

    The PDK does not state a routing WIRE WIDTH or a VIA PAD SIZE: those are
    the generator's style, which is why the limits program takes the pad
    half-height as an argument. Everything else — the minimum width a metal
    may be, the spacing it needs, the metal a via must be enclosed by, the
    area a metal island must have — the deck states, and every one of those is
    read here rather than chosen.

    A rule the deck does not state is ABSENT, not defaulted: the Metal1
    spacing the limits program already derives is the only fallback, and it
    is used only where the deck is silent."""

    def __init__(self, rules: dict, m1_space_um: float, lam: int,
                 wire_w_um: float, pad_half_um: float) -> None:
        self.lam = lam
        self.rules = rules
        self._fallback_space = m1_space_um

        def L(um: float) -> int:
            """A deck MINIMUM in lambda, always rounded UP.

            MEASURED: `round()` here turns the deck's 0.045 um via surround
            into 4 lambda on a 100-lambda/um grid — Python rounds 4.5 to the
            even 4 — and 4 lambda is 0.04 um, which is under the rule. That
            single half-lambda produced 1436 `metal overlap of via` errors on
            an 11-device block. A minimum is never rounded down."""
            return max(1, int(math.ceil(um * lam - 1e-9)))

        self.space = {n: L(v) for n, v in rules["metal_space_um"].items()}
        self.default_space = L(m1_space_um)
        self.wire = {}
        for n in (1, 2, 3, 4, 5, 6, 7):
            need = rules["metal_width_um"].get(n, 0.0)
            self.wire[n] = max(L(wire_w_um), L(need) if need else 1)
        self.via_pad = {}
        self.patch = {}
        self.short_half: Dict[int, int] = {}
        self.long_half: Dict[int, int] = {}
        self.enc_half: Dict[int, int] = {}
        self.via_pad_min: Dict[int, int] = {}
        self.area_lam2: Dict[int, int] = {}
        for k in range(1, 8):
            side = max(2 * pad_half_um, rules["via_width_um"].get(k, 0.0))
            half = max(1, int(round(side * lam / 2)))
            self.via_pad[k] = half
            enc = max(rules["via_surround_um"].get((k, k), 0.0),
                      rules["via_surround_um"].get((k, k + 1), 0.0))
            enc_dir = max(rules.get("via_surround_dir_um", {}).get((k, k), 0.0),
                          rules.get("via_surround_dir_um", {}).get((k, k + 1),
                                                                   0.0))
            area = max(rules["metal_area_um2"].get(k, 0.0),
                       rules["metal_area_um2"].get(k + 1, 0.0))
            # A via island must clear the cut by the surround the deck
            # demands AND be large enough for the minimum-area rule, because
            # an island connected to nothing else is its own area region.
            #
            # THE TWO SURROUNDS ARE NOT ONE. This PDK states an ALL-AROUND
            # surround of 0.005 um and a DIRECTIONAL one of 0.045 um, and
            # `deck_rules` now hands them over separately. Applying the
            # directional distance on every side is not caution: it is a
            # different rule, nine times the stated all-around one, and it
            # is what made every island a 0.4 um square. MEASURED on
            # ihp-sg13g2: the square is wider than the 0.16 um terminal
            # metal a device gencell offers, so it overhangs into the
            # 0.185 um gap the gencell leaves above that terminal, and the
            # sign-off deck answers M1.b / M2.b / V1.b — 2242 of them across
            # two blocks, every one of them this island's own edge.
            #
            # So the island is ANISOTROPIC by construction: the all-around
            # surround on the SHORT axis, the directional one on the LONG
            # axis, and the minimum area met by lengthening the long axis
            # rather than by growing both. Which axis is long is decided per
            # site, by where the neighbouring geometry leaves room.
            # At least ONE lambda of metal past the cut on every side even
            # where the deck states no all-around surround at all: a metal
            # island exactly the size of the cut it covers is a drawing this
            # generator will not make, and saying so here is cheaper than a
            # rule nobody wrote down. It is the generator's choice, like the
            # wire width, and it is recorded with the rest of them.
            short = half + max(L(enc) if enc else 0, 1)
            long_by_enc = half + (L(enc_dir) if enc_dir else 0)
            # one lambda of margin on the area island: the rule is an
            # inequality on a quantised grid, and a patch drawn at exactly
            # the minimum has nowhere to lose a half-lambda
            long_by_area = (int(math.ceil(area * lam * lam
                                          / (4.0 * short))) + 1
                            if area else 0)
            self.short_half[k] = short
            self.long_half[k] = max(long_by_enc, long_by_area, short)
            self.enc_half[k] = max(long_by_enc, short)
            # The painted via is the GENERATOR's size; the deck's own via
            # width is the FLOOR. Where the preferred pad leaves no legal
            # island, the floor is what the deck actually asks for, and
            # falling back to it is reading the deck rather than overruling
            # it. Recorded per site in the provenance when it is used.
            floor = max(1, int(math.ceil(
                rules["via_width_um"].get(k, 0.0) * lam / 2 - 1e-9))) \
                if rules["via_width_um"].get(k) else half
            self.via_pad_min[k] = min(half, floor)
            self.area_lam2[k] = int(round(
                rules["metal_area_um2"].get(k, 0.0) * lam * lam))
            # `patch` stays the widest half this generator can paint at a
            # via, because `pitch()` sizes its corridors from it.
            self.patch[k] = self.long_half[k]

    def metal_space(self, layer: str) -> int:
        m = _METAL_RE.match(layer) or _VIA_RE.match(layer)
        if m:
            n = int(m.group(1))
            if _VIA_RE.match(layer) and not _METAL_RE.match(layer):
                return self.rules_via_space(n)
            return self.space.get(n, self.default_space)
        return self.default_space

    def rules_via_space(self, k: int) -> int:
        um = self.rules["via_space_um"].get(k)
        return (max(1, int(round(um * self.lam))) if um
                else self.default_space)

    def pitch(self) -> int:
        """Centre-to-centre spacing for parallel routing: the widest thing
        this generator paints plus the widest spacing any routed layer asks
        for. One number, deliberately, so the corridor arithmetic stays
        readable — and it is the MAXIMUM, so it is never short."""
        widest = max(list(self.wire.values())
                     + [2 * v for v in self.patch.values()])
        return widest + max(list(self.space.values())
                            + [self.default_space])


# ──────────────────────────────────────────────────────────────────────
# 6. the plan — placement, straps, escape lanes, rails
# ──────────────────────────────────────────────────────────────────────
# All coordinates below are in LAMBDA, the unit Magic's own `box`/`paint`
# commands take, and the scale that turns microns into it was measured from
# Magic in the probe pass.
class Plan:
    """Everything the layout pass will paint, and every shortfall it found.

    The routing style is deliberately simple and deliberately EXPLICIT about
    what makes it correct, because a producer that cannot say why its wires
    do not touch is a producer nobody can audit:

      * every device sits in ONE row, so each occupies its own x interval;
      * the terminals of one net at one height are strapped together on
        metal2 at a height just above or just below that row of contacts —
        two nets sharing a contact row take OPPOSITE sides, which is what
        keeps an interleaved multi-finger device's drain strap clear of its
        source stubs;
      * each strap escapes sideways on metal3 into the corridor between two
        devices and drops to its net's metal2 rail below the row. Lanes in a
        corridor are handed out in order of the height they come from, so an
        escape never crosses the lane of an escape that started lower;
      * the rails are one metal2 track per net, below every device.

    Everything the plan cannot make clear it MEASURES and records as a
    deviation. It never adjusts a floor to make itself pass."""

    def __init__(self) -> None:
        self.shapes: List[dict] = []      # {net, layer, box}
        self.sites: Optional["Sites"] = None
        self.tcl: List[str] = []
        self.deviations: List[dict] = []
        self.ports: List[Tuple[str, int, int]] = []
        self.port_nets: List[str] = []
        # the declared ports as PINS: one record per port, with the
        # rectangle its label covers (see `_draw_pins`)
        self.pins: List[dict] = []
        # `floating_metal_patches` census, and each patch's own device
        self.island_patches: dict = {}
        self.patch_of: Dict[Tuple[str, tuple], str] = {}
        self.row_base = 0
        # the gencells' OWN geometry, placed. The emitter does not draw it
        # and cannot change it, but its routing runs beside it, and a
        # clearance record that cannot see the thing the routing is closest
        # to is not a record.
        self.device_shapes: List[dict] = []
        # ── the bulk-tap check's own denominator (vibe-ic#2056 item 3) ────
        # An empty `deviations` list is read as "the bulk-tap clearance floor
        # was met". On this PDK it means the floor was NEVER EVALUATED:
        # `ring_layer_of` answers None on every one of its gencell children,
        # because the ring sits inside a WELL rectangle wider than itself and
        # so fails the "encloses the cell" test it is judged by — so
        # `choose_tap`, `bulk_tap_clearance_lambda` and
        # `bulk_tap_row_separation_lambda` never run on a real device. That
        # was MEASURED and reported (lanes czadc28/czadc29, u_hawaii_adc,
        # ihp-sg13g2) and the correction was measured NOT to buy a verdict
        # (v1.17.93: a label-anchored ring runs the search and adds 240 bulk-
        # tap shortfalls the sign-off deck then contradicts). What is left is
        # the SILENCE, and that is what these three fields end: a run in
        # which the check examined nothing says so, in the repo's own
        # zero-denominator shape, instead of publishing an empty shortfall
        # list that reads as cleanliness.
        self.bulk_tap_considered = 0
        self.bulk_tap_examined = 0
        self.bulk_tap_unexamined: List[dict] = []
        # MEMBERSHIP, added with the resolver that made the search run at
        # all (vibe-ic#2129). A count says how many; only a NAME lets a
        # reader check that every shortfall the record publishes came from a
        # device the search actually entered. Without it "177 shortfalls"
        # and "177 shortfalls of a search that never ran" are the same line.
        self.bulk_tap_searched: List[str] = []          # device names
        self.bulk_tap_ring_layer: Dict[str, str] = {}   # device -> layer

    def paint(self, net: str, layer: str, x1: int, y1: int, x2: int, y2: int
              ) -> None:
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        row = {"net": net, "layer": layer, "box": (x1, y1, x2, y2)}
        self.shapes.append(row)
        if self.sites is not None:
            self.sites.add(row)
        self.tcl.append(f"box {x1} {y1} {x2} {y2}")
        self.tcl.append(f"paint {layer}")

    def deviate(self, dev: dict, quantity: str, required, achieved,
                detail: str = "") -> None:
        """I4 — a shortfall is a STRUCTURED record, never prose and never a
        verdict. The floor is this emitter's prediction; the adjudicator
        named here is the one that actually grades the geometry."""
        rec = {
            "device": dev.get("name"), "model": dev.get("model"),
            "w": dev.get("pars", {}).get("w"),
            "l": dev.get("pars", {}).get("l"),
            "quantity": quantity, "required": required, "achieved": achieved,
            "shortfall": (round(required - achieved, 6)
                          if isinstance(required, (int, float))
                          and isinstance(achieved, (int, float)) else None),
            "adjudicator": ADJUDICATOR,
        }
        if detail:
            rec["detail"] = detail
        self.deviations.append(rec)


_CONTACT_SECTION = re.compile(r"cont|c$")


def carried_planes(section: str,
                   layers: Optional["_lim.LayerIdentity"] = None
                   ) -> List[str]:
    """Which CONDUCTOR planes a gencell section's tiles actually occupy.

    In Magic a contact type IS its two conductors plus the cut, so the metal
    a contact carries is NOT in the metal section — the tiles there stop at
    the contact's edge, and the GDS the sign-off deck grades has metal
    everywhere the contact is. A reader that takes `<< metal2 >>` at face
    value is blind to every metal2 rectangle a via1 tile generates.
    `magic_gencell_layout_lib.implicit_metal_sections` measured the same law
    for metal1 (a `psubdiffcont` neighbour a metal1-only reader could not
    see, and 30 notch violations from not seeing it); this is that law
    applied to every level, from the section NAME, so no PDK layer is
    named here.

    MEASURED on delta_sigma, with the island placer already clearing every
    metal2 rectangle it could see: 80 M2.b violations left, all of them
    against device metal2 that exists only in the GDS a via1 tile writes.
    """
    if layers is not None and layers.knows(section):
        # THE PDK'S OWN ANSWER. A contact carries the planes of BOTH its
        # residues; a plain type carries its own. The heuristics below
        # reproduce this for a PDK that spells its conductors `metalN` /
        # `viaN` and get it WRONG for one that does not: on ihp-sg13g2 the
        # `mimcapcontact` a MiM capacitor's top plate is drawn on ends in
        # `cont`, so the guess below registered a metal6 plate as metal1
        # geometry — 960x960 lambda of conductor in the wrong place, and
        # the island placer could not see the plate it had to clear.
        return [section] + [p for p in layers.conductor_planes(section)
                            if p != section]
    out = [section]
    vm = _VIA_RE.match(section)
    if vm and not _METAL_RE.match(section):
        k = int(vm.group(1))
        out += [f"metal{k}", f"metal{k + 1}"]
    elif not _METAL_RE.match(section) and _CONTACT_SECTION.search(section):
        out.append("metal1")
    return out


def device_planes(cell: dict) -> Dict[str, List[Tuple[int, ...]]]:
    """The gencell's geometry as the DECK will see it: one entry per
    conductor plane, with every contact's implied metal folded in."""
    planes: Dict[str, List[Tuple[int, ...]]] = {}
    for section, rects in cell["sections"].items():
        for layer in carried_planes(section, cell.get("layers")):
            if not (_METAL_RE.match(layer) or _VIA_RE.match(layer)):
                continue
            planes.setdefault(layer, []).extend(rects)
    return planes


def _linked(a: str, b: str) -> bool:
    """Two layers a current can cross between: the same metal, the same via,
    or a via and either metal it joins. Derived from the layer NAMES, so a
    PDK with more or fewer levels needs no entry anywhere."""
    if a == b:
        return True
    va, vb = _VIA_RE.match(a), _VIA_RE.match(b)
    ma, mb = _METAL_RE.match(a), _METAL_RE.match(b)
    if va and mb and not _VIA_RE.match(b):
        k = int(va.group(1))
        return int(mb.group(1)) in (k, k + 1)
    if vb and ma and not _VIA_RE.match(a):
        k = int(vb.group(1))
        return int(ma.group(1)) in (k, k + 1)
    return False


def cell_components(cell: dict) -> Dict[Tuple[str, int], int]:
    """Two ids per rectangle: (conductor, same-layer polygon).

    Union-find over the cell's metal and via rectangles: two that touch or
    overlap on electrically linked layers are the same conductor. Magic
    writes a conductor as a TILE DECOMPOSITION, so a terminal's metal is
    many abutting rectangles and a scan that treats each rectangle as its
    own obstacle would call a terminal's own metal foreign to itself."""
    items: List[Tuple[str, int, Tuple[int, ...]]] = []
    for layer, rects in sorted(device_planes(cell).items()):
        for j, r in enumerate(rects):
            items.append((layer, j, tuple(r)))
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        la, _ja, ra = items[i]
        for j in range(i + 1, len(items)):
            lb, _jb, rb = items[j]
            if not _linked(la, lb):
                continue
            if ra[0] > rb[2] or rb[0] > ra[2] or ra[1] > rb[3] or rb[1] > ra[3]:
                continue
            a, b = find(i), find(j)
            if a != b:
                parent[a] = b
    # A SECOND partition, on ONE layer at a time. The first says what is
    # electrically the same conductor; this one says what MERGES INTO ONE
    # POLYGON on the layer the deck is grading. They are not the same
    # question and the deck only ever asks the second: two rectangles of one
    # conductor that meet only through a via are still two polygons on the
    # metal between them, and the spacing rule applies between them exactly
    # as it does between strangers. Exempting a whole conductor from spacing
    # because the island touched it SOMEWHERE is how an island lands two
    # lambda from its own terminal's other metal and the deck answers M2.b.
    lparent = list(range(len(items)))

    def lfind(i: int) -> int:
        while lparent[i] != i:
            lparent[i] = lparent[lparent[i]]
            i = lparent[i]
        return i

    for i in range(len(items)):
        la, _ja, ra = items[i]
        for j in range(i + 1, len(items)):
            lb, _jb, rb = items[j]
            if la != lb:
                continue
            if ra[0] > rb[2] or rb[0] > ra[2] or ra[1] > rb[3] or rb[1] > ra[3]:
                continue
            a, b = lfind(i), lfind(j)
            if a != b:
                lparent[a] = b

    return {(la, ja): (find(i), lfind(i))
            for i, (la, ja, _r) in enumerate(items)}


def floating_device_metal(cell: dict, geo: "Geo") -> List[dict]:
    """Every metal polygon of a gencell child that NO terminal label reaches
    and that is smaller than the deck's minimum area on its own layer.

    A gencell polygon this emitter routes to merges with the routing and is
    graded as part of it. One no label reaches is left exactly as the gencell
    drew it, and the minimum-area rule grades it alone. The two are told apart
    by CONDUCTOR (`cell_components`), and a conductor is reached when a label
    point lies on any of its rectangles — the same containment the router
    uses to find a terminal. Areas are summed over the polygon's rectangles,
    which Magic writes as non-overlapping tiles.

    Each record also names the label LAYER(S) of the sections its conductor
    is drawn over (`sections`): a gate contact the gencell did not label is
    drawn on the same contact type as the one it did, and that is how
    `floating_metal_patches` finds which terminal, and so which net, it is.

    MEASURED, and it is why this exists: the PDK's MOS gencell draws a gate
    contact at BOTH ends of the gate, carries each to metal2 through its own
    via1, and labels only the top one (the bottom is labelled only when there
    is no top contact). Unrouted, the bottom contact's metal2 is the gate
    length times one via pad: 20 (ldo) and 302 (delta_sigma) islands of
    0.0812 and 0.058 um2 under the 0.144 um2 Mn.d rule on u_hawaii_adc, and
    nothing in this emitter looked at geometry it did not route. Returns
    records, never raises."""
    comps = cell_components(cell)
    rects = [(layer, j, r) for layer, rs in sorted(device_planes(cell).items())
             for j, r in enumerate(rs)]
    reached = set()
    for lab in cell.get("labels", []):
        for layer, j, r in rects:
            if r[0] <= lab["x"] <= r[2] and r[1] <= lab["y"] <= r[3]:
                reached.add(comps.get((layer, j), (None, None))[0])
    area: Dict[Tuple[str, int], int] = {}
    boxes: Dict[Tuple[str, int], List[Tuple[int, int, int, int]]] = {}
    conductor: Dict[Tuple[str, int], int] = {}
    for layer, j, r in rects:
        mm = _METAL_RE.match(layer)
        if not mm or _VIA_RE.match(layer):
            continue
        c, lc = comps.get((layer, j), (None, None))
        key = (layer, lc)
        area[key] = area.get(key, 0) + (r[2] - r[0]) * (r[3] - r[1])
        boxes.setdefault(key, []).append(tuple(r))
        conductor[key] = c
    label_layers = {lab.get("layer") for lab in cell.get("labels", [])}
    out = []
    for (layer, lc), a in sorted(area.items(), key=str):
        need = geo.area_lam2.get(int(_METAL_RE.match(layer).group(1)), 0)
        c = conductor[(layer, lc)]
        if c in reached or not need or a >= need:
            continue
        mine = [r for (ly, j, r) in rects
                if comps.get((ly, j), (None, None))[0] == c]
        over = sorted(
            sec for sec, srs in cell["sections"].items()
            if sec in label_layers and any(
                s[0] < m[2] and m[0] < s[2] and s[1] < m[3] and m[1] < s[3]
                for s in srs for m in mine))
        out.append({"layer": layer, "area_lambda2": a,
                    "min_area_lambda2": need, "comp": c,
                    "bbox": _extent(boxes[(layer, lc)]), "sections": over})
    return out


def _clear_but(sites: "Sites", box: Sequence[int], layer: str,
               allowed: set, net: str,
               origin: Sequence[Sequence[int]] = (),
               joins: Sequence[Sequence[int]] = ()) -> bool:
    """`Sites.clear` for a box that is ALLOWED to join several conductors:
    every device conductor in `allowed` may touch it, every other conductor
    must keep the deck's space and must not touch, and this emitter's own
    paint of another net is an obstacle like any device's.

    EUCLIDEAN, where `Sites.clear` is per-axis. A patch sits INSIDE a
    gencell, next to the gencell's own metal at the gencell's own corner
    distances, and the per-axis reading refuses geometry the gencell already
    drew legally: MEASURED on the ldo pass device, every gate-contact island
    is 0.20 um across and 0.14 um up from its own finger's source/drain metal
    — 0.244 um apart against a 0.21 um rule, legal, and refused per-axis, so
    no patch that kept the island's own edge could ever pass. The distance
    here is the one the deck measures; the rectangles it is taken between are
    `parse_cell`'s, already rounded outward.

    `origin`: the polygons the box EXTENDS. A neighbour those already sit
    closer to than the rule (by `parse_cell`'s outward rounding, or because
    the gencell drew them so) is not made worse by a box that comes no
    closer to it than they do, so only a box that comes CLOSER is refused.

    `joins`: this net's own rectangles the caller is joining in the same
    stroke (a patch drawn as two rectangles is checked one at a time)."""
    s = sites.geo.metal_space(layer)

    def d2(a, b) -> int:
        dx = max(b[0] - a[2], a[0] - b[2], 0)
        dy = max(b[1] - a[3], a[1] - b[3], 0)
        return dx * dx + dy * dy

    for r in sites.near(layer, box, s):
        if "lcomp" in r and r.get("comp") in allowed:
            continue
        got = d2(box, r["box"])
        if "lcomp" not in r and r["net"] == net and \
                tuple(r["box"]) in {tuple(j) for j in joins}:
            continue
        if "lcomp" not in r and r["net"] == net:
            # this emitter's own paint of the SAME net: joining it is fine,
            # standing short of it is not — two polygons of one net are
            # still two polygons to the spacing rule (MEASURED: a same-net
            # escape 0.11 um from a patch, M2.b on delta_sigma)
            if got and got < s * s:
                return False
            continue
        if got >= s * s:
            continue
        if got == 0 or not origin or got < min(d2(o, r["box"])
                                                for o in origin):
            return False
    return True


def floating_metal_patches(plan: "Plan", per_dev: Sequence[dict],
                           geo: "Geo", sites: "Sites") -> List[dict]:
    """PLAN a legal area for every unrouted, sub-minimum-area gencell polygon,
    and RESERVE it, before any routing is drawn. `commit_metal_patches`
    paints them after the routing.

    WHOSE IT IS. A polygon no label reaches still belongs to a terminal: it is
    drawn over a section of the same type as one of the device's labels (a
    gate contact on the gate-contact type). When exactly one netlist net's
    labels sit on that type, the polygon is that net's; otherwise it is the
    device's own and every other net keeps clear of the patch.

    HOW IT IS MADE LEGAL — every option that fits, in this order:
      1. GROWN along one axis until it holds the deck's minimum area, into
         space that keeps the deck's spacing from every other conductor;
      2. BRIDGED to the nearest polygon of the SAME net on the same layer —
         the case of a multiplied device, whose stacked gate contacts sit one
         minimum space apart with no room to grow between them.

    WHY TWO PASSES, MEASURED on u_hawaii_adc. Painted before the routing, 302
    of 302 delta_sigma islands grew — and one escape strap, which the plan's
    structure places without asking the index, landed 0.11 um from a patch
    (M2.b). Painted after the routing, 301 of 302 found no room: the escapes
    had taken it. So the first option is RESERVED in the index here — the
    island placer then steers every via island around it — and the options
    are re-checked against the finished routing when they are painted."""
    pending: List[dict] = []
    cache: Dict[int, List[dict]] = {}
    for d in per_dev:
        cell, dev = d["cell"], d["dev"]
        if id(cell) not in cache:
            cache[id(cell)] = floating_device_metal(cell, geo)
        if not cache[id(cell)]:
            continue
        tmap, _ring, _un = terminal_map(dev, cell)
        nets_on: Dict[str, set] = {}
        for net, labs in tmap.items():
            for lab in labs:
                nets_on.setdefault(lab.get("layer"), set()).add(net)
        ox, oy = d["origin"]
        name = dev["name"]
        # which placed device conductor each net's labels reach — a bridge
        # may only join the polygon to one of its OWN net's
        net_comps: Dict[str, set] = {}
        for net, labs in tmap.items():
            for lab in labs:
                lx, ly = ox + lab["x"], oy + lab["y"]
                for r in d["rows"]:
                    b = r["box"]
                    if b[0] <= lx <= b[2] and b[1] <= ly <= b[3]:
                        net_comps.setdefault(net, set()).add(r["comp"])
        for isl in cache[id(cell)]:
            owners = set()
            for sec in isl["sections"]:
                owners |= nets_on.get(sec, set())
            net = next(iter(owners)) if len(owners) == 1 else f"<device {name}>"
            layer = isl["layer"]
            need = isl["min_area_lambda2"]
            x1, y1, x2, y2 = isl["bbox"]
            x1, y1, x2, y2 = x1 + ox, y1 + oy, x2 + ox, y2 + oy
            w, h = x2 - x1, y2 - y1
            me = (name, isl["comp"])
            here = (x1, y1, x2, y2)
            options: List[tuple] = []
            hh = int(math.ceil(need / max(w, 1))) + 1
            ww = int(math.ceil(need / max(h, 1))) + 1
            for box in ((x1, y2 - hh, x2, y2), (x1, y1, x2, y1 + hh),
                        (x2 - ww, y1, x2, y2), (x1, y1, x1 + ww, y2)):
                if _clear_but(sites, box, layer, {me}, net, [here]):
                    options.append(("grown", box, {me}, [here]))
            if not net.startswith("<device "):
                reach = 2 * geo.metal_space(layer)
                best = None
                for r in sites.near(layer, here, reach):
                    if "lcomp" not in r or r.get("comp") == me \
                            or not r["net"].startswith(f"<device {name}>"):
                        continue
                    b = r["box"]
                    ox1, ox2 = max(x1, b[0]), min(x2, b[2])
                    oy1, oy2 = max(y1, b[1]), min(y2, b[3])
                    if ox2 - ox1 >= min(w, b[2] - b[0]):
                        box = (ox1, min(y1, b[1]), ox2, max(y2, b[3]))
                    elif oy2 - oy1 >= min(h, b[3] - b[1]):
                        box = (min(x1, b[0]), oy1, max(x2, b[2]), oy2)
                    else:
                        continue
                    gap = box_separation(here, b)
                    if gap > reach or (best and gap >= best[0]):
                        continue
                    best = (gap, box, r.get("comp"), tuple(b))
                if best and best[2] in net_comps.get(net, ()) \
                        and _clear_but(sites, best[1], layer, {me, best[2]},
                                       net, [here, best[3]]):
                    options.append(("bridged", best[1], {me, best[2]},
                                    [here, best[3]]))
            if options:
                sites.add({"net": net, "layer": layer, "box": options[0][1]})
            pending.append({"dev": dev, "name": name, "net": net,
                            "layer": layer, "here": here, "need": need,
                            "area": isl["area_lambda2"], "options": options})
    return pending


def commit_metal_patches(plan: "Plan", pending: Sequence[dict],
                         sites: "Sites", examined: int) -> dict:
    """Paint the first option of each planned patch that is still clear of
    everything the routing has drawn since; record the ones none is.

    The patches are drawn through `Plan.paint` under the owning net, so the
    short audit sees them. Returns the census for the provenance."""
    census = {"examined": examined, "below_min_area": len(pending),
              "grown": 0, "bridged": 0, "joined": 0, "left": 0,
              "patches": []}
    for p in pending:
        done = next(((kind, box) for kind, box, allowed, origin in p["options"]
                     if _clear_but(sites, box, p["layer"], allowed, p["net"],
                                   origin)), None)
        if done is None and not p["net"].startswith("<device "):
            # THE ROUTING OF THE SAME NET CAME CLOSE: join it instead. An
            # option refused only because this net's own wire now stands
            # short of it is extended over that wire, which makes the two
            # one polygon (MEASURED: one delta_sigma gate contact whose own
            # escape landed 0.11 um below the planned growth).
            s = sites.geo.metal_space(p["layer"])
            for kind, box, allowed, origin in p["options"]:
                near = [r for r in sites.near(p["layer"], box, s)
                        if "lcomp" not in r and r["net"] == p["net"]
                        and 0 < box_separation(box, r["box"]) < s]
                for r in sorted(near, key=lambda r: box_separation(
                        box, r["box"])):
                    b = r["box"]
                    # the patch is stretched along the wire's side to cover
                    # the wire's whole span, and the gap between them is
                    # filled across that span: two full-width rectangles, no
                    # neck thinner than either of them
                    if b[2] < box[0] or b[0] > box[2]:
                        ext = (box[0], min(box[1], b[1]), box[2],
                               max(box[3], b[3]))
                        gx = (b[2], box[0]) if b[2] < box[0] \
                            else (box[2], b[0])
                        fill = (gx[0], b[1], gx[1], b[3])
                    else:
                        ext = (min(box[0], b[0]), box[1], max(box[2], b[2]),
                               box[3])
                        gy = (b[3], box[1]) if b[3] < box[1] \
                            else (box[3], b[1])
                        fill = (b[0], gy[0], b[2], gy[1])
                    if all(_clear_but(sites, q, p["layer"], allowed,
                                      p["net"], list(origin) + [b, box],
                                      joins=[b])
                           for q in (ext, fill)):
                        done = ("joined", ext, fill)
                        break
                if done:
                    break
        if done is None:
            census["left"] += 1
            plan.deviate(p["dev"], "device_metal_island_area_lambda2",
                         p["need"], p["area"],
                         f"an unrouted {p['layer']} polygon of {p['name']} at "
                         f"{list(p['here'])} is below the deck's minimum area "
                         f"and no legal growth or same-net bridge exists; "
                         f"DRAWN as the gencell made it")
            continue
        kind, boxes = done[0], done[1:]
        census[kind] += 1
        for box in boxes:
            plan.paint(p["net"], p["layer"], *box)
            plan.patch_of[(p["layer"], tuple(box))] = p["name"]
        census["patches"].append({"device": p["name"], "net": p["net"],
                                  "layer": p["layer"], "how": kind,
                                  "box": [list(b) for b in boxes]
                                  if len(boxes) > 1 else list(boxes[0])})
    return census


def friendly_conductor(rows: Sequence[dict], layer: str, x: int, y: int,
                       reach: int = 0):
    """Which conductor a terminal at (x, y) belongs to.

    The label's own layer first, by containment; then, because a gencell may
    put a label on a contact layer whose metal begins a lambda away, the
    NEAREST conductor on that layer within `reach`. None when neither
    answers — and None means "no conductor claimed here", which the caller
    treats as "clear everything", never as "clear nothing"."""
    best = None
    for r in rows:
        if r["layer"] != layer:
            continue
        b = r["box"]
        if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
            return r.get("comp")
        if reach:
            dx = max(b[0] - x, x - b[2], 0)
            dy = max(b[1] - y, y - b[3], 0)
            d = max(dx, dy)
            if d <= reach and (best is None or d < best[0]):
                best = (d, r.get("comp"))
    return best[1] if best else None


# ── where a via island may stand ────────────────────────────────────────
#
# THE DEFECT THIS CLOSES, MEASURED (ihp-sg13g2, u_hawaii_adc, image 0.3.46,
# the PDK's own KLayout sign-off deck, 560 rules graded):
#
#   delta_sigma  2780 violations   M2.b 1504  M3.b 654  V1.b 326  M1.b 296
#   ldo           264 violations   M2.b  210  V1.b  42  M1.b  12
#
# and, with the flow's own top-level paint stripped and the gencells left
# exactly where this emitter placed them, the SAME deck on the SAME
# placement reports ZERO. Not one violation on either block is the PDK's
# gencell or this emitter's placement of it; every one is this emitter's
# own paint, and every one is a MINIMUM-SPACING rule on a layer it routes
# on. Of the 2242 that involve a device, every single one has a via island
# as one of its two edges.
#
# The cause is that the island was drawn as a fixed square centred on the
# terminal label, with nothing consulted about what the label sits next to.
# A gencell hands over a terminal on a metal strip 0.16 um tall and leaves
# 0.185 um of legal space above it; a 0.4 um square centred on that strip
# overhangs 0.12 um into the gap at both ends. The emitter already HELD the
# geometry it needed — `Plan.device_shapes` is built before a single wire is
# drawn — and used it only to write the shortfall down afterwards.
#
# So the island is placed, not assumed: this index answers "may a box of
# this size stand here?" for the device geometry, and the search below takes
# the nearest position to the terminal where the answer is yes.
class Sites:
    """The device geometry an island must clear, indexed by layer and cell.

    A device is not ONE obstacle. It is one obstacle per CONDUCTOR, and the
    conductor the terminal sits on is the one the island must OVERLAP
    rather than clear — otherwise the only legal position for a terminal's
    island is off its own terminal. Conductors are found by union-find over
    the gencell's own rectangles on electrically linked layers, so nothing
    here names a device, a net or a PDK.
    """

    CELL = 400            # lambda per bucket side

    def __init__(self, rows: Sequence[dict], geo: Geo) -> None:
        self.geo = geo
        self.grid: Dict[tuple, List[dict]] = {}
        for r in rows:
            self.add(r)

    def add(self, r: dict) -> None:
        """Index one more rectangle. The emitter's OWN paint goes in here as
        it is drawn: an island placed clear of every device and into the
        island of the terminal next door has not been placed either, and
        that is what a wider island makes possible where a narrower one
        could not reach."""
        b = r["box"]
        for gx in range(b[0] // self.CELL, b[2] // self.CELL + 1):
            for gy in range(b[1] // self.CELL, b[3] // self.CELL + 1):
                self.grid.setdefault((r["layer"], gx, gy), []).append(r)

    def near(self, layer: str, box: Sequence[int], m: int) -> List[dict]:
        out: List[dict] = []
        seen: set = set()
        for gx in range((box[0] - m) // self.CELL, (box[2] + m) // self.CELL + 1):
            for gy in range((box[1] - m) // self.CELL,
                            (box[3] + m) // self.CELL + 1):
                for r in self.grid.get((layer, gx, gy), ()):
                    if id(r) not in seen:
                        seen.add(id(r))
                        out.append(r)
        return out

    def clear(self, box: Sequence[int], layers: Sequence[str],
              friendly, net: Optional[str] = None) -> bool:
        """True when a box on `layers` keeps the deck's space from every
        conductor but `friendly`, and touches none of them.

        The test is per-axis (`dx < s and dy < s`), which is the CONSERVATIVE
        reading of a Euclidean spacing rule: every pair the deck would call a
        violation is rejected here, and a few diagonal pairs it would allow
        are rejected too. Refusing a legal position costs a lambda of travel;
        accepting an illegal one costs a violation."""
        for layer in layers:
            s = self.geo.metal_space(layer)
            rows = self.near(layer, box, s)
            merged = set()
            for r in rows:
                if "lcomp" not in r:
                    continue
                b = r["box"]
                if b[0] <= box[2] and box[0] <= b[2] \
                        and b[1] <= box[3] and box[1] <= b[3]:
                    merged.add(r["lcomp"])
            for r in rows:
                if "lcomp" not in r:
                    # this emitter's own paint. One conductor is one net
                    # here, so a same-net rectangle is skipped and every
                    # other one is an obstacle like any device's.
                    if net is not None and r["net"] == net:
                        continue
                    b = r["box"]
                    dx = max(b[0] - box[2], box[0] - b[2], 0)
                    dy = max(b[1] - box[3], box[1] - b[3], 0)
                    if dx < s and dy < s:
                        return False
                    continue
                if r["lcomp"] in merged:
                    # one polygon with this island: no spacing rule applies
                    # between the parts of a single polygon — but a polygon
                    # this island has no business joining is a SHORT.
                    if friendly is None or r.get("comp") != friendly:
                        return False
                    continue
                b = r["box"]
                dx = max(b[0] - box[2], box[0] - b[2], 0)
                dy = max(b[1] - box[3], box[1] - b[3], 0)
                if dx < s and dy < s:
                    return False
        return True

    def touches(self, box: Sequence[int], layer: str, friendly) -> bool:
        """True when the box actually OVERLAPS the conductor it is there to
        connect to. A stack that clears everything by moving off its own
        terminal has not been placed; it has been lost."""
        if friendly is None:
            return True
        for r in self.near(layer, box, 0):
            if "lcomp" not in r or r.get("comp") != friendly:
                continue
            if (r["box"][0] < box[2] and box[0] < r["box"][2]
                    and r["box"][1] < box[3] and box[1] < r["box"][3]):
                return True
        return False


#: How far from its terminal an island may be moved before this emitter
#: stops looking. A stack that needs more than this is reported as a
#: deviation and DRAWN where it was asked for — the deck adjudicates.
ISLAND_SEARCH_LAMBDA = 120

#: The plane this generator runs its lanes and rails on. A terminal handed
#: over ABOVE it has to come down, and where it comes down is the question
#: `build_plan` answers.
ROUTE_LEVEL = 3


def _island_candidates(span: int):
    """Displacements, nearest first: along one axis, then the other, then
    the Manhattan rings. The one-axis passes come first because a terminal
    on a gencell's metal strip has room along that strip and none across
    it, and finding that with two scans instead of a ring saves the search
    from being quadratic in the span for the common case."""
    yield (0, 0)
    for d in range(1, span + 1):
        yield (0, -d)
        yield (0, d)
    for d in range(1, span + 1):
        yield (-d, 0)
        yield (d, 0)
    for r in range(2, span // 4 + 1):
        for dx in range(-r, r + 1):
            rest = r - abs(dx)
            if rest == 0 or dx == 0:
                continue
            yield (dx, rest)
            yield (dx, -rest)


def _via_stack(plan: Plan, net: str, x: int, y: int, level: int, geo: Geo,
               top: int = 3, sites: Optional["Sites"] = None,
               friendly=None, dev: Optional[dict] = None) -> Tuple[int, int]:
    """Carry a terminal from the metal the gencell delivered it on to the
    routing layer, and give every cut the metal the deck demands around it.

    Magic paints a via type as the two metals it joins plus the cut, so the
    stack between any two levels is just the vias between them — in either
    direction, which is how a terminal that lands ABOVE the routing layer
    comes down to it without this file naming the device that put it there.
    The enclosing metal is painted explicitly because the cut alone does not
    satisfy `surround`, and it is sized to the deck's surround AND
    minimum-area rules, both read from the deck.

    The island is ANISOTROPIC (`Geo.short_half` / `Geo.long_half`) and it is
    PLACED: when a `Sites` index is supplied, both orientations are tried at
    the nearest displacement that clears every foreign conductor and still
    overlaps the terminal's own. When no such position exists the island is
    drawn where it was asked for and a deviation is written — this emitter
    records shortfalls, it does not refuse to draw.

    Returns the centre the stack was actually placed at, so the wire that
    leaves it starts where it is rather than where it was asked for."""
    lo, hi = min(level, top), max(level, top)
    if lo == hi:
        return x, y
    metals = list(range(lo, hi + 1))
    vias = list(range(lo, hi))
    layers = [f"metal{k}" for k in metals] + [f"via{k}" for k in vias]
    term_layer = f"metal{level}"

    pad = max(geo.via_pad[k] for k in vias)
    pad_min = max(geo.via_pad_min[k] for k in vias)
    enc_short = max(geo.short_half[k] - geo.via_pad[k] for k in vias)
    enc_long = max(geo.enc_half[k] - geo.via_pad[k] for k in vias)

    # WHICH METAL OF THE STACK MUST CARRY THE MINIMUM AREA ON ITS OWN. The
    # rule is about a REGION, not about a rectangle, so an island that
    # merges into something bigger is not the region the rule grades:
    #   * the terminal metal merges with the conductor it lands on — that is
    #     what `touches` below is made to guarantee;
    #   * the top metal merges with the wire that leaves the stack, which is
    #     painted a few lines after this call and is never small;
    #   * a metal in BETWEEN merges with neither, so it is an island in the
    #     rule's own sense and must meet the area by itself.
    # Claiming the merge for the first two is not a waiver: if the merge does
    # not happen the deck says so, on the same layer, in the same run.
    inter = [k for k in metals if k not in (level, top)]
    area_full = max([geo.area_lam2.get(k, 0) for k in metals] or [0])
    area_min = max([geo.area_lam2.get(k, 0) for k in inter] or [0])

    def halves(p: int, area: int) -> Tuple[int, int]:
        hs = p + enc_short
        by_area = (int(math.ceil(area / (4.0 * hs))) + 1) if area else 0
        return hs, max(p + enc_long, by_area, hs)

    shapes: List[Tuple[int, int, int]] = []
    seen_shapes = set()
    ladder = [(pad, area_full)]
    if friendly is not None and area_min < area_full:
        ladder.append((pad, area_min))
    if pad_min < pad:
        ladder.append((pad_min, area_full))
        if friendly is not None and area_min < area_full:
            ladder.append((pad_min, area_min))
    for p, area in ladder:
        hs, hl = halves(p, area)
        for ax, ay in ((hl, hs), (hs, hl)):
            if (ax, ay, p) not in seen_shapes:
                seen_shapes.add((ax, ay, p))
                shapes.append((ax, ay, p))

    hx, hy, ph = shapes[0]
    cx, cy = x, y
    if sites is not None:
        placed = None
        for (ax, ay, p) in shapes:
            for (dx, dy) in _island_candidates(ISLAND_SEARCH_LAMBDA):
                box = (x + dx - ax, y + dy - ay, x + dx + ax, y + dy + ay)
                if not sites.clear(box, layers, friendly, net):
                    continue
                if not sites.touches(box, term_layer, friendly):
                    continue
                placed = (x + dx, y + dy, ax, ay, p)
                break
            if placed is not None:
                break
        if placed is None:
            plan.deviate(dev or {}, "via_island_clearance_lambda",
                         geo.metal_space(term_layer), 0,
                         f"no position within {ISLAND_SEARCH_LAMBDA} lambda "
                         f"of ({x}, {y}) hosts any of the "
                         f"{len(shapes)} island shapes this deck permits "
                         f"(smallest {2 * shapes[-1][0]}x{2 * shapes[-1][1]} "
                         f"lambda) clear of the neighbouring device geometry "
                         f"while still overlapping this terminal's own "
                         f"metal; DRAWN at the terminal and recorded, never "
                         f"moved off it")
        else:
            cx, cy, hx, hy, ph = placed

    for k in vias:
        plan.paint(net, f"metal{k}", cx - hx, cy - hy, cx + hx, cy + hy)
        plan.paint(net, f"metal{k + 1}", cx - hx, cy - hy, cx + hx, cy + hy)
        plan.paint(net, f"via{k}", cx - ph, cy - ph, cx + ph, cy + ph)
    return cx, cy


def build_plan(devs: Sequence[dict], ports: Sequence[str],
               cells: Dict[tuple, dict], facts: PdkFacts, geo: Geo,
               tap_clear: int, pin_spec: Optional[dict] = None) -> Plan:
    plan = Plan()
    body_tap_contact = body_tap_contact_layer(facts.layers)
    body_tap_metal_contact = body_tap_metal_contact_layer(facts.layers)
    body_tap_local = body_tap_local_layer(facts.layers)
    pitch = geo.pitch()
    pad_half = geo.via_pad[1]
    m1_space = geo.default_space
    hw2 = max(geo.wire[2] // 2, 1)
    hw3 = max(geo.wire[3] // 2, 1)
    min_gap = 4 * pitch

    # ── nets and their rails ──────────────────────────────────────────
    nets: List[str] = []
    for net in list(ports) + [n for d in devs for n in d["nets"]]:
        if net not in nets:
            nets.append(net)
    rail_y = {net: pitch + i * pitch for i, net in enumerate(nets)}
    row_base = pitch * (len(nets) + 24)

    # ── per device: which terminals escape at which height, on which side ──
    per_dev: List[dict] = []
    for dev in devs:
        cell = cells[config_key(dev)]
        tmap, ring, unmapped = terminal_map(dev, cell)
        for term in unmapped:
            plan.deviate(dev, "terminal_mapped", 1, 0,
                         f"the gencell emitted no label for {term}; that "
                         f"netlist terminal is not connected in this layout")
        # a label sitting ON the ring layer is the bulk contact, identified
        # per LABEL and not per net: a device whose source and bulk share a
        # net (a diode-tied bias leg does) would otherwise lose its source
        # terminal along with its bulk one.
        ring_labels = [(n, l) for n, labs in tmap.items() for l in labs
                       if ring and l["layer"] == ring]
        plain = [(n, l) for n, labs in tmap.items() for l in labs
                 if not (ring and l["layer"] == ring)]

        groups: List[dict] = []
        by_ny: Dict[tuple, List[dict]] = {}
        for net, lab in plain:
            by_ny.setdefault((net, lab["y"]), []).append(lab)
        for (net, y), glabs in by_ny.items():
            groups.append({"net": net, "y": y, "labels": glabs,
                           "level": min(l["level"] for l in glabs)})

        # A group of ONE contact escapes at its own height. A group of SEVERAL
        # contacts on one row — the fingers of a multi-finger device — must
        # first be tied together, and the strap cannot sit on that row: the
        # other net's fingers are interleaved with it. So it is reserved a
        # height OUTSIDE the device, alternately below and above, one strap
        # per row of its own. Every stub then runs away from the shared
        # contact row in one direction only, which is what keeps a drain
        # strap clear of the source stubs it passes.
        bx1, by1, bx2, by2 = cell["bbox"]
        n_below = n_above = 0
        for g in sorted(groups, key=lambda g: (-len(g["labels"]), g["y"])):
            if len(g["labels"]) == 1:
                g["escape_y"] = g["y"]
                g["strapped"] = False
                continue
            g["strapped"] = True
            if n_below <= n_above:
                n_below += 1
                g["escape_y"] = by1 - n_below * pitch
            else:
                n_above += 1
                g["escape_y"] = by2 + n_above * pitch

        plan.bulk_tap_considered += 1
        if ring_labels:
            plan.bulk_tap_examined += 1
            plan.bulk_tap_searched.append(dev.get("name"))
            plan.bulk_tap_ring_layer[dev.get("name")] = ring or ""
        else:
            # TAPPABLE separates the two zeroes. A device whose gencell child
            # draws two or more of the body-contact types the technology file
            # declares has a body connection distinct from its own signal
            # contacts, so a ring it does not have is a MISS. One that draws
            # fewer has nothing to tap, and its zero is a property of the
            # device. Measured on u_hawaii_adc: every MOS draws 3, every
            # resistor 2, every MiM capacitor 1.
            cands = body_contact_layers(cell)
            plan.bulk_tap_unexamined.append({
                "device": dev.get("name"), "model": dev.get("model"),
                "ring_layer": ring,
                "body_contact_layers": cands,
                "tappable": len(cands) >= 2,
                "reason": ("ring_layer_of identifies no guard-ring layer in "
                           "this gencell's output" if ring is None else
                           f"the gencell emits no terminal label on the "
                           f"guard-ring layer {ring}"),
            })
        if ring_labels:
            others = [(l["x"] - pad_half, l["y"] - pad_half,
                       l["x"] + pad_half, l["y"] + pad_half)
                      for _, l in plain]
            rows = sorted({g["escape_y"] for g in groups})
            forbidden = [(y - pitch + 1, y + pitch - 1) for y in rows]
            best = choose_tap(cell["sections"].get(ring, []), others,
                              forbidden, pad_half)
            if best is None:
                # I5 — a structure that cannot host the connection at all is
                # REFUSED by name, with what was measured, not asserted.
                raise Refusal(
                    f"{dev['name']} ({dev['model']} "
                    f"w={dev['pars'].get('w')}u l={dev['pars'].get('l')}u): "
                    f"its guard ring on layer {ring} offers no position that "
                    f"can host a {2 * pad_half}-lambda bulk tap. The device "
                    f"is legal; the RING is too small to tap.")
            tx, ty, clear, rows_ok = best
            if clear < tap_clear:
                plan.deviate(dev, "bulk_tap_clearance_lambda", tap_clear,
                             clear,
                             f"the best position on the guard ring clears "
                             f"the nearest terminal by {clear} lambda "
                             f"centre-to-centre; the floor is Metal1 space "
                             f"{m1_space} + tap pad {pad_half} + terminal "
                             f"pad {pad_half}. DRAWN and recorded, never "
                             f"refused")
            if not rows_ok:
                plan.deviate(dev, "bulk_tap_row_separation_lambda", pitch, 0,
                             "every position on the guard ring lies in the "
                             "escape band of another terminal row; the tap "
                             "is drawn at the clearest of them")
            direct_m1 = body_tap_direct_m1_layer(facts.layers, ring)
            dev_body_tap_contact = None if direct_m1 else body_tap_contact
            if dev_body_tap_contact is None and direct_m1 is None:
                plan.deviate(
                    dev, "body_tap_contact_layer", 1, 0,
                    "the loaded Magic technology declares no contact joining "
                    "the gencell's local-interconnect residue to metal1; the "
                    "body tap is left unconnected rather than guessed")
            groups.append({"net": ring_labels[0][0], "y": ty,
                           "escape_y": ty, "strapped": False,
                           "labels": [{"x": tx, "y": ty, "level": 1,
                                       "name": "tap"}],
                           "body_tap_contact": dev_body_tap_contact,
                           "body_tap_metal_contact": (None
                                                       if direct_m1
                                                       else body_tap_metal_contact),
                           "body_tap_local": (None if direct_m1
                                               else body_tap_local),
                           "body_tap_direct_m1": direct_m1,
                           "level": 1})

        # two groups escaping at one height take opposite sides, so their
        # metal3 runs are on opposite sides of the device and never meet
        for y in sorted({g["escape_y"] for g in groups}):
            row = sorted([g for g in groups if g["escape_y"] == y],
                         key=lambda g: min(l["x"] for l in g["labels"]))
            for idx, g in enumerate(row):
                g["side"] = "left" if idx % 2 == 0 else "right"
                if idx >= 2:
                    plan.deviate(
                        dev, "escape_sides_available", 2, idx + 1,
                        f"{idx + 1} nets escape at height {y}; only two "
                        f"sides exist, so this group shares a side")

        # SAME SIDE, DIFFERENT HEIGHT IS NOT AUTOMATICALLY CLEAR. Opposite
        # sides were the only separation this plan had, and it was applied
        # only to groups at the SAME height. A group of one contact escapes
        # at its own label's height, and a gencell's label rows are on the
        # gencell's grid, not on this generator's: two nets whose contacts
        # sit 47 lambda apart both went left, and their escape wires ran
        # parallel 17 lambda apart against a 21 lambda rule.
        #
        # MEASURED on delta_sigma with the island placer already in: 246
        # M3.b and 125 M2.b left, every one of them two escapes of one
        # device on one side. So the heights on a side are SPREAD to the
        # pitch the deck's own width and spacing require, upward, in the
        # order they already had — an escape never crosses one that started
        # below it, which is the property the lane allocation below rests on.
        # THE WIRE IS NOT THE TALLEST THING AT AN ESCAPE HEIGHT. Spacing the
        # heights by wire-width-plus-space left exactly 20 lambda against a
        # 21 lambda rule wherever the neighbour was a via ISLAND rather than
        # a wire — the island is 48 lambda across its long axis, the wire is
        # 30, and the placer may point either axis along the escape. So the
        # pitch is built from the WIDEST thing this generator paints at a
        # height, which is the island's long side. Measured: the last 18
        # M3.b on delta_sigma, every one of them an island against the
        # escape one slot above it.
        esc_pitch = max(max(geo.wire[k], 2 * geo.long_half[k])
                        + geo.metal_space(f"metal{k}") for k in (2, 3))
        for side in ("left", "right"):
            prev = None
            for g in sorted([g for g in groups if g["side"] == side],
                            key=lambda g: g["escape_y"]):
                if prev is not None and g["escape_y"] - prev < esc_pitch:
                    g["escape_y"] = prev + esc_pitch
                prev = g["escape_y"]
        per_dev.append({"dev": dev, "cell": cell, "groups": groups,
                        "bbox": cell["bbox"]})

    # ── corridors wide enough for the lanes they must carry ───────────
    n_left = [sum(1 for g in d["groups"] if g["side"] == "left")
              for d in per_dev]
    n_right = [sum(1 for g in d["groups"] if g["side"] == "right")
               for d in per_dev]
    gap_w = []
    for i in range(len(per_dev) + 1):
        need = (n_right[i - 1] if i > 0 else 0) + \
               (n_left[i] if i < len(per_dev) else 0)
        gap_w.append(max(min_gap, (need + 2) * pitch))

    x = 0
    for i, d in enumerate(per_dev):
        x += gap_w[i]
        d["box_x"] = x
        d["gap_hi"] = x
        x += d["bbox"][2] - d["bbox"][0]
        d["right_lo"] = x

    # ── the layout pass, in the order Magic will execute it ───────────
    for i, d in enumerate(per_dev):
        plan.tcl.append(f"box {d['box_x']} {row_base} "
                        f"{d['box_x']} {row_base}")
        plan.tcl.append(gencell_call(d["dev"], f"d{i}", facts))
        d["origin"] = (d["box_x"] + d["cell"]["delta"][0],
                       row_base + d["cell"]["delta"][1])

    comp_cache: Dict[int, Dict[Tuple[str, int], int]] = {}
    for d in per_dev:
        ox, oy = d["origin"]
        cell = d["cell"]
        if id(cell) not in comp_cache:
            comp_cache[id(cell)] = cell_components(cell)
        comps = comp_cache[id(cell)]
        name = d["dev"]["name"]
        rows: List[dict] = []
        for layer, rects in sorted(device_planes(cell).items()):
            for j, r in enumerate(rects):
                c, lc = comps.get((layer, j), (-1, -1))
                rows.append(
                    {"net": f"<device {name}>", "layer": layer,
                     "comp": (name, c), "lcomp": (name, layer, lc),
                     "box": (ox + r[0], oy + r[1], ox + r[2], oy + r[3])})
        d["rows"] = rows
        plan.device_shapes.extend(rows)
        for g in d["groups"]:
            g["abs_labels"] = [(ox + l["x"], oy + l["y"], l["level"])
                               for l in g["labels"]]
            g["abs_escape_y"] = oy + g["escape_y"]

    # The index is built ONCE, after every device is placed and before a
    # single wire is drawn: the routing runs closest to the devices, and a
    # placer that cannot see them places into them.
    sites = Sites(plan.device_shapes, geo)
    plan.sites = sites
    # What the gencells leave unrouted and too small: planned and reserved
    # now, painted after the routing (see `floating_metal_patches`).
    patches = floating_metal_patches(plan, per_dev, geo, sites)

    # Lanes are handed out in order of the height they come from: the lane
    # nearest the device serves the LOWEST escape. An escape therefore never
    # crosses the lane of an escape that started below it, and the lane of an
    # escape that started above it stops short of this one's height.
    for d in per_dev:
        for side, base, step in (("right", d["right_lo"], 1),
                                 ("left", d["gap_hi"], -1)):
            gs = sorted([g for g in d["groups"] if g["side"] == side],
                        key=lambda g: g["abs_escape_y"])
            for k, g in enumerate(gs):
                g["lane_x"] = base + step * (k + 1) * pitch

    for d in per_dev:
        for g in d["groups"]:
            net, ey, lane = g["net"], g["abs_escape_y"], g["lane_x"]
            tap_contact = g.get("body_tap_contact")
            tap_metal_contact = g.get("body_tap_metal_contact")
            tap_local = g.get("body_tap_local")
            if tap_contact:
                tx, ty, _ = g["abs_labels"][0]
                # The gencell's body label is on a device-contact layer whose
                # local-interconnect residue is already present in the child.
                # Paint only the PDK-derived local-to-metal1 contact here;
                # `_via_stack` then carries that conductor through metal1/2/3.
                hp = geo.via_pad[1]
                if tap_local:
                    plan.paint(net, tap_local, tx - hp, ty - hp,
                               tx + hp, ty + hp)
                plan.paint(net, tap_contact, tx - hp, ty - hp,
                           tx + hp, ty + hp)
                if tap_metal_contact:
                    plan.paint(net, tap_metal_contact, tx - hp, ty - hp,
                               tx + hp, ty + hp)
            if g["strapped"]:
                # THE STUB STARTS WHERE THE STACK ENDED UP. An island that
                # was moved a lambda off its label and then wired from the
                # label is not connected to itself.
                xs = []
                for (lx, ly, level) in g["abs_labels"]:
                    fr = friendly_conductor(d["rows"], f"metal{level}", lx, ly,
                                            reach=geo.default_space)
                    cx, cy = _via_stack(plan, net, lx, ly, level, geo, top=2,
                                        sites=sites, friendly=fr,
                                        dev=d["dev"])
                    xs.append(cx)
                    plan.paint(net, "metal2", cx - hw2, min(cy, ey),
                               cx + hw2, max(cy, ey))
                plan.paint(net, "metal2", min(xs) - hw2, ey - hw2,
                           max(xs) + hw2, ey + hw2)
                joint = max(xs) if g["side"] == "right" else min(xs)
                _via_stack(plan, net, joint, ey, 2, geo, top=3, sites=sites)
            elif g["level"] > ROUTE_LEVEL:
                # THE TERMINAL IS DELIVERED ABOVE THE ROUTING LAYER, and
                # every plane between the two is the DEVICE'S OWN.
                #
                # MEASURED on u_hawaii_adc (ihp-sg13g2, image 0.3.46). A MiM
                # capacitor hands its top plate over on metal6 and its
                # bottom plate on metal5, and the bottom plate is one
                # rectangle covering the WHOLE device. A stack dropped at
                # the top-plate terminal to come down to metal3 therefore
                # paints this net's metal5 island directly onto the other
                # terminal's plate: the two plates become one conductor, the
                # capacitor is shorted, and the sign-off LVS answers
                # `mismatch`. The island placer cannot rescue it — the plate
                # is 1120 lambda across and no position within
                # `ISLAND_SEARCH_LAMBDA` of the terminal is off it. The same
                # descent puts a via4 on the plate, which this PDK's deck
                # forbids outright (`spacing mimcap via4/m5`, 8 of them on
                # `delta_sigma` under Magic).
                #
                # So a terminal delivered above the routing layer LEAVES on
                # its own plane first and comes down at its lane, which is
                # outside the device by construction. Nothing here names a
                # device, a layer or a PDK: the level is the one the PDK's
                # layer table reported for the type the label sits on, and a
                # terminal at or below the routing layer is untouched.
                lx, ly, level = g["abs_labels"][0]
                esc, ex, ey0 = level, lx, ly
                sect = g["labels"][0].get("layer", "")
                if facts.layers is not None \
                        and facts.layers.device_electrode_contact(sect) \
                        and (level + 1) in geo.wire:
                    # AND WHEN THE PLANE IT ARRIVES ON IS THE DEVICE'S OWN
                    # ELECTRODE, IT GOES UP ONE MORE BEFORE IT LEAVES.
                    #
                    # A contact IS its residues, so this terminal's metal
                    # has exactly the electrode's footprint; a wire on that
                    # plane taken out of the contact crosses the
                    # electrode's edge, and that is the geometry a PDK
                    # writes an electrode-spacing rule about. MEASURED on a
                    # two-cell fixture (the PDK's own gencell child plus one
                    # painted stub, magic `drc style drc(full)`): the child
                    # alone 0, the contact covered but not left 0, a stub
                    # from the contact's own edge 1, from the plate centre
                    # 1, over the whole plate 4 — and the contact-sized pad
                    # plus one via up plus a stub on the plane ABOVE, 0. The
                    # rule is `analog_a5_pdk_device_limits.LayerIdentity.
                    # device_electrode_contact` and it names no device.
                    esc = level + 1
                    fr = friendly_conductor(d["rows"], f"metal{level}",
                                            lx, ly, reach=geo.default_space)
                    ex, ey0 = _via_stack(plan, net, lx, ly, level, geo,
                                         top=esc, sites=sites, friendly=fr,
                                         dev=d["dev"])
                hwt = max(geo.wire[esc] // 2, 1)
                plan.paint(net, f"metal{esc}",
                           min(ex, lane) - hwt, ey0 - hwt,
                           max(ex, lane) + hwt, ey0 + hwt)
                cx, cy = _via_stack(plan, net, lane, ey0, esc, geo,
                                    top=ROUTE_LEVEL, sites=sites,
                                    dev=d["dev"])
                joint = cx
                if cy != ey:
                    plan.paint(net, "metal3", cx - hw3, min(cy, ey) - hw3,
                               cx + hw3, max(cy, ey) + hw3)
            else:
                lx, ly, level = g["abs_labels"][0]
                fr = friendly_conductor(d["rows"], f"metal{level}", lx, ly,
                                        reach=geo.default_space)
                cx, cy = _via_stack(plan, net, lx, ly, level, geo,
                                    top=ROUTE_LEVEL,
                                    sites=sites, friendly=fr, dev=d["dev"])
                joint = cx
                if cy != ey:
                    # a metal3 jog back to the escape height. Metal3 is the
                    # one routed layer no gencell in this PDK paints, so the
                    # jog is free of the geometry the island had to leave —
                    # and keeping the escape at its own height is what stops
                    # one moved island from re-ordering every lane.
                    plan.paint(net, "metal3", cx - hw3, min(cy, ey) - hw3,
                               cx + hw3, max(cy, ey) + hw3)
            # across to the lane on metal3, then straight down to the rail
            plan.paint(net, "metal3", min(joint, lane) - hw3, ey - hw3,
                       max(joint, lane) + hw3, ey + hw3)
            plan.paint(net, "metal3", lane - hw3, rail_y[net], lane + hw3, ey)
            _via_stack(plan, net, lane, rail_y[net], 2, geo, top=3,
                       sites=sites)

    plan.island_patches = commit_metal_patches(plan, patches, sites,
                                               len(per_dev))

    # ── one metal2 rail per net, and a label on each declared port ──────
    rail_box: Dict[str, Tuple[int, int, int, int]] = {}
    for net in nets:
        xs = [g["lane_x"] for d in per_dev for g in d["groups"]
              if g["net"] == net]
        if not xs:
            continue
        ty = rail_y[net]
        plan.paint(net, "metal2", min(xs) - pitch, ty - hw2,
                   max(xs) + pitch, ty + hw2)
        rail_box[net] = (min(xs) - pitch, ty - hw2, max(xs) + pitch, ty + hw2)
        if net not in ports or not pin_spec:
            plan.ports.append((net, min(xs), ty))

    plan.row_base = row_base
    plan.port_nets = [n for n in nets if n in ports]
    if pin_spec:
        top_y = max([r["box"][3] for r in plan.shapes]
                    + [r["box"][3] for r in plan.device_shapes]
                    + [d["origin"][1] + d["cell"]["bbox"][3]
                       for d in per_dev] + [0])
        _draw_pins(plan, [n for n in ports if n in rail_box], rail_box,
                   pin_spec, geo, sites, top_y, pitch)
    return plan


# ──────────────────────────────────────────────────────────────────────
# 6b. the macro's pins — what the abstract is placed and powered by
# ──────────────────────────────────────────────────────────────────────
# THE DEFECT THIS CLOSES, MEASURED (u_hawaii_adc, ihp-sg13g2, vibeic-eda
# 0.3.79). Each declared port used to be labelled at a ZERO-AREA point on its
# metal2 rail, the point where the rail's via landing sits. Magic moved the
# label onto the via it sat on (DBPickLabelLayer), the GDS writer emits a pin
# boundary only for a label with area (CalmaWrite.c), and a GDS read turns
# text into a port only from a pin boundary (CalmaRdpt.c) — so the A8
# abstract, written by `gds read` + `lef write`, had SIZE and OBS and ZERO
# pins, on both blocks. A macro with no pins cannot be connected at all.
#
# The rule the pins follow now (analog decision q2-pin-layer):
#   * every declared port is a RECTANGULAR label on PURE routing metal —
#     never a point, never a cut layer, never the lowest metal;
#   * a signal port is a vertical stub on the lowest vertical routing layer
#     above this generator's own routing that is not a PDN strap layer,
#     running down to the macro's rail-side (bottom) boundary, so a router
#     reaches it from outside without crossing the obstruction;
#   * a supply port is a full-height stripe on the vertical layer of the
#     PDK's top strap pair, which is where the power grid's straps cross it.
# Which layers those are is read from the PDK's tech LEF (`pin_layers`); no
# layer is named here.
def tech_lef_layers(text: str) -> List[dict]:
    """`{name, type, direction, pitch, width, dc_density}` for every ROUTING and
    CUT layer of a tech LEF, in declaration order (bottom to top). Pure LEF
    grammar; an unparseable text gives `[]`, which callers read as ABSENT."""
    out: List[dict] = []
    cur: Optional[dict] = None
    for raw in (text or "").splitlines():
        s = raw.split("#", 1)[0].strip()
        m = re.match(r"^LAYER\s+(\S+)\s*$", s)
        if m:
            cur = {"name": m.group(1), "type": "", "direction": "",
                   "pitch": None, "width": None, "dc_density": None}
            out.append(cur)
            continue
        if cur is None:
            continue
        if re.match(r"^END\s+" + re.escape(cur["name"]) + r"\s*$", s):
            cur = None
            continue
        tok = s.rstrip(";").split()
        if not tok:
            continue
        key = tok[0].upper()
        try:
            if key == "TYPE" and len(tok) > 1 and not cur["type"]:
                cur["type"] = tok[1].upper()
            elif key == "DIRECTION" and len(tok) > 1 and not cur["direction"]:
                cur["direction"] = tok[1].upper()
            elif key == "PITCH" and len(tok) > 1 and cur["pitch"] is None:
                cur["pitch"] = float(tok[1])
            elif key == "WIDTH" and len(tok) == 2 and cur["width"] is None:
                cur["width"] = float(tok[1])
            elif key == "DCCURRENTDENSITY" and len(tok) > 2 \
                    and tok[1].upper() == "AVERAGE" \
                    and cur["dc_density"] is None:
                cur["dc_density"] = float(tok[2])
        except ValueError:
            continue
    return [r for r in out if r["type"] in ("ROUTING", "CUT")]


def pin_layers(lef_layers: Sequence[dict], wired: Sequence[int],
               magic_layers: Optional["_lim.LayerIdentity"] = None
               ) -> Tuple[Optional[int], Optional[int], dict]:
    """(signal level, supply level, basis) from the tech LEF's layer table.

    Level k is the k-th ROUTING layer, which is Magic's `metal{k}` — the
    numbering this emitter already routes by. `wired` is the set of levels
    this generator can size (its deck read).

    SUPPLY: the vertical layer of the top two routing layers — the pair a
    power grid straps with, so a full-height stripe there is crossed by the
    other strap layer of the pair.
    SIGNAL: the lowest VERTICAL routing layer above ROUTE_LEVEL (so none of
    this generator's own lanes and rails are on it) that is not one of those
    two strap layers. Vertical, because the pin sits on the bottom edge and is
    approached along the layer's preferred direction.
    If there is no such vertical layer, a HORIZONTAL layer at ROUTE_LEVEL
    may carry a side-facing pin via an extension of the existing metal2 rail.
    None for either means the LEF does not offer one; the caller records it."""
    routing = [r for r in lef_layers if r["type"] == "ROUTING"]
    # The LEF may list a local-interconnect routing layer before the first
    # Magic ``metal1`` alias.  It is electrically real, but it is not the
    # ``metal1`` that the existing A5 writer paints.  Use the Magic
    # technology's own aliases to align the LEF rows with the writer's
    # ``metalN`` levels; only a leading run before the first matched alias is
    # removed.  Later unmatched rows (for example vendor top-metal aliases)
    # remain visible to the existing strap selection instead of being guessed
    # away.
    if magic_layers is not None:
        aliases = set()
        for alias, canonical in magic_layers.canon.items():
            plane = magic_layers.plane_of.get(canonical, "")
            if re.fullmatch(r"metal\d+", str(plane), re.IGNORECASE):
                aliases.add(str(alias).lower())
        first = next((i for i, row in enumerate(routing)
                      if str(row.get("name", "")).lower() in aliases), None)
        if first:
            dropped = routing[:first]
            routing = routing[first:]
        else:
            dropped = []
    else:
        dropped = []
    lvl = {i + 1: r for i, r in enumerate(routing)}
    top2 = sorted(lvl)[-2:]
    supply = next((k for k in sorted(top2, reverse=True)
                   if lvl[k]["direction"] == "VERTICAL" and k in wired), None)
    signal = next((k for k in sorted(lvl)
                   if k > ROUTE_LEVEL and k not in top2 and k in wired
                   and lvl[k]["direction"] == "VERTICAL"), None)
    if signal is None:
        # A downward signal stub on metal2 crosses the other metal2 rails.
        # A horizontal layer can instead face the side boundary, reached by
        # extending that port's own metal2 rail on its existing row.  Keep
        # the strap pair reserved and derive the direction from the same LEF.
        signal = next((k for k in sorted(lvl)
                       if k >= ROUTE_LEVEL and k not in top2 and k in wired
                       and lvl[k]["direction"] == "HORIZONTAL"), None)
    basis = {"routing_layers": [r["name"] for r in routing],
             "strap_pair": [lvl[k]["name"] for k in top2],
             "signal_layer": lvl[signal]["name"] if signal else None,
             "supply_layer": lvl[supply]["name"] if supply else None}
    if dropped:
        basis["leading_non_magic_routing_layers"] = [r["name"] for r in dropped]
    return signal, supply, basis


#: the block's declared rail ROLE -> the pin USE it is labelled with. The
#: same vocabulary A8's `annotate_pg_pins` reads, so both ends agree.
RAIL_ROLE_USE = {"vdd": "power", "vcc": "power", "vpwr": "power",
                 "vss": "ground", "gnd": "ground", "vgnd": "ground"}

_CURRENT_UNIT_MA = {"a": 1e3, "ma": 1.0, "ua": 1e-3, "µa": 1e-3,
                    "μa": 1e-3, "na": 1e-6}


def declared_current_ma(spec: Optional[dict]) -> Tuple[Optional[float], str]:
    """The largest current the block's A1 spec declares, in mA, and the row
    it came from — or (None, reason).

    A spec row states a current for the BLOCK, not for a port: nothing in the
    spec says which port carries `iout`. So the largest declared current is the
    bound every port is sized for — a port cannot be sized for a smaller
    current than one the block declares without knowing it does not carry it.
    The row's `max` is used where it has one, else its `target`."""
    best: Tuple[Optional[float], str] = (None, "")
    for row in (spec or {}).get("specs") or []:
        unit = str(row.get("unit") or "").strip().lower().replace(" ", "")
        mult = _CURRENT_UNIT_MA.get(unit)
        if mult is None:
            continue
        for field in ("max", "target"):
            v = row.get(field)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                ma = float(v) * mult
                if best[0] is None or ma > best[0]:
                    best = (ma, f"spec.json `{row.get('name')}`.{field} = "
                                f"{v} {row.get('unit')}")
                break
    if best[0] is None:
        return None, "the block spec declares no current"
    return best


def pin_spec_for(ports: Sequence[str], rails: Optional[dict],
                 spec: Optional[dict], facts: "PdkFacts", geo: "Geo"
                 ) -> Tuple[Optional[dict], dict]:
    """What every declared port becomes as a pin: its layer, USE, width and
    cuts per via, each with the source it came from. (None, basis) when the
    tech LEF offers no layer to put it on — recorded, never guessed."""
    basis: dict = {"tech_lef": facts.sources.get("tech_lef"),
                   "tech_lef_sha256": facts.tech_lef_sha256,
                   "core_pg": dict(facts.core_pg)}
    if not facts.tech_lef:
        basis["result"] = "NOT_DETERMINED"
        basis["reason"] = ("no tech LEF was readable, so the routing layers, "
                           "their directions and the PDK's strap layers are "
                           "unknown; the ports keep their rail labels")
        return None, basis
    signal, supply, lb = pin_layers(facts.tech_lef, sorted(geo.wire),
                                    facts.layers)
    basis.update(lb)
    # the PDK's own layer table, as read, so a reader of the abstract (the A8
    # gate) can ask the same PDN planner PnR uses without the PDK on its host
    basis["tech_lef_layers"] = [dict(r) for r in facts.tech_lef]
    routing = [r for r in facts.tech_lef if r["type"] == "ROUTING"
               and r["name"] in lb["routing_layers"]]
    # The cut BETWEEN routing layers k and k+1 is Magic's `via{k}`: the CUT
    # the LEF declares after its k-th ROUTING layer. A cut before the first
    # routing layer (the device contact) is no via of this stack.
    cut_of: Dict[int, dict] = {}
    seen = -len(lb.get("leading_non_magic_routing_layers", []))
    for r in facts.tech_lef:
        if r["type"] == "ROUTING":
            seen += 1
        elif seen > 0 and seen not in cut_of:
            cut_of[seen] = r
    if rails is None:
        basis["pin_roles_source"] = "absent"
        role_of: Dict[str, str] = {}
    else:
        basis["pin_roles_source"] = "topology.json rails"
        role_of = {str(v): str(k).strip().lower()
                   for k, v in (rails or {}).items()}
    i_ma, i_src = declared_current_ma(spec)
    basis["current_bound_mA"] = i_ma
    basis["current_source"] = i_src
    out: dict = {}
    for i, net in enumerate(ports):
        is_rail = net in role_of
        level = supply if is_rail else signal
        if level is None:
            basis["result"] = "NOT_DETERMINED"
            basis["reason"] = (f"the tech LEF offers no "
                               f"{'supply' if is_rail else 'signal'} pin "
                               f"layer by the rule in `pin_layers`")
            return None, basis
        lef = routing[level - 1]
        rec = {"index": i + 1, "rail": is_rail, "level": level,
               "lef_layer": lef["name"], "lef_type": lef["type"],
               "direction": lef["direction"],
               "use": (RAIL_ROLE_USE.get(role_of[net]) if is_rail
                       else "signal"),
               "width_lam": geo.wire.get(level, 1), "cuts": 1,
               "em": {"result": "NOT_MEASURED", "reason": i_src}}
        if i_ma is not None:
            # THE EM RULE: the tech LEF's own `DCCURRENTDENSITY AVERAGE` —
            # mA per um of width for a routing layer, mA per cut for a cut
            # layer — the table `em_current_density_check` grades. The pin
            # strip is at least I/J wide, and every via level of its stack
            # carries at least I/J_cut cuts. The deck minimum is the floor.
            j = lef.get("dc_density")
            em = {"current_mA": i_ma, "current_source": i_src,
                  "rule": (f"{basis['tech_lef']} LAYER {lef['name']} "
                           f"DCCURRENTDENSITY AVERAGE {j} (mA/um)")
                  if j else None}
            if j:
                w_um = i_ma / j
                rec["width_lam"] = max(rec["width_lam"],
                                       int(math.ceil(w_um * geo.lam - 1e-9)))
                em["width_um_required"] = round(w_um, 4)
            stack = [cut_of.get(k) for k in range(2, level)]
            if stack and all(c and c.get("dc_density") for c in stack):
                rec["cuts"] = max(int(math.ceil(i_ma / c["dc_density"] - 1e-9))
                                  for c in stack)
                em["cut_rule"] = [f"LAYER {c['name']} DCCURRENTDENSITY "
                                  f"AVERAGE {c['dc_density']} (mA/cut)"
                                  for c in stack]
            em["result"] = "SIZED" if j else "NOT_MEASURED"
            rec["em"] = em
        out[net] = rec
    basis["result"] = "DETERMINED"
    return {"ports": out}, basis


def _pin_stack_boxes(x: int, y: int, lo: int, hi: int, geo: "Geo",
                     cuts: int) -> Tuple[List[Tuple[str, Tuple[int, ...]]],
                                         Dict[int, Tuple[int, int, int, int]]]:
    """The rectangles of a via stack from metal `lo` to metal `hi` at (x, y)
    carrying `cuts` cuts per level in a row along x: every via square, and one
    metal bar per level enclosing its cuts at the deck's surround and area
    (`Geo.long_half`, which is sized for both)."""
    vias = list(range(lo, hi))
    # A signal pin may legitimately land on the generator's metal2 rail.  In
    # that case the stack has no via levels; it still needs one real metal2
    # rectangle, but taking ``max`` over an empty via sequence would abort A5
    # before the geometry is emitted.
    p = (max(2 * geo.via_pad[k] + geo.rules_via_space(k) for k in vias)
         if vias else 1)
    offs = [i * p - ((cuts - 1) * p) // 2 for i in range(cuts)]
    paint: List[Tuple[str, Tuple[int, ...]]] = []
    bars: Dict[int, Tuple[int, int, int, int]] = {}
    for m in range(lo, hi + 1):
        # the bar is at least the layer's own minimum width across, or the
        # bar sticking out of a wide strip is a width violation (TM1.a,
        # measured: 4 on ldo before this floor)
        h = max([geo.long_half[k] for k in vias if k in (m - 1, m)]
                + [(geo.wire.get(m, 1) + 1) // 2])
        bars[m] = (x + offs[0] - h, y - h, x + offs[-1] + h, y + h)
        paint.append((f"metal{m}", bars[m]))
    for k in vias:
        ph = geo.via_pad[k]
        for o in offs:
            paint.append((f"via{k}", (x + o - ph, y - ph, x + o + ph, y + ph)))
    return paint, bars


def _draw_pins(plan: "Plan", ports: Sequence[str],
               rail_box: Dict[str, Tuple[int, int, int, int]], pin_spec: dict,
               geo: "Geo", sites: "Sites", top_y: int, pitch: int) -> None:
    """Bring each declared port from its metal2 rail to its pin layer, at the
    first position along the rail where the stack AND the stub or stripe keep
    the deck's space from every other conductor, and record the pin.

    Supplies first: a stripe spans the whole block and is the harder one to
    seat, and every signal stub is then placed clear of it. A port with no
    clear site is a producer refusal: emitting that fallback would make a
    known cross-net short part of the layout."""
    order = sorted(ports, key=lambda n: (not pin_spec["ports"][n]["rail"],
                                         ports.index(n)))
    for net in order:
        spec = pin_spec["ports"][net]
        level = spec["level"]
        rx1, ry1, rx2, ry2 = rail_box[net]
        y = (ry1 + ry2) // 2
        half = max(spec["width_lam"] // 2, geo.wire.get(level, 1) // 2, 1)
        cuts = max(1, spec["cuts"])
        if not spec["rail"] and spec.get("direction") == "HORIZONTAL":
            # Leave on the port's own rail row, below the device routing,
            # then rise at the side margin.  A vertical metal2 pin would
            # electrically join every lower rail it crossed (R1c native).
            edge = min([0] + [r["box"][0] for r in plan.shapes]
                       + [r["box"][0] for r in plan.device_shapes])
            x = edge + pitch
            paint, bars = _pin_stack_boxes(x, y, 2, level, geo, cuts)
            hw2 = max(geo.wire[2] // 2, 1)
            connection = (min(x, rx1) - hw2, y - hw2,
                          max(x, rx1) + hw2, y + hw2)
            strip = (edge, y - half, bars[level][2], y + half)
            objects = paint + [("metal2", connection),
                               (f"metal{level}", strip)]
            if any(not sites.clear(box, [layer], None, net)
                   for layer, box in objects):
                raise Refusal(
                    f"pin_site_clearance: no clear side pin site for {net}; "
                    "refusing to emit a cross-net pin geometry")
            for layer, box in objects:
                plan.paint(net, layer, *box)
            label = (edge, y - half,
                     bars[level][0] - geo.space.get(level, geo.default_space),
                     y + half)
            if label[2] <= label[0]:
                raise Refusal(f"no positive pure-metal label length for {net}")
            plan.pins.append({
                "net": net, "index": spec["index"],
                "layer": f"metal{level}", "lef_layer": spec.get("lef_layer"),
                "lef_type": spec.get("lef_type"), "use": spec["use"],
                "rail": False, "label_box": tuple(label),
                "strip_box": tuple(strip), "cuts_per_via": cuts,
                "width_lam": strip[3] - strip[1],
            })
            continue
        layers = ([f"metal{k}" for k in range(2, level + 1)]
                  + [f"via{k}" for k in range(2, level)])
        stepv = max(1, pitch // 4)
        cands = list(range(rx1, rx2 + 1, stepv))
        chosen = None
        for x in cands:
            paint, bars = _pin_stack_boxes(x, y, 2, level, geo, cuts)
            ext = (min(b[0] for b in bars.values()),
                   min(b[1] for b in bars.values()),
                   max(b[2] for b in bars.values()),
                   max(b[3] for b in bars.values()))
            if ext[0] < rx1 or ext[2] > rx2:
                continue
            if not sites.clear(ext, layers, None, net):
                continue
            top = bars[level]
            if spec["rail"]:
                strip = (x - half, 0, x + half, top_y)
                near = [f"metal{k}" for k in (level - 1, level, level + 1)
                        if k in geo.wire]
            else:
                strip = (x - half, 0, x + half, top[3])
                near = [f"metal{level}"]
            if not sites.clear(strip, near, None, net):
                continue
            chosen = (x, paint, bars, strip)
            break
        if chosen is None:
            if not spec["rail"]:
                raise Refusal(
                    f"pin_site_clearance: no position along the {net} rail "
                    f"seats its metal{level} pin and via stack clear of "
                    "every other conductor; refusing to emit a cross-net "
                    "pin geometry")
            # A power stripe is intentionally full-height and is allowed to
            # span its own macro geometry.  Preserve the existing rail
            # shortfall record; the non-rail fallback above is the unsafe
            # case that can join a different port's metal2 rail.
            x = rx1 + (rx2 - rx1) // 4
            paint, bars = _pin_stack_boxes(x, y, 2, level, geo, cuts)
            top = bars[level]
            strip = (x - half, 0, x + half, top_y)
            chosen = (x, paint, bars, strip)
            plan.deviate({"name": f"port {net}"}, "pin_site_clearance", 1, 0,
                         f"no position along the {net} rail seats its "
                         f"metal{level} pin and via stack clear of every "
                         "other conductor; power stripe drawn and recorded")
        x, paint, bars, strip = chosen
        for layer, b in paint:
            plan.paint(net, layer, *b)
        plan.paint(net, f"metal{level}", *strip)
        sp = geo.space.get(level, geo.default_space)
        bar = bars[level]
        if spec["rail"]:
            label = (strip[0], bar[3] + sp, strip[2], strip[3])
        else:
            label = (strip[0], strip[1], strip[2], bar[1] - sp)
        if label[2] <= label[0] or label[3] <= label[1]:
            plan.deviate({"name": f"port {net}"}, "pin_label_length_lambda",
                         1, label[3] - label[1],
                         f"the pure metal{level} length left for {net}'s pin "
                         f"label is not positive; the label covers the whole "
                         f"strip instead")
            label = strip
        plan.pins.append({
            "net": net, "index": spec["index"],
            "layer": f"metal{level}", "lef_layer": spec.get("lef_layer"),
            "lef_type": spec.get("lef_type"),
            "use": spec["use"], "rail": spec["rail"],
            "label_box": tuple(label), "strip_box": tuple(strip),
            "cuts_per_via": cuts, "width_lam": strip[2] - strip[0],
        })


# ──────────────────────────────────────────────────────────────────────
# 7. what the plan actually achieved — measured on the plan, not asserted
# ──────────────────────────────────────────────────────────────────────
def _banded(manifest: Sequence[dict], margin: int) -> List[List[dict]]:
    """The manifest cut into overlapping vertical bands.

    The library's two geometry audits are exact and quadratic, which is the
    right shape for a wiring manifest and the wrong one for a manifest that
    also carries every rectangle of 256 placed devices. Banding preserves the
    audits' answer — two rectangles closer than `margin` share at least one
    band — and pays for it in memory instead of time. A shape wider than a
    band simply appears in each band it crosses, which is what a rail does."""
    if not manifest:
        return []
    lo = min(r["box"][0] for r in manifest)
    hi = max(r["box"][2] for r in manifest)
    width = max(margin * 8, 1)
    n = max(1, (hi - lo) // width + 1)
    bands: List[List[dict]] = [[] for _ in range(n)]
    for r in manifest:
        a = max(0, (int(r["box"][0]) - margin - lo) // width)
        b = min(n - 1, (int(r["box"][2]) + margin - lo) // width)
        for k in range(a, b + 1):
            bands[k].append(r)
    return [b for b in bands if len(b) > 1]


def clearance_deviations(plan: Plan, geo: Geo,
                         devs: Sequence[dict]) -> None:
    """Every clearance this emitter's own routing came up short on, recorded.

    This is I4 applied to the routing itself, and the two questions it asks
    are `magic_gencell_layout_lib`'s, not this file's:

      * `cross_net_overlaps` — is it SHORTED? Two different nets overlapping
        on electrically linked layers. Run over the routing manifest.
      * `cross_net_spacing_violations` — is it MANUFACTURABLE? Same-layer
        cross-net pairs closer than the deck's minimum space, touching and
        overlapping pairs excluded because those are the other audit's
        finding. Run over the routing manifest AND over the routing beside
        the gencells' own geometry, which is the neighbour the routing is
        actually closest to.

    MEASURED, and the reason the second manifest exists: comparing the
    routing only with itself reported ZERO deviations for a block whose
    sign-off deck found 1339 violations. Nearly all of them were between this
    emitter's metal and the device's. A record that cannot see the thing the
    routing runs closest to is not a record.

    The floors are the spacing rules the deck states PER LAYER, and the deck
    is named as the adjudicator in every record. This program never converts
    any of it into a verdict."""
    owner = {d["name"]: d for d in devs}
    anon = {"name": None, "model": None, "pars": {}}
    layers = {s["layer"] for s in plan.shapes}
    min_space = {ly: geo.metal_space(ly) for ly in layers}
    margin = max(list(min_space.values()) + [geo.default_space])

    seen = set()
    for band in _banded(plan.shapes, margin):
        for hit in _gl.cross_net_overlaps(band):
            key = ("short",) + tuple(map(str, hit))
            if key in seen:
                continue
            seen.add(key)
            na, la, ba, nb, _lb, bb = hit
            plan.deviate(owner.get(na, anon), f"{la}_cross_net_overlap",
                         0, 1,
                         f"nets {na} and {nb} overlap on electrically linked "
                         f"layers at {list(ba)} / {list(bb)}")
        for hit in _gl.cross_net_spacing_violations(band, min_space):
            na, nb, layer, gap, ba, bb = hit
            key = ("space",) + tuple(map(str, hit))
            if key in seen:
                continue
            seen.add(key)
            plan.deviate(owner.get(na, anon), f"{layer}_space_lambda",
                         min_space[layer], round(gap, 3),
                         f"nets {na} and {nb} are {gap:.3g} lambda apart on "
                         f"{layer} at {list(ba)} / {list(bb)}")

    # THE ROUTING BESIDE THE DEVICE. The device's own rectangles are entered
    # under a pseudo-net that no netlist net can spell, so the same cross-net
    # scan asks the question, and pairs of device rectangles are dropped
    # afterwards: what a PDK gencell draws is the PDK's business, and a bare
    # gencell was measured DRC-clean on its own.
    mixed = list(plan.shapes) + plan.device_shapes
    for band in _banded(mixed, margin):
        for hit in _gl.cross_net_spacing_violations(band, min_space):
            na, nb, layer, gap, ba, bb = hit
            dev_a, dev_b = na.startswith("<device "), nb.startswith("<device ")
            if dev_a == dev_b:
                continue          # routing/routing above, device/device not ours
            key = ("dev",) + tuple(map(str, hit))
            if key in seen:
                continue
            seen.add(key)
            who = (na if dev_a else nb)[len("<device "):-1]
            if plan.patch_of.get((layer, tuple(bb if dev_a else ba))) == who:
                # a patch on one of the device's OWN polygons, which by
                # construction comes no closer to the rest of that device than
                # the polygon it extends (`_clear_but`): the gencell's own
                # spacing, and what a gencell draws is the PDK's business
                continue
            plan.deviate(owner.get(who, anon),
                         f"{layer}_space_to_device_lambda",
                         min_space[layer], round(gap, 3),
                         f"net {(nb if dev_a else na)} runs {gap:.3g} lambda "
                         f"from {who}'s own {layer} at {list(ba)} / "
                         f"{list(bb)}")

    # THE SHORT AUDIT, TRANSITIVE AND OVER THE DEVICES. See `net_shorts`.
    for short in net_shorts(plan):
        na, nb = short["nets"]
        chain = " -> ".join(
            f"{s['net']}:{s['layer']}{s['box']}" for s in short["path"]) \
            or "(no path recovered)"
        plan.deviate(anon, "routed_nets_per_conductor", 1, 2,
                     f"nets {na} and {nb} are ONE conductor in this layout: "
                     f"{chain}")


# ── the short audit, run TRANSITIVELY and over the devices too ──────────
#
# THE DEFECT THIS CLOSES, MEASURED. `clearance_deviations` above asks
# `cross_net_overlaps` "is it shorted?" — PAIRWISE, and over `plan.shapes`
# ONLY. Both halves of that are holes:
#
#   * a short does not need two of THIS emitter's rectangles to touch. It
#     needs a PATH. On u_hawaii_adc's `ldo` the path is three shapes long —
#     our metal5 island on `vg`, the MiM capacitor's own metal5 plate, our
#     metal5 island on `vout` — and no PAIR in it is two routing rectangles
#     of different nets, so the pairwise scan over the routing manifest saw
#     nothing and the producer reported a clean sheet.
#   * the deck's own LVS then reported `mismatch` on that block and on its
#     sibling, five schematic nets extracting as ONE, and nothing in the
#     flow could say why.
#
# The cause, once the path is printed, is one line of `parse_cell`:
# `metal_level_at` recognises a conductor only if its section is called
# `metalN` or `viaN`, and this PDK delivers a MiM capacitor's TOP plate on a
# section called `mimcapcontact`. Both of that device's terminal labels
# therefore read as the metal5 plane the BOTTOM plate occupies, and the
# emitter drops a via stack for each of them onto the same plate. The
# capacitor is shorted, and every net downstream of it collapses.
#
# This scan does not fix that. It makes the producer SAY it, in the record
# it owns, with the path — which is what I4 already requires of every other
# thing this emitter cannot make clear.
def net_shorts(plan: Plan, limit: int = 8) -> List[dict]:
    """Every pair of routed nets that share one conductor, with a WITNESS.

    Union-find over the routing manifest AND the placed gencells' own
    geometry, joined wherever two rectangles on electrically linked layers
    touch or overlap. A component carrying two routed nets is a short, and
    the shortest chain of rectangles between them is reported with it: a
    reader who is told "vg and vout are one net" and not WHERE has been told
    the symptom, which is what the sign-off LVS already said.
    """
    rows = [dict(r, _own=True) for r in plan.shapes] \
        + [dict(r, _own=False) for r in plan.device_shapes]
    if not rows:
        return []
    cell = max(64, geo_bucket(rows))
    grid: Dict[tuple, List[int]] = {}
    for i, r in enumerate(rows):
        b = r["box"]
        for gx in range(b[0] // cell, b[2] // cell + 1):
            for gy in range(b[1] // cell, b[3] // cell + 1):
                grid.setdefault((gx, gy), []).append(i)

    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    adj: Dict[int, List[int]] = {}
    for i, r in enumerate(rows):
        b = r["box"]
        seen: set = set()
        for gx in range(b[0] // cell, b[2] // cell + 1):
            for gy in range(b[1] // cell, b[3] // cell + 1):
                for j in grid.get((gx, gy), ()):
                    if j <= i or j in seen:
                        continue
                    seen.add(j)
                    o = rows[j]
                    if not _linked(r["layer"], o["layer"]):
                        continue
                    ob = o["box"]
                    if b[0] > ob[2] or ob[0] > b[2] \
                            or b[1] > ob[3] or ob[1] > b[3]:
                        continue
                    adj.setdefault(i, []).append(j)
                    adj.setdefault(j, []).append(i)
                    a, c = find(i), find(j)
                    if a != c:
                        parent[a] = c

    by_comp: Dict[int, Dict[str, List[int]]] = {}
    for i, r in enumerate(rows):
        if not r["_own"]:
            continue
        by_comp.setdefault(find(i), {}).setdefault(r["net"], []).append(i)

    out: List[dict] = []
    for comp, nets in sorted(by_comp.items()):
        if len(nets) < 2:
            continue
        order = sorted(nets)
        for k in range(1, len(order)):
            a, b_net = order[0], order[k]
            out.append({"nets": (a, b_net),
                        "path": _short_path(rows, adj, nets[a], set(nets[b_net]),
                                            limit)})
    return out


def geo_bucket(rows: Sequence[dict]) -> int:
    """A bucket side that keeps the neighbour lists short without making the
    grid itself the cost: the median rectangle's larger side, floored."""
    sides = sorted(max(r["box"][2] - r["box"][0], r["box"][3] - r["box"][1])
                   for r in rows)
    return max(1, sides[len(sides) // 2])


def _short_path(rows: Sequence[dict], adj: Dict[int, List[int]],
                src: Sequence[int], dst: set, limit: int) -> List[dict]:
    """The shortest chain of rectangles joining two nets, breadth-first."""
    prev: Dict[int, int] = {}
    seen = set(src)
    queue = list(src)
    hit = None
    while queue:
        u = queue.pop(0)
        if u in dst:
            hit = u
            break
        for v in adj.get(u, ()):
            if v in seen:
                continue
            seen.add(v)
            prev[v] = u
            queue.append(v)
    if hit is None:
        return []
    chain = [hit]
    while chain[-1] in prev:
        chain.append(prev[chain[-1]])
    chain.reverse()
    return [{"net": rows[i]["net"], "layer": rows[i]["layer"],
             "box": list(rows[i]["box"])} for i in chain[:limit]]


def layout_tcl(block: str, plan: Plan, out_dir: str) -> str:
    """The Magic script that draws the block, streams it, and says so.

    `LAYOUT_OK` is printed LAST: a run that dies mid-way prints no marker and
    this program reports the failure rather than a partial layout."""
    L = ["drc off", f"cellname create {block}", f"load {block}"]
    L += plan.tcl
    # Magic promotes every label in the top cell to an extraction interface
    # name.  `plan.ports` also carries the emitter's rail-anchor bookkeeping;
    # the declared interface is emitted below from `plan.pins`.  Labelling an
    # undeclared anchor widens the extracted top .subckt (the prior native
    # run exposed names such as `vdd.n10` and `vg.n19`).  This is a metadata
    # correction only: the repaired native extraction must still establish
    # whether any physical conductor remains open.  Keep the label path only
    # for a declared-port entry and never promote an undeclared anchor.
    for net, x, y in plan.ports:
        if net not in plan.port_nets:
            continue
        L.append(f"box {x} {y} {x} {y}")
        L.append(f"label {net} FreeSans 40 0 0 0 c metal2")
        L.append("port make")
    # A DECLARED PORT IS A RECTANGLE ON PURE ROUTING METAL (see `_draw_pins`).
    # A point label does not survive the GDS the abstract is written from, and
    # a label on a via is moved by Magic onto the cut layer; both give an
    # abstract with no pin. Refused here rather than written.
    for pin in sorted(plan.pins, key=lambda p: p["index"]):
        x1, y1, x2, y2 = pin["label_box"]
        if x2 <= x1 or y2 <= y1 or not _METAL_RE.match(pin["layer"]):
            raise ValueError(f"port {pin['net']}: a pin label must be a "
                             f"rectangle on a metal layer, got {pin}")
        L += [f"box {x1} {y1} {x2} {y2}",
              f"label {pin['net']} FreeSans 40 0 0 0 c {pin['layer']}",
              f"port make {pin['index']}",
              "port class inout"]
        if pin["use"]:
            L.append(f"port use {pin['use']}")
    # Each gencell child is SAVED BY NAME rather than left to `writeall`: a
    # cell Magic generated has no filename of its own, so `writeall force`
    # silently writes none of them and `layout.mag` comes out naming children
    # that do not exist. That is what made the first version's layout
    # unreadable — and a layout Magic cannot load reports DRC 0.
    L += [f"load {block}",
          f"set a5kids [cellname list children {block}]",
          "foreach c $a5kids { load $c ; save $c.mag }",
          f"load {block}",
          f"gds write {shlex.quote(out_dir)}/{block}.gds",
          f"save {shlex.quote(out_dir)}/layout.mag",
          'puts "A5_LAYOUT_OK"', "quit -noprompt"]
    return "\n".join(L)


# ──────────────────────────────────────────────────────────────────────
# 8. the producer
# ──────────────────────────────────────────────────────────────────────
def _read_json(path: Path) -> Optional[dict]:
    """A JSON document, or None when it is absent or unreadable."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def emit_block(project: Path, block: str, stage: Stage, magicrc: str,
               facts: PdkFacts, args) -> Tuple[int, dict]:
    bdir = _pl.analog_dir(project) / block
    sp = bdir / f"{block}.sp"
    report: dict = {"producer": PRODUCER, "schema": SCHEMA, "block": block,
                    "netlist": str(sp)}
    if not sp.is_file():
        report["result"] = "NO_NETLIST"
        report["reason"] = (f"A3 has not produced {sp}; A5 draws the A3 "
                            f"netlist and nothing else")
        return RC_REFUSED, report

    # A REFUSAL DOES NOT ERASE AN EARLIER LAYOUT, and it must not be silent
    # about that. MEASURED on this program's own negative control: drawing a
    # legal device, then editing its width below the PDK minimum and
    # re-running, leaves the first run's `layout.mag` on disk — and the A5
    # gate reads geometry, not provenance, so it PASSes that layout for a
    # netlist the PDK forbids. Deleting someone else's artefact is not this
    # producer's call; saying so, in the record it owns, is.
    # WHICH NETLIST THIS LAYOUT IS OF, by content. The path alone named a
    # netlist that A3 later re-emitted with different devices, and A7 then
    # extracted a layout of the OLD netlist and compared it with the new one:
    # MEASURED (delta_sigma, ihp-sg13g2) that read as
    # A7_RCX_DEVICE_INVENTORY_MISMATCH, cap_cmim 23 vs 78, while the extraction
    # matched the netlist actually drawn device for device. Provenance comments
    # are excluded (`content_digest`), so a byte-identical re-emission keeps
    # the identity.
    report["netlist_content_sha256"] = _pc.content_digest(
        sp.read_text(errors="replace"))
    stale = bdir / "layout.mag" if (bdir / "layout.mag").is_file() else None
    if stale:
        report["layout_present_before_this_run"] = str(stale)

    def refuse(result: str, reason: str, rc: int) -> Tuple[int, dict]:
        report["result"] = result
        report["reason"] = reason
        if stale:
            report["stale_layout_warning"] = (
                f"{stale} is from an EARLIER run and this netlist was "
                f"refused; it was not produced from the netlist now on disk, "
                f"and nothing here deleted it")
        return rc, report

    try:
        blockname, ports, devs = parse_netlist(sp)
    except ValueError as exc:
        # a netlist this program cannot read is NAMED, like everything else it
        # cannot do — never a traceback out of a producer the runner calls
        return refuse("UNREADABLE_NETLIST", str(exc), RC_REFUSED)
    report["subckt"] = blockname
    report["ports"] = ports
    report["devices"] = len(devs)

    unknown = sorted({d["model"] for d in devs
                      if d["model"] not in facts.gencells})
    if unknown:
        return refuse(
            "NO_GENCELL",
            f"the PDK defines no gencell for {', '.join(unknown)} in "
            f"{facts.sources.get('gencell_tcl')} or its technology "
            f"directory; this emitter draws with the PDK's own gencells and "
            f"does not invent a device", RC_REFUSED)
    for d in devs:
        d["class"] = facts.gencells[d["model"]].get("class")

    # I2 — before any probe.
    bad = forbidden_geometries(devs, facts)
    if bad:
        report["refusals"] = bad
        return refuse("FORBIDDEN",
                      "the PDK forbids " + str(len(bad)) + " geometry(ies) in "
                      "this netlist; see `refusals`", RC_FORBIDDEN)

    limits_used = {}
    for model in sorted({d["model"] for d in devs}):
        lmin, wmin, src = facts.limits_for(model)
        lmax, wmax, _ = _maxima_for(facts, model)
        limits_used[model] = {"lmin_um": lmin, "wmin_um": wmin,
                              "lmax_um": lmax, "wmax_um": wmax,
                              "class": facts.gencells[model].get("class"),
                              "source": src}
    report["pdk_limits"] = limits_used
    report["pdk_sources"] = dict(facts.sources)
    report["m1_space_um"] = facts.m1_space_um

    lam, cells = probe(stage, magicrc, devs, facts)
    report["lambda_per_um"] = lam

    geo = Geo(facts.deck, facts.m1_space_um, lam,
              args.wire_width_um, args.via_pad_half_um)
    pad_half_um = geo.via_pad[1] / lam
    tap_clear_um = facts.m1_space_um + 2 * pad_half_um
    tap_clear = max(1, round(tap_clear_um * lam))
    report["deck_rules"] = {
        k: {str(a): b for a, b in sorted(v.items(), key=str)}
        for k, v in facts.deck.items()}
    report["generator_geometry_um"] = {
        "wire_width": args.wire_width_um,
        "via_pad_half": args.via_pad_half_um,
        "note": ("the PDK does not state a routing wire width or a via pad "
                 "size — they are this generator's own choice, which is why "
                 "the limits program takes the pad half-height as an "
                 "argument. Both are recorded here and both are CLI flags."),
    }
    report["tap_clearance_um"] = {
        "value": round(tap_clear_um, 6),
        "terms": {"m1_space_um": facts.m1_space_um,
                  "tap_pad_half_um": pad_half_um,
                  "terminal_pad_half_um": pad_half_um},
        "status": ("PREDICTION — the sign-off deck adjudicates, this "
                   "emitter does not"),
    }

    # THE PINS: layer, USE, width and cuts per port, from the block's own
    # rail declaration (A2 IR), its spec's declared current (A1) and the
    # PDK's tech LEF. Never a rail inferred from a net NAME.
    topo = _read_json(bdir / "topology.json")
    rails = topo.get("rails") if isinstance(topo, dict) and \
        isinstance(topo.get("rails"), dict) else None
    pin_spec, pins_basis = pin_spec_for(ports, rails,
                                        _read_json(bdir / "spec.json"),
                                        facts, geo)
    report["pins_basis"] = pins_basis
    if facts.cell_lef_text is not None:
        snapshot = bdir / "a5_stdcell_pg.lef"
        snapshot.write_text(facts.cell_lef_text, encoding="utf-8")
        pins_basis["core_pg"]["snapshot"] = str(snapshot.relative_to(project))
    plan = build_plan(devs, ports, cells, facts, geo, tap_clear, pin_spec)
    clearance_deviations(plan, geo, devs)
    # A GEOMETRY THE PDK'S GENCELL CLAMPED. Recorded like every other
    # measurement this emitter makes, and blocking like the short: see
    # `over_maxima`. The device is in `cells` already — magic drew the
    # clamped one — so this is written where the rest of the record is.
    owner = {d["name"]: d for d in devs}
    for hit in over_maxima(devs, facts):
        plan.deviate(owner[hit["device"]], OVER_MAXIMUM_QUANTITY,
                     hit["pdk_maximum_um"], hit["requested_um"], hit["detail"])

    bdir.mkdir(parents=True, exist_ok=True)
    magic_run(stage, magicrc,
              layout_tcl(blockname, plan, stage.path or "."),
              f"a5layout_{blockname}", "A5_LAYOUT_OK")
    ok_mag, err_mag = stage.get("layout.mag", bdir / "layout.mag")
    ok_gds, err_gds = stage.get(f"{blockname}.gds", bdir / f"{block}.gds")
    # A Magic layout is a CELL HIERARCHY: `layout.mag` names the gencell
    # children it instantiates, and without them beside it the file cannot be
    # read back at all. MEASURED: the first version of this producer shipped
    # `layout.mag` alone, and Magic answered
    #
    #     File .../sg13_hv_nmos_NXWZTH.mag couldn't be read
    #     Failure to read in entire subtree of cell.
    #
    # then reported `drc list count total` = 0 — a clean DRC verdict on a
    # layout it had not loaded. The children are not a third output; they are
    # the layout, and they travel with it.
    rc_ls, listing, _ = stage.sh(
        f"cd {shlex.quote(stage.path or '.')} && ls -1 *.mag", timeout=120)
    children: List[str] = []
    if rc_ls == 0:
        # An interactive-login shell in an EDA image prints a banner on
        # stdout, so the listing is filtered to plain file names in the stage
        # rather than trusted whole. An unfiltered token here is an absolute
        # path from that banner, and joining it to the block directory
        # escapes the project entirely.
        for name in sorted(_MAG_NAME_RE.findall(listing)):
            if name in ("layout.mag", "a5probe.mag"):
                continue
            got, _ = stage.get(name, bdir / name)
            if got:
                children.append(name)
    report["layout_cells"] = children
    if not ok_mag:
        report["result"] = "NO_ARTEFACT"
        report["reason"] = f"magic reported success but layout.mag did not " \
                           f"come back: {err_mag}"
        return RC_REFUSED, report
    if not ok_gds:
        report["gds_note"] = f"{blockname}.gds did not come back: {err_gds}"

    report["result"] = "OK"
    report["shapes_painted"] = len(plan.shapes)
    # WHAT THE GENCELLS LEFT UNROUTED AND TOO SMALL, and what became of it.
    # See `floating_metal_patches`.
    fl = dict(plan.island_patches)
    fl["patches"] = fl.get("patches", [])[:50]
    report["floating_device_metal"] = fl
    report["pins"] = [{
        "net": p["net"], "index": p["index"], "layer": p["layer"],
        "lef_layer": p["lef_layer"], "lef_type": p["lef_type"],
        "use": p["use"], "rail": p["rail"],
        "box_um": [round(v / lam, 4) for v in p["label_box"]],
        "strip_um": [round(v / lam, 4) for v in p["strip_box"]],
        "width_um": round(p["width_lam"] / lam, 4),
        "cuts_per_via": p["cuts_per_via"],
        "em": (pin_spec or {}).get("ports", {}).get(p["net"], {}).get("em"),
    } for p in sorted(plan.pins, key=lambda q: q["index"])]
    report["deviations"] = plan.deviations
    report["deviation_summary"] = _summarise(plan.deviations)
    # Beside the shortfall list, never inside it: what the bulk-tap search
    # actually examined. An empty `deviations` with `examined == 0` is a
    # check that did not run, and the two must not read the same.
    report["bulk_tap"] = bulk_tap_denominator(plan)
    why_refused = bulk_tap_refusal(report["bulk_tap"])
    if why_refused:
        # The layout has been written by now; the record says the search that
        # was supposed to grade its bulk taps entered no device, so the exit
        # code says the same rather than leaving an empty shortfall list to
        # be read as a clean one (vibe-ic#2129).
        report["result"] = BULK_TAP_VACUOUS
        report["reason"] = why_refused
        return RC_REFUSED, report
    report["layout_mag"] = str(bdir / "layout.mag")
    report["layout_gds"] = str(bdir / f"{block}.gds") if ok_gds else None

    # A DRAWN SHORT IS BLOCKING. The layout is still written and still
    # reported — a reader repairing this needs the geometry — but the exit
    # code says the emitter did not draw this netlist. See `blocking_shorts`.
    shorts = blocking_shorts(plan.deviations)
    over = [d for d in plan.deviations
            if d.get("quantity") == OVER_MAXIMUM_QUANTITY]
    if shorts or over:
        report["result"] = "SHORTED" if shorts else "CLAMPED_GEOMETRY"
        if shorts:
            report["shorts"] = shorts
        if over:
            report["clamped_devices"] = over
        parts = []
        if shorts:
            parts.append(f"{len(shorts)} pair(s) of routed nets are ONE "
                         f"conductor in the layout this emitter drew, each "
                         f"recorded above with the chain of rectangles that "
                         f"joins them")
        if over:
            parts.append(f"{len(over)} device(s) were asked for above the "
                         f"PDK's own stated maximum, which the gencell does "
                         f"not refuse but CLAMPS, so the drawn device is not "
                         f"the one this netlist asks for")
        report["reason"] = (
            "; ".join(parts) + ". The layout and its GDS are written so the "
            "geometry can be read, and the exit code is non-zero because the "
            "netlist was not drawn.")
        return RC_FORBIDDEN, report
    return RC_OK, report


def bulk_tap_denominator(plan: "Plan") -> dict:
    """WHAT THE BULK-TAP CHECK ACTUALLY EXAMINED (vibe-ic#2056 item 3).

    `deviations` answers "did I find a shortfall?". It does not answer "did I
    look at anything?", and for this particular check the two have been
    conflated since the check was written: `choose_tap`, the clearance floor
    and `bulk_tap_row_separation_lambda` run only for a device whose guard
    ring `ring_layer_of` identifies, and on this PDK's gencell children it
    identifies none. Every such run published an empty shortfall list, which
    reads as "the floor was met" and means "the floor was never applied".

    So the count is stated in the repo's own zero-denominator shape
    (`_gate_denominator.Denominator`), whose constructor REFUSES a zero with
    no reason — a silence cannot be reintroduced by omission here, only by
    writing down a reason, and a written reason is reviewable.

    This is a DISCLOSURE, not a verdict: no exit code, no gate and no
    deviation depends on it. Nested under its own key rather than the
    canonical top-level `denominator`, because this producer is an emitter
    and does not claim to be one of the registered gates that key sweeps.

    chip-AGNOSTIC: nothing here names a device, a layer or a PDK; the reason
    quotes the layer the gencell itself emitted, when there was one."""
    considered = int(getattr(plan, "bulk_tap_considered", 0))
    examined = int(getattr(plan, "bulk_tap_examined", 0))
    unexamined = list(getattr(plan, "bulk_tap_unexamined", []))
    reason = ""
    if examined == 0:
        if considered == 0:
            reason = ("no device reached the bulk-tap search: this block "
                      "routed no device at all")
        else:
            why = sorted({str(r.get("reason")) for r in unexamined})
            reason = (
                f"the bulk-tap search ran on 0 of {considered} routed "
                f"device(s), so the clearance floor and the row-separation "
                f"check were NOT EVALUATED — which is not the same as met. "
                f"Reason(s) given by the devices themselves: "
                + "; ".join(why))
    searched = list(getattr(plan, "bulk_tap_searched", []))
    quantities = ("bulk_tap_clearance_lambda",
                  "bulk_tap_row_separation_lambda")
    shortfall = sorted({d.get("device") for d in getattr(plan, "deviations", ())
                        if d.get("quantity") in quantities})
    details: Dict[str, Any] = {
        # MEMBERSHIP (vibe-ic#2129): the population by name, so the shortfall
        # list is CHECKABLE as a subset of it rather than compared by count.
        "searched": searched,
        "ring_layer": dict(getattr(plan, "bulk_tap_ring_layer", {})),
        "shortfall_devices": shortfall,
        "shortfall_quantities": list(quantities),
        "tappable_not_searched": [r.get("device") for r in unexamined
                                  if r.get("tappable")],
        "not_tappable": [r.get("device") for r in unexamined
                         if not r.get("tappable")],
        "membership_note": (
            "`shortfall_devices` is a SUBSET of `searched` by construction; "
            "a name here that is not in `searched` would be a shortfall of a "
            "search that never ran"),
    }
    if unexamined:
        details["unexamined"] = unexamined
    return _den.Denominator(
        unit="routed devices whose guard ring the bulk-tap search could enter",
        examined=examined, considered=considered,
        not_applicable_reason=reason,
        details=details,
    ).as_dict()


#: The result A5 reports when the bulk-tap search examined nothing while a
#: device the PDK says HAS a body connection went unsearched.
BULK_TAP_VACUOUS = "BULK_TAP_SEARCH_EXAMINED_NOTHING"


def bulk_tap_refusal(bulk_tap: dict) -> str:
    """The reason A5 refuses this bulk-tap disclosure, or "" to accept it.

    THE ONE PLACE THE DISCLOSURE BECOMES A VERDICT, and only in the direction
    #2129 asks for. `bulk_tap_denominator` above is bookkeeping and stays
    that way: it moves no exit code on its own, which is what
    `test_the_disclosure_changes_no_verdict` holds. What moves here is
    narrower — a search that examined NOTHING while the PDK says at least one
    device HAS a body connection is the #2129 defect reproducing, and a run
    that writes a layout and exits 0 on it publishes an empty shortfall list
    that reads as a clean bulk-tap result. That is the shape this issue
    exists to make impossible.

    THE CONTROL is the other zero, and it is not refused: a block whose every
    device carries no body connection at all — a capacitor bank — examines
    nothing for a reason that is a property of the devices. It says so in the
    same record. Without that split the refusal would fire on every such
    block and could not be trusted anywhere."""
    if int(bulk_tap.get("examined", 0)) != 0:
        return ""
    if bulk_tap.get("details", {}).get("tappable_not_searched"):
        return str(bulk_tap.get("not_applicable_reason", ""))
    return ""


#: The deviation quantity `clearance_deviations` writes for a drawn short.
#: One name, used by the producer's exit code and by the A5 gate, so the two
#: cannot drift apart.
SHORT_QUANTITY = "routed_nets_per_conductor"

#: The deviation quantity `over_maxima` writes for a device the PDK's gencell
#: cannot draw at the size the netlist asks for.
OVER_MAXIMUM_QUANTITY = "device_geometry_above_pdk_maximum"

#: Every quantity that is NOT a clearance the sign-off deck adjudicates.
#: Each one says the emitter did not draw THIS netlist, so each one is
#: blocking, and the A5 gate reads the same set out of the same record.
BLOCKING_QUANTITIES = (SHORT_QUANTITY, OVER_MAXIMUM_QUANTITY)


def blocking_deviations(deviations: Sequence[dict]) -> List[dict]:
    """Every deviation that says the emitter did not draw THIS netlist.

    See `blocking_shorts` for why a short is not a clearance; a device the
    PDK's gencell silently CLAMPED is the same kind of statement, measured
    the same way and in the same record — the geometry on disk is not the
    geometry the netlist asked for, and no deck adjudicates that away."""
    return [d for d in deviations
            if d.get("quantity") in BLOCKING_QUANTITIES]


def blocking_shorts(deviations: Sequence[dict]) -> List[dict]:
    """The deviations that say this layout JOINS TWO ROUTED NETS.

    WHY THIS ONE IS NOT A DEVIATION LIKE THE OTHERS. Everything else this
    emitter records is a CLEARANCE it predicts and the sign-off deck
    adjudicates: drawn, recorded, and left to the deck, because the deck is
    the authority on whether 0.205 um is far enough. A short is not that
    kind of statement. It is not a distance the deck might yet permit; it is
    two nets of the netlist being one conductor in the layout, measured by
    union-find over this emitter's OWN manifest plus the placed gencells'
    own geometry, with the chain of rectangles that joins them printed
    beside it. No deck adjudicates it away, and the sign-off LVS that
    eventually says `mismatch` is telling the reader the symptom of a defect
    this emitter could already name.

    MEASURED on u_hawaii_adc (ihp-sg13g2, image 0.3.46): 13 of these — 1 on
    `ldo`, 12 on `delta_sigma` — while A5 exited 0 on both blocks and the
    per-block LVS answered `mismatch` with nothing in the flow able to say
    why. A design that carries none is untouched: this is the whole
    difference the rule makes to a clean block's exit code."""
    return [d for d in deviations if d.get("quantity") == SHORT_QUANTITY]


def _summarise(devs: Sequence[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for d in devs:
        q = out.setdefault(d["quantity"], {"count": 0, "worst_shortfall": 0})
        q["count"] += 1
        sf = d.get("shortfall")
        if isinstance(sf, (int, float)) and sf > q["worst_shortfall"]:
            q["worst_shortfall"] = sf
    return out


def _plugin_version() -> str:
    for up in Path(__file__).resolve().parents:
        meta = up / ".claude-plugin" / "plugin.json"
        if meta.is_file():
            try:
                return json.loads(meta.read_text()).get("version", "unknown")
            except (OSError, ValueError):
                break
    return "unknown"


def _finish(out: dict, args, rc: int) -> int:
    """Print the report and, when asked, write it — on EVERY path.

    A run that ends in ENV_UNAVAILABLE is exactly the run whose report a
    reader most needs, so it is written like any other."""
    print(json.dumps(out, indent=2))
    if getattr(args, "json", None):
        _aa.write_text(Path(args.json), json.dumps(out, indent=2) + "\n")
    return rc


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--block", action="append", default=[])
    ap.add_argument("--container", default="")
    ap.add_argument("--magicrc")
    ap.add_argument("--pdk-root", default="/foss/pdks")
    ap.add_argument("--family", default="ihp-sg13g2")
    ap.add_argument("--gencell-tcl")
    ap.add_argument("--drc-tech")
    ap.add_argument("--magic-tech")
    ap.add_argument("--tech-lef",
                    help="the PDK tech LEF the pins are placed and sized by "
                         "(default: <pdk-root>/<family>/libs.ref/*/lef/"
                         "*tech*.lef)")
    ap.add_argument("--wire-width-um", type=float,
                    default=DEFAULT_WIRE_W_UM)
    ap.add_argument("--via-pad-half-um", type=float,
                    default=DEFAULT_VIA_PAD_HALF_UM)
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    blocks = list(args.block) or list(load_block_list(project) or [])
    out: dict = {"producer": PRODUCER, "schema": SCHEMA,
                 "version": _plugin_version(),
                 "project": str(project), "blocks": {}}
    if not blocks:
        out["result"] = "NO_BLOCKS"
        out["reason"] = ("no analog block is declared and none was named; "
                         "there is nothing for A5 to draw")
        return _finish(out, args, RC_OK)

    magicrc = args.magicrc or (
        f"{args.pdk_root}/{args.family}/libs.tech/magic/{args.family}.magicrc")
    host_tmp = Path(tempfile.mkdtemp(prefix="a5_layout_emit."))
    stage = Stage(args.container, host_tmp)
    opened, why = stage.open()
    if not opened:
        out["result"] = "ENV_UNAVAILABLE"
        out["tool"] = "docker/container"
        out["reason"] = (f"ENV_UNAVAILABLE: magic is reached through the EDA "
                         f"container and the container is not: {why}. A5 "
                         f"emits NO layout.mag rather than a fabricated one.")
        return _finish(out, args, RC_ENV_UNAVAILABLE)

    try:
        rc_tool, _, _ = stage.sh("command -v magic", timeout=120)
        if rc_tool != 0:
            out["result"] = "ENV_UNAVAILABLE"
            out["tool"] = "magic"
            out["reason"] = (
                f"ENV_UNAVAILABLE: `magic` is not on PATH in "
                f"{args.container or 'this host'}. A5 draws with Magic's own "
                f"PDK gencells; without it there is no layout, and a "
                f"fabricated layout.mag is worse than none.")
            return _finish(out, args, RC_ENV_UNAVAILABLE)

        facts, why = read_pdk(stage, args.pdk_root, args.family,
                              args.gencell_tcl, args.drc_tech,
                              args.magic_tech, args.tech_lef)
        if facts is None:
            out["result"] = "ENV_UNAVAILABLE"
            out["tool"] = "pdk"
            out["reason"] = why
            return _finish(out, args, RC_ENV_UNAVAILABLE)

        worst = RC_OK
        for block in blocks:
            try:
                rc, rep = emit_block(project, block, stage, magicrc, facts,
                                     args)
            except Refusal as exc:
                rc, rep = RC_REFUSED, {"block": block, "result": "REFUSED",
                                       "reason": str(exc)}
            except MagicError as exc:
                rc, rep = RC_REFUSED, {"block": block, "result": "TOOL_ERROR",
                                       "reason": str(exc)}
            rep["version"] = out["version"]
            out["blocks"][block] = rep
            worst = max(worst, rc)
            # the provenance is written on EVERY outcome, not only the good
            # one: a block directory that still holds a layout must also hold
            # this producer's latest word about it, or the newest thing on
            # disk is an artefact nobody has vouched for.
            bdir = _pl.analog_dir(project) / block
            if bdir.is_dir():
                (bdir / "layout_provenance.json").write_text(
                    json.dumps(rep, indent=2) + "\n")
            print(f"LAYOUT: {'OK' if rc == RC_OK else rep.get('result')} "
                  f"[{block}] "
                  f"{len(rep.get('deviations', []))} deviation(s)")
    finally:
        stage.close()
        shutil.rmtree(host_tmp, ignore_errors=True)

    out["result"] = "OK" if worst == RC_OK else "NOT_OK"
    return _finish(out, args, worst)


if __name__ == "__main__":
    sys.exit(main())
