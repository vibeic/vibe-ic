"""Unit tests for `analog_a6_drc_attribute` — what each A6 violation IS.

The program drives Magic's sign-off deck inside an EDA container. These tests
need no container: `Stage` is the seam and a fake deck replays output captured
from a real run, so every branch of the attribution is exercised
deterministically.

The two arms that matter most are the ones that keep the program from becoming
a way to make violations disappear:

  * a DELIBERATELY DRAWN real violation must land in `LAYOUT` and the program
    must exit 1. A classifier that cannot fail is not a classifier.
  * the same violation, with a deviation record naming it exactly, must STILL
    land in `LAYOUT` and STILL exit 1. A producer that could clear its own
    DRC by writing itself a note would be marking its own homework.

Both were also measured end to end against the real deck; the numbers are
quoted in the tests that mirror them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path

import analog_a6_drc_attribute as A6A


M2B = "Metal2 spacing < 0.21um (M2.b)"
M2D = "Metal2 minimum area < 0.144um^2 (M2.d)"

# A layout with one placed child and two painted rectangles, in the shape
# Magic writes it.
LAYOUT = """magic
tech pdktech
timestamp 1
<< checkpaint >>
rect 0 0 100 100
use kid  d0
timestamp 1
transform 1 0 100 0 1 100
box -50 -50 50 50
<< metal2 >>
rect 500 500 540 540
rect 541 500 581 540
<< end >>
"""

CHILD = """magic
tech pdktech
timestamp 1
<< metal2 >>
rect -10 -10 10 10
<< end >>
"""


class FakeStage:
    """Replays a deck. Records every script it was asked to run."""

    def __init__(self, *, magic=True, open_ok=True, full=None, devonly=None,
                 solo=None, total=180, dev_total=58):
        self.path = "/stage"
        self.host_tmp = None
        self._magic, self._open_ok = magic, open_ok
        self.full = full if full is not None else []
        self.devonly = devonly if devonly is not None else []
        self.solo = solo if solo is not None else []
        self.total, self.dev_total = total, dev_total
        self.scripts: dict = {}
        self.staged: list = []

    def open(self):
        return (True, "") if self._open_ok else (False, "no container here")

    def put(self, src, name):
        self.staged.append(name)
        return True, ""

    def put_text(self, text, name):
        self.scripts[name] = text
        self.staged.append(name)
        return True, ""

    def get(self, name, dst):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        if name.startswith("a6solo"):
            Path(dst).write_text(
                "magic\ntech pdktech\ntimestamp 1\n<< checkpaint >>\n"
                "use kid  kid_0 some/where\ntimestamp 1\n"
                "transform 1 0 0 0 1 0\nbox -50 -50 50 50\n<< end >>\n")
            return True, ""
        return False, "no such file"

    def _dump(self, viol, total):
        return (f"A6TOTAL {total}\n"
                + "".join(f"V|{r}|{b[0]} {b[1]} {b[2]} {b[3]}\n"
                          for r, b in viol))

    def sh(self, cmd, timeout=900):
        if cmd.startswith("command -v magic"):
            return (0, "/bin/magic\n", "") if self._magic else (1, "", "")
        tag = re.search(r"(\S+)\.tcl$", cmd)
        name = tag.group(1) if tag else ""
        if name == "a6scale":
            return 0, "A6SCALE 200000 1 2\n", ""
        if name == "a6devonly":
            return 0, self._dump(self.devonly, self.dev_total), ""
        if name.startswith("a6solo"):
            return 0, self._dump(self.solo, len(self.solo)), ""
        return 0, self._dump(self.full, self.total), ""

    def close(self):
        pass


def _project(tmp_path: Path, *, deviations=None) -> Path:
    d = tmp_path / "proj" / "phase3" / "analog" / "blk"
    d.mkdir(parents=True)
    (d / "layout.mag").write_text(LAYOUT)
    (d / "kid.mag").write_text(CHILD)
    (d / "layout_provenance.json").write_text(json.dumps(
        {"producer": "analog_a5_layout_emit",
         "deviations": deviations or []}) + "\n")
    return tmp_path / "proj"


def _run(monkeypatch, project, stage, *extra):
    monkeypatch.setattr(A6A, "Stage", lambda container, host_tmp: (
        setattr(stage, "host_tmp", host_tmp) or stage))
    out = project / "a6.json"
    rc = A6A.main([str(project), "--block", "blk", "--container", "c",
                   "--json", str(out), *extra])
    return rc, (json.loads(out.read_text()) if out.is_file() else {})


# ══ the four populations are actually distinguished ══
def test_a_violation_the_bare_cell_reproduces_is_the_pdks_not_the_layouts(
        tmp_path, monkeypatch):
    """Proven, not inferred: the same rule at the same rectangle when the
    gencell is generated ALONE. Measured on u_hawaii_adc/ldo — the PDK's own
    `rppd` and its 20-finger pmos account for 66 violating rectangles under
    M2.d and CntB.h1 that no routing change can remove."""
    project = _project(tmp_path)
    # the child sits at (100,100); a solo violation at (-10,-10,10,10) in the
    # child's own frame is at (180,180,220,220) internal in the layout
    stage = FakeStage(solo=[(M2D, (-20, -20, 20, 20))],
                      full=[(M2D, (180, 180, 220, 220))], total=1)
    rc, doc = _run(monkeypatch, project, stage)
    assert doc["by_class"]["DEVICE_CELL"] == 1, doc["by_class"]
    assert doc["by_class"]["LAYOUT"] == 0
    assert rc == A6A.RC_DEVICE_ONLY
    assert "no routing change removes it" in doc["class_action"]["DEVICE_CELL"]


def test_a_violation_touching_the_flows_own_paint_is_the_layouts(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    # the layout paints metal2 at (500,500,540,540) lambda = (1000,1000,...)
    # internal; a violation there touches this flow's own paint
    stage = FakeStage(full=[(M2B, (1010, 1000, 1090, 1080))], total=1)
    rc, doc = _run(monkeypatch, project, stage)
    assert doc["by_class"]["LAYOUT"] == 1, doc["by_class"]
    assert rc == A6A.RC_LAYOUT_OWNS


def test_a_violation_the_stripped_placement_reproduces_is_the_placements(
        tmp_path, monkeypatch):
    """The same placement with every wire removed. A pure text transform of
    the layout's own file, so it needs no re-run of the producer."""
    far = (99000, 99000, 99040, 99040)
    project = _project(tmp_path)
    stage = FakeStage(full=[(M2D, far)], devonly=[(M2D, far)], total=1)
    rc, doc = _run(monkeypatch, project, stage)
    assert doc["by_class"]["DEVICE_PLACEMENT"] == 1, doc["by_class"]
    assert rc == A6A.RC_LAYOUT_OWNS   # not this flow's cell, still not clean


