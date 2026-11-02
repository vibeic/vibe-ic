#!/usr/bin/env python3
"""gds_xor_check — stream-out / finishing fidelity, as a tapeout checklist means it.

R-0915-129, metric 2. `tapeout_docs_gen` requires
`design__xor_difference__count`, and `signoff_metrics_aggregate` answered
NOT_MEASURED with "no step of this flow produces a GDS-vs-layout XOR report" --
literally true: `grep -c -i xor` over the flow yaml was ZERO. That is a GAP IN THE
FLOW, not a property of the problem: KLayout in the pinned image has `xor`, so the
comparison is producible and declaring it NOT_APPLICABLE_BY_STRUCTURE would have
been laundering.

WHAT THE MEASUREMENT IS. The SHIPPED GDS has been through finishing -- density
fill, seal ring, grid snap -- and every one of those wrote IN PLACE: measured on
spm run21, `cmp_fill_emit.json` records `gds_in == gds_out ==
phase3/stage3/pnr/spm.gds`. So no pre-finishing GDS survives to compare against,
and the honest reference is a FRESH STREAM-OUT of the same routed database the
shipped GDS came from. The run records exactly which that was:
`pad_ring_route_evidence.json` gives `gds_source_def` and its sha256 beside the
GDS's own sha256, so the comparison binds to the identity the run attested.

THE PARTITION IS THE POINT. A raw XOR of those two is NOT zero and must not be:
finishing added geometry on purpose. So the layers the finishing steps DECLARE
they added are separated out and disclosed with their own counts, and
`design__xor_difference__count` is the total on every OTHER layer -- where a
difference means the stream-out changed the design, which is what a checklist
means by fidelity. Both declarations are read from the run's own records:
  * fill      `die_density_fill.json` -> `fill.owned_layers`  (measured [34, 36,
              42, 46, 81] on run21)
  * seal ring `die_finishing.json` -> `seal_ring.ring_check.added_layers`
              (measured 14 layer/datatype pairs on run21)
A layer the finishing steps did NOT declare is a design layer, so an undeclared
addition cannot hide in the disclosed bucket.

FAIL on any design-layer difference. The finishing buckets never fail here --
their counts are evidence for a reader, and the steps that own them have their own
gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
# THE DECLARED REPORT IS WRITTEN ATOMICALLY, WITH NO FALLBACK. An earlier
# revision wrapped this import in a try/except and fell back to
# `out.write_text(...)`, which is the shape vibe-ic#1082's ratchet refuses --
# `atomic_artifact_write_check` named it here, at the fallback line, as the one
# NEW non-atomic declared-report write in 1452 programs. The fallback was worse
# than a missing import: a reader of this file would believe the write was
# atomic while the path that actually ran on any host where the import failed
# left a half-written receipt behind, and `signoff_metrics_aggregate --check`
# reads this receipt. An unimportable helper is a broken installation and must
# say so at import time, not degrade the guarantee silently.
from _atomic_artefact import write_json as _atomic_write_json
from _atomic_artefact import write_text as _atomic_write_text
import _stream_input_record as _sir  # noqa: E402

GATE = "gds_xor_check"
REPORT_REL = "reports/phase3/gds_xor.json"
#: The run's own attestation of which DEF the shipped GDS was streamed from.
ROUTE_EVIDENCE_REL = "reports/phase3/pad_ring_route_evidence.json"
FILL_REL = "reports/phase3/die_density_fill.json"
#: The CMP/dummy fill emitter's own receipt. It declares the DATATYPE its fill
#: lands on (`layers[].fill_datatype`), which is what makes the fill exemption
#: datatype-precise instead of swallowing a whole layer.
CMP_FILL_REL = "reports/phase3/cmp_fill_emit.json"
FINISHING_REL = "reports/phase3/die_finishing.json"

#: `layer/datatype` as the finishing records spell it.
_PAIR_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


def _json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fill_datatypes(project: Path) -> Set[int]:
    """The datatype(s) the fill emitter DECLARES it writes on, read from its receipt."""
    rec = _json(project / CMP_FILL_REL) or {}
    out: Set[int] = set()
    for row in (rec.get("layers") or []):
        dt = row.get("fill_datatype") if isinstance(row, dict) else None
        if isinstance(dt, int) and not isinstance(dt, bool):
            out.add(dt)
    return out


def _default_fill_pairs(project: Path, *, _validated_stream=None) -> Tuple[set, Optional[dict]]:
    """Read the consumed native filler's literal write set, not layer guesses."""
    import librelane_fill_dfm as fill
    import librelane_signoff_evidence as native
    import die_level_deck_rule_attribution as attribution
    if not (project / fill.DEFAULT_STREAM_REL).is_file():
        return set(), None
    promotion = (_validated_stream if _validated_stream is not None
                 else fill.validate_default_stream(project))
    arm = _json(project / fill.RECORD_REL)['gds']['librelane']
    folder = Path(arm['filler']['state']).parent
    receipt = fill.validate_step_receipt(folder, 'KLayout.Filler')
    cfg = _json(folder / 'config.json')
    script = cfg.get('KLAYOUT_FILLER_SCRIPT')
    if not script:
        return set(), None
    switch = project / 'phase3/librelane_switch.json'
    mounts = native._pdk_mounts(project, _json(switch) if switch.is_file() else {},
                                folder, promotion['image'])
    source = Path(script)
    if not source.is_file():
        for host, guest in mounts:
            if source.is_relative_to(guest):
                source = Path(host) / source.relative_to(guest)
                break
    if receipt['input']['config_files'].get(script) != _sha256(source):
        raise ValueError('XOR_FILLER_SCRIPT_UNBOUND')
    original = source.read_text()
    text = attribution.deck_code_only(original)
    declared = {name: (int(layer), int(datatype)) for name, layer, datatype in re.findall(
        r'^\s*(\w+)\s*=\s*\$ly\.layer\(\s*(\d+)\s*,\s*(\d+)\s*\)', text, re.M)}
    # The receipt binds the parent, not its require_relative children. Read the
    # parent's explicitly created fill containers in its original bound output;
    # current child source must never expand an old producer's write set.
    containers = {match.group(1) for match in re.finditer(
        r'^\s*\$fill_cell\w*\s*=\s*\$ly\.create_cell\(["\']([^"\']+)["\']\)',
        original, re.M) if text[match.start():].lstrip().startswith('$fill_cell')}
    import _gds_geometry as geometry
    try:
        before = geometry.read_layout(Path(arm['filler']['gds_in']))
        original_cells = set(before.cells)
        if not containers or containers.intersection(original_cells):
            raise ValueError('XOR_FILLER_CONTAINER_NOT_NEW')
        del before
        deposited = geometry.read_layout(Path(arm['filler']['filled_gds']))
    except geometry.GdsError as exc:
        raise ValueError('XOR_FILLER_OUTPUT_UNREADABLE: ' + str(exc)) from exc
    pending, visited, pairs = list(containers), set(), set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        if name in original_cells:
            raise ValueError('XOR_FILLER_REFERENCES_EXISTING_DESIGN_CELL')
        visited.add(name)
        cell = deposited.cells[name]
        pairs.update((element.layer, element.datatype) for element in cell.own_area_elements())
        pending.extend(element.sname for element in cell.refs())
    if not pairs.issubset(set(declared.values())):
        raise ValueError('XOR_FILLER_WRITE_SET_NOT_DECLARED')
    sources = {str(source): _sha256(source), arm['filler']['gds_in']: arm['filler']['gds_in_sha256'],
               arm['filler']['filled_gds']: arm['filler']['filled_sha256']}
    topup = arm.get('density_topup')
    if topup:
        config = _json(Path(topup['config']))
        report = _json(Path(topup['report']))
        active = {row['name'] for row in report['layers'] if row.get('passes', 0) > 0}
        for row in config['layers']:
            if row['name'] not in active:
                continue
            layer, datatype = row['layer'][0], row.get('fill_datatype')
            if type(layer) is not int or type(datatype) is not int:
                raise ValueError('XOR_TOPUP_WRITE_SET_NOT_DECLARED')
            pairs.add((layer, datatype))
        sources.update({topup['config']: topup['config_sha256'],
                        topup['report']: topup['report_sha256']})
    return pairs, {'source': fill.RECORD_REL, 'field': 'gds.librelane.filler/density_topup',
                   'pairs': [f'{l}/{d}' for l, d in sorted(pairs)],
                   'granularity': 'layer/datatype', 'native_sources': sources}


def declared_finishing_layers(project: Path, *, _validated_stream=None) -> Tuple[Set[int], Set[Tuple[int, int]],
                                                      Dict[str, Any]]:
    """({fill layer numbers}, {seal (layer, datatype) pairs}, provenance).

    Read from the run's OWN records, never from a layer-name convention: a layer
    is exempt from the design-layer count only because a finishing step SAID it
    added it.
    """
    prov: Dict[str, Any] = {"fill": None, "seal_ring": None}
    fill_pairs: Set[Tuple[int, Optional[int]]] = set()
    seal_pairs: Set[Tuple[int, int]] = set()

    # THE GENERATOR'S WHOLE WRITE SET, not one pass of it. `fill.owned_layers` is
    # the METAL pass's layers; the die-wide generator also runs a COMP pass and a
    # Poly2 pass, and the run's own receipt says so in the same document:
    # `fill.probe.layers_the_whole_generator_writes` = [22,30,34,36,42,46,81] with
    # `layers_per_pass` naming fill_comp.rb -> [22], fill_poly2.rb -> [30],
    # fill_metal.rb -> the five metals. Reading only `owned_layers` left 22/4 and
    # 30/4 unattributed, and this program then reported 85,581 differences as a
    # DESIGN fidelity finding when both counts were the run's own fill cells
    # (COMP_fill_cell 75,175 and Poly2_fill_cell 10,406, from the route
    # attestation's reachable_structure_references). Widest DECLARED set, then.
    fill = _json(project / FILL_REL)
    fblock = (fill or {}).get("fill") or {}
    whole = (fblock.get("probe") or {}).get("layers_the_whole_generator_writes")
    owned = fblock.get("owned_layers")
    layers = whole if isinstance(whole, list) else owned
    field = ("fill.probe.layers_the_whole_generator_writes"
             if isinstance(whole, list) else "fill.owned_layers")
    if isinstance(layers, list):
        nums = {int(x) for x in layers
                if isinstance(x, int) and not isinstance(x, bool)}
        # DATATYPE-PRECISE WHERE THE EMITTER DECLARES ONE. The fill lands on a
        # datatype the CMP emitter names (4 on run21), so exempting the whole layer
        # would also excuse 22/0 and 30/0 -- real design layers. Pairing each
        # declared layer with each declared fill datatype keeps those checked; with
        # no datatype declared the exemption stays layer-wide, as before, and the
        # provenance says which of the two was used.
        dts = fill_datatypes(project)
        if dts:
            fill_pairs = {(n, d) for n in nums for d in dts}
        else:
            fill_pairs = {(n, None) for n in nums}
        prov["fill"] = {"source": FILL_REL, "field": field,
                        "layers": sorted(nums),
                        "datatypes": sorted(dts) if dts else None,
                        "datatype_source": CMP_FILL_REL if dts else None,
                        "granularity": "layer/datatype" if dts else "layer-wide"}

    fin = _json(project / FINISHING_REL)
    added = (((fin or {}).get("seal_ring") or {}).get("ring_check")
             or {}).get("added_layers")
    if isinstance(added, list):
        for item in added:
            m = _PAIR_RE.match(str(item))
            if m:
                seal_pairs.add((int(m.group(1)), int(m.group(2))))
        prov["seal_ring"] = {"source": FINISHING_REL,
                             "field": "seal_ring.ring_check.added_layers",
                             "pairs": [f"{l}/{d}" for l, d in sorted(seal_pairs)]}
    native_pairs, native_provenance = (
        _default_fill_pairs(project) if _validated_stream is None else
        _default_fill_pairs(project, _validated_stream=_validated_stream))
    if native_provenance is not None:
        fill_pairs.update(native_pairs)
        prov['fill'] = native_provenance
    return fill_pairs, seal_pairs, prov


#: Where the flow itself puts the two artefacts, for a run that attested no pair.
#: These are the SAME strings the flow declares -- step 37's gate hard-requires
#: `phase3/stage4/gds/*.gds` and step 21's requires `phase3/stage3/pnr/routed.def`
#: -- so a project missing either has already FAILED at the step that owed it.
CANONICAL_GDS_GLOB = "phase3/stage4/gds/*.gds"
CANONICAL_DEF_REL = "phase3/stage3/pnr/routed.def"


