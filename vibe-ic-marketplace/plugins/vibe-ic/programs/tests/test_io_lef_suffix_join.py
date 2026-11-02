"""Unavailable IO wrapper LEF names rejoin the fingerprinted current PAD_LEFS.

The IO report carries no digest for its LEF names. These controls bind the only
candidate route: the complete PDK-relative set must equal the validated current
STA PAD_LEFS and the bytes must match those PAD_LEFS fingerprints.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS / "tests"))

import flow109_package_ready as D75  # noqa: E402
import latchup_esd_spacing_check as L  # noqa: E402
import test_flow109_package_ready as T  # noqa: E402

FAMILY = next(entry["name"] for entry in
              json.loads((PROGRAMS / "pdk_registry.json").read_text())["pdks"]
              if entry["name"] != "custom_auto_detect")
IO_SUFFIXES = ("libs.ref/neutral_io/lef/io.lef", "libs.ref/neutral_io/lef/io_aux.lef")
TECH_SUFFIX = "libs.ref/neutral_sc/techlef/tech.tlef"
CELL_SUFFIX = "libs.ref/neutral_sc/lef/cells.lef"
AUX_LEF = "VERSION 5.8 ;\nMACRO AUXPAD\n  CLASS PAD ;\n  SIZE 75 BY 350 ;\nEND AUXPAD\nEND LIBRARY\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Moved:
    """A native STA receipt whose recorded PDK carrier left the running image."""

    def __init__(self, tmp_path: Path, monkeypatch, family: str = FAMILY):
        self.tmp = tmp_path
        self.family = family
        self.project = T._project(tmp_path)
        self.authority = T._current_native_authority(self.project, monkeypatch)
        self.folder = self.authority["folder"]
        self.report_path = self.project / D75.IO_REPORT
        self.report = json.loads(self.report_path.read_text())
        self.config = json.loads((self.folder / "config.json").read_text())
        self.runtime = tmp_path / "runtime"
        io_bytes = (self.project / "input/pdk/io.lef").read_bytes()
        contents = {IO_SUFFIXES[0]: io_bytes, IO_SUFFIXES[1]: AUX_LEF.encode(),
                    TECH_SUFFIX: self.authority["tech"].read_bytes(),
                    CELL_SUFFIX: b"VERSION 5.8 ;\nEND LIBRARY\n"}
        for suffix, data in contents.items():
            self.asset(suffix).parent.mkdir(parents=True, exist_ok=True)
            self.asset(suffix).write_bytes(data)
        self.fingerprints = {}
        self.recorded = [self.historical(s) for s in IO_SUFFIXES]
        self.pads = [self.retired(s) for s in IO_SUFFIXES]
        self.config.update({
            "PDK": family, "PAD_LEFS": self.pads,
            "TECH_LEFS": {"nom_*": self.retired(TECH_SUFFIX)},
            "CELL_LEFS": [self.retired(CELL_SUFFIX)],
        })
        for suffix in contents:
            self.fingerprints[self.retired(suffix)] = _sha(self.asset(suffix))
        monkeypatch.setenv("PDK_ROOT", str(self.runtime))
        self.monkeypatch = monkeypatch
        self.apply()

    def asset(self, suffix: str) -> Path:
        return self.runtime / self.family / suffix

    def retired(self, suffix: str, root: str = "retired-store") -> str:
        return str(self.tmp / root / self.family / suffix)

    def historical(self, suffix: str, root: str = "historical-tree") -> str:
        return str(self.tmp / root / "versions" / self.family / suffix)

    def expose_pad(self, suffix: str, raw: str) -> None:
        """Make a named PAD_LEFS member readable with its fingerprinted bytes."""
        Path(raw).parent.mkdir(parents=True, exist_ok=True)
        Path(raw).write_bytes(self.asset(suffix).read_bytes())
        self.fingerprints[raw] = _sha(Path(raw))

    def apply(self, *, rebind_config: bool = True) -> None:
        self.report["io_library_lefs"] = self.recorded
        self.report_path.write_text(json.dumps(self.report))
        self.config["PAD_LEFS"] = self.pads
        (self.folder / "config.json").write_text(json.dumps(self.config))
        if not rebind_config:
            return
        fp_path = self.folder / "input_fingerprint.json"
        fingerprint = json.loads(fp_path.read_text())
        fingerprint["config_files"] = self.fingerprints
        fp_path.write_text(json.dumps(fingerprint))
        receipt_path = self.folder / "vibeic_receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["input"] = fingerprint
        receipt["sha256"].update({
            name: _sha(self.folder / name)
            for name in ("config.json", "input_fingerprint.json")})
        receipt_path.write_text(json.dumps(receipt))


def _traversal_recorded(m):
    m.recorded[0] = m.historical("libs.ref/neutral_io/lef/../lef/io.lef")


def _traversal_pad(m):
    raw = m.retired("libs.ref/neutral_io/lef/../lef/io.lef")
    m.fingerprints[raw] = m.fingerprints.pop(m.pads[0])
    m.pads[0] = raw


def _undeclared_pdk(m):
    del m.config["PDK"]


def _unknown_pdk(m):
    """Readable fingerprinted PAD_LEFS leave the registry as the only stop."""
    family = "unregistered_family"
    m.recorded = [str(m.tmp / "historical-tree" / family / s) for s in IO_SUFFIXES]
    m.pads = []
    for suffix in IO_SUFFIXES:
        raw = str(m.tmp / "readable" / family / suffix)
        m.expose_pad(suffix, raw)
        m.pads.append(raw)
    m.config["PDK"] = family


def _repeated_pdk_recorded(m):
    m.recorded = [str(m.tmp / "tree" / m.family / "nested" / m.family / s)
                  for s in IO_SUFFIXES]


def _repeated_pdk_pad(m):
    m.pads = []
    for suffix in IO_SUFFIXES:
        raw = str(m.tmp / "readable" / m.family / "nested" / m.family / suffix)
        m.expose_pad(suffix, raw)
        m.pads.append(raw)


def _repeated_pdk_inside_equal_suffixes(m):
    nested = [f"libs.ref/{m.family}/lef/{Path(s).name}" for s in IO_SUFFIXES]
    m.recorded = [m.historical(s) for s in nested]
    m.pads = []
    for suffix, name in zip(IO_SUFFIXES, nested):
        raw = str(m.tmp / "readable" / m.family / name)
        m.expose_pad(suffix, raw)
        m.pads.append(raw)


def _missing_recorded_member(m):
    m.recorded.pop()


def _missing_pad_member(m):
    m.pads.pop()


def _foreign_recorded_member(m):
    m.recorded[1] = m.historical("libs.ref/neutral_io/lef/other.lef")


def _duplicate_recorded_suffix(m):
    m.recorded.append(m.recorded[1])


def _duplicate_pad_suffix(m):
    m.pads.append(m.pads[1])


def _changed_bytes(m):
    with m.asset(IO_SUFFIXES[1]).open("ab") as stream:
        stream.write(b"# changed after the native receipt\n")


def _readable_pads(m):
    m.pads = []
    for suffix in IO_SUFFIXES:
        raw = str(m.tmp / "readable" / m.family / suffix)
        m.expose_pad(suffix, raw)
        m.pads.append(raw)


def _changed_bytes_at_readable_pad(m):
    _readable_pads(m)
    m.fingerprints[m.pads[1]] = "0" * 64


def _unfingerprinted_readable_pad(m):
    _readable_pads(m)
    del m.fingerprints[m.pads[1]]


def _absent_candidate(m):
    m.asset(IO_SUFFIXES[1]).unlink()


def _ambiguous_recorded_root(m):
    m.recorded[1] = m.historical(IO_SUFFIXES[1], "other-historical-tree")


def _ambiguous_pad_root(m):
    raw = m.retired(IO_SUFFIXES[1], "other-retired-store")
    m.fingerprints[raw] = m.fingerprints.pop(m.pads[1])
    m.pads[1] = raw


def _ambiguous_runtime_candidates(m):
    nested = m.runtime / m.family / m.family / IO_SUFFIXES[1]
    nested.parent.mkdir(parents=True)
    nested.write_bytes(m.asset(IO_SUFFIXES[1]).read_bytes())
    m.monkeypatch.setenv("PDK_ROOT", str(m.runtime / m.family))


def _partially_readable_record(m):
    path = Path(m.recorded[0])
    path.parent.mkdir(parents=True)
    path.write_bytes(m.asset(IO_SUFFIXES[0]).read_bytes())


def _relative_recorded(m):
    m.recorded = [f"absent/{m.family}/{suffix}" for suffix in IO_SUFFIXES]


def _relative_pad(m):
    raw = f"absent/{m.family}/{IO_SUFFIXES[0]}"
    m.fingerprints[raw] = m.fingerprints.pop(m.pads[0])
    m.pads[0] = raw


def _nonlibrary_suffix(m):
    m.recorded = [m.historical(f"elsewhere/{s}") for s in IO_SUFFIXES]
    m.pads = []
    for suffix in IO_SUFFIXES:
        raw = str(m.tmp / "readable" / m.family / "elsewhere" / suffix)
        m.expose_pad(suffix, raw)
        m.pads.append(raw)


DAMAGES = [value for name, value in sorted(globals().items())
           if name.startswith("_") and callable(value)
           and name not in {"_sha", "_readable_pads"}]


@pytest.fixture
def moved(tmp_path, monkeypatch):
    return Moved(tmp_path, monkeypatch)


def _damage_id(value):
    return value.__name__.lstrip("_")


def _latchup_context(m):
    return L.current_lef_context(m.project, m.folder, m.authority["def"])


def test_d75_consumes_the_fingerprinted_pad_lefs_for_unavailable_names(moved):
    report_before = moved.report_path.read_bytes()
    receipt_before = (moved.folder / "vibeic_receipt.json").read_bytes()
    result = D75.execute(moved.project, T._context(moved.project))
    assert result["component_status"] == "PASS", result
    assert T._by_name(result, "current_native_geometry_authority")["status"] == "PASS"
    assert T._by_name(result, "pad_bterm_coincidence_check")["status"] == "PASS"
    recorded = {item["path"]: item["sha256"] for item in result["inputs"]}
    for suffix in (*IO_SUFFIXES, TECH_SUFFIX):
        path = str(moved.asset(suffix).resolve())
        assert recorded[path] == moved.fingerprints[moved.retired(suffix)]
    assert not [path for path in recorded
                if "historical-tree" in path or "retired-store" in path]
    assert moved.report_path.read_bytes() == report_before
    assert (moved.folder / "vibeic_receipt.json").read_bytes() == receipt_before
    assert not [key for key in json.loads(receipt_before)["input"]["config_files"]
                if "historical-tree" in key]
    D75.validate(moved.project, result)


def test_io_order_is_the_report_order_not_the_pad_order(moved):
    moved.pads.reverse()
    moved.apply()
    assert D75._io_lefs(moved.project, moved.report) == [
        moved.asset(suffix) for suffix in IO_SUFFIXES]


@pytest.mark.parametrize("damage", DAMAGES, ids=_damage_id)
def test_d75_refuses_an_unproven_join(moved, damage):
    damage(moved)
    moved.apply()
    result = D75.execute(moved.project, T._context(moved.project))
    assert result["component_status"] == "NOT_MEASURED", result
    assert result["reason"] == "D75_IO_LIBRARY_UNBOUND", result


def test_d75_refuses_without_a_current_sta_record(moved):
    (moved.project / "reports/phase3/sta_postpnr_signoff.json").unlink()
    result = D75.execute(moved.project, T._context(moved.project))
    assert result["reason"] == "D75_IO_LIBRARY_UNBOUND", result


def test_d75_refuses_a_config_changed_after_its_receipt(moved):
    moved.config["PAD_LEFS"] = moved.pads
    moved.config["UNBOUND_EDIT"] = True
    moved.apply(rebind_config=False)
    result = D75.execute(moved.project, T._context(moved.project))
    assert result["reason"] == "D75_IO_LIBRARY_UNBOUND", result


def test_d75_refuses_a_config_outside_its_receipt(moved):
    path = moved.folder / "vibeic_receipt.json"
    receipt = json.loads(path.read_text())
    del receipt["sha256"]["config.json"]
    path.write_text(json.dumps(receipt))
    result = D75.execute(moved.project, T._context(moved.project))
    assert result["reason"] == "D75_IO_LIBRARY_UNBOUND", result


def test_d75_refuses_changed_tech_bytes_behind_a_valid_io_join(moved):
    moved.asset(TECH_SUFFIX).write_bytes(b"UNITS\n  DATABASE MICRONS 1000 ;\nEND UNITS\n")
    result = D75.execute(moved.project, T._context(moved.project))
    assert result["reason"] == "D75_CURRENT_NATIVE_GEOMETRY_UNBOUND", result


def test_readable_recorded_names_never_enter_the_join(tmp_path, monkeypatch):
    """No PDK, repeated components and no STA record: today's direct read stands."""
    project = T._project(tmp_path)
    readable = tmp_path / FAMILY / "again" / FAMILY / "io.lef"
    readable.parent.mkdir(parents=True)
    readable.write_bytes((project / "input/pdk/io.lef").read_bytes())
    relative = "input/pdk/io.lef"
    report = {"io_library_lefs": [str(readable), relative]}
    assert D75._io_lefs(project, report) == [readable, project / relative]


