#!/usr/bin/env python3
"""test_spef_full_scan_and_coupling_disclosure.py — the file that
`spef_extraction_check.py` cites as the pin on its own relaxation.

WHY THIS FILE EXISTS
--------------------
`spef_extraction_check`'s module docstring discloses, correctly, that moving
the substance checks from an 8 KB read window to a full-file scan RELAXES one
input: a valid SPEF whose `*SPEF` header sits past byte 8192 was
`ERROR BAD_HEADER` rc 1 before and is rc 0 now. It then offered the safety
guarantee a reviewer would actually lean on --

    "The guard did NOT go blind - a genuinely headerless SPEF still FAILs on
     both trees (pinned by `test_spef_full_scan_and_coupling_disclosure.py`)."

-- and named a file that existed nowhere in the repository. The relaxation may
well have been right; the sentence certifying it was not true. A citation to a
test that does not exist is a check that lies about being checked, and it is
worse than no citation at all, because it stops the reviewer from looking.

MEASURED before this file was written, on pristine origin/main 090fe7128, on a
constructed headerless SPEF (76,019 bytes, 200 `*D_NET`, no `*SPEF` token
anywhere):

    $ python3 programs/spef_extraction_check.py <proj>
      ERROR BAD_HEADER: top.spef missing *SPEF header
      rc=1

So the guarantee is TRUE and the relaxation is safe. This file makes the
citation true as well, and pins the half of the claim that nothing else pinned.

CORPUS FACT, recorded because "the relaxation is harmless" is a measurement and
not an opinion. Over every tracked `.spef` in the repo
(`git ls-files benchmark-data` -> 20 files), `*SPEF` sits at byte 0 and is the
first non-comment statement in 20 of 20. The relaxed input has ZERO instances
in the corpus, so the rc 1 -> 0 move changes no real artefact's verdict; it is
reachable only by the constructed file below.

THE COUPLING-DISCLOSURE HALF
----------------------------
`_spef_coupling.inject_coupling_into_spef` is the one thing in this plugin that
deliberately writes new text INTO a SPEF -- the honesty banner that marks the
lateral-coupling caps as analytical rather than foundry-field-solver. Once the
header predicate is a substring search over the WHOLE file instead of over the
first 8 KB, injected text is no longer structurally unable to reach it. The
banner is safe today for exactly one reason: not one of its lines is read by
`scan_spef` as a SPEF statement, because none of them starts with `*`. Nothing
pinned that. If the banner were ever reformatted to `*`-prefixed lines while
still naming `*SPEF`, a genuinely headerless SPEF would start passing and no
existing test would notice.
`test_the_disclosure_banner_can_never_satisfy_the_header_predicate` is that
pin -- and it asserts the PREDICATE'S OWN OUTPUT over a banner-only file, not
the adjacent, weaker proposition that the banner happens to use `//`. The
weaker form was what an adversarial pass broke: it fired on a legitimate
`/* ... */` reformat that is equally safe, and it never ran the code it was
named after. `test_the_banner_predicate_pin_fires_on_the_dangerous_reformat`
demonstrates the pin failing on the mutation it exists for, so it is not a
guard that cannot fail.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "spef_extraction_check.py"
sys.path.insert(0, str(_PROGRAMS))

import _spef_coupling as sc  # noqa: E402

# A generic IEEE-1481 header. No design name, no PDK SKU, no cell literal:
# this gate is structural and must stay chip-AGNOSTIC.
_HEADER = (
    '*SPEF "ieee 1481-1999"\n'
    '*DESIGN "top"\n'
    '*DATE "sometime"\n'
    '*VERSION "generic"\n'
    "*DIVIDER /\n*DELIMITER :\n*BUS_DELIMITER []\n"
    "*T_UNIT 1 NS\n*C_UNIT 1 PF\n*R_UNIT 1 OHM\n*L_UNIT 1 HENRY\n\n"
)


def _name_map(n: int) -> str:
    """A name map big enough to push what follows past the OLD 8 KB window --
    the shape every tracked SPEF has, reproduced rather than stubbed."""
    return "*NAME_MAP\n" + "".join(
        f"*{39 + i} _a_rather_long_internal_net_name_{i:05d}_\n"
        for i in range(n)) + "\n"


def _d_net(idx: int) -> str:
    """One grounded `*D_NET` record in OpenROAD's emitted shape."""
    return (f"*D_NET *{idx} 0.000445958\n"
            f"*CONN\n"
            f"*I *{idx}:D I *D generic_seq_cell\n"
            f"*I *{idx}:Y O *D generic_comb_cell\n"
            f"*CAP\n"
            f"1 *{idx}:D 2.96094e-05\n"
            f"2 *{idx}:Y 0.000193369\n"
            f"*RES\n1 *{idx}:Y *{idx}:8 41.8334\n"
            f"*END\n\n")


def _body(nets: int = 200, map_entries: int = 1200) -> str:
    return _name_map(map_entries) + "".join(_d_net(39 + i) for i in range(nets))


