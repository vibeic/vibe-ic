#!/usr/bin/env python3
"""Independent functional consumer for an explicit pulse-width/rearm contract.

The checker only runs when the source declares all observable identities.  It
then compiles the DUT with a deterministic, bounded stimulus containing:

* one legal pulse at the declared maximum width;
* one overlong pulse held active through a legal-looking suffix; and
* one legal pulse after an inactive level and a new rising edge.

The overlong window must produce no acceptance.  The two legal windows must
each produce exactly one acceptance.  This distinguishes a timeout state that
waits for inactive-plus-new-edge from a level-sensitive implementation that
reacquires while the invalid pulse is still active.  The program never adds a
pulse rule when the source has no explicit contract.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pulse_width_rearm_contract import (  # noqa: E402
    ContractParse,
    PulseWidthRearmContract,
    extract_contract,
)
from reset_clock_variant_alias import parse_module_ports  # noqa: E402
from _atomic_artefact import write_text as atomic_write_text  # noqa: E402


_IDENT = re.compile(r"^[A-Za-z_]\w*$")
_MAX_WIDTH = 1_000_000


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_fingerprint(path: Path) -> Dict[str, Any]:
    """Return the path identity used to reject a post-measurement swap."""
    stat = path.stat()
    link_stat = path.lstat()
    return {
        "resolved_path": str(path.resolve()),
        "path_inode": int(link_stat.st_ino),
        "path_ctime_ns": int(link_stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "st_size": int(stat.st_size),
        "st_mtime_ns": int(stat.st_mtime_ns),
        "st_ctime_ns": int(stat.st_ctime_ns),
    }


def _snapshot_file(path: Path) -> Dict[str, object]:
    """Read a live input once and retain its bytes plus path identity."""
    path = Path(path)
    before = _file_fingerprint(path)
    data = path.read_bytes()
    after = _file_fingerprint(path)
    if before != after:
        raise OSError(f"input changed while being read: {path}")
    return {"path": path, "bytes": data, "sha256": _sha256_bytes(data),
            "fingerprint": after}


def _snapshot_changes(snapshots: Iterable[Dict[str, object]]) -> List[str]:
    """Re-read live paths only for the pre-publication drift check."""
    changed: List[str] = []
    for snapshot in snapshots:
        path = Path(snapshot["path"])
        try:
            before = _file_fingerprint(path)
            current_bytes = path.read_bytes()
            current = _file_fingerprint(path)
        except OSError as exc:
            changed.append(f"{path}: unavailable ({exc})")
            continue
        if (current != snapshot["fingerprint"] or
                _sha256_bytes(current_bytes) != snapshot["sha256"]):
            changed.append(f"{path}: path/metadata changed")
        elif before != current:
            changed.append(f"{path}: changed while drift was checked")
    return changed


def _publish_report(report_path: Path, report: Dict,
                    before_commit: Callable[[], None], *,
                    after_commit: Optional[Callable[[], None]] = None) -> None:
    """Atomically publish one complete receipt after all binding checks."""
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{report_path.name}.", suffix=".tmp",
        dir=str(report_path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            staged = json.dumps(report, indent=2, sort_keys=True) + "\n"
            stream.write(staged)
            stream.flush()
            os.fsync(stream.fileno())
            # The validation is after staging, immediately before replacement.
            # A changed input turns a staged PASS into an atomic refusal.
            before_commit()
            final = json.dumps(report, indent=2, sort_keys=True) + "\n"
            if final != staged:
                stream.seek(0)
                stream.truncate()
                stream.write(final)
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(temporary, report_path)
        if after_commit is not None:
            # A rename scheduler can replace inputs *inside* os.replace, after
            # the last pre-commit observation. Reconcile that observation with
            # the committed receipt. A changed PASS is atomically superseded
            # by a refusal, never silently returned to the caller.
            committed = json.dumps(report, indent=2, sort_keys=True)
            after_commit()
            if json.dumps(report, indent=2, sort_keys=True) != committed:
                _publish_report(report_path, report, lambda: None)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _module_names(text: str) -> List[str]:
    return re.findall(r"\bmodule\s+([A-Za-z_]\w*)\b", text)


def _width_decl(width: str, kind: str) -> str:
    # parse_module_ports returns a packed range or an empty string.  Keep the
    # declaration structural; an unknown parameterised range is legal SV and
    # is left untouched for iverilog to resolve from the DUT.
    return f"{kind} {width} " if width else f"{kind} "


def _build_measurement_tb(rtl_text: str, top: str,
                          contract: PulseWidthRearmContract) -> Tuple[str, Dict]:
    ports = parse_module_ports(rtl_text, top)
    by_name = {name: (direction, width) for direction, width, name in ports}
    required = (contract.clock_signal, contract.input_signal, contract.accept_output)
    missing = [name for name in required if name not in by_name]
    if contract.reset_signal and contract.reset_signal not in by_name:
        missing.append(contract.reset_signal)
    if missing:
        raise ValueError("declared contract port(s) missing from RTL: " +
                         ", ".join(sorted(set(missing))))
    # The checker is intentionally scalar at the two observable pins.  A
    # multi-bit acceptance bus is an unsupported mapping, not a guessed bit.
    for name in (contract.clock_signal, contract.input_signal,
                 contract.accept_output, contract.reset_signal):
        if name and by_name[name][1] and by_name[name][1] not in ("[0:0]", "[0 : 0]"):
            raise ValueError(f"declared pulse mapping {name!r} is not scalar")
    if by_name[contract.clock_signal][0] != "input":
        raise ValueError("declared clock_signal is not an input port")
    if by_name[contract.input_signal][0] != "input":
        raise ValueError("declared input_signal is not an input port")
    if by_name[contract.accept_output][0] not in {"output", "inout"}:
        raise ValueError("declared accept_output is not an output port")
    if contract.reset_signal and by_name[contract.reset_signal][0] != "input":
        raise ValueError("declared reset_signal is not an input port")

    declarations: List[str] = []
    connections: List[str] = []
    driven_inputs: List[str] = []
    for direction, width, name in ports:
        if direction == "input":
            kind = "reg"
            declarations.append(f"  {_width_decl(width, kind)}{name};")
            driven_inputs.append(name)
        else:
            declarations.append(f"  wire {_width_decl(width, '').strip()}{name};")
        connections.append(f".{name}({name})")

    # Source identities are the only bindings used for the actual waveform;
    # other input ports get a stable zero so an unrelated mode cannot create a
    # second, guessed protocol.
    max_w = contract.max_width_cycles
    # Two cycles are deliberate: after a level-sensitive timeout the bad
    # variant can re-acquire and present this suffix as a fresh legal pulse;
    # extending it to the maximum would let that bad variant time out a second
    # time and would erase the discriminating control.
    suffix = 2
    reset_active = "1'b0"
    reset_inactive = "1'b1"
    if contract.reset_signal and contract.reset_active_low is False:
        reset_active, reset_inactive = "1'b1", "1'b0"
    elif not contract.reset_signal:
        reset_active = reset_inactive = "1'b0"

    lines = [
        "`timescale 1ns/1ps",
        "module pulse_width_rearm_measurement_tb;",
        "  reg clk;",
    ]
    # Do not redeclare the explicitly named clock below.
    for decl in declarations:
        if re.search(rf"\b{re.escape(contract.clock_signal)}\s*;", decl):
            continue
        lines.append(decl)
    lines.extend([
        f"  always #5 {contract.clock_signal} = ~{contract.clock_signal};",
        f"  {top} dut ({', '.join(connections)});",
        "  integer legal_accepts;",
        "  integer boundary_bad_accepts;",
        "  integer bad_accepts;",
        "  integer final_accepts;",
        "  integer window; // 0=legal, 1=max+1, 2=far-overlong, 3=final legal",
        "  integer i;",
        "  task automatic cycles(input integer n);",
        "    integer j; begin for (j = 0; j < n; j = j + 1) begin @(posedge "
        f"{contract.clock_signal}); #1; end end",
        "  endtask",
        "  always @(posedge " + contract.clock_signal + ") begin",
        "    #1;",
        f"    if ({contract.accept_output} === 1'b1) begin",
        "      if (window == 0) legal_accepts = legal_accepts + 1;",
        "      else if (window == 1) boundary_bad_accepts = boundary_bad_accepts + 1;",
        "      else if (window == 2) bad_accepts = bad_accepts + 1;",
        "      else if (window == 3) final_accepts = final_accepts + 1;",
        "    end",
        "  end",
        "  integer result_fd;",
        "  string PWR_RESULT_FILE;",
        "  string PWR_BINDING;",
        "  initial begin",
        '    if (!$value$plusargs("PWR_RESULT_FILE=%s", PWR_RESULT_FILE) ||',
        '        !$value$plusargs("PWR_BINDING=%s", PWR_BINDING)) begin',
        '      $display("PWR_BINDING_MISSING"); $finish; end',
        "    result_fd = $fopen(PWR_RESULT_FILE, \"w\");",
        "    if (result_fd == 0) begin $display(\"PWR_RESULT_OPEN_FAIL\"); $finish; end",
        f"    {contract.clock_signal} = 1'b0;",
    ])
    # Drive every input to zero before the reset release.  The pulse and reset
    # are then assigned by identity, never by a spelling heuristic.
    for name in driven_inputs:
        if name != contract.clock_signal:
            lines.append(f"    {name} = 1'b0;")
    lines.extend([
        "    legal_accepts = 0; boundary_bad_accepts = 0; bad_accepts = 0; "
        "final_accepts = 0; window = -1;",
    ])
    if contract.reset_signal:
        lines.append(f"    {contract.reset_signal} = {reset_active};")
        lines.append("    cycles(2);")
        lines.append(f"    {contract.reset_signal} = {reset_inactive};")
        lines.append("    cycles(1);")
    else:
        lines.append("    cycles(3);")
    # First valid pulse: exactly max_w active clock intervals.
    lines.extend([
        "    window = 0;",
        f"    @(negedge {contract.clock_signal}); {contract.input_signal} = 1'b1;",
        f"    cycles({max_w});",
        f"    @(negedge {contract.clock_signal}); {contract.input_signal} = 1'b0;",
        "    cycles(2);",
        # Exact max+1 boundary: an off-by-one timeout must be observable.
        "    window = 1;",
        f"    @(negedge {contract.clock_signal}); {contract.input_signal} = 1'b1;",
        f"    cycles({max_w} + 1);",
        f"    @(negedge {contract.clock_signal}); {contract.input_signal} = 1'b0;",
        "    cycles(2);",
        # The invalid pulse remains high beyond the maximum and through a
        # suffix that would look legal if a timeout rearmed by level.
        "    window = 2;",
        f"    @(negedge {contract.clock_signal}); {contract.input_signal} = 1'b1;",
        f"    cycles({max_w} + 2);",
        f"    cycles({suffix});",
        f"    @(negedge {contract.clock_signal}); {contract.input_signal} = 1'b0;",
        "    cycles(2);",
        # No acceptance is credited until the new rising edge below.  This
        # makes an inactive-level-only rearm fail the same control.
        "    window = 3;",
        f"    @(negedge {contract.clock_signal}); {contract.input_signal} = 1'b1;",
        f"    cycles({max_w});",
        f"    @(negedge {contract.clock_signal}); {contract.input_signal} = 1'b0;",
        "    cycles(2);",
        "    $display(\"PWR_COUNTS legal=%0d boundary_bad=%0d bad=%0d final=%0d max=%0d\", legal_accepts, boundary_bad_accepts, bad_accepts, final_accepts, "
        f"{max_w});",
        "    $fdisplay(result_fd, \"PWR_CHANNEL_BEGIN\");",
        '    $fdisplay(result_fd, "PWR_BINDING %s", PWR_BINDING);',
        "    $fdisplay(result_fd, \"PWR_COUNTS legal=%0d boundary_bad=%0d bad=%0d final=%0d max=%0d\", legal_accepts, boundary_bad_accepts, bad_accepts, final_accepts, ",
        f"{max_w});",
        "    if (legal_accepts == 1 && boundary_bad_accepts == 0 && bad_accepts == 0 && final_accepts == 1) begin",
        "      $display(\"PWR_PASS\"); $fdisplay(result_fd, \"PWR_VERDICT PASS\");",
        "    end else begin",
        "      $display(\"PWR_FAIL\"); $fdisplay(result_fd, \"PWR_VERDICT FAIL\");",
        "    end",
        "    $fdisplay(result_fd, \"PWR_CHANNEL_END\");",
        "    $fclose(result_fd);",
        "    $finish;",
        "  end",
        # Hard wall so a broken clock/reset cannot make native validation hang.
        f"  initial begin #{(max_w * 8 + 80) * 10}; $display(\"PWR_TIMEOUT\"); $finish; end",
        "endmodule",
    ])
    tb = "\n".join(lines) + "\n"
    stimulus = {
        "input_signal": contract.input_signal,
        "accept_output": contract.accept_output,
        "clock_signal": contract.clock_signal,
        "max_width_cycles": max_w,
        "boundary_overlong_cycles": max_w + 1,
        "overlong_cycles": max_w + 2,
        "active_suffix_cycles": suffix,
        "rearm": "inactive_then_new_rising_edge",
        "tb_sha256": _sha256_text(tb),
    }
    return tb, stimulus


def _run(cmd: List[str], timeout: int = 120,
         cwd: Optional[Path] = None, *,
         launch_record: Optional[Dict] = None) -> Tuple[int, str, str]:
    try:
        if launch_record is not None:
            with subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True,
                                  cwd=str(cwd) if cwd else None) as process:
                launch_record.update({"pid": process.pid, "argv": cmd,
                                      "cwd": str(cwd) if cwd else None})
                try:
                    out, err = process.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    out, err = process.communicate()
                    launch_record["returncode"] = 124
                    return 124, out or "", (err or "") + "\nsimulation timeout"
                launch_record["returncode"] = process.returncode
                return process.returncode, out or "", err or ""
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                            cwd=str(cwd) if cwd else None)
        return cp.returncode, cp.stdout or "", cp.stderr or ""
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return 124, out, "simulation timeout"
    except OSError as exc:
        return 127, "", str(exc)


def _parse_result_channel(text: str, expected_binding: Optional[str] = None
                          ) -> Tuple[Optional[Dict[str, int]], Optional[str], str]:
    """Parse the launched harness channel, rejecting duplicates and wrong runs."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if expected_binding is not None:
        binding_rows = [line for line in lines if line.startswith("PWR_BINDING ")]
        if binding_rows != ["PWR_BINDING " + expected_binding]:
            return None, None, "measurement result channel is not bound to the launched run"
    if lines.count("PWR_CHANNEL_BEGIN") != 1 or lines.count("PWR_CHANNEL_END") != 1:
        return None, None, "measurement result channel markers are missing or duplicated"
    count_rows = [line for line in lines if line.startswith("PWR_COUNTS ")]
    verdict_rows = [line for line in lines if line.startswith("PWR_VERDICT ")]
    if len(count_rows) != 1 or len(verdict_rows) != 1:
        return None, None, "measurement result channel has duplicate or missing verdict rows"
    m = re.fullmatch(
        r"PWR_COUNTS legal=(\d+) boundary_bad=(\d+) bad=(\d+) final=(\d+) max=(\d+)",
        count_rows[0])
    vm = re.fullmatch(r"PWR_VERDICT (PASS|FAIL)", verdict_rows[0])
    if not m or not vm:
        return None, None, "measurement result channel has malformed rows"
    return ({"legal": int(m.group(1)), "boundary_bad": int(m.group(2)),
             "bad": int(m.group(3)), "final": int(m.group(4)),
             "max": int(m.group(5))}, vm.group(1), "")