def test_latchup_context_reopens_the_same_join(moved):
    context = _latchup_context(moved)
    rows = {row["path"]: row["sha256"] for row in context["lefs"]}
    for suffix in (*IO_SUFFIXES, CELL_SUFFIX):
        assert rows[str(moved.asset(suffix))] == moved.fingerprints[moved.retired(suffix)]
    assert context["roles"] == {"PADX": "PAD"}
    assert L._checked_lef_roles(context, moved.authority["def"]) == {"PADX": "PAD"}


@pytest.mark.parametrize("damage", DAMAGES, ids=_damage_id)
def test_latchup_context_refuses_an_unproven_join(moved, damage):
    damage(moved)
    moved.apply()
    with pytest.raises(ValueError, match="PERC_LEF_IO_AUTHORITY_MISMATCH"):
        _latchup_context(moved)


def test_latchup_context_refuses_changed_cell_bytes(moved):
    changed = b"VERSION 5.8 ;\n# changed\nEND LIBRARY\n"
    moved.asset(CELL_SUFFIX).write_bytes(changed)
    with pytest.raises(FileNotFoundError):
        _latchup_context(moved)
    readable = Path(moved.retired(CELL_SUFFIX))
    readable.parent.mkdir(parents=True)
    readable.write_bytes(changed)
    with pytest.raises(ValueError, match="PERC_LEF_BYTES_CHANGED"):
        _latchup_context(moved)
