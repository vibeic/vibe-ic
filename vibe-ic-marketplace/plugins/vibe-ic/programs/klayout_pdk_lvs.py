#!/usr/bin/env python3
"""klayout_pdk_lvs — net-correct KLayout transistor-level layout extraction for LVS.

Chip- and PDK-AGNOSTIC: a `LayerMap` (GDS layer numbers + the standard CMOS device
recognition) drives KLayout's `LayoutToNetlist` to extract a transistor SPICE netlist
from a flattened GDS, robustly enough to LVS a commercial-PDK design against its gate
netlist (via netgen). Deterministic and multithreaded (no LLM in the compute loop).

Why this exists (proven on a commercial 180nm PDK whose LEF-abstract extraction
collapses magic's top-level nets while KLayout's geometric device extraction does not):
extracting the flat GDS to real transistors with an OSS-authored device deck reaches
~99.9% device-match vs the gate netlist — i.e. transistor-level LVS on a proprietary
PDK needs NO commercial tool.

The three hard-won correctness rules (all encoded below):
  1. WELL-AWARE recognition — NMOS S/D = N+ diffusion OUTSIDE nwell, PMOS S/D = P+
     diffusion INSIDE nwell (the same tap-vs-S/D discriminator a foundry LVS deck uses).
     The gate splits S/D by subtracting poly.
  2. MOS3 (no bulk) — do NOT put wells/taps in the connectivity graph; they bridge power
     rails through the shared substrate.
  3. Pin labels attach to METAL ONLY — a text on diffusion bridges S/D islands.
Power (a FOLLOWPIN-only grid is physically-disjoint rails that are one logical net):
`assign_power_by_geometry` renames every net whose m1 overlaps a VDD/VSS rail MARKER so
all rails collapse to one node — and REPORTS any net touching BOTH rails (a real short),
never silently merging it.

CLI:
  klayout_pdk_lvs.py extract <gds> --out layout.spice   # flat chip -> transistor SPICE
  klayout_pdk_lvs.py lib     <gds> --out cells.spice     # cell library -> per-cell SPICE
  klayout_pdk_lvs.py cell    <gds> --cell NAME           # single-cell diagnostic
Threads default to $KLVS_THREADS or the CPU count. `--layermap <json>` supplies the PDK's
own layer numbering (the real PDK map ships in the project's bridge config, NOT here).
Requires the KLayout Python module (`pya`); exits 3 (disclosed) if absent — never fakes.
"""
import sys, os, re, json, argparse
from _atomic_artefact import writing as atomic_writing  # vibe-ic#1082 (helper from PR #1094)

# A GENERIC example layer map (a common 180nm-style GDS numbering) so the tool is
# runnable/testable standalone. It is NOT any specific foundry's map — supply the real
# PDK layer numbering with `--layermap <json>` (the runner wires this from the project's
# bridge `lvs_layermap` config). Each value is [gds_layer, gds_datatype];
# `nactive`=N+ active/OD, `pactive`=P+ active/OD.
DEFAULT_LAYERMAP = {
    "poly": [3, 0], "nwell": [2, 0], "nactive": [1, 0], "pactive": [30, 0],
    "cont": [7, 0], "text": [100, 0],
    "metal": [[9, 0], [11, 0], [13, 0], [15, 0]],           # m1..m4 (bottom->top)
    "via":   [[10, 0], [12, 0], [14, 0]],                    # v1..v3 (between metals)
    "vdd_rail_marker": [901, 0], "vss_rail_marker": [902, 0],
}


def _default_threads():
    try:
        return int(os.environ.get("KLVS_THREADS") or (os.cpu_count() or 8))
    except Exception:
        return 8


def _require_pya():
    try:
        import pya  # noqa
        return pya
    except Exception:
        sys.stderr.write("klayout_pdk_lvs: KLayout Python module 'pya' not available "
                         "(run inside vibeic-eda). DISCLOSED, not faked.\n")
        sys.exit(3)


