"""The ISA-suite producer: pinned public suites, run on the design's own RTL,
judged by each suite's own criterion (lane isaprod, 2026-09-28).

MEASURED on a reused bit-serial RV32I core (vibeic-eda 0.3.84): riscv-arch-test
3.9.1 against Spike matched 9/40 signatures on the supplied RTL and 40/40 on
the upstream fix, while riscv-tests alone gave a false green. These tests pin
every refusal the producer makes and every verdict it can reach, without a
container: the tool runs are replaced by an executor that writes the file the
container job would write, so the REAL host path (lock, acquisition, env,
binding, judging, rows, transcript) is what runs.

chip-AGNOSTIC: the fixture design is a synthetic top with a byte-wide
simple-dual-port SRAM port; no chip, vendor, PDK or case-name literal.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import shutil
import tarfile
import urllib.request
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import isa_suite_producer as I  # noqa: E402
import instruction_coverage_measure as ICM  # noqa: E402

CAL = PROGRAMS / "calibration"
ROOT = "suite-0123"
PROG_S = b"/* a program */\n"
HDR = b"/* a header */\n"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _tarball(files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel, blob in files.items():
            ti = tarfile.TarInfo(f"{ROOT}/{rel}")
            ti.size = len(blob)
            tf.addfile(ti, io.BytesIO(blob))
    return buf.getvalue()


FILES = {"src/add-01.S": PROG_S, "src/Fencei.S": PROG_S, "env/h.h": HDR}
TARBALL = _tarball(FILES)


def _lock(**over) -> dict:
    suite = {
        "commit": "f" * 40, "root": ROOT,
        "tarball_url": "https://example.invalid/suite.tar.gz",
        "tarball_sha256": _sha(TARBALL),
        "include_dirs": ["env"],
        "files": {k: _sha(v) for k, v in FILES.items()},
        "programs": [
            {"id": "s-add", "path": "src/add-01.S", "unit": "I",
             "instruction": "add", "judge": "signature", "role": "primary"},
            {"id": "s-fencei", "path": "src/Fencei.S", "unit": "Zifencei",
             "instruction": "fence.i", "judge": "signature", "role": "primary"},
        ],
    }
    suite.update(over)
    return {"isa_units": {
        "I": {"instructions": ["add", "sub", "ecall", "ebreak"],
              "trap_dependent": ["ecall", "ebreak"],
              "trap_dependent_reason": "no trap target"},
        "Zifencei": {"instructions": ["fence.i"], "trap_dependent": []}},
        "suites": {"s": suite}}


RTL = """module soc_top #(parameter memsize = 1024, parameter aw = $clog2(memsize))
  (input wire clk_i, input wire rst_i,
   output wire [aw-1:0] o_m_waddr, output wire [7:0] o_m_wdata,
   output wire o_m_wen, output wire [aw-1:0] o_m_raddr,
   input wire [7:0] i_m_rdata, output wire o_m_ren, output wire o_led);
