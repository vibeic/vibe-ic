import json







# --- D34 metric binding: per-clock sink reconciliation and planning targets ---

import hashlib
import uuid

import pytest

import _physical_current as current

LIBERTY = """
library (demo) {
  cell (DFF) { pin (CLK) { direction : input; clock : true; }
               pin (D) { direction : input; } pin (Q) { direction : output; }
               ff (IQ, IQN) { clocked_on : "CLK"; next_state : "D"; } }
  cell (DFFN) { pin (CLKN) { direction : input; clock : true; }
                pin (D) { direction : input; } pin (Q) { direction : output; }
                ff (IQ, IQN) { clocked_on : "!CLKN"; next_state : "D"; } }
  cell (LAT) { pin (E) { direction : input; } pin (D) { direction : input; }
               pin (Q) { direction : output; } latch (IQ, IQN) { enable : "E"; data_in : "D"; } }
  cell (BUF) { pin (A) { direction : input; timing () { related_pin : "A"; } }
               pin (Z) { direction : output; } }
  cell (PADIN) { pin (PAD) { direction : input; is_pad : true; } pin (PU) { direction : input; }
                 pin (Y) { direction : output; } }
  cell (AND2) { pin (A) { direction : input; } pin (B) { direction : input; }
                pin (Z) { direction : output; } }
}
"""


def _def(clock_b_driver="( PIN clkb )", extra=""):
    return f"""VERSION 5.8 ;
DESIGN chip_top ;
COMPONENTS 6 ;
    - u_pad PADIN + PLACED ( 0 0 ) N ;
    - u_buf BUF + PLACED ( 0 0 ) N ;
    - u_core/r\\[0\\] DFF + PLACED ( 0 0 ) N ;
    - u_core/r\\[1\\] DFFN + PLACED ( 0 0 ) N ;
    - u_core/l0 LAT + PLACED ( 0 0 ) N ;
    - u_and AND2 + PLACED ( 0 0 ) N ;
END COMPONENTS
PINS 3 ;
    - clka + NET clka + DIRECTION INPUT + USE SIGNAL ;
    - clkb + NET clkb + DIRECTION INPUT + USE SIGNAL ;
    - en + NET en + DIRECTION INPUT + USE SIGNAL ;
END PINS
NETS 5 ;
    - clka ( PIN clka ) ( u_pad PAD ) ;
    - ca ( u_pad Y ) ( u_buf A ) ;
    - cka ( u_buf Z ) ( u_core/r\\[0\\] CLK ) ( u_core/l0 E ) ;
    - clkb {clock_b_driver} ( u_core/r\\[1\\] CLKN ) ;
    - en ( PIN en ) ( u_and B ) ;{extra}
END NETS
END DESIGN
"""


SOURCES = {"clka": "clka", "clkb": "clkb"}
DOMAINS = {"clka": ["u_core/l0/E", "u_core/r[0]/CLK"], "clkb": ["u_core/r[1]/CLKN"]}




def _write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body, sort_keys=True))


def _rel(project, path):
    return {"path": str(path.relative_to(project)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _log(domains):
    lines = ["CLOCK_PLAN_NATIVE clka|24.0|clka", "CLOCK_PLAN_NATIVE clkb|24.0|clkb"]
    for name, pins in domains.items():
        lines += [f"CLOCK_PLAN_SINK {name}|{pin}" for pin in pins]
        lines.append(f"CLOCK_PLAN_SINK_COUNT {name}|{len(pins)}")
    return "\n".join([*lines, "CLOCK_PLAN_DONE", ""])


def _approved(project, relative, schema, payload, source):
    _write(project / relative, {"schema": schema, **payload, "approval": {
        "authority": "requirements_owner", 'approver': 'neutral-requirements-reviewer', "status": "APPROVED",
        "source_reference": _rel(project, project / source)}})








def test_clock_plan_sinks_closes_the_census_or_refuses():
    assert current.clock_plan_sinks(_log(DOMAINS), ["clka", "clkb"]) == DOMAINS
    with pytest.raises(ValueError, match="CLOCK_PLAN_SINK_CENSUS_INCOMPLETE"):
        current.clock_plan_sinks(_log(DOMAINS).replace("SINK_COUNT clka|2", "SINK_COUNT clka|3"),
                                 ["clka", "clkb"])
    with pytest.raises(ValueError, match="CLOCK_PLAN_SINK_CENSUS_INCOMPLETE"):
        current.clock_plan_sinks("CLOCK_PLAN_SINK clka|a/CLK\n", ["clka"])




































def test_native_liberty_pin_roles_keep_the_declared_directions():
    from _cdc_netlist import liberty_pin_roles
    roles = liberty_pin_roles(LIBERTY)
    assert {key: roles["PADIN"]["PAD"][key] for key in ("direction", "clock", "is_pad")} == {
        "direction": "input", "clock": False, "is_pad": True}
    assert roles["BUF"]["A"]["direction"] == "input"
    assert roles["BUF"]["Z"]["direction"] == "output"