# ---------------------------------------------------------------- extraction core
def setup_extraction(l2n, ly, lm, pya):
    """Configure a LayoutToNetlist with the CMOS device recognition + connectivity."""
    def R(spec, name):
        # make_polygon_layer already REGISTERS the layer under `name`; naming each layer
        # at creation is what lets assign_power_by_geometry find m1 via layer_by_name("m1").
        # Never l2n.register() a make_polygon_layer product again -> "already registered".
        n, dt = spec
        li = ly.find_layer(n, dt)
        return l2n.make_polygon_layer(li if li is not None else ly.layer(n, dt), name)

    poly = R(lm["poly"], "poly"); nwell = R(lm["nwell"], "nwell")
    nactive = R(lm["nactive"], "nactive"); pactive = R(lm["pactive"], "pactive")
    cont = R(lm["cont"], "cont")
    metals = [R(m, f"m{i + 1}") for i, m in enumerate(lm["metal"])]
    vias = [R(v, f"v{i + 1}") for i, v in enumerate(lm["via"])]
    # v1.3.93 — PER-METAL port-label text sub-layers: a DEF pin's text is emitted
    # (by def_gds_port_power_restore) on text GDS layer lm["text"][0], datatype =
    # its 1-based metal index. Attaching each metal to ONLY its own text sub-layer
    # means a pin names the net on its OWN metal and never welds it to a foreign
    # higher-metal wire crossing over the pin point (the off-by-one net "short").
    tbase = lm["text"][0]
    metal_labels = []
    for i, m in enumerate(metals):
        ti = ly.find_layer(tbase, i + 1)
        tl = l2n.make_text_layer(ti if ti is not None else ly.layer(tbase, i + 1),
                                 f"text_m{i + 1}")
        metal_labels.append(tl)
    # datatype-0 catch-all: a label with no resolved metal layer -> m1 (legacy).
    ti0 = ly.find_layer(tbase, lm["text"][1])
    labels_catchall = l2n.make_text_layer(
        ti0 if ti0 is not None else ly.layer(tbase, lm["text"][1]), "text_c")
    m1 = metals[0]

    # 1. WELL-AWARE device regions; gate splits S/D by subtracting poly. Only these
    # boolean-derived layers are register()ed (they are fresh, unregistered products).
    nmos_diff = nactive - nwell
    pmos_diff = pactive & nwell
    ngate = poly & nmos_diff
    pgate = poly & pmos_diff
    nsd = nmos_diff - poly
    psd = pmos_diff - poly
    for r, nm in ((ngate, "ngate"), (pgate, "pgate"), (nsd, "nsd"), (psd, "psd")):
        l2n.register(r, nm)

    nmos = pya.DeviceExtractorMOS3Transistor("nmos")
    pmos = pya.DeviceExtractorMOS3Transistor("pmos")
    l2n.extract_devices(nmos, {"SD": nsd, "G": ngate, "tS": nsd, "tD": nsd, "tG": poly})
    l2n.extract_devices(pmos, {"SD": psd, "G": pgate, "tS": psd, "tD": psd, "tG": poly})

    # 2. MOS3 connectivity: signal + power only (no wells/taps).
    for r in [nsd, psd, poly] + metals:
        l2n.connect(r)
    for diff in (nsd, psd, poly):
        l2n.connect(cont, diff)
    l2n.connect(cont, m1)
    for i, v in enumerate(vias):
        l2n.connect(v, metals[i]); l2n.connect(v, metals[i + 1])
    # 3. labels -> ONLY the pin's own metal (layer-aware; no cross-metal weld)
    for m, tl in zip(metals, metal_labels):
        l2n.connect(m, tl)
    l2n.connect(metals[0], labels_catchall)


def finalize(l2n):
    l2n.extract_netlist()
    nl = l2n.netlist()
    nl.combine_devices()
    nl.purge()
    for ckt in nl.each_circuit():
        made = set()
        for p in ckt.each_pin():
            nf = ckt.net_for_pin(p.id())
            if nf and nf.name:
                made.add(nf.name)
        for net in ckt.each_net():
            nm = net.name
            if nm and nm.strip() and nm not in made:
                ckt.connect_pin(ckt.create_pin(nm), net)
                made.add(nm)
    return nl