def shipped_and_source(project: Path, *, _validated_stream=None) -> Tuple[Optional[Path], Optional[Path],
                                               Dict[str, Any]]:
    """(shipped GDS, the routed DEF it was streamed from, the run's attestation).

    PREFERRED SOURCE: `pad_ring_route_evidence.json`, which records the GDS path
    and sha256 beside `gds_source_def` and ITS sha256. Taking them from there
    rather than by globbing binds the comparison to the pair the run attested, and
    makes a tree whose GDS has since changed detectable.

    BUT THE ATTESTATION IS THE BINDING, NOT THE SUBJECT, and conflating the two
    was a real defect in the first shape of this step. The runner writes that file
    only under `_chip_path_requests_pad_ring(project)`, so on every design that is
    not on the chip pad-ring path there is no attestation -- and the first draft
    made the STEP conditional on it, which `flow_condition_reachability_check`
    named for what it is: a SELF-DISABLING CONDITION on an artefact the flow
    itself produces, where "the file is missing" and "the fidelity check was never
    made" are indistinguishable to every reader downstream. Its absence is loud
    NOWHERE (T7=None, T3=None, T5=None, measured).

    So the subject is the TWO ARTEFACTS, which is what the fidelity question is
    actually about, and both have a loud absence: the shipped GDS is a hard
    `files_exist` in step 37's own gate and the routed DEF is one in step 21's, so
    a project missing either FAILED there and never reaches here looking clean.
    The attestation, when the run wrote one, still decides the pairing and still
    refuses on a sha256 that no longer holds; when it did not, the canonical flow
    paths are used and `att["binding"]` says so, so no reader can mistake a
    convention-bound comparison for an attested one.
    """
    import librelane_fill_dfm as fill
    if (project / fill.DEFAULT_STREAM_REL).is_file():
        try:
            stream = (_validated_stream if _validated_stream is not None
                      else fill.validate_default_stream(project))
            return Path(stream['canonical']), Path(stream['filled_def']), {
                'source': fill.DEFAULT_STREAM_REL, 'binding': 'native-current-stream',
                'gds': stream['canonical'],
                'gds_sha256_recorded': stream['canonical_sha256'],
                'def': stream['filled_def'],
                'def_sha256_recorded': stream['filled_def_sha256'],
                'streamout_engine': 'klayout'}
        except (fill.Refusal, OSError, ValueError, KeyError) as exc:
            return None, None, {'source': fill.DEFAULT_STREAM_REL,
                                'binding': 'REFUSED', 'reason': str(exc)}
    ev = _json(project / ROUTE_EVIDENCE_REL) or {}
    gds_rel = ((ev.get("gds_evidence") or {}).get("path"))
    def_rel = ev.get("gds_source_def")
    att = {
        "source": ROUTE_EVIDENCE_REL,
        "gds": gds_rel,
        "gds_sha256_recorded": (ev.get("gds_evidence") or {}).get("sha256"),
        "def": def_rel,
        "def_sha256_recorded": ev.get("gds_source_def_sha256"),
        "streamout_engine": (ev.get("gds_evidence") or {}).get("streamout_engine"),
        "binding": "attested" if isinstance(gds_rel, str) else "",
    }
    gds = (project / gds_rel) if isinstance(gds_rel, str) else None
    dfile = (project / def_rel) if isinstance(def_rel, str) else None

    if gds is None or not gds.is_file():
        # SORTED, so two candidate GDS files pick the same one on every host: an
        # unordered glob would make the subject depend on directory order.
        found = sorted(project.glob(CANONICAL_GDS_GLOB))
        if found:
            gds = found[0]
            att.update(binding="flow-canonical",
                       gds=str(gds.relative_to(project)),
                       gds_sha256_recorded=None,
                       binding_reason=(
                           f"{ROUTE_EVIDENCE_REL} attested no shipped GDS "
                           f"(this design is not on the chip pad-ring path), so "
                           f"the subject is the flow's own declaration "
                           f"{CANONICAL_GDS_GLOB} -- whose absence FAILs step 37"))
    if dfile is None or not dfile.is_file():
        cand = project / CANONICAL_DEF_REL
        if cand.is_file():
            dfile = cand
            att.setdefault("binding_reason", "")
            att.update(binding=att["binding"] or "flow-canonical",
                       def_sha256_recorded=None)
            att["def"] = CANONICAL_DEF_REL
    return gds, dfile, att


#: The boundary artefact the gds step retains: the stream-out BEFORE fill, seal
#: ring and snap. Same shape as the boundary DEFs #2484 keeps, and for the same
#: reason -- every finishing pass writes IN PLACE, so a "before" only exists if it
#: was kept.
PREFINISH_REL_FMT = "phase3/stage3/pnr/{top}.prefinish.gds"
#: A GLOB, NOT ONE NAME, and for the same reason `STREAMOUT_LOG_GLOB` below is one.
#:
#: The runner retains `{top}.prefinish.gds` where `top` is the name PnR ran under;
#: this checker resolved `{top}` from the DEF FILE'S STEM. Those are not the same
#: string. MEASURED on spm run22: the shipped GDS is `spm.gds`, the source DEF is
#: `spm.def` -- so this looked for `phase3/stage3/pnr/spm.prefinish.gds` -- while
#: the boundary the run actually kept is `phase3/stage3/pnr/chip_top.prefinish.gds`
#: (the runner's top was `chip_top`, and the front door's own advisory recorded
#: "phase3 auto-derived top='spm' from --ic-name (no chip_top module)").
#:
#: The names could not meet, so the RETAINED boundary was never used and every run
#: fell back to a re-stream. That fallback is the expensive path this artefact
#: exists to avoid, and a re-stream missing one library produces a CONFIDENT WRONG
#: ANSWER about the design -- 776,403 then 348,392 phantom differences, measured,
#: and neither of them about that chip.
#:
#: One boundary per run, so a glob is exact rather than lenient: if it ever matches
#: more than one, `resolve_reference` refuses instead of guessing.
PREFINISH_GLOB = "phase3/stage3/pnr/*.prefinish.gds"
#: The run's own retained stream-out recipe and its transcript. A fallback that
#: re-streams must use THE RUN'S recipe, not a hand-rolled read: that mistake
#: produced 776,403 differences across 29 design layers on run21 -- placement boxes
#: against real standard-cell geometry -- and it was mine, not the design's.
STREAMOUT_SCRIPT_REL = "phase3/stage3/pnr/stream_out.py"
#: A GLOB, NOT ONE NAME, because the two stream-out engines write two names:
#: KLayout writes `stream_out.log` and Magic writes `<top>.magic_stream_out.log`.
#: Reading only the KLayout name meant a Magic-streamed run recovered NO library
#: hints at all and its re-streamed reference came out thin -- caught, but caught
#: as a refusal from `reference_is_faithful` rather than answered. This is also
#: the spelling step 37 declares and its own gate asserts, so the read, the
#: declaration and the assertion are the same set.
STREAMOUT_LOG_GLOB = "phase3/stage3/pnr/*stream_out.log"

#: The three field lines of the stream-out transcript that name a library input.
#:
#: ANCHORED AT BOTH ENDS, WITH A CLOSED FIELD TYPE, AND THAT IS WHAT MAKES THE
#: POLARITY QUESTION NOT ARISE HERE. Every one of these lines is written by the
#: run's own stream-out recipe (`phase3_one_shot_runner`, the stream-out body)
#: with `print(f"<TOKEN> <verb phrase>: {value}")`, from a value it had already
#: resolved -- so the grammar has no free-text field in which a denial could be
#: spelled. The recipe DOES say the negative, and it says it in DIFFERENT
#: productions that these patterns cannot reach:
#:     "LEFDEF_MAP not applied (none configured) - legacy numbering"
#:     "LEFDEF_MAP_CONFIGURED_BUT_ABSENT: ..."
#:     "MACRO_GDS merged (no DEF master matched): <path>"
#:     "CELL_GDS manual-substituted <n> std cell(s)"        (no ": <path>" field)
#: none of which matches `<TOKEN> <the exact verb>: <\S+>$`. A non-match leaves
#: the key OUT of the env dict, which is exactly what the denial means -- the
#: re-stream then passes no such variable and reads what the run read.
_LOG_PATTERNS = (
    ("LEFDEF_MAP", re.compile(r"^LEFDEF_MAP applied:\s*(\S+)\s*$", re.M), False),
    ("CELL_GDS", re.compile(r"^CELL_GDS manual-substitute \(post-read\):\s*(\S+)\s*$", re.M), False),
    ("MACRO_GDS", re.compile(r"^MACRO_GDS manual-substituted \d+ macro\(s\):\s*(\S+)\s*$", re.M), True),
)


def restream_env_from_transcript(project: Path) -> Tuple[Dict[str, str], List[str]]:
    """({env the run's stream-out used}, the transcript lines that said so).

    READ, not guessed. The run keeps `stream_out.log`, and it names the library
    inputs it resolved -- the layermap it applied, the std-cell GDS it substituted
    229 cells from, the two macro GDS files it substituted 16 macros from. Those
    are container-side PDK paths and must NOT be translated again, which is why
    only the project-side keys go in `path_keys` at the call.
    """
    env: Dict[str, str] = {}
    cited: List[str] = []
    # NEWEST LAST, and sorted so two candidates pick the same one on every host.
    # A DRC re-stream leaves a second Magic transcript beside the first, and the
    # library set that matters is the one the SHIPPED GDS came from.
    found = sorted(project.glob(STREAMOUT_LOG_GLOB),
                   key=lambda q: (q.stat().st_mtime, q.name))
    if not found:
        return env, cited
    log = found[-1]
    rel = log.relative_to(project).as_posix()
    try:
        text = log.read_text(errors="replace")
    except OSError:
        return env, cited
    for key, pattern, many in _LOG_PATTERNS:
        found = pattern.findall(text)
        if not found:
            continue
        # ";" IS THE SEPARATOR THE SCRIPT PARSES, not whitespace: the recipe
        # reads MACRO_GDS as `os.environ.get('MACRO_GDS','').split(';')`
        # (phase3_one_shot_runner.py, the stream-out body). Joining with a space
        # hands it ONE unopenable path, both macro libraries are silently lost,
        # and the only symptom is a reference that is too small.
        env[key] = ";".join(dict.fromkeys(found)) if many else found[0]
        cited.append(f"{rel}: {key} = {env[key][:120]}")
    return env, cited


#: The KLayout batch script. Streams the routed DEF, XORs it against the shipped
#: GDS and prints one machine-readable line per differing layer. Printing rather
#: than writing a database: the counts are the evidence and a reader should not
#: have to open a layout to get them.
_XOR_RB = r'''
begin
  ship = RBA::Layout::new
  ship.read(ENV["XOR_SHIPPED"])
  ref  = RBA::Layout::new
  ref.read(ENV["XOR_REFERENCE"])
  top_s = ship.top_cell
  top_r = ref.top_cell
  if top_s.nil? || top_r.nil?
    puts "XOR_ERROR no top cell"
    exit 3
  end
  puts "XOR_TOOL klayout"
  puts "XOR_TOP shipped=#{top_s.name} reference=#{top_r.name}"
  # THE FAITHFULNESS CENSUS, printed before any difference is counted. A
  # reference that is missing libraries produces a CONFIDENT WRONG ANSWER, and
  # nothing in the difference counts reveals it -- measured twice on run21: a bare
  # DEF read gave 776,403 differences and a re-stream missing cell substitution
  # gave 348,392, and only the reference's SIZE (8.3 MB against a shipped 102.9 MB)
  # gave either away. So the census is evidence the caller checks, not decoration.
  def census(ly)
    shapes = 0
    ly.each_cell { |c| ly.layer_indexes.each { |i| shapes += c.shapes(i).size } }
    [ly.cells.to_s, shapes.to_s]
  end
  sc, ss = census(ship)
  rc2, rs = census(ref)
  puts "XOR_CENSUS shipped_cells=#{sc} shipped_shapes=#{ss} reference_cells=#{rc2} reference_shapes=#{rs}"
  if ENV["XOR_BOUNDARY"]
    boundary = RBA::Layout::new
    boundary.read(ENV["XOR_BOUNDARY"])
    bc, bs = census(boundary)
    puts "XOR_BOUNDARY_CENSUS cells=#{bc} shapes=#{bs}"
  end
  layers = {}
  ship.layer_indexes.each { |i| li = ship.get_info(i); layers[[li.layer, li.datatype]] = true }
  ref.layer_indexes.each  { |i| li = ref.get_info(i);  layers[[li.layer, li.datatype]] = true }
  layers.keys.sort.each do |pair|
    lay, dt = pair
    a = RBA::Region::new
    b = RBA::Region::new
    is = ship.find_layer(lay, dt)
    ir = ref.find_layer(lay, dt)
    a.insert(top_s.begin_shapes_rec(is)) unless is.nil?
    b.insert(top_r.begin_shapes_rec(ir)) unless ir.nil?
    d = a ^ b
    puts "XOR_LAYER #{lay}/#{dt} #{d.count}"
  end
  puts "XOR_DONE"
end
'''


