"""Which canonical steps each of the three delivery routes reaches.

OWNER RULING 2026-09-02: an IC runs BOTH 37.5ic and 37.5ip -- a die ships its
own IP deliverable set (LEF/Liberty/GDS/Verilog + the integration documents)
alongside its chip documents -- and only a pure-IP route skips 37.5ic.

Before that ruling was encoded, 37.5ip's condition was the single router
`NO_TEMPLATE.txt`, so a design declaring `deliverable=DIE` reached NEITHER
terminal's kit: MEASURED on spm x gf180mcuD at plugin 1.15.67, the run
recorded `Step 37.5ip ... condition not met: {'files_exist':
['input/submission_template/NO_TEMPLATE.txt']}`.

THE PIN. These tests read the shipped flow definition and assert, per route,
exactly which of the two terminals is reachable. They are a PIN in both
directions: widening 37.5ic to accept `NO_TEMPLATE.txt` (asking a pure IP for
a pad ring it has no die for) fails here just as loudly as narrowing 37.5ip
back to one router. The routers themselves stay mutually exclusive --
`tapeout_declaration_check` owns that and nothing here touches it.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

FLOW = (Path(__file__).resolve().parents[2]
        / "flow" / "phase1_phase2_phase3.yaml")

#: The three mutually-exclusive router artefacts step 0.5ic may write.
ROUTERS = {
    "IP": "input/submission_template/NO_TEMPLATE.txt",
    "SELF_TAPEOUT": "input/submission_template/SELF_TAPEOUT.txt",
    "SHUTTLE": "input/submission_template/slots/*.yaml",
}


def _steps():
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    out = {}
    for value in doc.values():
        if not isinstance(value, list):
            continue
        for step in value:
            if isinstance(step, dict) and "id" in step:
                out[str(step["id"])] = step
    return out


def _condition_routers(step):
    """The router paths this step's condition tests, and its any_of flag."""
    cond = step.get("condition") or {}
    files = cond.get("files_exist") or []
    return [str(f) for f in files], bool(cond.get("any_of"))


@pytest.fixture(scope="module")
def steps():
    found = _steps()
    for sid in ("0.5ic", "37.5ic", "37.5ip"):
        assert sid in found, f"step {sid} is not in {FLOW}"
    return found


class TestRouteReachability:
    @pytest.mark.parametrize("route", sorted(ROUTERS))
    def test_every_route_reaches_the_ip_deliverable_terminal(self, steps, route):
        """37.5ip is reachable on ALL THREE routes -- the ruling, encoded."""
        files, any_of = _condition_routers(steps["37.5ip"])
        assert any_of, ("37.5ip's condition must be `any_of`: the routers are "
                        "mutually exclusive, so an ALL-of reading over three "
                        "of them is reachable by nothing")
        assert ROUTERS[route] in files, (
            f"route {route} ({ROUTERS[route]}) does not reach 37.5ip; "
            f"condition names {files}")

    def test_the_chip_terminal_stays_chip_only(self, steps):
        """37.5ic must NOT accept the IP router.

        The other direction of the pin. A pure IP has no die, so asking it for
        a pad ring, a seal ring and a tape-out precheck is a refusal it can
        never answer -- this is the half that the widening above must not take
        with it.
        """
        files, any_of = _condition_routers(steps["37.5ic"])
        assert any_of, "37.5ic's condition must stay `any_of`"
        assert ROUTERS["IP"] not in files, (
            "37.5ic accepts the pure-IP router; a design with no die would be "
            f"asked for a pad ring. condition names {files}")
        for route in ("SELF_TAPEOUT", "SHUTTLE"):
            assert ROUTERS[route] in files, (
                f"chip route {route} no longer reaches 37.5ic: {files}")

    def test_the_route_owner_is_unchanged(self, steps):
        """Both terminals still hang off step 0.5ic's declaration.

        Holds in BOTH directions: it passed before the widening and must keep
        passing after, so the change cannot quietly re-home the condition.
        """
        for sid in ("37.5ic", "37.5ip"):
            owner = steps[sid].get("condition_owner") or {}
            assert str(owner.get("step")) == "0.5ic", (sid, owner)
            assert owner.get("declaration") == "delivery_route", (sid, owner)
            assert steps[sid].get("condition_kind") == "design_dependent", sid

    def test_step_0_5ic_still_declares_exactly_these_three_routers(self, steps):
        """The population this test parametrises over is the flow's own.

        Without this, adding a fourth router would leave the reachability
        tests above silently measuring a stale set of three.
        """
        declared = " ".join(str(o) for o
                            in (steps["0.5ic"].get("required_outputs") or []))
        for path in ROUTERS.values():
            assert path in declared, (
                f"{path} is not among step 0.5ic's required_outputs; the "
                "router population this module pins has moved")