def _dut_unsafe_constructs(text: str) -> List[str]:
    """Admit expanded DUT code, never DUT file/process/plusarg capabilities.

    Scan exactly the preprocessed bytes subsequently compiled, including
    macros and every context module. Escaped identifiers, comments and strings
    are lexical spans, so quoted examples cannot mint or conceal executable
    system tasks. Console output cannot write the private result channel.
    """
    noncode = re.compile(r'\\[^\s]+|//[^\n]*|/\*.*?\*/|"(?:[^"\\]|\\.)*"', re.S)
    escaped_harness = any(m.group(0) == r"\pulse_width_rearm_measurement_tb"
                          for m in noncode.finditer(text))
    code = noncode.sub(lambda m: "\n" * m.group(0).count("\n") + " ", text)
    pure_or_console = {
        "$clog2", "$bits", "$signed", "$unsigned", "$size", "$left",
        "$right", "$low", "$high", "$increment", "$countones",
        "$onehot", "$onehot0", "$isunknown", "$display", "$write",
        "$strobe", "$monitor", "$monitoron", "$monitoroff",
    }
    calls = set(re.findall(r'\$[A-Za-z_]\w*(?:\$[A-Za-z_]\w*)*', code))
    unsafe = sorted(calls - pure_or_console)
    unsafe.extend(sorted(set(re.findall(
        r'\b(?:force|release|bind|pulse_width_rearm_measurement_tb)\b', code))))
    if escaped_harness:
        unsafe.append("escaped measurement harness hierarchy")
    if re.search(r'\b(?:import|export)\s+"DPI', text):
        unsafe.append("DPI")
    return unsafe