def assign_power_by_geometry(l2n, ly, top, lm, pya):
    """Name power nets by geometry: a net whose m1 overlaps a VDD/VSS rail marker IS that
    rail (all rails collapse to one node). A net overlapping BOTH markers is a real
    VDD<->VSS short (must be 0 for a clean design) — it is NEVER silently merged.

    Returns (shorts, locations): `shorts` = the count (or -1 if the markers are absent);
    `locations` = a list of per-short dicts {net, vdd_at:[x,y]um, vss_at:[x,y]um} that
    LOCALIZE the offending net so the short is actionable upstream (a bare count only
    says "not clean" — a coordinate says WHERE to look in the router/GDS)."""
    vddi = ly.find_layer(*lm["vdd_rail_marker"]); vssi = ly.find_layer(*lm["vss_rail_marker"])
    if vddi is None or vssi is None:
        return -1, []
    tc = ly.top_cell()
    dbu = ly.dbu
    vdd_box = pya.Region(tc.begin_shapes_rec(vddi))
    vss_box = pya.Region(tc.begin_shapes_rec(vssi))
    m1_layer = l2n.layer_by_name("m1")
    shorts = 0
    locations = []

    def _rep(region):
        # a representative (x, y) in µm at the center of the overlap's bbox
        b = region.bbox()
        return [round((b.left + b.right) / 2.0 * dbu, 3),
                round((b.bottom + b.top) / 2.0 * dbu, 3)]

    for net in top.each_net():
        sh = l2n.shapes_of_net(net, m1_layer, True)
        if not sh or sh.size() == 0:
            continue
        r = pya.Region()
        for s in sh.each():
            r.insert(s)
        ov = r & vdd_box
        os_ = r & vss_box
        on_v = not ov.is_empty()
        on_s = not os_.is_empty()
        if on_v and on_s:
            shorts += 1
            locations.append({"net": net.name or f"n{net.expanded_name()}",
                              "vdd_at": _rep(ov), "vss_at": _rep(os_)})
        elif on_v:
            net.name = "VDD"
        elif on_s:
            net.name = "VSS"
    return shorts, locations


# ---------------------------------------------------------------- named SPICE writer
def _net_name(net, counter):
    if net is None:
        counter[0] += 1
        return f"UNCONN_{counter[0]}"
    nm = net.name
    if nm and nm.strip():
        return nm.strip().replace("[", ".").replace("]", "").replace(",", "_").replace(" ", "")
    return f"n{net.expanded_name()}".replace(":", "_")


def _has_param(dc, name):
    try:
        return any(pd.name == name for pd in dc.parameter_definitions())
    except Exception:
        return False


def write_named_spice(nl, path):
    """Emit named-pin SPICE (netgen maps a Verilog instance's .A/.B/.Y onto the subckt).

    Emits `.GLOBAL VDD VSS` so netgen treats the power rails as global nets (the
    geometric power assignment already collapsed every FOLLOWPIN rail to one
    VDD/one VSS node); the file is then netgen-ready with no post-processing."""
    counter = [0]
    lines = ["* klayout_pdk_lvs extraction (named-pin SPICE for netgen LVS)",
             ".GLOBAL VDD VSS", ""]
    for ckt in nl.each_circuit():
        pins = [_net_name(ckt.net_for_pin(p.id()), counter) for p in ckt.each_pin()]
        lines.append(f".SUBCKT {ckt.name} {' '.join(pins)}")
        for d in ckt.each_device():
            dc = d.device_class()
            t = {td.name: d.net_for_terminal(td.id()) for td in dc.terminal_definitions()}
            S = _net_name(t.get("S"), counter); G = _net_name(t.get("G"), counter)
            D = _net_name(t.get("D"), counter)
            B = _net_name(t.get("B"), counter) if "B" in t else S
            L = d.parameter("L") if _has_param(dc, "L") else 0.0
            W = d.parameter("W") if _has_param(dc, "W") else 0.0
            lines.append(f"M{d.expanded_name()} {D} {G} {S} {B} {dc.name} L={L:.4g}U W={W:.4g}U")
        for sc in ckt.each_subcircuit():
            child = sc.circuit_ref()
            nets = [_net_name(sc.net_for_pin(p.id()), counter) for p in child.each_pin()]
            lines.append(f"X{sc.expanded_name()} {' '.join(nets)} {child.name}")
        lines.append(".ENDS")
        lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


