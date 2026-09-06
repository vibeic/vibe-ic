"""#2050 item 4 — the receipt convention is written by the PRODUCER.

WHAT WAS MEASURED, on v1.17.79 (8982e264689a). Four auditors named by a
compliance.yaml wrote their report to a caller-chosen `--json PATH`, so no
filename existed for `_cc_audit_receipt_evidence` to look for and all four were
listed in `UNREGISTERED_AUDITORS`, where they BLOCK with a configuration error::

    gds_size_check   synth_netlist_check   tapeout_signoff_check
    fpga_async_input_synchronizer_check

#2048 refused to invent a filename inside the CHECKER, which was right: a
consumer that guesses where its evidence lives is guessing. `_audit_receipt.py`
closes it from the producing side instead — each of them now writes
`<auditor>_receipt.json` as a sibling of the caller's own `--json`, carrying the
auditor name, the verdict, how many items were examined, and a SUBJECT DIGEST.

Every assertion below is written in both directions. The digest is the reason:
without it a receipt only proves that SOME run of the auditor passed, and a
stale receipt beside a new report reads exactly like a fresh one.

Every receipt here is produced by RUNNING the real program on a synthetic
input built in `tmp_path`; none is hand-written to the shape the checker
wants, because a hand-written receipt would test the test.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[2]
_PROGRAMS = _PLUGIN / "programs"
_CHECKER = _PLUGIN / "_shared" / "skill_compliance_check.py"

sys.path.insert(0, str(_PLUGIN / "_shared"))
sys.path.insert(0, str(_PROGRAMS))
import skill_compliance_check as scc  # noqa: E402
import _audit_receipt as ar  # noqa: E402

# A GDSII HEADER record (0x0002) followed by enough bytes to clear the
# program's default 100 KB floor. Synthetic: it is not a layout.
_GDS_BYTES = b"\x00\x06\x00\x02\x00\x05" + b"\x00" * 200_000


def _run(program: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_PROGRAMS / program), *args],
                          capture_output=True, text=True)


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------
def test_receipt_lands_beside_the_callers_json_under_one_fixed_name(tmp_path):
    out = tmp_path / "reports" / "audit.json"
    p = ar.emit_receipt("gds_size_check", out, "PASS", 1, [])
    assert p == tmp_path / "reports" / "gds_size_check_receipt.json"
    assert p.is_file()
    assert json.loads(p.read_text())["auditor"] == "gds_size_check"


def test_no_json_asked_for_means_no_receipt_and_no_crash(tmp_path):
    """NOT_MEASURED is the honest downstream state, so returning None is the
    honest upstream one. Inventing a location would be the guess this whole
    mechanism exists to avoid."""
    assert ar.emit_receipt("gds_size_check", None, "PASS", 1, []) is None


def test_an_unwritable_receipt_degrades_loudly_and_never_raises(tmp_path,
                                                                capsys):
    blocker = tmp_path / "blocked"
    blocker.write_text("I am a file, not a directory")
    assert ar.emit_receipt("gds_size_check", blocker / "a" / "out.json",
                           "PASS", 1, []) is None
    assert "NO RECEIPT WRITTEN" in capsys.readouterr().err


def test_subject_digest_is_content_addressed_not_path_addressed(tmp_path):
    """Same bytes under two different directories -> same digest, so a
    compliance.yaml can pin one and it still means something in another
    checkout. Different bytes -> different digest, which is the whole point."""
    a = tmp_path / "a"; a.mkdir(); (a / "d.gds").write_bytes(b"xxxx")
    b = tmp_path / "b"; b.mkdir(); (b / "d.gds").write_bytes(b"xxxx")
    c = tmp_path / "c"; c.mkdir(); (c / "d.gds").write_bytes(b"yyyy")
    assert ar.subject_of([a / "d.gds"])["sha256"] == \
        ar.subject_of([b / "d.gds"])["sha256"]
    assert ar.subject_of([a / "d.gds"])["sha256"] != \
        ar.subject_of([c / "d.gds"])["sha256"]


def test_a_directory_subject_says_its_digest_did_not_witness_bytes(tmp_path):
    """`basis` is stated, never assumed. A path-basis digest still separates
    one subject from another; it does not witness content, and says so."""
    assert ar.subject_of([tmp_path])["basis"] == ar.BASIS_PATH
    f = tmp_path / "x.v"; f.write_text("module x; endmodule\n")
    assert ar.subject_of([f])["basis"] == ar.BASIS_CONTENT


def test_argument_order_does_not_change_the_digest(tmp_path):
    x = tmp_path / "x.v"; x.write_text("a")
    y = tmp_path / "y.v"; y.write_text("b")
    assert (ar.subject_of([x, y])["sha256"]
            == ar.subject_of([y, x])["sha256"])


# ---------------------------------------------------------------------------
# The four producers, run for real
# ---------------------------------------------------------------------------
def test_gds_size_check_writes_its_own_receipt(tmp_path):
    gds = tmp_path / "design.gds"
    gds.write_bytes(_GDS_BYTES)
    out = tmp_path / "reports" / "gds.json"
    r = _run("gds_size_check.py", "--gds-file", str(gds), "--json", str(out))
    assert r.returncode == 0, r.stderr
    rec = json.loads((out.parent / "gds_size_check_receipt.json").read_text())
    assert rec["auditor"] == "gds_size_check"
    assert rec["verdict"] == "PASS"
    # The declared population is the ONE path named on the command line, so it
    # is never zero: an absent file is a measured FAIL over that path, not an
    # audit of nothing.
    assert rec["examined"] == 1
    assert rec["subject"]["sha256"] == ar.subject_of([gds])["sha256"]


def test_gds_size_check_receipt_records_the_failure_too(tmp_path):
    out = tmp_path / "reports" / "gds.json"
    r = _run("gds_size_check.py", "--gds-file", str(tmp_path / "absent.gds"),
             "--json", str(out))
    assert r.returncode == 1
    rec = json.loads((out.parent / "gds_size_check_receipt.json").read_text())
    assert rec["verdict"] == "FAIL"


def test_synth_netlist_check_receipt_covers_the_rtl_it_was_judged_against(
        tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input a, output b); assign b = a; endmodule\n")
    netlist = tmp_path / "top_syn.v"
    netlist.write_text(
        "module top(input a, output b);\n"
        + "".join(f"  BUF _{i}_ (.A(a), .Y(b));\n" for i in range(40))
        + "endmodule\n")
    out = tmp_path / "reports" / "synth.json"
    _run("synth_netlist_check.py", "--netlist", str(netlist),
         "--rtl", str(rtl), "--json", str(out))
    rec = json.loads((out.parent / "synth_netlist_check_receipt.json").read_text())
    assert rec["auditor"] == "synth_netlist_check"
    # A receipt taken before an RTL edit must not read as backing for the
    # netlist after it, so the RTL is IN the subject.
    assert rec["subject"]["sha256"] == ar.subject_of([netlist, rtl])["sha256"]
    assert rec["subject"]["sha256"] != ar.subject_of([netlist])["sha256"]


def test_fpga_async_receipt_counts_the_files_it_read(tmp_path):
    rtl = tmp_path / "rtl"; rtl.mkdir()
    (rtl / "top.v").write_text(
        "module top(input clk, input rst_n, input dat, output q);\n"
        "reg s1, s2; always @(posedge clk) begin s1 <= dat; s2 <= s1; end\n"
        "assign q = s2;\nendmodule\n")
    out = tmp_path / "reports" / "async.json"
    _run("fpga_async_input_synchronizer_check.py", str(rtl),
         "--top", "top", "--json", str(out))
    rec = json.loads(
        (out.parent
         / "fpga_async_input_synchronizer_check_receipt.json").read_text())
    assert rec["examined"] == 1
    assert rec["verdict"] in ("PASS", "FAIL")


def test_fpga_async_over_an_empty_tree_is_not_measured_not_clean(tmp_path):
    """A verdict over zero files is an audit of nothing. The program returns
    PASS there; the receipt records examined=0 and the compliance checker
    turns that into NOT_MEASURED rather than a clean design."""
    empty = tmp_path / "rtl"; empty.mkdir()
    out = tmp_path / "reports" / "async.json"
    _run("fpga_async_input_synchronizer_check.py", str(empty),
         "--top", "top", "--json", str(out))
    rec = json.loads(
        (out.parent
         / "fpga_async_input_synchronizer_check_receipt.json").read_text())
    assert rec["examined"] == 0
    assert rec["verdict"] == "PASS", "the program itself passes here"
    spec = {"id": "X", "rule": "audit_receipt_evidence",
            "auditor": "fpga_async_input_synchronizer_check"}
    ctx = scc.CheckContext(output_path=out.parent / "report.md")
    f, = scc._cc_audit_receipt_evidence(spec, "", ctx)
    assert (f.severity, f.state) == ("FAIL", scc.STATE_NOT_MEASURED)


def test_tapeout_signoff_shim_reads_back_what_signoff_audit_wrote(tmp_path):
    project = tmp_path / "proj"; project.mkdir()
    out = tmp_path / "reports" / "tapeout.json"
    sys.path.insert(0, str(_PROGRAMS))
    import tapeout_signoff_check as tsc
    tsc.run([str(project), "--json", str(out)])
    rec = json.loads((out.parent
                      / "tapeout_signoff_check_receipt.json").read_text())
    written = json.loads(out.read_text())
    assert rec["auditor"] == "tapeout_signoff_check"
    # The receipt is READ BACK from the audit it certifies, so the two can
    # never disagree — the shim never sees the AuditResult, only an rc.
    assert (rec["verdict"] == "PASS") == bool(written["passed"])
    assert rec["detail"]["program"] == written["program"]


def test_a_waived_tapeout_pass_keeps_its_own_spelling():
    """rule 11: PASS_WITH_WAIVERS must not collapse onto a bare PASS. The
    checker's line is `== 'PASS'`, so the waived tier lands non-PASS."""
    rs = scc.AUDIT_RECEIPTS["tapeout_signoff_check"]
    assert rs.verdict({"verdict": "PASS_WITH_WAIVERS"}) == scc.STATE_FAIL
    assert rs.verdict({"verdict": "PASS"}) == scc.STATE_PASS