def _project(tmp: Path, text: str) -> Path:
    ext = tmp / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True, exist_ok=True)
    (ext / "top.spef").write_text(text)
    return tmp


def _run(proj: Path):
    out = proj / "out.json"
    r = subprocess.run([sys.executable, str(_PROG), str(proj),
                        "--json", str(out)],
                       capture_output=True, text=True, timeout=60)
    return r, json.loads(out.read_text())


def _categories(doc):
    return [f["category"] for f in doc["findings"]]


# ===========================================================================
# THE CITED CLAIM ITSELF
# ===========================================================================
def test_a_genuinely_headerless_spef_is_still_an_error(tmp_path):
    """The exact sentence `spef_extraction_check` cites this file for.

    A file with real extraction substance (200 `*D_NET`, 76 KB) but no `*SPEF`
    token ANYWHERE must still be ERROR BAD_HEADER rc 1. If the full-file scan
    had gone blind, this is the input that would silently start passing.
    """
    text = '*DESIGN "top"\n*DATE "x"\n*DIVIDER /\n' + _body()
    assert "*SPEF" not in text, (
        "fixture does not reproduce the case: it still contains a header token")
    assert len(text) > 8192, "fixture must be larger than the old read window"
    r, doc = _run(_project(tmp_path, text))
    assert "BAD_HEADER" in _categories(doc), doc["findings"]
    assert doc["summary"]["pass"] is False
    assert r.returncode == 1, r.stdout


def test_the_headerless_error_survives_real_extraction_substance(tmp_path):
    """Two-sided: the ERROR must not be an artefact of the file looking empty.

    The same headerless file reports its nets honestly -- 200 of them -- and is
    STILL rc 1. A gate that only failed because it saw nothing would be a
    different (and much weaker) gate than the one being certified.
    """
    text = '*DESIGN "top"\n*DATE "x"\n' + _body(nets=200)
    r, doc = _run(_project(tmp_path, text))
    assert doc["summary"]["d_nets"] == 200, doc["summary"]
    assert doc["summary"]["has_nets"] is True
    assert r.returncode == 1


def test_a_valid_late_header_spef_is_clean(tmp_path):
    """The relaxation, EXECUTED rather than asserted in prose.

    A well-formed SPEF behind a comment banner longer than the old 8 KB window
    was rc 1 before the change and must be rc 0 now. This is the one rc 1 -> 0
    move; it has zero instances in the tracked corpus (20/20 have `*SPEF` at
    byte 0) and is reachable only by construction.
    """
    banner = "".join(f"// extraction log line {i:05d}\n" for i in range(400))
    assert len(banner) > 8192, len(banner)
    text = banner + _HEADER + _body(nets=50)
    assert text.index("*SPEF") > 8192, "fixture does not reproduce the case"
    r, doc = _run(_project(tmp_path, text))
    assert "BAD_HEADER" not in _categories(doc), doc["findings"]
    assert r.returncode == 0, r.stdout


# ===========================================================================
# THE COUPLING-DISCLOSURE HALF
# ===========================================================================
def test_the_disclosure_banner_can_never_satisfy_the_header_predicate(tmp_path):
    """RUN THE PREDICATE. Not a proxy for it.

    `scan_spef` decides `has_header` by searching for `*SPEF` on any line that
    starts with `*`, over the WHOLE file. The coupling banner is the only text
    this plugin injects into a SPEF, so it is the only text that could make a
    headerless file look headed.

    An earlier revision of this test asserted the ADJACENT property -- "every
    banner line starts with `//`" -- which is the disease this whole change
    exists to remove, inside the fix meant to cure it. It is neither necessary
    nor sufficient: `//` is not what protects the predicate (`scan_spef` skips
    any line not starting with `*`, so a `/* ... */` block comment is equally
    safe and the proxy failed it anyway), and a comment style says nothing
    about what the predicate returns. So the assertion is now the predicate's
    own output over a file containing nothing but the banner. It goes red on
    the dangerous reformat -- a `*`-prefixed banner line naming `*SPEF` -- and
    stays silent on every safe one.
    """
    import spef_extraction_check as S
    banner = sc.disclosure_banner()
    assert banner.strip(), "the banner is empty -- nothing is being disclosed"
    f = tmp_path / "banner_only.spef"
    f.write_text(banner)
    assert S.scan_spef(f)["has_header"] is False, (
        f"the disclosure banner alone satisfies the header predicate; a "
        f"headerless SPEF would be laundered clean by the pass that exists to "
        f"disclose a limitation. Banner:\n{banner}")
    # ... and the same predicate over a headerless body PLUS the banner, so the
    # claim covers the banner in the position the injector actually puts it.
    g = tmp_path / "body_and_banner.spef"
    g.write_text(banner + '*DESIGN "top"\n*D_NET *1 0.1\n*CAP\n1 *1:D 0.1\n'
                 "*END\n")
    assert S.scan_spef(g)["has_header"] is False, S.scan_spef(g)


