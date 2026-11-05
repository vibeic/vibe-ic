"""Step 37.3 re-streams from the stream-out's OWN record of what it read.

MEASURED on lane fxspm1's spm integration run (gf180mcuD, 2026-09-28): step 37.3
answered NOT_MEASURED, rc 127, "the run records no LEF set for its stream-out".
`gds_xor_check` assembled the set from `technology_units.json`, the pad-ring IO
record and a registry glob. A core design has no IO ring, so that assembly was
empty on EVERY such design, for a GDS the flow had just streamed itself (with
Magic, which the re-stream would not have used either).

The rule now:
  * the stream-out step (both engines) writes `<gds stem>.stream_inputs.json`
    beside its output: engine, recipe, DEF, and every LEF / cell GDS / macro GDS /
    layer map / rcfile it handed the tool, each with its sha256;
  * `gds_xor_check` re-streams from that record and nothing else, with the
    recorded engine, after proving each input still holds the recorded bytes
    where the tool runs; an absent or incomplete record is refused BY NAME.

The tool itself is faked (its file writes are not what is under test); the
digest check is real `sha256sum -c` on the host, through `_klayout_launch`'s own
HostRunner.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import _klayout_launch as KL  # noqa: E402
import gds_xor_check as G  # noqa: E402

PNR = "phase3/stage3/pnr"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class _Tool(KL.HostRunner):
    """The real host runner for everything (`sha256sum -c` included) except the
    EDA tool, whose invocation is recorded instead of executed."""

    def __init__(self):
        super().__init__("klayout", ("-zz", "-b", "-r"))
        self.calls = []

    def run(self, script, env, *, path_keys=(), timeout=1800):
        self.calls.append(("klayout", str(script),
                           {k: str(v) for k, v in env.items()}))
        return 0, "", ""

    def run_argv(self, argv, env, *, timeout=1800):
        if argv and argv[0] == "magic":
            self.calls.append(("magic", [str(a) for a in argv],
                               {k: str(v) for k, v in env.items()}))
            return 0, "", ""
        return super().run_argv(argv, env, timeout=timeout)


def _core_run(root: Path, *, engine: str):
    """A core design's run as the stream-out leaves it: DEF, recipe, a legalized
    tech LEF in the project, library files outside it, NO IO-ring record."""
    project = root / "spm"
    pnr = project / PNR
    pnr.mkdir(parents=True)
    dfile = pnr / "spm.def"
    dfile.write_text("VERSION 5.8 ;\nDESIGN spm ;\nCOMPONENTS 0 ;\nEND DESIGN\n")
    (pnr / "routed.def").write_bytes(dfile.read_bytes())
    tlef = pnr / "active_via_legalized.tlef"
    tlef.write_text("VERSION 5.8 ;\n")
    lib = root / "pdk"
    lib.mkdir()
    cell_gds, mapf, rc = lib / "cells.gds", lib / "tech.map", lib / "tech.magicrc"
    cell_gds.write_bytes(b"GDS cells")
    mapf.write_text("metal1 NET 34 0\n")
    rc.write_text("tech load x\n")
    recipe = pnr / ("magic_stream_out.tcl" if engine == "magic" else "stream_out.py")
    recipe.write_text("# the run's own recipe\n")
    files = {"LEFS": str(tlef), "CELL_GDS": str(cell_gds), "MACRO_GDS": "",
             "LEFDEF_MAP": str(mapf) if engine == "klayout" else ""}
    return project, dfile, recipe, files, (str(rc) if engine == "magic" else None)




# ── the producer ─────────────────────────────────────────────────────────────





# ── the consumer ─────────────────────────────────────────────────────────────

def test_a_run_without_the_record_is_refused_by_naming_it(tmp_path):
    """Never assembled from other records. RED ON MAIN: main assembles the LEF
    set from technology_units.json / the IO record / a registry glob and names
    no record."""
    project, dfile, recipe, _files, _rc = _core_run(tmp_path, engine="klayout")
    rc, _so, se = G.stream_reference(_Tool(), project / "scratch", dfile,
                                     project / "out.gds", 60)
    assert rc == 127
    assert f"{PNR}/spm.stream_inputs.json" in se and "records no stream-out input set" in se


def test_the_fxspm1_core_run_is_re_streamed_not_refused(tmp_path):
    """RED ON MAIN, FOR THE MEASURED REASON: a core run whose stream-out left its
    record (written here exactly as the producer writes it) is refused on main
    with rc 127 "the run records no LEF set for its stream-out", because main
    never reads the record and its own assembly needs an IO-ring record."""
    project, dfile, recipe, files, rcfile = _core_run(tmp_path, engine="magic")
    # As on the integration run: step_gds also leaves the KLayout recipe in the
    # pnr dir, so main gets past "recipe absent" to the LEF-set refusal.
    (project / PNR / "stream_out.py").write_text("# the KLayout recipe\n")
    tlef = Path(files["LEFS"])
    entry = lambda p, rel=None: {"path": str(p), "project_rel": rel, "sha256": _sha(Path(p))}
    rec = {"schema": "vibeic.stream_inputs/1", "program": "phase3_one_shot_runner",
           "engine": "magic", "output": "spm.gds", "top": "spm",
           "recipe": {"project_rel": f"{PNR}/{recipe.name}", "sha256": _sha(recipe)},
           "def": {"project_rel": f"{PNR}/spm.def", "sha256": _sha(dfile)},
           "inputs": {"LEFS": [entry(tlef, f"{PNR}/{tlef.name}")],
                      "CELL_GDS": [entry(files["CELL_GDS"])],
                      "MACRO_GDS": [], "LEFDEF_MAP": []},
           "scalars": {}, "rcfile": entry(rcfile), "unhashed": []}
    (project / PNR / "spm.stream_inputs.json").write_text(json.dumps(rec))
    tool = _Tool()
    rc, _so, se = G.stream_reference(tool, project / "scratch", dfile,
                                     project / "scratch" / "ref.gds", 60)
    assert rc == 0, f"a recorded core-design stream-out was refused: {se}"
    assert [c[0] for c in tool.calls] == ["magic"], tool.calls