# ---------------------------------------------------------------------------
# The checker end of the contract — the control the issue asks for
# ---------------------------------------------------------------------------
def _drive(tmp_path, yml_text, report_text):
    d = tmp_path / "work"; d.mkdir(parents=True, exist_ok=True)
    yml = d / "compliance.yaml"; yml.write_text(yml_text)
    rep = d / "report.md"; rep.write_text(report_text)
    oj = d / "audit.json"
    r = subprocess.run(
        [sys.executable, str(_CHECKER), "--requirements", str(yml),
         "--json", str(oj), str(rep)], capture_output=True, text=True)
    return r, json.loads(oj.read_text())


_YML = """\
skill: synthetic
output_type: report
requirements: []
cross_checks:
  - id: X_gds_size_check
    description: "GDS exists and is not trivially small"
    rule: audit_receipt_evidence
    auditor: gds_size_check
"""


def test_a_real_receipt_beside_the_report_passes(tmp_path):
    d = tmp_path / "work"; d.mkdir()
    gds = tmp_path / "design.gds"; gds.write_bytes(_GDS_BYTES)
    _run("gds_size_check.py", "--gds-file", str(gds),
         "--json", str(d / "gds.json"))
    r, data = _drive(tmp_path, _YML, "# report\n")
    st = [f for f in data["findings"] if f["id"] == "X_gds_size_check"]
    assert st and st[0]["state"] == "PASS", data["findings"]
    assert r.returncode == 0


