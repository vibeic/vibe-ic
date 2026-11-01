"""Native macro-top PDN geometry. All nets/pins come from the declaration/ODB.

The PDK chooses routing layers, widths, pitches and via definitions. Pad-only
rails use the existing pad network and its external supply landing; a mesh is
only needed for rails with core loads. Narrow macro pins escape on their own
layer before changing layers outside the macro. No abstract blockage is erased.
"""
from pathlib import Path
import json
import subprocess

from librelane_contract import Refusal


def box(rect):
    return (rect.xMin(), rect.yMin(), rect.xMax(), rect.yMax())


def area(rect):
    a, b, c, d = box(rect)
    return (c-a)*(d-b)


def geometries(term):
    return [(layer, rect) for layer, rect in term.getGeometries() if layer.getRoutingLevel() > 0]


def bond_geometry(term, side):
    """The declared terminal's outermost metal is the external supply port."""
    def distance(item):
        layer, rect = item
        a, b, c, d = box(rect)
        edge = {"south": b, "west": a, "north": -d, "east": -c}[side]
        return edge, -layer.getRoutingLevel(), -area(rect)
    shapes = geometries(term)
    if not shapes:
        raise Refusal("A18_SUPPLY_PAD_ACCESS_ABSENT", term.getMTerm().getName())
    return min(shapes, key=distance)


def loaded_rails(block, intent):
    return {term.getNet().getName() for name in intent["core_instances"]
            for term in block.findInst(name).getITerms()
            if term.getNet() and term.getNet().getName() in intent["rails"]}


def prepare_recipe(odb_path, config, intent, prefix, destination):
    import odb
    db = odb.dbDatabase.create()
    odb.read_db(db, str(odb_path))
    block = db.getChip().getBlock()
    units = block.getDbUnitsPerMicron()
    core = box(block.getCoreArea())
    vertical, horizontal = config["PDN_VERTICAL_LAYER"], config["PDN_HORIZONTAL_LAYER"]
    powers = [n for n, kind in intent["rails"].items() if kind == "POWER"]
    grounds = [n for n, kind in intent["rails"].items() if kind == "GROUND"]
    secondary = [n for n in intent["rails"] if n not in (powers[0], grounds[0])]
    lines = [prefix, f"set_voltage_domain -name Core -power {{{powers[0]}}} -ground {{{grounds[0]}}} "
             + "-secondary_power {" + " ".join(secondary) + "}",
             f"define_pdn_grid -name a18_grid -starts_with POWER -pins {{{vertical} {horizontal}}}"]
    for axis, layer in (("V", vertical), ("H", horizontal)):
        args = " ".join(f"-{key.lower()} {config['PDN_'+axis+key]}" for key in ("WIDTH", "PITCH", "OFFSET", "SPACING"))
        lines.append(f"add_pdn_stripe -grid a18_grid -layer {{{layer}}} {args} -starts_with POWER -extend_to_core_ring")
    width_v, width_h = float(config["PDN_CORE_RING_VWIDTH"]), float(config["PDN_CORE_RING_HWIDTH"])
    lines.append(f"add_pdn_ring -grid a18_grid -layers {{{vertical} {horizontal}}} "
                 f"-widths {{{width_v} {width_h}}} "
                 f"-spacings {{{config['PDN_CORE_RING_VSPACING']} {config['PDN_CORE_RING_HSPACING']}}} "
                 f"-core_offsets {{{config['PDN_CORE_RING_VOFFSET']} {config['PDN_CORE_RING_HOFFSET']}}} -connect_to_pads")
    # Ring positions follow actual placed pad PG bands, rather than a uniform
    # distance from the core. Corners are opaque; their internal PG connection
    # remains part of the verified pad cells.
    for net in intent["rails"]:
        centers = {}
        for pad in intent["pads"]:
            inst = block.findInst(pad["name"])
            axis = 1 if pad["side"] in ("south", "north") else 0
            candidates = [r for t in inst.getITerms() if t.getNet() and t.getNet().getName() == net
                          for l, r in geometries(t) if l.getName() == vertical]
            if candidates:
                reverse = pad["side"] in ("south", "west")
                chosen = sorted(candidates, key=lambda r: box(r)[axis]+box(r)[axis+2], reverse=reverse)[0]
                centers.setdefault(pad["side"], []).append((box(chosen)[axis]+box(chosen)[axis+2])/2/units)
        if set(centers) != {"south", "east", "north", "west"}:
            raise Refusal("A18_PAD_PG_BAND_ABSENT", net)
        c = {side: sum(values)/len(values) for side, values in centers.items()}
        # OpenROAD expects left, bottom, right, top offsets from the core.
        offsets = [core[0]/units-c["west"]-width_v/2, core[1]/units-c["south"]-width_h/2,
                   c["east"]-core[2]/units-width_v/2, c["north"]-core[3]/units-width_h/2]
        if min(offsets) < 0:
            raise Refusal("A18_PAD_PG_BAND_INSIDE_CORE", net)
        lines.append(f"add_pdn_ring -grid a18_grid -layers {{{vertical} {horizontal}}} "
                     f"-widths {{{width_v} {width_h}}} "
                     f"-spacings {{{config['PDN_CORE_RING_VSPACING']} {config['PDN_CORE_RING_HSPACING']}}} "
                     + "-core_offsets {" + " ".join(map(str, offsets)) + "} -nets {" + net + "}")
    # A pad/macro PG pin can be on a lower routing layer than the mesh.
    pin_layers = {l.getName() for inst in block.getInsts() for t in inst.getITerms()
                  if t.getNet() and t.getNet().getName() in intent["rails"] for l, _ in geometries(t)}
    pairs = {tuple(sorted((a, b), key=lambda n: db.getTech().findLayer(n).getRoutingLevel()))
             for a in pin_layers | {vertical, horizontal} for b in (vertical, horizontal) if a != b}
    for a, b in sorted(pairs):
        lines.append(f"add_pdn_connect -grid a18_grid -layers {{{a} {b}}}")
    Path(destination).write_text("\n".join(lines)+"\n")