def test_a_violation_neither_control_reproduces_is_named_an_interaction(
        tmp_path, monkeypatch):
    """Magic re-checks a subcell's interior in the parent's context, so a
    cell that is clean standalone is not necessarily clean in place. That
    population gets its own name instead of being folded into either side."""
    project = _project(tmp_path)
    stage = FakeStage(full=[(M2D, (99000, 99000, 99040, 99040))], total=1)
    rc, doc = _run(monkeypatch, project, stage)
    assert doc["by_class"]["INTERACTION"] == 1, doc["by_class"]
    assert rc == A6A.RC_LAYOUT_OWNS


def test_the_stripped_placement_keeps_the_instances_and_drops_the_paint():
    out = A6A.devices_only(LAYOUT)
    assert "use kid" in out and "transform 1 0 100 0 1 100" in out
    assert "rect 500 500 540 540" not in out
    assert "<< metal2 >>" not in out


# ══ THE CONTROL: a real violation must still be caught, and a note is not a
#    waiver ══
INJECTED = (M2B, (600082, 600000, 600122, 600080))


def test_a_deliberately_drawn_violation_is_caught_and_refused(tmp_path,
                                                              monkeypatch):
    """Bidirectional control. MEASURED end to end against the real deck: two
    metal2 rectangles of different nets painted 1 lambda apart at
    (300000,300000) took the ldo's DRC from 180 to 182, landed in `LAYOUT`,
    and the program exited 1. A classifier that cannot fail is not one."""
    project = _project(tmp_path)
    # painted at the top level, so it touches this flow's own paint
    t = (project / "phase3" / "analog" / "blk" / "layout.mag")
    t.write_text(t.read_text().replace(
        "<< metal2 >>\n",
        "<< metal2 >>\nrect 300000 300000 300040 300040\n"
        "rect 300041 300000 300081 300040\n"))
    stage = FakeStage(full=[INJECTED], total=1)
    rc, doc = _run(monkeypatch, project, stage)
    assert doc["by_class"]["LAYOUT"] == 1, doc["by_class"]
    assert rc == A6A.RC_LAYOUT_OWNS
    assert doc["result"] == "LAYOUT_OWNS"


