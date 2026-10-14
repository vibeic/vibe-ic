"""The two L10 cases that need nothing delivered get a real oracle.

MEASURED on subservient x gf180mcuD as a DIE, FRONT DOOR, run r48 (lane
icsub2, host 8HD-4, tree 41d3b39b8, image 0.3.67 sha256:4e9f54ef): 1 of 10
declared L10 cases executed its own oracle. `reset_assert_sram` and
`i_rst_glitch_instruction_fetch_race` need NO delivered program — they are
properties over the design's own declared observables — and fell to the
substance-floor scaffold only because the flow owned an emitter for one
property family (the "within N cycles of reset release" convention, which is
why `reset_n_cycle_instruction` was the single case that ran) and none for
the reset-ASSERT family. R-0915-102(2).

MEASURED end-to-end with iverilog in the pinned image, on the real declared
cases and the real DUT port surface (observed outputs picked structurally:
`o_sram_we` for the hold family, `o_sram_cyc` for the glitch family):

    arm                                   reset_assert_sram   glitch
    shipped RTL (registered boundary)     PASS                PASS
    mutant (reset branch drives it to 1)  FAIL (32 checks)    FAIL (1 check)
    pre-R-0915-99 combinational boundary  PASS                FAIL (1 check)

The mutant arm is what makes these oracles evidence rather than decoration.
The third arm is not a claim about the registered-boundary change — the hold
invariant holds in both revisions — but it does show the glitch oracle
catching a combinational control boundary on its own.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reset_invariant_oracle_tb_gen as R  # noqa: E402
import testbench_gen as T  # noqa: E402

_IN = [("i_clk", ""), ("i_rst", ""), ("i_sram_data", "[7:0]")]
_OUT = [("o_sram_addr", "[9:0]"), ("o_sram_data", "[7:0]"),
        ("o_sram_we", ""), ("o_sram_cyc", ""), ("o_gpio", "")]

_HOLD = {"name": "reset_assert_sram", "kind": "functional_vector",
         "stimulus": "Reset assert 中 SRAM 內容保留",
         "expected": "holds: Reset assert 中 SRAM 內容保留"}
_GLITCH = {"name": "i_rst_glitch_instruction_fetch_race",
           "kind": "functional_vector",
           "stimulus": "i_rst glitch 不應導致 instruction fetch race",
           "expected": "holds: i_rst glitch 不應導致 instruction fetch race"}


def test_each_case_is_claimed_by_exactly_its_own_family():
    assert R.case_family(_HOLD) == R.FAMILY_HOLD
    assert R.case_family(_GLITCH) == R.FAMILY_GLITCH


def test_the_release_side_family_is_not_claimed():
    """The boot-latency emitter owns "within N cycles of reset RELEASE"."""
    boot = {"name": "reset_n_cycle_instruction",
            "stimulus": "Reset 解除後 N cycle 內取得第一條指令",
            "expected": "第一個 bus access 在 10 cycle 內"}
    assert R.case_family(boot) is None


def test_an_unrelated_case_grounds_nothing():
    for c in ({"name": "blinky_hex", "stimulus": "blinky.hex",
               "expected": "GPIO 輸出規則性 toggle"},
              {"name": "rv32i_40", "stimulus": "整套 RV32I 指令",
               "expected": "100% PASS"}):
        assert R.case_family(c) is None
        assert R.emit_case_oracle_from_ports(c, "dut", _IN, _OUT, []) is None


def test_a_case_that_reads_as_both_is_refused():
    both = {"name": "x",
            "stimulus": "Reset assert 中 SRAM 內容保留; i_rst glitch",
            "expected": "不應導致 instruction fetch race"}
    assert R.case_family(both) is None


def test_the_hold_oracle_watches_the_write_output():
    tb = R.emit_case_oracle_from_ports(_HOLD, "subservient", _IN, _OUT, [])
    assert "o_sram_we" in tb
    assert "RESET_ASSERT_HOLD" in tb
    assert "$fatal(1);" in tb, "a check that cannot fail is not an oracle"
    assert "@(negedge i_clk);" in tb, "sample mid-cycle, never on the edge"


def test_the_glitch_oracle_watches_the_bus_activity_output():
    tb = R.emit_case_oracle_from_ports(_GLITCH, "subservient", _IN, _OUT, [])
    assert "o_sram_cyc" in tb
    assert "RESET_GLITCH_NO_RACE" in tb
    assert "$fatal(1);" in tb
    # the window closes when reset is released: ordinary resumption after a
    # glitch is not a race, and an earlier draft that stayed open past the
    # release FAILed the shipped design for restarting.
    i_check = tb.index("asserted inside the reset glitch")
    i_release = tb.index("i_rst = 1'b0;", i_check)
    assert i_release > i_check


def test_no_reset_port_grounds_nothing():
    ports = [("i_clk", "")]
    assert R.emit_case_oracle_from_ports(_HOLD, "dut", ports, _OUT, []) is None


def test_no_clock_grounds_nothing():
    assert R.emit_case_oracle_from_ports(
        _HOLD, "dut", [("i_rst", "")], _OUT, []) is None


def test_no_observable_output_grounds_nothing():
    """A DUT surface with nothing to watch defers to the scaffold."""
    outs = [("o_gpio", ""), ("o_led", "")]
    assert R.emit_case_oracle_from_ports(_HOLD, "dut", _IN, outs, []) is None
    assert R.emit_case_oracle_from_ports(_GLITCH, "dut", _IN, outs, []) is None


def test_an_active_low_reset_is_driven_the_right_way_round():
    ins = [("clk", ""), ("rst_n", ""), ("din", "[7:0]")]
    tb = R.emit_case_oracle_from_ports(_HOLD, "dut", ins, _OUT, [])
    assert "rst_n = 1'b0;" in tb, "asserted is LOW for an active-low reset"


def test_the_emitter_is_wired_into_the_producer_and_names_itself(tmp_path):
    out = tmp_path / "tb"
    out.mkdir()
    ports = [("input", w, n) for n, w in _IN] + \
            [("output", w, n) for n, w in _OUT]
    got = T._emit_case_reset_invariant_oracle(
        tmp_path, _HOLD, "subservient", ports, out, {})
    assert got == out / "reset_assert_sram.v"
    text = got.read_text()
    assert T.ORACLE_GENERATED_MARKER in text
    assert "_emit_case_reset_invariant_oracle" in text


def test_the_producer_defers_when_the_case_is_not_ours(tmp_path):
    out = tmp_path / "tb"
    out.mkdir()
    ports = [("input", w, n) for n, w in _IN] + \
            [("output", w, n) for n, w in _OUT]
    assert T._emit_case_reset_invariant_oracle(
        tmp_path, {"name": "blinky_hex", "stimulus": "blinky.hex",
                   "expected": "toggle"}, "subservient", ports, out, {}) is None
    assert list(out.iterdir()) == []


def test_work_already_authored_is_not_clobbered(tmp_path):
    out = tmp_path / "tb"
    out.mkdir()
    (out / "reset_assert_sram.v").write_text("module authored; endmodule\n")
    ports = [("input", w, n) for n, w in _IN] + \
            [("output", w, n) for n, w in _OUT]
    got = T._emit_case_reset_invariant_oracle(
        tmp_path, _HOLD, "subservient", ports, out, {})
    assert "authored" in got.read_text()


# #3074: self-authored registered byte-memory INPUT and actual native producers.
import hashlib
import json
import resource
import shutil
import subprocess
import pytest
import _l10_execution as X
import l10_tb_conformance_check as C

CASE = {"name": "reset_content_retained", "kind": "functional_vector",
        "stimulus": "Reset assert retains external byte memory content, including the first sampled rising edge after an active pending write.",
        "expected": "Every actual storage byte remains unchanged throughout the complete reset assertion interval."}

DEBT = {"name": "independent_unimplemented_obligation", "kind": "functional_vector",
        "stimulus": "Check a separately declared unspecified data transaction", "expected": "The independent expected result remains owed."}

RTL = """module sample_store(input i_clk, input i_rst, input [7:0] i_store_rdata,
 output reg [2:0] o_store_raddr, output reg [2:0] o_store_waddr,
 output reg [7:0] o_store_wdata, output OWE o_store_we);
 reg [3:0] phase;
 PENDING
 always @(posedge i_clk) begin
  if(i_rst) begin phase <= 0; o_store_raddr <= 0; o_store_waddr <= 2; o_store_wdata <= 8'h3c; SETZERO end
  else begin phase <= phase + 1; o_store_raddr <= 2;
   if(phase == 2) begin SETONE o_store_waddr <= 2; o_store_wdata <= 8'h3c; end
   else begin SETZERO end
  end
 end
