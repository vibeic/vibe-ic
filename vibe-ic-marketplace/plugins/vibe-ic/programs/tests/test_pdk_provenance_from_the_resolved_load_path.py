"""PDK provenance is decided from the RESOLVED LOAD PATH, and the sample is stated.

The gate's own PASS record said `verified: "library identity only"` and
`not_verified: "foundry / process node (not derivable from a library filename)"`.
Both sentences were true of a FILENAME, and a filename was the whole of the
evidence — `loaded_libraries` kept the basename and threw away the directory the
tool had just resolved. On this repo's own tracked corpus the same gate reported
"PASS — 2 of 2 loaded librar(ies) match" on a run whose own artefacts resolve
FIVE distinct library load paths under one kit directory; the missing three are
two timing corners and the technology LEF. Of those five the gate can now
account for three from that run's `*.log` files — the two corners are named only
in `.rpt`/`.tcl`, which this program deliberately does not read. The other two
are not recovered; what changes for them is that the record now states the
denominator.

Every fixture below is synthetic. `zq42k3` / `othernode` name no real process.
The three tests that must exercise `_NAMED_PDK_RE` use entries from that table
because that is what the table is — the same precedent the sibling test file
already sets — and the rule logic under test contains no PDK literal at all.

RUN THIS FILE AGAINST THE PRE-FIX PROGRAM by pointing `VIBE_IC_PDK_GATE` at it.
Every test marked CONTROL must fail there and pass here; every test marked
REVERSE must pass in BOTH directions, because a rule that fires on everything is
not a fix.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

GATE = Path(os.environ.get(
    "VIBE_IC_PDK_GATE",
    Path(__file__).resolve().parents[1] / "declared_pdk_is_the_pdk_used_check.py"))


def _mk(root: Path, *, target, loaded, staged=("zq42k3_sc.lib",), logs=1):
    """A run that declares `target` and whose logs record `loaded` load paths."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "phase1").mkdir(parents=True, exist_ok=True)
    if target is not None:
        (root / "phase1" / "pdk_staging_read.json").write_text(
            json.dumps({"adopted_pdk_target": target}), encoding="utf-8")
    for name in staged:
        f = root / "input" / "pdk" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("library (x) { }\n", encoding="utf-8")
    d = root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    if logs == 1:
        d.joinpath("tool.log").write_text(
            "".join(f"[INFO ODB-0227] LEF file: {p}, created 1 layers\n"
                    for p in loaded), encoding="utf-8")
    else:
        for i in range(logs):
            p = loaded[i % len(loaded)] if loaded else ""
            d.joinpath(f"tool{i:04d}.log").write_text(
                f"[INFO ODB-0227] LEF file: {p}, created 1 layers\n" if p else "",
                encoding="utf-8")
    return root


def _run(root: Path):
    rec = root.parent / f"{root.name}.rec.json"
    p = subprocess.run([sys.executable, str(GATE), str(root), "--json", str(rec)],
                       capture_output=True, text=True, timeout=55)
    d = json.loads(rec.read_text()) if rec.is_file() else {}
    return p.returncode, p.stdout + p.stderr, d


_DECLARED = "Example Foundry ZQ42-K3"
_KIT = "/opt/eda-image/kits/zq42k3"


# ── CONTROL: these FAIL against the pre-fix program ─────────────────────────

def test_provenance_comes_from_the_resolved_load_path(tmp_path):
    """CONTROL. The kit's libraries are named for the FAMILY, not the process.

    `merged.lef` and `cells.lib` carry no identity a filename matcher can use —
    every kit on earth ships files with those names. The directory the tool
    resolved names the process outright. Deciding from the basename, this run
    reports that it cannot show which process it implemented against; deciding
    from the path, it plainly can.
    """
    r = _mk(tmp_path / "run", target=_DECLARED,
            loaded=[f"{_KIT}/libs/merged.lef", f"{_KIT}/libs/cells.lib"])
    rc, out, rec = _run(r)
    assert rc == 0, out
    assert rec["verdict"] == "PASS"
    assert rec["matched_by_load_path_only"], rec
    assert rec["provenance_source"] == "load path", rec
    assert rec["verified"] == "library identity + load-path provenance", rec


