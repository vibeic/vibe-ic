#!/usr/bin/env python3
"""size_policy_drift_check.py — one policy about layout artefacts, stated once.

THIS GATE BLOCKS (rc=1) when the mechanisms that decide whether a layout
artefact ships stop agreeing with each other.

WHY IT EXISTS (#419)
--------------------
Five mechanisms held an opinion about `*.gds` / `*.def` / `*.spef` / `*.oas`,
each locally reasonable, and no two of them agreed:

  1. `.gitignore` ignored `*.gds`/`*.def` at the root and NEGATED them back
     for `benchmark-data/ic/**`; `*.spef`/`*.oas` were never ignored at all.
     So git accepted all four.
  2. The comment beside that negation said files over 50 MB would be stopped
     by "benchmark_evidence_structure_check 的 size-guard". No such guard
     existed — the sentence was the whole implementation.
  3. `benchmark_evidence_publish` dropped all four by EXTENSION, so a cell
     published by the program carried less evidence than the hand-staged
     cells it replaced.
  4. That program's docstring justified the drop as "gitignored / too large",
     which by then was false on both counts.
  5. `benchmark_evidence_structure_check`'s NO_RAW_GEOMETRY FAILED any cell
     carrying one — and therefore failed ALL THREE reference cells, the most
     complete evidence this repository publishes.

Nobody introduced a contradiction on purpose. Each mechanism was edited alone
and stayed true to what its author knew. What was missing was anything that
could notice the set had stopped being consistent.

WHAT IT CHECKS
--------------
  * the three modules that name a size ceiling agree on the number;
  * `.gitignore` still permits layout artefacts under `benchmark-data/ic/**`,
     since every other mechanism is now built on that being true;
  * neither module has reverted to an extension-only drop — established by
    CALLING each decider on a file either side of the ceiling, not by
    grepping for the constant;
  * the docstrings do not still assert the superseded policy.

It reads the SOURCE, not the imported constants, for the docstring half —
a comment can go stale while the code stays right, and a stale comment is
what made this take five mechanisms to unpick.

WHY THERE IS A BEHAVIOURAL PROBE AS WELL AS A GREP
--------------------------------------------------
The first version of this gate checked that each module DECLARED a ceiling
and did not contain a stale phrase. Measured against a deliberate mutant —
`_excluded` reverted to `suffix in _LAYOUT_EXTS`, the exact rule #419 existed
to remove, with `_SIZE_CEILING = 50 * 1000 * 1000` left untouched beside it —
that gate returned PASS with zero findings. A declared constant is not a
followed one. So the ceiling owners now expose named predicates and this gate
CALLS them with a file just under and just over the ceiling: the decision has
to flip at the ceiling and nowhere else. A grep for prose rots the same way
the prose does; a call cannot, because it fails the moment the behaviour
stops matching.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

_CEILING_OWNERS = {
    "tracked_blob_size_guard.py": r"^_CEILING\s*=\s*(.+)$",
    "benchmark_evidence_publish.py": r"^_SIZE_CEILING\s*=\s*(.+)$",
    "benchmark_evidence_structure_check.py": r"^_SIZE_CEILING\s*=\s*(.+)$",
}

# Phrases that asserted the superseded policy. Any of them reappearing means
# a docstring has drifted back behind the code.
_STALE_CLAIMS = (
    "EXCLUDED BY CONSTRUCTION",
    "must never be committed",
    "must be gitignored; keep only",
)


# The deciders whose BEHAVIOUR must follow the ceiling they declare, as
# (module stem, attribute name). Each is called on a real file either side of
# the ceiling; a module that answers "excluded" for a 1 KB .gds has reverted to
# an extension rule no matter what constant it still spells.
#
# PROBE THE DECISION, NOT A LEAF HELPER. The first version of this gate called
# `benchmark_evidence_structure_check.over_ceiling` — a three-line pure size
# test that no plausible regression touches. The place that module actually
# decides whether a cell may ship is `check_folder`, which is where the
# extension-only rule lived before #419. Reverting `check_folder` to that rule
# while leaving `over_ceiling` defined beside it passed this gate with zero
# findings, and failed all three real reference cells with a self-contradicting
# message ("phase3/stage4/gds/spm.gds (1 MB)" reported as over a 50 MB
# ceiling). A helper that the decision merely happens to call is not the
# decision; probing it is the same rubber stamp as grepping for the constant.
_DECIDERS = (
    ("benchmark_evidence_publish", "_excluded"),
    ("benchmark_evidence_structure_check", "check_folder"),
)


def _decision_fn(stem: str, attr, mod):
    """Adapt a decider's public entry point to `Path -> bool` ("would refuse").

    The two owners decide at different granularities and neither should be
    reshaped to suit the probe:
      * the publisher decides per FILE   -> `_excluded(p)` is already the shape
      * the structure check decides per CELL -> `check_folder(dir)`, whose
        NO_RAW_GEOMETRY entry in `.checks` is the verdict on layout size.
    Outside a git repo `check_folder` falls back to a filesystem walk, so a
    throwaway directory holding one sparse file is a faithful probe of the
    real code path — no repo, no fixture cell, no network.
    """
    if stem == "benchmark_evidence_structure_check":
        def decide(p: Path) -> bool:
            res = attr(p.parent)
            return res.checks.get("NO_RAW_GEOMETRY") is False
        return decide
    return lambda p: bool(attr(p))


def _load(programs: Path, stem: str):
    """Import `stem` from `programs` in isolation, without permanently
    polluting sys.modules — the check may be pointed at a mutant copy.

    The module MUST be registered in sys.modules before exec_module: a
    `@dataclass` defined in a module absent from sys.modules raises
    `AttributeError: 'NoneType' object has no attribute '__dict__'` on 3.10,
    because dataclasses resolves `cls.__module__` through that table. Without
    this the probe reported the structure check UNIMPORTABLE against a
    perfectly good tree — a gate failing on its own plumbing, which is the
    failure mode that teaches people to ignore it.
    """
    import importlib.util
    path = programs / f"{stem}.py"
    if not path.is_file():
        return None
    key = f"_spdc_{stem}"
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    prev = sys.modules.get(key)
    sys.modules[key] = mod
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None
    finally:
        if prev is not None:
            sys.modules[key] = prev
        else:
            sys.modules.pop(key, None)


def _probe_behaviour(programs: Path, ceiling: int, findings: list) -> None:
    """Call each decider on a file just under and just over `ceiling`.

    Sparse files: `truncate` gives st_size without consuming the disk, so a
    60 MB probe costs nothing.
    """
    import tempfile
    for stem, fname in _DECIDERS:
        mod = _load(programs, stem)
        if mod is None:
            findings.append(f"UNIMPORTABLE: {stem} could not be loaded, so its "
                            f"decision cannot be verified — only its spelling")
            continue
        attr = getattr(mod, fname, None)
        if attr is None:
            findings.append(
                f"NO_PREDICATE: {stem}.{fname} is gone. The ceiling can no "
                f"longer be verified by CALLING it, which is the only form "
                f"of this check that a stale comment cannot survive")
            continue
        fn = _decision_fn(stem, attr, mod)
        # One file per directory: the cell-granularity decider judges a whole
        # directory, so a shared temp dir would put both probes in front of it
        # at once and the over-ceiling one would mask the under-ceiling one.
        try:
            with tempfile.TemporaryDirectory() as td_s, \
                    tempfile.TemporaryDirectory() as td_b:
                small = Path(td_s) / "probe_small.gds"
                big = Path(td_b) / "probe_big.gds"
                with small.open("wb") as fh:
                    fh.truncate(1024)
                with big.open("wb") as fh:
                    fh.truncate(ceiling + 1024)
                small_excluded = bool(fn(small))
                big_excluded = bool(fn(big))
        except Exception as exc:
            findings.append(f"PREDICATE_RAISED: {stem}.{fname}: {exc}")
            continue
        if small_excluded:
            findings.append(
                f"EXTENSION_RULE_RETURNED: {stem}.{fname} rejects a 1 KB "
                f".gds. That is the extension-only rule #419 removed — it "
                f"threw away the artefact a reviewer can open in order to "
                f"avoid the one nobody can commit. The declared ceiling "
                f"is not being applied.")
        if not big_excluded:
            findings.append(
                f"CEILING_NOT_ENFORCED: {stem}.{fname} accepts a file "
                f"over the {ceiling / 1e6:.0f} MB ceiling. Committing it "
                f"is what the ceiling exists to prevent.")


def _repo_root(start: Path) -> Path:
    r = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() \
        else start


def audit(programs: Path, gitignore: Path) -> dict:
    findings, ceilings = [], {}

    for name, pat in _CEILING_OWNERS.items():
        p = programs / name
        if not p.is_file():
            findings.append(f"MISSING: {name} — a ceiling owner is gone; the "
                            f"policy cannot be consistent with a missing half")
            continue
        src = p.read_text(errors="replace")
        m = re.search(pat, src, re.MULTILINE)
        if not m:
            findings.append(
                f"NO_CEILING: {name} no longer declares a size ceiling — an "
                f"extension-only rule is what #419 replaced")
            continue
        try:
            ceilings[name] = int(eval(m.group(1).split("#")[0].strip(),  # noqa: S307
                                      {"__builtins__": {}}, {}))
        except Exception:
            findings.append(f"UNPARSEABLE: {name} ceiling {m.group(1)!r}")
        for claim in _STALE_CLAIMS:
            if claim in src:
                findings.append(
                    f"STALE_CLAIM: {name} still says {claim!r} — the code "
                    f"routes by size; the prose says it refuses by kind")

    if len(set(ceilings.values())) > 1:
        findings.append(
            "CEILING_DISAGREEMENT: " + ", ".join(
                f"{k}={v}" for k, v in sorted(ceilings.items())))

    # The half a grep cannot do: make the deciders actually decide.
    if ceilings:
        _probe_behaviour(programs, min(ceilings.values()), findings)

    gi = gitignore.read_text(errors="replace") if gitignore.is_file() else ""
    for ext in ("gds", "def"):
        if not re.search(rf"^!benchmark-data/ic/\*\*/\*\.{ext}\s*$",
                         gi, re.MULTILINE):
            findings.append(
                f"GITIGNORE_REVERTED: the negation for *.{ext} under "
                f"benchmark-data/ic/** is gone. Every other mechanism now "
                f"assumes git accepts these; without it the publisher stages "
                f"files that can never be committed.")

    return {"program": "size_policy_drift_check", "ceilings": ceilings,
            "findings": findings,
            "verdict": "FAIL" if findings else "PASS"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--programs", default=str(_HERE))
    ap.add_argument("--gitignore", default=None)
    a = ap.parse_args(argv)
    programs = Path(a.programs).resolve()
    gi = Path(a.gitignore) if a.gitignore \
        else _repo_root(programs) / ".gitignore"

    rep = audit(programs, gi)
    if rep["findings"]:
        print(f"[FAIL] size_policy_drift_check: {len(rep['findings'])} "
              f"disagreement(s) about which layout artefacts ship:")
        for f in rep["findings"]:
            print(f"   {f}")
        return 1
    v = next(iter(rep["ceilings"].values()), 0)
    # Name the entry points that were called and the extensions that were
    # checked. A PASS sentence claiming more ground than the run covered is
    # the same failure this gate exists to catch, one level up.
    probed = ", ".join(f"{s}.{f}" for s, f in _DECIDERS)
    print(f"[PASS] size_policy_drift_check: {len(rep['ceilings'])} module(s) "
          f"agree on a {v / 1e6:.0f} MB ceiling; the decision entry point of "
          f"each ceiling-owner ({probed}) was CALLED either side of it and "
          f"flipped there; the ROOT .gitignore negates *.gds and *.def under "
          f"benchmark-data/ic/**.")
    print(f"       NOT covered by this gate: *.spef / *.oas (no root rule "
          f"either way), and per-cell .gitignore files nested under "
          f"benchmark-data/ic/** — several published cells carry one that "
          f"ignores layout artefacts locally. This gate reads the root file "
          f"only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