def test_no_receipt_is_not_measured_and_blocks(tmp_path):
    r, data = _drive(tmp_path, _YML, "# report\n")
    st, = [f for f in data["findings"] if f["id"] == "X_gds_size_check"]
    assert (st["severity"], st["state"]) == ("FAIL", "NOT_MEASURED")
    assert "gds_size_check_receipt.json" in st["detail"]
    assert r.returncode == 1


def test_a_receipt_for_another_subject_is_a_fail_not_a_pass(tmp_path):
    """THE control #2050 asks for. The receipt is real, its verdict is PASS,
    and it is about a different GDS — so it backs nothing here."""
    d = tmp_path / "work"; d.mkdir()
    ours = tmp_path / "ours.gds"; ours.write_bytes(_GDS_BYTES)
    theirs = tmp_path / "theirs.gds"; theirs.write_bytes(_GDS_BYTES + b"\x01")
    _run("gds_size_check.py", "--gds-file", str(theirs),
         "--json", str(d / "gds.json"))
    yml = _YML + f"    subject:\n      sha256: {ar.subject_of([ours])['sha256']}\n"
    r, data = _drive(tmp_path, yml, "# report\n")
    st, = [f for f in data["findings"] if f["id"] == "X_gds_size_check"]
    assert (st["severity"], st["state"]) == ("FAIL", "FAIL")
    assert "different subject" in st["description"]
    assert r.returncode == 1

    # ... and the same receipt for the RIGHT subject passes, so the assertion
    # above is about the subject and not about the yaml having a `subject:` key
    # at all.
    _run("gds_size_check.py", "--gds-file", str(ours),
         "--json", str(d / "gds.json"))
    r2, data2 = _drive(tmp_path, yml, "# report\n")
    st2, = [f for f in data2["findings"] if f["id"] == "X_gds_size_check"]
    assert st2["state"] == "PASS"
    assert r2.returncode == 0