def _suite_paths(suite_path: Path) -> Tuple[Path, Path, Path]:
    """Resolve the neutral suite's source and polarity fixtures.

    Paths are declared in the suite file itself.  This keeps ``--suite`` a
    generic entry point and prevents a program-level private fixture list from
    becoming a hidden protocol rule.
    """
    text = suite_path.read_text(errors="replace")
    fields = {}
    for key in ("SOURCE", "POSITIVE_RTL", "NEGATIVE_RTL"):
        m = re.search(rf"^\s*//\s*PWR_{key}:\s*(\S+)\s*$", text,
                      re.IGNORECASE | re.MULTILINE)
        if m:
            fields[key] = m.group(1)
    missing = [key for key in ("SOURCE", "POSITIVE_RTL", "NEGATIVE_RTL")
               if key not in fields]
    if missing:
        raise ValueError("suite is missing declared PWR paths: " + ", ".join(missing))
    base = suite_path.parent
    paths = tuple((base / fields[key]).resolve() for key in
                  ("SOURCE", "POSITIVE_RTL", "NEGATIVE_RTL"))
    for path in paths:
        if not path.is_file():
            raise ValueError(f"suite-declared path does not exist: {path}")
    return paths  # type: ignore[return-value]


def run_suite(suite_path: Path, require_tools: bool = False) -> Tuple[int, Dict]:
    source_path, positive_path, negative_path = _suite_paths(suite_path)
    results = {}
    for label, rtl_path in (("compliant", positive_path), ("level_reacquire_bad", negative_path)):
        rc, report = run_check(source_path, rtl_path,
                               context_files=[], require_tools=require_tools)
        results[label] = {"rc": rc, "report": report}
    positive = results["compliant"]["report"]
    negative = results["level_reacquire_bad"]["report"]
    same_contract = positive.get("contract", {}).get("source_sha256") == \
        negative.get("contract", {}).get("source_sha256")
    same_stimulus = positive.get("stimulus", {}).get("tb_sha256") == \
        negative.get("stimulus", {}).get("tb_sha256")
    native = all(r["report"].get("measured") is True for r in results.values())
    negative_counts = negative.get("counts") or {}
    negative_property_observed = (
        negative.get("measured") is True and
        negative_counts.get("legal") == 1 and
        negative_counts.get("final") == 1 and
        negative_counts.get("bad", 0) >= 1)
    expected_polarities = (
        positive.get("verdict") == "PASS" and
        negative.get("verdict") == "FAIL" and
        negative_property_observed)
    measured_fail = (
        (positive.get("verdict") == "FAIL" and positive.get("measured") is True) or
        (negative.get("verdict") == "FAIL" and negative.get("measured") is True
         and not negative_property_observed))
    report = {
        "program": "pulse_width_rearm_conformance_check",
        "suite": str(suite_path),
        "suite_sha256": _sha256_text(suite_path.read_text(errors="replace")),
        "variants": results,
        "same_source_contract": same_contract,
        "same_frozen_stimulus": same_stimulus,
        "native_measured": native,
        "negative_property_observed": negative_property_observed,
        "expected_polarities": expected_polarities,
    }
    # A measured design failure is stronger evidence than an independent arm
    # that could not be measured. Never launder the former into NOT_MEASURED.
    if measured_fail:
        report["verdict"] = "FAIL"
        report["reason"] = "measured FAIL takes precedence over any unmeasured arm"
        return 1, report
    if not native:
        report["verdict"] = "NOT_MEASURED"
        report["reason"] = "both polarity runs require a native simulation result"
        return 3, report
    if not same_contract or not same_stimulus:
        report["verdict"] = "NOT_MEASURED"
        report["reason"] = "polarity arms did not consume identical source/stimulus identities"
        return 3, report
    report["verdict"] = "PASS" if expected_polarities else "FAIL"
    report["reason"] = ("compliant PASS and level-sensitive FAIL on the same waveform"
                         if expected_polarities else
                         "polarity acceptance did not match the declared contract")
    return (0 if expected_polarities else 1), report


