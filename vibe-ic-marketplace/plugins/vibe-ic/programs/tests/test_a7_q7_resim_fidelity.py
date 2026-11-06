"""A7 post-layout producer — what "it ran" must also mean (q7, T109).

MEASURED (vibeic-eda 0.3.79, u_hawaii_adc):
  * NON-INTERFERENCE. The producer wrote its 11 resimulation decks into
    `phase3/analog/ldo/post_layout/`; A3's `analog_netlist_pdk_check`
    rglobs `phase3/analog` for `*.sp` and its population grew 13 -> 24.
  * NO SILENT DROP. The extracted body sits one level down (`xrcx`), so a
    delta_sigma probe `meas tran railx_max_nbias max v(xdut.nbias)` fails
    post-layout with "no such vector" while ngspice exits 0 — and `compare()`
    kept only the intersection of pre and post keys, so 240 such rows
    vanished without a record.
  * DEVICE INVENTORY. ldo's extracted netlist carries 30 PDK devices for the
    A3 netlist's 11 (the m=20 pass device as 20 fingers); nothing compared
    them.

The end-to-end tests drive the shipped `run()` against a stub `docker` that
plays the tools only: LibreLane Magic.RCX writes the given SPICE_RCX, and
ngspice answers each `meas` of the deck it is handed — a probe resolves when
the net it names exists in the circuit that deck includes.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401 — puts programs/ on sys.path
import _eda_pin as PIN
import _analog_producer_common as PC
import analog_a7_post_layout_emit as A7
from _stated_eda_image import state_the_image, stated_image  # noqa: E402

#: STATED, NOT READ FROM THIS HOST (lane rfimg2). This was
#: `"ghcr.io/vibeic/vibeic-eda@" + PIN.IMAGE_DIGEST` at module level, which
#: asks this host's docker at collection: inside the image (no docker) the
#: whole file was a collection error. The runs below are in-process, so the
#: pin is stated for each test by `_the_stated_image`.
IMAGE = stated_image()


@pytest.fixture(autouse=True)
def _the_stated_image(monkeypatch):
    state_the_image(monkeypatch)

TECH = "tech\n  format 35\n  t\nend\ninclude t-extract\n"
TECH_EXTRACT = """extract
 style ngspice variants (),(lvs)
 device msubcircuit nfet ndiff ndiff pwell