def test_another_auditors_receipt_under_this_name_is_no_evidence(tmp_path):
    d = tmp_path / "work"; d.mkdir()
    log = tmp_path / "t.log"; log.write_text("Done.\n")
    _run("eda_log_check.py", "--log-file", str(log),
         "--json", str(d / "log.json"))
    (d / "gds_size_check_receipt.json").write_text(
        (d / "eda_log_check_receipt.json").read_text())
    r, data = _drive(tmp_path, _YML, "# report\n")
    st, = [f for f in data["findings"] if f["id"] == "X_gds_size_check"]
    assert (st["severity"], st["state"]) == ("FAIL", "NOT_MEASURED")
    assert r.returncode == 1


def test_every_producer_receipt_auditor_names_a_program_that_writes_one():
    """Structural: a registered `<auditor>_receipt.json` contract is only
    honest if the named program actually CALLS the helper.

    PARSED, NOT GREPPED, and the reason is measured. This test first read the
    source for the substring `emit_receipt`. Deleting the call from
    `gds_size_check.py` and leaving its import and its comment behind — the M4
    control for this lane — kept the substring and kept this test GREEN, so it
    was passing for the import's reason, not the call's. That is the same
    exemption-by-substring shape `test_issue1417_no_test_bytecompiles_the_
    shipped_tree.py` documents. An `ast` walk for an actual Call cannot be
    satisfied by a comment, a docstring or an import line.
    """
    for name, rs in scc.AUDIT_RECEIPTS.items():
        if not rs.filename.endswith(ar.RECEIPT_SUFFIX):
            continue
        tree = ast.parse((_PROGRAMS / f"{name}.py").read_text())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and ((isinstance(n.func, ast.Name)
                       and n.func.id == "emit_receipt")
                      or (isinstance(n.func, ast.Attribute)
                          and n.func.attr == "emit_receipt"))]
        assert calls, (
            f"{name} is registered under the producer-receipt convention but "
            "never CALLS emit_receipt — an import is not an emission")
        assert rs.filename == ar.receipt_filename(name)