endmodule
"""


def _project(tmp: Path, units=("I", "Zifencei"), **decl_over) -> Path:
    p = tmp / "proj"
    (p / "plugin_output").mkdir(parents=True)
    decl = {"top_module": "soc_top", "clock_port_name": "clk_i",
            "memsize_bytes": 1024, "reset_polarity": "active_high",
            "sram_interface_protocol": "sdp8_waddr_raddr_wen_ren_sync1r",
            "isa_extensions": list(units), "rf_storage": "shared_sram"}
    decl.update(decl_over)
    (p / "plugin_output" / "declaration.json").write_text(json.dumps(decl))
    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L10_TEST_CASES.json").write_text(json.dumps({"fields": {"test_cases": [
        {"name": "base_isa", "kind": "functional_vector",
         "stimulus": "the whole RV32I instruction set, unit tests",
         "expected": "100% PASS (compliance suite)"},
        {"name": "fence_ext", "kind": "functional_vector",
         "stimulus": "Zifencei instruction", "expected": "PASS"},
        {"name": "mul_ext", "kind": "functional_vector",
         "stimulus": "(if M is chosen) Mul/Div", "expected": "PASS",
         "applies_when": {"option": "M"}},
        {"name": "boot", "kind": "functional_vector",
         "stimulus": "first fetch after reset", "expected": "within 10 cycles"},
    ]}}))
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(
        {"params": [{"name": "RESET_PC", "default": "`0x00000000`",
                     "source": "L3_external_interface.md"}]}))
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "soc_top.v").write_text(RTL)
    return p


def _fake_executor(outcome: dict):
    """Writes the results.json the container job would write. `outcome` maps
    program id -> (ref_words|None, ref_rc, dut transcript, dut words|None
    [, dut_rc])."""
    def _run(job_path: Path, work: Path):
        job = json.loads(Path(job_path).read_text())
        res = {"programs": {}, "builds": {}, "sims": {}, "done": True,
               "memsize_full": 1 << 21}
        for arm in job["arms"]:
            res["builds"][f"{arm['name']}_full"] = {"ok": True}
            res["builds"][f"{arm['name']}_delivered"] = {"ok": True}
        for prog in job["programs"]:
            item = outcome[prog["id"]]
            ref_words, ref_rc, tr, dut_words = item[:4]
            dut_rc = item[4] if len(item) > 4 else 0
            size = item[5] if len(item) > 5 else 512
            d = Path(work) / "o" / prog["id"]
            d.mkdir(parents=True)
            (d / "dut.dis").write_text((CAL / "isa_objdump_no_relax_negative.dis").read_text())
            ref = None
            if ref_words is not None:
                ref = d / "ref.sig"
                ref.write_text("\n".join(ref_words) + "\n")
            res["programs"][prog["id"]] = {
                "build": {"ok": True, "size": size, "ref_size": size,
                          "tohost": 100, "disassembly": str(d / "dut.dis"),
                          "objdump_rc": 0, "nm_rc": 0, "nm_ref_rc": 0,
                          "objcopy_rc": 0},
                "ref": {"rc": ref_rc, "sig": str(ref) if ref else None}}
            for arm in job["arms"]:
                for label in ("full", "delivered"):
                    if label == "delivered" and size + job["rf_reserved_bytes"] > job["memsize_declared"]:
                        continue
                    for iv in job["init_patterns"]:
                        sig = None
                        if dut_words is not None:
                            sig = d / f"{arm['name']}_{label}_{iv}.sig"
                            sig.write_text("\n".join(dut_words) + "\n")
                        res["sims"].setdefault(prog["id"], {}).setdefault(
                            f"{arm['name']}_{label}", {})[iv] = {
                            "rc": dut_rc, "transcript": tr,
                            "sig": str(sig) if sig else None}
        (Path(work) / "results.json").write_text(json.dumps(res))
        return 0, "fake"
    return _run


HALT = (CAL / "isa_tb_halt_negative.log").read_text()
HANG = (CAL / "isa_tb_hang_positive.log").read_text()
WORDS = ["00000001", "deadbeef", "00000000"]
ALLOW = {"external_suite_fetch": "allowed"}


def _produce(p, outcome, **kw):
    return I.produce(p, executor=_fake_executor(outcome),
                     fetch=lambda _u: TARBALL, lock=kw.pop("lock", _lock()),
                     pol=kw.pop("pol", ALLOW), **kw)


@pytest.fixture(autouse=True)
def _private_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBEIC_ISA_SUITE_CACHE", str(tmp_path / "cache"))


# ── 1. the lock: a digest that does not match is NOT_MEASURED ─────────────

def test_a_tarball_digest_mismatch_is_refused(tmp_path):
    root, why = I.acquire("s", _lock()["suites"]["s"], tmp_path / "x",
                          fetch=lambda _u: TARBALL + b"\0")
    assert root is None and "tarball sha256" in why


def test_a_member_digest_mismatch_is_refused_naming_the_file(tmp_path):
    lock = _lock()
    lock["suites"]["s"]["files"]["src/add-01.S"] = "0" * 64
    root, why = I.extract_verified(TARBALL, lock["suites"]["s"], tmp_path)
    assert root is None and "src/add-01.S" in why


def test_the_verified_tarball_extracts_only_locked_files(tmp_path):
    root, why = I.extract_verified(TARBALL, _lock()["suites"]["s"], tmp_path)
    assert root is not None and "3 locked file(s) verified" in why
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) \
        == sorted(FILES)


def test_fetch_refuses_an_oversize_stream_before_keeping_it(monkeypatch):
    monkeypatch.setattr(I, "FETCH_MAX_BYTES", 1024, raising=False)

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, _size=-1):
            return b"x" * 1025

        read1 = read

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: Stream())
    with pytest.raises(ValueError, match="byte ceiling"):
        I.default_fetch("https://example.invalid/suite.tar.gz")


def test_fetch_refuses_a_continuously_streaming_deadline(monkeypatch):
    clock = [0.0]

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, _size=-1):
            clock[0] += I.FETCH_DEADLINE_S / 3
            return b"x"

        read1 = read

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: Stream())
    monkeypatch.setattr(I.time, "monotonic", lambda: clock[0])
    with pytest.raises(TimeoutError, match="overall fetch deadline"):
        I.default_fetch("https://example.invalid/suite.tar.gz")


def test_no_network_makes_every_bound_case_not_measured(tmp_path):
    p = _project(tmp_path)

    def _down(_u):
        raise OSError("no route to host")
    rec = I.produce(p, executor=_fake_executor({}), fetch=_down, lock=_lock(),
                    pol=ALLOW)
    assert "no route to host" in rec["refusal"]
    assert {r["id"]: r["verdict"] for r in rec["rows"]} == {
        "base_isa": "NOT_EXECUTED", "fence_ext": "NOT_EXECUTED"}
    assert all(r["sim_executed"] is False and "NOT_MEASURED" in r["detail"]
               for r in rec["rows"])


def test_a_mismatched_tarball_through_the_producer_is_not_measured(tmp_path):
    p = _project(tmp_path)
    rec = I.produce(p, executor=_fake_executor({}), fetch=lambda _u: b"junk",
                    lock=_lock(), pol=ALLOW)
    assert "tarball sha256" in rec["refusal"]
    assert all(r["verdict"] == "NOT_EXECUTED" for r in rec["rows"])


def test_a_refused_fetch_policy_names_itself(tmp_path):
    p = _project(tmp_path)
    rec = I.produce(p, executor=_fake_executor({}), fetch=lambda _u: TARBALL,
                    lock=_lock(), pol={"external_suite_fetch": "refused"})
    assert "external_suite_fetch='refused'" in rec["refusal"]


def test_the_shipped_policy_allows_the_fetch():
    assert I.fetch_allowed(I.load_policy())[0] is True


def test_the_shipped_lock_pins_commits_and_digests():
    lock = I.load_lock()
    for name, s in lock["suites"].items():
        assert len(s["commit"]) == 40, name
        assert len(s["tarball_sha256"]) == 64, name
        for prog in s["programs"]:
            assert prog["path"] in s["files"], prog["id"]
    act = [p for p in lock["suites"]["riscv-arch-test"]["programs"]]
    assert len([p for p in act if p["unit"] == "I"]) == 39
    covered = {p["instruction"] for p in act if p["unit"] == "I"}
    enum = lock["isa_units"]["I"]["instructions"]
    assert sorted(set(enum) - covered) == ["ebreak", "ecall"]


# ── 2. the env is the flow's own, at the design's reset vector ────────────

def test_the_env_is_csr_free_and_links_at_the_reset_vector():
    env = I.gen_env({"reset_pc": 0x100})
    assert ". = 0x100;" in env["link_dut.ld"]
    assert f". = {I.SPIKE_DRAM_BASE:#x};" in env["link_ref.ld"]
    for name in ("riscv_test.h", "model_test.h"):
        code = re.sub(r"/\*.*?\*/", "", env[name], flags=re.S).lower()
        assert "tohost" in code
        assert not re.search(r"\bcsr\w*\b|\becall\b|\bebreak\b|mtvec", code)


def test_design_facts_come_from_the_declaration_and_the_ports(tmp_path):
    facts, why = I.design_facts(_project(tmp_path))
    assert facts is not None, why
    assert facts["sram_ports"] == {
        "waddr": "o_m_waddr", "wdata": "o_m_wdata", "wen": "o_m_wen",
        "raddr": "o_m_raddr", "rdata": "i_m_rdata", "ren": "o_m_ren"}
    assert (facts["reset"], facts["memsize_param"], facts["reset_pc"],
            facts["rf_reserved_bytes"]) == ("rst_i", "memsize", 0, 128)
    tb = I.gen_tb(facts)
    assert "soc_top #(.memsize(MEMSIZE)) dut" in tb
    assert "mem[i] = iv[7:0]" in tb           # powered up to +init, not zero


def test_direction_disambiguates_shared_sram_data_ports_through_producer(tmp_path):
    p = _project(tmp_path)
    rtl = p / "phase2/stage1/rtl/soc_top.v"
    rtl.write_text(RTL.replace("o_m_wdata", "o_m_data")
                      .replace("i_m_rdata", "i_m_data")
                      .replace("o_m_wen", "o_m_we")
                      .replace("o_m_raddr", "o_m_addr"))
    rec = _produce(p, {
        "s-add": (WORDS, 0, HALT, WORDS),
        "s-fencei": (WORDS, 0, HALT, WORDS),
    })
    assert rec["refusal"] is None
    assert rec["design_facts"]["sram_ports"]["wdata"] == "o_m_data"
    assert rec["design_facts"]["sram_ports"]["rdata"] == "i_m_data"
    assert rec["design_facts"]["sram_ports"]["wen"] == "o_m_we"
    assert rec["design_facts"]["sram_ports"]["raddr"] == "o_m_addr"
    assert {r["id"]: r["verdict"] for r in rec["rows"]} == {
        "base_isa": "PASS", "fence_ext": "PASS"}


def test_ambiguous_shared_sram_data_output_refuses(tmp_path):
    p = _project(tmp_path)
    rtl = p / "phase2/stage1/rtl/soc_top.v"
    rtl.write_text(RTL.replace("o_m_wdata", "o_m_data, output wire [7:0] m_data")
                      .replace("i_m_rdata", "i_m_data"))
    facts, why = I.design_facts(p)
    assert facts is None
    assert "wdata" in why and "o_m_data" in why and "m_data" in why


def test_other_interface_data_cannot_be_bound_as_sram_write_data(tmp_path):
    p = _project(tmp_path)
    rtl = p / "phase2/stage1/rtl/soc_top.v"
    rtl.write_text(RTL.replace("o_m_wdata", "o_uart_data")
                      .replace("i_m_rdata", "i_m_data"))
    rec = _produce(p, {"s-add": (WORDS, 0, HALT, WORDS),
                       "s-fencei": (WORDS, 0, HALT, WORDS)})
    assert (rec.get("design_facts") or {}).get("sram_ports", {}).get("wdata") != "o_uart_data"
    assert rec["design_facts"] is None
    assert "wdata" in rec["refusal"] and "o_uart_data" in rec["refusal"]
    assert {r["verdict"] for r in rec["rows"]} == {"NOT_EXECUTED"}


def test_explicit_sram_role_from_another_interface_is_refused(tmp_path):
    p = _project(tmp_path)
    rtl = p / "phase2/stage1/rtl/soc_top.v"
    rtl.write_text(RTL.replace("o_m_wdata", "o_uart_wdata"))
    facts, why = I.design_facts(p)
    assert (facts or {}).get("sram_ports", {}).get("wdata") != "o_uart_wdata"
    assert facts is None
    assert "wdata" in why and "o_uart_wdata" in why


def test_an_unmodellable_sram_protocol_is_refused_by_name(tmp_path):
    p = _project(tmp_path, sram_interface_protocol="wishbone_classic")
    facts, why = I.design_facts(p)
    assert facts is None and "wishbone_classic" in why


# ── 3. the objdump guard ───────────────────────────────────────────────────

def test_a_planted_compressed_parcel_is_caught():
    real = (CAL / "isa_objdump_rvc_parcel_positive.dis").read_text()
    assert I.objdump_guard(real, allow_compressed=False) == [
        "2 16-bit instruction(s) on a core that declares no C"]
    planted = (CAL / "isa_objdump_no_relax_negative.dis").read_text() + \
        "  1c0:\t0001                \tc.nop\n"
    assert I.objdump_guard(planted, allow_compressed=False)
    assert I.objdump_guard(planted, allow_compressed=True) == []


def test_a_clean_image_passes_the_guard():
    clean = (CAL / "isa_objdump_no_relax_negative.dis").read_text()
    assert I.objdump_guard(clean, allow_compressed=False) == []


def test_empty_or_malformed_objdump_is_not_a_clean_image():
    assert any("decoded instructions" in issue for issue in
               I.objdump_guard("", allow_compressed=False))
    assert any("decoded instructions" in issue for issue in
               I.objdump_guard("objdump: failed to decode\n", allow_compressed=False))
    partial = "   0:\t00000013\taddi\ta0,a0,0\n   4:\t123456\tbroken\n"
    assert any("parsed 1 of 2" in issue for issue in
               I.objdump_guard(partial, allow_compressed=False))


def test_a_csr_instruction_and_an_oversized_image_are_caught():
    dis = "   0:\t30529073          \tcsrrw\tzero,mtvec,t0\n" \
          "   4:\t00000073          \tecall\n"
    v = I.objdump_guard(dis, allow_compressed=False, size_bytes=900,
                        program_area=896)
    assert "CSR/system instruction(s) csrrw x1, ecall x1" in v
    assert "image ends at 900 B, beyond the 896 B program area" in v


# ── 4. the judge ───────────────────────────────────────────────────────────

def test_a_signature_mismatch_fails_naming_the_first_differing_word():
    dut = {"status": "halted", "tohost": 1, "cycles": 10}
    st, why = I.judge_signature(WORDS, 0, dut,
                                ["00000001", "deadbeee", "00000001"])
    assert st == I.FAIL
    assert why.startswith("signature word 1 (byte offset 0x4) is deadbeee, "
                          "reference deadbeef (2 of 3 words differ)")


def test_a_hang_is_fail():
    dut = I.parse_tb_transcript(HANG)
    assert dut["status"] == "hang" and dut["cycles"] == 20_000_000
    assert I.judge_signature(WORDS, 0, dut, None)[0] == I.FAIL
    assert I.judge_tohost(0, dut)[0] == I.FAIL


def test_a_reference_timeout_or_missing_signature_is_not_measured():
    dut = I.parse_tb_transcript(HALT)
    assert I.judge_signature(WORDS, 124, dut, WORDS)[0] == I.NOT_MEASURED
    assert I.judge_signature(None, 0, dut, WORDS)[0] == I.NOT_MEASURED
    assert I.judge_tohost(124, dut)[0] == I.NOT_MEASURED


def test_a_nonzero_reference_rc_with_a_residual_signature_is_not_measured():
    """A partial Spike signature is not oracle evidence after its process fails."""
    dut = I.parse_tb_transcript(HALT)
    st, why = I.judge_signature(["00000001"], 1, dut, ["00000001"])
    assert st == I.NOT_MEASURED
    assert why == "the reference model itself does not pass this program (rc 1)"


def test_a_matching_signature_and_a_tohost_of_one_pass():
    dut = I.parse_tb_transcript(HALT)
    assert dut == {"status": "halted", "tohost": 1, "cycles": 154515}
    assert I.judge_signature(WORDS, 0, dut, list(WORDS))[0] == I.PASS
    assert I.judge_tohost(0, dut)[0] == I.PASS
    assert I.judge_tohost(0, dict(dut, tohost=5)) == (I.FAIL,
                                                      "self-check failed at test 2")


def test_a_set_is_pass_only_when_every_member_passes():
    assert I.fold([I.PASS, I.PASS]) == I.PASS
    assert I.fold([I.PASS, I.NOT_MEASURED]) == I.NOT_MEASURED
    assert I.fold([I.NOT_MEASURED, I.FAIL]) == I.FAIL
    assert I.fold([]) == I.NOT_MEASURED


# ── 5. mandatory enumeration; legacy IDs retained for contract migration ──

def test_no_trap_support_excludes_ecall_and_ebreak_by_name(tmp_path):
    facts, _ = I.design_facts(_project(tmp_path))
    total, excl, why = I.instruction_total(_lock(), facts)
    assert (total, excl) == (4, [])
    assert "no Zicsr" in why


def test_a_trap_capable_core_is_judged_on_every_instruction(tmp_path):
    facts, _ = I.design_facts(_project(tmp_path, units=("I", "Zicsr")))
    assert I.instruction_total(_lock(), facts)[:2] == (4, [])
    facts, _ = I.design_facts(_project(tmp_path / "b", trap_support=True))
    assert I.instruction_total(_lock(), facts)[:2] == (4, [])


def test_the_shipped_lock_gives_38_without_traps_and_40_with():
    lock = I.load_lock()
    assert I.instruction_total(lock, {"trap_support": False})[:2] == (
        40, [])
    assert I.instruction_total(lock, {"trap_support": True})[:2] == (40, [])


# ── 6. which cases bind ────────────────────────────────────────────────────

def test_only_cases_naming_a_declared_unit_bind(tmp_path):
    p = _project(tmp_path)
    assert I.bound_cases(p, ["I", "Zifencei"]) == {
        "base_isa": ["I"], "fence_ext": ["Zifencei"]}
    assert I.bound_cases(p, ["I"]) == {"base_isa": ["I"]}
    assert I.bind_case({"stimulus": "(if M is chosen) Mul/Div"},
                       ["I", "M"]) == []
    assert I.bind_case({"stimulus": "RV32IM subset"}, ["I"]) == []


# ── 7. the producer end to end, and the coverage line ─────────────────────

def test_the_coverage_line_is_the_instruments_grammar():
    line = I.coverage_line(37, 38)
    m = ICM.EMISSION_RE.search(line)
    assert m and (m.group("dim"), m.group("covered"), m.group("total")) == (
        "instruction", "37", "38")


def test_a_passing_suite_writes_pass_rows_and_the_coverage_line(tmp_path):
    p = _project(tmp_path)
    rec = _produce(p, {"s-add": (WORDS, 0, HALT, WORDS),
                       "s-fencei": (WORDS, 0, HALT, WORDS)})
    rows = {r["id"]: r for r in rec["rows"]}
    assert rows["base_isa"]["verdict"] == "PASS"
    assert rows["base_isa"]["sim_executed"] is True
    assert rec["cases"]["base_isa"].get("full_parameter", {"verdict": "PASS"})["verdict"] == "PASS"
    assert rec["cases"]["base_isa"].get("delivered", {"verdict": "PASS"})["verdict"] == "PASS"
    assert rows["fence_ext"]["verdict"] == "PASS"
    cov = rec["cases"]["base_isa"]["coverage"]
    assert cov == {"covered": 1, "total": 4, "excluded": [],
                   "uncovered": ["sub", "ecall", "ebreak"]}
    text = (p / I.TRANSCRIPT_REL.format(case="base_isa")).read_text()
    assert I.coverage_line(1, 4) in text
    assert "excluded from the instruction total: none" in text
    assert "(parameter only); delivered-size subset at memsize 1024" in text
    assert (p / I.RECEIPT_REL).is_file()


def test_full_parameter_pass_does_not_publish_delivered_l10_pass(tmp_path):
    p = _project(tmp_path)
    oversized = (WORDS, 0, HALT, WORDS, 0, 4096)
    rec = _produce(p, {"s-add": oversized, "s-fencei": oversized})
    case = rec["cases"]["base_isa"]
    row = next(r for r in rec["rows"] if r["id"] == "base_isa")
    assert rec["programs"]["s-add"]["fits_declared_memsize"] is False
    assert case.get("full_parameter", {"verdict": case["verdict"]})["verdict"] == "PASS"
    assert case.get("delivered", {"verdict": case["verdict"]})["verdict"] == "NOT_MEASURED"
    assert case["verdict"] == "NOT_MEASURED"
    assert case["full_parameter"]["coverage"]["covered"] == 1
    assert case["coverage"]["covered"] == 0
    assert row["verdict"] == "NOT_EXECUTED"
    assert row["sim_executed"] is False
    assert "delivered" in row["detail"] and "4096" in row["detail"]
    transcript = (p / I.TRANSCRIPT_REL.format(case="base_isa")).read_text()
    assert "CORE ISA (parameter only) PASS" in transcript
    assert I.coverage_line(0, 4) in transcript

    import testbench_gen as TB
    import _l10_execution as X
    tb = p / "phase2" / "stage1" / "sim" / "tb"
    tb.mkdir(parents=True)
    (tb / "base_isa.v").write_text(
        f"// {TB.ORACLE_NONE_MARKER}\nmodule base_isa;\nendmodule\n")
    report = {}
    TB.run_unit_tbs(p, report=report,
                    dispatch=lambda *_args: (0, "ok"),
                    isa_producer=lambda _project: rec)
    assert X.case_state("base_isa", X.load_record(p))[0] == X.NOT_EXECUTED


def test_one_delivered_program_cannot_certify_a_two_program_case(tmp_path):
    from _hostpaths import require_repo
    shipped_lock = json.loads(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "isa_suites.lock.json").read_text())
    shipped = [item for suite in shipped_lock["suites"].values()
               for item in suite["programs"]
               if item["unit"] == "I" and item["role"] == "primary"][:2]
    assert len(shipped) == 2 and shipped[0]["id"] != shipped[1]["id"]
    p = _project(tmp_path, units=("I",))
    lock = _lock()
    programs = lock["suites"]["s"]["programs"]
    programs[:] = [dict(programs[0], id=item["id"],
                        instruction=item["instruction"]) for item in shipped]
    lock["isa_units"]["I"]["instructions"] = [
        item["instruction"] for item in shipped] + ["ecall", "ebreak"]
    rec = _produce(p, {shipped[0]["id"]: (WORDS, 0, HALT, WORDS),
                       shipped[1]["id"]: (WORDS, 0, HALT, WORDS, 0, 4096)},
                   lock=lock)
    case = rec["cases"]["base_isa"]
    assert case["full_parameter"]["verdict"] == "PASS"
    assert case["delivered"]["passed"] == 1
    assert case["verdict"] == "NOT_MEASURED"
    assert rec["rows"][0]["verdict"] == "NOT_EXECUTED"


def test_completed_results_with_failed_executor_refuse_every_case(tmp_path):
    p = _project(tmp_path)
    completed = _fake_executor({"s-add": (WORDS, 0, HALT, WORDS),
                                "s-fencei": (WORDS, 0, HALT, WORDS)})

    def failed_after_write(job_path, work):
        completed(job_path, work)
        return 42, "container failed after results.json was written"

    rec = I.produce(p, executor=failed_after_write, fetch=lambda _u: TARBALL,
                    lock=_lock(), pol=ALLOW)
    assert rec["executor_rc"] == 42
    assert "rc 42" in rec["refusal"]
    assert "container failed after" in rec["refusal"]
    assert {r["verdict"] for r in rec["rows"]} == {"NOT_EXECUTED"}
    assert all(not r["sim_executed"] for r in rec["rows"])


def test_failed_objdump_rc_refuses_a_valid_looking_disassembly(tmp_path):
    p = _project(tmp_path)
    completed = _fake_executor({"s-add": (WORDS, 0, HALT, WORDS),
                                "s-fencei": (WORDS, 0, HALT, WORDS)})

    def failed_objdump(job_path, work):
        result = completed(job_path, work)
        path = Path(work) / "results.json"
        doc = json.loads(path.read_text())
        for prog in doc["programs"].values():
            prog["build"]["objdump_rc"] = 127
        path.write_text(json.dumps(doc))
        return result

    rec = I.produce(p, executor=failed_objdump, fetch=lambda _u: TARBALL,
                    lock=_lock(), pol=ALLOW)
    assert all(r["verdict"] == "NOT_EXECUTED" for r in rec["rows"])
    assert all("objdump" in r["detail"] for r in rec["rows"])


def test_inside_carries_failed_objdump_rc_into_build_record(tmp_path, monkeypatch):
    work = tmp_path / "inside"
    work.mkdir()
    job = {"work": str(work), "march": "rv32i", "spike_isa": "rv32i_zicsr",
           "reset_pc": 0, "rf_reserved_bytes": 0, "memsize_declared": 4096,
           "arms": [], "init_patterns": [],
           "programs": [{"id": "p", "judge": "tohost", "src": "p.S",
                         "include_dirs": []}]}
    job_path = work / "job.json"
    job_path.write_text(json.dumps(job))

    def tool(argv, _cwd, _log, **_kw):
        name = argv[0]
        if name == I.TOOLS["objdump"]:
            return 127, "objdump: failed"
        if name == I.TOOLS["nm"]:
            return 0, ("80001000 T _end\n00000010 T tohost\n" if
                       "ref.elf" in argv[-1] else
                       "00001000 T _end\n00000010 T tohost\n")
        return 0, ""

    monkeypatch.setattr(I, "_run", tool)
    assert I.inside(job_path) == 0
    build = json.loads((work / "results.json").read_text())["programs"]["p"]["build"]
    assert build["objdump_rc"] == 127
    assert build["ok"] is False


def test_a_mismatch_or_a_hang_fails_the_case(tmp_path):
    p = _project(tmp_path)
    rec = _produce(p, {"s-add": (WORDS, 0, HALT, ["00000001", "0", "0"]),
                       "s-fencei": (WORDS, 0, HANG, None)})
    rows = {r["id"]: r["verdict"] for r in rec["rows"]}
    assert rows == {"base_isa": "FAIL", "fence_ext": "FAIL"}
    assert rec["cases"]["base_isa"]["coverage"]["covered"] == 0


def test_a_reference_timeout_keeps_the_case_not_measured(tmp_path):
    p = _project(tmp_path)
    rec = _produce(p, {"s-add": (None, 124, HALT, WORDS),
                       "s-fencei": (WORDS, 0, HALT, WORDS)})
    rows = {r["id"]: r for r in rec["rows"]}
    assert rows["base_isa"]["verdict"] == "NOT_EXECUTED"
    assert rows["base_isa"]["sim_executed"] is False
    assert rows["fence_ext"]["verdict"] == "PASS"


def test_a_nonzero_dut_sim_rc_cannot_promote_halt_text_to_pass(tmp_path):
    """The results.json native rc is authoritative over a HALT marker."""
    p = _project(tmp_path)
    rec = _produce(p, {"s-add": (WORDS, 0, HALT, WORDS, 1),
                       "s-fencei": (WORDS, 0, HALT, WORDS)})
    states = rec["programs"]["s-add"]["arms"]["staged_full"]["by_init"]
    assert states and all(x["state"] == I.NOT_MEASURED for x in states)
    assert all(x["rc"] == 1 for x in states)
    assert all("DUT simulation exited nonzero (rc 1)" == x["why"]
               for x in states)
    rows = {r["id"]: r for r in rec["rows"]}
    assert rows["base_isa"]["verdict"] == "NOT_EXECUTED"


def test_a_declared_unit_with_no_suite_binds_nothing(tmp_path):
    """A case naming a declared extension the lock has no program for is not
    this producer's: it is left to whatever owns it, never a NOT_MEASURED
    row over an empty program set."""
    p = _project(tmp_path, units=("I", "Zifencei", "Zicsr"))
    l10 = p / "phase1" / "generated_docs" / "L10_TEST_CASES.json"
    doc = json.loads(l10.read_text())
    doc["fields"]["test_cases"].append(
        {"name": "csr_ext", "kind": "functional_vector",
         "stimulus": "Zicsr CSR access + timer IRQ", "expected": "PASS"})
    l10.write_text(json.dumps(doc))
    rec = _produce(p, {"s-add": (WORDS, 0, HALT, WORDS),
                       "s-fencei": (WORDS, 0, HALT, WORDS)})
    assert sorted(rec["bound_cases"]) == ["base_isa", "fence_ext"]
    assert "csr_ext" not in {r["id"] for r in rec["rows"]}


def test_a_design_with_no_isa_case_is_left_alone(tmp_path):
    p = _project(tmp_path, units=())
    rec = _produce(p, {})
    assert rec["rows"] == [] and "nothing to produce" in rec["refusal"]
    assert not (p / I.RECEIPT_REL).exists()


def test_the_isa_row_replaces_the_scaffold_row():
    old = [{"id": "base_isa", "verdict": "NOT_EXECUTED"},
           {"id": "boot", "verdict": "PASS"}]
    new = [{"id": "base_isa", "verdict": "FAIL"}]
    assert I.merge_rows(old, new) == [{"id": "boot", "verdict": "PASS"},
                                      {"id": "base_isa", "verdict": "FAIL"}]


def test_the_executor_publishes_the_isa_row(tmp_path):
    """Through `testbench_gen.run_unit_tbs`: the scaffold's NOT_EXECUTED row
    for an ISA case is replaced by the suite's own verdict."""
    import testbench_gen as TB
    import _l10_execution as X
    p = _project(tmp_path)
    tb = p / "phase2" / "stage1" / "sim" / "tb"
    tb.mkdir(parents=True)
    (tb / "base_isa.v").write_text(f"// {TB.ORACLE_NONE_MARKER}\nmodule base_isa;\nendmodule\n")

    def _dispatch(argv, run_dir, container, tool, timeout):
        return 0, "ok"

    def _isa(project):
        return {"rows": [{"id": "base_isa", "verdict": "FAIL",
                          "sim_executed": True, "tb_file": "receipt",
                          "detail": "ISA suite: 0/1 primary programs pass"}],
                "cases": {}}
    rep: dict = {}
    TB.run_unit_tbs(p, report=rep, dispatch=_dispatch, isa_producer=_isa)
    rec = X.load_record(p)
    assert X.case_state("base_isa", rec)[0] == X.FAIL
    xml = (p / "phase2/stage1/sim_professional/l10_unit_tb/results.xml").read_text()
    assert 'name="base_isa"' in xml and "<failure" in xml