def _tool_identity(executable: str) -> Dict[str, str]:
    path = shutil.which(executable) or ""
    if not path:
        return {"path": "", "version": "unavailable"}
    try:
        cp = subprocess.run([path, "-V"], capture_output=True, text=True,
                            timeout=10, check=False)
        text = (cp.stdout or "") + (cp.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        text = f"version probe failed: {exc}"
    return {"path": path, "version": text.strip()[:1000]}


def _freeze_file(work: Path, source: Path, data: bytes, root: Path,
                 ordinal: int) -> Path:
    try:
        relative = source.resolve().relative_to(root.resolve())
    except ValueError:
        relative = Path(f"{ordinal:03d}_{source.name}")
    target = work / "frozen" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def run_check(source_path: Path, rtl_path: Path, top: Optional[str] = None,
              context_files: Optional[Iterable[Path]] = None,
              require_tools: bool = False, *,
              _input_bytes: Optional[Dict[str, bytes]] = None) -> Tuple[int, Dict]:
    context = [Path(p) for p in (context_files or [])]
    # Project admission supplies the bytes it already froze during discovery
    # and top selection. Standalone checks retain their one-read API.
    read_input = (lambda path: path.read_bytes()) if _input_bytes is None else \
        (lambda path: _input_bytes[str(path)])
    source_bytes = read_input(source_path)
    rtl_bytes = read_input(rtl_path)
    context_bytes = [(path, read_input(path)) for path in context]
    source_text = source_bytes.decode("utf-8", "replace")
    rtl_text = rtl_bytes.decode("utf-8", "replace")
    parsed: ContractParse = extract_contract(source_text)
    report: Dict = {
        "program": "pulse_width_rearm_conformance_check",
        "source": str(source_path),
        "rtl": str(rtl_path),
        "reads_only": "source contract + RTL + generated measurement waveform",
        "source_file_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "rtl_sha256": hashlib.sha256(rtl_bytes).hexdigest(),
        "context_files": [str(path) for path, _ in context_bytes],
        "context_sha256": {
            str(path): hashlib.sha256(data).hexdigest()
            for path, data in context_bytes
        },
        "tool_identity": {
            "iverilog": _tool_identity("iverilog"),
            "vvp": _tool_identity("vvp"),
            "python": sys.version,
        },
    }
    if not parsed.declared:
        report.update({"verdict": "NOT_APPLICABLE", "measured": False,
                       "reason": parsed.reason})
        # A protocol without an explicit pulse maximum/rearm contract is
        # outside this rule.  Tool availability cannot turn that honest
        # non-applicability into an error.
        return 0, report
    if parsed.contract is None:
        report.update({"verdict": "NOT_MEASURED", "measured": False,
                       "reason": parsed.reason})
        return 3, report
    contract = parsed.contract
    report["contract"] = contract.to_dict()
    if contract.source_hash_valid is False:
        report.update({"verdict": "NOT_MEASURED", "measured": False,
                       "reason": "declared source_sha256 does not match the exact source bytes"})
        return 3, report
    names = _module_names(rtl_text)
    if top is None:
        top = names[0] if len(names) == 1 else None
    if not top or not _IDENT.fullmatch(top):
        report.update({"verdict": "NOT_MEASURED", "measured": False,
                       "reason": "top module mapping is missing or ambiguous"})
        return 3, report
    report["top"] = top
    try:
        tb_text, stimulus = _build_measurement_tb(rtl_text, top, contract)
    except (OSError, ValueError) as exc:
        report.update({"verdict": "NOT_MEASURED", "measured": False,
                       "reason": str(exc)})
        return 3, report
    report["stimulus"] = stimulus
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        report.update({"verdict": "SKIP", "measured": False,
                       "reason": "iverilog/vvp unavailable; native result is NOT_MEASURED"})
        return (2 if require_tools else 0), report
    with tempfile.TemporaryDirectory(prefix="pwrconf_") as td, \
            tempfile.TemporaryDirectory(prefix="pwrchannel_") as channel_td:
        work = Path(td)
        all_sources = [rtl_path] + context
        try:
            common_root = Path(__import__("os").path.commonpath(
                [str(path.resolve()) for path in all_sources]))
        except (ValueError, OSError):
            common_root = rtl_path.parent
        frozen_rtl = _freeze_file(work, rtl_path, rtl_bytes, common_root, 0)
        frozen_context = []
        for index, (path, data) in enumerate(context_bytes, start=1):
            frozen_context.append(_freeze_file(work, path, data, common_root, index))
        tb_path = work / "pulse_width_rearm_measurement_tb.sv"
        bin_path = work / "pulse_width_rearm_measurement.vvp"
        tb_path.write_text(tb_text)
        expanded_path = work / "expanded_dut.sv"
        preprocess_cmd = ["iverilog", "-g2012", "-E", "-o", str(expanded_path),
                          str(frozen_rtl), *[str(p) for p in frozen_context]]
        pre_rc, pre_out, pre_err = _run(preprocess_cmd, cwd=work)
        report["preprocess_command"] = preprocess_cmd
        if pre_rc != 0 or not expanded_path.is_file():
            report.update({"verdict": "NOT_MEASURED", "measured": False,
                           "reason": "frozen DUT preprocessing failed",
                           "raw_compile_tail": (pre_out + pre_err).splitlines()[-8:]})
            return 3, report
        expanded_bytes = expanded_path.read_bytes()
        report["expanded_dut_sha256"] = _sha256_bytes(expanded_bytes)
        unsafe = _dut_unsafe_constructs(expanded_bytes.decode("utf-8", "replace"))
        report["dut_admission"] = {"unsafe_constructs": unsafe,
                                   "expanded_dut_sha256": report["expanded_dut_sha256"]}
        if unsafe:
            report.update({"verdict": "NOT_MEASURED", "measured": False,
                           "reason": "DUT has forbidden simulation/file/channel capabilities: " +
                                     ", ".join(unsafe)})
            return 3, report
        compile_cmd = ["iverilog", "-g2012", "-o", str(bin_path), "-s",
                       "pulse_width_rearm_measurement_tb", str(expanded_path), str(tb_path)]
        report["frozen_rtl"] = str(frozen_rtl)
        report["frozen_context_files"] = [str(p) for p in frozen_context]
        rc, out, err = _run(compile_cmd, cwd=work)
        report["compile_command"] = compile_cmd
        report["compile_stdout_sha256"] = _sha256_text(out)
        report["compile_stderr_sha256"] = _sha256_text(err)
        if rc != 0:
            report.update({"verdict": "NOT_MEASURED", "measured": False,
                           "reason": "RTL plus independent measurement waveform did not compile",
                           "raw_compile_tail": (out + "\n" + err).strip().splitlines()[-8:]})
            return 3, report
        # These identities are minted only AFTER DUT admission/compilation.
        # The DUT cannot query plusargs, read files, finish the simulation or
        # reach the harness hierarchy. Only the generated harness has access.
        nonce = secrets.token_hex(32)
        frozen_result = Path(channel_td) / (secrets.token_hex(32) + ".txt")
        input_binding = _sha256_text(json.dumps({
            "source": report["source_file_sha256"], "rtl": report["rtl_sha256"],
            "context": report["context_sha256"], "tb": stimulus["tb_sha256"],
            "expanded_dut": report["expanded_dut_sha256"],
        }, sort_keys=True))
        binary_sha256 = _sha256_bytes(bin_path.read_bytes())
        binding = nonce + ":" + input_binding + ":" + binary_sha256
        report["run_binding"] = {"nonce": nonce, "input_sha256": input_binding,
                                 "binary_sha256": binary_sha256, "channel": str(frozen_result)}
        sim_cmd = [shutil.which("vvp"), str(bin_path),
                   "+PWR_RESULT_FILE=" + str(frozen_result), "+PWR_BINDING=" + binding]
        launch_record: Dict = {}
        rc2, sim_out, sim_err = _run(sim_cmd, cwd=work, launch_record=launch_record)
        report["native_process"] = launch_record
        report["simulation_command"] = sim_cmd
        report["simulation_stdout_sha256"] = _sha256_text(sim_out)
        report["simulation_stderr_sha256"] = _sha256_text(sim_err)
        report["raw_simulation_tail"] = (sim_out + "\n" + sim_err).strip().splitlines()[-12:]
        channel_text = frozen_result.read_text(errors="replace") if frozen_result.is_file() else ""
        report["result_channel_sha256"] = _sha256_text(channel_text)
        report["result_channel_tail"] = channel_text.strip().splitlines()[-12:]
    counts, channel_verdict, channel_error = _parse_result_channel(channel_text, binding)
    report["counts"] = counts
    report["channel_verdict"] = channel_verdict
    if rc2 != 0 or "PWR_TIMEOUT" in sim_out or counts is None or channel_error:
        report.update({"verdict": "NOT_MEASURED", "measured": False,
                       "reason": channel_error or
                       "bounded measurement did not emit a complete result"})
        return 3, report
    expected = {"legal": 1, "boundary_bad": 0, "bad": 0, "final": 1,
                "max": contract.max_width_cycles}
    passed = channel_verdict == "PASS" and counts == expected
    report.update({"verdict": "PASS" if passed else "FAIL", "measured": True,
                   "reason": ("compliant legal/overlong/rearm waveform matched"
                              if passed else
                              "overlong, max+1, stuck, or legal pulse behavior "
                              "did not match the declared contract")})
    return (0 if passed else 1), report


def _contract_source_candidates(project: Path) -> List[Path]:
    roots = [project / "phase1" / "input_prompt",
             project / "phase1" / "input_doc"]
    suffixes = {".json", ".md", ".markdown", ".txt", ".yaml", ".yml"}
    out: List[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in suffixes:
                out.append(path)
    return out


def _discover_project_contract_snapshot(
        project: Path) -> Tuple[Optional[Path], Optional[ContractParse], Dict,
                                   Dict[str, Dict[str, object]]]:
    """Discover contracts while retaining the one live read of every source."""
    declared = []
    malformed = []
    candidates = _contract_source_candidates(project)
    snapshots: Dict[str, Dict[str, object]] = {}
    for path in candidates:
        try:
            snapshot = _snapshot_file(path)
            snapshots[str(path)] = snapshot
            parsed = extract_contract(snapshot["bytes"].decode("utf-8", "replace"))
        except OSError as exc:
            malformed.append({"path": str(path), "reason": str(exc)})
            continue
        if parsed.declared:
            if parsed.contract is None:
                malformed.append({"path": str(path), "reason": parsed.reason})
            else:
                declared.append((path, parsed))
    info = {"candidates": [str(p) for p in candidates],
            "declared": [str(p) for p, _ in declared],
            "malformed": malformed}
    if malformed:
        return (None, None,
                {**info, "reason": "incomplete or malformed source-bound pulse contract"},
                snapshots)
    if len(declared) > 1:
        return (None, None,
                {**info, "reason": "multiple source-bound pulse contracts are ambiguous"},
                snapshots)
    if not declared:
        return (None, None,
                {**info, "reason": "no explicit source-declared pulse maximum and rearm contract"},
                snapshots)
    return declared[0][0], declared[0][1], info, snapshots


def discover_project_contract(project: Path) -> Tuple[Optional[Path], Optional[ContractParse], Dict]:
    """Find one source-bound contract; ambiguity and incompleteness refuse."""
    source_path, parsed, info, _snapshots = _discover_project_contract_snapshot(project)
    return source_path, parsed, info


def _snapshot_subject_digest(snapshots: Iterable[Dict[str, object]]) -> str:
    """Retain the ordered RTL aggregate digest from the frozen byte set."""
    return _sha256_bytes(b"\n".join(snapshot["bytes"] for snapshot in snapshots))


_GENERATION_BINDINGS = (
    "project", "top", "rtl_files", "source_contract_path", "source_contract_sha256",
    "source_file_sha256", "rtl_sha256", "rtl_file_sha256", "rtl_subject_sha256",
    "context_sha256", "stimulus", "expanded_dut_sha256", "run_binding",
    "native_process", "result_channel_sha256",
)


def _seal_input_generation(report_path: Path, report: Dict,
                           snapshots: Iterable[Dict[str, object]]) -> None:
    """Preserve the consumed bytes as a sealed generation, independent of live paths.

    A receipt is about this content-addressed immutable object, never an
    assertion that unlocked project paths will stay unchanged. Adopters must
    validate the seal and compare the current selection with this generation.
    """
    payload = {
        "schema": "pulse-width-rearm-input-generation.v1",
        "bindings": {key: report[key] for key in _GENERATION_BINDINGS if key in report},
        "source_candidates": report["source_discovery"]["candidates"],
        "native_verdict": report["verdict"], "native_measured": report["measured"],
        "inputs": [{"path": str(row["path"]), "sha256": row["sha256"],
                    "fingerprint": row["fingerprint"],
                    "bytes_base64": base64.b64encode(row["bytes"]).decode("ascii")}
                   for row in snapshots],
    }
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=f".{report_path.name}.inputs.",
                                suffix=".json", dir=str(report_path.parent))
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), 0o400)
    report["input_generation"] = {
        "path": path, "sha256": _sha256_bytes(encoded),
        "subject": "immutable consumed source/ordered RTL bytes",
        "adoption_requires": "seal, current input selection and live path identities",
    }


