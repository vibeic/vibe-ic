"""`L21.fields.hard_macro_supplies` had three consumers and no producer.

`hardmacro_supply_intent`, `ip_integration_check` and `nvm_program_supply_intent`
all read the (master, pin) -> rail binding; nothing wrote it before the macro
abstracts exist, so two acceptance rounds of a mixed-signal cell declared it BY
HAND from the design's own sentences. `l21_hard_macro_supply_bind` reads the
same sentences: the interface declaration (`.subckt`) for the pins, the rails
the two rail producers already declared, and the per-block spec table rows.

Every rule below was written from that cell's documents, stated generically:
  * a pin binds when its row names ONE declared rail in the spec cell or at
    the head of the note, and the stated voltage agrees;
  * a rail named only in the body of the note is a relation, not a binding
    (an LDO OUTPUT row says "regulated CORE for ..." — it does not take CORE);
  * a ground-named pin with no declared ground rail is a DECLARED GAP;
  * a placeholder the LEF producer wrote (rail == pin name) yields to the
    documents; any other existing entry is left byte-identical.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import l21_hard_macro_supply_bind as mod  # noqa: E402

L5 = """\
# L5 — Analog spec

## Block A — `dsm` : modulator (x6)
| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| Order | 2 | 1-3 | — | loop order |
| Vin (diff) | 1.0 | 0-1.2 | V | input range vs VHI/VLO |
| Vdd (core) | 1.2 | 1.1-1.3 | V | core supply (one copy from the LDO) |
| output | 1-bit | — | — | bitstream |

