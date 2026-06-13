"""tests/test_agent_report_sha256_attestation_check.py — v1.6.33

Seven cases covering rule #5 attestation gate:
  1. happy path — every canonical artefact attested in report   PASS
  2. AGENT_REPORT.md exists but zero sha256 tokens              FAIL (NO_TABLE)
  3. SOF on disk but its sha256 not in report                   FAIL (MISSING)
  4. report attests SOF AND GDS — both match                    PASS
  5. AGENT_REPORT.md missing                                    VACUOUS_PASS
  6. no canonical artefacts on disk                             VACUOUS_PASS
  7. multi-extension coverage (LEF + Liberty + .v) all attested PASS
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from programs.agent_report_sha256_attestation_check import audit


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_artefact(project: Path, rel: str, body: bytes) -> str:
    """Write `body` to <project>/<rel>; return the SHA256 hex."""
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return _sha256(body)


def _write_report(project: Path, body: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "AGENT_REPORT.md").write_text(body, encoding="utf-8")


def test_happy_path_sof_attested(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    sof_hex = _write_artefact(p,
        "phase2/stage1/fpga/output_files/de10lite_top.sof",
        b"// fake sof " + b"X" * 4096)
    _write_report(p, f"""# AGENT_REPORT
## Verdict
PASS
## Acceptance evidence
SOF: phase2/stage1/fpga/output_files/de10lite_top.sof
sha256:{sof_hex}
## Waivers
none
## Discoveries
none
## Iteration log
- run 1
""")
    verdict, findings = audit(p)
    assert verdict == "PASS", findings
    assert findings == []


def test_no_attestation_table_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_artefact(p,
        "phase2/stage1/fpga/output_files/de10lite_top.sof",
        b"// fake sof " + b"X" * 4096)
    _write_report(p, "# AGENT_REPORT\n\nNo SHA256 anywhere in here.\n")
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "NO_ATTESTATION_TABLE" for f in findings)


def test_sof_missing_attestation_fails(tmp_path: Path) -> None:
    """Report has SOME sha256 but not the SOF's sha256."""
    p = tmp_path / "proj"
    _write_artefact(p,
        "phase2/stage1/fpga/output_files/de10lite_top.sof",
        b"// fake sof " + b"X" * 4096)
    # Report attests an UNRELATED hash, not the actual SOF
    fake_hash = "a" * 64
    _write_report(p, f"# AGENT_REPORT\n\n## Verdict\n\n"
                     f"sha256:{fake_hash}\n")
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "MISSING_ATTESTATION" and f.artefact_kind == "FPGA SOF"
               for f in findings)