def test_the_technology_lef_is_a_library_load(tmp_path):
    """CONTROL. `.tlef` describes the METAL STACK — the most process-identifying
    file in the kit — and the pattern did not match it, so the gate whose job is
    to identify the process could not see it."""
    r = _mk(tmp_path / "run", target=_DECLARED,
            loaded=[f"{_KIT}/tech/zq42k3_tech.tlef"])
    rc, out, rec = _run(r)
    assert rc == 0, out
    assert rec["libraries_examined"] == 1, rec
    assert "no cell-library load at all" not in out


def test_examined_counts_load_paths_not_filenames(tmp_path):
    """CONTROL, and the exact 2-vs-5 shape measured on the tracked corpus.

    Five distinct resolved load paths: one kit, two cell flavours, a corner
    each, and the technology LEF. Collapsed to basenames — and with `.tlef`
    invisible — they are TWO. "2 of 2 match" then prints a sample as if it were
    the population it was drawn from.
    """
    r = _mk(tmp_path / "run", target=_DECLARED, loaded=[
        f"{_KIT}/libs/hd/zq42k3_sc.lef",
        f"{_KIT}/libs/hs/zq42k3_sc.lef",
        f"{_KIT}/libs/hd/zq42k3_sc.lib",
        f"{_KIT}/libs/hs/zq42k3_sc.lib",
        f"{_KIT}/tech/zq42k3_tech.tlef",
    ])
    rc, out, rec = _run(r)
    assert rc == 0, out
    assert rec["libraries_examined"] == 5, rec
    assert rec["matching_libraries_total"] == 5, rec
    assert len(rec["libraries_loaded_basenames"]) == 3, rec
    assert "5 of 5" in out, out


def test_a_truncated_scan_says_it_is_truncated(tmp_path):
    """CONTROL. The 400-log cap and the 40-entry record list both truncate in
    silence, so a capped scan reported the same shape as a complete one."""
    r = _mk(tmp_path / "run", target=_DECLARED, logs=401,
            loaded=[f"{_KIT}/libs/l{i:04d}/zq42k3_sc.lef" for i in range(401)])
    rc, out, rec = _run(r)
    assert rc == 0, out
    assert rec["logs_found"] == 401, rec
    assert rec["logs_scanned"] == 400, rec
    assert rec["logs_scan_truncated"] is True, rec
    assert rec["libraries_loaded_truncated"] is True, rec
    assert len(rec["libraries_loaded"]) == 40, rec
    assert "SAMPLE" in out, out


def test_a_kit_the_declaration_never_names_is_a_fail(tmp_path):
    """CONTROL, and the defect this whole file exists for.

    The declared kit IS staged and one load does come from it, so a filename
    matcher finds its match and PASSes. The other load came out of the image's
    own kit directory — a process the declaration never mentions. That is the
    substitution the header describes, and from a basename it is invisible.

    `_NAMED_PDK_RE` entry, not a design literal: the table is what is being
    exercised.
    """
    r = _mk(tmp_path / "run", target=_DECLARED, loaded=[
        "/run/input/pdk/zq42k3/libs/zq42k3_sc.lef",
        "/opt/eda-image/pdks/nangate45/lib/NangateOpenCellLibrary.lef",
    ])
    rc, out, rec = _run(r)
    assert rc == 1, out
    assert "nangate45" in rec["foreign_named_pdk_roots"], rec
    assert "the declaration does not name" in out, out


def test_a_family_declaration_is_corroborated_by_the_kit_directory(tmp_path):
    """CONTROL, in the shape the tracked corpus is actually in: the design
    declares the kit FAMILY and the image ships the lettered variant of it, with
    library filenames that carry neither. Only the path answers."""
    r = _mk(tmp_path / "run", target="sky130", staged=(), loaded=[
        "/foss/pdks/sky130A/libs.ref/xx_sc_hd/lef/xx_sc_hd.lef",
        "/foss/pdks/sky130A/libs.ref/xx_sc_hd/techlef/xx_sc_hd__nom.tlef",
    ])
    rc, out, rec = _run(r)
    assert rc == 0, out
    assert rec["foreign_named_pdk_roots"] == {}, rec
    assert rec["matched_by_load_path_only"], rec


# ── REVERSE: these must pass in BOTH directions ────────────────────────────