def test_a_deviation_that_names_the_violation_exactly_does_not_clear_it(
        tmp_path, monkeypatch):
    """The anti-cheat, and the reason `covered_by_deviation` is a separate
    field rather than a class. MEASURED against the real deck: adding a
    deviation whose `detail` names the injected rectangles verbatim left the
    class `LAYOUT`, the exit code 1 and the count 182 exactly as they were —
    only the annotation changed."""
    project = _project(tmp_path, deviations=[{
        "device": "cheat", "quantity": "metal2_space_lambda",
        "required": 21, "achieved": 1, "shortfall": 20, "adjudicator": "A6",
        "detail": "nets a and b are 1 lambda apart on metal2 at "
                  "(300000, 300000, 300040, 300040) / "
                  "(300041, 300000, 300081, 300040)"}])
    t = (project / "phase3" / "analog" / "blk" / "layout.mag")
    t.write_text(t.read_text().replace(
        "<< metal2 >>\n",
        "<< metal2 >>\nrect 300000 300000 300040 300040\n"
        "rect 300041 300000 300081 300040\n"))
    stage = FakeStage(full=[INJECTED], total=1)
    rc, doc = _run(monkeypatch, project, stage)
    assert rc == A6A.RC_LAYOUT_OWNS
    assert doc["by_class"]["LAYOUT"] == 1
    assert doc["findings"]["LAYOUT"][0]["covered_by_deviation"] is True
    assert "not a waiver" in doc["waiver_note"]


def test_the_recorded_deviations_are_read_but_never_change_a_class(
        tmp_path, monkeypatch):
    """Same violation, same class, with and without the record."""
    both = []
    for devs in ([], [{"quantity": "q", "detail":
                       "at (600041, 600000, 600061, 600040) / (1, 2, 3, 4)"}]):
        project = _project(tmp_path / f"p{len(both)}", deviations=devs)
        t = (project / "phase3" / "analog" / "blk" / "layout.mag")
        t.write_text(t.read_text().replace(
            "<< metal2 >>\n", "<< metal2 >>\nrect 600000 600000 600122 600080\n"))
        rc, doc = _run(monkeypatch, project, FakeStage(full=[INJECTED],
                                                       total=1))
        both.append((rc, doc["by_class"]))
    assert both[0] == both[1], both


# ══ the measurement itself must not be able to answer 0 by accident ══
def test_the_deck_script_selects_the_whole_cell_before_it_checks():
    """`drc check` works on the CURSOR BOX. MEASURED: a control script that
    loaded a cell and checked without `select top cell` first reported 0 for
    a gencell that in fact violates 6 rules — it had measured an empty box.
    Every script this program emits selects the cell first."""
    tcl = A6A._check_tcl("somecell")
    assert tcl.index("select top cell") < tcl.index("drc check")
    assert "drc list count total" in tcl


