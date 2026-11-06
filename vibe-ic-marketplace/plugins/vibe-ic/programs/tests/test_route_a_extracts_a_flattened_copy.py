"""Route A (`magic_port_extract_emit.build_extraction_tcl`) must extract a FLAT
copy of the top, as its `flatten_top` option promises.

MEASURED in the pinned image (vibeic-eda 0.3.83, magic 8.3.684). Main emitted
`flatten <top>` while `<top>` was the loaded cell. Magic refuses a target that
already exists ("<top> already exists"), writes nothing and carries on, so the
script extracted the HIERARCHICAL top:

    arm                            spm (fxspm1 integ_run GDS)          fixture
    main  `flatten spm`            29 .subckt, top `spm` = 616 X-lines  2 .subckt
    fixed `flatten -dotoplabels`   1 .subckt `spm_flat`, 5054 devices  1 .subckt
          into `spm_flat`, load it   the same 38 ports as main           TOPPIN VSUBS
    same, WITHOUT -dotoplabels     386 ports, 348 instance-prefixed    11 prefixed

The rule the emitter follows now: flatten into `flat_cell_name(top)`, which
differs from the top, load THAT before `port makeall` and `extract all`, and
refuse (exit 3) when a cell of that name is already in the GDS, because then
the flatten would be inert again.

The structural tests run everywhere. The behavioural ones run Magic on a layout
built from the standard-cell library the environment declares (PDK_ROOT, PDK,
STD_CELL_LIBRARY, as the pinned image sets them) and skip, naming why, where
Magic or that library is absent; run them in the pinned image
(tools/ci/run_suite_in_eda_image.sh).
"""
from __future__ import annotations

import importlib
import os
import re
import shutil
from pathlib import Path

import pytest

import _progress_run as _pr
from _tool_probes import skip_not_verified

M = importlib.import_module("magic_port_extract_emit")