def escape_geometry(choice):
    _, _, layer, edge, transverse, end, axis, width, via = choice
    start, stop = sorted((edge, end))
    low = transverse-width//2
    high = low+width
    # The neck fits the LEF pin. The native via contributes its wider local
    # enclosure at the landing, rather than widening the whole escape route.
    coords = (start,low,stop,high) if axis == 0 else (low,start,high,stop)
    x, y = (end, transverse) if axis == 0 else (transverse, end)
    shapes = [(layer, coords)]
    for q in via.getBoxes():
        if q.getTechLayer().getRoutingLevel() > 0:
            a, b, c, d = box(q)
            shapes.append((q.getTechLayer(), (a+x,b+y,c+x,d+y)))
    return coords, x, y, shapes


def placed_obstruction(inst, obstruction):
    import odb
    a, b, c, d = box(obstruction)
    points = [odb.Point(x,y) for x,y in ((a,b),(a,d),(c,b),(c,d))]
    transform = inst.getTransform()
    for point in points:
        transform.apply(point)
    return (min(p.x() for p in points), min(p.y() for p in points),
            max(p.x() for p in points), max(p.y() for p in points))


def escape_is_clear(block, inst, net, intent, shapes):
    # Include via enclosures, not only the centreline. These are conservative
    # access checks; the native router/checker still owns physical verification.
    obstacles = []
    for other in block.getInsts():
        if other != inst and other.getName() in intent["core_instances"]:
            obstacles.extend((layer, box(other.getBBox())) for layer, _ in shapes)
        for term in other.getITerms():
            if term.getNet() != net:
                obstacles.extend((layer, box(rect)) for layer, rect in geometries(term))
        for obstruction in other.getMaster().getObstructions():
            layer = obstruction.getTechLayer()
            if layer is not None and layer.getRoutingLevel() > 0:
                obstacles.append((layer, placed_obstruction(other, obstruction)))
    for other_net in block.getNets():
        if other_net == net:
            continue
        for wire in other_net.getSWires():
            for segment in wire.getWires():
                if segment.isVia():
                    via = segment.getTechVia() or segment.getBlockVia()
                    obstacles.extend((q.getTechLayer(), box(segment)) for q in via.getBoxes()
                                     if q.getTechLayer().getRoutingLevel() > 0)
                else:
                    obstacles.append((segment.getTechLayer(), box(segment)))
    for obstruction in block.getObstructions():
        shape = obstruction.getBBox()
        obstacles.append((shape.getTechLayer(), box(shape)))
    for layer, (a,b,c,d) in shapes:
        spacing = layer.getSpacing()
        for other_layer, (x,y,u,v) in obstacles:
            if layer.getName() == other_layer.getName() and a < u+spacing and c > x-spacing and b < v+spacing and d > y-spacing:
                return False
    return True