def test_a_layout_whose_children_are_missing_is_not_attributed(tmp_path,
                                                                monkeypatch):
    """A Magic layout is a cell hierarchy. MEASURED: with the children absent
    Magic prints `couldn't be read` / `Failure to read in entire subtree` and
    then answers `drc list count total` = 0 — a clean verdict on a layout it
    never loaded. That must never reach a caller as `DEVICE_ONLY`."""
    project = _project(tmp_path)
    (project / "phase3" / "analog" / "blk" / "kid.mag").unlink()
    rc, doc = _run(monkeypatch, project, FakeStage())
    assert rc == A6A.RC_NOT_ATTRIBUTED
    assert doc["result"] == "NOT_ATTRIBUTED"
    assert "cell hierarchy" in doc["reason"]


def test_a_deck_that_reports_no_count_is_not_attributed(tmp_path,
                                                         monkeypatch):
    project = _project(tmp_path)
    stage = FakeStage()
    stage.sh = lambda cmd, timeout=900: (
        (0, "/bin/magic\n", "") if cmd.startswith("command -v")
        else (0, "A6SCALE 200000 1 2\n", "") if "a6scale" in cmd
        else (0, "magic said nothing useful\n", ""))
    rc, doc = _run(monkeypatch, project, stage)
    assert rc == A6A.RC_NOT_ATTRIBUTED
    assert "missing verdict is not a clean one" in doc["reason"]


@pytest.mark.parametrize("stage,tool,needle", [
    (FakeStage(open_ok=False), "docker/container", "container is not"),
    (FakeStage(magic=False), "magic", "not on PATH"),
])
def test_an_absent_capability_is_named_never_reported_as_clean(
        tmp_path, monkeypatch, stage, tool, needle):
    project = _project(tmp_path)
    rc, doc = _run(monkeypatch, project, stage)
    assert rc == A6A.RC_NOT_ATTRIBUTED
    assert doc["tool"] == tool and needle in doc["reason"]


def test_a_missing_layout_is_not_attributed_rather_than_clean(tmp_path,
                                                               monkeypatch):
    project = _project(tmp_path)
    (project / "phase3" / "analog" / "blk" / "layout.mag").unlink()
    rc, doc = _run(monkeypatch, project, FakeStage())
    assert rc == A6A.RC_NOT_ATTRIBUTED
    assert "A5 has not drawn this block" in doc["reason"]


# ══ the window comes from the deck's own words ══
def test_the_rule_distance_is_read_from_the_rules_own_message():
    assert A6A.rule_distance(M2B, 100, 25) == 21
    assert A6A.rule_distance("Metal1 spacing < 0.18um (M1.b)", 100, 25) == 18
    # a different grid gives a different lambda count for the same rule
    assert A6A.rule_distance(M2B, 200, 25) == 42


def test_a_rule_that_names_no_distance_falls_back_and_says_so(tmp_path,
                                                               monkeypatch):
    project = _project(tmp_path)
    stage = FakeStage(full=[("Some rule with no distance in it",
                             (99000, 99000, 99040, 99040))], total=1)
    rc, doc = _run(monkeypatch, project, stage)
    assert doc["window_fallback_rects"] == 1
    assert "the attribution is weaker for them" in doc["window_fallback_note"]


def test_both_units_are_reported_side_by_side_never_mixed(tmp_path,
                                                           monkeypatch):
    """Magic counts ERRORS; an attribution can only be made per violating
    RECTANGLE. Reporting one as the other is how 180 and 829 become the same
    sentence."""
    project = _project(tmp_path)
    stage = FakeStage(full=[(M2B, (1010, 1000, 1090, 1080))], total=180)
    rc, doc = _run(monkeypatch, project, stage)
    assert doc["drc_total"] == 180
    assert doc["violating_rects"] == 1
    assert "different measurements of the same run" in doc["unit_note"]