end
"""

# `ghost` is a net of the A3 circuit that the extraction does not keep (an
# unlabelled net Magic renames); `nint` is one it keeps. The nfet is one
# 4u device in A3 and two 2u fingers after extraction.
A3_NET = (".lib ../../../models/m.lib tt\n.subckt blk a b vss\n"
          "X0 a nint vss vss nfet w=4u l=1u\n"
          "X1 nint ghost cap w=10u l=10u\n"
          "X2 ghost b vss rr w=1u l=5u\n.ends blk\n")
TB = (".include blk.sp\nV1 a 0 1.8\nX1 a b 0 blk\n"
      ".save v(b) v(x1.nint) v(x1.ghost)\n.control\nop\n"
      "meas op vint find v(x1.nint)\n"
      "meas op vgh find v(x1.ghost)\n"
      "let vo = v(b)\n"
      "echo \"MEAS vout=\" $&vo\n.endc\n.end\n")
RCX = """* NGSPICE file created from blk.ext - technology: t
.subckt blk a b vss
X0 a nint vss vss nfet w=2u l=1u
X1 a nint.n1 vss vss nfet w=2u l=1u
X2 nint a_10_20# cap l=10u w=10u
X3 a_10_20# b vss rr w=1u l=5u
R0 nint nint.n1 3.0
C0 nint vss 1.2f
.ends
"""

STUB = r'''#!/usr/bin/env python3
import json, os, re, subprocess, sys
a = sys.argv[1:]
j = " ".join(a)
if a[:2] == ["image", "inspect"]:
    print("null"); sys.exit(0)
if a[0] == "inspect":
    if "Mounts" in j:
        print(json.dumps([{"Type": "bind", "Source": os.environ["STUB_ROOT"],
                           "Destination": os.environ["STUB_ROOT"]}]))
    else:
        print("sha256:aaaa\trepo@" + os.environ["STUB_DIGEST"])
    sys.exit(0)
if a[0] == "run":
    if "--help" in j:
        sys.exit(0)
    if "-c" in a and "Config.load" in a[-1]:
        src = re.search(r"p='([^']+)'", a[-1]).group(1)
        out = re.search(r"out='([^']+)'", a[-1]).group(1)
        cfg = json.load(open(src))
        cfg["MAGIC_TECH"] = os.environ["STUB_TECH"]
        open(out, "w").write(json.dumps(cfg))
        sys.exit(0)
    if "librelane.steps" in a:
        folder = a[a.index("-o") + 1]
        state_in = json.load(open(a[a.index("-i") + 1]))
        os.makedirs(folder, exist_ok=True)
        rcx = os.path.join(folder, "blk.rcx.spice")
        open(rcx, "w").write(open(os.environ["STUB_RCX"]).read())
        state_in["spice_rcx"] = rcx
        open(os.path.join(folder, "state_out.json"), "w").write(
            json.dumps(state_in))
        sys.exit(0)
    sys.exit(1)
if a[0] == "exec":
    cmd = a[-1]
    if "--json-measure" in cmd:
        print("unrecognized option"); sys.exit(0)
    if "command -v ngspice" in cmd:
        print("/foss/tools/bin/ngspice"); sys.exit(0)
    if " -b " in cmd:
        deck = cmd.split()[-2].strip("'")
        text = open(deck).read()
        post = "_post_" in deck
        inc = re.search(r"^\.include\s+(\S+)", text, re.M).group(1)
        circuit = open(os.path.join(os.path.dirname(deck), inc)).read()
        def resolves(path):
            parts = path.split(".")
            if len(parts) == 1:
                return True
            if post:
                # the wrapper holds only its ports and the xrcx instance
                return parts[1] == "xrcx" and (" " + parts[-1] + " ") in (
                    " " + circuit.replace("\n", " ") + " ")
            return (" " + parts[-1] + " ") in (" " + circuit.replace(
                "\n", " ") + " ")
        for line in text.splitlines():
            m = re.match(r"^\s*meas\s+\w+\s+(\w+)\s+\w+\s+v\(([^)]+)\)", line)
            if m:
                if resolves(m.group(2)):
                    print(f"{m.group(1)} = {'0.9' if post else '1.0'}")
                else:
                    print(f"Error: no such vector as 'v({m.group(2)}')")
                    print(f"meas {m.group(1)} failed!")
        if os.environ.get("STUB_POST_LOSES_VOUT") and post:
            print("MEAS vout=")
        else:
            print("MEAS vout= " + ("1.19" if post else "1.20"))
        sys.exit(0)
    sys.exit(subprocess.run(["bash", "-c", cmd]).returncode)
sys.exit(0)
'''


def _project(tmp_path: Path, tb: str = TB, net: str = A3_NET) -> Path:
    project = tmp_path / "proj"
    b = project / "phase3" / "analog" / "blk"
    b.mkdir(parents=True)
    tech_dir = tmp_path / "pdkroot" / "tpdk" / "libs.tech" / "magic"
    tech_dir.mkdir(parents=True)
    (tech_dir / "t.tech").write_text(TECH)
    (tech_dir / "t-extract.tech").write_text(TECH_EXTRACT)
    (b / "blk.gds").write_bytes(b"\x00\x06\x00\x02\x02\x58")
    (b / "blk.sp").write_text(net)
    (b / "layout_provenance.json").write_text(json.dumps({
        "producer": "analog_a5_layout_emit", "result": "OK",
        "pdk_sources": {"magic_tech": str(tech_dir / "t.tech")},
        "netlist_content_sha256": PC.content_digest(net)}))
    (b / "tb_blk.sp").write_text(tb)
    return project


@pytest.fixture
def stub(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    (d / "docker").write_text(STUB.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1))
    (d / "docker").chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_ROOT", str(tmp_path))
    monkeypatch.setenv("STUB_DIGEST", PIN.IMAGE_DIGEST)
    monkeypatch.setenv("STUB_TECH",
                       str(tmp_path / "pdkroot/tpdk/libs.tech/magic/t.tech"))
    monkeypatch.setenv("VIBEIC_DESIGNS_HOST_ROOT", str(tmp_path))
    rcx = tmp_path / "rcx.spice"
    rcx.write_text(RCX)
    monkeypatch.setenv("STUB_RCX", str(rcx))
    import analog_real_corner_sweep as ARS
    ARS._NGSPICE_CACHE.clear()
    ARS._JSON_MEASURE_SUPPORT.clear()
    ARS._CONTAINER_PATH_CACHE.clear()
    return tmp_path


def _sp_population(project: Path):
    """The file population A3's gate examines, by ITS OWN discovery."""
    import analog_netlist_pdk_check as NPC
    return sorted(str(p.relative_to(project)) for root in
                  NPC._analog_roots(project) for p in root.rglob("*.sp"))