def test_a_step4_run_writes_the_receipt_the_owner_credit_reads(tmp_path,
                                                               monkeypatch):
    """R-0929-OWNER-SUB-ACCEPT (1) end to end: Step 4's executor
    (`testbench_gen.run_unit_tbs`, called with NO injected producer, so the
    shipped wiring runs) writes `reports/phase2/isa_suites/isa_suite_receipt.json`
    and the LANDED reader `_l10_execution.isa_conformance_credit` credits it.

    Only the container job and the network are replaced (the executor writes
    the files the job would write). The programs do not fit the delivered
    memory, so the row stays NOT_EXECUTED at the delivered size and the case
    is credited only by the test-parameter rule -- the owner's shape."""
    import testbench_gen as TB
    import _l10_execution as X
    p = _project(tmp_path)
    oversized = (WORDS, 0, HALT, WORDS, 0, 4096)
    monkeypatch.setattr(I, "load_lock", lambda *_a, **_k: _lock())
    monkeypatch.setattr(I, "default_fetch", lambda _u: TARBALL)
    monkeypatch.setattr(I, "docker_executor", _fake_executor(
        {"s-add": oversized, "s-fencei": oversized}))
    tb = p / "phase2" / "stage1" / "sim" / "tb"
    tb.mkdir(parents=True)
    (tb / "base_isa.v").write_text(
        f"// {TB.ORACLE_NONE_MARKER}\nmodule base_isa;\nendmodule\n")
    TB.run_unit_tbs(p, report={}, dispatch=lambda *_a: (0, "ok"))

    assert (p / X.ISA_RECEIPT_REL).is_file(), "Step 4 wrote no ISA receipt"
    assert X.case_state("base_isa", X.load_record(p))[0] == X.NOT_EXECUTED
    l10 = json.loads((p / "phase1/generated_docs/L10_TEST_CASES.json")
                     .read_text())["fields"]["test_cases"]
    row = next(r for r in l10 if r["name"] == "base_isa")
    credit, refusal = X.isa_conformance_credit(p, "base_isa", row)
    assert refusal is None, refusal
    assert credit is not None
    assert ("core ISA conformance at test memsize=2097152 (delivered "
            "memsize=1024; parameter only, same RTL: 1 file(s)"
            in credit["sentence"]), credit["sentence"]
    # A FAIL anywhere in the suite is refused by the same reader.
    failing = (WORDS, 0, HANG, None, 0, 4096)
    monkeypatch.setattr(I, "docker_executor", _fake_executor(
        {"s-add": failing, "s-fencei": oversized}))
    TB.run_unit_tbs(p, report={}, dispatch=lambda *_a: (0, "ok"))
    credit, refusal = X.isa_conformance_credit(p, "base_isa", row)
    assert credit is None and "a failing suite" in (refusal or ""), refusal