def connect_macro_edges(db, intent, config):
    import odb
    block = db.getChip().getBlock()
    layers = {config["PDN_VERTICAL_LAYER"], config["PDN_HORIZONTAL_LAYER"]}
    for name in intent["core_instances"]:
        inst = block.findInst(name)
        bounds = box(inst.getBBox())
        for term in inst.getITerms():
            net = term.getNet()
            if not net or net.getName() not in intent["rails"]:
                continue
            choices = []
            narrow_access, legal_access = False, False
            for layer, rect in geometries(term):
                a, b, c, d = box(rect)
                for axis, sign, edge in ((0,-1,a),(0,1,c),(1,-1,b),(1,1,d)):
                    if edge != bounds[axis+(2 if sign > 0 else 0)]:
                        continue
                    width = layer.getWidth()
                    pin_width = d-b if axis == 0 else c-a
                    if pin_width < width:
                        narrow_access = True
                        continue
                    legal_access = True
                    transverse = (b+d)//2 if axis == 0 else (a+c)//2
                    for sw in net.getSWires():
                        for target in sw.getWires():
                            if target.isVia() or target.getTechLayer().getName() not in layers or target.getTechLayer() == layer:
                                continue
                            coords = box(target)
                            if not coords[1-axis] <= transverse <= coords[3-axis]:
                                continue
                            end = (coords[axis]+coords[axis+2])//2
                            if sign*(end-edge) <= 0:
                                continue
                            vias = [v for v in block.getVias() if {q.getTechLayer().getName() for q in v.getBoxes()
                                    if q.getTechLayer().getRoutingLevel()>0} == {layer.getName(),target.getTechLayer().getName()}]
                            for via in vias:
                                top = [q for q in via.getBoxes() if q.getTechLayer() == target.getTechLayer()]
                                x, y = (end, transverse) if axis == 0 else (transverse, end)
                                if any(not (coords[0] <= x+q.xMin() and x+q.xMax() <= coords[2]
                                            and coords[1] <= y+q.yMin() and y+q.yMax() <= coords[3]) for q in top):
                                    continue
                                choices.append((abs(end-edge), sum(area(q) for q in via.getBoxes()),
                                                layer, edge, transverse, end, axis, width, via))
            if not choices:
                if narrow_access and not legal_access:
                    raise Refusal("A18_MACRO_PG_PIN_TOO_NARROW", f"{name}/{term.getMTerm().getName()}")
                raise Refusal("A18_MACRO_PG_EDGE_ACCESS_ABSENT", f"{name}/{term.getMTerm().getName()}")
            for choice in sorted(choices, key=lambda c:c[:2]):
                coords, x, y, shapes = escape_geometry(choice)
                if escape_is_clear(block, inst, net, intent, shapes):
                    break
            else:
                raise Refusal("A18_MACRO_PG_ESCAPE_BLOCKED", f"{name}/{term.getMTerm().getName()}")
            layer, via = choice[2], choice[-1]
            sw = net.getSWires()[0]
            odb.dbSBox.create(sw, layer, *coords, "STRIPE")
            odb.dbSBox.create(sw, via, x, y, "STRIPE")