# ── (1a) non-interference ─────────────────────────────────────────────────
def test_the_producer_leaves_the_analog_gates_population_member_for_member(
        stub):
    project = _project(stub)
    before = _sp_population(project)
    assert A7.run(project, "blk", "vibeic-eda", IMAGE, ["ngspice()"]) == 0
    assert _sp_population(project) == before
    assert not (project / "phase3/analog/blk/post_layout").exists()
    work = project / "phase3/librelane/analog/blk/a7_resim"
    assert (work / "tb_blk_post_ngspice.sp").is_file()
    rec = json.loads((project / "phase3/analog/blk/a7_post_layout.json")
                     .read_text())
    assert rec["pre"]["testbench"].startswith(
        "phase3/librelane/analog/blk/a7_resim/")


# ── (1b) remap, and nothing dropped silently ──────────────────────────────
def test_an_internal_probe_is_remapped_into_the_extracted_body(stub):
    project = _project(stub)
    assert A7.run(project, "blk", "vibeic-eda", IMAGE, ["ngspice()"]) == 0
    work = project / "phase3/librelane/analog/blk/a7_resim"
    post_tb = (work / "tb_blk_post_ngspice.sp").read_text()
    assert "v(X1.xrcx.nint)" in post_tb or "v(x1.xrcx.nint)" in post_tb
    doc = json.loads((project / "phase3/analog/blk/pre_vs_post.json")
                     .read_text())
    names = {s["name"] for s in doc["specs"]}
    assert "vint@ngspice()" in names, names
    assert "vout@ngspice()" in names


def test_a_probe_whose_net_is_absent_is_listed_by_name_never_dropped(stub):
    project = _project(stub)
    assert A7.run(project, "blk", "vibeic-eda", IMAGE, ["ngspice()"]) == 0
    doc = json.loads((project / "phase3/analog/blk/pre_vs_post.json")
                     .read_text())
    nc = (doc.get("_provenance") or {}).get("not_compared") or {}
    assert "vgh@ngspice()" in nc and "absent" in nc["vgh@ngspice()"], nc
    rec = json.loads((project / "phase3/analog/blk/a7_post_layout.json")
                     .read_text())
    assert "vgh@ngspice()" in (rec.get("not_comparable_post_layout") or {})
    post_tb = (project / "phase3/librelane/analog/blk/a7_resim/"
               "tb_blk_post_ngspice.sp").read_text()
    assert "x1.ghost" not in post_tb.split(".save", 1)[1].split("\n", 1)[0]


def test_a_comparable_measurement_missing_post_layout_is_refused(
        stub, monkeypatch):
    monkeypatch.setenv("STUB_POST_LOSES_VOUT", "1")
    project = _project(stub)
    assert A7.run(project, "blk", "vibeic-eda", IMAGE, ["ngspice()"]) == 1
    rec = json.loads((project / "phase3/analog/blk/a7_post_layout.json")
                     .read_text())
    assert rec["rule"] == "A7_POST_MEASUREMENT_MISSING"
    assert "vout" in rec["detail"]
    assert not (project / "phase3/analog/blk/pre_vs_post.json").exists()


def test_remap_targets_the_wrapper_node_for_an_extracted_port():
    tb = "X9 a b 0 blk\n.save v(x9.nint) v(x9.deep)\n"
    out, dropped = A7.remap_probes(tb, "blk", {"a", "b", "nint"}, {"deep"},
                                   {"a": "a", "b": "b", "nint": "rcx_int_2"})
    assert "v(x9.rcx_int_2)" in out and "v(x9.xrcx.deep)" in out
    assert dropped == {}


def test_an_echo_that_names_a_dropped_measurement_loses_only_that_key():
    tb = ("X1 a b 0 blk\nmeas tran g max v(x1.gone)\nlet h = g / 2\n"
          "echo \"MEAS keep=\" $&k \" hh=\" $&h\n")
    out, dropped = A7.remap_probes(tb, "blk", {"a", "b"}, set(), {})
    assert set(dropped) == {"g", "h", "hh"}
    echo = [ln for ln in out.splitlines() if ln.startswith("echo")][0]
    assert "keep=" in echo and "$&k" in echo and "hh" not in echo