def test_a_healthy_run_still_passes(tmp_path):
    """REVERSE. Declared, staged, and read from the declared kit's own
    directory with filenames that carry the identity too. If this stopped
    passing, the rule would be firing on legitimate state."""
    r = _mk(tmp_path / "run", target=_DECLARED, loaded=[
        f"{_KIT}/libs/zq42k3_sc.lef", f"{_KIT}/libs/zq42k3_sc__tt_025C.lib"])
    rc, out, rec = _run(r)
    assert rc == 0, out
    assert rec["verdict"] == "PASS"


def test_a_substituted_kit_is_still_reported(tmp_path):
    """REVERSE, and the one that matters most: the real defect underneath.

    A rule tuned until a count reached zero would swallow this. The declared kit
    is staged, the tools read a DIFFERENT one, and that must still be a FAIL —
    it was before this change and it is after.
    """
    r = _mk(tmp_path / "run", target=_DECLARED,
            loaded=["/opt/eda-image/kits/othernode/lib/othernode_sc.lef"])
    rc, out, rec = _run(r)
    assert rc == 1, out
    assert rec["verdict"] == "FAIL"
    assert "was not the one used" in out, out


def test_a_run_directory_named_for_a_process_does_not_corroborate_itself(tmp_path):
    """REVERSE. The circularity the path opens, closed.

    A run stored under `<design>_<process>/` would otherwise corroborate its own
    declaration out of its own folder name and report that it had confirmed the
    kit when it had confirmed the filing system. The load below happens inside
    that directory and carries no other identity, so it must corroborate
    nothing — the same load path from a directory that is NOT the run's own does
    pass, one test up.
    """
    root = tmp_path / "design_zq42k3"
    r = _mk(root, target=_DECLARED,
            loaded=[f"{root}/build/pnr/merged.lef"])
    rc, out, rec = _run(r)
    assert rc == 1, out
    assert rec["matching_libraries"] == [], rec


def test_a_run_created_round_directory_does_not_corroborate_either(tmp_path):
    """REVERSE, and the hole the corpus sweep found before this landed.

    The circular directory need not be the run root itself. A flow that files
    each round under `clean_run_..._<process>_<date>/` puts the process name one
    level BELOW the root, where a run-root name check cannot see it. Measured on
    a real tracked project: two memory-macro loads whose filenames carry no
    process identity were corroborated out of exactly such a folder.

    A load that resolves inside the run tree carries no provenance — the flow
    put those bytes there. It is still judged by its filename, which is what
    leaves this a FAIL rather than a PASS on a folder name.
    """
    root = tmp_path / "run"
    r = _mk(root, target=_DECLARED, loaded=[
        f"{root}/clean_run_v1_zq42k3_20260101/input/pdk_local/macros/sram2048.lef",
    ])
    rc, out, rec = _run(r)
    assert rc == 1, out
    assert rec["matching_libraries"] == [], rec


def test_a_vendor_prefixed_kit_directory_is_not_a_foreign_root(tmp_path):
    """REVERSE. The declaration names the kit; the image files it under the
    vendor-prefixed spelling of the same kit. Two spellings of one identifier
    must not read as two processes.

    `_NAMED_PDK_RE` entries, for the same reason as the control above.
    """
    r = _mk(tmp_path / "run", target="sg13g2", staged=(), loaded=[
        "/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef",
        "/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_tech.lef",
    ])
    rc, out, rec = _run(r)
    assert rc == 0, out
    # `.get` with a default, deliberately: a REVERSE case must be readable
    # against the PRE-FIX program too, where this key does not exist. Asserting
    # a new field here would make the test fail for the wrong reason and the
    # both-directions claim would prove nothing.
    assert rec.get("foreign_named_pdk_roots", {}) == {}, rec


def test_no_load_at_all_is_still_the_unchanged_verdict(tmp_path):
    """REVERSE. Nothing about keeping the path changes the run that recorded no
    load: still FAIL, still not an accusation that another kit was used."""
    r = _mk(tmp_path / "run", target=_DECLARED, loaded=[])
    rc, out, rec = _run(r)
    assert rc == 1, out
    assert rec["no_library_load_recorded"] is True, rec
    assert rec["libraries_loaded"] == [], rec
    assert rec.get("libraries_examined", 0) == 0, rec
    assert "was not the one used" not in out, out