# ── review wave 58: disclosure by staged bytes, no stale receipt ───────────

def _step4(p, monkeypatch, outcome):
    """Step 4's executor with the shipped wiring; only the container job and
    the network are replaced."""
    import testbench_gen as TB
    monkeypatch.setattr(I, "load_lock", lambda *_a, **_k: _lock())
    monkeypatch.setattr(I, "default_fetch", lambda _u: TARBALL)
    monkeypatch.setattr(I, "docker_executor", _fake_executor(outcome))
    tb = p / "phase2" / "stage1" / "sim" / "tb"
    tb.mkdir(parents=True, exist_ok=True)
    (tb / "base_isa.v").write_text(
        f"// {TB.ORACLE_NONE_MARKER}\nmodule base_isa;\nendmodule\n")
    return TB.run_unit_tbs(p, report={}, dispatch=lambda *_a: (0, "ok"))


def _base_isa_credit(p):
    import _l10_execution as X
    l10 = json.loads((p / "phase1/generated_docs/L10_TEST_CASES.json")
                     .read_text())["fields"]["test_cases"]
    row = next(r for r in l10 if r["name"] == "base_isa")
    return X.isa_conformance_credit(p, "base_isa", row)


OVERSIZED = (WORDS, 0, HALT, WORDS, 0, 4096)
FIX_BEFORE = "module fixed_core; /* pinned, with the defect */ endmodule\n"
FIX_AFTER = "module fixed_core; /* the upstream fix */ endmodule\n"


def test_a_fix_a_catalog_pull_staged_is_disclosed_in_the_credit(tmp_path,
                                                                monkeypatch):
    """Owner ruling 2B: the design declares no `ip_upstream`, a catalog pull
    staged an upstream fix and recorded it in the staged SOURCE_MANIFEST. The
    STAGED BYTES are the fix's after-image, so the receipt, the Step-4 credit
    sentence and the card each DISCLOSE it."""
    import final_report_generate as FRG
    p = _project(tmp_path)
    rtl = p / "phase2" / "stage1" / "rtl"
    (rtl / "fixed_core.v").write_text(FIX_AFTER)
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps({"source_pins": [{
        "ip_name": "somecore", "version": "9.9",
        "errata_applied": [{
            "upstream_commit": "abcdef0123456789" * 2 + "abcdef01",
            "file": "src/fixed_core.v", "disclosure": "upstream fix",
            "before_sha256": _sha(FIX_BEFORE.encode()),
            "after_sha256": _sha(FIX_AFTER.encode())}]}]}))
    _step4(p, monkeypatch, {"s-add": OVERSIZED, "s-fencei": OVERSIZED})
    rec = json.loads((p / I.RECEIPT_REL).read_text())
    assert any("upstream abcdef0123 applied to staged fixed_core.v" in d
               for d in rec["deviation_disclosures"]), rec["deviation_disclosures"]
    credit, refusal = _base_isa_credit(p)
    assert refusal is None, refusal
    assert "DISCLOSED deviation from somecore 9.9: upstream abcdef0123" \
        in credit["sentence"], credit["sentence"]
    card = "\n".join(FRG._deviation_section(p))
    assert "## Disclosed deviations" in card and "abcdef0123" in card


def test_an_unmodified_staged_file_discloses_nothing(tmp_path, monkeypatch):
    """The control: the same manifest, but the staged file is the PRE-fix
    bytes -- no deviation is in the silicon, so none is disclosed."""
    p = _project(tmp_path)
    rtl = p / "phase2" / "stage1" / "rtl"
    (rtl / "fixed_core.v").write_text(FIX_BEFORE)
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps({"source_pins": [{
        "ip_name": "somecore", "version": "9.9",
        "errata_applied": [{
            "upstream_commit": "abcdef0123456789" * 2 + "abcdef01",
            "file": "src/fixed_core.v", "disclosure": "upstream fix",
            "after_sha256": _sha(FIX_AFTER.encode())}]}]}))
    _step4(p, monkeypatch, {"s-add": OVERSIZED, "s-fencei": OVERSIZED})
    rec = json.loads((p / I.RECEIPT_REL).read_text())
    assert rec["deviation_disclosures"] == []
    credit, _ = _base_isa_credit(p)
    assert "DISCLOSED" not in credit["sentence"]


def test_an_applied_erratum_without_an_input_original_is_still_disclosed(
        tmp_path, monkeypatch):
    """An APPLIED flow-record row whose input original is not unique: arm A
    cannot be built, but the disclosure is not dropped -- and the receipt says
    arm A was not built."""
    import reused_ip_erratum as E
    p = _project(tmp_path)
    rtl = p / "phase2" / "stage1" / "rtl"
    (rtl / "fixed_core.v").write_text(FIX_AFTER)
    row = {"status": E.APPLIED, "ip": "somecore", "pinned_version": "9.9",
           "fix_commit": "1234567890abcdef", "erratum": "zeroing",
           "file": "src/fixed_core.v", "staged_file": str(rtl / "fixed_core.v"),
           "input_file": None, "sha256_before": _sha(FIX_BEFORE.encode()),
           "sha256_after": _sha(FIX_AFTER.encode())}
    (p / E.FLOW_RECORD_REL).parent.mkdir(parents=True, exist_ok=True)
    (p / E.FLOW_RECORD_REL).write_text(json.dumps({"rows": [row]}))
    _step4(p, monkeypatch, {"s-add": OVERSIZED, "s-fencei": OVERSIZED})
    rec = json.loads((p / I.RECEIPT_REL).read_text())
    assert rec["arms"] == ["staged"]
    assert any("upstream 1234567890 applied" in d
               for d in rec["deviation_disclosures"])
    assert any("arm A not built for fixed_core.v" in d
               for d in rec["deviation_disclosures"])
    credit, _ = _base_isa_credit(p)
    assert "DISCLOSED deviation from somecore 9.9: upstream 1234567890" \
        in credit["sentence"]


def test_a_rerun_whose_producer_crashes_keeps_no_credit(tmp_path, monkeypatch):
    """Run 1 credits; run 2's container job raises. The earlier receipt must
    not credit run 2 (review wave 58 P1)."""
    p = _project(tmp_path)
    _step4(p, monkeypatch, {"s-add": OVERSIZED, "s-fencei": OVERSIZED})
    assert _base_isa_credit(p)[0] is not None

    def _boom(_job, _work):
        raise RuntimeError("docker daemon gone")
    monkeypatch.setattr(I, "docker_executor", _boom)
    import testbench_gen as TB
    TB.run_unit_tbs(p, report={}, dispatch=lambda *_a: (0, "ok"))
    credit, refusal = _base_isa_credit(p)
    assert credit is None and "docker daemon gone" in (refusal or ""), refusal