# ---------------------------------------------------------------- commands
def _counts(circuit):
    from collections import Counter
    c = Counter(d.device_class().name for d in circuit.each_device())
    return dict(c), sum(1 for _ in circuit.each_net())


def _load_lm(path):
    if not path:
        return DEFAULT_LAYERMAP
    with open(path) as f:
        return json.load(f)


_METAL_RE = re.compile(r"^(?:MET|METAL|M)(\d+)$", re.IGNORECASE)
_VIA_RE = re.compile(r"^(?:VIA|V)(\d+)$", re.IGNORECASE)


def _metal_via_from_pdk_map(path):
    """Parse an Encounter/SoC LEF->GDS layermap (`<NAME> <PURPOSE> <gdsL> <gdsDT>`
    rows) into ORDERED metal + via `[gds, dt]` lists (m1..mN, v1..vN).

    A commercial PDK's routing stack often has MORE metal layers than
    DEFAULT_LAYERMAP's generic 4-metal/3-via example. Extracting with too few
    metal layers leaves upper-metal wires out of the connectivity graph, so any
    net that routes through an uncovered layer SPLITS into disconnected pieces ->
    a spurious extra net -> a FALSE LVS mismatch (a commercial PDK: exactly one
    6-metal net split, taking spm from MISMATCH to MATCH once M5/M6 were covered).

    Picks each layer's ROUTING geometry: purpose NET/DRAWING if present, else the
    datatype-0 row, else the first row. chip-AGNOSTIC (name-pattern only; the GDS
    numbers are read from the file at runtime, nothing hardcoded)."""
    metals, vias = {}, {}
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                s = line.strip()
                if not s or s[0] in "#/*;":
                    continue
                t = s.split()
                if (len(t) < 4 or not t[2].lstrip("-").isdigit()
                        or not t[3].lstrip("-").isdigit()):
                    continue
                name, purpose, g, d = t[0], t[1].upper(), int(t[2]), int(t[3])
                mm = _METAL_RE.match(name)
                vv = _VIA_RE.match(name)
                if mm:
                    metals.setdefault(int(mm.group(1)), []).append((purpose, g, d))
                elif vv:
                    vias.setdefault(int(vv.group(1)), []).append((purpose, g, d))
    except OSError:
        return [], []

    def _pick(rows):
        for want in ("NET", "DRAWING", "DRW"):
            for (p, g, d) in rows:
                if p == want:
                    return [g, d]
        for (p, g, d) in rows:
            if d == 0:
                return [g, d]
        return [rows[0][1], rows[0][2]]

    return ([_pick(metals[i]) for i in sorted(metals)],
            [_pick(vias[i]) for i in sorted(vias)])


def _resolve_layermap(layermap_path, pdk_map_path=None):
    """Return (layermap, note). Start from the supplied `--layermap` JSON (or the
    generic DEFAULT), then EXTEND the metal/via lists to the PDK's full routing
    stack discovered from `--pdk-map` (the same Encounter/SoC map the streamout
    step already finds via _discover_lefdef_layermap). Only ever GROWS the
    metal/via coverage (never shrinks a supplied map); device/text/rail-marker
    layers are left untouched. `note` is a human-readable stderr line (or None)."""
    base = _load_lm(layermap_path)
    lm = dict(base)
    note = None
    base_m = len(lm.get("metal", []) or [])
    base_v = len(lm.get("via", []) or [])
    if pdk_map_path and os.path.exists(pdk_map_path):
        pm, pv = _metal_via_from_pdk_map(pdk_map_path)
        if len(pm) > base_m or len(pv) > base_v:
            if len(pm) > base_m:
                lm["metal"] = pm
            if len(pv) > base_v:
                lm["via"] = pv
            note = ("[lvs] auto-extended metal/via coverage "
                    f"{base_m}m/{base_v}v -> {len(lm['metal'])}m/{len(lm['via'])}v "
                    f"from PDK map {os.path.basename(pdk_map_path)} (a short metal "
                    "stack SPLITS upper-metal nets -> false MISMATCH)")
    elif layermap_path is None:
        # No explicit map AND no PDK map to auto-derive from: the generic 4-metal
        # DEFAULT is in use. WARN — a >4-metal PDK will false-MISMATCH.
        note = (f"[lvs][WARN] using the GENERIC {base_m}-metal/{base_v}-via default "
                "layermap (no lvs_layermap, no discoverable PDK layermap). On a PDK "
                "with more metal layers, nets routed on the uncovered layers SPLIT "
                "-> a FALSE LVS mismatch. Supply the PDK's layermap or make its "
                "Encounter/SoC map discoverable.")
    return lm, note