## Block B — `reg` : regulator (x1)
| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| Vout | 1.2 | 1.1-1.3 | V | regulated CORE for the LDO-fed modulator copy |
| Vin | 1.8 | 1.6-2.0 | V | IOVDD (confirmed top pin) |
| Dropout | ≤ 0.5 | — | V | headroom (1.8 IOVDD − 1.2 CORE = 0.6 V available) |
"""

SP = """\
* interface declaration
.subckt dsm vdd vss vin vrefp clk bit_out
.ends dsm
.subckt reg vin vss vref vout
.ends reg
"""


def _l21(rails=(("CORE", 1.2), ("IOVDD", 1.8)), extra=None, hms=None):
    doms = [{"name": n, "power_net": n, "voltage_v": v,
             "derived_by": "l21_doc_supply_rail_synth"} for n, v in rails]
    doms += list(extra or [])
    f = {"power_domains": doms}
    if hms is not None:
        f["hard_macro_supplies"] = hms
    return {"layer": "L21", "fields": f}


def _project(tmp_path, l21, l5=L5, sp=SP):
    (tmp_path / "input" / "docs").mkdir(parents=True)
    (tmp_path / "input" / "interfaces").mkdir(parents=True)
    (tmp_path / "input" / "docs" / "L5_ANALOG_SPEC.md").write_text(l5)
    (tmp_path / "input" / "interfaces" / "analog_blocks.sp").write_text(sp)
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    (d / "L21_POWER_INTENT.json").write_text(json.dumps(l21))
    return tmp_path


def _run(tmp_path, apply=True):
    args = [str(tmp_path), "--json", str(tmp_path / "out.json")]
    if apply:
        args.append("--apply")
    rc = mod.main(args)
    res = json.loads((tmp_path / "out.json").read_text())
    l21 = json.loads((tmp_path / "phase1" / "generated_docs"
                      / "L21_POWER_INTENT.json").read_text())
    return rc, res, l21


def _by_pin(res):
    return {(p["master"], p["pin"]): p for p in res["pins"]}


# ── the producer exists, and binds what the documents bind ──────────────────
def test_the_key_now_has_a_producer(tmp_path):
    """THE bidirectional control: no entry before, the documents' entries
    after. Every earlier flow left this key absent."""
    rc, res, l21 = _run(_project(tmp_path, _l21()))
    assert rc == 0
    hms = l21["fields"]["hard_macro_supplies"]
    bound = {(e["master"], e["pin"]): e["rail"] for e in hms if "rail" in e}
    assert bound == {("dsm", "vdd"): "CORE", ("reg", "vin"): "IOVDD"}
    assert all(e["derived_by"] == mod.PROGRAM for e in hms)


def test_the_spec_cell_binds_and_cites_its_line(tmp_path):
    rc, res, _ = _run(_project(tmp_path, _l21()), apply=False)
    p = _by_pin(res)[("dsm", "vdd")]
    assert p["status"] == "bound" and p["rail"] == "CORE"
    assert p["evidence"]["file"].endswith("L5_ANALOG_SPEC.md")
    assert "Vdd (core)" in p["evidence"]["matched_text"]
    assert "1.2 V agrees" in p["why"]


def test_the_head_of_the_note_binds(tmp_path):
    rc, res, _ = _run(_project(tmp_path, _l21()), apply=False)
    p = _by_pin(res)[("reg", "vin")]
    assert p["status"] == "bound" and p["rail"] == "IOVDD"
    assert "head" in p["why"]


# ── what it refuses ─────────────────────────────────────────────────────────
def test_a_rail_in_the_body_of_the_note_is_a_citation_not_a_binding(tmp_path):
    """The LDO's OUTPUT row says 'regulated CORE for the LDO-fed copy'. That
    is what the pin DOES to CORE, not what feeds it. Bound, it would declare a
    supply generator as a supply consumer."""
    rc, res, l21 = _run(_project(tmp_path, _l21()))
    p = _by_pin(res)[("reg", "vout")]
    assert p["status"] == "cited" and p["cited_rails"] == ["CORE"]
    assert ("reg", "vout") not in {(e["master"], e["pin"])
                                   for e in l21["fields"]["hard_macro_supplies"]}
    cites = l21["fields"]["hard_macro_supply_citations"]
    assert [(c["master"], c["pin"]) for c in cites] == [("reg", "vout")]


def test_a_stated_voltage_that_contradicts_the_rail_refuses(tmp_path):
    l5 = L5.replace("| Vdd (core) | 1.2 |", "| Vdd (core) | 3.3 |")
    rc, res, _ = _run(_project(tmp_path, _l21(), l5=l5), apply=False)
    p = _by_pin(res)[("dsm", "vdd")]
    assert p["status"] == "voltage_mismatch"
    assert "3.3" in p["why"] and "1.2" in p["why"]


def test_two_declared_rails_on_one_row_is_ambiguous(tmp_path):
    l5 = L5.replace("| Vin | 1.8 | 1.6-2.0 | V | IOVDD (confirmed top pin) |",
                    "| Vin | 1.8 | 1.6-2.0 | V | IOVDD or CORE (unclear) |")
    rc, res, _ = _run(_project(tmp_path, _l21(), l5=l5), apply=False)
    p = _by_pin(res)[("reg", "vin")]
    assert p["status"] == "ambiguous"
    assert set(p["cited_rails"]) == {"IOVDD", "CORE"}


def test_signal_pins_are_not_supplies(tmp_path):
    rc, res, _ = _run(_project(tmp_path, _l21()), apply=False)
    b = _by_pin(res)
    assert b[("dsm", "vin")]["status"] == "no_rail_named"
    assert b[("dsm", "clk")]["status"] == "no_row"
    assert b[("reg", "vref")]["status"] == "no_row"


# ── ground ──────────────────────────────────────────────────────────────────
def test_a_ground_pin_with_no_ground_rail_is_a_declared_gap(tmp_path):
    rc, res, l21 = _run(_project(tmp_path, _l21()))
    gaps = [e for e in l21["fields"]["hard_macro_supplies"]
            if e.get("integration_gap") is True]
    assert {(e["master"], e["pin"]) for e in gaps} == {("dsm", "vss"),
                                                       ("reg", "vss")}
    assert all("no return" in e["detail"] for e in gaps)


def test_a_ground_pin_binds_to_the_one_declared_ground_rail(tmp_path):
    gnd = {"name": "vss", "power_net": "CORE", "ground_net": "vss",
           "is_power_domain": False, "voltage_v": 0.0,
           "derived_by": "l21_macro_supply_rail_synth"}
    rc, res, l21 = _run(_project(tmp_path, _l21(extra=[gnd])))
    p = _by_pin(res)[("dsm", "vss")]
    assert p["status"] == "bound" and p["rail"] == "vss" and p["use"] == "GROUND"


# ── existing entries ────────────────────────────────────────────────────────
def test_an_existing_declaration_is_left_byte_identical(tmp_path):
    hand = {"master": "dsm", "pin": "vdd", "rail": "IOVDD",
            "evidence": {"file": "by hand"}}
    rc, res, l21 = _run(_project(tmp_path, _l21(hms=[hand])))
    hms = l21["fields"]["hard_macro_supplies"]
    assert hms[0] == hand
    assert res["already_declared"][0]["pin"] == "vdd"
    assert ("dsm", "vdd") not in {(e["master"], e["pin"])
                                  for e in res["bindings_added"]}


def test_a_lef_placeholder_yields_to_the_documents(tmp_path):
    """`l21_macro_supply_rail_synth` binds `vdd -> vdd` when the abstracts
    already exist: it says the pin IS a supply, not which rail feeds it."""
    ph = {"master": "dsm", "pin": "vdd", "rail": "vdd", "use": "POWER",
          "derived_by": "l21_macro_supply_rail_synth"}
    rc, res, l21 = _run(_project(tmp_path, _l21(hms=[ph])))
    hms = {(e["master"], e["pin"]): e for e in
           l21["fields"]["hard_macro_supplies"]}
    assert hms[("dsm", "vdd")]["rail"] == "CORE"
    assert hms[("dsm", "vdd")]["superseded_placeholder"]["rail"] == "vdd"
    assert res["placeholders_superseded"][0] == ph


# ── not applicable, honestly ────────────────────────────────────────────────
def test_no_interface_declaration_is_not_applicable(tmp_path):
    p = _project(tmp_path, _l21())
    (p / "input" / "interfaces" / "analog_blocks.sp").unlink()
    rc, res, l21 = _run(p)
    assert rc == 2
    assert res["verdict"] == "NOT_APPLICABLE_NO_INTERFACE_DECLARATION"
    assert "hard_macro_supplies" not in l21["fields"]


def test_no_declared_rail_is_not_applicable(tmp_path):
    rc, res, _ = _run(_project(tmp_path, _l21(rails=())))
    assert rc == 2
    assert res["verdict"] == "NOT_APPLICABLE_NO_DECLARED_RAIL"


def test_dry_run_writes_nothing(tmp_path):
    p = _project(tmp_path, _l21())
    before = (p / "phase1" / "generated_docs" / "L21_POWER_INTENT.json").read_text()
    rc, res, _ = _run(p, apply=False)
    after = (p / "phase1" / "generated_docs" / "L21_POWER_INTENT.json").read_text()
    assert rc == 0 and before == after and res["applied"] is False