def test_sof_and_gds_both_attested_passes(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    sof_hex = _write_artefact(p,
        "phase2/stage1/fpga/output_files/de10lite_top.sof",
        b"// sof " + b"X" * 4096)
    gds_hex = _write_artefact(p,
        "phase3/stage4/gds/chip_top.gds",
        b"\x00\x06\x00\x02" + b"Y" * 4096)
    _write_report(p, f"""# AGENT_REPORT
## Acceptance evidence
| artefact | sha256 |
| --- | --- |
| SOF | sha256:{sof_hex} |
| GDS | sha256:{gds_hex} |
""")
    verdict, findings = audit(p)
    assert verdict == "PASS", findings


def test_no_report_is_vacuous(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_artefact(p,
        "phase2/stage1/fpga/output_files/de10lite_top.sof",
        b"// fake sof " + b"X" * 4096)
    # AGENT_REPORT.md NOT written
    verdict, findings = audit(p)
    assert verdict == "VACUOUS_PASS"
    assert findings == []


def test_no_canonical_artefacts_is_vacuous(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_report(p, "# AGENT_REPORT\nNothing here yet.\n")
    # No SOF / GDS / etc. on disk
    verdict, findings = audit(p)
    assert verdict == "VACUOUS_PASS"
    assert findings == []


def test_multi_extension_coverage_passes(tmp_path: Path) -> None:
    """LEF + Liberty + analog hardmacro .v all on disk; all attested."""
    p = tmp_path / "proj"
    lef_hex = _write_artefact(p,
        "analog/hardmacro/ldo_default/ldo_default.lef",
        b"VERSION 5.7;\n" + b"L" * 1024)
    lib_hex = _write_artefact(p,
        "analog/hardmacro/ldo_default/ldo_default.lib",
        b"library(test) {\n" + b"B" * 1024 + b"\n}\n")
    netlist_hex = _write_artefact(p,
        "phase2/stage2/synth/chip_top.v",
        b"module chip_top();\nendmodule\n" + b"N" * 1024)
    _write_report(p, f"""# AGENT_REPORT
## Acceptance evidence

LEF: sha256:{lef_hex}
Liberty: sha256:{lib_hex}
synth netlist: sha256:{netlist_hex}
""")
    verdict, findings = audit(p)
    assert verdict == "PASS", findings


# v1.6.34 — closes producer-consumer mismatch (gate now reads
# reports/final_summary.md as well as AGENT_REPORT.md).

def _write_final_summary(project: Path, body: str) -> None:
    p = project / "reports" / "final_summary.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_final_summary_md_accepted_as_report(tmp_path: Path) -> None:
    """v1.6.32 wired final_report_generate.py to write
    `reports/final_summary.md`; v1.6.34 makes the gate also read it."""
    p = tmp_path / "proj"
    sof_hex = _write_artefact(p,
        "phase2/stage1/fpga/output_files/de10lite_top.sof",
        b"// sof " + b"X" * 4096)
    _write_final_summary(p, f"# Final Summary\n\nsha256:{sof_hex}\n")
    # Note: NO AGENT_REPORT.md
    verdict, findings = audit(p)
    assert verdict == "PASS", findings


def test_either_report_satisfies_attestation(tmp_path: Path) -> None:
    """If both files exist, declared hashes from either count."""
    p = tmp_path / "proj"
    sof_hex = _write_artefact(p,
        "phase2/stage1/fpga/output_files/de10lite_top.sof",
        b"// sof " + b"X" * 4096)
    gds_hex = _write_artefact(p,
        "phase3/stage4/gds/chip_top.gds",
        b"\x00\x06\x00\x02" + b"Y" * 4096)
    # SOF attested only in AGENT_REPORT.md
    _write_report(p, f"# AGENT_REPORT\nsha256:{sof_hex}\n")
    # GDS attested only in reports/final_summary.md
    _write_final_summary(p, f"# Final Summary\nsha256:{gds_hex}\n")
    verdict, findings = audit(p)
    assert verdict == "PASS", findings


def test_neither_report_present_is_vacuous(tmp_path: Path) -> None:
    """v1.6.34: vacuous when BOTH canonical report files are absent."""
    p = tmp_path / "proj"
    _write_artefact(p,
        "phase2/stage1/fpga/output_files/de10lite_top.sof",
        b"// sof " + b"X" * 4096)
    verdict, findings = audit(p)
    assert verdict == "VACUOUS_PASS"
    assert findings == []


def test_hash_mismatch_reports_missing(tmp_path: Path) -> None:
    """If the report declares some sha256 token but the on-disk
    artefact's actual hash differs, the gate reports MISSING_ATTESTATION
    (the disk hash is not declared anywhere)."""
    p = tmp_path / "proj"
    _write_artefact(p,
        "phase2/stage1/fpga/output_files/de10lite_top.sof",
        b"// real sof " + b"X" * 4096)
    # Declare a DIFFERENT hash (different bytes → different sha256)
    bogus = _sha256(b"// totally different sof " + b"Y" * 4096)
    _write_final_summary(p, f"# Final Summary\nsha256:{bogus}\n")
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "MISSING_ATTESTATION"
               and f.artefact_kind == "FPGA SOF"
               for f in findings)


def test_final_summary_with_full_table_passes(tmp_path: Path) -> None:
    """Smoke-test the v1.6.34 producer table format: pipe-table with
    sha256: tokens in each row matches the gate's regex."""
    p = tmp_path / "proj"
    sof_hex = _write_artefact(p,
        "phase2/stage1/fpga/output_files/de10lite_top.sof",
        b"// sof " + b"X" * 4096)
    gds_hex = _write_artefact(p,
        "phase3/stage4/gds/chip_top.gds",
        b"\x00\x06\x00\x02" + b"Y" * 4096)
    lef_hex = _write_artefact(p,
        "analog/hardmacro/ldo/ldo.lef",
        b"VERSION 5.7;\n" + b"L" * 1024)
    _write_final_summary(p, f"""# Final Summary

## SHA-256 Attestation

| Artefact | Path | Size (B) | SHA-256 |
|---|---|---:|---|
| FPGA SOF | `phase2/stage1/fpga/output_files/de10lite_top.sof` | 4,108 | `sha256:{sof_hex}` |
| chip GDS | `phase3/stage4/gds/chip_top.gds` | 4,100 | `sha256:{gds_hex}` |
| analog LEF | `analog/hardmacro/ldo/ldo.lef` | 1,037 | `sha256:{lef_hex}` |
""")
    verdict, findings = audit(p)
    assert verdict == "PASS", findings