def _generation_changes(report: Dict, *, check_live: bool = True) -> List[str]:
    """Validate both the immutable subject and the live generation on adoption."""
    try:
        seal = report["input_generation"]
        encoded = Path(seal["path"]).read_bytes()
        if _sha256_bytes(encoded) != seal["sha256"]:
            return ["immutable input generation digest changed"]
        generation = json.loads(encoded)
        if generation["schema"] != "pulse-width-rearm-input-generation.v1":
            return ["unknown input generation schema"]
        bindings = {key: report[key] for key in _GENERATION_BINDINGS if key in report}
        if bindings != generation["bindings"]:
            return ["receipt bindings differ from immutable input generation"]
        if report.get("verdict") == "PASS" and (
                generation["native_verdict"] != "PASS" or
                generation["native_measured"] is not True):
            return ["receipt PASS is not backed by the measured generation"]
        snapshots = []
        for row in generation["inputs"]:
            data = base64.b64decode(row["bytes_base64"], validate=True)
            if _sha256_bytes(data) != row["sha256"]:
                return ["immutable input bytes do not match their digests"]
            snapshots.append({**row, "bytes": data})
        if not check_live:
            return []
        changes = _snapshot_changes(snapshots)
        if [str(p) for p in _contract_source_candidates(Path(report["project"]))] != \
                generation["source_candidates"]:
            changes.append("source candidate path set changed")
        return changes
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"input generation unavailable or malformed: {exc}"]


