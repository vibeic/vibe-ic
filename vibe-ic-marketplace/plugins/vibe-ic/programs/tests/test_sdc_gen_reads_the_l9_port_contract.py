"""L9's port list has four key spellings and three direction spellings.
`sdc_gen` read ONE of each.

`l9_rtl_pin_consistency_check` — the gate that certifies the very same layer —
already reads the UNION of all four keys; its docstring records why (reading a
single key gave a correct RTL top NO verification, and field runs were
dual-writing the same pins into two keys to clear it). `sdc_gen` never got
that lesson, so on a layer written with the canonical `top_ports` it saw an
empty port list and emitted an SDC with no `set_input_delay` and no
`set_output_delay` at all — every I/O path unconstrained, silently.

The direction key splits the same way: records are written `{"name","dir",
"width"}`, and `sdc_gen` tested `port["mode"]`. A missing key is not
`"output"`, so EVERY port — including every output — went down the input
branch and got a `set_input_delay`. That artefact is worse than the empty one:
it is populated, it passes a presence check, and it constrains output ports as
inputs.

Both halves are asserted below, plus the controls that keep the change narrow.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

RTL = """\
module dut (
    input  wire        aclk,
    input  wire        arst_n,
    input  wire        s_valid,
    input  wire [7:0]  s_data,
    output wire        m_valid,
    output wire [7:0]  m_data
);
    reg [7:0] r;
    always @(posedge aclk) r <= s_data;
    assign m_valid = s_valid;
    assign m_data  = r;
