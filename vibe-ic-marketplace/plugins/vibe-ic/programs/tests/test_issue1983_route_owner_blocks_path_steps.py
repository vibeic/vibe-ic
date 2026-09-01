#!/usr/bin/env python3
"""Issue #1983 — an unresolved route is not the opposite delivery path.

The four path-dependent steps may use ``SKIPPED-CONDITION`` only after their
owner, Step 0.5ic, has resolved one authoritative route.  If the owner fails,
or if its mutually-exclusive declaration is missing/conflicting, every path
step is still owed an answer and is attributed to that upstream blocker.

The tests drive the public ``flow_compliance_check.main`` entry point over a
small neutral flow.  This is deliberate: the regression was in the roll-up,
not in any one path predicate, and a helper-only test could stay green while
the report continued to print four false skips.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(os.environ.get(
    "VIBEIC_CONTRACT_PROGRAMS",
    str(Path(__file__).resolve().parent.parent))).resolve()
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as FCC  # noqa: E402

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
import _hostpaths  # noqa: E402


PLUGIN = PROGRAMS.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

OWNER = "0.5ic"
PATH_STEPS = ("15.5ic", "26.5ic", "37.5ic", "37.5ip")
CHIP_STEPS = PATH_STEPS[:3]
ROUTES = {
    "chip": "input/route/SELF_CHIP.txt",
    "ip": "input/route/IP_DELIVERY.txt",
    "shuttle": "input/route/slots/*.yaml",
}


def _canonical_steps() -> dict[str, dict]:
    yaml = pytest.importorskip("yaml")
    return {str(s["id"]): s
            for s in yaml.safe_load(FLOW.read_text())["steps"]}


def _tiny_flow(*, owner_links: bool = True) -> dict:
    """Neutral five-row flow with the same route/owner shape as canonical."""
    declaration = {
        "exactly_one": True,
        "files_exist": [ROUTES["shuttle"], ROUTES["chip"], ROUTES["ip"]],
    }
    owner = {
        "id": OWNER,
        "name": "Delivery route declaration owner",
        "stage": "stage4",
        "condition_declarations": {"delivery_route": declaration},
        "required_outputs": [
            " OR ".join(declaration["files_exist"]),
            "reports/route_owner.json",
        ],
        "gate": {"json_field_true": {
            "file": "reports/route_owner.json",
            "field": "valid",
            "expect": True,
        }},
        "blocks_on": [],
    }

    def path_step(sid: str, files: list[str]) -> dict:
        step = {
            "id": sid,
            "name": f"Path-dependent step {sid}",
            "stage": "stage4",
            "condition": {"any_of": True, "files_exist": files},
            "condition_kind": "design_dependent",
            "required_outputs": [f"outputs/{sid}/done.json"],
            "blocks_on": [OWNER],
        }
        if owner_links:
            step["condition_owner"] = {
                "step": OWNER,
                "declaration": "delivery_route",
            }
        return step

    steps = [owner]
    steps.extend(path_step(sid, [ROUTES["shuttle"], ROUTES["chip"]])
                 for sid in CHIP_STEPS)
    steps.append(path_step("37.5ip", [ROUTES["ip"]]))
    return {"stages": [{"id": "stage4", "name": "route"}], "steps": steps}


def _run(tmp_path: Path, *, routes: tuple[str, ...], owner_valid: bool,
         owner_links: bool = True) -> tuple[int, dict]:
    yaml = pytest.importorskip("yaml")
    project = tmp_path / "project"
    project.mkdir(parents=True)
    for route in routes:
        rel = ROUTES[route]
        if "*" in rel:
            path = project / rel.replace("*.yaml", "slot_a.yaml")
        else:
            path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"route={route}\n")
    owner_report = project / "reports/route_owner.json"
    owner_report.parent.mkdir(parents=True, exist_ok=True)
    owner_report.write_text(json.dumps({"valid": owner_valid}) + "\n")

    flow = tmp_path / "flow.yaml"
    flow.write_text(yaml.safe_dump(_tiny_flow(owner_links=owner_links),
                                   sort_keys=False))
    out = tmp_path / "flow_report.json"
    rc = FCC.main([
        str(project), "--flow-def", str(flow), "--stage", "4",
        "--skip-yosys-gates", "--json", str(out),
    ])
    return rc, json.loads(out.read_text())


def _rows(report: dict) -> dict[str, dict]:
    return {str(row["id"]): row for row in report["steps"]}


def test_checked_in_flow_is_real_artefact_backing_for_the_route_contract():
    """The behavioural contract is also exercised against the shipped YAML."""
    yaml = pytest.importorskip("yaml")
    flow = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml")
    steps = {str(s["id"]): s for s in yaml.safe_load(flow.read_text())["steps"]}
    assert set(PATH_STEPS) < set(steps)
    assert OWNER in steps


def test_canonical_flow_names_one_route_owner_and_one_declaration():
    """Real checked-in artefact backing: no test-only route contract drift."""
    steps = _canonical_steps()
    owner = steps[OWNER]
    declaration = owner["condition_declarations"]["delivery_route"]
    assert declaration["exactly_one"] is True

    expected = set(owner["required_outputs"][0].split(" OR "))
    assert set(declaration["files_exist"]) == expected, (
        "the route declaration must be the same artefact set Step 0.5ic is "
        "required to produce")

    for sid in PATH_STEPS:
        assert steps[sid]["condition_owner"] == {
            "step": OWNER, "declaration": "delivery_route"}
        assert set(steps[sid]["condition"]["files_exist"]) <= expected


def test_unresolved_route_blocks_all_four_and_names_owner_verdict(tmp_path):
    rc, report = _run(tmp_path, routes=(), owner_valid=False)
    rows = _rows(report)
    assert rc == 1
    assert rows[OWNER]["status"] == "FAIL", rows[OWNER]

    for sid in PATH_STEPS:
        row = rows[sid]
        assert row["status"] == "MISSING", (sid, row)
        assert row["cascade_note"] == "blocked-by-upstream(0.5ic)"
        reason = " ".join(row["reasons"])
        assert "Step 0.5ic" in reason
        assert "verdict FAIL" in reason
        assert "delivery_route declaration is MISSING" in reason
        assert "design-derived N/A" in reason


@pytest.mark.parametrize(
    "route,expected_runs,expected_skips",
    [
        ("chip", set(CHIP_STEPS), {"37.5ip"}),
        ("ip", {"37.5ip"}, set(CHIP_STEPS)),
        ("shuttle", set(CHIP_STEPS), {"37.5ip"}),
    ],
)
def test_explicit_chip_ip_and_shuttle_keep_the_opposite_path_na(
        tmp_path, route, expected_runs, expected_skips):
    _, report = _run(tmp_path, routes=(route,), owner_valid=True)
    rows = _rows(report)
    assert rows[OWNER]["status"] == "PASS", rows[OWNER]
    assert {sid for sid in PATH_STEPS
            if rows[sid]["status"] == "SKIPPED-CONDITION"} == expected_skips
    assert {sid for sid in PATH_STEPS
            if rows[sid]["status"] == "MISSING"} == expected_runs
    for sid in expected_skips:
        assert not rows[sid].get("cascade_note"), rows[sid]


def test_failed_owner_blocks_even_when_one_route_file_exists(tmp_path):
    rc, report = _run(tmp_path, routes=("ip",), owner_valid=False)
    rows = _rows(report)
    assert rc == 1
    assert rows[OWNER]["status"] == "FAIL"
    for sid in PATH_STEPS:
        assert rows[sid]["status"] == "MISSING", (sid, rows[sid])
        reason = " ".join(rows[sid]["reasons"])
        assert "verdict FAIL" in reason
        assert "present as input/route/IP_DELIVERY.txt" in reason
        assert "not authoritative" in reason


def test_conflicting_routers_block_both_paths_instead_of_running_both(tmp_path):
    rc, report = _run(tmp_path, routes=("chip", "ip"), owner_valid=False)
    rows = _rows(report)
    assert rc == 1
    assert rows[OWNER]["status"] == "FAIL"
    for sid in PATH_STEPS:
        assert rows[sid]["status"] == "MISSING", (sid, rows[sid])
        reason = " ".join(rows[sid]["reasons"])
        assert "verdict FAIL" in reason
        assert "delivery_route declaration is CONFLICTING" in reason
        assert ROUTES["chip"] in reason and ROUTES["ip"] in reason


def test_removing_owner_distinction_reproduces_exactly_four_false_skips(
        tmp_path):
    """Mutation control: remove only the owner links, keep every predicate."""
    _, fixed = _run(tmp_path / "fixed", routes=(), owner_valid=False,
                    owner_links=True)
    _, mutated = _run(tmp_path / "mutated", routes=(), owner_valid=False,
                      owner_links=False)
    fixed_rows = _rows(fixed)
    mutated_rows = _rows(mutated)
    changed = {
        sid for sid in PATH_STEPS
        if fixed_rows[sid]["status"] != mutated_rows[sid]["status"]}
    assert changed == set(PATH_STEPS)
    assert {sid for sid in PATH_STEPS
            if mutated_rows[sid]["status"] == "SKIPPED-CONDITION"} == set(
                PATH_STEPS)
    assert all(fixed_rows[sid]["status"] == "MISSING" for sid in PATH_STEPS)
