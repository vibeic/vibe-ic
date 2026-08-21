"""v1.6.68 — LVS was unrunnable at random because magic's DEF reader aborts
on a DEF BLOCKAGES entry that names no layer.

Field observation (real Phase-3 run, multi-supply ASIC): the routed DEF held

    BLOCKAGES 1 ;
        - PLACEMENT + SOFT + COMPONENT <inst> RECT ( x1 y1 ) ( x2 y2 ) ;
    END BLOCKAGES

A `- PLACEMENT` entry is a directive to the PLACER; it names no layer and
carries no conductor. Magic has nothing to bind the RECT to, prints

    LEF read, Line NNNN (Error): No layer defined for RECT.

and then terminates the DEF read PART OF THE TIME. Measured on the SAME
byte-identical DEF with the SAME command: 2 of 5 runs produced a netlist,
3 of 5 produced none. With the layer-less entry removed: 5 of 5 produced a
netlist, and every one of them was byte-identical (same md5) to the netlist
the intact DEF produced on the runs where it happened to survive — i.e. the
removal is loss-free for extraction, which is what makes it a fix and not a
workaround.

Two independent defects, pinned separately:

  D1  the runner fed magic the signed-off DEF as-is, so a design that uses a
      placement blockage (a routine macro-halo / keep-out) had a ~60 %
      chance of no LVS at all;
  D2  magic exits 0 even on a fatal `lef read` / `def read`, so `rc=0` is not
      evidence. The no-netlist branch reported "produced no extracted netlist
      (rc=0)" — a message that states a file is missing while implying the
      tool was fine.

HOW THIS FILE PROVES IT, AND WHY IT WAS REWRITTEN (2026-08-05)
=============================================================
As first landed (41c49f94d) this file did NOT reproduce either defect. Measured
against the pre-landing tree e3aa9b126, its 9 tests came out:

    6 x AttributeError  — `P3._strip_nonlayer_blockages` does not exist there;
    1 x AssertionError  — but on `'_strip_nonlayer_blockages(' in <source text>`,
                          i.e. a grep for that same new symbol's NAME;
    1 x ValueError      — `_P3_CODE.index('"LVS_EXTRACTION_NO_NETLIST", _detail')`
                          on a source string that does not contain it;
    1 x PASS            — the pipefail test, which is about a shared repair that
                          predates this landing and passes on both trees.

So eight of nine failures said only "a private helper is missing" or "a string
is missing from the source". That is symbol existence, not behaviour, and the
landing commit's own docstring claimed the opposite of it.

Every test below now drives `step_lvs` — the shipped Phase-3 step — with a
fake container, and asserts on what the flow OBSERVABLY does:

  * the DEF TEXT magic is actually handed (read back from the `DEF=` the
    runner puts in the command it issues);
  * the signed-off DEF's bytes on disk afterwards;
  * the provenance record beside the staged copy;
  * the fields of the FAIL verdict the step publishes.

Each of those raises AssertionError on e3aa9b126 and passes on b85d68acc.

chip-AGNOSTIC: DEF syntax + the step's own reports. No PDK, no container, no
tool.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as P3  # noqa: E402


# --------------------------------------------------------------------------
# DEF fixtures. Deliberately fewer than 16 signal nets so the unrelated
# signal-routing honesty gate (`_LVS_MIN_SIGNAL_NETS_FOR_ROUTING_CHECK`) does
# not decide these runs; the question here is about BLOCKAGES.
# --------------------------------------------------------------------------
_HEAD = """\
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
"""

_TAIL = """\
COMPONENTS 1 ;
- u0 CELLA + PLACED ( 0 0 ) N ;
END COMPONENTS
SPECIALNETS 1 ;
    - VDD ( * VPWR ) + USE POWER ;
