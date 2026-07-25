"""Regression tests for gds_deliverable_plausibility_check.py.

Field observation that produced this gate (spm x ihp-sg13g2, plugin
1.5.74): a sign-off run reported

    overall verdict : PASS_WITH_WAIVERS
    overall.pct     : 100.0%

while `ls -l` on the Step-37 deliverable showed 86 bytes.

Two distinct facts came out of the artefact investigation, and this file
pins both:

  1. The 86 bytes were a SYMLINK's own size (the length of its target
     path string). `stat -L` resolved to a genuine 822,084-byte layout.
     A gate must therefore report BOTH sizes so nobody re-derives the
     false alarm -> `TestSymlinkTransparency`.
  2. The gate that was actually wired at Step 37 (`gds_size_check`
     v1.1.0) could not have caught a real 86-byte-class failure for the
     right reason anyway: its ONLY fatal criterion was a hardcoded
     100 KB byte floor, and its GDSII-format check was a WARNING. Any
     blob at or above the floor passed sign-off -> `TestNegativeControl`.

NEGATIVE-CONTROL CONTRACT
-------------------------
`TestNegativeControl` asserts, for every fixture, BOTH:
  (a) the fixture satisfies everything the pre-fix wired gate checked
      (it exists, is non-empty, and is >= the 100 KB backstop), so the
      pre-fix flow reported PASS on it; and
  (b) this gate FAILs it.
A test that cannot fail against the unfixed code proves nothing, so (a)
is asserted explicitly rather than assumed.
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "gds_deliverable_plausibility_check.py"
SIZE_PROG = Path(__file__).resolve().parent.parent / "gds_size_check.py"
assert PROG.exists(), f"program not found: {PROG}"

# The byte floor the pre-fix Step-37 gate used, in bytes. Referenced only
# to prove the negative-control fixtures cleared it.
PREFIX_BACKSTOP_BYTES = 100 * 1024


# ---------------------------------------------------------------------------
# Minimal well-formed GDSII builder (test fixture only)
# ---------------------------------------------------------------------------
def _rec(rtype: int, payload: bytes = b"") -> bytes:
    if len(payload) % 2:
        payload += b"\x00"
    return struct.pack(">HH", len(payload) + 4, rtype) + payload


def _ascii(name: str) -> bytes:
    b = name.encode("ascii")
    return b + (b"\x00" if len(b) % 2 else b"")


def build_gds(top: str = "top", n_placements: int = 8,
              pad_records: int = 0, pad_points: int = 7000,
              cell: str = "leaf", with_endlib: bool = True) -> bytes:
    """A structurally valid GDSII stream with `n_placements` SREFs.

    `pad_records` appends that many oversized boundaries so a fixture can
    reach an arbitrary byte size while keeping its PLACEMENT count low —
    exactly the shape a "big enough but empty for this design" stub has.
    A GDSII record length is a uint16, so the padding is spread across
    several records rather than one huge one.
    """
    out = [
        _rec(0x0002, struct.pack(">h", 3)),                 # HEADER
        _rec(0x0102, struct.pack(">12h", *([1] * 12))),     # BGNLIB
        _rec(0x0206, _ascii("LIB")),                        # LIBNAME
        _rec(0x0305, b"\x00" * 16),                         # UNITS
    ]

    # Leaf cell: one boundary on a real layer.
    out += [
        _rec(0x0502, struct.pack(">12h", *([1] * 12))),     # BGNSTR
        _rec(0x0606, _ascii(cell)),                         # STRNAME
        _rec(0x0800),                                       # BOUNDARY
        _rec(0x0D02, struct.pack(">h", 1)),                 # LAYER
        _rec(0x0E02, struct.pack(">h", 0)),                 # DATATYPE
        _rec(0x1003, struct.pack(">8i", 0, 0, 0, 10, 10, 10, 10, 0)),
        _rec(0x1100),                                       # ENDEL
        _rec(0x0700),                                       # ENDSTR
    ]

    # Top cell: n SREFs of the leaf, plus an optional oversized boundary.
    top_body = [
        _rec(0x0502, struct.pack(">12h", *([1] * 12))),
        _rec(0x0606, _ascii(top)),
    ]
    for i in range(n_placements):
        top_body += [
            _rec(0x0A00),                                   # SREF
            _rec(0x1206, _ascii(cell)),                     # SNAME
            _rec(0x1003, struct.pack(">2i", i * 100, 0)),   # XY
            _rec(0x1100),                                   # ENDEL
        ]
    for _ in range(pad_records):
        xy = struct.pack(">%di" % (2 * pad_points),
                         *([0] * (2 * pad_points)))
        top_body += [
            _rec(0x0800),
            _rec(0x0D02, struct.pack(">h", 1)),
            _rec(0x0E02, struct.pack(">h", 0)),
            _rec(0x1003, xy),
            _rec(0x1100),
        ]
    top_body.append(_rec(0x0700))
    out += top_body
    if with_endlib:
        out.append(_rec(0x0400))                            # ENDLIB
    return b"".join(out)


def make_project(tmp_path: Path, gds: bytes | None, components: int,
                 top: str = "top", design: str | None = None,
                 gds_name: str | None = None) -> Path:
    """A minimal project tree: one routed DEF + one canonical chip GDS."""
    proj = tmp_path / "proj"
    (proj / "phase3" / "stage3" / "pnr").mkdir(parents=True, exist_ok=True)
    (proj / "phase3" / "stage4" / "gds").mkdir(parents=True, exist_ok=True)
    (proj / "phase3" / "stage3" / "pnr" / "routed.def").write_text(
        f"VERSION 5.8 ;\nDESIGN {design or top} ;\n"
        f"COMPONENTS {components} ;\nEND COMPONENTS\nEND DESIGN\n")
    if gds is not None:
        (proj / "phase3" / "stage4" / "gds"
         / (gds_name or f"{top}.gds")).write_bytes(gds)
    return proj


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True)


def run_prefix_size_gate(gds_path: Path) -> int:
    """Exit code of the byte-floor gate the pre-fix flow relied on."""
    return subprocess.run(
        [sys.executable, str(SIZE_PROG), "--gds-file", str(gds_path),
         "--min-size-kb", "100"],
        capture_output=True, text=True).returncode


# ===========================================================================
# The guard must not fire on legitimate passing state
# ===========================================================================
class TestHealthyDesign:
    def test_well_formed_gds_passes(self, tmp_path):
        proj = make_project(tmp_path, build_gds(n_placements=64), 64)
        r = run([str(proj)])
        assert r.returncode == 0, r.stdout + r.stderr

    def test_coverage_margin_tolerated(self, tmp_path):
        """Streamout need not emit one SREF per DEF component exactly."""
        proj = make_project(tmp_path, build_gds(n_placements=80), 100)
        assert run([str(proj)]).returncode == 0

    def test_no_gds_yet_is_vacuous_pass(self, tmp_path):
        """Pre-stream-out projects must not be failed by this gate."""
        proj = make_project(tmp_path, None, 100)
        r = run([str(proj)])
        assert r.returncode == 2
        assert "VACUOUS_PASS" in r.stdout

    def test_no_def_keeps_structural_checks(self, tmp_path):
        """Without a DEF the byte floor is undecidable — say so, don't pass
        silently, and keep failing structurally broken streams."""
        proj = tmp_path / "p"
        (proj / "phase3" / "stage4" / "gds").mkdir(parents=True)
        (proj / "phase3" / "stage4" / "gds" / "top.gds").write_bytes(
            build_gds(n_placements=32))
        r = run([str(proj), "--json", str(tmp_path / "r.json")])
        assert r.returncode == 0
        rules = {f["rule"] for f in
                 json.loads((tmp_path / "r.json").read_text())["findings"]}
        assert "DESIGN_FLOOR_NOT_DERIVABLE" in rules


# ===========================================================================
# NEGATIVE CONTROL — each fixture passed the pre-fix wired gate
# ===========================================================================
class TestNegativeControl:
    """Every fixture here cleared the pre-fix gate's only fatal criterion.

    Each case asserts the pre-fix gate's exit code explicitly, so if a
    future refactor makes these fixtures fail for a trivial reason the
    negative-control property is caught rather than silently lost.
    """

    # Explicit ids: pytest derives node ids from parameter values, and a
    # 150 KB bytes literal would produce a node id long enough to blow the
    # PYTEST_CURRENT_TEST env var past E2BIG in any subprocess call.
    @pytest.mark.parametrize("name,payload", [
        ("zero_blob", b"\x00" * 150_000),
        ("renamed_error_log",
         b"ERROR: detailed route failed, no layout produced\n" * 3200),
    ], ids=["zero_blob", "renamed_error_log"])
    def test_non_gds_blob_above_backstop(self, tmp_path, name, payload):
        assert len(payload) >= PREFIX_BACKSTOP_BYTES
        proj = make_project(tmp_path, payload, 1826)
        gds = proj / "phase3" / "stage4" / "gds" / "top.gds"
        # Pre-fix criterion: exists, non-empty, >= the 100 KB backstop.
        assert gds.stat().st_size >= PREFIX_BACKSTOP_BYTES
        r = run([str(proj)])
        assert r.returncode == 1, f"{name} was accepted as a sign-off GDS"
        assert "NOT_A_GDS" in r.stderr

    def test_header_prefix_then_garbage(self, tmp_path):
        """Four valid header bytes + garbage: pre-fix this produced ZERO
        findings and exit 0 — the cleanest possible false PASS."""
        payload = b"\x00\x06\x00\x02\x00\x03" + b"\xAB" * 149_994
        proj = make_project(tmp_path, payload, 1826)
        gds = proj / "phase3" / "stage4" / "gds" / "top.gds"
        assert run_prefix_size_gate(gds) == 0, (
            "fixture no longer reproduces the pre-fix PASS")
        assert run([str(proj)]).returncode == 1

    def test_big_enough_but_empty_for_this_design(self, tmp_path):
        """The hardcoded-floor hole: a structurally VALID 120 KB GDS that
        places 20 instances, for a design whose own DEF places 200,000.

        The pre-fix gate exits 0 (valid header, above 100 KB). It is not
        a plausible layout of this design.
        """
        gds = build_gds(n_placements=20, pad_records=3)
        assert len(gds) >= PREFIX_BACKSTOP_BYTES
        proj = make_project(tmp_path, gds, 200_000)
        gds_path = proj / "phase3" / "stage4" / "gds" / "top.gds"
        assert run_prefix_size_gate(gds_path) == 0, (
            "fixture no longer reproduces the pre-fix PASS")
        r = run([str(proj), "--json", str(tmp_path / "r.json")])
        assert r.returncode == 1
        rules = {f["rule"] for f in
                 json.loads((tmp_path / "r.json").read_text())["findings"]}
        assert "GDS_BELOW_DESIGN_FLOOR" in rules
        assert "GDS_PLACEMENT_SHORTFALL" in rules

    def test_floor_scales_with_the_design(self, tmp_path):
        """The SAME GDS is fine for a small design and impossible for a
        large one — proving the floor is design-derived, not a constant."""
        gds = build_gds(n_placements=20, pad_records=3)
        assert run([str(make_project(tmp_path / "a", gds, 20))]).returncode == 0
        assert run([str(make_project(tmp_path / "b", gds, 200_000))]).returncode == 1


# ===========================================================================
# The 86-byte artefact class
# ===========================================================================
class TestTinyDeliverable:
    def test_86_byte_deliverable_fails(self, tmp_path):
        """An 86-byte real file at the canonical path is never a layout."""
        payload = b"\x00\x06\x00\x02\x00\x03" + b"\x00" * 80
        assert len(payload) == 86
        proj = make_project(tmp_path, payload, 1826)
        assert run([str(proj)]).returncode == 1

    def test_truncated_stream_fails(self, tmp_path):
        """A streamer killed mid-write leaves no ENDLIB."""
        proj = make_project(tmp_path, build_gds(n_placements=64,
                                                with_endlib=False), 64)
        r = run([str(proj), "--json", str(tmp_path / "r.json")])
        assert r.returncode == 1
        rules = {f["rule"] for f in
                 json.loads((tmp_path / "r.json").read_text())["findings"]}
        assert "GDS_NO_ENDLIB" in rules

    def test_zero_components_def_fails(self, tmp_path):
        """A tool that genuinely placed nothing must not reach PASS."""
        proj = make_project(tmp_path, build_gds(n_placements=8), 0)
        r = run([str(proj), "--json", str(tmp_path / "r.json")])
        assert r.returncode == 1
        rules = {f["rule"] for f in
                 json.loads((tmp_path / "r.json").read_text())["findings"]}
        assert "DEF_ZERO_COMPONENTS" in rules


# ===========================================================================
# Symlink transparency — the source of the original false alarm
# ===========================================================================
class TestSymlinkTransparency:
    def test_symlink_reports_both_sizes(self, tmp_path):
        """`ls -l` on a symlink shows the target-path length, not the GDS.

        The gate must surface apparent AND resolved size so a reviewer
        cannot mistake one for the other — and must not fail a healthy
        design merely because the path is a link (that is
        chip_gds_canonical_real_file_check's call, not this gate's).
        """
        real = tmp_path / "elsewhere" / "top.gds"
        real.parent.mkdir(parents=True)
        real.write_bytes(build_gds(n_placements=64))
        proj = make_project(tmp_path, None, 64)
        link = proj / "phase3" / "stage4" / "gds" / "top.gds"
        link.symlink_to(real)

        r = run([str(proj), "--json", str(tmp_path / "r.json")])
        assert r.returncode == 0
        rep = json.loads((tmp_path / "r.json").read_text())
        art = rep["artefacts"][0]
        assert art["is_symlink"] is True
        assert art["apparent_size_bytes"] == len(str(real))
        assert art["size_bytes"] == real.stat().st_size
        assert art["apparent_size_bytes"] != art["size_bytes"]
        assert "DELIVERABLE_IS_SYMLINK" in {f["rule"] for f in rep["findings"]}

    def test_broken_symlink_is_not_vacuous(self, tmp_path):
        """A dangling deliverable must FAIL, never reach VACUOUS_PASS."""
        proj = make_project(tmp_path, None, 64)
        (proj / "phase3" / "stage4" / "gds" / "top.gds").symlink_to(
            tmp_path / "does_not_exist.gds")
        assert run([str(proj)]).returncode == 1


# ===========================================================================
# Corpus sweep — must NOT fire on genuinely converged reference layouts
# ===========================================================================
_CORPUS_ROOT = Path(__file__).resolve().parents[5] / "benchmark-data" / "ic"


def _corpus_cells() -> list[Path]:
    if not _CORPUS_ROOT.is_dir():
        return []
    return sorted({p.parents[3]
                   for p in _CORPUS_ROOT.glob("*/*/phase3/stage4/gds/*.gds")})


@pytest.mark.skipif(not _corpus_cells(),
                    reason="benchmark-data corpus not present in this tree")
@pytest.mark.parametrize("cell", _corpus_cells(),
                         ids=lambda p: f"{p.parent.name}_{p.name}")
def test_corpus_converged_cells_pass(cell):
    """A guard that flags legitimate passing state is a bug, not a guard."""
    r = run([str(cell)])
    assert r.returncode == 0, f"{cell} was flagged: {r.stdout}{r.stderr}"