def test_a_rerun_that_binds_nothing_or_never_runs_keeps_no_credit(
        tmp_path, monkeypatch):
    """P1b: the declaration stops listing the ISA units -- nothing produced.
    P1c: no TB, so run_unit_tbs never reaches the producer. Either way the
    earlier receipt is gone and nothing is credited."""
    import testbench_gen as TB
    p = _project(tmp_path)
    _step4(p, monkeypatch, {"s-add": OVERSIZED, "s-fencei": OVERSIZED})
    assert _base_isa_credit(p)[0] is not None
    decl = p / "plugin_output" / "declaration.json"
    d = json.loads(decl.read_text())
    decl.write_text(json.dumps(dict(d, isa_extensions=[])))
    TB.run_unit_tbs(p, report={}, dispatch=lambda *_a: (0, "ok"))
    assert not (p / I.RECEIPT_REL).exists()
    assert _base_isa_credit(p) == (None, None)

    q = _project(tmp_path / "c")
    _step4(q, monkeypatch, {"s-add": OVERSIZED, "s-fencei": OVERSIZED})
    shutil.rmtree(q / "phase2" / "stage1" / "sim" / "tb")
    assert TB.run_unit_tbs(q, report={}, dispatch=lambda *_a: (0, "ok")) < 0
    assert not (q / I.RECEIPT_REL).exists()


def test_a_receipt_the_execution_record_does_not_bind_credits_nothing(
        tmp_path, monkeypatch):
    """A receipt copied back beside a record that binds another one (or none)
    is not this run's evidence."""
    import _l10_execution as X
    p = _project(tmp_path)
    _step4(p, monkeypatch, {"s-add": OVERSIZED, "s-fencei": OVERSIZED})
    rp = p / I.RECEIPT_REL
    doc = json.loads(rp.read_text())
    rp.write_text(json.dumps(dict(doc, run_id="an-earlier-run")))
    credit, refusal = _base_isa_credit(p)
    assert credit is None and "did not produce" in refusal, refusal
    rec = json.loads(X.record_path(p).read_text())
    rec.pop(X.ISA_RECEIPT_BINDING_KEY)
    X.record_path(p).write_text(json.dumps(rec))
    rp.write_text(json.dumps(doc))
    credit, refusal = _base_isa_credit(p)
    assert credit is None and "binds no ISA receipt" in refusal, refusal


def test_core_parameters_with_csr_decides_trap_support(tmp_path):
    facts, _ = I.design_facts(_project(
        tmp_path, core_parameters={"WITH_CSR": 1}))
    assert I.instruction_total(_lock(), facts)[:2] == (4, [])
    facts, _ = I.design_facts(_project(
        tmp_path / "b", core_parameters={"WITH_CSR": 0}))
    assert I.instruction_total(_lock(), facts)[:2] == (4, [])


def test_the_isa_transcript_never_overwrites_the_scaffold_run_log(
        tmp_path, monkeypatch):
    """The scaffold TB's own transcript stays its evidence; the ISA producer
    writes beside it."""
    p = _project(tmp_path)
    _step4(p, monkeypatch, {"s-add": OVERSIZED, "s-fencei": OVERSIZED})
    case = p / "phase2/stage1/sim_professional/l10_unit_tb/base_isa"
    assert (case / "isa_suite.log").is_file()
    assert "CORE ISA" in (case / "isa_suite.log").read_text()
    assert "CORE ISA" not in (case / "run.log").read_text()


# Issue3107: exact public planning INPUT and real flow-owned trap programs.
# This mini RTL is a self-authored byte-SRAM machine-environment component,
# sufficient for the generated challenges, not a claimed full RV32I CPU.
_SYSTEM_RTL = r"""module soc_top #(parameter memsize = 1024,
  parameter aw = $clog2(memsize), parameter READ_LATENCY = 1, parameter FAULT = 0)
 (input wire clk_i, input wire rst_i,
  output wire [aw-1:0] o_m_waddr, output wire [7:0] o_m_wdata,
  output wire o_m_wen, output wire [aw-1:0] o_m_raddr,
  input wire [7:0] i_m_rdata, output wire o_m_ren, output wire o_led);
 reg [31:0] regs[0:31];
 reg [31:0] pc, instr, mtvec, mepc, mcause, store_addr, store_data;
 reg [1:0] lane;
 reg [2:0] state;
 reg [31:0] value, oldcsr;
 integer k;
 wire [6:0] opcode = instr[6:0];
 wire [4:0] rd = instr[11:7], rs1 = instr[19:15], rs2 = instr[24:20];
 wire [2:0] funct3 = instr[14:12];
 wire [31:0] imm_i = {{20{instr[31]}}, instr[31:20]};
 wire [31:0] imm_s = {{20{instr[31]}}, instr[31:25], instr[11:7]};
 wire [31:0] imm_b = {{19{instr[31]}}, instr[31], instr[7], instr[30:25], instr[11:8], 1'b0};
 wire [31:0] imm_j = {{11{instr[31]}}, instr[31], instr[19:12], instr[20], instr[30:21], 1'b0};
 assign o_m_ren = state == 0;
 assign o_m_raddr = pc + lane;
 assign o_m_wen = state == 3;
 assign o_m_waddr = store_addr + lane;
 assign o_m_wdata = store_data >> (lane*8);
 assign o_led = 1'b0;
 always @(posedge clk_i) begin
  if (rst_i) begin
   pc <= 0; lane <= 0; state <= 0; instr <= 0;
   mtvec <= 0; mepc <= 0; mcause <= 0;
   for (k=0;k<32;k=k+1) regs[k] <= 0;
  end else begin
   regs[0] <= 0;
   case (state)
    0: state <= READ_LATENCY==2 ? 4 : 1;
    4: state <= 1;
    1: begin
     instr[lane*8 +: 8] <= i_m_rdata;
     if (lane == 3) begin lane <= 0; state <= 2; end
     else begin lane <= lane+1; state <= 0; end
    end
    2: begin
     pc <= pc+4; state <= 0;
     case (opcode)
      7'h13: if (rd!=0) begin
       if (funct3==0) regs[rd] <= regs[rs1]+imm_i;
       if (funct3==1) regs[rd] <= regs[rs1]<<instr[24:20];
       if (funct3==6) regs[rd] <= regs[rs1]|imm_i;
      end
      7'h17: if (rd!=0) regs[rd] <= pc+{instr[31:12],12'b0};
      7'h37: if (rd!=0) regs[rd] <= {instr[31:12],12'b0};
      7'h6f: begin if (rd!=0) regs[rd] <= pc+4; pc <= pc+imm_j; end
      7'h67: begin if (rd!=0) regs[rd] <= pc+4; pc <= (regs[rs1]+imm_i)&32'hfffffffe; end
      7'h63: begin
       if ((funct3==0 && regs[rs1]==regs[rs2]) ||
           (funct3==1 && regs[rs1]!=regs[rs2])) pc <= pc+imm_b;
      end
      7'h23: begin store_addr <= regs[rs1]+imm_s; store_data <= regs[rs2];
       lane <= 0; state <= 3; end
      7'h0f: begin end
      7'h73: begin
       if (instr == 32'h00000073 || instr == 32'h00100073) begin
        if (FAULT!=3) begin
         mepc <= pc+(FAULT==2 ? 4 : 0);
         mcause <= FAULT==1 ? 7 : (instr==32'h00000073 ? 11 : 3);
         pc <= mtvec;
        end
       end else if (instr==32'h30200073) pc <= mepc;
       else begin
        case (instr[31:20])
         12'h305: oldcsr=mtvec;
         12'h341: oldcsr=mepc;
         12'h342: oldcsr=mcause;
         default: oldcsr=0;
        endcase
        if (rd!=0) regs[rd] <= oldcsr;
        value = funct3==1 ? regs[rs1] : oldcsr|regs[rs1];
        if (funct3==1 || (funct3==2 && rs1!=0)) begin
         case (instr[31:20])
          12'h305: mtvec <= value;
          12'h341: mepc <= value;
          12'h342: mcause <= value;
         endcase
        end
       end
      end
     endcase
    end
    3: begin
     if (lane==3) begin lane<=0;state<=0;end
     else lane<=lane+1;
    end
   endcase
  end
 end
endmodule
"""
_SMOKE_ASM = b"""#include "riscv_test.h"
RVTEST_RV32U
RVTEST_CODE_BEGIN
 li t2,13
 addi t3,t2,7
 li t4,20
 bne t3,t4,failed
 RVTEST_PASS
failed:
 li gp,1
 RVTEST_FAIL
RVTEST_DATA_BEGIN
 .word 0
RVTEST_DATA_END
"""


def _system_lock():
    files={'src/smoke.S':_SMOKE_ASM}
    tar=_tarball(files)
    lock={'isa_units':{'I':{'instructions':['addi','ecall','ebreak'],
                              'flow_system_programs':['ecall','ebreak']}},
          'suites':{'neutral':{'commit':'f'*40,'root':ROOT,
                    'tarball_url':'https://example.invalid/neutral-system.tar.gz',
                    'tarball_sha256':_sha(tar),'include_dirs':[],
                    'files':{name:_sha(data) for name,data in files.items()},
                    'programs':[{'id':'neutral-addi','path':'src/smoke.S','unit':'I',
                                 'instruction':'addi','judge':'tohost','role':'primary'}]}}}
    return lock,tar


@pytest.mark.parametrize('declaration', [
 {'isa_extensions':['I','Zifencei'],'WITH_CSR':0},
 {'isa_extensions':['I','Zifencei'],'WITH_CSR':1},
 {'isa_extensions':['I','Zicsr'],'WITH_CSR':0},
 {'isa_extensions':['I'],'core_parameters':{'WITH_CSR':0}},
])
def test_mandatory_system_obligations_do_not_depend_on_optional_csr(declaration):
    traps,why=I.trap_support(declaration)
    total,excluded,reason=I.instruction_total(I.load_lock(),
                    {'trap_support':traps,'trap_support_why':why})
    assert (total,excluded)==(40,[]), (total,excluded,reason)