def adopt_project_receipt(project: Path, rtl_files: Iterable[Path],
                          report_path: Path, report: Dict) -> Tuple[int, Dict]:
    """BLOCKING: a native receipt can be adopted only for the current generation.

    Publication is atomic for the sealed snapshot, while arbitrary external
    writers need not share a lock. Revalidation is therefore mandatory at the
    actual reference-TB consumer, both before execution and before its PASS.
    """
    changes = _generation_changes(report)
    if Path(report.get("project", "")).resolve() != Path(project).resolve():
        changes.append("receipt belongs to a different project")
    if report.get("rtl_files") != [str(path) for path in rtl_files]:
        changes.append("adopted ordered RTL selection changed")
    try:
        if json.loads(Path(report_path).read_text()) != report:
            changes.append("published receipt differs from the measured receipt")
    except (OSError, ValueError) as exc:
        changes.append(f"published receipt unavailable: {exc}")
    if changes:
        measured_fail = report.get("verdict") == "FAIL" and report.get("measured") is True
        report["input_stability"] = {"stable": False, "changes": changes,
                                     "scope": "generation adoption", "digest_mismatch": []}
        report.update({"verdict": "FAIL" if measured_fail else "NOT_MEASURED",
                       "measured": measured_fail,
                       "reason": ("measured FAIL takes precedence; " if measured_fail else "") +
                                 "input generation changed at adoption: " + "; ".join(changes)})
        _publish_report(report_path, report, lambda: None)
        return (1 if measured_fail else 3), report
    return (1 if report.get("verdict") == "FAIL" else 0), report