def test_the_banner_predicate_pin_fires_on_the_dangerous_reformat(tmp_path):
    """The pin above must be FALSIFIABLE, so exercise the exact mutation it
    guards against on a copy of the banner rather than trusting that it would.

    A `*`-prefixed banner line naming `*SPEF` is the one reformat that would
    fabricate a header. `scan_spef` reads it as a statement, finds the token,
    and a genuinely headerless file passes.
    """
    import spef_extraction_check as S
    dangerous = ("*COMMENT COUPLING-AWARE AUGMENTATION of this *SPEF "
                 "(analytical)\n")
    f = tmp_path / "dangerous.spef"
    f.write_text(dangerous)
    assert S.scan_spef(f)["has_header"] is True, (
        "the mutation this test exists to demonstrate no longer fabricates a "
        "header, so the pin above proves nothing")


def test_a_headerless_spef_carrying_the_disclosure_banner_still_fails(tmp_path):
    """The same property, executed end to end through the real injector.

    Coupling augmentation runs on a SPEF and writes the banner into it. If that
    augmentation could supply the header, a headerless extraction would be
    laundered into a clean rc by the very pass that exists to disclose a
    limitation.
    """
    headerless = ('*DESIGN "top"\n*VERSION "generic"\n'
                  "*NAME_MAP\n*1 net_a\n*2 net_b\n\n"
                  "*D_NET *1 0.0002\n*CONN\n*I *10:D I *D generic_seq_cell\n"
                  "*CAP\n1 *10:D 0.0001\n*RES\n*END\n\n"
                  "*D_NET *2 0.0003\n*CONN\n*I *12:D I *D generic_seq_cell\n"
                  "*CAP\n1 *12:D 0.0003\n*RES\n*END\n\n")
    assert "*SPEF" not in headerless
    augmented, n = sc.inject_coupling_into_spef(
        headerless, {("net_a", "net_b"): 0.0005}, eps_r=4.0)
    assert n == 1, "fixture did not actually exercise the injector"
    assert "NOT foundry-calibrated" in augmented, "banner was not injected"
    assert "*SPEF" not in augmented, (
        "the coupling pass introduced a *SPEF token into a headerless file")
    # pad past 1 KB so TOO_SMALL is not what produces the rc
    padded = augmented + "".join(f"// pad {i:05d}\n" for i in range(60))
    r, doc = _run(_project(tmp_path, padded))
    assert "BAD_HEADER" in _categories(doc), doc["findings"]
    assert r.returncode == 1


def test_a_coupling_augmented_spef_still_passes(tmp_path):
    """The legitimate state, which must NOT be made to fail.

    A properly headed SPEF that has been through coupling augmentation is a
    normal, expected artefact. It passes, and its net count is unchanged by the
    banner -- disclosure text is not extraction substance and must not be
    counted as either nets or a header.
    """
    base = _HEADER + "*NAME_MAP\n*1 net_a\n*2 net_b\n\n" + \
        ("*D_NET *1 0.0002\n*CONN\n*I *10:D I *D generic_seq_cell\n"
         "*CAP\n1 *10:D 0.0001\n*RES\n*END\n\n"
         "*D_NET *2 0.0003\n*CONN\n*I *12:D I *D generic_seq_cell\n"
         "*CAP\n1 *12:D 0.0003\n*RES\n*END\n\n")
    augmented, n = sc.inject_coupling_into_spef(
        base, {("net_a", "net_b"): 0.0005}, eps_r=4.0)
    assert n == 1
    padded = augmented + "".join(f"// pad {i:05d}\n" for i in range(60))
    r, doc = _run(_project(tmp_path, padded))
    assert r.returncode == 0, r.stdout
    assert doc["summary"]["d_nets"] == 2, (
        f"the disclosure banner changed the net count: {doc['summary']}")


# ===========================================================================
# THE CITATION, AT ITS OWN SITE
# ===========================================================================
def test_spef_extraction_check_cites_this_file_and_it_exists():
    """The defect this file was written for, pinned where it happened.

    `spef_extraction_check`'s docstring names a test file as the pin on its
    relaxation. Every test filename it names must be a file that exists, and
    this module must be among them -- otherwise the guarantee is again a
    sentence nobody can check.
    """
    doc = _PROG.read_text(errors="replace").split('"""')[1]
    cited = re.findall(r"test_[A-Za-z0-9_]+\.py", doc)
    assert cited, (
        "spef_extraction_check's docstring no longer cites any test as the pin "
        "on its documented relaxation -- the relaxation is now unbacked")
    tests_dir = Path(__file__).resolve().parent
    for name in cited:
        assert (tests_dir / name).is_file(), (
            f"spef_extraction_check cites {name}, which does not exist. A "
            f"citation to a missing test is a check that lies about being "
            f"checked.")
    assert Path(__file__).name in cited, (
        f"this module is named as the pin but is no longer cited; cited: "
        f"{sorted(set(cited))}")