@pytest.mark.parametrize('fault,want', [(0,I.PASS),(1,I.FAIL),(2,I.FAIL),(3,I.FAIL)])
@pytest.mark.parametrize('latency',[1,2])
def test_flow_owned_system_programs_measure_precise_traps_native(tmp_path,monkeypatch,fault,want,latency):
    import _l10_execution as X
    missing=[name for name in [*I.TOOLS.values(),'iverilog','vvp'] if shutil.which(name) is None]
    assert not missing, 'NOT_VERIFIED: pinned native tool(s) unavailable: '+str(missing)
    p=_project(tmp_path,units=('I',),WITH_CSR=1,rf_storage='registers',
               sram_interface_protocol=f'sdp8_waddr_raddr_wen_ren_sync{latency}r')
    rtl=p/'phase2/stage1/rtl/soc_top.v'
    rtl.write_text(_SYSTEM_RTL.replace('parameter FAULT = 0',f'parameter FAULT = {fault}')
                             .replace('parameter READ_LATENCY = 1',f'parameter READ_LATENCY = {latency}'))
    row={'name':'system_component','kind':'functional_vector',
         'stimulus':'RV32I SYSTEM ECALL and EBREAK precise-trap component checks',
         'expected':'PASS'}
    l10=p/'phase1/generated_docs/L10_TEST_CASES.json'
    l10.write_text(json.dumps({'test_cases':[row]}))
    lock,tar=_system_lock()
    monkeypatch.setattr(I,'CYCLE_CAP',10000)
    def actual_inside(job,work):
        return I.inside(job), 'Actual existing native inside job in pinned outer image'
    rec=I.produce(p,lock=lock,pol=ALLOW,fetch=lambda _u:tar,executor=actual_inside,
                  work_root=tmp_path/'native_job',keep_work=True)
    (tmp_path/'native_summary.json').write_text(json.dumps(rec,indent=2))
    assert rec['refusal'] is None, rec
    assert {'flow-I-ecall','flow-I-ebreak'} <= set(rec['programs']), rec['programs']
    for instruction in ['ecall','ebreak']:
        prog=rec['programs']['flow-I-'+instruction]
        assert not prog.get('pre'), prog
        assert prog['arms']['staged_delivered']['state']==want, prog
        if fault:
            assert all(x['why']==f'self-check failed at test {fault+1}'
                       for x in prog['arms']['staged_delivered']['by_init'])
    assert rec['cases']['system_component']['verdict']==want
    # Replay the same emitted TB/actual assembled images with the other
    # supported simulator, at the declared latency and delivered memory.
    # This is extra component evidence, not a replacement execution receipt.
    import subprocess
    work=tmp_path/'native_job'
    binary=work/'icarus.vvp'
    ccargv=['iverilog','-g2012','-s','isa_tb','-o',str(binary),
            str(work/'env/isa_tb.v'),str(rtl)]
    cc=subprocess.run(ccargv,capture_output=True,text=True,timeout=30)
    assert cc.returncode==0,cc.stdout+cc.stderr
    results=json.loads((work/'results.json').read_text())
    for pid in ['neutral-addi','flow-I-ecall','flow-I-ebreak']:
        expected=1 if pid=='neutral-addi' or not fault else {1:5,2:7,3:9}[fault]
        for init in ['ff','a5']:
            observed=results['sims'][pid]['staged_delivered'][init]
            assert I.parse_tb_transcript(observed['transcript'])['tohost']==expected
    icarus=[]
    for pid in ['neutral-addi','flow-I-ecall','flow-I-ebreak']:
        b=results['programs'][pid]['build']
        for init in ['ff','a5']:
            argv=['vvp',str(binary),f'+hex={work / "build" / pid / "dut.hex"}',
                  f'+tohost={b["tohost"]}',f'+init={init}']
            run=subprocess.run(argv,capture_output=True,text=True,timeout=30)
            assert run.returncode==0,run.stdout+run.stderr
            state,why=I.judge_tohost(results['programs'][pid]['ref']['rc'],
                                   I.parse_tb_transcript(run.stdout))
            assert state==(I.PASS if pid=='neutral-addi' else want),(pid,state,why)
            expected=1 if pid=='neutral-addi' or not fault else {1:5,2:7,3:9}[fault]
            assert I.parse_tb_transcript(run.stdout)['tohost']==expected
            icarus.append({'program':pid,'init':init,'argv':argv,'rc':run.returncode,
                           'stdout':run.stdout,'stderr':run.stderr,'judged_state':state})
    (work/'icarus_results.json').write_text(json.dumps({'compile_argv':ccargv,
                  'compile_rc':cc.returncode,'binary_sha256':_sha(binary.read_bytes()),
                  'latency':latency,'fault':fault,'runs':icarus},indent=2))
    X.write_record(p,l10,rec['rows'],producer='issue3107_actual_native_source_control',
                   isa_receipt=p/I.RECEIPT_REL)
    credit,refusal=X.isa_conformance_credit(p,'system_component',row)
    if fault:
        assert credit is None and 'failing' in refusal, (credit,refusal)
    else:
        assert refusal is None and credit['instructions']['covered']==3, (credit,refusal)
        assert credit['instructions']['total']==3
        # The receipt, native tools and component source are current; a stale
        # receipt from this actual run still cannot credit changed RTL.
        rtl.write_text(rtl.read_text()+'\n// changed source after execution\n')
        assert X.isa_conformance_credit(p,'system_component',row)[0] is None


def test_missing_trap_environment_keeps_named_unmeasured_primary_obligations(tmp_path):
    p=_project(tmp_path,units=('I',),WITH_CSR=0)
    lock,tar=_system_lock()
    rec=I.produce(p,lock=lock,pol=ALLOW,fetch=lambda _u:tar,
                 executor=_fake_executor({'neutral-addi':(None,0,HALT,None)}))
    assert rec['instruction_total']['total']==3
    assert rec['instruction_total']['excluded']==[]
    assert {'flow-I-ecall','flow-I-ebreak'} <= set(rec['programs']), rec['programs']
    for instruction in ['ecall','ebreak']:
        prog=rec['programs']['flow-I-'+instruction]
        assert prog['pre'][0]==I.NOT_MEASURED
        assert 'mandatory '+instruction in prog['pre'][1]
    assert rec['cases']['base_isa']['verdict']==I.NOT_MEASURED
    assert rec['rows'][0]['verdict']=='NOT_EXECUTED'
    assert rec['cases']['base_isa']['coverage']['uncovered']==['ecall','ebreak']


def test_flow_system_privileged_instructions_do_not_admit_general_or_unknown_csr():
    import inspect
    dis='   0: 30529073 csrrw zero,mtvec,t0\n   4: 00000073 ecall\n   8: 30200073 mret\n'
    assert I.objdump_guard(dis,allow_compressed=False)
    # The finite generated-program API is the only narrowed environment.
    if 'system_obligation' not in inspect.signature(I.objdump_guard).parameters:
        assert not I.objdump_guard(dis,allow_compressed=False), 'SOURCE_DECLINED: legitimate finite SYSTEM environment'
    assert not I.objdump_guard(dis,allow_compressed=False,system_obligation='ecall')
    bad=dis+'   c: 34029073 csrrw zero,mscratch,t0\n'
    assert I.objdump_guard(bad,allow_compressed=False,system_obligation='ecall')
    assert I.objdump_guard(dis,allow_compressed=False,system_obligation='ebreak')



@pytest.mark.parametrize("latency,wrong_address", [
    (0, False), (1, False), (2, False), (0, True),
], ids=["async0", "sync1", "pipeline2", "wrong-address"])
def test_native_sram_read_latency_from_generated_parent(
        tmp_path, latency, wrong_address):
    """Public #3108's SRAM contract, not an ISA-suite qualification.

    Declaration/ports, renderer, Icarus and strict transcript/tohost judge are
    real. Reference rc0 is a SOURCE_CONTROL input to that existing judge; no
    instruction-suite acquisition, reference emulator or owner RTL is used.
    """
    import subprocess
    project = _project(
        tmp_path, units=("I",), memsize_bytes=16, rf_storage="flops",
        sram_interface_protocol=(
            "sdp8_raddr_waddr_wdata_rdata_we_sync" + str(latency) + "r"))
    address = 2 if wrong_address else 1
    rtl = f"""`timescale 1ns/1ps
module soc_top #(parameter memsize=16, parameter aw=$clog2(memsize)) (
  input wire clk_i, input wire rst_i,
  output wire [aw-1:0] o_m_waddr, output wire [7:0] o_m_wdata,
  output wire o_m_wen, output wire [aw-1:0] o_m_raddr,
  input wire [7:0] i_m_rdata, output wire o_m_ren, output wire o_led);
  reg [aw-1:0] address=0;
  reg write_enable=0;
  integer beat;
  assign o_m_waddr=8;
  assign o_m_wdata=1;
  assign o_m_wen=write_enable;
  assign o_m_raddr=address;
  assign o_m_ren=1;
  assign o_led=0;
  initial begin
    wait (rst_i === 1'b0);
    #1;
    if (i_m_rdata !== 8'h19) begin
      $display("INITIAL_VALUE_FAIL actual=%02x expected=19", i_m_rdata);
      $fatal(1);
    end
    #1 address={address};
    #1;
    if ({latency} == 0) begin
      if (i_m_rdata !== 8'ha6) begin
        $display("ASYNC0_VALUE_FAIL actual=%02x expected=a6 at=%0t", i_m_rdata, $time);
        $fatal(1);
      end
    end else begin
      if (i_m_rdata !== 8'h19) begin
        $display("CLOCKED_READ_DID_NOT_HOLD actual=%02x expected=19", i_m_rdata);
        $fatal(1);
      end
      for (beat=1; beat<={latency}; beat=beat+1) begin
        @(posedge clk_i); #1;
        if (beat < {latency} && i_m_rdata !== 8'h19) begin
          $display("PIPELINE_READ_EARLY actual=%02x expected=19", i_m_rdata);
          $fatal(1);
        end
        if (beat == {latency} && i_m_rdata !== 8'ha6) begin
          $display("CLOCKED_READ_VALUE_FAIL actual=%02x expected=a6", i_m_rdata);
          $fatal(1);
        end
      end
    end
    $display("SRAM_READ_VALUE_PASS latency={latency} initial=19 next=%02x", i_m_rdata);
    @(negedge clk_i); write_enable=1;
    @(posedge clk_i); #1 write_enable=0;
  end
endmodule
"""
    dut = project / "phase2/stage1/rtl/soc_top.v"
    dut.write_text(rtl)
    facts, why = I.design_facts(project)
    assert facts is not None, why
    assert facts["sram"]["read_latency"] == latency
    work = tmp_path / "native"
    work.mkdir()
    parent = work / "isa_tb.v"
    parent.write_text(I.gen_tb(facts))
    memory = bytes([0x19, 0xa6] + [0] * 14)
    (work / "memory.hex").write_text("\n".join(f"{b:02x}" for b in memory) + "\n")
    compile_argv = ["iverilog", "-g2012", "-s", "isa_tb", "-o", "sim",
                    str(parent), str(dut)]
    compiled = subprocess.run(compile_argv, cwd=work, capture_output=True, text=True)
    assert compiled.returncode == 0, (compiled.stdout, compiled.stderr)
    sim_argv = ["vvp", "sim", "+hex=memory.hex", "+tohost=8"]
    simulated = subprocess.run(sim_argv, cwd=work, capture_output=True, text=True)
    parsed = I.parse_tb_transcript(simulated.stdout)
    verdict, reason = I.judge_tohost(0, parsed)
    values = {
        "scope": "native SRAM renderer component; reference rc SOURCE_CONTROL",
        "latency": latency, "wrong_address": wrong_address,
        "facts": facts, "memory_sha256": _sha(memory),
        "dut_sha256": _sha(dut.read_bytes()), "parent_sha256": _sha(parent.read_bytes()),
        "compile": {"argv": compile_argv, "returncode": compiled.returncode,
                    "stdout": compiled.stdout, "stderr": compiled.stderr},
        "simulation": {"argv": sim_argv, "returncode": simulated.returncode,
                       "stdout": simulated.stdout, "stderr": simulated.stderr},
        "strict_consumer": {"parsed": parsed, "verdict": verdict, "reason": reason},
    }
    (work / "native-values.json").write_text(json.dumps(values, indent=2) + "\n")
    assert simulated.returncode == (1 if wrong_address else 0), values
    assert verdict == (I.FAIL if wrong_address else I.PASS), values
    if wrong_address:
        assert "ASYNC0_VALUE_FAIL" in simulated.stdout, values
    else:
        assert f"SRAM_READ_VALUE_PASS latency={latency}" in simulated.stdout, values
        assert parsed["tohost"] == 1, values


