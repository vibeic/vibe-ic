#!/usr/bin/env python3
"""FX_P2 (4) — the D3 rule at the P0 frontend: slang's declaration-order
refusal is retried once with `--allow-use-before-declare` and DISCLOSED; any
other refusal still FAILs.

MEASURED on subservient (reused serv 1.4.0, 8HD-4, 2026-09-28): with reference_tb,
step 4, LEC and three final-audit gates fixed and phase 1 regenerated, phase 2
still halted: the P0 umbrella FAILed on `p0_tool_frontend_check` ("Yosys
elaboration failed"). Yosys's own output:

    serv_state.v:111:52: error: identifier 'trap_pending' used before its declaration
    serv_state.v:118:37: error: identifier 'trap_pending' used before its declaration

The same portability defect D3 books for strict Icarus. In the image (0.3.83)
`read_slang --allow-use-before-declare` elaborates that shape, and a genuinely
undeclared name still fails ("use of undeclared identifier") with or without it.

Orchestrator ruling (2026-09-28), the D3 review's two conditions:
  (a) the retry runs ONLY for reused-IP projects -- plugin-authored RTL with a
      use-before-declare stays a FAIL for repair;
  (b) only when EVERY slang error is its exact use-before-declare diagnostic --
      not a mix, not another refusal, not a transcript with no diagnostic.

Only the EDA tools' answers are faked (`_invoke`), by argv, replaying REAL
read_slang transcripts from the image (the calibration files).
chip-AGNOSTIC: synthetic RTL.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import p0_tool_frontend_check as F  # noqa: E402

FLAG = "--allow-use-before-declare"
CAL = PROGRAMS / "calibration"
#: real read_slang output: only a use-before-declare / that plus an undeclared
LATE = (CAL / "p0_slang_use_before_declare_positive.log").read_text()
MIXED = (CAL / "p0_slang_use_before_declare_negative.log").read_text()
GHOST = ("top.v:2:21: error: use of undeclared identifier 'ghost'\n"
         "Build failed: 1 error, 0 warnings\n")


_SRC = ("module top(input a, output y);\n  assign y = late;\n"
        "  wire late = a;\nendmodule\n")


def _project(tmp_path: Path, reused_ip=True) -> Path:
    """FX_P2 review: the file is SUPPLIED IP the way subservient's is -- staged
    byte-for-byte from `input/vendor_rtl/` and named in the manifest's
    `staged_from_input` -- so the per-file condition holds."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(_SRC)
    vendor = tmp_path / "input" / "vendor_rtl"
    vendor.mkdir(parents=True)
    (vendor / "top.v").write_text(_SRC)
    if reused_ip is not None:
        (rtl / "SOURCE_MANIFEST.json").write_text(
            json.dumps({"reused_ip": bool(reused_ip),
                        "staged_from_input": ["input/vendor_rtl/top.v"]}))
    return tmp_path


def _at(log: str, root: Path) -> str:
    """The real transcript names the probe's `rtl/late.v`; the tool names the
    absolute path it was handed, so point it at this project's file."""
    top = str((root / "phase2" / "stage1" / "rtl" / "top.v").resolve())
    return log.replace("rtl/late.v", top).replace("rtl/mixed.v", top)


def _fake(monkeypatch, *, strict, relaxed_ok, strict_rc=1):
    calls = []

    def _invoke(tool, args, root, image):
        calls.append((tool, list(args)))
        if tool == "yosys":
            log = _at(strict, Path(root))
            if FLAG in args[-1]:
                rc, err = (0, "") if relaxed_ok else (1, log)
            else:
                rc, err = strict_rc, log
            return subprocess.CompletedProcess([tool], rc, "", err)
        return subprocess.CompletedProcess([tool], 0, "", "")

    monkeypatch.setattr(F, "_invoke", _invoke)
    return calls


def _yosys(calls):
    return [a for t, a in calls if t == "yosys"]


# ---- the measured case: reused IP, only use-before-declare ---------------
def test_reused_ip_declaration_order_refusal_is_disclosed(monkeypatch,
                                                          tmp_path):
    calls = _fake(monkeypatch, strict=LATE, relaxed_ok=True)
    r = F.check(_project(tmp_path))
    assert r["passed"] is True, r["findings"]
    assert any("DECLARATION_ORDER_RELAXED" in d
               for d in r.get("disclosures", [])), r
    assert "used before its declaration" in r.get("strict_refusal", "")
    ys = _yosys(calls)
    assert len(ys) == 2 and FLAG not in ys[0][-1] and FLAG in ys[1][-1]
    assert {FLAG in args[-1] for args in ys} == {False, True}
    assert ys[1][-1].index(FLAG) < ys[1][-1].index("top.v")
    emitted = r["tools"]["Yosys.JsonHeader"]
    assert emitted["argv"] == ["yosys", *ys[1]]
    assert emitted["strict_argv"] == ["yosys", *ys[0]]


# ---- (a) plugin-authored RTL is not retried ------------------------------
def test_authored_rtl_use_before_declare_stays_a_fail(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, strict=LATE, relaxed_ok=True)
    r = F.check(_project(tmp_path, reused_ip=False))
    assert r["passed"] is False
    assert "Yosys elaboration failed" in r["findings"]
    assert len(_yosys(calls)) == 1 and not r.get("disclosures")


def test_no_manifest_is_not_reused_ip(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, strict=LATE, relaxed_ok=True)
    r = F.check(_project(tmp_path, reused_ip=None))
    assert r["passed"] is False and len(_yosys(calls)) == 1


# ---- (b) only slang's exact diagnostic, and only alone -------------------
def test_a_mixed_refusal_is_not_retried(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, strict=MIXED, relaxed_ok=True)
    r = F.check(_project(tmp_path))
    assert r["passed"] is False and len(_yosys(calls)) == 1


def test_an_undeclared_identifier_is_not_retried(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, strict=GHOST, relaxed_ok=True)
    r = F.check(_project(tmp_path))
    assert r["passed"] is False and len(_yosys(calls)) == 1


def test_a_timeout_or_silent_failure_is_not_retried(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, strict="", relaxed_ok=True, strict_rc=124)
    r = F.check(_project(tmp_path))
    assert r["passed"] is False and len(_yosys(calls)) == 1


def test_a_retry_that_does_not_elaborate_counts_for_nothing(monkeypatch,
                                                            tmp_path):
    _fake(monkeypatch, strict=LATE, relaxed_ok=False)
    r = F.check(_project(tmp_path))
    assert r["passed"] is False
    assert "Yosys elaboration failed" in r["findings"]
    assert not r.get("disclosures")


def test_a_clean_strict_elaboration_makes_one_call(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, strict="", relaxed_ok=True, strict_rc=0)
    r = F.check(_project(tmp_path))
    assert r["passed"] is True and len(_yosys(calls)) == 1
    assert not r.get("disclosures")


def test_the_reader_answers_on_the_real_transcripts():
    assert F.only_use_before_declare(LATE) is True
    assert F.only_use_before_declare(MIXED) is False
    assert F.only_use_before_declare(GHOST) is False
    assert F.only_use_before_declare("") is False