endmodule
"""

PORTS = [
    {"name": "aclk",    "dir": "in",  "width": 1},
    {"name": "arst_n",  "dir": "in",  "width": 1},
    {"name": "s_valid", "dir": "in",  "width": 1},
    {"name": "s_data",  "dir": "in",  "width": 8},
    {"name": "m_valid", "dir": "out", "width": 1},
    {"name": "m_data",  "dir": "out", "width": 8},
]


def _project(tmp_path, l9_key, dir_key, nested=False):
    """A project whose L9 spells the port list with `l9_key` and the direction
    with `dir_key`. `nested` selects the schema-v2 `fields` wrapper. Everything
    else is identical across variants."""
    p = tmp_path / f"proj_{l9_key}_{dir_key}_{int(nested)}"
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (p / "phase2" / "stage1" / "rtl" / "dut.v").write_text(RTL)
    recs = [{"name": r["name"], dir_key: r["dir"], "width": r["width"]}
            for r in PORTS]
    l9 = {"top_module": "dut", l9_key: recs}
    (p / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"fields": l9} if nested else l9))
    (p / "phase1" / "generated_docs" / "L8_RTL_CONSTANTS.json").write_text(
        json.dumps({"clock_mhz": 50,
                    "clock_domains": [{"name": "aclk", "mhz": 50}]}))
    return p


def _emit(tmp_path, l9_key, dir_key, nested=False):
    p = _project(tmp_path, l9_key, dir_key, nested)
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "sdc_gen.py"), str(p),
         "--top-name", "dut", "--force"],
        capture_output=True, text=True, cwd=str(PROGRAMS))
    sdc = list(p.rglob("*.sdc"))
    text = sdc[0].read_text() if sdc else ""
    return text, r.stdout + r.stderr


def _ports_of(text, cmd):
    out = set()
    for line in text.splitlines():
        if line.strip().startswith(cmd):
            for tok in line.split("get_ports")[1:]:
                out.add(tok.split("{")[1].split("}")[0].strip())
    return out


# -- the defect, both halves ------------------------------------------------

def test_canonical_key_yields_io_delays(tmp_path):
    """`top_ports` is what the promoter writes. Reading only the legacy alias
    produced an SDC with zero I/O delays."""
    text, _ = _emit(tmp_path, "top_ports", "dir")
    assert "set_input_delay" in text, (
        "L9 declares 6 ports under the canonical key `top_ports`, yet the "
        "emitted SDC constrains no input path:\n" + text)
    assert "set_output_delay" in text, (
        "no output path constrained:\n" + text)


def test_output_ports_are_not_constrained_as_inputs(tmp_path):
    """The direction half. `m_valid`/`m_data` are outputs; they must never
    receive a `set_input_delay`."""
    text, _ = _emit(tmp_path, "top_ports", "dir")
    ins = _ports_of(text, "set_input_delay")
    outs = _ports_of(text, "set_output_delay")
    assert {"m_valid", "m_data"} <= outs, (
        "output ports missing from set_output_delay: got %r" % (outs,))
    assert not ({"m_valid", "m_data"} & ins), (
        "OUTPUT ports carry set_input_delay — the direction key was read "
        "under one spelling only: %r" % (ins,))


# -- controls: the change must be narrow ------------------------------------

def test_every_key_spelling_agrees(tmp_path):
    """All four alias spellings must produce the same role split. This is the
    control that the fix reads a UNION and did not merely swap one hard-coded
    key for another."""
    base = None
    for key in ("top_ports", "ports", "top_level_ports", "top_module_pins"):
        text, _ = _emit(tmp_path, key, "dir")
        got = (_ports_of(text, "set_input_delay"),
               _ports_of(text, "set_output_delay"))
        if base is None:
            base = got
        assert got == base, (
            "L9 key %r produced a different constraint set than the first "
            "spelling: %r vs %r" % (key, got, base))
    assert base and base[1], "no spelling produced any output delay"


def test_legacy_mode_spelling_still_works(tmp_path):
    """A layer written the OLD way (`top_module_pins` + `mode`) must keep
    constraining exactly as it did. This is the backwards control: the fix is
    additive, not a replacement."""
    p = _project(tmp_path, "top_module_pins", "mode")
    doc = p / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    d = json.loads(doc.read_text())
    for rec in d["top_module_pins"]:
        rec["mode"] = "output" if rec["mode"] == "out" else "input"
    doc.write_text(json.dumps(d))
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "sdc_gen.py"), str(p),
         "--top-name", "dut", "--force"],
        capture_output=True, text=True, cwd=str(PROGRAMS))
    assert r.returncode == 0, r.stdout + r.stderr
    text = list(p.rglob("*.sdc"))[0].read_text()
    assert {"m_valid", "m_data"} <= _ports_of(text, "set_output_delay")
    assert {"s_valid", "s_data"} <= _ports_of(text, "set_input_delay")


#: A top with a clock and reset and NO data path. `RTL` above has four data
#: ports, which the generator now recovers from the RTL surface even when L9
#: declares none — so it is the wrong fixture for "constrains no I/O path".
RTL_NO_IO = """\
module dut (
    input  wire        aclk,
    input  wire        arst_n
);
endmodule
"""


def test_empty_l9_still_emits_and_now_says_so(tmp_path):
    """A layer that declares NO ports is the design's problem, not this
    generator's — it must still emit (unchanged behaviour) but must no longer
    do it silently.

    FIXTURE CORRECTED: this used `RTL`, whose four data ports the generator
    recovers from the RTL surface, so the design was fully constrained and the
    condition under test never arose. The assertion was right and could not
    fire — #744 shipped it with no code that prints the diagnostic at all,
    which is how a test can be both correct and never green."""
    p = tmp_path / "empty"
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (p / "phase2" / "stage1" / "rtl" / "dut.v").write_text(RTL_NO_IO)
    (p / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "dut"}))
    (p / "phase1" / "generated_docs" / "L8_RTL_CONSTANTS.json").write_text(
        json.dumps({"clock_mhz": 50}))
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "sdc_gen.py"), str(p),
         "--top-name", "dut", "--force"],
        capture_output=True, text=True, cwd=str(PROGRAMS))
    assert list(p.rglob("*.sdc")), "no SDC emitted at all"
    assert "constrains NO input or output path" in (r.stdout + r.stderr), (
        "an I/O-unconstrained SDC was emitted with no diagnostic:\n"
        + r.stdout + r.stderr)


def test_shared_accessor_is_the_one_reader():
    """The accessor lives in the shared contract module, so the next consumer
    inherits the union instead of re-declaring the key tuple a fourth time."""
    spec = importlib.util.spec_from_file_location(
        "ldcc", PROGRAMS / "l_doc_consumer_contract.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["ldcc"] = m
    spec.loader.exec_module(m)
    assert m.l9_top_ports({"top_ports": [{"name": "a"}],
                           "top_module_pins": [{"name": "b"}]}) == [
        {"name": "a"}, {"name": "b"}], "union+dedupe not honoured"
    assert m.l9_top_ports({"ports": [{"name": "a"}],
                           "top_ports": [{"name": "a"}]}) == [{"name": "a"}], \
        "same port under two keys must dedupe to one"
    assert m.l9_port_direction({"dir": "out"}) == "out"
    assert m.l9_port_direction({"mode": "output"}) == "out"
    assert m.l9_port_direction({"direction": "inout"}) == "inout"
    assert m.l9_port_direction({"name": "x"}) == "in", \
        "a record naming no direction must keep defaulting to input"


def test_schema_v2_nested_fields_is_read_too(tmp_path):
    """Schema v2 nests the payload under `fields`. A consumer reading only the
    top level sees an empty layer and cannot distinguish that from a design
    that declares no ports."""
    flat, _ = _emit(tmp_path, "top_ports", "dir", nested=False)
    nest, _ = _emit(tmp_path, "top_ports", "dir", nested=True)
    for text, label in ((flat, "flat"), (nest, "nested under `fields`")):
        assert {"m_valid", "m_data"} <= _ports_of(text, "set_output_delay"), (
            "%s L9 produced no output constraints:\n%s" % (label, text))
    assert _ports_of(flat, "set_input_delay") == \
        _ports_of(nest, "set_input_delay"), \
        "the two schema shapes must constrain the same ports"
