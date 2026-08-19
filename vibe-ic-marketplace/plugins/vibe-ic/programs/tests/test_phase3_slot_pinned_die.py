#!/usr/bin/env python3
"""Step 0.5ic -> phase 3: the SLOT pins the die, and contradicting it is refused.

Every case here defends one measured fact. The measurement that started them:
the shuttle operator's own precheck container refused four layouts this flow
published, and `check_size.py` compares the layout bounding box to the slot
with `!=` on floats and no tolerance. All 8 published GDS missed every slot in
both dimensions; the closest filled 3.15% of the smallest one.

NEGATIVE CONTROL, deliberately: `test_no_report_leaves_die_to_the_flow` and
`test_declared_slot_absent_leaves_die_to_the_flow` are the cases that must NOT
change behaviour. A design with no shuttle target still owns its own die, and a
resolver that started pinning dies for those would be worse than the bug.
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner", str(_PROGRAMS / "phase3_one_shot_runner.py"))
_m = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("phase3_one_shot_runner", _m)
_spec.loader.exec_module(_m)

slot_geometry = _m._slot_declared_geometry


def _write(project: Path, ingest: dict) -> None:
    p = project / "reports" / "phase1"
    p.mkdir(parents=True, exist_ok=True)
    (p / "submission_template.json").write_text(json.dumps(
        {"schema": "submission_template/1",
         "program": "submission_template_ingest",
         "ingest": ingest}))


def _slot(name="slot_0p5x0p5", die=(0, 0, 1936, 2531),
          core=(442, 442, 1494, 2089)) -> dict:
    rec = {"slot": name,
           "source_relpath": f"librelane/slots/{name}.yaml",
           "source_sha256": "0" * 64,
           "die_area": {"key": "DIE_AREA", "raw": list(die)}}
    if core is not None:
        rec["core_area"] = {"key": "CORE_AREA", "raw": list(core)}
    return rec


def _ingested(slots, declared) -> dict:
    return {"status": "INGESTED", "declared_slot": declared,
            "slots": slots, "slots_shipped": [s["slot"] for s in slots]}


class SlotGeometry(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    # ---- the cases that must NOT change behaviour -----------------------
    def test_no_report_leaves_die_to_the_flow(self):
        self.assertIsNone(slot_geometry(self.project))

    def test_no_project_leaves_die_to_the_flow(self):
        self.assertIsNone(slot_geometry(None))

    def test_not_ingested_leaves_die_to_the_flow(self):
        _write(self.project, {"status": "NOT_APPLICABLE", "declared_slot": None,
                              "slots": []})
        self.assertIsNone(slot_geometry(self.project))

    def test_ingested_but_no_slot_declared_leaves_die_to_the_flow(self):
        _write(self.project, _ingested([_slot()], None))
        self.assertIsNone(slot_geometry(self.project))

    def test_unreadable_report_leaves_die_to_the_flow(self):
        p = self.project / "reports" / "phase1"
        p.mkdir(parents=True)
        (p / "submission_template.json").write_text("{ not json")
        self.assertIsNone(slot_geometry(self.project))

    # ---- the case the step exists for ----------------------------------
    def test_declared_slot_pins_die_and_core(self):
        _write(self.project, _ingested([_slot()], "slot_0p5x0p5"))
        got = slot_geometry(self.project)
        self.assertEqual(got["die_um"], "1936x2531")
        self.assertEqual(got["die_area"], [0, 0, 1936, 2531])
        self.assertEqual(got["core_area"], [442, 442, 1494, 2089])
        self.assertEqual(got["source_file"],
                         "librelane/slots/slot_0p5x0p5.yaml")
        self.assertNotIn("unusable", got)

    def test_the_right_slot_is_picked_from_several(self):
        slots = [_slot("slot_1x1", (0, 0, 3932, 5122), (442, 442, 3490, 4680)),
                 _slot("slot_0p5x0p5")]
        _write(self.project, _ingested(slots, "slot_1x1"))
        self.assertEqual(slot_geometry(self.project)["die_um"], "3932x5122")

    def test_core_area_absent_is_not_an_error(self):
        # A template may pin only the die. The runner then keeps its own core.
        _write(self.project, _ingested([_slot(core=None)], "slot_0p5x0p5"))
        got = slot_geometry(self.project)
        self.assertEqual(got["die_um"], "1936x2531")
        self.assertIsNone(got["core_area"])

    # ---- the refusals ---------------------------------------------------
    def test_declared_slot_not_in_the_list_is_refused_not_ignored(self):
        _write(self.project, _ingested([_slot()], "slot_1x1"))
        got = slot_geometry(self.project)
        self.assertIn("unusable", got)
        self.assertIn("0 slot record", got["unusable"])

    def test_two_records_for_one_slot_name_is_refused(self):
        _write(self.project, _ingested([_slot(), _slot()], "slot_0p5x0p5"))
        self.assertIn("unusable", slot_geometry(self.project))

    def test_non_integral_die_is_refused_not_rounded(self):
        # The operator compares with `!=`; half a database unit is a refusal.
        _write(self.project,
               _ingested([_slot(die=(0, 0, 1936.5, 2531))], "slot_0p5x0p5"))
        got = slot_geometry(self.project)
        self.assertIn("unusable", got)
        self.assertIn("integral", got["unusable"])

    def test_die_origin_not_at_zero_is_refused(self):
        # The operator's FIRST clause is the origin, before anything else.
        _write(self.project,
               _ingested([_slot(die=(10, 10, 1946, 2541))], "slot_0p5x0p5"))
        got = slot_geometry(self.project)
        self.assertIn("unusable", got)
        self.assertIn("(0, 0)", got["unusable"])

    def test_die_area_missing_is_refused(self):
        rec = _slot()
        rec.pop("die_area")
        _write(self.project, _ingested([rec], "slot_0p5x0p5"))
        self.assertIn("unusable", slot_geometry(self.project))

    def test_die_area_wrong_arity_is_refused(self):
        rec = _slot()
        rec["die_area"]["raw"] = [0, 0, 1936]
        _write(self.project, _ingested([rec], "slot_0p5x0p5"))
        self.assertIn("unusable", slot_geometry(self.project))


class NoOperatorLiteral(unittest.TestCase):
    """The resolver must carry no slot dimension of its own: every number it
    reports has to come out of the report it read. A literal here would be a
    second source of truth that nothing re-derives."""

    def test_resolver_source_names_no_slot_dimension(self):
        import inspect
        src = inspect.getsource(slot_geometry)
        for literal in ("1936", "2531", "3932", "5122", "3880", "5070", "26",
                        "60"):
            self.assertNotIn(literal, src,
                             f"{literal!r} is operator geometry and must be "
                             f"read, not carried")


if __name__ == "__main__":
    unittest.main()
