"""Regression tests for two phase1_doc_one_shot_runner backlog fixes.

ORGANIC-20260531-l3-addr-len-max-comparator-and-disk-source-gap
  FIX 1: the addr_max/len_max comparator alternation now includes bare
         *exceed* verbs (exceeds / greater / 超過 / must not exceed) so a
         datasheet stating "address EXCEEDS 0x7F" yields addr_max=0x7F
         instead of None (the L3 gate then PASSes instead of hard-FAILing).
  FIX 2: when the bound lives ONLY in an on-disk sidecar .txt (e.g. a
         spreadsheet->txt conversion) that is NOT in the in-memory extracted
         dict, a disk-scan fallback over the SAME glob set the L3 gate uses
         still captures it — emitter and gate agree on the source set.

ORGANIC-20260531-legacy-binary-office-doc-ingestion-depth
  A/B: extract_doc_legacy gains a LibreOffice tier and a binary-garbage
       guard so an un-decodable legacy .doc returns "" (a KNOWN skip gap)
       instead of feeding raw OLE bytes downstream.
  C:   extract_one routes .xls -> extract_xls_legacy (xlrd / LibreOffice /
       else "").

All inputs are synthetic; no chip/vendor/SKU literals participate.
"""
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

mod = importlib.import_module("phase1_doc_one_shot_runner")

_PROGRAMS_DIR = Path(mod.__file__).resolve().parent
_L3_GATE = _PROGRAMS_DIR / "l3_opcode_argument_constraints_check.py"


# ---------------------------------------------------------------------------
# FIX 1 — comparator alternation now matches bare exceed verbs
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("line,expected", [
    ("the device replies only if address EXCEEDS 0x7F is not sent", "7F"),
    ("位址超過 0x80 時不回覆", "80"),
    ("if the address is greater than 0x7F there is no reply", "7F"),
    ("addr must not exceed 0x3F", "3F"),
])
def test_addr_max_regex_matches_bare_exceed(line, expected):
    m = mod._V1_6_371_RE_ADDR_MAX.search(line)
    assert m is not None, f"addr_max regex failed to match: {line!r}"
    assert m.group(1).upper() == expected


@pytest.mark.parametrize("line,expected", [
    ("length must not exceed 0x1F per command", "1F"),
    ("讀取長度超過 0x80 → no reply", "80"),
    ("if length is greater than 0x20 the frame is dropped", "20"),
])
def test_len_max_regex_matches_bare_exceed(line, expected):
    m = mod._V1_6_371_RE_LEN_MAX.search(line)
    assert m is not None, f"len_max regex failed to match: {line!r}"
    assert m.group(1).upper() == expected


def test_addr_max_regex_still_ignores_plain_address_prose():
    # Regression guard: a bare "address 0x32" with NO comparator must NOT
    # be read as a max (the v1.6.371 tightening must survive FIX 1).
    assert mod._V1_6_371_RE_ADDR_MAX.search("read register at address 0x32") \
        is None


def test_len_max_regex_still_ignores_plain_length_prose():
    assert mod._V1_6_371_RE_LEN_MAX.search("payload length 0x08 bytes") is None


# ---------------------------------------------------------------------------
# FIX 2 — disk-scan fallback (bound lives only in on-disk sidecar .txt)
# ---------------------------------------------------------------------------
def _eligible_l2():
    return {"protocol_overview": {"half_duplex": True,
                                  "protocol_class": "half_duplex"}}


def test_disk_scan_fallback_captures_addr_len_not_in_memory(tmp_path):
    project = tmp_path / "proj"
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    # The ONLY place the bound appears: an on-disk spreadsheet->txt sidecar
    # that is deliberately NOT in the in-memory `extracted` dict below.
    (docs / "cmd_table.txt").write_text(
        "Command protocol limits\n"
        "address EXCEEDS 0x7F → no reply\n"
        "length must not exceed 0x80\n",
        encoding="utf-8",
    )
    # in-memory extracted dict has the opcode table but NOT the limits sidecar
    extracted = {
        "spec.md": "Opcode Table\nopcode 0x10 read\nopcode 0x20 write\n",
    }
    res = mod.gen_l3_cmd_protocol(project, extracted, _eligible_l2())
    assert res is not None

    l3_path = project / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json"
    assert l3_path.is_file(), "L3 doc was not written"
    data = json.loads(l3_path.read_text())
    assert data["addr_max"] == "0x7F", data.get("addr_max")
    assert data["len_max"] == "0x80", data.get("len_max")

    # End-to-end: the L3 gate (which scans disk) must now PASS.
    cp = subprocess.run(
        [sys.executable, str(_L3_GATE), str(project)],
        capture_output=True, text=True,
    )
    assert cp.returncode == 0, (
        f"L3 gate did not PASS\nstdout={cp.stdout}\nstderr={cp.stderr}")