def cmd_extract(args, pya):
    lm, _note = _resolve_layermap(args.layermap, getattr(args, "pdk_map", None))
    if _note:
        print(_note, file=sys.stderr)
    ly = pya.Layout(); ly.read(args.gds)
    l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, ly.top_cell(), []))
    l2n.threads = args.threads
    setup_extraction(l2n, ly, lm, pya)
    nl = finalize(l2n)
    top = nl.top_circuit()
    if top is None:
        # NO CIRCUIT MEANS THE LAYER MAP DID NOT FIT THE LAYOUT, and saying so
        # is the whole value here. DEFAULT_LAYERMAP is an EXAMPLE numbering; on
        # a PDK numbered differently, device recognition matches nothing, the
        # netlist has no circuit at all, and the next line used to raise
        # `'NoneType' object has no attribute 'each_device'` deep inside the
        # container. That reached the caller as a bare non-zero rc, so an
        # entire LVS arm read as "the tool has not run" with no hint that the
        # cause was a layer map nobody had supplied. Measured on an open PDK
        # whose own sign-off runset compares the same block cleanly.
        print("EXTRACT %s: NO CIRCUIT — the layer map recognized no device. "
              "Supply the PDK's own numbering with --layermap/--pdk-map; the "
              "built-in map is an example, not a default for every PDK."
              % args.gds, file=sys.stderr)
        return 3
    shorts, short_locs = assign_power_by_geometry(l2n, ly, top, lm, pya)
    cc, nnet = _counts(top)
    print(f"EXTRACT {args.gds}: devices={cc} nets={nnet} power_shorts={shorts}")
    if short_locs:
        # localize each VDD<->VSS short so it is actionable upstream (not just a count)
        print("power_short_locations=" + json.dumps(short_locs))
        for loc in short_locs:
            print(f"  SHORT net={loc['net']} VDD@{loc['vdd_at']}um VSS@{loc['vss_at']}um")
    if args.out:
        write_named_spice(nl, args.out)
        print("wrote", args.out)
    return 0 if shorts in (0, -1) else 4     # nonzero shorts -> nonzero exit (honest)


def cmd_lib(args, pya):
    lm, _note = _resolve_layermap(args.layermap, getattr(args, "pdk_map", None))
    if _note:
        print(_note, file=sys.stderr)
    ly = pya.Layout(); ly.read(args.gds)
    l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, ly.top_cells()[0], []))
    l2n.threads = args.threads
    setup_extraction(l2n, ly, lm, pya)
    nl = finalize(l2n)
    n = sum(1 for _ in nl.each_circuit())
    print(f"LIB {args.gds}: {n} circuits -> {args.out}")
    if args.out:
        write_named_spice(nl, args.out)
    return 0


def cmd_cell(args, pya):
    lm, _note = _resolve_layermap(args.layermap, getattr(args, "pdk_map", None))
    if _note:
        print(_note, file=sys.stderr)
    ly = pya.Layout(); ly.read(args.gds)
    if args.cell not in [c.name for c in ly.each_cell()]:
        print("no such cell", args.cell); return 2
    l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, ly.cell(args.cell), []))
    l2n.threads = args.threads
    setup_extraction(l2n, ly, lm, pya)
    nl = finalize(l2n)
    c = nl.circuit_by_name(args.cell)
    if not c:
        print("no circuit extracted for", args.cell); return 3
    cc, _ = _counts(c)
    pins = [c.net_for_pin(p.id()).name if c.net_for_pin(p.id()) else '?' for p in c.each_pin()]
    shorted = sum(1 for d in c.each_device()
                  for tn in [{t.name: (d.net_for_terminal(t.id()).name
                              if d.net_for_terminal(t.id()) else None)
                              for t in d.device_class().terminal_definitions()}]
                  if tn.get('S') is not None and tn.get('S') == tn.get('D'))
    print(f"CELL {args.cell}: devices={cc} pins={pins} sd_shorts={shorted}")
    return 0