# ── (1c) device inventory ─────────────────────────────────────────────────
def test_the_inventory_sums_mos_fingers_and_counts_everything_else():
    a3 = A7.device_instances(A3_NET, "blk")
    rcx = A7.device_instances(RCX, "blk")
    got = A7.device_inventory(a3, rcx, {"nfet"})
    assert got["result"] == "MATCH", got
    # a MOS model compared as a multiset would call the fingers a mismatch
    assert A7.device_inventory(a3, rcx, set())["result"] == "MISMATCH"
    # a lost capacitor, a changed length: both refused
    lost = [d for d in rcx if d["model"] != "cap"]
    assert A7.device_inventory(a3, lost, {"nfet"})["result"] == "MISMATCH"
    longer = [dict(d, l=2e-6) if d["model"] == "nfet" else d for d in rcx]
    assert A7.device_inventory(a3, longer, {"nfet"})["result"] == "MISMATCH"
    # Magic writes 5 significant digits: 115.384u comes back 0.11538m
    r1 = A7.device_instances(".subckt t a\nX0 a b r w=0.5u l=115.384u\n"
                             ".ends\n", "t")
    r2 = A7.device_instances(".subckt t a\nX0 a b r l=0.11538m w=0.5u\n"
                             ".ends\n", "t")
    assert A7.device_inventory(r1, r2, set())["result"] == "MATCH"


def test_an_extraction_that_changed_the_devices_is_refused(stub, monkeypatch):
    bad = RCX.replace("X2 nint a_10_20# cap l=10u w=10u\n", "")
    p = stub / "rcx_bad.spice"
    p.write_text(bad)
    monkeypatch.setenv("STUB_RCX", str(p))
    project = _project(stub)
    assert A7.run(project, "blk", "vibeic-eda", IMAGE, ["ngspice()"]) == 1
    rec = json.loads((project / "phase3/analog/blk/a7_post_layout.json")
                     .read_text())
    assert rec["rule"] == "A7_RCX_DEVICE_INVENTORY_MISMATCH"
    assert "cap" in rec["detail"]


# ── the `_NOT_PROSE` claim for the two card readers, re-measured ──────────
def _denial_vocabulary() -> list:
    """`_prose_polarity`'s OWN denial words, read out of its own patterns."""
    import re
    import _prose_polarity as PP
    raw = PP._DENIAL_CORE + "|" + PP._DENIAL_RETIRED
    out = set()
    for m in re.findall(r"([A-Za-z][A-Za-z' -]{2,})", raw):
        m = m.strip()
        out.add(m[1:] if m.startswith("b") and len(m) > 3 else m)
    return sorted(w for w in out if len(w) >= 2 and not w.startswith("b"))


_CARD_SHAPES = (
    "meas tran {t} max v(x1.nint)",
    "meas tran k max v(x1.{t})",
    "meas tran k max v(x1.ghost)\nlet {t} = k / 2",
    "meas tran {t} max v(x1.ghost)\necho \"MEAS a=\" $&{t} \" b=\" $&w",
    "meas tran k max v(x1.ghost)\necho \"MEAS {t}=\" $&k \" b=\" $&w",
    ".save v(x1.{t}) v(x1.ghost) v(b)",
    "* {t} v(x1.nint)",
)


def test_the_not_prose_claim_for_the_probe_remap_is_falsifiable():
    """`remap_probes` and `_echo_without` are in
    `prose_polarity_consulted_check._NOT_PROSE` as grammar readers. THE
    PROPERTY: a denial word in any name position changes nothing but the
    name — the output equals the output for a neutral name, with the name
    substituted — so a polarity consult there is a branch that cannot fire.
    THE CONTRAST: the identical strings, read as prose, are denied."""
    import re
    import _prose_polarity as PP
    tokens = [t for t in _denial_vocabulary()
              if re.fullmatch(r"[A-Za-z_]\w*", t)]
    assert len(tokens) >= 5, "the vocabulary was not read"
    trials = changed = 0
    for tok in tokens:
        for shape in _CARD_SHAPES:
            trials += 1
            head = "X1 a b 0 blk\n"
            got = A7.remap_probes(head + shape.format(t=tok) + "\n", "blk",
                                  {"a", "b"}, {"nint", tok.lower()}, {})
            ref = A7.remap_probes(head + shape.format(t="zqz") + "\n", "blk",
                                  {"a", "b"}, {"nint", "zqz"}, {})
            want = (ref[0].replace("zqz", tok),
                    {k.replace("zqz", tok.lower()): v.replace("zqz", tok.lower())
                     for k, v in ref[1].items()})
            if got != want:
                changed += 1
    assert trials >= 35
    assert changed == 0, ("a denial word changed what the card reader wrote "
                          "— the _NOT_PROSE entries for analog_a7_post_layout"
                          "_emit are false; delete them, not this assertion")
    prose = sum(1 for t in tokens for s in _CARD_SHAPES
                if PP.is_denied(s.format(t=t)))
    assert prose >= len(tokens), "the vocabulary is not inert as prose"