def test_disk_scan_fallback_does_not_run_for_ineligible_chip(tmp_path):
    # Regression guard: an ineligible (non-protocol) chip must NOT pick up
    # an addr/len max from disk prose even when the disk has a bound line.
    project = tmp_path / "proj"
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "notes.txt").write_text(
        "address EXCEEDS 0x7F somewhere\n", encoding="utf-8")
    extracted = {"spec.md": "a plain cpu core, no opcode protocol here\n"}
    l2 = {"protocol_overview": {"half_duplex": False,
                                "protocol_class": "memory_mapped"}}
    res = mod.gen_l3_cmd_protocol(project, extracted, l2)
    assert res is not None
    data = json.loads(
        (project / "phase1" / "generated_docs" /
         "L3_CMD_PROTOCOL.json").read_text())
    assert data["addr_max"] is None
    assert data["len_max"] is None


# ---------------------------------------------------------------------------
# Legacy-office decode — binary guard + skip path (no raw bytes downstream)
# ---------------------------------------------------------------------------
def _fake_ole_doc_bytes() -> bytes:
    # OLE2 compound-file magic + NUL-laden body — never valid prose.
    return (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
            + b"\x00" * 64
            + b"Word.Document.8\x00"
            + bytes(range(0, 32)) * 4)


def test_extract_doc_legacy_returns_empty_when_no_decoder(tmp_path, monkeypatch):
    # antiword/catdoc/libreoffice all "absent": last-resort raw decode of
    # an OLE blob must be recognised as binary and return "" (NOT garbage).
    monkeypatch.setattr(mod, "_run",
                        lambda *a, **k: (127, "", "COMMAND_NOT_FOUND"))
    monkeypatch.setattr(mod.shutil, "which", lambda *a, **k: None)
    p = tmp_path / "legacy.doc"
    p.write_bytes(_fake_ole_doc_bytes())
    out = mod.extract_doc_legacy(p)
    assert out == "", f"binary .doc leaked downstream: {out[:60]!r}"


def test_extract_doc_legacy_uses_libreoffice_tier(tmp_path, monkeypatch):
    # antiword/catdoc absent, but a libreoffice tier yields prose.
    prose = "This is the decoded prose body of the legacy document.\n"

    def fake_run(cmd, timeout=60):
        if cmd[0] in ("antiword", "catdoc"):
            return (127, "", "COMMAND_NOT_FOUND")
        # soffice/libreoffice convert: drop a .txt into the --outdir
        if "--convert-to" in cmd:
            outdir = Path(cmd[cmd.index("--outdir") + 1])
            (outdir / "doc_out.txt").write_text(prose, encoding="utf-8")
            return (0, "", "")
        return (0, "", "")

    monkeypatch.setattr(mod, "_run", fake_run)
    monkeypatch.setattr(mod.shutil, "which",
                        lambda name: "/usr/bin/soffice"
                        if name in ("soffice", "libreoffice") else None)
    p = tmp_path / "legacy.doc"
    p.write_bytes(_fake_ole_doc_bytes())
    out = mod.extract_doc_legacy(p)
    assert "decoded prose body" in out


def test_binary_garbage_guard_structural_rule():
    # NUL present -> binary; clean ascii -> not binary; mostly-control -> binary
    assert mod._looks_like_binary_garbage(b"abc\x00def", "abcdef") is True
    assert mod._looks_like_binary_garbage(b"hello world", "hello world") is False
    noisy = "".join(chr(c) for c in range(1, 20)) * 10
    assert mod._looks_like_binary_garbage(noisy.encode("latin-1", "ignore"),
                                          noisy) is True


# ---------------------------------------------------------------------------
# FIX C — .xls routes to legacy BIFF decoder
# ---------------------------------------------------------------------------
def test_extract_one_routes_xls_to_legacy(tmp_path, monkeypatch):
    called = {"hit": False}

    def fake_xls(p):
        called["hit"] = True
        return ""

    monkeypatch.setattr(mod, "extract_xls_legacy", fake_xls)
    p = tmp_path / "book.xls"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32)
    out = mod.extract_one(p)
    assert called["hit"] is True
    assert out == ""


def test_extract_xls_legacy_returns_empty_without_decoder(tmp_path, monkeypatch):
    # xlrd import fails AND libreoffice absent -> "" (skip path records gap).
    monkeypatch.setattr(mod.shutil, "which", lambda *a, **k: None)
    real_import = __builtins__["__import__"] if isinstance(
        __builtins__, dict) else __builtins__.__import__

    def blocked_import(name, *a, **k):
        if name == "xlrd":
            raise ImportError("no xlrd")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    p = tmp_path / "book.xls"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
    out = mod.extract_xls_legacy(p)
    assert out == ""