def connect_pad_ties(db, intent, config):
    import odb
    block, tech = db.getChip().getBlock(), db.getTech()
    routing = sorted([l for l in tech.getLayers() if l.getRoutingLevel()>0], key=lambda l:l.getRoutingLevel())
    target_layer = tech.findLayer(config["PDN_VERTICAL_LAYER"])
    half = round(float(config["PDN_VWIDTH"])*block.getDbUnitsPerMicron()/2)
    for pad in intent["pads"]:
        inst = block.findInst(pad["name"])
        for term in inst.getITerms():
            net = term.getNet()
            if not net or net.getName() not in intent["rails"] or term.getMTerm().getSigType() in ("POWER", "GROUND"):
                continue
            # External bond terminals are already connected inside the pad.
            if term.getMTerm().getName() == pad["terminal"]:
                continue
            source_layer, rect = max(geometries(term), key=lambda t:t[0].getRoutingLevel())
            pg = [(l,r) for t in inst.getITerms() if t != term and t.getNet() == net
                  and t.getMTerm().getSigType() in ("POWER","GROUND")
                  for l,r in geometries(t) if l == target_layer]
            if not pg or source_layer.getRoutingLevel()>target_layer.getRoutingLevel():
                raise Refusal("A18_PAD_TIE_ACCESS_ABSENT", f"{pad['name']}/{term.getMTerm().getName()}")
            x, y = (rect.xMin()+rect.xMax())//2, (rect.yMin()+rect.yMax())//2
            _, target = min(pg, key=lambda t:abs((t[1].xMin()+t[1].xMax())//2-x)+abs((t[1].yMin()+t[1].yMax())//2-y))
            sw = net.getSWires()[0]
            levels = [l for l in routing if source_layer.getRoutingLevel() <= l.getRoutingLevel() <= target_layer.getRoutingLevel()]
            for lo, hi in zip(levels, levels[1:]):
                vias = [v for v in tech.getVias() if {q.getTechLayer().getName() for q in v.getBoxes()
                        if q.getTechLayer().getRoutingLevel()>0} == {lo.getName(),hi.getName()}]
                if lo == source_layer:
                    vias = [v for v in vias if all(rect.xMin() <= x+q.xMin() and x+q.xMax() <= rect.xMax()
                            and rect.yMin() <= y+q.yMin() and y+q.yMax() <= rect.yMax()
                            for q in v.getBoxes() if q.getTechLayer() == lo)]
                if not vias:
                    raise Refusal("A18_PAD_TIE_VIA_ABSENT", f"{pad['name']}/{term.getMTerm().getName()}: {lo.getName()}")
                via = min(vias, key=lambda v:sum(area(q) for q in v.getBoxes()))
                odb.dbSBox.create(sw, via, x, y, "STRIPE")
            tx = max(target.xMin()+half, min(x,target.xMax()-half))
            ty = max(target.yMin()+half, min(y,target.yMax()-half))
            odb.dbSBox.create(sw,target_layer,min(x,tx)-half,y-half,max(x,tx)+half,y+half,"STRIPE")
            if ty != y:
                odb.dbSBox.create(sw,target_layer,tx-half,min(y,ty)-half,tx+half,max(y,ty)+half,"STRIPE")


def finish(odb_path, intent, config, directory):
    import odb
    db = odb.dbDatabase.create(); odb.read_db(db,str(odb_path))
    block = db.getChip().getBlock()
    loaded = loaded_rails(block, intent)
    for net_name in set(intent["rails"])-loaded:
        pads = [p for p in intent["pads"] if p["port"] == net_name]
        if not pads:
            raise Refusal("A18_SUPPLY_PAD_ABSENT", net_name)
        net = block.findNet(net_name)
        for sw in list(net.getSWires()):
            odb.dbSWire.destroy(sw)
        sw = odb.dbSWire.create(net,"ROUTED")
        bt = block.findBTerm(net_name)
        for bp in list(bt.getBPins()):
            odb.dbBPin.destroy(bp)
        for pad in pads:
            layer, rect = bond_geometry(block.findInst(pad["name"]).findITerm(pad["terminal"]),pad["side"])
            bp = odb.dbBPin.create(bt); bp.setPlacementStatus("FIRM")
            odb.dbBox.create(bp,layer,*box(rect))
            odb.dbSBox.create(sw,layer,*box(rect),"STRIPE")
    connect_macro_edges(db, intent, config)
    connect_pad_ties(db,intent,config)
    odb.write_db(db,str(odb_path))
    odb.write_def(block,str(Path(odb_path).with_suffix(".def")))
    return {"core_load_rails": sorted(loaded), "pad_only_rails": sorted(set(intent["rails"])-loaded)}


def check(odb_path, rails, directory, openroad):
    """Recheck every final rail with the unchanged native connectivity checker."""
    directory = Path(directory)
    script = directory / "check-final-pdn.tcl"
    lines = [f"read_db {{{odb_path}}}", "set failed 0"]
    for rail in rails:
        lines += [f"if {{[catch {{check_power_grid -net {{{rail}}} -error_file {{{directory / (rail+'-final-grid-errors.rpt')}}}}} result] || !$result}} {{",
                  f"  puts stderr {{A18_FINAL_PDN_FAILED: {rail}}}", "  set failed 1", "}"]
    lines.append("exit $failed")
    script.write_text("\n".join(lines)+"\n")
    with (directory / "check-final-pdn.log").open("w") as log:
        subprocess.run([openroad,"-exit",str(script)],stdout=log,stderr=subprocess.STDOUT,check=True)