END SPECIALNETS
END DESIGN
"""

#: the measured shape: a layer-less PLACEMENT directive between two ordinary
#: layer blockages, and spanning two physical lines as OpenROAD writes it.
_LAYERLESS = ("    - PLACEMENT + SOFT + COMPONENT u_otp.u_macro "
              "RECT ( 10560 305780 )\n      ( 426560 458780 ) ;\n")
_LAYER_1 = "    - LAYER MET1 RECT ( 100 200 ) ( 300 400 ) ;\n"
_LAYER_2 = "    - LAYER MET2 RECT ( 5 6 ) ( 7 8 ) ;\n"

DEF_MIXED = (_HEAD + "BLOCKAGES 3 ;\n" + _LAYER_1 + _LAYERLESS + _LAYER_2
             + "END BLOCKAGES\n" + _TAIL)
DEF_ONLY_LAYERLESS = (_HEAD + "BLOCKAGES 1 ;\n" + _LAYERLESS
                      + "END BLOCKAGES\n" + _TAIL)
DEF_ALL_LAYER = (_HEAD + "BLOCKAGES 2 ;\n" + _LAYER_1 + _LAYER_2
                 + "END BLOCKAGES\n" + _TAIL)
DEF_NO_BLOCKAGES = _HEAD + _TAIL


_CLEAN_NETGEN = "Final result: Circuits match uniquely.\n"


class Run:
    """What a driven `step_lvs` did, from the outside."""

    def __init__(self, project: Path, result, magic_cmds):
        self.project = project
        self.result = result
        self.magic_cmds = magic_cmds

    @property
    def def_path_handed_to_magic(self) -> Path:
        assert len(self.magic_cmds) == 1, (
            f"expected exactly one magic extraction command, got "
            f"{len(self.magic_cmds)}")
        m = re.search(r"DEF=(\S+)", self.magic_cmds[0])
        assert m, f"the magic command names no DEF: {self.magic_cmds[0][:400]}"
        return Path(m.group(1))

    @property
    def def_text_handed_to_magic(self) -> str:
        return self.def_path_handed_to_magic.read_text()

    @property
    def signed_off_def(self) -> Path:
        return self.project / "phase3" / "stage3" / "pnr" / "chip_top.def"

    @property
    def provenance(self):
        p = (self.project / "phase3" / "stage3" / "extracted"
             / "extract_def_provenance.json")
        return json.loads(p.read_text()) if p.is_file() else None

    @property
    def verdict(self):
        p = self.project / "reports" / "phase3" / "lvs_verdict.json"
        return json.loads(p.read_text()) if p.is_file() else None


def _drive(tmp_path: Path, monkeypatch, def_text: str, *,
           magic_writes_netlist: bool = True,
           magic_log: str = "MAGIC_EXT2SPICE_DONE\n",
           netgen_transcript: str = _CLEAN_NETGEN) -> Run:
    """Run the shipped `step_lvs` against a fake container.

    The fake answers the runner's tool/tech probes, then plays magic and
    netgen. `magic_writes_netlist=False` is the MEASURED failure shape: rc 0,
    no `.sp` written, and a log that never reaches the recipe's own completion
    sentinel.
    """
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top.def").write_text(def_text)
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text("module chip_top();\nendmodule\n")

    pdk = P3.PdkConfig(name="sky130A", liberty="/foss/pdks/x.lib",
                       tech_lef="/t.tlef", cell_lef="/c.lef", cell_gds=None,
                       site="s", drc_deck=None)
    magic_cmds: list = []

    def fake(container, cmd, timeout=0, **_kw):
        if cmd.startswith("command -v") or cmd.startswith("test -f"):
            return (0, "", "")
        if "magic" in cmd and "SPICE_OUT=" in cmd:
            magic_cmds.append(cmd)
            sp = Path(re.search(r"SPICE_OUT=(\S+)", cmd).group(1))
            sp.parent.mkdir(parents=True, exist_ok=True)
            (sp.parent / "ext2spice.log").write_text(magic_log)
            if magic_writes_netlist:
                sp.write_text(".subckt chip_top a b\n.ends\n")
            # magic exits 0 either way — that is the whole point of D2.
            return (0, magic_log, "")
        if "netgen" in cmd:
            m = re.search(r"(\S+/lvs\.rpt)", cmd)
            if m:
                rpt = Path(m.group(1))
                rpt.parent.mkdir(parents=True, exist_ok=True)
                rpt.write_text("Netgen 1.5\n" + netgen_transcript)
            return (0, netgen_transcript, "")
        return (0, "", "")

    monkeypatch.setattr(P3, "_docker_exec", fake)
    monkeypatch.setattr(P3, "_to_container_path", lambda s, c: s)
    res = P3.step_lvs(tmp_path, "chip_top", pdk, "x")
    return Run(tmp_path, res, magic_cmds)


# ═══ D1 — what magic is actually handed ═══════════════════════════════════

def test_magic_is_never_handed_a_layerless_blockage(tmp_path, monkeypatch):
    """THE defect, reproduced at the step.

    On the unfixed tree the runner points magic at the signed-off DEF, so the
    `- PLACEMENT` entry that magic cannot bind is in the file it reads and the
    read aborts 3 times in 5. Asserted on the DEF TEXT the runner chose, not on
    any helper.
    """
    run = _drive(tmp_path, monkeypatch, DEF_MIXED)
    handed = run.def_text_handed_to_magic
    assert "PLACEMENT" not in handed, (
        "magic was handed a DEF still carrying a layer-less `- PLACEMENT` "
        "blockage; its DEF read aborts on that entry non-deterministically "
        "and LVS then has no netlist to compare\n"
        f"handed: {run.def_path_handed_to_magic}")


def test_the_conducting_blockages_survive_the_staging(tmp_path, monkeypatch):
    """Loss-free by construction: only the entries magic cannot bind go. A
    stripper that also dropped the LAYER entries would remove real geometry
    from the extraction input and quietly change the netlist."""
    run = _drive(tmp_path, monkeypatch, DEF_MIXED)
    handed = run.def_text_handed_to_magic
    assert "LAYER MET1 RECT ( 100 200 ) ( 300 400 ) ;" in handed
    assert "LAYER MET2 RECT ( 5 6 ) ( 7 8 ) ;" in handed
    # a stale count is itself a malformed DEF
    m = re.search(r"(?m)^\s*BLOCKAGES\s+(\d+)\s*;", handed)
    assert m and int(m.group(1)) == 2, handed
    assert handed.count("END BLOCKAGES") == 1


def test_nothing_outside_the_blockages_section_reaches_magic_changed(
        tmp_path, monkeypatch):
    """OVER-BREADTH GUARD — passes on e3aa9b126 too, and is meant to.

    On the unfixed tree magic gets the whole signed-off DEF, so every one of
    these survives trivially. Its job is to stop a future stripper from
    widening: it goes red the moment the staging touches anything outside
    BLOCKAGES."""
    run = _drive(tmp_path, monkeypatch, DEF_MIXED)
    handed = run.def_text_handed_to_magic
    for keep in ("VERSION 5.8 ;", "DESIGN chip_top ;",
                 "UNITS DISTANCE MICRONS 1000 ;",
                 "- u0 CELLA + PLACED ( 0 0 ) N ;",
                 "- VDD ( * VPWR ) + USE POWER ;",
                 "END SPECIALNETS", "END DESIGN"):
        assert keep in handed, keep


def test_the_section_disappears_when_every_entry_was_layerless(
        tmp_path, monkeypatch):
    run = _drive(tmp_path, monkeypatch, DEF_ONLY_LAYERLESS)
    handed = run.def_text_handed_to_magic
    assert "BLOCKAGES" not in handed, handed
    assert "- VDD ( * VPWR ) + USE POWER ;" in handed
    assert handed.rstrip().endswith("END DESIGN")


def test_the_signed_off_def_is_never_rewritten(tmp_path, monkeypatch):
    """The extraction copy is a NEW file. Rewriting the signed-off DEF would
    change what GDS, DRC and every other consumer reads on the strength of a
    magic-specific workaround."""
    run = _drive(tmp_path, monkeypatch, DEF_MIXED)
    assert run.signed_off_def.read_text() == DEF_MIXED
    assert run.def_path_handed_to_magic != run.signed_off_def


def test_the_staging_is_disclosed_beside_the_staged_copy(
        tmp_path, monkeypatch):
    """A silently-different extraction input is worse than none: the reader
    has to be able to see WHICH entries were dropped and why."""
    run = _drive(tmp_path, monkeypatch, DEF_MIXED)
    prov = run.provenance
    assert prov is not None, "no extract_def_provenance.json was written"
    assert prov["signed_off_def"] == str(run.signed_off_def)
    assert prov["extraction_def"] == str(run.def_path_handed_to_magic)
    dropped = prov["dropped_blockage_entries"]
    assert len(dropped) == 1 and "PLACEMENT" in dropped[0], dropped
    assert "u_otp.u_macro" in dropped[0], dropped


# ── strict fall-through: a DEF magic can read is handed over as it is ──────
@pytest.mark.parametrize("def_text,label",
                         [(DEF_ALL_LAYER, "every blockage names a layer"),
                          (DEF_NO_BLOCKAGES, "no BLOCKAGES section at all")])
def test_an_unaffected_def_is_handed_to_magic_as_the_signed_off_file(
        tmp_path, monkeypatch, def_text, label):
    """No staging, no copy, no provenance record — a design that never had the
    problem must take byte-for-byte the path it took before.

    Passes on e3aa9b126 as well, necessarily: on that tree NO design gets a
    staged copy. It is the negative control for the four tests above, and its
    green is not evidence for them."""
    run = _drive(tmp_path, monkeypatch, def_text)
    assert run.def_path_handed_to_magic == run.signed_off_def, label
    assert run.def_text_handed_to_magic == def_text, label
    assert run.provenance is None, label


# ═══ D2 — the no-netlist verdict must not imply the tool was fine ═════════

def test_a_no_netlist_run_localises_the_abort_and_says_rc_is_not_evidence(
        tmp_path, monkeypatch):
    """MEASURED in the image: magic exits 0 even on a fatal `lef read` /
    `def read`. So the old detail — "produced no extracted netlist (rc=0)" —
    quoted the one number that carries no signal for this tool, and quoted it
    as though it did.

    Driven at the step: magic returns 0, writes no `.sp`, and its log stops
    after `PORTS_PROMOTED`. The published verdict must name the recipe's own
    completion sentinel and where the run stopped.
    """
    run = _drive(
        tmp_path, monkeypatch, DEF_ALL_LAYER, magic_writes_netlist=False,
        magic_log=("Reading LEF ...\nPORTS_PROMOTED\n"
                   "ext2spice: something (Error): boom\n"))
    res, verdict = run.result, run.verdict
    assert res.status == "FAIL"
    assert res.extras.get("finding") == "LVS_EXTRACTION_NO_NETLIST"
    # the sentinel is REPORTED, and reported as absent
    assert res.extras.get("magic_completion_sentinel") is False, res.extras
    assert verdict is not None and verdict.get(
        "magic_completion_sentinel") is False, verdict
    # ...and the abort is localised to AFTER port promotion
    stage = res.extras.get("magic_aborted_stage") or ""
    assert "AFTER port promotion" in stage, stage
    assert verdict.get("magic_aborted_stage") == stage
    # the message must stop letting rc=0 stand for "the tool was fine"
    assert "MAGIC_EXT2SPICE_DONE" in res.detail, res.detail
    assert "not evidence" in res.detail, res.detail


def test_an_abort_before_port_promotion_is_a_different_stage(
        tmp_path, monkeypatch):
    """The localisation has to actually depend on the log. A field that always
    says the same thing localises nothing — so the same run with the log
    stopping EARLIER must report the earlier stage."""
    early = _drive(tmp_path / "a", monkeypatch, DEF_ALL_LAYER,
                   magic_writes_netlist=False,
                   magic_log="Reading LEF ...\ndef read (Error): boom\n")
    late = _drive(tmp_path / "b", monkeypatch, DEF_ALL_LAYER,
                  magic_writes_netlist=False,
                  magic_log="Reading LEF ...\nPORTS_PROMOTED\nboom\n")
    e = early.result.extras.get("magic_aborted_stage") or ""
    l = late.result.extras.get("magic_aborted_stage") or ""
    assert "BEFORE port promotion" in e, e
    assert e != l, (e, l)


def test_a_completed_recipe_that_wrote_nothing_is_not_called_an_abort(
        tmp_path, monkeypatch):
    """Over-breadth guard. If the sentinel IS present the recipe ran to the
    end, and saying it "aborted" would be a fabricated diagnosis."""
    run = _drive(tmp_path, monkeypatch, DEF_ALL_LAYER,
                 magic_writes_netlist=False,
                 magic_log="PORTS_PROMOTED\nMAGIC_EXT2SPICE_DONE\n")
    assert run.result.extras.get("magic_completion_sentinel") is True
    stage = run.result.extras.get("magic_aborted_stage") or ""
    assert "abort" not in stage.lower(), stage


# ═══ the shared pipefail repair — passes on BOTH trees, and says so ═══════

def test_magic_pipeline_does_not_let_tee_mask_the_exit_status():
    """PRE-EXISTING GUARD, not a pin on this landing.

    The repair this asserts landed one layer down, in
    `_tool_status_not_the_log_sinks`, which every `_docker_exec` command passes
    through — and it was already on the tree before 41c49f94d. This test
    therefore PASSES on e3aa9b126 as well as on b85d68acc and discriminates
    nothing here. It is kept because the property is real and unguarded
    elsewhere in this file's subject area, and it is labelled so nobody reads
    its green as evidence for the blockage fix.
    """
    guarded = P3._tool_status_not_the_log_sinks(
        "magic -dnull -noconsole -rcfile rc t.tcl 2>&1 | tee ext2spice.log")
    assert guarded.startswith("set -o pipefail; "), guarded
    # ...and it is the PIPELINE that gets it: a command with no log sink is
    # left exactly as it was, so this is not a blanket shell-option change.
    assert P3._tool_status_not_the_log_sinks("magic t.tcl") == "magic t.tcl"