def run_xor(runner, scratch: Path, shipped: Path, reference: Path,
            timeout: int, *, boundary: Optional[Path] = None) -> Tuple[int, str, str]:
    """Execute the XOR script, translating both paths for the runner.

    THE SCRIPT LIVES IN `scratch`, which is inside the project, because a
    container runner only reaches what its bind-mounts cover: a script written to
    the host's own /tmp produced
    `ERROR: Unable to open file: /tmp/.../xor.rb (errno=2)`. The paths are passed
    through the ENVIRONMENT and named in `path_keys` -- that is how
    `KLayoutRunner.run` translates a host path to its in-container spelling; ARGV
    is not plumbed at all.
    """
    script = scratch / "xor.rb"
    script.write_text(_XOR_RB)
    env = {"XOR_SHIPPED": shipped, "XOR_REFERENCE": reference}
    if boundary is not None:
        env["XOR_BOUNDARY"] = boundary
    return runner.run(script, env, path_keys=tuple(env), timeout=timeout)


_CENSUS_RE = re.compile(
    r"^XOR_CENSUS shipped_cells=(\d+) shipped_shapes=(\d+) "
    r"reference_cells=(\d+) reference_shapes=(\d+)$", re.M)

#: How much smaller than the shipped layout a reference may be before it is
#: refused as unfaithful. The pre-finishing reference is legitimately smaller --
#: fill and seal ring add geometry -- but not by an ORDER OF MAGNITUDE: on run21
#: the shipped layout is 1,464,279 shapes and an unfaithful reference came back at
#: a fraction of that while a faithful one must carry all the standard cells.
_MIN_REFERENCE_SHAPE_FRACTION = 0.5


def reference_is_faithful(stdout: str, *, boundary: bool = False) -> Tuple[bool, str, Dict[str, int]]:
    """(is it plausible, why not, the census).

    A reference missing a library is the failure mode this program must never
    report as a design finding, and it cannot be seen in the difference counts.
    So the two layouts' own censuses are compared, and an implausibly thin
    reference is REFUSED rather than trusted.
    """
    m = _CENSUS_RE.search(stdout)
    if not m:
        return False, "the comparison printed no census, so the reference could not be checked for faithfulness", {}
    stats = {"shipped_cells": int(m.group(1)), "shipped_shapes": int(m.group(2)),
             "reference_cells": int(m.group(3)), "reference_shapes": int(m.group(4))}
    if stats["shipped_shapes"] <= 0:
        return False, "the shipped layout reports zero shapes", stats
    denominator = stats['shipped_shapes']
    if boundary:
        owned = re.search(r'^XOR_BOUNDARY_CENSUS cells=(\d+) shapes=(\d+)$', stdout, re.M)
        if not owned or int(owned.group(2)) <= 0:
            return False, 'the validated pre-finishing boundary printed no nonempty census', stats
        stats.update(boundary_cells=int(owned.group(1)), boundary_shapes=int(owned.group(2)))
        denominator = stats['boundary_shapes']
    frac = stats["reference_shapes"] / denominator
    if frac < _MIN_REFERENCE_SHAPE_FRACTION:
        return False, (
            f"the reference carries {stats['reference_shapes']} shape(s) in "
            f"{stats['reference_cells']} cell(s) against the "
            f"{'validated pre-finishing boundary' if boundary else 'shipped layout'}'s "
            f"{denominator} in {stats.get('boundary_cells', stats['shipped_cells'])} "
            f"({frac:.1%}) — a pre-finishing reference is smaller, but not by that "
            f"much, so a library did not resolve and any difference count here "
            f"would be about THIS PROGRAM and not about the design"), stats
    return True, "", stats


def _default_stream_boundary(project: Path, dfile: Path, shipped: Path, *,
                             _validated_stream=None) -> Optional[Path]:
    """The original native stream, before its validated seal/fill chain.

    Completeness compares streams of the same database boundary. A finishing
    deposit is not evidence that a pre-finishing reference lost a library.
    """
    import librelane_fill_dfm as fill
    if not (project / fill.DEFAULT_STREAM_REL).is_file():
        return None
    record = (_validated_stream if _validated_stream is not None
              else fill.validate_default_stream(project))
    if (Path(record['filled_def']).resolve() != dfile.resolve()
            or Path(record['canonical']).resolve() != shipped.resolve()):
        raise ValueError('XOR_DEFAULT_BOUNDARY_SUBJECT_CHANGED')
    return Path(record['stream']).resolve()


def parse_layers(stdout: str) -> Tuple[Dict[Tuple[int, int], int], bool]:
    """({(layer, datatype): differing-polygon count}, the script ran to the end).

    The DONE marker is required: a truncated transcript is not a clean zero, which
    is the whole failure mode this module exists to avoid reproducing.
    """
    counts: Dict[Tuple[int, int], int] = {}
    for m in re.finditer(r"^XOR_LAYER (\d+)/(\d+) (\d+)$", stdout, re.M):
        counts[(int(m.group(1)), int(m.group(2)))] = int(m.group(3))
    return counts, bool(re.search(r"^XOR_DONE$", stdout, re.M))


