#!/usr/bin/env python3
"""The fixtures in `fixtures/ppa/` are shared by every PPA lane, and a shared
fixture fails in a way a private one cannot: silently, everywhere at once.

WHY THIS FILE EXISTS AT ALL

A fixture tree has exactly one dangerous failure mode. Somebody edits a NEGATIVE
fixture until it stops being negative -- adds the missing view, gives the waiver
an owner, puts geometry in the empty layout -- because on the day they touch it,
that looks like fixing a broken input. The tests built on it all turn green and
STAY green, and no other test in this repository can tell. A suite of only
positive fixtures is a gate that is always green; a suite whose negative fixtures
have quietly decayed into positive ones is worse, because it still looks like it
has negatives.

So this file does not test any lane's code. It tests that the FIXTURES still
carry the properties they were built to carry:

  * every file is in the manifest with a matching sha256 (nothing edited)
  * every file on disk is IN the manifest (nothing added without provenance --
    a fixture whose origin is unknown is worthless the moment it disagrees
    with someone)
  * the absent things are still absent
  * the negative things are still negative

WHY THE CHECK IS ALSO A CLI

`python3 test_ppa_fixture_integrity.py --root <dir>` honours the exit-code
contract in docs/PPA_INTERFACES.md §1 (0 pass / 1 finding / 2 undetermined /
3 bad invocation), so the fixture tree can be gated outside pytest too. It
lives in the test file rather than in `programs/` on purpose: adding a
top-level program would require an edit to `programs/INDEX.md` and
`PROGRAM_INVENTORY.json`, and those have a single writer (the lander).
If the lander wants it promoted, see RESULT.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "ppa"
MANIFEST_NAME = "MANIFEST.json"

# The path that must never come into existence. See fixtures/ppa/vacuous/README.md.
ABSENT_REL = "vacuous/absent_report.rpt"

MARKER_CANNOT_CHECK = "[CANNOT CHECK]"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def iter_fixture_files(root: pathlib.Path):
    """Every regular file under root except the manifest itself.

    Sorted, so a failure names the same file on every machine.
    """
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != MANIFEST_NAME:
            yield p


def load_manifest(root: pathlib.Path) -> dict:
    return json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))


def load_json(root: pathlib.Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def count_rdb(root: pathlib.Path, rel: str) -> tuple[int, int]:
    """(categories, items) in a KLayout report-database XML.

    Counted by tag, not parsed as a schema: the property under test is how many
    of each element the tool emitted, and a regex cannot be fooled by a
    namespace change the way a stricter reader could be broken by one.
    """
    text = (root / rel).read_text(encoding="utf-8", errors="replace")
    return len(re.findall(r"<category>", text)), len(re.findall(r"<item>", text))


def count_shapes(root: pathlib.Path, rel: str) -> int:
    """Shapes in a layout, measured by the program that already owns the question.

    Deliberately NOT a private copy of a GDS walker. `drc_vacuous_pass_check`
    is the program that decides whether a DRC clean was earned, so validating
    the fixture with the same measurement it will be consumed by is the only
    way to know the fixture still means what it claims.
    """
    import drc_vacuous_pass_check as dvp

    return dvp.measure_layout(root / rel).shapes


def _num(pattern: str, text: str) -> float:
    m = re.search(pattern, text, re.M)
    assert m, "pattern not found: %s" % pattern
    return float(m.group(1))


def waiver_has_owner(entry: dict) -> bool:
    """An owner is a party that can be asked. A status is not an owner.

    The `approver` KEY being present proves nothing -- the real published waiver
    this fixture is built from has `"approver": "tapeout-review-pending"`, which
    is a state of the process, not somebody who accepted the risk.
    """
    v = (entry.get("approver") or "").strip()
    if not v:
        return False
    placeholder = re.compile(
        r"^(tbd|n/?a|none|unknown|pending|unassigned|-+|\?+)$"
        r"|(^|[^a-z])pending([^a-z]|$)",
        re.I,
    )
    return not placeholder.search(v)


# --------------------------------------------------------------------------
# the checks — each returns a list of finding strings (empty == clean)
# --------------------------------------------------------------------------
def check_manifest_covers_tree(root: pathlib.Path) -> list[str]:
    man = load_manifest(root)
    listed = {e["path"] for e in man["files"]}
    on_disk = {str(p.relative_to(root)) for p in iter_fixture_files(root)}
    out = []
    for extra in sorted(on_disk - listed):
        out.append(
            "%s is on disk but not in %s -- a fixture with no recorded "
            "provenance is one nobody can trust when it disagrees with them"
            % (extra, MANIFEST_NAME)
        )
    for missing in sorted(listed - on_disk):
        out.append("%s is in %s but not on disk" % (missing, MANIFEST_NAME))
    return out


def check_hashes(root: pathlib.Path) -> list[str]:
    man = load_manifest(root)
    out = []
    for e in man["files"]:
        p = root / e["path"]
        if not p.is_file():
            continue  # reported by check_manifest_covers_tree
        actual = sha256_file(p)
        if actual != e["sha256"]:
            out.append(
                "%s changed: manifest %s, on disk %s -- if the change was "
                "deliberate, say what property it preserves and regenerate "
                "with --regen"
                % (e["path"], e["sha256"], actual)
            )
    return out


def check_absent_stays_absent(root: pathlib.Path) -> list[str]:
    if (root / ABSENT_REL).exists():
        return [
            "%s EXISTS. It is the fixture for 'nothing was read', and it only "
            "works by not being there. Every lane's rc=2-on-missing-input test "
            "now passes against a file that is present." % ABSENT_REL
        ]
    return []


def check_empty_stays_empty(root: pathlib.Path) -> list[str]:
    p = root / "vacuous/empty_but_present.rpt"
    if not p.is_file():
        return ["vacuous/empty_but_present.rpt is missing"]
    if p.stat().st_size != 0:
        return [
            "vacuous/empty_but_present.rpt is %d bytes, not 0. It is the "
            "fixture for 'read it, it was empty'; with content it is no longer "
            "distinguishable from any other report." % p.stat().st_size
        ]
    return []


def check_sta_view_is_still_missing(root: pathlib.Path) -> list[str]:
    decl = load_json(root, "sta/known_answer/views.declared.json")
    out = []
    absent = [v for v in decl["declared_views"] if not v["present"]]
    if not absent:
        out.append(
            "every declared STA view is now present. The fixture exists so "
            "NOT_MEASURED has something to be about; with all views shipped it "
            "proves nothing."
        )
    for v in decl["declared_views"]:
        p = root / "sta/known_answer" / v["report"]
        if v["present"] and not p.is_file():
            out.append("declared-present view %s has no report at %s" % (v["view"], v["report"]))
        if not v["present"] and p.is_file():
            out.append(
                "view %s is declared absent but %s exists -- the hole this "
                "fixture is built around has been filled in" % (v["view"], v["report"])
            )
    # the known answer must still be readable off the reports, verbatim
    exp = load_json(root, "sta/known_answer/expected.json")
    for rec in exp["records"]:
        if rec["status"] != "MEASURED":
            continue
        text = (root / "sta/known_answer" / rec["source"]["path"]).read_text(encoding="utf-8")
        if rec["source"]["line_evidence"] not in text:
            out.append(
                "%s no longer contains its evidence line %r, so the known "
                "answer %s is no longer readable off the fixture"
                % (rec["source"]["path"], rec["source"]["line_evidence"], rec["value"])
            )
    if not any(r["status"] == "NOT_MEASURED" for r in exp["records"]):
        out.append("expected.json no longer contains a NOT_MEASURED record")
    for rec in exp["records"]:
        if rec["status"] == "NOT_MEASURED":
            if "value" in rec:
                out.append("the NOT_MEASURED record carries a `value` -- contract §2 forbids it")
            if not rec.get("reason"):
                out.append("the NOT_MEASURED record carries no `reason` -- contract §2 requires one")
    return out


def check_power_pair_differs_only_in_basis(root: pathlib.Path) -> list[str]:
    d = root / "power/activity_basis_pair"
    vl = (d / "vectorless_sdc.rpt").read_text(encoding="utf-8")
    vc = (d / "vector_vcd.rpt").read_text(encoding="utf-8")
    out = []

    # everything a scope must match on is identical...
    for label, pat in (
        ("netlist", r"netlist\s+(\S+\s+sha256:\S+)"),
        ("liberty", r"liberty\s+(\S+)"),
        ("sdc", r"sdc\s+(\S+\s+sha256:\S+)"),
    ):
        a = re.search(pat, vl)
        b = re.search(pat, vc)
        if not a or not b:
            out.append("could not read the %s provenance line out of both reports" % label)
        elif a.group(1) != b.group(1):
            out.append(
                "the pair no longer shares its %s (%r vs %r). It is only a "
                "fixture about activity basis while the basis is the ONLY "
                "difference." % (label, a.group(1), b.group(1))
            )

    # ...and the basis is not.
    mvl = re.search(r"POWER_ANALYSIS_MODE:\s*(\S+)", vl)
    mvc = re.search(r"POWER_ANALYSIS_MODE:\s*(\S+)", vc)
    if not mvl or not mvc:
        out.append("POWER_ANALYSIS_MODE missing from one of the pair")
    elif mvl.group(1) == mvc.group(1):
        out.append("both reports now declare the same activity basis %r" % mvl.group(1))

    # the VCD side must have actually annotated something. A vector_vcd report
    # that annotated 0 pins is a vectorless number wearing a VCD label -- three
    # reports in the published corpus are exactly that, which is why it is
    # checked here rather than assumed.
    ann = re.search(r"Annotated\s+(\d+)\s+pin activities", vc)
    if not ann:
        out.append("the VCD report no longer states how many pin activities it annotated")
    elif int(ann.group(1)) == 0:
        out.append(
            "the VCD report annotated 0 pin activities -- it declares a VCD "
            "basis but carries vectorless numbers, so the pair no longer "
            "differs in basis at all"
        )

    tvl = _num(r"^Total\s+\S+\s+\S+\s+\S+\s+(\S+)", vl) if "Total" in vl else None
    tvc = _num(r"^Total\s+\S+\s+\S+\s+\S+\s+(\S+)", vc) if "Total" in vc else None
    if tvl is None or tvc is None:
        out.append("could not read a Total row from one of the pair")
    elif tvl == tvc:
        out.append(
            "the two Totals are now equal (%g). The fixture's point is that "
            "changing only the activity basis moves the number, so a "
            "cross-basis comparison is meaningless." % tvl
        )
    return out


def check_area_pair_differs_only_in_stage(root: pathlib.Path) -> list[str]:
    exp = load_json(root, "area/stage_pair/expected.json")
    synth = load_json(root, "area/stage_pair/synthesis_stats.json")
    post = load_json(root, "area/stage_pair/post_route_floorplan_pdn.json")
    out = []
    a, b = exp["records"][0], exp["records"][1]
    if a["scope"]["stage"] == b["scope"]["stage"]:
        out.append("the two area records now share a stage; there is nothing left to refuse")
    if a["unit"] == b["unit"]:
        out.append("the two area records now share a unit")
    if a["value"] != synth["chip_area"]:
        out.append(
            "expected.json says the synthesis area is %r but synthesis_stats.json "
            "says %r" % (a["value"], synth["chip_area"])
        )
    if b["value"] != post["die_area_units"]:
        out.append(
            "expected.json says the post-route area is %r but "
            "post_route_floorplan_pdn.json says %r" % (b["value"], post["die_area_units"])
        )
    # the trap itself: the cell counts agreeing is what makes the pair deceptive
    if synth["cell_count"] != post["n_components"]:
        out.append(
            "the cell counts no longer agree (%r vs %r). The pair was chosen "
            "BECAUSE they agree -- that is what makes a naive comparator "
            "believe the two area numbers are the same measurement."
            % (synth["cell_count"], post["n_components"])
        )
    if exp["comparison_expectation"]["verdict"] != "UNDETERMINED":
        out.append("the expected comparison verdict is no longer UNDETERMINED")
    return out


def check_drc_three_ways(root: pathlib.Path) -> list[str]:
    d = "drc/zero_three_ways"
    exp = load_json(root, d + "/expected.json")
    out = []

    clean = sha256_file(root / d / "ran_and_found_none/drc.xml")
    vac = sha256_file(root / d / "ran_on_empty_layout/drc.xml")
    if clean != vac:
        out.append(
            "ran_and_found_none/drc.xml and ran_on_empty_layout/drc.xml are no "
            "longer byte-identical. Their identity IS the finding: it is the "
            "proof that no report-only gate can tell an earned clean from a "
            "vacuous one, and it is why the layout must be measured."
        )

    for case in exp["cases"]:
        rel = "%s/%s" % (d, case["dir"])
        cats, items = count_rdb(root, rel + "/drc.xml")
        if cats != case["categories_in_report"]:
            out.append("%s: %d categories, expected %d" % (case["dir"], cats, case["categories_in_report"]))
        if items != case["items_in_report"]:
            out.append("%s: %d items, expected %d" % (case["dir"], items, case["items_in_report"]))
        shapes = count_shapes(root, rel + "/layout.gds.gz")
        if shapes != case["shapes_in_layout"]:
            out.append(
                "%s: layout has %d shapes, expected %d%s"
                % (
                    case["dir"], shapes, case["shapes_in_layout"],
                    " -- an EMPTY layout that acquired geometry stops being the"
                    " vacuous case" if case["shapes_in_layout"] == 0 else "",
                )
            )
        rc = case["expected_verdict"]["rc"]
        if rc == 0 and not (cats > 0 and items == 0 and shapes > 0):
            out.append("%s expects rc=0 but does not satisfy the earned-clean rule" % case["dir"])
        if rc == 2 and (cats > 0 and items == 0 and shapes > 0):
            out.append("%s expects rc=2 but now satisfies the earned-clean rule" % case["dir"])
        if rc == 1:
            out.append(
                "%s expects rc=1, but none of these three runs looked at the "
                "design; rc=1 is a claim about silicon (contract §1)" % case["dir"]
            )
    return out


def check_waiver_owners(root: pathlib.Path) -> list[str]:
    w = load_json(root, "waiver/no_owner/waivers.json")
    exp = load_json(root, "waiver/no_owner/expected.json")
    by_id = {e["id"]: e for e in w["waived_steps"]}
    out = []
    for case in exp["cases"]:
        entry = by_id.get(case["id"])
        if entry is None:
            out.append("waiver id %r vanished from waivers.json" % case["id"])
            continue
        owned = waiver_has_owner(entry)
        if owned != case["owned"]:
            out.append(
                "waiver id %r: owner check says %s, fixture says %s (approver=%r)%s"
                % (
                    case["id"], owned, case["owned"], entry.get("approver"),
                    " -- an unowned waiver that acquired an owner is a negative"
                    " fixture that has gone positive" if owned else "",
                )
            )
    if not any(not c["owned"] for c in exp["cases"]):
        out.append("no unowned waiver is left in the fixture")
    return out


ALL_CHECKS = (
    ("manifest_covers_tree", check_manifest_covers_tree),
    ("hashes", check_hashes),
    ("absent_stays_absent", check_absent_stays_absent),
    ("empty_stays_empty", check_empty_stays_empty),
    ("sta_view_is_still_missing", check_sta_view_is_still_missing),
    ("power_pair_differs_only_in_basis", check_power_pair_differs_only_in_basis),
    ("area_pair_differs_only_in_stage", check_area_pair_differs_only_in_stage),
    ("drc_three_ways", check_drc_three_ways),
    ("waiver_owners", check_waiver_owners),
)


# --------------------------------------------------------------------------
# pytest surface
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name,fn", ALL_CHECKS, ids=[n for n, _ in ALL_CHECKS])
def test_fixture_property_still_holds(name, fn):
    findings = fn(FIXTURES)
    assert not findings, "%s:\n  - %s" % (name, "\n  - ".join(findings))


def test_the_absent_fixture_is_still_absent():
    """Named on its own so the failure says what it means.

    `vacuous/absent_report.rpt` is a fixture that works by not existing. If a
    future commit creates it, every lane's "rc=2 when the input is missing"
    test starts passing against a file that is present, and nothing else in
    this repository would report that.
    """
    assert not (FIXTURES / ABSENT_REL).exists(), (
        "%s exists; see fixtures/ppa/vacuous/README.md" % ABSENT_REL
    )


def test_every_fixture_has_provenance():
    """A fixture whose origin is unknown is a fixture nobody can trust on the
    day it disagrees with them."""
    man = load_manifest(FIXTURES)
    for e in man["files"]:
        assert e.get("origin"), "%s has no origin" % e["path"]
        assert e.get("carries"), "%s does not say what property it carries" % e["path"]


def test_bad_invocation_is_rc3_not_rc2():
    """A typo in a flag must not look like a tree that could not be read.

    argparse's default for a usage error is 2, and 2 here means UNDETERMINED.
    Somebody has to go and look at an UNDETERMINED; nobody has to go and look
    at a typo, and conflating them wastes the attention the 2 was for.
    """
    with pytest.raises(SystemExit) as e:
        main(["--root", str(FIXTURES), "--no-such-flag"])
    assert e.value.code == 3


def test_cli_on_a_missing_root_is_rc2_not_rc0(tmp_path, capsys):
    """The one that matters most.

    A checker that exits 0 when its input is absent is a gate that can never
    fail, and this repository has shipped that twice. It must also not exit 1:
    1 means a finding about the fixtures, and a root that is not there supports
    no finding at all.
    """
    rc = main(["--root", str(tmp_path / "nope")])
    assert rc == 2
    assert MARKER_CANNOT_CHECK in capsys.readouterr().err


def test_cli_on_a_root_without_a_manifest_is_rc2(tmp_path, capsys):
    """Directory present, manifest absent. Still 'I could not look', not 'clean'."""
    (tmp_path / "ppa").mkdir()
    rc = main(["--root", str(tmp_path / "ppa")])
    assert rc == 2
    assert MARKER_CANNOT_CHECK in capsys.readouterr().err


def test_cli_on_the_real_tree_is_rc0(capsys):
    assert main(["--root", str(FIXTURES)]) == 0


def test_cli_reports_rc1_when_a_property_breaks(tmp_path):
    """The mutation arm, run in a COPY so the real tree is untouched.

    Filling in the deliberately-absent STA view is the exact edit a future
    author would make in good faith, so it is the one worth proving is caught.
    """
    import shutil

    root = tmp_path / "ppa"
    shutil.copytree(FIXTURES, root)
    assert main(["--root", str(root)]) == 0, "the copy must start clean"
    (root / "sta/known_answer/views/setup_tt_025c_5v00.rpt").write_text(
        "worst slack max 9.99\n", encoding="utf-8"
    )
    assert main(["--root", str(root)]) == 1


# --------------------------------------------------------------------------
# CLI — docs/PPA_INTERFACES.md §1
# --------------------------------------------------------------------------
def regen_manifest(root: pathlib.Path) -> int:
    """Rewrite the sha256 of every already-listed file. Provenance is NOT
    invented here: a file with no entry is reported, never auto-added, because
    only a human knows where it came from."""
    man = load_manifest(root)
    listed = {e["path"]: e for e in man["files"]}
    unknown = [
        str(p.relative_to(root)) for p in iter_fixture_files(root)
        if str(p.relative_to(root)) not in listed
    ]
    if unknown:
        print(
            "refusing to regenerate: these files have no provenance entry, and "
            "only you know where they came from:\n  " + "\n  ".join(unknown),
            file=sys.stderr,
        )
        return 3
    for e in man["files"]:
        e["sha256"] = sha256_file(root / e["path"])
    (root / MANIFEST_NAME).write_text(
        json.dumps(man, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("regenerated %d hashes in %s" % (len(man["files"]), MANIFEST_NAME))
    return 0


class _ArgParser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, and 2 in this contract means
    UNDETERMINED -- "I could not look". A misspelled flag is not that; it is a
    BAD INVOCATION, which is rc=3 (contract §1). Left to the default, a typo in
    a CI invocation would be indistinguishable from a fixture tree that could
    not be read, and the second of those is the one somebody must go and fix."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print("%s: error: %s" % (self.prog, message), file=sys.stderr)
        raise SystemExit(3)


def main(argv=None) -> int:
    ap = _ArgParser(
        description="Check that the shared PPA fixtures still carry their properties."
    )
    ap.add_argument("--root", default=str(FIXTURES))
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--regen", action="store_true",
                    help="rewrite the manifest hashes (does not invent provenance)")
    args = ap.parse_args(argv)

    root = pathlib.Path(args.root)

    # rc=2, never 0 and never 1: nothing was read, so nothing can be claimed.
    if not root.is_dir():
        print("%s fixture root does not exist: %s" % (MARKER_CANNOT_CHECK, root), file=sys.stderr)
        return 2
    if not (root / MANIFEST_NAME).is_file():
        print("%s no %s under %s" % (MARKER_CANNOT_CHECK, MANIFEST_NAME, root), file=sys.stderr)
        return 2
    try:
        load_manifest(root)
    except (OSError, ValueError) as exc:
        print("%s %s is unreadable: %s" % (MARKER_CANNOT_CHECK, MANIFEST_NAME, exc), file=sys.stderr)
        return 2

    if args.regen:
        return regen_manifest(root)

    results, findings = {}, []
    for name, fn in ALL_CHECKS:
        try:
            got = fn(root)
        except (OSError, ValueError, KeyError, AssertionError, ImportError) as exc:
            # A check that cannot run has NOT found the fixtures clean.
            print("%s check %r could not run: %s: %s"
                  % (MARKER_CANNOT_CHECK, name, type(exc).__name__, exc), file=sys.stderr)
            return 2
        results[name] = got
        findings.extend("%s: %s" % (name, f) for f in got)

    if args.json_out:
        pathlib.Path(args.json_out).write_text(
            json.dumps(
                {
                    "schema": "vibeic.ppa.fixture_integrity.v1",
                    "root": str(root),
                    "passed": not findings,
                    "checks": results,
                    "findings": findings,
                },
                indent=2, ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )

    if findings:
        print("[REFUSE] %d fixture propert%s no longer hold%s:"
              % (len(findings), "y" if len(findings) == 1 else "ies",
                 "s" if len(findings) == 1 else ""), file=sys.stderr)
        for f in findings:
            print("  - %s" % f, file=sys.stderr)
        return 1

    print("PPA fixtures intact: %d checks, %d files"
          % (len(ALL_CHECKS), len(load_manifest(root)["files"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