# ── v1.3.93 — in-KLayout netlist COMPARE (pin-matched LVS) ───────────────────
# netgen's partition matcher proves "device classes equivalent" but CANNOT
# pin-match a design with a topologically-symmetric port bus (e.g. the 32-bit
# carry-save `spm` multiplier: the interior x[] bits sit in one automorphism
# orbit its refinement never breaks, and netgen does not use net-name hints).
# KLayout's `NetlistComparer` DOES use net/pin-name hints + backtracking, so it
# resolves the bus — GIVEN four deterministic, chip-AGNOSTIC prep steps proven
# on the real commercial-PDK spm sign-off (MATCH in 0.22s; corrupt-one-device →
# MISMATCH confirms it keeps full discriminating power — NO false-clean):
#   1. BULK NORMALIZATION (the unlock): both the geometric layout extraction and
#      the gate→SPICE source tie each MOS body (4th terminal) inconsistently
#      (sometimes to the local source node, sometimes to the rail), and the
#      split DIFFERS per side — so VDD/VSS carry different device populations and
#      the comparer can't even anchor the power seed. Reconnect every NMOS bulk
#      → ground and PMOS bulk → power (the physical truth: shared p-substrate /
#      n-well taps) BEFORE combine_devices. 1981→13 residual mismatches.
#   2. PORT-PIN restriction: the extractor exposes internal nets as top pins;
#      keep only the pins whose net is a REAL port (the SOURCE netlist's port
#      set) plus power/ground. Demoted nets stay as internal named-net hints.
#   3. POWER-ONLY device drop: a device whose EVERY terminal is on power/ground
#      is a decoupling/filler cap, NOT logic — a standard LVS cap waiver. Flat
#      extraction merges some into neighbours so the counts differ per side;
#      dropping them (all-power-terminal devices, both sides) equalises the
#      LOGIC device population. NEVER drops a device with a signal terminal, so
#      a real short (signal shorted to power) still surfaces as a device/net
#      mismatch — verified by the corrupt-device tests.
#   4. W/L TOLERANCE + drop AS/AD/PS/PD: geometric extraction yields tiny
#      finger-sum W jitter (≤0.01µm) on wide drive cells and zero parasitic
#      area/perimeter; an EqualDeviceParameters tolerance on L/W and disabling
#      the four parasitic params clears that non-defect residual.
# §4.05: reads only the two design netlists (layout + gate source), never any
# oracle/golden. Never call the resulting MATCH "silicon-proven".
_DEFAULT_PWR = "VDD"
_DEFAULT_GND = "VSS"


def _lvs_strip_strays(nl, top):
    """Drop stray TOP circuits (no parent) other than the design top — e.g. the
    cell-library wrapper circuit a `.include`d cells SPICE leaves behind."""
    changed = True
    while changed:
        changed = False
        for c in list(nl.each_circuit()):
            if c.name.lower() != top.lower() and not any(True for _ in c.each_parent()):
                nl.remove(c); changed = True


def _lvs_normalize_bulk(c, power, ground):
    gnet = c.net_by_name(ground); pnet = c.net_by_name(power)
    for d in c.each_device():
        nm = d.device_class().name.upper()
        bid = next((td.id() for td in d.device_class().terminal_definitions()
                    if td.name == "B"), None)
        if bid is None:
            continue
        tgt = gnet if "NMOS" in nm else pnet if "PMOS" in nm else None
        if tgt is not None:
            d.connect_terminal(bid, tgt)


def _lvs_drop_power_only(c, pwr_set):
    rm = [d for d in c.each_device()
          if {(d.net_for_terminal(td.id()).name if d.net_for_terminal(td.id()) else "?")
              for td in d.device_class().terminal_definitions()} <= pwr_set]
    for d in rm:
        c.remove_device(d)
    return len(rm)


