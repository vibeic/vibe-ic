#!/usr/bin/env python3
"""waveform_artifact_hygiene_check.py — no sim waveform dumps in the bundle.

A raw simulation waveform dump (VCD/FST/GHW/SHM) is never a program: it
inflates the shipped package and actively pollutes repo-wide audits —
VCD identifier/timestamp tokens spuriously match issue-tag greps (e.g.
searching programs/ for an issue number hits the dump).  Simulation
byproducts belong in tmp/work dirs, never inside the plugin tree.

This checker walks a tree (filesystem level, so UNTRACKED strays count
too — that is exactly how the defect escaped git-based gates) and fails
when any waveform artifact exists.

CLASSIFICATION IS BY CONTENT, NOT BY NAME (#805)
------------------------------------------------
Until v1.9.78 the whole test was `p.suffix.lower() in WAVEFORM_SUFFIXES`.
The file never opened a candidate, so a waveform was whatever was NAMED like
one. That is not merely imprecise — it is wrong on an artefact this project
produces today. Measured on this machine, and inside the shipped EDA image:

    iverilog built WITHOUT zlib, $dumpfile("t.fst"); $dumpvars;
      vvp a.vvp        -> rc 0, writes a 331-byte ASCII **VCD** named t.fst
      vvp a.vvp -fst   -> rc 1 "FST support disabled since zlib not available"

The FST writer degrades to VCD while KEEPING the requested filename, so the
name and the content disagree and every suffix-based check calls it an FST.
`fst2vcd` rejects the same file. The checker must therefore read bytes.

THREE STATES, NOT TWO
---------------------
    WAVEFORM      the leading bytes match a waveform format -> a FINDING,
                  whatever the file is called. A disagreement between the
                  name and the content is reported ON the finding, because
                  "named .fst, contains VCD" is the sentence that would have
                  caught the image bug from the plugin side.
    NOT_WAVEFORM  the file was read and matches no waveform format. Silent.
    UNDETERMINED  the file could NOT be read, or it CLAIMS a waveform format
                  by name and its content confirms nothing. This is its own
                  verdict (rc 3) and never collapses into the passing one: a
                  file that cannot be read is not a file that is clean, and a
                  zero-byte `wave.vcd` is a failed dump, not an absent one.

DETECTION SCOPE IS ONLY WHAT CAN BE DETECTED
--------------------------------------------
`.vcd`, `.fst` and `.ghw` have file magic and are identified by it. `.shm`
(Cadence SimVision) has none to read — the real artefact is a DIRECTORY whose
members are `.trn`/`.dsd`, so a *file* named `.shm` is a claim with nothing
behind it. It stays in `WAVEFORM_SUFFIXES`, but it resolves to UNDETERMINED,
never to a confirmed hit and never to a pass. No coverage is claimed that this
program cannot demonstrate.

Exit: 0 = PASS (tree clean), 1 = FAIL (confirmed waveform artifacts listed),
      2 = VACUOUS (nothing was walked), 3 = UNDETERMINED (something in the
      tree could not be classified — not clean, not a confirmed finding).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

WAVEFORM_SUFFIXES = (".vcd", ".fst", ".ghw", ".shm")
# The subset of the above this program can confirm or refute FROM CONTENT.
# `.shm` is deliberately absent — see the module docstring.
CONTENT_DETECTABLE_SUFFIXES = (".vcd", ".fst", ".ghw")
# Directories that are never part of the shipped bundle.
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules"}

# How much of a file the classifier reads. The largest signature below ends at
# byte 19, so 512 is generous; it is bounded so that walking a tree costs the
# same whether a candidate is 300 bytes or 3 GB.
HEAD_BYTES = 512

# --- content signatures ----------------------------------------------------
# FST, from the writer itself (`fstWriterEmitHdrBytes`, gtkwave `fstapi.c`;
# the block-type enum is `fstapi.h`): the file opens with a header block whose
# tag is FST_BL_HDR (0) and whose section length is the constant 329.
_FST_BL_HDR = 0x00
_FST_HDR_SECLEN = (329).to_bytes(8, "big")
# `fstWriterSetRepackOnClose` rewrites the finished trace as ONE gzip stream
# behind a FST_BL_ZWRAPPER (254) tag: +0 tag, +1 uint64 section length,
# +9 uint64 uncompressed length, +17 the gzip stream. The reader treats a ZERO
# section length as "not finished compressing, this is a failed read", so the
# same nonzero test is applied here rather than accepting a truncated write.
_FST_BL_ZWRAPPER = 0xFE
_GZIP_MAGIC = b"\x1f\x8b"
# GHW, from ghdl's own reader (`libghw.c`): a 9-byte magic then version 16,0.
_GHW_MAGIC = b"GHDLwave\n"
# VCD is text and has no magic; what it has is a grammar. The value-change
# section is preceded by declaration commands, and a dump therefore opens with
# one of these (leading whitespace allowed). Requiring the token to sit at the
# START and to be followed by whitespace keeps arbitrary prose that merely
# mentions `$var` out of the hit list.
_VCD_OPENERS = (
    b"$date", b"$version", b"$timescale", b"$comment", b"$scope", b"$var",
    b"$upscope", b"$enddefinitions", b"$dumpvars", b"$dumpall",
)

# Which suffix each detectable format is normally written under, so a
# disagreement can be named rather than merely counted.
_CANONICAL_SUFFIX = {"vcd": ".vcd", "fst": ".fst", "ghw": ".ghw"}

WAVEFORM = "WAVEFORM"
NOT_WAVEFORM = "NOT_WAVEFORM"
UNDETERMINED = "UNDETERMINED"


class Finding(NamedTuple):
    """One non-clean file. `state` is WAVEFORM or UNDETERMINED — NOT_WAVEFORM
    produces no Finding, which is the whole point of reading the bytes."""

    path: str
    state: str
    fmt: str      # "vcd"/"fst"/"ghw" for WAVEFORM; "" when undetermined
    detail: str

    def __str__(self) -> str:  # what main() prints, and what a test can read
        if self.state == WAVEFORM:
            return f"waveform artifact in shipped tree: {self.path} — {self.detail}"
        return f"UNCLASSIFIED file in shipped tree: {self.path} — {self.detail}"


def sniff_format(head: bytes) -> Optional[str]:
    """The format the LEADING BYTES say this is: 'vcd' / 'fst' / 'ghw', or
    None for "these bytes are not the start of a waveform I can identify".

    None is not "this is safe" — the caller decides what an unidentified
    candidate means. Kept separate from any filesystem access so a test can
    drive it with bytes and so the name can never reach it.
    """
    if len(head) >= 9 and head[0] == _FST_BL_HDR and head[1:9] == _FST_HDR_SECLEN:
        return "fst"
    if (len(head) >= 19 and head[0] == _FST_BL_ZWRAPPER
            and head[17:19] == _GZIP_MAGIC and head[1:9] != b"\x00" * 8):
        return "fst"
    if head.startswith(_GHW_MAGIC):
        return "ghw"
    # VCD last: it is the only text format here, so a NUL in the head rules it
    # out and stops a binary file from being read as one.
    if b"\x00" not in head:
        stripped = head.lstrip()
        for opener in _VCD_OPENERS:
            if stripped.startswith(opener):
                rest = stripped[len(opener):]
                if not rest or rest[:1].isspace():
                    return "vcd"
    return None


def classify(path: Path) -> Tuple[str, str, str]:
    """(state, fmt, detail) for ONE file. Reads it; never guesses from the name.

    The suffix is used for exactly two things, both of them after the read:
    deciding whether an unidentifiable file is a claim that failed to hold up,
    and naming the disagreement when the content contradicts the name.
    """
    suffix = path.suffix.lower()
    claims_waveform = suffix in WAVEFORM_SUFFIXES
    try:
        with open(path, "rb") as fh:
            head = fh.read(HEAD_BYTES)
    except OSError as exc:
        return (UNDETERMINED, "",
                f"could not be read ({type(exc).__name__}: "
                f"{exc.strerror or exc}) — an unreadable file is not a clean "
                f"one; nothing here says it is not a waveform dump")
    fmt = sniff_format(head)
    if fmt:
        canonical = _CANONICAL_SUFFIX[fmt]
        if suffix == canonical:
            return (WAVEFORM, fmt, f"content is {fmt.upper()}")
        named = suffix or "(no suffix)"
        return (WAVEFORM, fmt,
                f"NAME/CONTENT DISAGREE: named {named}, content is "
                f"{fmt.upper()}. A waveform writer that degrades to another "
                f"format while keeping the requested filename produces exactly "
                f"this, and a name-based check calls it clean")
    if not claims_waveform:
        return (NOT_WAVEFORM, "", "")
    if suffix not in CONTENT_DETECTABLE_SUFFIXES:
        return (UNDETERMINED, "",
                f"named {suffix}, for which this checker has NO content "
                f"detector (the real artefact is a directory of members, so "
                f"there is no magic to read) — the name is the only evidence "
                f"and a name is what #805 is about")
    if not head:
        return (UNDETERMINED, "",
                f"named {suffix} and EMPTY (0 bytes) — an empty dump is a "
                f"failed one, not an absent one")
    return (UNDETERMINED, "",
            f"named {suffix} but its first {len(head)} byte(s) match no "
            f"waveform format this checker can identify — the name claims a "
            f"waveform and the content does not confirm it")


def audit(root: str) -> Tuple[List[Finding], int]:
    """Non-clean files under root, WITH the number of files examined.

    The count is returned rather than left for the caller to re-derive, because
    `PASS - 0 waveform artifact(s)` was printed identically for a clean tree and
    for a path that does not exist. This gate looks for something that should be
    ABSENT, so zero is the expected answer — which is exactly why "I walked
    3000 files and found none" and "I walked nothing" must not read the same
    (#564).

    #805: the first element used to be a list of paths that matched a suffix.
    It is now a list of `Finding`s carrying the state the CONTENT supports, so
    a caller that asserts `findings == []` is asserting the tree is clean —
    not merely that nothing was named like a waveform.
    """
    root_p = Path(root)
    findings: List[Finding] = []
    examined = 0
    for p in sorted(root_p.rglob("*")):
        if not p.is_file():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        examined += 1
        state, fmt, detail = classify(p)
        if state != NOT_WAVEFORM:
            findings.append(Finding(str(p), state, fmt, detail))
    return findings, examined


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root", nargs="?", default=".",
                   help="tree to scan (default: cwd)")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    findings, examined = audit(args.root)
    for f in findings:
        print(str(f))
    if not findings and examined == 0:
        # Not clean — nothing was walked. Measured over 40 corpus projects
        # before landing: 38 answer 0 artefacts over a real tree and 2 answer 1
        # (a genuine finding), so no real project reaches this branch.
        print(f"VACUOUS_PASS: waveform_artifact_hygiene_check examined nothing "
              f"(reason: no files under {args.root!r}) — an absent tree has no "
              f"waveform artefacts for the same reason it has nothing else",
              file=sys.stderr)
        return 2
    waveforms = [f for f in findings if f.state == WAVEFORM]
    unclassified = [f for f in findings if f.state == UNDETERMINED]
    # The denominator goes on its OWN line, BEFORE the verdict, and the verdict
    # line stays free of it.
    #
    # `gate_host_independence_check` compares the LAST non-empty line between a
    # working checkout and a fresh worktree, and it is right to treat a differing
    # count as a real difference. But this gate walks the whole repo root, so its
    # count legitimately differs — measured 3753 vs 3693, the 60 being run
    # leftovers under benchmark-data/. Both sides said PASS with rc 0; only the
    # number moved.
    #
    # Putting the count on the verdict line made an honest disclosure into a
    # host-dependent verdict. Disclosure and verdict are different jobs, and the
    # consumers differ too: a human reads the count, the aggregator reads the
    # last line.
    print(f"examined {examined} file(s) under {args.root!r}")
    if waveforms:
        print(f"FAIL — {len(waveforms)} waveform artifact(s)")
        return 1
    if unclassified:
        # NOT a PASS and NOT a confirmed finding. Its own exit code, so a
        # caller can tell "the tree is clean" from "I could not tell" — the
        # distinction the suffix test never had to make because it never
        # looked.
        print(f"UNDETERMINED — {len(unclassified)} file(s) could not be "
              f"classified")
        return 3
    print("PASS — 0 waveform artifact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