def run_project(project: Path, rtl_files: Iterable[Path], top: str,
                report_path: Optional[Path] = None,
                runtime_identity: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict]:
    """Measure a sealed input generation; refuse live drift at publish/adoption."""
    project = Path(project)
    source_path, parsed, discovery, source_snapshots = \
        _discover_project_contract_snapshot(project)
    files = [Path(p) for p in rtl_files]
    report: Dict[str, Any] = {
        "program": "pulse_width_rearm_conformance_check",
        "normal_consumer": True,
        "project": str(project), "top": top,
        "source_discovery": discovery,
        "runtime_identity": runtime_identity or {},
        "rtl_files": [str(path) for path in files],
    }
    input_snapshots = list(source_snapshots.values())
    digest_mismatch: List[str] = []
    measured_fail = False
    rc = 3

    def validate_publication() -> None:
        nonlocal rc
        live_changes = _snapshot_changes(input_snapshots)
        current_candidates = [str(path) for path in _contract_source_candidates(project)]
        if current_candidates != discovery.get("candidates", []):
            live_changes.append("source candidate path set changed")
        if "input_generation" in report:
            live_changes.extend(_generation_changes(report, check_live=False))
        report["input_stability"] = {
            "stable": not (live_changes or digest_mismatch),
            "changes": live_changes, "digest_mismatch": digest_mismatch,
            "scope": "live observation only; immutable input_generation is the measurement subject",
        }
        if live_changes or digest_mismatch:
            reasons = []
            if digest_mismatch:
                reasons.append("measured digest set does not match frozen inputs: " +
                               ", ".join(digest_mismatch))
            if live_changes:
                reasons.append("input path/byte set changed before receipt publication: " +
                               "; ".join(live_changes))
            if measured_fail:
                report.update({"verdict": "FAIL", "measured": True,
                               "reason": "measured FAIL takes precedence; publication drift: " +
                                         " | ".join(reasons)})
                rc = 1
            else:
                report.update({"verdict": "NOT_MEASURED", "measured": False,
                               "reason": " | ".join(reasons)})
                rc = 3

    if source_path is None:
        if discovery.get("declared") or discovery.get("malformed"):
            report.update({"verdict": "NOT_MEASURED", "measured": False,
                           "reason": discovery.get("reason", "source contract unavailable")})
        else:
            report.update({"verdict": "NOT_APPLICABLE", "measured": False,
                           "reason": discovery.get("reason", "no contract"),
                           "declared_by": "source-bound contract discovery"})
            rc = 0
    elif parsed is None or not files:
        report.update({"verdict": "NOT_MEASURED", "measured": False,
                       "reason": "source contract is applicable but current RTL inputs are absent"})
    else:
        file_snapshots: Dict[str, Dict[str, object]] = {}
        snapshot_error = ""
        for path in files:
            try:
                if str(path) not in file_snapshots:
                    snapshot = _snapshot_file(path)
                    file_snapshots[str(path)] = snapshot
                    input_snapshots.append(snapshot)
            except OSError as exc:
                snapshot_error = str(exc)
                break
        primary = next((path for path in files if str(path) in file_snapshots and
                        top in _module_names(file_snapshots[str(path)]["bytes"].decode(
                            "utf-8", "replace"))), None)
        if snapshot_error or primary is None:
            report.update({"verdict": "NOT_MEASURED", "measured": False,
                           "reason": (f"could not freeze current RTL inputs: {snapshot_error}"
                                      if snapshot_error else
                                      "declared top module is absent from the current RTL inputs")})
        else:
            context = [path for path in files if path != primary]
            frozen_bytes = {str(row["path"]): row["bytes"] for row in input_snapshots}
            rc, measured = run_check(source_path, primary, top=top,
                                     context_files=context, _input_bytes=frozen_bytes)
            expected_source = source_snapshots[str(source_path)]["sha256"]
            expected_rtl = file_snapshots[str(primary)]["sha256"]
            expected_context = {str(path): file_snapshots[str(path)]["sha256"]
                                for path in context}
            for role, actual, expected in (
                    ("source", measured.get("source_file_sha256"), expected_source),
                    ("primary RTL", measured.get("rtl_sha256"), expected_rtl),
                    ("context", measured.get("context_sha256", {}), expected_context)):
                if actual != expected:
                    digest_mismatch.append(role)
            if measured.get("measured") is True and not measured.get("stimulus", {}).get("tb_sha256"):
                digest_mismatch.append("stimulus")
            measured_fail = (measured.get("verdict") == "FAIL" and
                             measured.get("measured") is True)
            report.update(measured)
            # The publication digests are exclusively from the frozen set,
            # including on refusal; no live byte can rewrite a measured SHA.
            report.update({
                "source_contract_path": str(source_path),
                "source_contract_sha256": expected_source,
                "source_file_sha256": expected_source,
                "rtl_sha256": expected_rtl,
                "context_sha256": expected_context,
                "rtl_subject_sha256": _snapshot_subject_digest(
                    file_snapshots[str(path)] for path in files),
                "rtl_file_sha256": {str(path): file_snapshots[str(path)]["sha256"]
                                    for path in files},
            })
    if report_path:
        _seal_input_generation(Path(report_path), report, input_snapshots)
    validate_publication()
    if report_path:
        _publish_report(report_path, report, validate_publication,
                        after_commit=validate_publication)
    return rc, report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", default=None,
                    help="neutral suite with PWR_SOURCE/PWR_POSITIVE_RTL/PWR_NEGATIVE_RTL markers")
    ap.add_argument("--source", "--spec", "--prompt", dest="source", required=False,
                    help="source document or explicit pulse contract")
    ap.add_argument("--rtl", required=False, help="authored RTL")
    ap.add_argument("--top", default=None, help="explicit DUT top module")
    ap.add_argument("--context", action="append", default=[],
                    help="additional source file(s) needed to compile the DUT")
    ap.add_argument("--require-tools", action="store_true",
                    help="return 2 when iverilog/vvp are unavailable")
    ap.add_argument("--json", default=None, help="write the evidence report")
    args = ap.parse_args(argv)
    try:
        if args.suite:
            rc, report = run_suite(Path(args.suite), args.require_tools)
        elif not args.source or not args.rtl:
            ap.error("--source and --rtl are required unless --suite is supplied")
        else:
            rc, report = run_check(Path(args.source), Path(args.rtl), args.top,
                                   [Path(p) for p in args.context], args.require_tools)
    except OSError as exc:
        print(f"PWR_ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"pulse_width_rearm_conformance_check: {report['verdict']} - {report.get('reason', '')}")
    if report.get("counts"):
        print("  counts: " + json.dumps(report["counts"], sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