def _inline_includes(path, _seen=None):
    """Return the SPICE text of `path` with every `.include` spliced INLINE
    (recursively), so a single reader parse links every `X<inst>` to the
    device-bearing `.subckt` it references.

    KLayout's `NetlistSpiceReader` (a) mangles absolute `.include` paths whose
    directory names contain a '-' — `/home/u/vibe-ic/.../cells.spice` is
    truncated to `/home/u//vibe` and fails to open — and (b) does NOT link a
    reference to a `.subckt` read in a SEPARATE `read()` call (the referenced
    cell comes back empty, its devices lost). Doing the include expansion here,
    then a single `read()` of the combined text, sidesteps both: it reproduces
    the tool's own inline-include semantics under paths we control. Relative
    include paths resolve against the including file's directory; cycles guard.
    """
    if _seen is None:
        _seen = set()
    ap = os.path.abspath(path)
    if ap in _seen:
        return ""  # already spliced — break include cycles
    _seen.add(ap)
    base = os.path.dirname(ap)
    out = []
    with open(path) as f:
        for line in f.read().splitlines():
            m = re.match(r"^\s*\.include\s+(\S+)", line, re.I)
            if m:
                p = m.group(1).strip().strip('"').strip("'")
                if not os.path.isabs(p):
                    p = os.path.join(base, p)
                out.append("* inlined: " + p)
                out.append(_inline_includes(p, _seen))
            else:
                out.append(line)
    return "\n".join(out)


def _read_spice(pya, path):
    """Read a SPICE netlist into a KLayout Netlist, resolving `.include`
    ourselves via `_inline_includes` + a single `read()`. Include-free files
    read unchanged (fast path)."""
    nl = pya.Netlist()
    rdr = pya.NetlistSpiceReader()
    with open(path) as f:
        has_inc = re.search(r"(?im)^\s*\.include\s+\S", f.read()) is not None
    if not has_inc:
        nl.read(path, rdr)
        return nl
    tmp = path + ".inlined.tmp"
    with open(tmp, "w") as f:
        f.write(_inline_includes(path))
    try:
        nl.read(tmp, rdr)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return nl


def _circuit_ci(nl, name):
    """circuit_by_name, but case-insensitive — the default SPICE reader
    upper-cases circuit names (`spm` -> `SPM`), so an exact lookup on the
    caller's `--top spm` would miss it."""
    c = nl.circuit_by_name(name)
    if c is not None:
        return c
    lname = (name or "").lower()
    for c in nl.each_circuit():
        if c.name.lower() == lname:
            return c
    return None


def _lvs_source_ports(pya, path, top):
    nl = _read_spice(pya, path)
    _lvs_strip_strays(nl, top)
    c = _circuit_ci(nl, top)
    if c is None:
        return set()
    return set((c.net_for_pin(p).name if c.net_for_pin(p) else "") for p in c.each_pin())


def _lvs_prep(pya, path, top, realports, power, ground, is_layout):
    nl = _read_spice(pya, path)
    _lvs_strip_strays(nl, top)
    c = _circuit_ci(nl, top)
    if c is None:
        raise RuntimeError(f"no circuit named {top!r} in {path}")
    if is_layout:
        for p in list(c.each_pin()):
            nn = c.net_for_pin(p)
            if (nn.name if nn else None) not in realports:
                c.remove_pin(p.id())
    nl.flatten()
    c = _circuit_ci(nl, top)
    _lvs_normalize_bulk(c, power, ground)
    nl.combine_devices()
    c = _circuit_ci(nl, top)
    dropped = _lvs_drop_power_only(c, {power, ground})
    nl.purge()
    return nl, dropped


def _lvs_tune(nl, pya, tol_abs, tol_rel):
    for dc in nl.each_device_class():
        for pn in ("AS", "AD", "PS", "PD"):
            if dc.has_parameter(pn):
                dc.enable_parameter(pn, False)
        eq = None
        for pn in ("L", "W"):
            if dc.has_parameter(pn):
                t = pya.EqualDeviceParameters(dc.parameter_id(pn), tol_abs, tol_rel)
                eq = t if eq is None else eq + t
        if eq is not None:
            dc.equal_parameters = eq


class _LvsLogger(object):
    """Wrap GenericNetlistCompareLogger, counting real mismatch callbacks."""
    def __new__(cls, pya):
        base = pya.GenericNetlistCompareLogger

        class _L(base):
            def __init__(s):
                base.__init__(s); s.mismatches = 0
            def net_mismatch(s, *a): s.mismatches += 1
            def device_mismatch(s, *a): s.mismatches += 1
            def pin_mismatch(s, *a): s.mismatches += 1
            def circuit_mismatch(s, *a): s.mismatches += 1
        return _L()