def _commands(tcl: str):
    """Each TCL line as its token list; comments and blank lines dropped."""
    return [ln.split() for ln in tcl.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def _flatten_target(tcl: str):
    """The cell the script's one `flatten` writes (its last argument)."""
    fl = [c for c in _commands(tcl) if c[0] == "flatten"]
    assert len(fl) == 1, f"expected one flatten, got {fl}"
    return fl[0][-1]


def _first(cmds, *head):
    for i, c in enumerate(cmds):
        if c[:len(head)] == list(head):
            return i
    return -1


def test_the_flatten_target_is_a_new_cell_and_is_what_gets_extracted():
    """RED ON MAIN: main flattens into the loaded top's own name."""
    top = "chip"
    tcl = M.build_extraction_tcl(top, "/g.gds", "/o.spice")
    flat = _flatten_target(tcl)
    assert flat != top, (
        f"`flatten {flat}` targets the loaded top itself; Magic answers "
        f"'{top} already exists' and flattens nothing")
    assert flat == M.flat_cell_name(top)
    cmds = _commands(tcl)
    flattens = [c for c in cmds if c[0] == "flatten"]
    assert flattens == [["flatten", "-dotoplabels", flat]], flattens
    i_flat = _first(cmds, "flatten")
    i_load = _first(cmds[i_flat:], "load", flat)
    assert i_load > 0, f"the flat cell {flat} is never loaded after the flatten"
    i_load += i_flat
    for later in (("port", "makeall"), ("extract", "all"), ("ext2spice", "lvs")):
        j = _first(cmds, *later)
        assert j > i_load, f"`{' '.join(later)}` must run on {flat}, after its load"


def test_an_existing_target_cell_is_refused_before_the_flatten():
    """A GDS that already holds `<top>_flat` would make the flatten inert again;
    the script must stop with a non-zero exit rather than extract that cell."""
    top = "my_TOP_9"
    tcl = M.build_extraction_tcl(top, "/g.gds", "/o.spice")
    flat = _flatten_target(tcl)
    guard = re.search(
        r"if \{\[lsearch -exact \[cellname list allcells\] (\S+)\] >= 0\} \{"
        r"(.*?)\n\}", tcl, re.DOTALL)
    assert guard, "no existence check on the flatten target"
    assert guard.group(1) == flat, guard.group(1)
    assert re.search(r"^\s*exit [1-9]\d*\s*$", guard.group(2), re.MULTILINE), (
        "the refusal must exit non-zero, not print and carry on")
    assert tcl.index(guard.group(0)) < tcl.index(f"flatten -dotoplabels {flat}")


def test_no_flatten_extracts_the_top_as_loaded():
    cmds = _commands(M.build_extraction_tcl(
        "top", "/g.gds", "/o.spice", M.MagicExtractOptions(flatten_top=False)))
    assert not [c for c in cmds if c[0] in ("flatten", "if")], cmds
    assert _first(cmds, "load", "top") < _first(cmds, "extract", "all")


# ── behavioural: Magic itself, on the installed PDK's own library ───────────

def _pdk_under_test():
    """(rcfile, pdk name, standard-cell GDS) of the PDK and cell library the
    environment DECLARES (`PDK_ROOT`, `PDK`, `STD_CELL_LIBRARY`, as the pinned
    image sets them), else None. No PDK is named here."""
    root, pdk = os.environ.get("PDK_ROOT"), os.environ.get("PDK")
    lib_name = os.environ.get("STD_CELL_LIBRARY")
    if not (root and pdk and lib_name):
        return None
    pdk_dir = Path(root) / pdk
    rc = pdk_dir / "libs.tech" / "magic" / f"{pdk}.magicrc"
    lib = pdk_dir / "libs.ref" / lib_name / "gds" / f"{lib_name}.gds"
    return (rc, pdk, lib) if rc.is_file() and lib.is_file() else None


def _need_magic():
    if shutil.which("magic") is None:
        skip_not_verified(
            "Magic is absent from this host, so its behavioural extraction test was not measured",
            "Run this file inside the pinned vibeic-eda image",
        )
    try:
        import pya
    except ImportError:
        skip_not_verified(
            "KLayout's pya module is absent from this host, so the layout fixture was not measured",
            "Run this file inside the pinned vibeic-eda image",
        )
    found = _pdk_under_test()
    if found is None:
        skip_not_verified(
            "No declared PDK_ROOT/PDK/STD_CELL_LIBRARY resolves to a Magic rcfile and standard-cell GDS",
            "Run this file inside the pinned vibeic-eda image with its PDK environment",
        )
    return pya, found


def _labelled_cell(pya, lib: Path):
    """The smallest library cell with at least three distinct pin-like labels
    (a logic cell: a filler or tap carries only its supplies and no device),
    with one of those labels' layer and position."""
    ly = pya.Layout()
    ly.read(str(lib))
    best = None
    for c in ly.each_cell():
        if c.child_cells():
            continue
        pins = {}
        for li in ly.layer_indexes():
            for s in c.shapes(li).each():
                if s.is_text() and re.fullmatch(r"[A-Za-z_]\w*", s.text_string):
                    pins.setdefault(s.text_string, (li, s.text.trans.disp))
        if len(pins) >= 3:
            key = (c.bbox().area(), c.name)
            if best is None or key < best[0]:
                name = sorted(pins)[0]
                best = (key, c.name) + pins[name]
    assert best, f"no cell with three pin labels in {lib}"
    return ly, best[1], best[2], best[3]


def _design(pya, lib: Path, out: Path, *, extra_cell: str = ""):
    """Top `chip` with two instances of a labelled library cell (labels KEPT,
    as N6 ships them) and one top label, `TOPPIN`, placed on the first
    instance's own pin so Magic attaches it to that metal."""
    src, cell, li, at = _labelled_cell(pya, lib)
    ly = pya.Layout()
    ly.dbu = src.dbu
    child = ly.create_cell(cell)
    child.copy_tree(src.cell(cell))
    top = ly.create_cell("chip")
    w = child.bbox().width()
    top.insert(pya.CellInstArray(child.cell_index(), pya.Trans(0, 0)))
    top.insert(pya.CellInstArray(child.cell_index(), pya.Trans(3 * w, 0)))
    info = src.get_info(li)
    top.shapes(ly.layer(info)).insert(pya.Text("TOPPIN", pya.Trans(at)))
    if extra_cell:
        squat = ly.create_cell(extra_cell)
        squat.insert(pya.CellInstArray(top.cell_index(), pya.Trans()))
    ly.write(str(out))
    return cell


def _run_route_a(tmp_path: Path, rc: Path, pdk: str, gds: Path):
    spice = tmp_path / "out.spice"
    script = tmp_path / "route_a.tcl"
    script.write_text(_route_a_tcl(gds, spice))
    env = dict(os.environ, PDK=pdk, PDK_ROOT=str(rc.parents[3]))
    r = _pr.run(["magic", "-noconsole", "-dnull", "-rcfile", str(rc),
                 str(script)], cwd=str(tmp_path), env=env,
                capture_output=True, text=True)
    return r, spice


def _route_a_tcl(gds: Path = Path("/g.gds"), spice: Path = Path("/o.spice")):
    return M.build_extraction_tcl("chip", str(gds), str(spice))


def _subckts(spice: Path):
    lines = []
    for ln in spice.read_text(errors="replace").splitlines():
        if ln.startswith("+") and lines:
            lines[-1] += " " + ln[1:]
        else:
            lines.append(ln)
    out, cur = [], None
    for ln in lines:
        m = re.match(r"\.subckt\s+(\S+)(.*)", ln, re.IGNORECASE)
        if m:
            cur = [m.group(1), m.group(2).split(), 0]
            out.append(cur)
        elif re.match(r"\.ends", ln, re.IGNORECASE):
            cur = None
        elif cur is not None and ln[:1] in "XxMm":
            cur[2] += 1
    return out


def test_magic_extracts_one_flat_subckt_with_the_tops_labels_only(tmp_path):
    """RED ON MAIN: two `.subckt`s (the library cell and the hierarchical top)."""
    pya, (rc, pdk, lib) = _need_magic()
    gds = tmp_path / "chip.gds"
    cell = _design(pya, lib, gds)
    r, spice = _run_route_a(tmp_path, rc, pdk, gds)
    assert r.returncode == 0, r.stderr[-2000:]
    subs = _subckts(spice)
    flat = _flatten_target(_route_a_tcl())
    assert [s[0] for s in subs] == [flat] and flat != "chip", (
        f"Route A must extract ONE flat copy of chip, got {[s[0] for s in subs]}")
    name, ports, devices = subs[0]
    assert devices > 0, "the flat cell carries no devices"
    assert "TOPPIN" in ports, ports
    lifted = [p for p in ports if p.startswith(cell + "_")]
    assert not lifted, f"library pin labels became top ports: {lifted}"


def test_magic_refuses_a_gds_that_already_holds_the_flat_cell(tmp_path):
    pya, (rc, pdk, lib) = _need_magic()
    gds = tmp_path / "chip.gds"
    flat = _flatten_target(_route_a_tcl())
    # A cell of the target's name already in the GDS. Where the target IS the
    # top (main), the top itself is that cell and nothing needs adding.
    _design(pya, lib, gds, extra_cell=flat if flat != "chip" else "")
    r, spice = _run_route_a(tmp_path, rc, pdk, gds)
    assert r.returncode != 0, "a squatted flat-cell name must not extract"
    assert "MAGIC_PORT_EXTRACT_REFUSED" in (r.stdout + r.stderr)
    assert not spice.exists()