_FIVE_ROLE_PROTOCOLS = ("sdp8_raddr_waddr_wdata_rdata_we_sync0r",
                        "registered_dual_port_8bit_async_read_sync_write")

_SINGLE_PORT_PROTOCOL = "registered_single_port_8bit_async_read_sync_write"


def _single_port_project(tmp_path, mutation=None):
    project = _five_role_project(tmp_path, _FIVE_ROLE_PROTOCOLS[0],
                                 "wrong_address" if mutation == "wrong_address" else None)
    path = project / "plugin_output/declaration.json"
    decl = json.loads(path.read_text())
    decl["sram_interface_protocol"] = _SINGLE_PORT_PROTOCOL
    roles = decl["sram_interface"]
    roles["read_address"] = roles["write_address"] = "o_mem_addr"
    rtl = project / "phase2/stage1/rtl/soc_top.v"
    text = rtl.read_text().replace(
        "output wire [aw-1:0] o_mem_raddr, output wire [aw-1:0] o_mem_waddr,",
        "output wire [aw-1:0] o_mem_addr,").replace(
        "assign o_mem_raddr=address; assign o_mem_waddr=8;",
        "assign o_mem_addr=write_enable ? 8 : address;")
    if mutation == "missing_role":
        roles.pop("write_address")
    elif mutation == "split_address":
        roles["write_address"] = "o_other_addr"
        text = text.replace("output wire [aw-1:0] o_mem_addr,",
                            "output wire [aw-1:0] o_mem_addr, output wire [aw-1:0] o_other_addr,")
    elif mutation == "wrong_width":
        text = text.replace("input wire [7:0] i_mem_data", "input wire [3:0] i_mem_data")
    elif mutation == "synchronous_read":
        roles["read_latency_cycles"] = 1
    elif mutation == "data_alias":
        roles["write_data"] = "o_mem_addr"
    elif mutation == "unknown_protocol":
        decl["sram_interface_protocol"] = "unregistered_memory_guess"
    path.write_text(json.dumps(decl, indent=2))
    rtl.write_text(text)
    return project


def test_single_port_memory_binds_one_address_for_both_owning_readers(tmp_path):
    import testbench_gen as tb
    import reset_invariant_oracle_tb_gen as retention
    project = _single_port_project(tmp_path)
    facts, why = I.design_facts(project)
    top, ports, _ = tb.resolve_dut(project, "soc_top")
    memory, reason = retention.declared_retention_memory(project, top,
        [(n, w) for d, w, n in ports if d == "input"],
        [(n, w) for d, w, n in ports if d == "output"])
    assert facts is not None and memory is not None, (why, reason)
    assert facts["sram_ports"]["raddr"] == facts["sram_ports"]["waddr"] == "o_mem_addr"
    assert memory["raddr"] == memory["waddr"] == "o_mem_addr"
    assert facts["sram"]["read_latency"] == 0


@pytest.mark.parametrize("mutation", ["missing_role", "split_address", "wrong_width",
    "synchronous_read", "data_alias", "unknown_protocol"])
def test_single_port_contract_refuses_unsupported_or_ambiguous_binding(tmp_path, mutation):
    facts, why = I.design_facts(_single_port_project(tmp_path, mutation))
    assert facts is None and why, (mutation, facts, why)


@pytest.mark.parametrize("protocol", ["single_port_8bit_async_read_posedge_write",
    "registered_single_port_8bit_async_read_sync_write"], ids=["address-only", "semantic-alias"])
def test_single_port_typed_contracts_refuse_mixed_address_shapes(tmp_path, protocol):
    import testbench_gen as tb
    import reset_invariant_oracle_tb_gen as retention
    project = _single_port_project(tmp_path)
    path = project / "plugin_output/declaration.json"
    decl = json.loads(path.read_text())
    decl["sram_interface_protocol"] = protocol
    decl["sram_interface"]["address"] = decl["sram_interface"]["read_address"]
    path.write_text(json.dumps(decl))
    facts, why = I.design_facts(project)
    top, ports, _ = tb.resolve_dut(project, "soc_top")
    memory, reason = retention.declared_retention_memory(project, top,
        [(n, w) for d, w, n in ports if d == "input"],
        [(n, w) for d, w, n in ports if d == "output"])
    assert facts is None and why, (protocol, facts, why)
    assert memory is None and reason, (protocol, memory, reason)