def cmd_compare(args, pya):
    top = args.top or "spm"
    power = (args.power or _DEFAULT_PWR).upper()
    ground = (args.ground or _DEFAULT_GND).upper()
    pwr_set = {power, ground}
    realports = _lvs_source_ports(pya, args.source, top) | pwr_set
    lay, drop_l = _lvs_prep(pya, args.gds, top, realports, power, ground, is_layout=True)
    src, drop_s = _lvs_prep(pya, args.source, top, realports, power, ground, is_layout=False)
    _lvs_tune(lay, pya, args.tol_abs, args.tol_rel)
    _lvs_tune(src, pya, args.tol_abs, args.tol_rel)

    def _stats(nl):
        c = _circuit_ci(nl, top)
        cc = {}
        for d in c.each_device():
            k = d.device_class().name
            cc[k] = cc.get(k, 0) + 1
        return {"pins": c.pin_count(),
                "nets": sum(1 for _ in c.each_net()), "devices": cc}
    lg = _LvsLogger(pya)
    ok = pya.NetlistComparer(lg).compare(lay, src)
    result = {
        "verdict": "MATCH" if ok else "MISMATCH",
        "top": top, "power": power, "ground": ground,
        "layout": {**_stats(lay), "power_only_devices_dropped": drop_l},
        "source": {**_stats(src), "power_only_devices_dropped": drop_s},
        "mismatch_msgs": lg.mismatches,
        "tolerance": {"wl_abs_um": args.tol_abs, "wl_rel": args.tol_rel,
                      "parasitic_area_perim": "ignored (extracted=0)"},
        "method": "klayout_netlist_comparer",
        "disclosure": ("KLayout pya NetlistComparer with bulk-normalization + "
                       "power-only-cap waiver + W/L tolerance. Reads only layout "
                       "+ gate netlists (§4.05). NOT silicon-proven."),
    }
    print("LVS_COMPARE " + json.dumps(result))
    if args.out:
        with atomic_writing(args.out) as f:
            json.dump(result, f, indent=2)
        print("wrote", args.out)
    return 0 if ok else 4


def main(argv=None):
    ap = argparse.ArgumentParser(description="Net-correct KLayout transistor LVS extraction + compare")
    ap.add_argument("cmd", choices=["extract", "lib", "cell", "compare"])
    ap.add_argument("gds", help="GDS (extract/lib/cell) or LAYOUT SPICE netlist (compare)")
    ap.add_argument("--cell")
    ap.add_argument("--out")
    ap.add_argument("--source", help="compare: gate-level SOURCE SPICE netlist (reference)")
    ap.add_argument("--top", help="compare: top circuit name (default spm)")
    ap.add_argument("--power", help="compare: power net name (default VDD)")
    ap.add_argument("--ground", help="compare: ground net name (default VSS)")
    ap.add_argument("--tol-abs", type=float, default=0.05, dest="tol_abs",
                    help="compare: W/L absolute tolerance in um (default 0.05)")
    ap.add_argument("--tol-rel", type=float, default=0.02, dest="tol_rel",
                    help="compare: W/L relative tolerance (default 0.02)")
    ap.add_argument("--layermap", help="JSON PDK layer map (default: a generic example; supply your PDK's)")
    ap.add_argument("--pdk-map", dest="pdk_map",
                    help="PDK Encounter/SoC LEF->GDS layermap file (`<NAME> <PURPOSE> "
                         "<gdsL> <gdsDT>` rows); auto-extends the metal/via layer "
                         "coverage to the PDK's full routing stack so upper-metal nets "
                         "are not split (prevents a false LVS mismatch on >4-metal PDKs)")
    ap.add_argument("--threads", type=int, default=_default_threads())
    args = ap.parse_args(argv)
    pya = _require_pya()
    return {"extract": cmd_extract, "lib": cmd_lib, "cell": cmd_cell,
            "compare": cmd_compare}[args.cmd](args, pya)


if __name__ == "__main__":
    sys.exit(main())