# ══ the runner asks, and A6 still decides ══
def test_the_runner_asks_for_the_attribution_at_a6_and_only_there(
        tmp_path, monkeypatch):
    """The attribution is ADVISORY. It is dispatched at A6, it is not
    dispatched anywhere else, and the StepResult's verdict comes from the A6
    gate exactly as it did before — the adjudicator keeps its own decision."""
    import inspect as _inspect
    import subprocess as _sp
    import analog_one_shot_runner as AOSR
    import _progress_run as _real_pr

    seen = []

    # FAITHFUL DOUBLE — it must refuse exactly what the real collaborator
    # refuses. The previous stand-in was `def run(argv, **kw)`, which is MORE
    # PERMISSIVE than `_progress_run.run`: it silently swallowed a `timeout=`
    # that the real function has no parameter for. So this test stayed green
    # while the A6 dispatch raised `TypeError: run() got an unexpected keyword
    # argument 'timeout'` in production and killed the analog runner. A double
    # that accepts what the real thing refuses cannot fail.
    #
    # Binding the REAL signature — rather than rejecting one named keyword —
    # is deliberate: it is not a special case for `timeout`, so the NEXT
    # argument that drifts away from `_progress_run.run` is caught the same way.
    _REAL_RUN_SIG = _inspect.signature(_real_pr.run)

    class _Pr:
        @staticmethod
        def run(*args, **kw):
            _REAL_RUN_SIG.bind(*args, **kw)   # raises TypeError exactly as production does
            argv = args[0]
            seen.append(Path(argv[1]).name)
            return _sp.CompletedProcess(argv, 0, "PASS: gate\n", "")

    monkeypatch.setattr(AOSR, "_pr", _Pr())
    monkeypatch.setattr(AOSR, "_try_native_a6_pv",
                        lambda *a, **k: {"ran": False})
    proj = tmp_path / "proj"
    (proj / "phase3" / "analog" / "b").mkdir(parents=True)
    AOSR.step_for_block(proj, {"name": "b"}, "A6_block_pv", None)
    assert "analog_a6_drc_attribute.py" in seen, seen

    for other in ("A5_layout", "A7_post_layout_resim", "A9_hw_verify"):
        seen.clear()
        AOSR.step_for_block(proj, {"name": "b"}, other, None)
        assert "analog_a6_drc_attribute.py" not in seen, (other, seen)


def test_the_deviation_annotation_can_actually_match_what_a5_writes(tmp_path):
    """`covered_by_deviation` was false on every violation of every block.

    The producer writes its boxes with `list(...)`, so each detail reads
    `... at [43039, 58469, 43920, 58499] / [42639, 58516, 43964, 58546]`, and
    this reader's pattern accepted only `(...)`. It matched NOTHING A5 has
    ever written, so a violation A5 had recorded in the same run read as one
    A5 did not know about. Measured on the real `layout_provenance.json` of a
    294-device block: 0 boxes recovered before, 5788 after.
    """
    import json

    prov = {"deviations": [
        {"quantity": "metal3_space_lambda",
         "detail": "nets a and b are 17 lambda apart on metal3 at "
                   "[43039, 58469, 43920, 58499] / "
                   "[42639, 58516, 43964, 58546]"},
        {"quantity": "bulk_tap_clearance_lambda",
         "detail": "the best position clears by 7 lambda"},
    ]}
    (tmp_path / "layout_provenance.json").write_text(json.dumps(prov))
    got = A6A.recorded_deviation_boxes(tmp_path, 100)
    assert ("metal3_space_lambda", (43039, 58469, 43920, 58499)) in got
    assert ("metal3_space_lambda", (42639, 58516, 43964, 58546)) in got
    assert len(got) == 2, got