@pytest.mark.parametrize("wrong_address", [False, True], ids=["correct", "wrong-address"])
def test_native_single_port_parent_observes_async_bytes_and_real_writes(tmp_path, wrong_address):
    import subprocess
    project = _single_port_project(tmp_path, "wrong_address" if wrong_address else None)
    facts, why = I.design_facts(project)
    assert facts is not None, why
    work = tmp_path / "native-single"
    work.mkdir()
    parent = work / "isa_tb.v"
    parent.write_text(I.gen_tb(facts))
    dut = project / "phase2/stage1/rtl/soc_top.v"
    (work / "memory.hex").write_text("\n".join(f"{b:02x}" for b in [0x19, 0xa6] + [0] * 14) + "\n")
    cp = subprocess.run(["iverilog", "-g2012", "-s", "isa_tb", "-o", "sim", str(parent), str(dut)],
                        cwd=work, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    run = subprocess.run(["vvp", "sim", "+hex=memory.hex", "+tohost=8"],
                         cwd=work, capture_output=True, text=True)
    verdict, why = I.judge_tohost(0, I.parse_tb_transcript(run.stdout))
    assert run.returncode == (1 if wrong_address else 0), run.stdout + run.stderr
    assert verdict == (I.FAIL if wrong_address else I.PASS), (why, run.stdout)
    assert ("ASYNC0_VALUE_FAIL" if wrong_address else "FIVE_ROLE_ASYNC_VALUE_PASS") in run.stdout


def _five_role_project(tmp_path, protocol, mutation=None):
    project = _project(tmp_path, units=("I",), memsize_bytes=16, rf_storage="flops",
                       sram_interface_protocol=protocol)
    decl_path = project / "plugin_output/declaration.json"
    decl = json.loads(decl_path.read_text())
    decl["sram_interface"] = {"read_address": "o_mem_raddr", "write_address": "o_mem_waddr",
        "write_data": "o_mem_data", "read_data": "i_mem_data", "write_enable": "o_mem_we",
        "read_latency_cycles": 0}
    rtl = """`timescale 1ns/1ps
module soc_top #(parameter memsize=16, parameter aw=$clog2(memsize)) (
 input wire clk_i, input wire rst_i, input wire [7:0] i_mem_data,
 output wire [aw-1:0] o_mem_raddr, output wire [aw-1:0] o_mem_waddr,
 output wire [7:0] o_mem_data, output wire o_mem_we);
 reg [aw-1:0] address=0;
 reg write_enable=0;
 assign o_mem_raddr=address; assign o_mem_waddr=8;
 assign o_mem_data=1; assign o_mem_we=write_enable;
 initial begin
  wait(rst_i===1'b0); #1;
  if(i_mem_data!==8'h19) $fatal(1,"INITIAL_VALUE_FAIL actual=%02x",i_mem_data);
  #1 address=NEXT_ADDRESS; #1;
  if(i_mem_data!==8'ha6) $fatal(1,"ASYNC0_VALUE_FAIL actual=%02x expected=a6",i_mem_data);
  $display("FIVE_ROLE_ASYNC_VALUE_PASS initial=19 next=%02x",i_mem_data);
  @(negedge clk_i); write_enable=1;
  @(posedge clk_i); #1 write_enable=0;
 end
endmodule
""".replace("NEXT_ADDRESS", "2" if mutation == "wrong_address" else "1")
    if mutation == "missing_role":
        decl["sram_interface"].pop("write_address")
    elif mutation == "foreign_data":
        rtl = rtl.replace("i_mem_data", "i_other_data")
    elif mutation == "wrong_width":
        rtl = rtl.replace("input wire [7:0] i_mem_data", "input wire [3:0] i_mem_data")
    elif mutation == "sync_retention":
        decl["sram_interface"]["read_latency_cycles"] = 1
    elif mutation == "unknown_commit":
        decl["sram_interface_protocol"] = "unstated_external_memory_commit"
    elif mutation == "missing_clock":
        decl["clock_port_name"] = "missing_clk"
    elif mutation == "ambiguous_reset":
        rtl = rtl.replace("input wire rst_i,", "input wire rst_i, input wire reset_other,")
    decl_path.write_text(json.dumps(decl, indent=2))
    (project / "phase2/stage1/rtl/soc_top.v").write_text(rtl)
    return project


@pytest.mark.parametrize("protocol", _FIVE_ROLE_PROTOCOLS, ids=["sdp-five", "canonical-five"])
def test_explicit_five_role_contract_binds_the_same_actual_ports_for_both_readers(tmp_path, protocol):
    import testbench_gen as tb
    import reset_invariant_oracle_tb_gen as retention
    project = _five_role_project(tmp_path, protocol)
    facts, why = I.design_facts(project)
    top, ports, detail = tb.resolve_dut(project, "soc_top")
    memory, reason = retention.declared_retention_memory(project, top,
        [(n,w) for d,w,n in ports if d == "input"], [(n,w) for d,w,n in ports if d == "output"])
    print("FIVE_ROLE_BINDING " + json.dumps({"protocol": protocol, "isa_admitted": facts is not None,
          "isa_reason": why, "retention_admitted": memory is not None, "retention_reason": reason}))
    assert (facts is not None, memory is not None) == (True, True), (why, reason)
    assert facts["sram"]["read_latency"] == 0
    assert "ren" not in facts["sram_ports"]
    assert facts["sram_ports"] == {"raddr": memory["raddr"], "waddr": memory["waddr"],
        "wdata": memory["wdata"], "rdata": memory["rdata"], "wen": memory["we"]}
    assert memory["depth"] == 16


@pytest.mark.parametrize("mutation", ["missing_role", "foreign_data", "wrong_width",
                                      "sync_retention", "unknown_commit", "missing_clock", "ambiguous_reset"])
def test_explicit_five_role_admission_retains_named_refusals(tmp_path, mutation):
    project = _five_role_project(tmp_path, _FIVE_ROLE_PROTOCOLS[0], mutation)
    facts, why = I.design_facts(project)
    assert facts is None and why, (mutation, facts, why)


@pytest.mark.parametrize("protocol", _FIVE_ROLE_PROTOCOLS, ids=["sdp-five", "canonical-five"])
@pytest.mark.parametrize("wrong_address", [False, True], ids=["correct", "wrong-address"])
def test_native_five_role_parent_consumes_async_bytes_and_tohost(tmp_path, protocol, wrong_address):
    import subprocess
    project = _five_role_project(tmp_path, protocol, "wrong_address" if wrong_address else None)
    facts, why = I.design_facts(project)
    assert facts is not None, why
    work = tmp_path / "native-five"
    work.mkdir()
    parent = work / "isa_tb.v"
    parent.write_text(I.gen_tb(facts))
    dut = project / "phase2/stage1/rtl/soc_top.v"
    memory = bytes([0x19,0xa6]+[0]*14)
    (work / "memory.hex").write_text("\n".join(f"{b:02x}" for b in memory)+"\n")
    compile_argv = ["iverilog", "-g2012", "-s", "isa_tb", "-o", "sim", str(parent), str(dut)]
    cp = subprocess.run(compile_argv, cwd=work, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    run_argv = ["vvp", "sim", "+hex=memory.hex", "+tohost=8"]
    run = subprocess.run(run_argv, cwd=work, capture_output=True, text=True)
    parsed = I.parse_tb_transcript(run.stdout)
    verdict, why = I.judge_tohost(0, parsed)
    values = {"scope": "self-authored native SRAM/tohost component; reference rc SOURCE_CONTROL",
        "protocol": protocol, "wrong_address": wrong_address,
        "dut_sha256": _sha(dut.read_bytes()), "parent_sha256": _sha(parent.read_bytes()),
        "memory_sha256": _sha(memory), "compile": {"argv": compile_argv, "rc": cp.returncode,
        "stdout": cp.stdout, "stderr": cp.stderr}, "run": {"argv": run_argv, "rc": run.returncode,
        "stdout": run.stdout, "stderr": run.stderr}, "consumer": {"verdict": verdict, "reason": why}}
    (work / "native-values.json").write_text(json.dumps(values, indent=2)+"\n")
    assert run.returncode == (1 if wrong_address else 0), values
    assert verdict == (I.FAIL if wrong_address else I.PASS), values
    assert ("ASYNC0_VALUE_FAIL" if wrong_address else "FIVE_ROLE_ASYNC_VALUE_PASS") in run.stdout, values


# #3130: acquisition bytes are source inputs, its cited archive is an output.
# The existing executor/network fixtures are SOURCE_CONTROL, not native CPU
# observations. The producer, credit reader, report writer and storage CLI are real.
def _3130_cache(tmp_path, monkeypatch, mode):
    import os
    import gzip
    # The archive input must be byte-identical across independent QA arms.
    monkeypatch.setitem(globals(), 'TARBALL',
                        gzip.compress(gzip.decompress(TARBALL), mtime=0))
    # Fleet measurement may retain these observations in caller-owned roots,
    # but an ordinary suite invocation must remain self-contained.  The prior
    # fixture made both variables undeclared mandatory inputs and all eleven
    # controls failed before exercising acquisition or storage.
    alias = os.environ.get('ISSUE3130_VOLATILE_ALIAS')
    base = ((Path(alias) / tmp_path.name) if alias
            else (tmp_path / 'volatile-alias'))
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(I.tempfile, 'gettempdir', lambda: str(base))
    monkeypatch.delenv('VIBEIC_ISA_SUITE_CACHE', raising=False)
    if mode == 'custom':
        monkeypatch.setenv('VIBEIC_ISA_SUITE_CACHE', str(base / 'chosen-cache'))
    if mode != 'cold':
        cache = I.cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        (cache / ('f' * 40 + '.tar.gz')).write_bytes(TARBALL)
    return base


def _3130_storage(project, output):
    import subprocess
    command = [sys.executable, str(PROGRAMS / 'project_outputs_in_tree_check.py'),
               str(project), '--json', str(output)]
    proc = subprocess.run(command, text=True, capture_output=True)
    return {'argv': command, 'rc': proc.returncode, 'stdout': proc.stdout,
            'stderr': proc.stderr, 'report': json.loads(output.read_text())}


def _3130_observed(tmp_path, value):
    import os
    values = os.environ.get('ISSUE3130_VALUES_DIR')
    folder = Path(values) if values else tmp_path / 'observed-values'
    folder.mkdir(parents=True, exist_ok=True)
    value['input'] = {'tarball_sha256': _sha(TARBALL),
                      'files': {k: _sha(v) for k, v in FILES.items()},
                      'lock': _lock()}
    (folder / (tmp_path.name + '.json')).write_text(json.dumps(value, indent=2))


@pytest.mark.parametrize('mode', ['warm', 'cold', 'custom'])
def test_isa_acquisition_keeps_current_project_archive_through_credit_and_storage(
        tmp_path, monkeypatch, mode):
    import subprocess
    _3130_cache(tmp_path, monkeypatch, mode)
    p = _project(tmp_path)
    archive = p / '.vibeic-state/isa-suite-cache' / ('f' * 40 + '.tar.gz')
    observations = []
    for attempt in range(2):
        _step4(p, monkeypatch, {'s-add': OVERSIZED, 's-fencei': OVERSIZED})
        credit, refusal = _base_isa_credit(p)
        assert refusal is None and credit is not None, refusal
        report = p / 'reports/phase2/gates/cpu_functional_oracle_waiver.json'
        proc = subprocess.run([sys.executable,
            str(PROGRAMS / 'cpu_functional_oracle_waiver_check.py'), str(p),
            '--json', str(report)], text=True, capture_output=True)
        doc = json.loads(report.read_text())
        # This fixture leaves other CPU obligations incomplete. A storage fix
        # must not turn the unrelated complete CPU verdict into PASS.
        assert proc.returncode != 0
        actual_credit = doc['isa_conformance_credit']['credited']
        assert any(c['suite_pins'] == credit['suite_pins'] for c in actual_credit)
        storage = _3130_storage(p, tmp_path / f'storage-{attempt}.json')
        observations.append({'suite_pins': credit['suite_pins'], 'storage': storage,
            'cpu_rc': proc.returncode, 'cpu_verdict': doc['verdict'],
            'archive_sha256': _sha(archive.read_bytes()) if archive.is_file() else None})
    _3130_observed(tmp_path, {'mode': mode, 'attempts': observations,
        'archive': str(archive), 'locked_archive_sha256': _sha(TARBALL)})
    assert [o['storage']['rc'] for o in observations] == [0, 0]
    assert archive.read_bytes() == TARBALL
    assert I.verify_tarball(archive.read_bytes(), _lock()['suites']['s'])[0]
    assert all(str(archive) in o['suite_pins'][0] for o in observations)


@pytest.mark.parametrize('use_cache', [True, False])
def test_direct_acquisition_keeps_the_archive_beside_its_verified_output(
        tmp_path, monkeypatch, use_cache):
    _3130_cache(tmp_path, monkeypatch, 'warm')
    p = tmp_path / 'project'
    dest = p / '.vibeic-state/acquired'
    root, why = I.acquire('s', _lock()['suites']['s'], dest,
                          fetch=lambda _u: TARBALL, use_cache=use_cache)
    assert root is not None
    report = p / 'reports/acquisition.json'
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'suite_pin': why}))
    storage = _3130_storage(p, tmp_path / 'storage.json')
    archive = dest / ('f' * 40 + '.tar.gz')
    _3130_observed(tmp_path, {'why': why, 'storage': storage,
        'archive_sha256': _sha(archive.read_bytes()) if archive.is_file() else None})
    assert storage['rc'] == 0, storage
    assert archive.read_bytes() == TARBALL
    assert {str(f.relative_to(root)): _sha(f.read_bytes()) for f in root.rglob('*')
            if f.is_file()} == _lock()['suites']['s']['files']


@pytest.mark.parametrize('bad', ['tarball', 'member'])
def test_acquisition_refuses_changed_locked_bytes_before_archive_publication(
        tmp_path, monkeypatch, bad):
    _3130_cache(tmp_path, monkeypatch, 'cold')
    suite = _lock()['suites']['s']
    blob = TARBALL + b'drift' if bad == 'tarball' else TARBALL
    if bad == 'member':
        suite['files']['src/add-01.S'] = '0' * 64
    dest = tmp_path / 'project/.vibeic-state/acquired'
    root, why = I.acquire('s', suite, dest, fetch=lambda _u: blob, use_cache=False)
    _3130_observed(tmp_path, {'root': str(root) if root else None, 'why': why})
    assert root is None and 'sha256' in why
    assert not (dest / (suite['commit'] + '.tar.gz')).exists()


@pytest.mark.parametrize('live', [True, False])
def test_storage_still_refuses_uncopied_live_or_dangling_volatile_archive(
        tmp_path, monkeypatch, live):
    base = _3130_cache(tmp_path, monkeypatch, 'cold')
    external = base / 'uncopied.tar.gz'
    if live:
        external.write_bytes(TARBALL)
    p = tmp_path / 'project'
    report = p / 'reports/acquisition.json'
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'suite_pin': f'cache {external}'}))
    storage = _3130_storage(p, tmp_path / 'storage.json')
    _3130_observed(tmp_path, {'storage': storage, 'live': live})
    assert storage['rc'] == 1
    assert any(f['path'] == str(external) and f['class'] == ('live' if live else 'dangling')
               for f in storage['report']['flagged'])


def test_unpreservable_project_archive_refuses_before_cpu_executor(
        tmp_path, monkeypatch):
    _3130_cache(tmp_path, monkeypatch, 'warm')
    p = _project(tmp_path)
    blocked = p / '.vibeic-state/isa-suite-cache'
    blocked.parent.mkdir(parents=True)
    blocked.write_text('a file is not an archive directory')
    calls = []
    execute = _fake_executor({'s-add': OVERSIZED, 's-fencei': OVERSIZED})
    def executor(job, work):
        calls.append(str(job))
        return execute(job, work)
    rec = I.produce(p, executor=executor, fetch=lambda _u: TARBALL,
                    lock=_lock(), pol=ALLOW, work_root=tmp_path / 'work')
    _3130_observed(tmp_path, {'refusal': rec['refusal'], 'executor_calls': calls,
                             'rows': rec['rows']})
    assert calls == []
    assert 'preserve' in rec['refusal'] and 'archive' in rec['refusal']
    assert {r['verdict'] for r in rec['rows']} == {'NOT_EXECUTED'}


def test_a_changed_retained_archive_is_republished_from_verified_input(
        tmp_path, monkeypatch):
    _3130_cache(tmp_path, monkeypatch, 'warm')
    dest = tmp_path / 'project/.vibeic-state/acquired'
    archive = dest / ('f' * 40 + '.tar.gz')
    first, why = I.acquire('s', _lock()['suites']['s'], dest,
                           fetch=lambda _u: TARBALL)
    assert first is not None
    before = _sha(archive.read_bytes()) if archive.is_file() else None
    archive.write_bytes(b'changed retained bytes')
    second, why = I.acquire('s', _lock()['suites']['s'], dest,
                            fetch=lambda _u: TARBALL)
    after = _sha(archive.read_bytes())
    _3130_observed(tmp_path, {'before': before, 'after': after, 'why': why})
    assert second is not None and before == after == _sha(TARBALL)
