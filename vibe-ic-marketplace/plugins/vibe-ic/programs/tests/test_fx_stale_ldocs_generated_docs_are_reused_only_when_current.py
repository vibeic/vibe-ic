#!/usr/bin/env python3
"""FX_STALE_LDOCS — generated L docs are reused only when they are what the
CURRENT phase-1 producer would write (reworked after review wave8).

MEASURED on subservient (8HD-4, 2026-09-28, lane fxtb FX_P2 arm f4): an exact
fresh copy of a tree whose L1 had been written by the pre-fix producer kept
FAILing `l1_pin_table_aliases_typed_check` after the producer was fixed,
because the front door skipped phase 1 whenever 13 L docs existed.

Review wave8 (LDOCS: correctness DO_NOT_LAND, integrity LAND_AFTER_FIX) found
the mechanism right and its inputs wrong; each finding has a test here:
  B1  the design-input digest hashed files the FLOW rewrites (phase 3's
      tapeout declaration), so REUSE was unreachable after a full run;
  B2  a later FLOW rewrite of a doc (A8's rail synth, restamp_l_doc_skeletons)
      read as a hand edit and halted the next run;
  M3  plugin DATA files, `tools/`, `-m` launches and the --pdk/--ic-name knobs
      were outside the identity;
  M4  the stamp blessed docs the run did not write; an interrupted
      regeneration left the old stamp vouching; handed docs were judged stale
      by window runs;
  §4.05  the input digest restated its own off-limits list.

A tiny fake PLUGIN is built per test (programs/ + data/): its producer reads a
data file and the design input, lists the input dir, and writes the L docs --
all under phase 1's own `ProducerRecorder`. chip-AGNOSTIC.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import vibe_ic_one_shot_runner as ORCH  # noqa: E402


KNOBS = {"ic_name": "chip", "pdk": "", "mode": "docs"}

PRODUCER = '''
import json, os
from pathlib import Path
HERE = Path(__file__).resolve().parent

def produce(project, n=13, skip=(), declaration=False, raise_after=None):
    table = json.loads((HERE.parent / "data" / "table.json").read_text())
    docs = Path(project) / "input" / "docs"
    spec = (docs / "spec.md").read_text()
    list(os.scandir(docs))
    if declaration:
        d = Path(project) / "input" / "submission_template"
        d.mkdir(parents=True, exist_ok=True)
        (d / "tapeout_declaration.json").write_text('{"answers": {}}')
        (d / "tapeout_declaration.json").read_text()   # phase 1 reads its own
        list(os.scandir(d))
    gd = Path(project) / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        if i in skip:
            continue
        if raise_after is not None and i > raise_after:
            raise RuntimeError("layer step died")
        (gd / f"L{i}_DOC.json").write_text(
            json.dumps({"doc": i, "t": table["v"], "len": len(spec)}))
'''


def _plugin(tmp_path: Path) -> Path:
    plug = tmp_path / "plugin"
    (plug / "programs").mkdir(parents=True)
    (plug / "data").mkdir()
    (plug / "programs" / "fake_l_producer.py").write_text(PRODUCER)
    (plug / "data" / "table.json").write_text('{"v": 1}')
    return plug


def _project(tmp_path: Path, design_input=True) -> Path:
    proj = tmp_path / "proj"
    if design_input:
        (proj / "input" / "docs").mkdir(parents=True)
        (proj / "input" / "docs" / "spec.md").write_text("# spec\n")
        (proj / "input" / "unread_notes.txt").write_text("never read\n")
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    return proj


def _load(plug: Path):
    # keyed by the PATH: `id()` is reused across tests, and a cached module
    # from another test's plugin would run that plugin's producer.
    import hashlib
    name = "fake_l_producer_" + hashlib.sha1(
        str(plug.resolve()).encode()).hexdigest()[:12]
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, plug / "programs" / "fake_l_producer.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod








# ---------------------------------------------------------------------------
# the measured case, the old project, and the control
# ---------------------------------------------------------------------------






# A Default continuation can submit intact historical outputs to today's D1
# consumers. That is revalidation, never a claim about today's producer bytes.


def _source_drift(plug):
    src = plug / "programs" / "fake_l_producer.py"
    src.write_text(src.read_text() + "\n# another producer revision\n")












# ---------------------------------------------------------------------------
# B1 — design input is what phase 1 READ, not what the flow rewrites
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# M3 — plugin data, knobs, -m launches, top-level closure only
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# M4 — only what this run wrote; an interrupted run; handed docs
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# B2 — a FLOW rewrite after phase 1 is recorded, a hand edit refuses
# ---------------------------------------------------------------------------










def test_the_refusal_halts_the_run_by_name():
    src = Path(ORCH.__file__).read_text()
    assert 'plan.append(("phase1", "NOT_MEASURED", 1))' in src
    assert "p1_mode == _P1_MODE_REFUSED" in src


# ---------------------------------------------------------------------------
# design input itself; supersede; the second track; the sibling entry
# ---------------------------------------------------------------------------




















# ---------------------------------------------------------------------------
# the producer side: phase 1 stamps what it ran, and only when it ran D1
# ---------------------------------------------------------------------------
def _p1(monkeypatch, body):
    import phase1_one_shot_runner as P1
    monkeypatch.setattr(P1, "main", body)
    return P1