endmodule
"""

PORTS = [{"name": n,"direction":d,"width":w} for d,w,n in
 [("input",1,"i_clk"),("input",1,"i_rst"),("input",8,"i_store_rdata"),
 ("output",3,"o_store_raddr"),("output",3,"o_store_waddr"),("output",8,"o_store_wdata"),("output",1,"o_store_we")]]

DECL = {"top_module":"sample_store","clock_port_name":"i_clk","reset_polarity":"active_high",
        "sram_interface_protocol":"registered_dual_port_8bit_async_read_sync_write",
        "sram_interface":{"read_address":"o_store_raddr","write_address":"o_store_waddr",
            "write_data":"o_store_wdata","read_data":"i_store_rdata","write_enable":"o_store_we","read_latency_cycles":0}}

DIAGNOSTIC = """`timescale 1ns/1ps
module strict_pending_probe;
 reg i_clk=0, i_rst=1; wire [2:0] raddr,waddr; wire [7:0] wdata; wire we;
 reg [7:0] memory[0:7]; reg [7:0] snapshot[0:7]; wire [7:0] rdata=memory[raddr];
 sample_store dut(i_clk,i_rst,rdata,raddr,waddr,wdata,we);
 always #5 i_clk=~i_clk;
 // Real external-memory commit: previous registered transaction commits on
 // every rising edge, INCLUDING reset's first edge. Never gate on reset.
 always @(posedge i_clk) if(we===1'b1) memory[waddr] <= wdata;
 integer i,cycles; reg found; integer address; reg [7:0] before_byte,pending_data;
 initial begin
  for(i=0;i<8;i=i+1) memory[i]=8'ha5+i*17;
  repeat(4) @(negedge i_clk); i_rst=0; found=0;
  for(cycles=0;cycles<64 && !found;cycles=cycles+1) begin
   @(negedge i_clk);
   if(we===1'b1 && memory[waddr]!==wdata) found=1;
  end
  if(!found) $fatal(1,"no non-idempotent pending transaction; retention NOT_MEASURED");
  address=waddr; before_byte=memory[waddr]; pending_data=wdata;
  for(i=0;i<8;i=i+1) snapshot[i]=memory[i];
  $display("PENDING address=%0d before=%02x data=%02x",address,before_byte,pending_data);
  i_rst=1;
  @(posedge i_clk); @(negedge i_clk);
  $display("FIRST_EDGE address=%0d before=%02x after=%02x post_edge_we=%b",address,before_byte,memory[address],we);
  for(i=0;i<8;i=i+1) if(memory[i]!==snapshot[i]) begin
   $display("STRICT_RETENTION FAIL edge=0 byte=%0d before=%02x after=%02x",i,snapshot[i],memory[i]);
   $fatal(1);
  end
  repeat(5) begin @(posedge i_clk); @(negedge i_clk);
   for(i=0;i<8;i=i+1) if(memory[i]!==snapshot[i]) $fatal(1,"later reset byte changed");
  end
  $display("STRICT_RETENTION PASS bytes=8 edges=6 including_first_edge=1"); $finish;
 end
endmodule
"""

def bounded():
 resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,4*1024**3))
 resource.setrlimit(resource.RLIMIT_CORE,(0,0))

def execute(argv,cwd,timeout=120):
 p=subprocess.run([str(a) for a in argv],cwd=cwd,capture_output=True,text=True,timeout=timeout,preexec_fn=bounded)
 return p.returncode,(p.stderr or "")+(p.stdout or "")

def dispatch(argv,cwd,container,tool,timeout):
 argv=list(argv)
 if '-j' in argv: argv[argv.index('-j')+1]='1'
 return execute(argv,cwd,timeout)

def prepare(root,good=False):
 for d in ['phase1/generated_docs','phase2/stage1/rtl','plugin_output','input/docs']:(root/d).mkdir(parents=True,exist_ok=True)
 s=RTL.replace('OWE','wire' if good else 'reg').replace('PENDING',"reg pending; assign o_store_we = pending && !i_rst;" if good else '')
 s=s.replace('SETZERO','pending <= 0;' if good else 'o_store_we <= 0;').replace('SETONE','pending <= 1;' if good else 'o_store_we <= 1;')
 (root/'phase2/stage1/rtl/sample_store.v').write_text(s)
 docs=root/'phase1/generated_docs'
 for n,data in [('L1_DATASHEET.json',{'ic_class':'glue_logic'}),('L2_FRS.json',{'function':'registered external byte-store sequencer'}),('L3_CMD_PROTOCOL.json',{'opcodes':[]}),('L9_INTEGRATION_SPEC.json',{'top_module':'sample_store','top_ports':PORTS}),('L10_TEST_CASES.json',{'test_cases':[CASE,DEBT]})]:(docs/n).write_text(json.dumps(data,indent=2))
 (root/'plugin_output/declaration.json').write_text(json.dumps(DECL,indent=2))
 (root/'input/docs/retention.md').write_text('# Neutral external memory contract\n'+CASE['stimulus']+'\n'+CASE['expected']+'\nPorts and protocol: '+json.dumps(DECL)+'\n')
 return root/'phase2/stage1/rtl/sample_store.v'

def _retention_consumer(project):
 out = project / "consumer.json"
 rc = C.main(["--l10", str(project / "phase1/generated_docs/L10_TEST_CASES.json"),
              "--tb-dir", str(T._pl.sim_dir(project) / "tb"), "--project", str(project),
              "--out", str(out), "--strict"])
 return rc, json.loads(out.read_text())


def _retention_native(project, good=True, mutation=None, diagnostic=True):
 from not_verified_tier import skip_not_verified
 if any(shutil.which(tool) is None for tool in ("iverilog", "vvp", "verilator")):
  skip_not_verified("native reset retention needs Icarus and Verilator", "Run this module in the pinned EDA image")
 rtl = prepare(project, good)
 if mutation == "no_pending":
  rtl.write_text(rtl.read_text().replace("if(phase == 2)", "if(1'b0)"))
 elif mutation == "unsupported_width":
  rtl.write_text(rtl.read_text().replace("[2:0]", "[16:0]"))
 elif mutation in ("unsupported_protocol", "missing_role"):
  path = project / "plugin_output/declaration.json"
  decl = json.loads(path.read_text())
  if mutation == "unsupported_protocol": decl["sram_interface_protocol"] = "unstated_commit_convention"
  else: decl["sram_interface"].pop("write_address")
  path.write_text(json.dumps(decl))
 diagnostic_rc = None
 diagnostic_log = ""
 if diagnostic:
  tb = project / "strict_pending_probe.v"
  tb.write_text(DIAGNOSTIC)
  rc, log = execute(["iverilog", "-g2012", "-s", "strict_pending_probe", "-o", project / "strict.vvp", rtl, tb], project)
  assert rc == 0, log
  diagnostic_rc, diagnostic_log = execute(["vvp", project / "strict.vvp"], project)
  (project / "strict-run.log").write_text(diagnostic_log)
 generation = {}
 assert T.emit_unit_tbs(project, top="sample_store", report=generation,
                        scaffold=False, case_stated=True) == 1
 execution = {}
 T.run_unit_tbs(project, report=execution, dispatch=dispatch, container=None,
                build_timeout=120, run_timeout=30)
 rc, consumer = _retention_consumer(project)
 result = {"diagnostic_rc": diagnostic_rc, "diagnostic": diagnostic_log,
           "generation": generation, "execution": execution, "consumer_rc": rc,
           "consumer": consumer, "rtl_sha256": hashlib.sha256(rtl.read_bytes()).hexdigest()}
 (project / "native-retention-receipt.json").write_text(json.dumps(result, indent=2))
 return project, result


@pytest.fixture(scope="module")
def native_retention_good(tmp_path_factory):
 return _retention_native(tmp_path_factory.mktemp("retention_good"))


@pytest.fixture(scope="module")
def native_retention_bad(tmp_path_factory):
 return _retention_native(tmp_path_factory.mktemp("retention_bad"), good=False)


def _retention_row(consumer):
 return next(r for r in consumer["results"] if r["id"] == CASE["name"])


def _debt_stays_owed(consumer):
 debt = next(r for r in consumer["results"] if r["id"] == DEBT["name"])
 assert debt["status"] == "NOT_EXECUTED" and debt["pass"] is False
 assert debt["sim_executed"] is False and debt["waived"] is False


def test_registered_pending_first_edge_byte_change_is_failed_by_native_case(native_retention_bad):
 project, result = native_retention_bad
 assert result["diagnostic_rc"] == 1
 assert "FIRST_EDGE address=2 before=c7 after=3c post_edge_we=0" in result["diagnostic"]
 case = result["execution"]["cases"][0]
 assert case["state"] == "failed", case
 row = _retention_row(result["consumer"])
 assert row["status"] == "fail" and row["pass"] is False and row["sim_executed"] is True
 log = (Path(case["work_dir"]) / "run.log").read_text()
 assert "retention arm=1 edge=0 byte=2 before=c7 after=3c" in log
 assert "RESET_RETENTION SAMPLE arm=1 edge=0 bytes=a5b63cd8e9fa0b1c post_edge_we=0" in log
 assert result["consumer_rc"] == 1
 _debt_stays_owed(result["consumer"])


def test_strict_retention_positive_measures_actual_idle_and_pending_bytes(native_retention_good):
 _, result = native_retention_good
 assert result["diagnostic_rc"] == 0
 assert "FIRST_EDGE address=2 before=c7 after=c7 post_edge_we=0" in result["diagnostic"]
 row = _retention_row(result["consumer"])
 assert row["pass"] is True and row["status"] == "pass" and row["sim_executed"] is True
 case = result["execution"]["cases"][0]
 measured = (case.get("reset_retention") or {}).get("measurement")
 assert measured is not None and measured["complete"] is True and measured["changed"] is False
 assert measured["pending"] == {"address": 2, "before": "c7", "data": "3c"}
 assert measured["baselines"] == {"0": "a5b6c7d8e9fa0b1c", "1": "a5b6c7d8e9fa0b1c"}
 assert measured["samples"] == {a: {str(i): "a5b6c7d8e9fa0b1c" for i in range(6)} for a in ("0", "1")}
 assert result["consumer_rc"] == 1  # The independent unimplemented obligation still blocks.
 _debt_stays_owed(result["consumer"])


@pytest.mark.parametrize("mutation", ["unsupported_protocol", "missing_role", "unsupported_width", "no_pending"])
def test_unbound_or_unexercised_memory_protocol_is_native_not_measured(tmp_path, mutation):
 _, result = _retention_native(tmp_path, mutation=mutation, diagnostic=False)
 case = result["execution"]["cases"][0]
 assert case["state"] == "not_measured", case
 assert "NOT_MEASURED" in case["message"]
 row = _retention_row(result["consumer"])
 assert row["pass"] is False and row["status"] == "NOT_EXECUTED"
 assert row["sim_executed"] is False and row["waived"] is False
 if mutation == "no_pending":
  log = (Path(case["work_dir"]) / "run.log").read_text()
  assert "RESET_RETENTION PENDING" not in log, log
  assert "RESET_RETENTION BASELINE arm=1" not in log, log
  assert f"[TB {CASE['name']}] PASS" not in log, log
 _debt_stays_owed(result["consumer"])


@pytest.mark.parametrize("mutation", ["legacy_pass", "missing_execution", "missing_transcript", "changed_transcript",
                                      "missing_first_edge", "missing_bytes", "changed_rtl", "changed_declaration", "changed_tb"])
def test_retention_pass_requires_current_execution_protocol_and_actual_bytes(native_retention_good, mutation):
 project, original = native_retention_good
 record_path = X.record_path(project)
 case = original["execution"]["cases"][0]
 transcript = Path(case["work_dir"]) / "run.log"
 rtl = project / "phase2/stage1/rtl/sample_store.v"
 decl = project / "plugin_output/declaration.json"
 tb = Path(case["tb_file"])
 saved = {p: p.read_bytes() for p in (record_path, transcript, rtl, decl, tb)}
 try:
  record = json.loads(saved[record_path])
  row = record["cases"][0]
  evidence = row.get("reset_retention")
  if mutation == "legacy_pass": row.pop("reset_retention", None)
  elif mutation == "missing_execution": record_path.unlink()
  elif mutation == "missing_transcript": transcript.unlink()
  elif mutation == "changed_transcript": transcript.write_text(saved[transcript].decode() + "changed current native transcript\n")
  elif mutation in ("missing_first_edge", "missing_bytes"):
   text = saved[transcript].decode()
   lines = [line for line in text.splitlines() if not (line.startswith("RESET_RETENTION SAMPLE arm=1 edge=0 ")
            if mutation == "missing_first_edge" else line.startswith("RESET_RETENTION SAMPLE "))]
   transcript.write_text("\n".join(lines) + "\n")
   if isinstance(evidence, dict): evidence["transcript_sha256"] = hashlib.sha256(transcript.read_bytes()).hexdigest()
  elif mutation == "changed_rtl": rtl.write_text(saved[rtl].decode().replace("8'h3c", "8'h3d"))
  elif mutation == "changed_declaration":
   data = json.loads(saved[decl]); data["sram_interface_protocol"] = "different_commit_protocol"; decl.write_text(json.dumps(data))
  elif mutation == "changed_tb": tb.write_text(saved[tb].decode() + "// changed current testbench\n")
  if mutation != "missing_execution": record_path.write_text(json.dumps(record))
  _, rejected = _retention_consumer(project)
  measured = _retention_row(rejected)
  assert measured["pass"] is False, measured
  assert measured["status"] == "NOT_EXECUTED" and measured["waived"] is False
  _debt_stays_owed(rejected)
 finally:
  for path, data in saved.items(): path.write_bytes(data)


def test_consumer_refuses_false_pass_over_measured_first_edge_corruption(native_retention_bad):
 project, _ = native_retention_bad
 path = X.record_path(project); original = path.read_bytes()
 try:
  record = json.loads(original)
  record["cases"][0]["verdict"] = "PASS"
  path.write_text(json.dumps(record))
  _, checked = _retention_consumer(project)
  row = _retention_row(checked)
  assert row["pass"] is False and row["status"] == "fail", row
  assert "actual memory bytes changed" in " ".join(row["evidence"])
  _debt_stays_owed(checked)
 finally:
  path.write_bytes(original)


# Source/metadata controls for the optional designer stimulus. No simulator is
# dispatched here; decoder transcripts are synthetic data, not native evidence.
_PRELOAD = [{"address": 7, "byte": 255}, {"address": 0, "byte": 0},
            {"address": 4, "byte": 165}]
_ABSENT = object()


def _preload_metadata_project(project, choice=_ABSENT):
 prepare(project, good=True)
 path = project / "plugin_output/declaration.json"
 decl = json.loads(path.read_text())
 if choice is not _ABSENT:
  decl["verification_stimuli"] = choice
  path.write_text(json.dumps(decl))
 report = {}
 assert T.emit_unit_tbs(project, top="sample_store", report=report,
                        scaffold=False, case_stated=True) == 1
 tb = T._pl.sim_dir(project) / "tb" / (CASE["name"] + ".v")
 return tb, report


def _preload_choice(entries):
 return {"reset_retention": {"memory_preload": entries}}


def _emitted_preload(text):
 import re
 return {int(address): int(byte, 16) for address, byte in
         re.findall(r"retention_mem\[(\d+)\] = 8'h([0-9a-f]{2});", text)}


def test_declared_preload_is_consumed_by_the_general_producer(tmp_path):
 tb, report = _preload_metadata_project(tmp_path, _preload_choice(_PRELOAD))
 text = tb.read_text()
 assert _emitted_preload(text) == {0: 0, 4: 165, 7: 255}
 memory = report["reset_invariant_cases"][0]["retention_memory"]
 assert memory["memory_preload"] == sorted(_PRELOAD, key=lambda entry: entry["address"])
 assert R._retention_memory_identity(tmp_path, tb)[0] == memory
 assert report["no_real_oracle"] == [DEBT["name"]]
 seed = text.index("retention_mem[_i] = 8'ha5 + _i * 17;")
 overlay = text.index("retention_mem[7] = 8'hff;")
 idle = text.index("observe_reset(0);")
 assert seed < overlay < idle
 assert "always @(posedge i_clk) if (o_store_we === 1'b1)" in text
 assert "retention_mem[o_store_waddr] <= o_store_wdata;" in text
 assert "edge_number = 0; edge_number < 6" in text
 assert "active_cycles < 64 && !pending_found" in text
 assert "retention_mem[o_store_waddr] !== o_store_wdata" in text
 assert "retention_mem[_i] !== retention_before[_i]" in text
 assert "NOT_MEASURED: no actual non-idempotent pending write within 64 cycles" in text


@pytest.mark.parametrize("choice", [_ABSENT, {}, {"reset_retention": {}}])
def test_absent_preload_keeps_the_stock_seed_and_unexercised_refusal(tmp_path, choice):
 tb, report = _preload_metadata_project(tmp_path, choice)
 text = tb.read_text()
 assert _emitted_preload(text) == {}
 assert "retention_mem[_i] = 8'ha5 + _i * 17;" in text
 assert "NOT_MEASURED: no actual non-idempotent pending write within 64 cycles" in text
 assert "memory_preload" not in report["reset_invariant_cases"][0]["retention_memory"]


@pytest.mark.parametrize("choice", [
 None, [], {"reset_retention": None}, {"reset_retention": []},
 _preload_choice(None), _preload_choice([]), _preload_choice({"address": 0, "byte": 1}),
 _preload_choice([None]), _preload_choice([{"address": 0}]),
 _preload_choice([{"address": 0, "byte": 1, "ignored": 2}]),
 *[_preload_choice([{"address": address, "byte": 1}]) for address in (-1, 8, True, "1", 1.0)],
 *[_preload_choice([{"address": 0, "byte": byte}]) for byte in (-1, 256, False, "1", 1.0)],
 _preload_choice([{"address": 0, "byte": 1}, {"address": 0, "byte": 2}]),
])
def test_malformed_preload_declines_actual_byte_credit(tmp_path, choice):
 tb, report = _preload_metadata_project(tmp_path, choice)
 row = report["reset_invariant_cases"][0]
 assert row["retention_memory"] is None
 assert row["retention_basis"].startswith("NOT_MEASURED: retention")
 text = tb.read_text()
 assert R.RETENTION_HEADER not in text
 assert "NOT_MEASURED — write strobe necessary condition only" in text
 assert report["no_real_oracle"] == [DEBT["name"]]


def _preload_decoder_record(project, changed=False):
 tb, _ = _preload_metadata_project(project, _preload_choice(_PRELOAD))
 # Known neutral byte snapshots test the existing metadata consumer only.
 before = "00b6c7d8a5fa0bff"
 lines = [f"RESET_RETENTION BASELINE arm={arm} bytes={before}" for arm in (0, 1)]
 lines.append("RESET_RETENTION PENDING address=2 before=c7 data=3c")
 for arm in (0, 1):
  for edge in range(6):
   data = "00b63cd8a5fa0bff" if changed and arm == 1 else before
   lines.append(f"RESET_RETENTION SAMPLE arm={arm} edge={edge} bytes={data} post_edge_we=0")
 transcript = project / "synthetic-decoder-transcript.txt"
 transcript.write_text("\n".join(lines) + "\n")
 rtl = project / "phase2/stage1/rtl/sample_store.v"
 evidence, _ = R.capture_retention_execution(project, tb, transcript,
                                           {str(rtl): X.file_sha256(rtl)})
 X.write_record(project, project / "phase1/generated_docs/L10_TEST_CASES.json",
                [{"id": CASE["name"], "verdict": "PASS", "sim_executed": True,
                  "tb_file": str(tb), "reset_retention": evidence}],
                producer="CPU metadata fixture, NOT native execution")
 record = X.load_record(project, project / "phase1/generated_docs/L10_TEST_CASES.json")
 return tb, transcript, record


def test_preload_binding_reaches_the_existing_retention_metadata_consumer(tmp_path):
 _, _, record = _preload_decoder_record(tmp_path)
 assert R.retention_case_state(tmp_path, CASE["name"], record)[0] == X.PASS
 assert R.retention_case_state(tmp_path, DEBT["name"], record)[0] == X.NOT_EXECUTED


@pytest.mark.parametrize("damage", ["changed_preload", "removed_preload", "malformed_preload",
                                    "changed_tb", "missing_edge_zero", "changed_source"])
def test_preload_metadata_credit_keeps_current_binding_refusals(tmp_path, damage):
 tb, transcript, record = _preload_decoder_record(tmp_path)
 decl = tmp_path / "plugin_output/declaration.json"
 if damage in ("changed_preload", "removed_preload", "malformed_preload"):
  data = json.loads(decl.read_text())
  if damage == "changed_preload": data["verification_stimuli"] = _preload_choice([{"address": 0, "byte": 1}])
  elif damage == "removed_preload": data.pop("verification_stimuli")
  else: data["verification_stimuli"] = _preload_choice([{"address": True, "byte": 1}])
  decl.write_text(json.dumps(data))
 elif damage == "changed_tb": tb.write_text(tb.read_text() + "// current bytes changed\n")
 elif damage == "changed_source":
  rtl = tmp_path / "phase2/stage1/rtl/sample_store.v"
  rtl.write_text(rtl.read_text() + "// current bytes changed\n")
 else:
  transcript.write_text("\n".join(line for line in transcript.read_text().splitlines()
                                if not line.startswith("RESET_RETENTION SAMPLE arm=1 edge=0 ")) + "\n")
  record["rows"][CASE["name"]]["reset_retention"]["transcript_sha256"] = X.file_sha256(transcript)
 assert R.retention_case_state(tmp_path, CASE["name"], record)[0] == X.NOT_EXECUTED


def test_preload_metadata_consumer_refuses_forged_pass_over_first_edge_change(tmp_path):
 _, _, record = _preload_decoder_record(tmp_path, changed=True)
 state, why = R.retention_case_state(tmp_path, CASE["name"], record)
 assert state == X.FAIL
 assert "including its first sampled edge" in why


@pytest.mark.parametrize("protocol", ["sdp8_raddr_waddr_wdata_rdata_we_sync0r",
    "registered_dual_port_8bit_async_read_sync_write"], ids=["sdp-five", "canonical-five"])
@pytest.mark.parametrize("good", [True, False], ids=["retained", "first-edge-corruption"])
def test_native_retention_uses_the_shared_selected_five_role_contract(tmp_path, monkeypatch, protocol, good):
    import sys
    import isa_suite_producer as isa
    original = prepare
    def selected_prepare(project, good=False):
        rtl = original(project, good)
        rtl.write_text(rtl.read_text().replace("module sample_store(", "module sample_store #(parameter memsize=8)("))
        path = project / "plugin_output/declaration.json"
        decl = json.loads(path.read_text())
        decl.update(sram_interface_protocol=protocol, memsize_bytes=8, reset_pc=0)
        path.write_text(json.dumps(decl, indent=2))
        return rtl
    monkeypatch.setattr(sys.modules[__name__], "prepare", selected_prepare)
    project, result = _retention_native(tmp_path, good=good, diagnostic=False)
    facts, reason = isa.design_facts(project)
    assert facts is not None, reason
    assert facts["sram"]["read_latency"] == 0 and "ren" not in facts["sram_ports"]
    row = _retention_row(result["consumer"])
    case = result["execution"]["cases"][0]
    assert case["state"] == ("passed" if good else "failed"), result
    assert row["status"] == ("pass" if good else "fail") and row["sim_executed"], row
    if good:
        measurement = case["reset_retention"]["measurement"]
        assert measurement["complete"] and not measurement["changed"]
        assert measurement["pending"] == {"address":2,"before":"c7","data":"3c"}
    else:
        log = (Path(case["work_dir"]) / "run.log").read_text()
        assert "retention arm=1 edge=0 byte=2 before=c7 after=3c" in log, log
    _debt_stays_owed(result["consumer"])