def partition(counts: Dict[Tuple[int, int], int],
              fill_pairs: Set[Tuple[int, Optional[int]]],
              seal_pairs: Set[Tuple[int, int]]
              ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """(design rows, finishing rows, design total). Only DIFFERING layers appear."""
    design: List[Dict[str, Any]] = []
    finishing: List[Dict[str, Any]] = []
    total = 0
    for (lay, dt), n in sorted(counts.items()):
        if n == 0:
            continue
        row = {"layer": lay, "datatype": dt, "differences": n}
        if (lay, dt) in seal_pairs:
            finishing.append({**row, "declared_by": "seal_ring"})
        elif (lay, dt) in fill_pairs or (lay, None) in fill_pairs:
            finishing.append({**row, "declared_by": "density_fill"})
        else:
            design.append(row)
            total += n
    return design, finishing, total


def reanchored(project: Path, recorded: str) -> str:
    """A path the run recorded, re-anchored to THIS project directory.

    The run records ABSOLUTE HOST paths for the artefacts it produced itself
    (`technology_units.json.tech_lef` is the legalized tlef in the run's own pnr
    dir). Read on a COPY of that run those paths point at the ORIGINAL root --
    another lane's directory, which this program must not read, and which on the
    dispatcher host may not exist at all. Re-anchoring is by the LONGEST TAIL THAT
    EXISTS under `project`: existence-tested, so it cannot silently invent a file,
    and convention-free, so it does not care that a copy is named `run21x` while
    the original was `run21`. A path that already resolves is returned untouched,
    and one with no existing tail is returned unchanged so the caller's own
    open-failure names the real path.
    """
    if not recorded or Path(recorded).exists():
        return recorded
    parts = PurePosixPath(recorded).parts
    for i in range(1, len(parts)):
        cand = project.joinpath(*parts[i:])
        if cand.exists():
            return str(cand)
    return recorded


#: The stream-out's OWN record of what it read, written beside the GDS it
#: streamed and keyed on that output's stem (`_stream_input_record`). The
#: re-stream reads it and nothing else: an earlier revision assembled the LEF
#: set from `technology_units.json`, the pad-ring IO record and a registry glob,
#: which is empty for every design without an IO ring -- MEASURED on fxspm1's
#: spm integration run, step 37.3 NOT_MEASURED for a GDS the flow had streamed.
STREAM_INPUTS_REL_FMT = "phase3/stage3/pnr/{stem}.stream_inputs.json"


def _inputs_hold_the_recorded_bytes(runner, pairs: List[Tuple[str, str]],
                                    timeout: int) -> Tuple[bool, str]:
    """Does each `(tool-side path, sha256)` hold those bytes WHERE THE TOOL RUNS?

    Asked in the runner's own environment -- a PDK file inside the container has
    no host copy -- through `sha256sum -c --status`, whose EXIT CODE is the
    answer; nothing is read out of its text. On a failure each input is asked
    alone, so the refusal names the one that moved.
    """
    def check(some: List[Tuple[str, str]]) -> int:
        sums = "".join(f"{sha}  {path}\n" for path, sha in some)
        rc, _so, _se = runner.run_argv(
            ["bash", "-c", 'printf "%s" "$VIBEIC_XOR_SUMS" | sha256sum -c --status -'],
            {"VIBEIC_XOR_SUMS": sums}, timeout=timeout)
        return rc
    if check(pairs) == 0:
        return True, ""
    for path, sha in pairs:
        if check([(path, sha)]) != 0:
            return False, (f"{path} does not hold the bytes the stream-out read "
                           f"(recorded sha256 {sha[:16]}...)")
    return False, ("the recorded inputs do not verify as a set although each "
                   "verifies alone")


def _def_design_name(def_file: Optional[Path]) -> str:
    """The DESIGN statement of a DEF — the name the runner writes the boundary under.

    Read from the DEF itself rather than inferred from its filename, because those
    are different strings on every pad-ring run and on every run whose DEF is
    `routed.def`: that mismatch is the defect this resolver exists to close.
    """
    if def_file is None:
        return ""
    try:
        with def_file.open("r", errors="replace") as fh:
            for line in fh:
                text = line.strip()
                if text.startswith("DESIGN "):
                    parts = text.split()
                    if len(parts) >= 2:
                        return parts[1].strip().rstrip(";").strip()
                if text.startswith("COMPONENTS "):
                    break            # DESIGN precedes COMPONENTS in a valid DEF
    except OSError:
        return ""
    return ""


def _boundary_is_this_runs(project: Path, kept: Path,
                           dfile: Optional[Path]) -> Tuple[bool, str]:
    """Is this retained boundary provably the one THIS run streamed?

    The runner writes a receipt beside it carrying the sha256 it computed, the size,
    and the DEF it streamed from with that DEF's sha256. A boundary whose receipt is
    absent, unreadable, or disagrees with the bytes now on disk is not evidence about
    this run; neither is one streamed from a DEF that is no longer the DEF being
    compared. Refusing is cheap -- the caller re-streams, which is what it did before
    any of this existed.
    """
    receipt = kept.with_suffix(".gds.receipt.json")
    try:
        rec = json.loads(receipt.read_text(errors="replace"))
    except (OSError, ValueError):
        return False, (f"no readable receipt at "
                       f"{receipt.relative_to(project).as_posix()}")
    if not isinstance(rec, dict):
        return False, "the receipt is not an object"
    live = _sha256(kept)
    if str(rec.get("sha256") or "") != live:
        return False, ("the receipt describes different bytes "
                       "(sha256 mismatch), so the file has been replaced since")
    if dfile is not None and rec.get("def_sha256"):
        if str(rec["def_sha256"]) != _sha256(dfile):
            return False, (f"it was streamed from a different "
                           f"{rec.get('streamed_from_def') or 'DEF'} than the one "
                           f"being compared")
    return True, ""


def resolve_reference(project: Path, top: str,
                     dfile: Optional[Path] = None) -> Tuple[Optional[Path], str,
                                                       Dict[str, Any]]:
    """(retained pre-finishing GDS, "retained"|"restreamed", provenance).

    PREFERRED: the boundary artefact the gds step retains. Then the comparison is
    against bytes THIS RUN wrote before finishing touched anything, and the
    expectation on design layers is exactly 0.

    FALLBACK, for runs that predate the artefact (run21 and earlier): re-stream
    through the run's OWN recipe. A re-streamed reference can differ by stream-out
    nondeterminism, so a nonzero there must be attributed per layer before anyone
    calls it a fidelity finding -- which is why the receipt says WHICH reference it
    used and never lets the two be confused.
    """
    import librelane_fill_dfm as fill
    if (project / fill.DEFAULT_STREAM_REL).is_file():
        stream = fill.validate_default_stream(project)
        kept = Path(stream['stream'])
        if dfile is None or Path(stream['filled_def']).resolve() != dfile.resolve():
            raise ValueError('XOR_DEFAULT_BOUNDARY_DEF_CHANGED')
        return kept, 'retained native klayout', {
            'kind': 'retained', 'path': str(kept.relative_to(project)),
            'sha256': stream['stream_sha256'], 'evidence': fill.DEFAULT_STREAM_REL,
            'note': 'original receipt-bound native StreamOut before seal and fill'}
    # NAMED BY THE DEF'S OWN DESIGN, AND PROVEN TO BE THIS RUN'S. R-0915-148.
    #
    # My first cut resolved the exact `{top}` spelling and then GLOBBED
    # `*.prefinish.gds`. The glob fixed the name mismatch and opened a worse hole,
    # which a pre-landing review caught: nothing tied the single match to THIS run.
    # Both stream-out branches now retain a boundary with a receipt.  An older
    # KLayout boundary must never be mistaken for a later Magic run's layout:
    # the receipt binds its bytes and routed DEF to the run being compared.
    #
    # Two things close it. The name is DERIVED, not guessed: the runner names the
    # file after the DEF's own DESIGN statement, so this reads that statement. And
    # the artefact must be PROVABLE: the runner records a receipt beside it (sha256,
    # size, the DEF it was streamed from and that DEF's sha), and a boundary whose
    # receipt is absent, unreadable, or disagrees with the bytes on disk is NOT this
    # run's. An unprovable boundary re-streams, exactly as an absent one does --
    # never `retained`.
    design = _def_design_name(dfile) if dfile is not None else ""
    candidates = []
    if design:
        candidates.append(PREFINISH_REL_FMT.format(top=design))
    if top and top != design:
        candidates.append(PREFINISH_REL_FMT.format(top=top))
    kept, rel = None, ""
    for cand in candidates:
        if (project / cand).is_file():
            kept, rel = project / cand, cand
            break
    if kept is not None:
        ok, why = _boundary_is_this_runs(project, kept, dfile)
        if not ok:
            return None, "unprovable", {
                "kind": "unprovable",
                "path": rel,
                "note": (f"a retained finishing boundary is present but cannot be "
                         f"proven to belong to this run ({why}), so it is NOT used "
                         f"as the reference; the comparison re-streams the current "
                         f"DEF instead"),
            }
    if kept is not None and kept.is_file():
        return kept, "retained", {
            "kind": "retained", "path": rel, "sha256": _sha256(kept),
            "note": ("the stream-out the gds step kept BEFORE fill and seal ring, "
                     "after grid snap; design-layer differences are expected to be exactly 0"),
        }
    return None, "restreamed", {
        "kind": "restreamed",
        "note": (f"{rel} is absent, so the reference was re-streamed through the "
                 f"run's own recorded stream-out (engine, recipe and inputs under "
                 f"`stream_inputs`); stream-out nondeterminism can "
                 f"move a count here, so any nonzero design-layer difference must "
                 f"be attributed per layer before it is read as a fidelity finding"),
    }


def stream_reference(runner, scratch: Path, dfile: Path, out: Path, timeout: int,
                     *, stem: Optional[str] = None) -> Tuple[int, str, str]:
    """Stream the routed DEF to GDS: the PRE-FINISHING reference.

    From the run's own record of its stream-out (`STREAM_INPUTS_REL_FMT`, keyed
    on `stem`, the shipped GDS's): the same engine and recipe, and every input
    it names, each proven to hold the bytes it held then. Any gap is a refusal
    that names it -- rc 127, never an assembled substitute, because a reference
    missing one library produces a confident wrong answer about the design.
    """
    project = scratch.parent
    rec_rel = STREAM_INPUTS_REL_FMT.format(stem=stem or dfile.stem)
    rec, why = _sir.read(project / rec_rel)
    if rec is None:
        if not (project / STREAMOUT_SCRIPT_REL).is_file():
            return 127, "", (f"{rec_rel} is {why} and {STREAMOUT_SCRIPT_REL} is "
                             f"absent, so the run's own stream-out recipe cannot "
                             f"be reused and this program will not substitute "
                             f"one of its own")
        return 127, "", (
            f"the run records no stream-out input set: {rec_rel} is {why}. The "
            f"stream-out step writes it beside the GDS it streamed (engine, "
            f"recipe, LEFs, cell/macro GDS, layer map, each with its sha256), "
            f"and this program will not assemble one from other records -- a "
            f"reference missing one library measures the wrong thing")
    recipe_rel = (rec.get("recipe") or {}).get("project_rel")
    if (not isinstance(recipe_rel, str) or not recipe_rel
            or Path(recipe_rel).is_absolute()
            or Path(recipe_rel).as_posix() != recipe_rel
            or ".." in Path(recipe_rel).parts):
        return 127, "", (f"recorded recipe path {recipe_rel!r} is not a "
                         "canonical path within the current project")
    own = project / recipe_rel
    try:
        recipe_target = own.resolve(strict=True)
    except OSError:
        return 127, "", (f"recorded recipe {recipe_rel} is absent from the "
                         "current project")
    if not recipe_target.is_relative_to(project.resolve()):
        return 127, "", (f"recorded recipe {recipe_rel} resolves outside the "
                         "current project")
    if not recipe_target.is_file():
        return 127, "", (f"recorded recipe {recipe_rel} is not a file in the "
                         "current project")
    if _sha256(own) != (rec.get("recipe") or {}).get("sha256"):
        return 127, "", (f"{recipe_rel} changed since the stream-out ran "
                         f"({rec_rel} records a different sha256), so running it "
                         f"again would not reproduce that stream")
    def_rec = rec.get("def") or {}
    if def_rec.get("sha256") != _sha256(dfile):
        return 127, "", (f"the recorded stream-out read "
                         f"{def_rec.get('project_rel')} (sha256 "
                         f"{str(def_rec.get('sha256'))[:16]}...), not the DEF this "
                         f"check compares ({dfile.name}), so the reference would "
                         f"be of a different layout")
    unhashed = [e["path"] for e in _sir.all_entries(rec) if not e.get("sha256")]
    if unhashed:
        return 127, "", (f"{rec_rel} carries no sha256 for {len(unhashed)} "
                         f"input(s) (first: {unhashed[0]}), so a re-stream cannot "
                         f"prove it reads what the stream-out read")

    # Resolve the whole recorded set before asking the tool to hash anything.
    # A project input belongs to this copy of the run: falling back to the old
    # absolute path would verify the original's bytes and call an incomplete
    # copy reproducible. External inputs alone retain their absolute paths.
    resolved: Dict[int, str] = {}
    project_real = project.resolve()
    entries = _sir.all_entries(rec)
    for entry in entries:
        rel = entry.get("project_rel")
        if rel is None:
            path = entry.get("path")
            if not isinstance(path, str) or not Path(path).is_absolute():
                return 127, "", (f"recorded external input {path!r} has no "
                                 "absolute tool path")
            resolved[id(entry)] = path
            continue
        if (not isinstance(rel, str) or not rel
                or Path(rel).is_absolute() or Path(rel).as_posix() != rel
                or ".." in Path(rel).parts):
            return 127, "", (f"recorded project-relative input {rel!r} is "
                             "not a canonical path within the current project")
        candidate = project / rel
        try:
            target = candidate.resolve(strict=True)
        except OSError:
            return 127, "", (f"recorded project-relative input {rel} is "
                             "absent from the current project")
        if not target.is_relative_to(project_real):
            return 127, "", (f"recorded project-relative input {rel} resolves "
                             "outside the current project")
        if not target.is_file():
            return 127, "", (f"recorded project-relative input {rel} is not "
                             "a file in the current project")
        resolved[id(entry)] = str(runner.cpath(candidate))

    def resolve(entry: Dict[str, Any]) -> str:
        """Use only the paths checked above for both hashing and stream-out."""
        return resolved[id(entry)]

    ok, why = _inputs_hold_the_recorded_bytes(
        runner, [(resolve(e), e["sha256"]) for e in entries],
        timeout)
    if not ok:
        return 127, "", f"{why}, so a re-stream would not read what the stream-out read"
    native = rec.get('native_cli')
    if native is not None:
        # This recipe takes CLI arguments; applying the legacy environment
        # interface would silently omit its actual LEFs/maps/library GDS.
        try:
            import librelane_fill_dfm as fill
            fill.validate_default_stream(project)
            commands = Path(native['commands'])
            argv = list(native['argv'])
            if (_sha256(commands) != native['commands_sha256']
                    or len(argv) < 3 or Path(argv[1]).name != 'stream_out.py'):
                raise ValueError('native stream COMMANDS changed')
            argv[:3] = ['python3', str(runner.cpath(own)), str(runner.cpath(dfile))]
            seen = set()
            for entry in native['inputs']:
                index = entry['argv_index']
                if (type(index) is not int or index < 4 or index >= len(argv)
                        or index in seen or argv[index] != entry['path']):
                    raise ValueError('native stream input argument changed')
                argv[index] = resolve(entry)
                seen.add(index)
            output_index = argv.index('--output') + 1
            argv[output_index] = str(runner.cpath(out))
        except (OSError, ValueError, TypeError, KeyError, fill.Refusal) as exc:
            return 127, '', 'native stream recipe refused: ' + str(exc)
        return runner.run_argv(argv, {}, timeout=timeout)
    env: Dict[str, Any] = dict(_sir.iter_env(rec, resolve))
    env["TOP"] = rec.get("top") or dfile.stem
    if rec["engine"] == "klayout":
        env.update({"DEF": str(dfile), "GDS_OUT": str(out)})
        return runner.run(own, env, path_keys=("DEF", "GDS_OUT"), timeout=timeout)
    env.update({"DEF": runner.cpath(dfile), "GDS_OUT": runner.cpath(out)})
    return runner.run_argv(["magic", "-dnull", "-noconsole", "-rcfile",
                            resolve(rec["rcfile"]), runner.cpath(own)],
                           env, timeout=timeout)



# ══════════════════════════════════════════════════════════════════════
# THE JUDGE: read the run's own receipt, decide the step, measure nothing
# ══════════════════════════════════════════════════════════════════════
#: Typed so the flow's own taxonomy can classify the non-verdict instead of
#: guessing at prose. `_flow_reason_taxonomy.CAPABILITY_ABSENT` is the class for
#: a tool this checkout cannot reach; INPUT_ABSENT-shaped cases (no receipt at
#: all) are `ASKED_BEFORE_PRODUCER`, which is what an audit clause asked before
#: its producer ran actually is.
_JUDGE_CAPABILITY_ABSENT = "CAPABILITY_ABSENT"
_JUDGE_ASKED_BEFORE_PRODUCER = "ASKED_BEFORE_PRODUCER"


#: Step 37's LibreLane promotion record (librelane_step37.run).
LIBRELANE_PROMOTION_REL = "phase3/librelane/37-promotion.json"


#: U15 (IC_BLOCKER_AUDIT 2026-09-29) — the two measurements that can say the
#: SHIPPED GDS carries the routed layout's connectivity. Magic's and KLayout's
#: streams of the same routed DEF XOR'd against each other (step 37's LibreLane
#: chain, `37-xor.json`), or an LVS whose layout was EXTRACTED FROM the shipped
#: GDS bytes (`lvs_verdict.json` -> `layout_source`, kind "gds").
LIBRELANE_STREAM_XOR_REL = "phase3/librelane/37-xor.json"
LVS_VERDICT_REL = "reports/phase3/lvs_verdict.json"
CONNECTIVITY_BASES = ("magic_vs_klayout_stream_xor",
                      "lvs_extracted_from_shipped_gds")
#: Not skip-eligible (`_flow_reason_taxonomy`): the flow was handed this
#: question and did not perform the measurement that answers it.
_CONNECTIVITY_UNMEASURED_CLASS = "FLOW_DOES_NOT_PERFORM"


def _validated_native_connectivity(project, comparison, doc):
    """Apply the native reader's role binding to its same-call validated result."""
    import _native373_current as native
    import _physical_current as pc
    project = Path(project).resolve()
    current = comparison["current"]
    native._require(comparison.get("shipped_sha256_live") == current["inputs"]["shipped"]["sha256"],
                    "NATIVE373_SHIPPED_IDENTITY_CHANGED")
    native._require(current["inputs"].get("connectivity") == pc.entry(project, project / native.REL),
                    "NATIVE373_DEPENDENCY_SWAPPED")
    native._require(current["inputs"]["def"] == doc["current"]["inputs"]["def"], "NATIVE373_DEF_SWAPPED")
    native._require(current["design"] == doc["current"]["design"]
                    and current["pdk"] == doc["current"]["pdk"], "NATIVE373_CONTEXT_CHANGED")
    native._require(current["inputs"]["reference"] in (doc["current"]["outputs"]["magic_gds"],
                                                      doc["current"]["outputs"]["klayout_gds"]),
                    "NATIVE373_REFERENCE_NOT_NATIVE")
    return {"verdict": "PASS" if doc["count"] == 0 else "FAIL", "xor_difference_count": doc["count"],
            "evidence": native.REL, "evidence_sha256": pc.digest(project / native.REL),
            "reference_sha256": current["inputs"]["reference"]["sha256"],
            "scope": doc["scope"]}


def gds_connectivity(project: Path, live_sha256: str,
                     comparison: Optional[Dict[str, Any]] = None, *,
                     _validated_native=None) -> Dict[str, Any]:
    """Is the SHIPPED GDS (these bytes) shown to carry the routed connectivity?

    WHAT DOES NOT COUNT, measured on the spm IC-path tail (cx_spmic2_run,
    2026-09-28). Step 37.3 XOR'd the shipped GDS against
    `chip_top.prefinish.gds` -- the SAME KLayout stream-out, kept before fill
    and seal ring. Zero design-layer differences there proves finishing did not
    touch the design layers; it cannot see a stream-out that dropped a via or a
    net, because both sides carry the same stream. And step 31's LVS read the
    routed DEF (`_run_extraction_lvs` is DEF-direct), so no measurement in the
    run ever read the connectivity of the bytes that ship.

    Two independent measurements can, and each is bound to `live_sha256`:
      * step 37's LibreLane chain promoted THESE bytes (`canonical_sha256`) and
        its `KLayout.XOR` of the Magic and KLayout streams of the one routed
        DEF measured `design__xor_difference__count` (0 -> PASS, >0 -> FAIL);
      * `lvs_verdict.json` records a layout extracted from a GDS whose sha256
        is THESE bytes (PASS/FAIL from its own status).
    Anything else is NOT_MEASURED with the reason, never PASS. A measured FAIL
    from either outranks a PASS from the other.
    """
    found: List[Dict[str, Any]] = []
    looked: List[str] = []
    if comparison and (comparison.get("current") or {}).get("inputs", {}).get("connectivity"):
        import _native373_current as _bounded
        try:
            measured = (_bounded.connectivity(project, comparison)
                        if _validated_native is None else
                        _validated_native_connectivity(project, comparison, _validated_native))
            measured["basis"] = CONNECTIVITY_BASES[0]
            found.append(measured)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return {"subject_sha256": live_sha256, "measurements": [],
                    "not_measured_by": [str(exc)], "verdict": "NOT_DETERMINED", "basis": None,
                    "reason_class": _CONNECTIVITY_UNMEASURED_CLASS,
                    "reason": "current native stream dependency refused: " + str(exc)}
    promo = _json(project / LIBRELANE_PROMOTION_REL)
    if not isinstance(promo, dict):
        looked.append(f"{LIBRELANE_PROMOTION_REL} absent (no Magic-vs-KLayout "
                      f"stream XOR was run by step 37)")
    elif promo.get("canonical_sha256") != live_sha256:
        looked.append(f"{LIBRELANE_PROMOTION_REL} promoted different bytes "
                      f"({str(promo.get('canonical_sha256'))[:16]}...)")
    else:
        rec = _json(project / LIBRELANE_STREAM_XOR_REL)
        row = ((rec or {}).get("metrics") or {}).get(
            "design__xor_difference__count") or {}
        value = row.get("value")
        measured = (isinstance(value, int) and not isinstance(value, bool)
                    and row.get("status") in ("MEASURED", "FAIL")
                    and (rec or {}).get("verdict") in ("PASS", "FAIL"))
        if not measured:
            looked.append(f"{LIBRELANE_STREAM_XOR_REL} carries no measured "
                          f"design__xor_difference__count")
        else:
            found.append({
                "basis": CONNECTIVITY_BASES[0],
                "verdict": "PASS" if value == 0 else "FAIL",
                "evidence": LIBRELANE_STREAM_XOR_REL,
                "evidence_sha256": _sha256(project / LIBRELANE_STREAM_XOR_REL),
                "xor_difference_count": value})
    lvs = _json(project / LVS_VERDICT_REL)
    src = (lvs or {}).get("layout_source") if isinstance(lvs, dict) else None
    if not isinstance(lvs, dict):
        looked.append(f"{LVS_VERDICT_REL} absent")
    elif not isinstance(src, dict) or src.get("kind") != "gds":
        looked.append(
            f"{LVS_VERDICT_REL} records no layout extracted from a GDS "
            f"(layout_source={src.get('kind') if isinstance(src, dict) else None!r}"
            f"; an LVS extracted from the routed DEF says nothing about the "
            f"streamed bytes)")
    elif src.get("sha256") != live_sha256:
        looked.append(f"{LVS_VERDICT_REL} extracted a different GDS "
                      f"({str(src.get('sha256'))[:16]}..., shipped "
                      f"{live_sha256[:16]}...)")
    elif src.get("extracted_sha256") != live_sha256:
        # R-0929-GDSXOR-SPLIT: the private `<top>.lvs.gds` carries DEF-derived
        # rail markers that name power nets by overlap ("robust to via gaps"),
        # so its extraction decides power connectivity from the DEF, not from
        # the streamed bytes. Only an extraction OF the shipped bytes counts.
        looked.append(
            f"{LVS_VERDICT_REL} extracted {src.get('extracted') or 'unrecorded bytes'}"
            f" (sha256 {str(src.get('extracted_sha256'))[:16]}...), not the "
            f"shipped bytes ({live_sha256[:16]}...); a private DEF-augmented "
            f"LVS copy is not an extraction of the shipped GDS")
    elif lvs.get("status") not in ("PASS", "FAIL"):
        looked.append(f"{LVS_VERDICT_REL} on the shipped GDS has status "
                      f"{lvs.get('status')!r}, not a measured compare")
    else:
        found.append({
            "basis": CONNECTIVITY_BASES[1], "verdict": lvs["status"],
            "evidence": LVS_VERDICT_REL,
            "evidence_sha256": _sha256(project / LVS_VERDICT_REL),
            "finding": lvs.get("finding")})
    out: Dict[str, Any] = {"subject_sha256": live_sha256, "measurements": found,
                           "not_measured_by": looked}
    fails = [m for m in found if m["verdict"] == "FAIL"]
    if fails:
        out.update(verdict="FAIL", basis=fails[0]["basis"])
    elif found:
        out.update(verdict="PASS", basis=found[0]["basis"])
    else:
        out.update(verdict="NOT_DETERMINED", basis=None,
                   reason_class=_CONNECTIVITY_UNMEASURED_CLASS,
                   reason=("the shipped GDS's connectivity was not measured: "
                           + "; ".join(looked)))
    return out


def librelane_finishing_receipt(project: Path, live_sha256: str
                                ) -> Optional[Dict[str, Any]]:
    """The 37.3 receipt for a GDS step 37's LibreLane chain promoted, or None.

    None unless ``37-promotion.json`` names these exact bytes
    (``canonical_sha256`` == the shipped GDS's sha256). Then the promoted arm's
    judged ``Vibeic.FinishingXOR`` record decides: PASS -> 0 design-layer
    differences; a defect -> each design pair it names, from the State's
    per-pair metrics; a record that cannot be read or was not measured ->
    NOT_DETERMINED with its reason (never a zero).
    """
    promo_path = project / LIBRELANE_PROMOTION_REL
    if not promo_path.is_file():
        return None
    try:
        promo = json.loads(promo_path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(promo, dict) or promo.get("canonical_sha256") != live_sha256:
        return None
    arm = promo.get("selection")
    rel = f"phase3/librelane/37.3-{arm}-finishing-xor.json"
    base = {"reference": {"kind": "librelane_stream", "arm": arm,
                          "promotion": LIBRELANE_PROMOTION_REL,
                          "finishing_record": rel}}
    try:
        record = json.loads((project / rel).read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        return {"verdict": "NOT_DETERMINED", "rc": 2, "report": base,
                "reason": f"step 37 promoted a LibreLane stream but its finishing "
                          f"record {rel} is unreadable ({type(exc).__name__})"}
    rows = record.get("metrics") or {}
    defect = rows.get("vibeic__finishing_xor__defect__count") or {}
    if record.get("verdict") not in ("PASS", "FAIL") or \
            defect.get("status") not in ("MEASURED", "FAIL"):
        return {"verdict": "NOT_DETERMINED", "rc": 2, "report": base,
                "reason": f"{rel}: the finishing XOR was not measured "
                          f"({'; '.join(record.get('reasons') or []) or record.get('verdict')})"}
    state = {}
    folder = defect.get("folder")
    try:
        state = json.loads((Path(folder) / "state_out.json").read_text()).get("metrics") or {}
    except (OSError, ValueError, TypeError):
        state = {}
    prefix = "vibeic__finishing_xor__defect__count__pair:"
    diffs = []
    for key, value in sorted(state.items()):
        if key.startswith(prefix) and isinstance(value, int) and value > 0:
            layer, _, datatype = key[len(prefix):].partition("_")
            diffs.append({"layer": int(layer), "datatype": int(datatype),
                          "differences": value, "declared_by": "Vibeic.FinishingXOR"})
    count = defect.get("value")
    if count and not diffs:
        diffs = [{"layer": None, "datatype": None, "differences": count,
                  "declared_by": "Vibeic.FinishingXOR (no per-pair metric)"}]
    report = dict(base, design_layer_differences=diffs,
                  design__xor_difference__count=count,
                  layers_compared=state.get("vibeic__finishing_xor__design_pair__count"),
                  finishing_record_sha256=_sha256(project / rel))
    # Reuse the existing strict native receipt reader, including image/PDK,
    # execution, config, current State and material input bindings.
    try:
        import _physical_current as _pc
        import librelane_signoff_evidence as _native
        shipped, dfile, _att = shipped_and_source(project)
        config_root = project / f"phase3/librelane/37.3-{arm}-config"
        measured = _native.count_row(project, Path(folder), "Vibeic.FinishingXOR",
                                     "vibeic__finishing_xor__defect__count", shipped, config_root)
        if measured.get("value") != count or type(count) is not int:
            raise ValueError(measured.get("reason") or "XOR_LIBRELANE_COUNT_NOT_CURRENT")
        config = json.loads((config_root / "Vibeic.FinishingXOR.json").read_text())
        pre = Path(config["VIBEIC_FINISHING_PRE_GDS"])
        if not pre.is_file() or _sha256(pre) == live_sha256:
            raise ValueError("XOR_IDENTICAL_OR_MISSING_INPUTS")
        pdk_name, technology = _pc.pdk_of(project)
        report["current_native"] = {
            "step": "37.3", "stage": "stage4", "design": _pc.design_of(dfile),
            "pdk": pdk_name, "tool": "librelane:Vibeic.FinishingXOR",
            "shipped": _pc.entry(project, shipped), "reference": _pc.entry(project, pre),
            "def": _pc.entry(project, dfile), "technology": _pc.entry(project, technology),
            "receipt": _pc.entry(project, Path(folder) / "vibeic_receipt.json"),
            "state": _pc.entry(project, Path(folder) / "state_out.json"),
            "config": _pc.entry(project, config_root / "Vibeic.FinishingXOR.json")}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"verdict": "NOT_DETERMINED", "rc": 2, "report": report,
                "reason": f"XOR_LIBRELANE_CURRENT_REFUSED: {exc}"}
    if count == 0:
        return {"verdict": "PASS", "rc": 0, "report": report,
                "reason": f"step 37's LibreLane finishing XOR on the promoted "
                          f"{arm} stream: 0 design geometry removed, covered or "
                          f"touched ({rel})"}
    return {"verdict": "FAIL", "rc": 1, "report": report,
            "reason": f"step 37's LibreLane finishing XOR on the promoted {arm} "
                      f"stream counted {count} defect(s) ({rel})"}


def _stated_class(doc: Dict[str, Any],
                  default: str = _JUDGE_CAPABILITY_ABSENT) -> str:
    """The reason class the receipt STATES (normalised), else `default`."""
    try:
        import _flow_reason_taxonomy as _tax  # noqa: PLC0415
        stated = _tax.normalise(doc.get("reason_class"))
    except Exception:                                      # pragma: no cover
        stated = None
    return stated or default


def current_geometry_refusal(project: Path, doc: Dict[str, Any], *,
                             _validated_stream=None) -> str:
    """Re-read the existing geometric comparison without composing later LVS.

    Both Step37.3 and the downstream DEF-level LVS association use the same
    raw transcript, material/boundary and finishing-partition obligations.
    """
    diffs = doc.get("design_layer_differences")
    count = doc.get("design__xor_difference__count")
    layers = doc.get("layers_compared")
    # A zero is credit only for the current, separately produced subjects.
    import _physical_current as _pc
    current = doc.get("current")
    refusal = _pc.validate(project, current, step="37.3", stage="stage4",
                           tools=("klayout",),
                           required_inputs=("shipped", "reference", "def", "technology", "recipe"),
                           required_outputs=("log",), marker="XOR_DONE")
    if not refusal:
        shipped, dfile, _att = (shipped_and_source(project) if _validated_stream is None else
                              shipped_and_source(project, _validated_stream=_validated_stream))
        for role, path in (("shipped", shipped), ("def", dfile)):
            if path is None or _pc.entry(project, path) != current["inputs"][role]:
                refusal = "XOR_CURRENT_SUBJECT_SWAPPED"
        if current["inputs"]["shipped"]["sha256"] == current["inputs"]["reference"]["sha256"]:
            refusal = "XOR_IDENTICAL_INPUTS"
        text = (project / current["outputs"]["log"]["path"]).read_text()
        boundary = None
        try:
            boundary = (_default_stream_boundary(project, dfile, shipped)
                        if _validated_stream is None else
                        _default_stream_boundary(project, dfile, shipped,
                                                 _validated_stream=_validated_stream))
            if boundary is not None:
                if current['inputs'].get('boundary') != _pc.entry(project, boundary):
                    refusal = 'XOR_DEFAULT_BOUNDARY_CHANGED'
                faithful, why, _stats = reference_is_faithful(text, boundary=True)
                if not faithful:
                    refusal = 'XOR_REFERENCE_INCOMPLETE: ' + why
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            refusal = 'XOR_DEFAULT_BOUNDARY_REFUSED: ' + str(exc)
        counts, done = parse_layers(text)
        tops = re.findall(r"(?m)^XOR_TOP shipped=(\S+) reference=(\S+)$", text)
        if not done or not counts or tops != [(current["design"], current["design"])]:
            refusal = "XOR_NATIVE_SUBJECT_OR_EXECUTION_MISMATCH"
        if not re.search(r"(?m)^XOR_TOOL klayout(?:\s|$)", text):
            refusal = "XOR_NATIVE_TOOL_MISSING"
        try:
            fill, seal, provenance = (
                declared_finishing_layers(project) if _validated_stream is None else
                declared_finishing_layers(project, _validated_stream=_validated_stream))
            if boundary is not None and doc.get('declared_finishing_layers') != provenance:
                refusal = 'XOR_FINISHING_WRITE_SET_CHANGED'
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            return 'XOR_FINISHING_WRITE_SET_REFUSED: ' + str(exc)
        native_design, native_finishing, total = partition(counts, fill, seal)
        if (native_design != diffs or total != count or len(counts) != layers
                or native_finishing != doc.get("finishing_layer_differences")):
            refusal = "XOR_NATIVE_VALUES_CHANGED"
    return refusal


def judge_receipt(project: Path, rel: str) -> Tuple[int, str, Dict[str, Any]]:
    """Decide step 37.3 from the receipt the PRODUCER wrote. Returns (rc, line, doc).

    WHY A JUDGE AND NOT A SECOND MEASUREMENT, measured on the SLT53D S arm. The
    flow clause used to be `gds_xor_check . --json reports/phase3/gds_xor.json`,
    so the completion audit RE-RAN the comparison. On that arm the producer's
    receipt said PASS, rc 0, 0 design-layer differences across 46 layers, runner
    {"kind": "container", "detail": "real-ic-arm-eda:klayout"} -- and the audit's
    own invocation of the same program, seconds later on the same host, could not
    reach KLayout (the static clause carries no `--container`) and exited
    NOT_DETERMINED. The audit published the invocation that did not measure, and
    every one of the five subjects read FAIL.

    R-0915-126 already names the rule this broke: PRODUCER WRITES, GATE READS.
    The receipt redirect exists precisely so a gate clause can never overwrite a
    producer document -- and a clause that re-measures is the trap the redirect
    was built for, because the redirect protects the BYTES and says nothing about
    which of the two answers gets published.

    THE MAPPING, and every branch is one a reader can check against the receipt:
      * no receipt                  -> rc 2, ASKED_BEFORE_PRODUCER
      * unreadable / not this gate  -> rc 2, EXECUTION_ERROR-shaped, named
      * verdict NOT_DETERMINED      -> rc 2, carrying the receipt's OWN reason
      * design-layer differences    -> rc 1  (a measured defect, and the answer
                                       to dimension 2's question about this step)
      * zero differences            -> rc 0
    Nothing here opens a layout, launches a tool or writes a byte.
    """
    path = project / rel
    if not path.is_file():
        return 2, (
            f"NOT_MEASURED [{_JUDGE_ASKED_BEFORE_PRODUCER}]: {rel} does not "
            f"exist, so this step's own producer has not run yet; an absent "
            f"receipt is a question nobody asked, not a clean comparison"), {}
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        return 2, (
            f"NOT_MEASURED [EXECUTION_ERROR]: {rel} is not readable JSON "
            f"({type(exc).__name__}: {exc}), so it states nothing this step can "
            f"be judged on"), {}
    if not isinstance(doc, dict) or doc.get("gate") != GATE:
        return 2, (
            f"NOT_MEASURED [EXECUTION_ERROR]: {rel} is not a {GATE} receipt "
            f"(gate={doc.get('gate') if isinstance(doc, dict) else type(doc).__name__})"
        ), (doc if isinstance(doc, dict) else {})

    verdict = str(doc.get("verdict") or "")
    diffs = doc.get("design_layer_differences")
    count = doc.get("design__xor_difference__count")
    reason = str(doc.get("reason") or "no reason recorded")
    layers = doc.get("layers_compared")

    if verdict == "NOT_DETERMINED" or not isinstance(diffs, list):
        # THE RECEIPT'S OWN REASON, carried verbatim. The producer knows why it
        # could not measure; re-deriving that here is how two readers come to
        # disagree about one run.
        return 2, (
            f"NOT_MEASURED [{_stated_class(doc)}]: the run's own receipt "
            f"{rel} records verdict NOT_DETERMINED — {reason}"), doc
    if diffs or (isinstance(count, int) and count > 0):
        named = ", ".join(
            f"{d.get('layer')}/{d.get('datatype')}={d.get('differences')}"
            for d in diffs[:6] if isinstance(d, dict))
        return 1, (
            f"FAIL: the run's own receipt {rel} records {len(diffs)} DESIGN "
            f"layer(s) differing between the shipped GDS and this run's "
            f"pre-finishing reference ({count} differing polygon(s): {named})"), doc
    if (doc.get("reference") or {}).get("kind") == "librelane_stream":
        shipped, dfile, _att = shipped_and_source(project)
        if shipped is None or dfile is None:
            return 2, "NOT_MEASURED [EXECUTION_ERROR]: XOR_CURRENT_SUBJECT_MISSING", doc
        fresh = librelane_finishing_receipt(project, _sha256(shipped))
        if fresh is None or fresh["verdict"] != "PASS":
            return 2, "NOT_MEASURED [EXECUTION_ERROR]: XOR_LIBRELANE_NOT_CURRENT", doc
        for key in ("design_layer_differences", "design__xor_difference__count", "layers_compared", "current_native"):
            if doc.get(key) != fresh["report"].get(key) or fresh["report"].get(key) is None:
                return 2, "NOT_MEASURED [EXECUTION_ERROR]: XOR_LIBRELANE_RECORD_CHANGED", doc
        conn = gds_connectivity(project, _sha256(shipped))
        if conn.get("verdict") == "FAIL":
            return 1, (
                f"FAIL: current connectivity failed — {conn.get('reason') or 'measured connectivity failure'}"), doc
        if conn.get("verdict") != "PASS":
            return 2, (
                f"NOT_MEASURED [{_stated_class(conn, _CONNECTIVITY_UNMEASURED_CLASS)}]: "
                f"current connectivity unmeasured — {conn.get('reason') or 'no connectivity measurement recorded'}"), doc
        return 0, "PASS: current LibreLane finishing XOR and current connectivity", doc

    current = doc.get("current")
    refusal = current_geometry_refusal(project, doc)
    if refusal:
        return 2, f"NOT_MEASURED [EXECUTION_ERROR]: {refusal}", doc

    # U15 / R-0929-GDSXOR-SPLIT: `verdict` is the GEOMETRIC answer (0
    # design-layer differences). Step 37.3's composed status also needs the
    # shipped bytes' connectivity (`connectivity`), bound to the sha256 the
    # receipt compared.
    conn = doc.get("connectivity")
    live = doc.get("shipped_sha256_live")
    ref = doc.get("reference") if isinstance(doc.get("reference"), dict) else {}
    if not isinstance(conn, dict) or conn.get("verdict") not in ("PASS", "FAIL"):
        cls = _stated_class(conn if isinstance(conn, dict) else {},
                            _CONNECTIVITY_UNMEASURED_CLASS)
        why = (conn.get("reason") if isinstance(conn, dict) and conn.get("reason")
               else f"the receipt carries no connectivity measurement; its "
                    f"reference is the {ref.get('kind') or 'unstated'} "
                    f"pre-finishing stream, which proves finishing left the "
                    f"design layers alone and cannot see a stream-out that "
                    f"lost connectivity")
        return 2, (
            f"NOT_MEASURED [{cls}]: {rel} records 0 "
            f"design-layer difference(s) across {layers} layer(s) against the "
            f"pre-finishing reference, but {why}"), doc
    if (not isinstance(live, str) or not live
            or conn.get("subject_sha256") != live
            or conn.get("basis") not in CONNECTIVITY_BASES):
        return 2, (
            f"NOT_MEASURED [{_CONNECTIVITY_UNMEASURED_CLASS}]: {rel}'s "
            f"connectivity is not bound to the shipped GDS it compared "
            f"(subject {str(conn.get('subject_sha256'))[:16]}..., shipped "
            f"{str(live)[:16]}..., basis {conn.get('basis')!r})"), doc
    fresh_conn = gds_connectivity(project, live, doc)
    changed = (fresh_conn.get("verdict") != conn.get("verdict")
               or fresh_conn.get("basis") != conn.get("basis"))
    if current["inputs"].get("connectivity"):
        # Later DEF-level LVS can disclose a different reason it is not a
        # GDS extraction. That diagnostic is not a changed native measurement.
        changed = ({k: v for k, v in fresh_conn.items() if k != "not_measured_by"}
                   != {k: v for k, v in conn.items() if k != "not_measured_by"})
    if changed:
        return 2, "NOT_MEASURED [EXECUTION_ERROR]: XOR_CONNECTIVITY_EVIDENCE_CHANGED", doc
    if conn["verdict"] == "FAIL":
        return 1, (
            f"FAIL: {rel} records the shipped GDS's connectivity FAILED under "
            f"{conn.get('basis')}"), doc
    return 0, (
        f"PASS: the run's own receipt {rel} records 0 design-layer difference(s) "
        f"across {layers} layer(s) compared and the shipped GDS's connectivity "
        f"measured by {conn.get('basis')} — {reason}"), doc


# ── The IC front door: the delivered GDS against the signoff GDS (#88 D3) ────
#
# On the Flow109 IC front door no selected row runs step 37.3: the IC profile of
# D64 is the native final-geometry adapter, which refuses IC seal re-entry and
# writes no REPORT_REL. D77 (`signoff_metrics_aggregate._xor`) still reads it,
# so before this producer the IC path could never measure that key. Ruling #88
# D3 names the measurement: KLayout's own XOR, with the deck LibreLane's
# KLayout.XOR step runs, of the DELIVERED GDS (the final post-fill stream this
# carrier ships) against the SIGNOFF GDS (the stream step 31 is admitted to sign
# off) of the same carrier. No layer is exempt here, so a difference on any
# layer is a FAIL; an unrun or unreadable comparison is NOT_MEASURED.

#: LibreLane's own resolver for the deck it ships, asked in the runner's
#: environment, so the script is the image's and never a copy of it.
NATIVE_XOR_SCRIPT_PROBE = ("import os; from librelane.common import get_script_dir; "
                           "print(os.path.join(get_script_dir(), 'klayout', 'xor.drc'))")
NATIVE_XOR_RDB_REL = "reports/phase3/gds_xor.xml"
NATIVE_XOR_LOG_REL = "reports/phase3/gds_xor.log"
NATIVE_XOR_THREADS = 2
_NATIVE_METRIC_RE = re.compile(r"^%OL_METRIC_I (\S+) (\d+)\s*$", re.M)
_RDB_LAYER_RE = re.compile(r"^(\d+)/(\d+)$")


def ic_front_door_owns_xor() -> bool:
    """True on a Flow109 IC launch whose validated plan selects no 37.3 row."""
    import os
    import flow109
    raw = os.environ.get(flow109.CONTEXT_ENV)
    if not raw:
        return False
    context = flow109.validate_execution_context(json.loads(Path(raw).read_text()))
    if context["features"].get("ic") is not True:
        return False
    plan = flow109.resolve_plan(context["features"], context["step_profiles"])
    return not any(str((row["profile"].get("dispatch") or {}).get("native_step_id")) == "37.3"
                   for row in plan["rows"])


def delivered_gds(project: Path) -> Path:
    """The stream this carrier ships, bound by `shipped_and_source`."""
    gds, _source_def, binding = shipped_and_source(project)
    if gds is None or not gds.is_file():
        raise ValueError("XOR_DELIVERED_GDS_UNBOUND: "
                         + json.dumps(binding, sort_keys=True, default=str)[:300])
    if (binding.get("binding") == "flow-canonical"
            and len(list(project.glob(CANONICAL_GDS_GLOB))) != 1):
        raise ValueError(f"XOR_DELIVERED_GDS_AMBIGUOUS: {CANONICAL_GDS_GLOB} names "
                         f"more than one stream and no record selects one")
    recorded = binding.get("gds_sha256_recorded")
    if isinstance(recorded, str) and recorded and recorded != _sha256(gds):
        raise ValueError(f"XOR_DELIVERED_GDS_CHANGED: {gds.name} is not the "
                         f"stream {binding.get('source')} records")
    return gds.resolve()


def signoff_gds(project: Path) -> Path:
    """The stream step 31 is admitted to sign off.

    Step 31 refuses any routed GDS `_gds_admission.admitted_gds` does not admit
    (`execution_backend_producers.produce_signoff`), so the admission record
    names the signoff GDS; `admitted_gds` re-proves it is still current.
    """
    import _gds_admission as admission
    record = json.loads(admission.admission_path(project).read_text())
    rel = record.get("gds_relpath") if isinstance(record, dict) else None
    gds = project / str(rel or "")
    if not rel or not gds.is_file() or not admission.admitted_gds(project, gds):
        raise ValueError(f"XOR_SIGNOFF_GDS_NOT_ADMITTED: {rel!r} is not the "
                         f"current admitted stream")
    return gds.resolve()


def _single_top(gds: Path) -> str:
    import gds_topcell_name_check as topcell
    defined, referenced, valid = topcell.parse_structures(gds.read_bytes())
    tops = sorted(set(defined) - referenced)
    if not valid or len(tops) != 1:
        raise ValueError(f"XOR_TOP_CELL_UNDETERMINED: {gds.name} tops {tops[:4]}")
    return tops[0]


def rdb_layer_counts(path: Path) -> Dict[Tuple[int, int], int]:
    """{(layer, datatype): differing polygons} from the native report database.

    xor.drc declares one top-level category per compared layer and writes one
    item per differing polygon, naming its category quoted (`'68/20'`).
    """
    import xml.etree.ElementTree as ET
    declared: List[str] = []
    items: Dict[str, int] = {}
    stack: List[str] = []
    for event, elem in ET.iterparse(str(path), events=("start", "end")):
        if event == "start":
            stack.append(elem.tag)
            continue
        stack.pop()
        if elem.tag == "name" and stack == ["report-database", "categories", "category"]:
            declared.append((elem.text or "").strip())
        elif elem.tag == "category" and stack == ["report-database", "items", "item"]:
            name = (elem.text or "").strip()
            if len(name) >= 2 and name[0] == name[-1] == "'":
                name = name[1:-1]
            items[name] = items.get(name, 0) + 1
        elif elem.tag == "item":
            elem.clear()
    if set(items) - set(declared):
        raise ValueError(f"XOR_REPORT_UNDECLARED_CATEGORY: {sorted(set(items) - set(declared))[:4]}")
    counts: Dict[Tuple[int, int], int] = {}
    for name in declared:
        m = _RDB_LAYER_RE.match(name)
        if not m:
            raise ValueError(f"XOR_REPORT_CATEGORY_NOT_A_LAYER: {name!r}")
        counts[(int(m.group(1)), int(m.group(2)))] = items.get(name, 0)
    return counts


def native_delivered_xor(project: Path, *, container: Optional[str] = None,
                         runner=None, out: Optional[Path] = None,
                         timeout: int = 24 * 3600) -> Dict[str, Any]:
    """Run LibreLane's xor.drc on the delivered and signoff GDS; write REPORT_REL.

    Total 0 -> PASS (rc 0), total > 0 -> FAIL (rc 1), anything unrun,
    unbound or unreadable -> NOT_MEASURED (rc 2). The total is the deck's own
    `design__xor_difference__count`; the per-layer counts are its report
    database, and the two must agree.
    """
    project = Path(project).resolve()
    out = Path(out) if out is not None else project / REPORT_REL
    report: Dict[str, Any] = {
        "gate": GATE, "producer": "gds_xor_check.native_delivered_xor",
        "basis": "ruling #88 D3: KLayout XOR of the delivered GDS against the "
                 "signoff GDS of the same carrier",
        "project": str(project), "verdict": "NOT_MEASURED", "rc": 2,
        "reference": {"kind": "signoff_gds"}}

    def finish(verdict: str, rc: int, reason: str) -> Dict[str, Any]:
        report.update(verdict=verdict, rc=rc, reason=reason)
        out.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(out, report)
        return report

    try:
        delivered = delivered_gds(project)
        signoff = signoff_gds(project)
        report["delivered"] = {"path": str(delivered.relative_to(project)),
                               "sha256": _sha256(delivered)}
        report["reference"].update(path=str(signoff.relative_to(project)),
                                   sha256=_sha256(signoff),
                                   source="reports/phase3/gds_admission.json")
        top = _single_top(delivered)
        if _single_top(signoff) != top:
            raise ValueError("XOR_TOP_CELL_MISMATCH: the delivered and signoff GDS "
                             "have different top cells")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return finish("NOT_MEASURED", 2, str(exc))
    report["top_cell"] = top

    if runner is None:
        import _klayout_launch as kl
        runner = kl.find_runner(container, project=project)
    if runner is None or not all(runner.covers(p) for p in
                                 (delivered, signoff, project / NATIVE_XOR_RDB_REL)):
        return finish("NOT_MEASURED", 2, "XOR_TOOL_ABSENT: no KLayout runner reaches "
                                         "this project; an unrun XOR is not a zero")
    report["runner"] = {"kind": runner.kind, "detail": runner.detail}
    try:
        return finish(*_run_native_xor(project, report, runner, delivered, signoff,
                                       top, timeout))
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        return finish("NOT_MEASURED", 2, f"XOR_NATIVE_FAILED: {type(exc).__name__}: {exc}")


def _run_native_xor(project, report, runner, delivered, signoff, top, timeout):
    """(verdict, rc, reason) of one native run; its counts go into `report`."""
    rc, so, se = runner.run_argv(["python3", "-c", NATIVE_XOR_SCRIPT_PROBE], {}, timeout=300)
    script = (so or "").strip().splitlines()[-1].strip() if rc == 0 and (so or "").strip() else ""
    if not script.endswith("/klayout/xor.drc"):
        return ("NOT_MEASURED", 2,
                f"XOR_NATIVE_SCRIPT_ABSENT: LibreLane's klayout/xor.drc is not "
                f"resolvable in the runner (rc={rc}): {(se or so or '').strip()[-200:]}")
    rdb, log = project / NATIVE_XOR_RDB_REL, project / NATIVE_XOR_LOG_REL
    rdb.parent.mkdir(parents=True, exist_ok=True)
    rdb.unlink(missing_ok=True)
    argv = [runner.klayout_bin(), "-b", "-r", script,
            "-rd", f"top_cell={top}", "-rd", f"a={runner.cpath(delivered)}",
            "-rd", f"b={runner.cpath(signoff)}", "-rd", f"jobs={NATIVE_XOR_THREADS}",
            "-rd", f"rdb_out={runner.cpath(rdb)}", "-rd", "ignore=", "-rd", "tilesize="]
    rc, so, se = runner.run_argv(argv, {}, timeout=timeout)
    _atomic_write_text(log, (so or "") + "\n" + (se or ""))
    report["native"] = {"tool": "klayout", "script": script, "argv": argv, "rc": rc,
                        "report": NATIVE_XOR_RDB_REL, "log": NATIVE_XOR_LOG_REL}
    metrics = {key: int(value) for key, value in _NATIVE_METRIC_RE.findall(so or "")}
    total = metrics.get("design__xor_difference__count")
    if rc != 0 or total is None or not rdb.is_file():
        return ("NOT_MEASURED", 2,
                f"XOR_NATIVE_FAILED: rc={rc}, total metric "
                f"{'present' if total is not None else 'absent'}, report "
                f"{'present' if rdb.is_file() else 'absent'}: "
                f"{(se or so or '').strip()[-200:]}")
    shapes = [metrics.get(f"design__xor__shape__count__layout:{side}") for side in "ab"]
    report["census"] = {"delivered_shapes": shapes[0], "signoff_shapes": shapes[1]}
    if not all(isinstance(n, int) and n > 0 for n in shapes):
        return ("NOT_MEASURED", 2, "XOR_VACUOUS: a compared layout carries no shape "
                                   "under its top cell")
    counts = rdb_layer_counts(rdb)
    if not counts or sum(counts.values()) != total:
        return ("NOT_MEASURED", 2,
                f"XOR_NATIVE_COUNTS_DISAGREE: the report database lists "
                f"{sum(counts.values())} difference(s) on {len(counts)} layer(s); "
                f"the deck's metric says {total}")
    rows = [{"layer": layer, "datatype": datatype, "differences": n}
            for (layer, datatype), n in sorted(counts.items())]
    differing = [row for row in rows if row["differences"]]
    report.update(layers_compared=len(rows), layer_differences=rows,
                  design_layer_differences=differing, finishing_layer_differences=[],
                  design__xor_difference__count=total)
    if total:
        named = ", ".join(f"{r['layer']}/{r['datatype']}={r['differences']}"
                          for r in differing[:6])
        return ("FAIL", 1, f"the delivered GDS differs from the signoff GDS on "
                           f"{len(differing)} layer(s) ({total} differing polygon(s): {named})")
    return ("PASS", 0, f"0 differences between the delivered GDS and the signoff GDS "
                       f"across {len(rows)} layer(s) compared")


def ic_front_door_xor(project: Path) -> Optional[Dict[str, Any]]:
    """D77's XOR receipt on the IC front door; None on every other route."""
    try:
        owned = ic_front_door_owns_xor()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[{GATE}] IC front door not established, XOR not produced: {exc}",
              file=sys.stderr)
        return None
    return native_delivered_xor(project) if owned else None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None,
                    help=f"where to write the report (default {REPORT_REL})")
    ap.add_argument("--container", default=None)
    ap.add_argument("--check", metavar="RECEIPT", default=None,
                    help="JUDGE the receipt at RECEIPT (project-relative) "
                         "instead of performing the comparison: 0 design-layer "
                         "differences -> 0, a measured difference -> 1, a "
                         "NOT_DETERMINED or absent receipt -> 2. Reads only; "
                         "this is the form the flow's gate clause uses, so the "
                         "audit judges the producer's measurement rather than "
                         "re-running it with a resolver that may reach no tool.")
    ap.add_argument("--timeout", type=int, default=0,
                    help="0 (the default) means NO deadline: a 100 MB XOR is "
                         "working, not wedged, and the watchdog supervises "
                         "progress instead")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{GATE}] project dir not found: {project}", file=sys.stderr)
        return 1

    if args.check:
        rc, line, _doc = judge_receipt(project, args.check)
        # THE CLASSIFIED LINE FIRST, AT COLUMN 0, AND THAT IS NOT COSMETIC.
        # Every reader of a gate's non-verdict in this flow takes the FIRST line
        # of stdout -- `_p0_skip_reason_from_output` does, and so does the output
        # snippet the step row carries. Printing a decorative `=== gate ===`
        # banner first hands all of them the banner: MEASURED on a run21 copy,
        # the row read "gate program signalled VACUOUS_PASS (input not
        # applicable)" and the receipt's own reason ("no KLayout runner reaches
        # this project") reached nobody. The banner still prints, second, for a
        # human reading a terminal.
        print(line)
        print(f"=== {GATE} --check ({project.name}) ===")
        # step_metrics_adoption_check: step 37.3 declares this program, so the
        # verdict it just judged is emitted through the one metrics schema,
        # attributed to the clause that ran it (`--check <receipt>`). The
        # receipt IS the verdict document. Best-effort: cannot change rc.
        import step_metrics  # noqa: PLC0415
        step_metrics.emit_gate_outcome(
            "gds_xor_check", list(argv if argv is not None else sys.argv[1:]),
            rc, report=args.check)
        return rc
    out = Path(args.json) if args.json else (project / REPORT_REL)
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()

    # rc 2 FOR NOT_DETERMINED -- the not-checked convention every other gate in
    # this flow uses -- and rc 1 ONLY for a measured design-layer difference.
    #
    # THIS WAS rc 1 FOR BOTH, AND THE COST WAS MEASURED. An earlier draft exited 2
    # on a refusal, dimension 2 caught that ("step 37.3 gate CANNOT FAIL on
    # anything a project DID"), and the over-correction was to make every refusal
    # exit 1 -- which made "the tool was not reachable" indistinguishable from
    # "the design's geometry changed". On the SLT53D S arm that published a FAIL
    # over a PASS: the producer measured 0 differences across 46 layers and the
    # audit's own re-invocation, which could not reach KLayout, exited 1 and the
    # row read FAIL on all five subjects.
    #
    # The two questions are now separated where they belong. A REFUSAL is rc 2,
    # which the audit maps to a typed non-verdict, never a defect -- an unrun XOR
    # is not a zero and it is not a difference either. A MEASURED DIFFERENCE is
    # rc 1 and blocks. And dimension 2's question is answered by `--check`, the
    # judge the flow clause now names: hand it a receipt with one design-layer
    # difference and it exits 1 on a project that DID something.
    report: Dict[str, Any] = {"gate": GATE, "project": str(project),
                              "verdict": "NOT_DETERMINED", "rc": 2}
    shipped, dfile, att = shipped_and_source(project)
    report["attestation"] = att
    finishing_error = None
    try:
        fill_pairs, seal_pairs, prov = declared_finishing_layers(project)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        fill_pairs, seal_pairs, prov = set(), set(), {}
        finishing_error = str(exc)
    report["declared_finishing_layers"] = prov

    def finish(verdict: str, rc: int, reason: str) -> int:
        report.update(verdict=verdict, rc=rc, reason=reason)
        # THE CLASS, STATED BY THE GATE THAT KNOWS IT. `_flow_reason_taxonomy
        # .report_reason_class` reads this field and `_p0_declared_reason_class`
        # prefers it over every prose recogniser -- "branch-owned evidence
        # outranks prose". Without it a refusal is typed by pattern-matching the
        # sentence, which is how "the tool was unreachable" and "this design has
        # no such thing" come to share a class.
        if verdict == "NOT_DETERMINED":
            report["reason_class"] = _JUDGE_CAPABILITY_ABSENT
        else:
            report.pop("reason_class", None)
        out.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(out, report)
        print(f"=== {GATE} ({project.name}) ===")
        print(f"  verdict: {verdict}  (rc={rc})")
        print(f"  {reason}")
        return rc

    if finishing_error is not None:
        return finish('NOT_DETERMINED', 2, 'XOR_FINISHING_WRITE_SET_REFUSED: ' + finishing_error)

    # NAME BOTH PLACES THAT WERE LOOKED IN. A refusal that cites only the
    # attestation sends a reader to a file that a design off the chip pad-ring
    # path never had, and they would read "missing attestation" where the truth is
    # "no shipped GDS anywhere".
    if shipped is None or not shipped.is_file():
        return finish("NOT_DETERMINED", 2,
                      f"no shipped GDS exists: neither {ROUTE_EVIDENCE_REL} nor "
                      f"{CANONICAL_GDS_GLOB} names one on disk, so there is "
                      f"nothing to compare; this is an absent input, not a clean "
                      f"XOR")
    if dfile is None or not dfile.is_file():
        return finish("NOT_DETERMINED", 2,
                      f"no routed DEF exists: neither {ROUTE_EVIDENCE_REL} nor "
                      f"{CANONICAL_DEF_REL} names one on disk, so no "
                      f"pre-finishing reference can be streamed")

    # IDENTITY FIRST. The attestation's sha256 is what makes this the pair the run
    # shipped; a GDS that changed since is a different subject and is refused
    # rather than silently compared.
    live = _sha256(shipped)
    report["shipped_sha256_live"] = live
    recorded = att.get("gds_sha256_recorded")
    if isinstance(recorded, str) and recorded and recorded != live:
        return finish("NOT_DETERMINED", 2,
                      f"the shipped GDS changed since the run attested it "
                      f"({ROUTE_EVIDENCE_REL} records {recorded[:16]}..., on disk "
                      f"{live[:16]}...), so this run's own pairing no longer holds")

    def finish_geometric(verdict: str, rc: int, reason: str) -> int:
        """R-0929-GDSXOR-SPLIT: `verdict` stays the GEOMETRIC answer; the
        shipped bytes' connectivity is its own field, which step 37.3's
        judge composes with it (`judge_receipt`)."""
        conn = gds_connectivity(project, live, report)
        report["connectivity"] = conn
        return finish(verdict, rc, f"{reason}; connectivity of the shipped "
                                   f"GDS: {conn['verdict']}"
                                   + (f" ({conn['basis']})" if conn.get("basis")
                                      else f" [{conn.get('reason_class')}]"))

    # STEP 37 ON LIBRELANE (lane mig105). When the shipped bytes are exactly
    # the stream LibreLane's step-37 chain promoted, the finishing comparison
    # was already MEASURED inside that chain, by `Vibeic.FinishingXOR` on the
    # promoted arm's own three streams (StreamOut, SealRing, Filler). The
    # receipt is written from that judged record -- one instrument, one
    # answer -- and nothing is re-streamed. Any other bytes fall through to
    # the direct comparison below.
    ll = librelane_finishing_receipt(project, live)
    if ll is not None:
        report.update(ll["report"])
        if ll["verdict"] not in ("PASS", "FAIL"):
            return finish(ll["verdict"], ll["rc"], ll["reason"])
        return finish_geometric(ll["verdict"], ll["rc"], ll["reason"])

    bounded = None
    try:
        import _native373_current as _bounded
        bounded = _bounded.produce(project, dfile)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        report["native_dependency_refusal"] = str(exc)

    try:
        boundary = _default_stream_boundary(project, dfile, shipped)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        return finish('NOT_DETERMINED', 2, 'XOR_DEFAULT_BOUNDARY_REFUSED: ' + str(exc))

    try:
        import _klayout_launch as _kl
    except ImportError as exc:                             # pragma: no cover
        return finish("NOT_DETERMINED", 2, f"KLayout launcher unavailable: {exc}")
    # THE ONE RESOLVER, project included: with no explicit --container the run's
    # own `reports/container_image.json` names the container it used, so this
    # invocation and the runner's resolve the same environment instead of falling
    # through to a conventional default that mounts a different tree.
    runner = (_bounded.ShippedXorRunner(project, bounded["image"]) if bounded is not None
              else _kl.find_runner(args.container, project=project))
    if runner is None or not runner.covers(shipped):
        return finish("NOT_DETERMINED", 2,
                      "no KLayout runner reaches this project, so the comparison "
                      "was not performed; an unrun XOR is not a zero")
    report["runner"] = {"kind": runner.kind, "detail": runner.detail}

    timeout = args.timeout if args.timeout > 0 else 24 * 3600
    kept, kind, prov = resolve_reference(project, dfile.stem, dfile)
    if bounded is not None:
        # The reference is a real stream of this current DEF, independently
        # compared against the other engine before the shipped comparison.
        import _physical_current as _pc
        streams = bounded["current"]["outputs"]
        chosen = next((streams[role] for role in ("magic_gds", "klayout_gds")
                       if streams[role]["sha256"] != live), None)
        if chosen is not None:
            kept = project / chosen["path"]
            kind = "native two-engine"
            prov = {"kind": "native_stream", "path": chosen["path"],
                    "sha256": chosen["sha256"], "dependency": _bounded.REL}
    report["reference"] = prov
    with tempfile.TemporaryDirectory(prefix="gds_xor_ref_",
                                     dir=str(project)) as scratch:
        if kept is not None:
            reference = kept
        else:
            reference = Path(scratch) / "pre_finishing.gds"
            rec_rel = STREAM_INPUTS_REL_FMT.format(stem=shipped.stem)
            rec, _why = _sir.read(project / rec_rel)
            report["reference"]["stream_inputs"] = (
                {"path": rec_rel, "engine": rec["engine"],
                 "inputs": len(_sir.all_entries(rec))} if rec else
                {"path": rec_rel, "absent": _why})
            rc, so, se = stream_reference(runner, Path(scratch), dfile,
                                          reference, timeout, stem=shipped.stem)
            if rc != 0 or not reference.is_file():
                return finish("NOT_DETERMINED", 2,
                              f"re-streaming the pre-finishing reference from "
                              f"{att.get('def')} failed (rc={rc}): "
                              f"{(se or so or '').strip()[:220]}")
            report["reference"]["streamed_from"] = att.get("def")
            # What the tool's own transcript says it resolved, beside the record
            # of what it was handed -- disclosure for a reader, not an input.
            _t_env, cited = restream_env_from_transcript(project)
            if cited:
                report["reference"]["stream_transcript"] = cited
        import _physical_current as _pc
        try:
            pdk_name, technology = _pc.pdk_of(project)
            if _pc.digest(shipped) == _pc.digest(reference):
                return finish("NOT_DETERMINED", 2, "XOR_IDENTICAL_INPUTS")
            if reference.parent == Path(scratch):
                retained = project / "reports/phase3/gds_xor_reference.gds"
                retained.write_bytes(reference.read_bytes())
                reference = retained
            inputs = {"shipped": _pc.entry(project, shipped),
                      "reference": _pc.entry(project, reference),
                      "def": _pc.entry(project, dfile),
                      "technology": _pc.entry(project, technology)}
            if boundary is not None:
                inputs['boundary'] = _pc.entry(project, boundary)
            if bounded is not None:
                inputs["connectivity"] = _pc.entry(project, project / _bounded.REL)
            design_name = _pc.design_of(dfile)
        except (OSError, ValueError) as exc:
            return finish("NOT_DETERMINED", 2, f"XOR_CURRENT_INPUT_REFUSED: {exc}")
        report["reference"]["bytes"] = reference.stat().st_size
        rc, so, se = run_xor(runner, Path(scratch), shipped, reference,
                             timeout, **({'boundary': boundary} if boundary is not None else {}))
        log_path = project / "reports/phase3/gds_xor_native.log"
        script_path = project / "reports/phase3/gds_xor_native.rb"
        log_path.write_text((so or "") + "\n" + (se or ""))
        script_path.write_text(_XOR_RB)
        inputs["recipe"] = _pc.entry(project, script_path)
        report["current"] = _pc.build(
            project, "37.3", "stage4", design_name, pdk_name, "klayout", inputs,
            {"log": _pc.entry(project, log_path)},
            getattr(runner, "execution", None) or
            {"rc": rc, "argv": ["klayout", "-b", "-r", str(script_path)],
             "runner": report["runner"]})
        counts, done = parse_layers(so)
        ok, why, stats = reference_is_faithful(so, boundary=boundary is not None)
        report["census"] = stats
        if done and not ok:
            return finish("NOT_DETERMINED", 2, f"refusing to compare: {why}")
        if rc != 0 or not done:
            return finish("NOT_DETERMINED", 2,
                          f"the XOR did not run to completion (rc={rc}, "
                          f"XOR_DONE={'yes' if done else 'no'}): "
                          f"{(se or so or '').strip()[:200]}")

    design, finishing, total = partition(counts, fill_pairs, seal_pairs)
    report["layers_compared"] = len(counts)
    report["design_layer_differences"] = design
    report["finishing_layer_differences"] = finishing
    report["design__xor_difference__count"] = total
    if total:
        named = ", ".join(f"{r['layer']}/{r['datatype']}={r['differences']}"
                          for r in design[:6])
        return finish("FAIL", 1,
                      f"the shipped GDS differs from the {kind} pre-finishing "
                      f"reference on {len(design)} DESIGN layer(s) "
                      f"({total} differing polygon(s): {named}) — finishing may add "
                      f"geometry on the layers it declares, and these are not "
                      f"those")
    return finish_geometric(
        "PASS", 0,
        f"the shipped GDS matches the {kind} pre-finishing reference "
        f"on every design layer (0 differences across "
        f"{len(counts)} layer(s) compared); "
        f"{len(finishing)} finishing-declared layer(s) differ as "
        f"expected and are listed separately")


if __name__ == "__main__":
    sys.exit(main())
