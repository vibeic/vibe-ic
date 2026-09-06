#!/usr/bin/env python3
"""_pdk_layer_authority — what a TECHNOLOGY says, read from the PDK volume.

Two questions the tape-out precheck used to answer from a DECLARATION, and one
place that answers both from the process itself (vibe-ic#2058, FP-10 and the
orchestrator's ForbiddenLayers ruling of 2026-09-06):

    layer_table(volume)     the (layer, datatype) pairs the technology's own
                            KLayout layer table defines. The ALLOWED set —
                            everything else in a GDS is a layer the process
                            does not know.
    seal_ring_facility(v)   whether this technology can build a seal ring at
                            all, i.e. whether the volume ships the generator
                            `die_finishing_gen` drives.

WHY A DECLARATION CANNOT ANSWER EITHER
======================================
`seal_ring_required: false` and `forbidden_layers: []` are both a design saying
"do not check this". MEASURED on spm x gf180mcuD (lane czspmfp, image label
0.3.46): `General.SealRing` reported NOT_DETERMINED for a declared `false`
while `die_finishing_gen` treated the SAME false as a decided not-applicable
and wrote its SKIPPED marker — two consumers of one declaration disagreeing
about what it means, and neither able to reach a PASS. `General.ForbiddenLayers`
reported NOT_DETERMINED over 32 layer/datatype pairs because nobody had written
a list down.

A NOT_APPLICABLE is legitimate ONLY when it is a fact about the PROCESS: this
technology has no seal-ring facility, so there is nothing to check and nothing
to declare away. That is derivable, and it is derived here. A DECLARED false is
refused, and says so.

WHAT COUNTS AS THE LAYER TABLE
==============================
The KLayout layer-properties document (`*.lyp`) the technology ships beside its
`.lyt` — the table the deck and the viewer both read. It is XML with one
`<source>layer/datatype@cv</source>` per entry, optionally prefixed by a name
(`LVS_RF 100/5@1`), and it is the same shape in every PDK the pinned image
carries. MEASURED over that image (label 0.3.46), parsing only `<source>`:

    gf180mcuD   118 pairs   libs.tech/klayout/tech/gf180mcu.lyp
    sky130A     429 pairs   libs.tech/klayout/tech/sky130A.lyp
    ihp-sg13g2  378 pairs   libs.tech/klayout/tech/sg13g2.lyp
    asap7         -         no libs.tech/klayout at all
    nangate45     -         no libs.tech/klayout at all

A volume with no readable table returns None. NOT_DETERMINED is the answer
then, naming the authority that was missing — never an empty ALLOWED set, which
would make every layer in every GDS forbidden at once.

RESOLVING THE VOLUME FROM A PDK NAME
====================================
The name a run resolves is not always the volume's directory name: MEASURED on
spm, `tapeout_precheck` published `pdk="gf180mcu"` (read from the run's own tool
logs) while the volume is `gf180mcuD`. Resolution therefore tries, in order,
recording every attempt so an absence names specific paths:

    1. `pdk_registry.json` entry whose `name` matches exactly
    2. ... whose `basename(container_path)` matches exactly
    3. ... whose `name` starts with the asked-for name, UNIQUELY. Two
       candidates is an ambiguity and returns nothing: a confident answer about
       which of two processes was meant is exactly the kind of guess this
       module exists to remove.
    4. `$PDK_ROOT/<name>` — the environment, consulted last and only when the
       registry said nothing, because the environment is a fact about the
       machine and not about the design.

chip-AGNOSTIC: no foundry, vendor, node or SKU literal. Every name here comes
from `pdk_registry.json`, from the caller, or from the environment; the two
relative paths are PDK STRUCTURE (the layout every KLayout-integrated PDK
uses), and the seal-ring one is imported from `die_finishing_gen` rather than
re-spelled so the two cannot drift.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_HERE = Path(__file__).resolve().parent

#: KLayout technology directories, in the order a technology lays them out.
_LYP_GLOBS = (
    "libs.tech/klayout/tech/*.lyp",
    "libs.tech/klayout/*.lyp",
)
#: `<source>` payloads are `[<name> ]<layer>/<datatype>[@<cellview>]`. Anchored
#: to the END of the payload's first `@`-free token group so a name carrying
#: digits (`met1`, `sg13g2`) cannot be read as a layer number.
_SOURCE_RE = re.compile(r"<source>([^<]*)</source>")
_PAIR_RE = re.compile(r"(?:^|\s)(\d+)\s*/\s*(\d+)\s*$")

LayerKey = Tuple[int, int]


def _registry(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    import json
    p = path or (_HERE / "pdk_registry.json")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = doc.get("pdks")
    return entries if isinstance(entries, list) else []


def resolve_volume(pdk: Optional[str],
                   registry_path: Optional[Path] = None,
                   environ: Optional[Dict[str, str]] = None
                   ) -> Tuple[Optional[Path], str, List[str]]:
    """(volume, how it was found, every candidate tried).

    `volume` is a directory that EXISTS. An unresolvable name is not an error
    and not a default — it is None, and `tried` says where we looked.
    """
    tried: List[str] = []
    if not pdk or not str(pdk).strip():
        return None, "no PDK was named", tried
    name = str(pdk).strip()
    entries = _registry(registry_path)

    def _use(cp: Any, how: str) -> Optional[Path]:
        if not isinstance(cp, str) or not cp:
            return None
        tried.append(cp)
        p = Path(cp)
        return p if p.is_dir() else None

    for e in entries:
        if e.get("name") == name:
            got = _use(e.get("container_path"), "registry name")
            if got is not None:
                return got, f"pdk_registry.json name={name!r}", tried
    for e in entries:
        cp = e.get("container_path")
        if isinstance(cp, str) and cp and os.path.basename(cp.rstrip("/")) == name:
            got = _use(cp, "registry basename")
            if got is not None:
                return got, f"pdk_registry.json basename={name!r}", tried
    prefixed = [e for e in entries
                if isinstance(e.get("name"), str)
                and e["name"].startswith(name) and e["name"] != name]
    if len(prefixed) == 1:
        got = _use(prefixed[0].get("container_path"), "registry prefix")
        if got is not None:
            return (got,
                    f"pdk_registry.json name={prefixed[0]['name']!r} is the "
                    f"only entry beginning {name!r}", tried)
    elif len(prefixed) > 1:
        names = ", ".join(sorted(str(e["name"]) for e in prefixed))
        return None, (f"{len(prefixed)} registry entries begin {name!r} "
                      f"({names}); which process was meant is not derivable"), tried
    env = environ if environ is not None else os.environ
    root = env.get("PDK_ROOT")
    if root:
        cand = Path(root) / name
        tried.append(str(cand))
        if cand.is_dir():
            return cand, "$PDK_ROOT/<name>", tried
    return None, f"no volume for {name!r} in the registry or under $PDK_ROOT", tried


def parse_layer_table(text: str) -> Set[LayerKey]:
    """Every (layer, datatype) a KLayout layer-properties document defines."""
    pairs: Set[LayerKey] = set()
    for src in _SOURCE_RE.findall(text):
        head = src.split("@")[0].strip()
        m = _PAIR_RE.search(head)
        if m:
            pairs.add((int(m.group(1)), int(m.group(2))))
    return pairs


def layer_table(volume: Optional[Path]
                ) -> Tuple[Optional[Set[LayerKey]], Optional[str], List[str]]:
    """(the allowed pairs, the file that supplied them, every path tried).

    None means NOT DETERMINED, never "the empty set": a technology whose table
    could not be read has not declared every layer forbidden.
    """
    tried: List[str] = []
    if volume is None:
        return None, None, tried
    for glob in _LYP_GLOBS:
        for cand in sorted(volume.glob(glob)):
            tried.append(str(cand))
            try:
                text = cand.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            pairs = parse_layer_table(text)
            if pairs:
                return pairs, str(cand), tried
    return None, None, tried


def seal_ring_facility(volume: Optional[Path]
                       ) -> Tuple[Optional[bool], Optional[str], List[str]]:
    """(does this technology ship a seal-ring generator, the path, tried).

    None means the question could not be reached at all — no volume. False is a
    MEASUREMENT: the volume is here and it ships no generator, so this process
    has no seal-ring facility and a seal ring is not applicable to it.
    """
    from die_finishing_gen import _PDK_SCRIPT_REL as REL
    tried: List[str] = []
    if volume is None:
        return None, None, tried
    cand = volume / REL
    tried.append(str(cand))
    if cand.is_file():
        return True, str(cand), tried
    return False, None, tried


#: THE FLOW'S OWN MARKER LAYERS, derived from the writer, never typed here.
#:
#: `def_gds_port_power_restore` puts port-label text and power-rail markers into
#: the streamed GDS so `klayout_pdk_lvs` can name the power nets geometrically.
#: They are OURS: no PDK layer table defines them, and MEASURED on spm x
#: gf180mcuD they are exactly the three pairs that rung reported as unmapped —
#: 100/0, 901/0 and 902/0 out of 32 in use.
#:
#: THE DATATYPE IS DATA, THE LAYER IS THE CONTRACT. That module's own comment:
#: "text GDS layer TEXT_LAYER[0] (100), datatype = the pin's 1-based metal index
#: (MET1->dt1, MET2->dt2, …) … datatype 0 = catch-all for a pin with no resolved
#: metal layer". So the label datatype depends on how many metals THIS design
#: routed on, and only the LAYER number can be declared ahead of a run. Matching
#: layer 100 at any datatype is therefore the derivation, not a widening — and
#: it is why this returns a layer number beside the exact pairs instead of
#: pretending to enumerate a family it cannot know.
#:
#: IMPORTED, NEVER RE-SPELLED. A typed copy of `(901, 0)` here would be a second
#: declaration of the same fact, free to drift from the writer the day someone
#: moves it — which is the whole shape `_declared_die` exists to remove one
#: layer down.
def flow_marker_layers() -> Tuple[Set[LayerKey], Optional[int], str, List[str]]:
    """(exact pairs, the label LAYER number, provenance, what was tried).

    `(set(), None, why, tried)` when the writer cannot be imported — and that is
    NOT_DETERMINED for the caller, never "the flow declares nothing", which
    would report our own markers as unknown layers.
    """
    tried = ["def_gds_port_power_restore.RAIL_MARKER",
             "def_gds_port_power_restore.TEXT_LAYER"]
    try:
        import def_gds_port_power_restore as _w
    except Exception as exc:                                  # noqa: BLE001
        return set(), None, (f"the flow's marker writer could not be imported "
                             f"({exc})"), tried
    exact: Set[LayerKey] = set()
    rails = getattr(_w, "RAIL_MARKER", None)
    if isinstance(rails, dict):
        for v in rails.values():
            if (isinstance(v, (tuple, list)) and len(v) == 2
                    and all(isinstance(n, int) for n in v)):
                exact.add((int(v[0]), int(v[1])))
    base = None
    tl = getattr(_w, "TEXT_LAYER", None)
    if (isinstance(tl, (tuple, list)) and len(tl) == 2
            and isinstance(tl[0], int)):
        base = int(tl[0])
    if not exact and base is None:
        return set(), None, ("def_gds_port_power_restore declares neither "
                             "RAIL_MARKER nor TEXT_LAYER in a shape this can "
                             "read"), tried
    return exact, base, ("derived from def_gds_port_power_restore's own "
                         "RAIL_MARKER and TEXT_LAYER"), tried


def is_flow_marker(layer: int, datatype: int,
                   exact: Set[LayerKey], base: Optional[int]) -> bool:
    """True iff THIS flow declares it writes on that layer/datatype."""
    return (layer, datatype) in exact or (base is not None and layer == base)
