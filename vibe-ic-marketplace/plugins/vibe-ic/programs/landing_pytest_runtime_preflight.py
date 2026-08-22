#!/usr/bin/env python3
"""landing_pytest_runtime_preflight.py — can this host RUN the protected
landing test runtime at all?  Asked ONCE, before the arms, attributably.

THIS GATE REFUSES (rc=2).  It is not a test verdict and never becomes one.

THE DEFECT IT EXISTS FOR (v1.10.69)
===================================
`tools/gatekeeper-land.sh` runs its three test arms through
`trusted_pytest_entry.py` under `python3 -I`.  Isolated mode implies `-s`, so
the USER site directory is suppressed.  On a host whose test runner is
installed there — which is what `CONTRIBUTING`'s `pip install pytest` produces,
and what all seven hosts of this fleet actually have — the entry's `import
pytest` raises, the entry refuses, and the child dies before emitting one
lifecycle event.

MEASURED on the landing host at 7c376e348, the repo-tools arm alone::

    asked 40  recorded 0  NORECORD 40  aggregate INCOMPLETE rc=2 cases=0

Across all three arms that is every selected file in every arm reported as
UNKNOWN and not one junit test case in existence.

THE POINT IS NOT THAT THE RUNTIME IS UNAVAILABLE — that part is the protected
runtime working as designed, and it must keep refusing an unattested toolchain.
The defect is that the refusal arrived as a per-file UNKNOWN, hundreds of times,
attributed to hundreds of innocent files, leaving the reader to infer a cause
that no line ever named.  The commit that introduced it ALREADY KNEW: its own
`tools/ci/test_repo_tools_tests_gate.py` skips three tests with this exact
diagnosis.  That knowledge was applied to the commit's CI tests and not to the
landing gate, which `gatekeeper-land.sh:47-52` still documents as a supported
host shape.

A gate that cannot look must say so ONCE, in one attributable line, naming the
cause and the remedy.  It must not say "UNKNOWN" for every file it was asked
about.  That is the whole of this program.

WHY IT PROBES THE WHOLE CHAIN AND NOT JUST THE IMPORT
=====================================================
`python3 -I -c "import pytest"` answers one question of four.  The child the
arms really spawn also has to: resolve `_pytest` and `pluggy` outside the
subject checkout, raw-attest all of them, load the protected progress plugin by
exact path, and emit a complete lifecycle protocol.  Any of those failing
produces the SAME NORECORD-everywhere shape as a missing import, so any of them
deserves the same one-line refusal instead of hundreds of UNKNOWNs.

So the probe EXECUTES the real entry, with the real argv shape, on a synthetic
one-test file, and requires a recorded pass.  It costs milliseconds against a
gate that costs an hour and a half, and it is the only form of the check that
cannot be satisfied by a runtime that imports and then cannot report.

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` IS ASSERTED, NOT ASSUMED
===========================================================
The three arms all set it, and `gatekeeper-land.sh:520-528` records why: of the
entry points installed on this host exactly one — `web3`'s `pytest_ethereum` —
raises at import and takes the session down AT COLLECTION, so not one test runs.
Restoring the user site directory (the host lane below) restores those entry
points too, which makes the token load-bearing exactly where it was previously
merely tidy.  The probe therefore sets it, and the entry itself REFUSES a host
lane without it, so a lane can never be opened into a session that autoloads.

chip-AGNOSTIC: interpreter/toolchain shape only; no design, PDK or vendor name.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


#: The environment variable that opts a host OUT of the digest-pinned image and
#: INTO its own site directory.  Read by `trusted_pytest_entry.py`, which owns
#: the resolution and the refusals; named here so the remedy text and the entry
#: cannot drift apart.
HOST_LANE_ENV = "VIBEIC_TRUSTED_PYTEST_SITE"

#: The value that asks the entry to DERIVE the directory from the non-isolated
#: interpreter's user site directory instead of stating it.
HOST_LANE_AUTO = "auto"

#: The pinned runner image, spelled the way `trusted_pytest_entry`'s own tests
#: and `tools/ci/protected_landing_transition.json` spell it.  A remedy that
#: names a floating tag is not a remedy: a floating tag is how a host ends up
#: with a runtime nobody pinned.
RUNNER_IMAGE = ("ghcr.io/vibeic/vibeic-eda@sha256:"
                "66c33ff2e05781758f596d82bff61ad8a404ef0a7eae3d21ab8a9d55df0d01ff")

#: The parent's semantic progress stream, which this probe must NOT join.
#:
#: `pytest_per_file_junit` hands its child a stream path and a nonce and then
#: validates every event against that nonce AND the child's pid. A nested
#: trusted-entry invocation inherits both, writes the parent's nonce from a
#: different pid, and the parent's own session is failed with
#: `schema/nonce/pid mismatch` — MEASURED: the repo-tools arm reported this
#: file's own gate test NORECORD for exactly that reason. The prefix is matched
#: rather than the two names listed so a renamed suffix cannot reopen it.
PROGRESS_ENV_PREFIX = "VIBEIC_PYTEST_PROGRESS"

#: The synthetic subject.  ONE test, no imports, no fixtures — the probe is
#: about the runtime, and a subject that can fail for its own reasons would make
#: a runtime verdict out of a subject bug.
_PROBE_TEST = "def test_landing_runtime_is_executable():\n    assert True\n"
_PROBE_NAME = "test_landing_runtime_probe.py"


def _run(argv: List[str], *, cwd: Optional[Path] = None,
         env: Optional[Dict[str, str]] = None,
         ) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=None if cwd is None else str(cwd), env=env,
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=300, check=False)


def isolated_import_lane(python: str) -> Tuple[bool, str]:
    """Does the ISOLATED interpreter resolve the test runner by itself?

    True means the image lane: the runner is in a system directory that `-I`
    keeps.  The resolved file is returned either way, because "it is installed,
    just not where `-I` looks" is the whole diagnosis and a reader should not
    have to run a second command to get it.
    """
    probe = _run([python, "-I", "-c",
                  "import pytest, sys; sys.stdout.write(pytest.__file__)"])
    if probe.returncode == 0:
        return True, probe.stdout.strip()
    fallback = _run([python, "-c",
                     "import pytest, sys; sys.stdout.write(pytest.__file__)"])
    if fallback.returncode == 0:
        return False, fallback.stdout.strip()
    return False, ""


def entry_probe(python: str, entry: Path) -> subprocess.CompletedProcess:
    """Execute the real trusted entry on a synthetic one-test subject.

    `entry` is made ABSOLUTE first. The child runs with `cwd` set to the
    synthetic subject directory, so a relative path that resolved for the caller
    does not resolve for the child — and the failure arrives as
    "the trusted entry could not execute and report one synthetic test", a cause
    this program did not have. MEASURED on 8HD-d at 46db018669, the same tree
    both ways::

        --programs vibe-ic-marketplace/.../programs   probe_returncode 2  ok false
        --programs $PWD/vibe-ic-marketplace/.../programs   probe_returncode 0  ok true

    "I could not find the entry" and "the runtime cannot report" are different
    findings with different remedies, and this gate exists precisely so a reader
    is not left inferring which one they have.
    """
    entry = entry.absolute()
    with tempfile.TemporaryDirectory(prefix="vibeic-runtime-probe-") as raw:
        subject = Path(raw)
        (subject / _PROBE_NAME).write_text(_PROBE_TEST, encoding="utf-8")
        env = {key: value for key, value in os.environ.items()
               if key not in {"PYTHONPATH", "PYTHONHOME"}
               and not key.startswith(PROGRESS_ENV_PREFIX)}
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        return _run([python, "-I", str(entry), "-q", "-p",
                     "no:cacheprovider", _PROBE_NAME],
                    cwd=subject, env=env)


def _refusal_lines(*, python: str, isolated_ok: bool, resolved: str,
                   lane: Optional[str], probe: Optional[subprocess.CompletedProcess],
                   ) -> List[str]:
    """The one attributable refusal.  Every line here is measured, not inferred."""
    out = [
        "  REFUSE  the protected landing test runtime cannot run on this host.",
        "",
        "          CAUSE",
    ]
    if not isolated_ok and lane is None and resolved:
        # THE FLEET'S SHAPE, and the one worth naming precisely: the runner IS
        # installed, just not where an isolated interpreter looks.
        out += [
            "            `python3 -I` is isolated mode, which suppresses the USER",
            "            site directory. The landing arms execute their test runner",
            "            through trusted_pytest_entry.py under -I, and on this host",
            "            the runner resolves ONLY in the user site directory, so the",
            "            entry cannot import it and refuses.",
            "",
            "          MEASURED",
            f"            {python} -c    'import pytest'  ->  {resolved}",
            f"            {python} -I -c 'import pytest'  ->  ModuleNotFoundError",
        ]
    elif not isolated_ok and lane is None:
        # A DIFFERENT CAUSE WITH THE SAME BLAST RADIUS, so it gets its own
        # sentence rather than the one above. Saying "isolated mode suppressed
        # it" about an interpreter that has no test runner at all would send the
        # reader to the wrong remedy.
        out += [
            "            this interpreter cannot import the test runner AT ALL —",
            "            not in isolated mode and not outside it. The landing arms",
            "            execute their runner through trusted_pytest_entry.py, so",
            "            the entry refuses and no arm can produce a record.",
            "",
            "          MEASURED",
            f"            {python} -c    'import pytest'  ->  ModuleNotFoundError",
            f"            {python} -I -c 'import pytest'  ->  ModuleNotFoundError",
        ]
    else:
        out += [
            "            the entry was reachable but the runtime it assembles could",
            "            not execute one synthetic test and report it. A runtime that",
            "            imports and cannot report produces exactly the same",
            "            every-file-UNKNOWN shape as one that cannot import.",
            "",
            "          MEASURED",
            f"            lane        {lane or 'image (system site directory)'}",
            f"            runner      {resolved or 'unresolved'}",
        ]
        if probe is not None:
            out.append(f"            probe rc    {probe.returncode}")
            for stream, label in ((probe.stderr, "stderr"), (probe.stdout, "stdout")):
                for line in [ln for ln in stream.splitlines() if ln.strip()][-6:]:
                    out.append(f"            {label}      {line}")
    out += [
        "",
        "          WHY THIS IS A REFUSAL AND NOT A RUN",
        "            Continuing would spawn every arm's child into the same failure.",
        "            Each selected file would be reported NORECORD — UNKNOWN, not",
        "            clean and not red — and no junit test case would exist at all.",
        "            That is hundreds of lines naming hundreds of innocent files and",
        "            not one line naming the cause. Refusing once, here, is the",
        "            same verdict said truthfully.",
        "",
        "          REMEDY — run the landing inside the digest-pinned runner image,",
        "          where the test runner is in the system site directory:",
        "",
        f'            docker run --rm -v "$PWD:$PWD" -w "$PWD" \\',
        f"              {RUNNER_IMAGE} \\",
        "              bash tools/gatekeeper-land.sh",
        "",
        "          OR open the HOST LANE explicitly, accepting that the runtime is",
        "          then the host's and not the pinned image's:",
        "",
        f"            {HOST_LANE_ENV}={HOST_LANE_AUTO} bash tools/gatekeeper-land.sh",
        f"            {HOST_LANE_ENV}=<absolute site dir> bash tools/gatekeeper-land.sh",
        "",
        f"          `{HOST_LANE_AUTO}` derives the directory from the NON-isolated",
        "          interpreter's user site directory. The lane is opt-in on purpose:",
        "          it is an explicit, attributable step away from the pinned image,",
        "          never a silent fallback. trusted_pytest_entry.py still raw-attests",
        "          every file it resolves and still refuses anything resolving inside",
        "          the subject checkout.",
    ]
    return out


def preflight(*, programs: Path, python: Optional[str] = None) -> Dict[str, object]:
    """Decide, once, whether the landing arms can produce a record at all."""
    python = python or sys.executable
    entry = Path(programs) / "trusted_pytest_entry.py"
    lane = os.environ.get(HOST_LANE_ENV) or None
    if not entry.is_file():
        return {"ok": False, "lane": lane, "isolated_import": False,
                "runner": "", "probe_returncode": None,
                "reason": "trusted_pytest_entry.py is absent",
                "lines": ["  REFUSE  the protected landing test runtime is not "
                          "installed in this tree.",
                          f"          expected {entry}"]}
    isolated_ok, resolved = isolated_import_lane(python)
    if not isolated_ok and lane is None:
        return {"ok": False, "lane": None, "isolated_import": False,
                "runner": resolved, "probe_returncode": None,
                "reason": "isolated interpreter cannot import the test runner "
                          "and no host lane is configured",
                "lines": _refusal_lines(python=python, isolated_ok=False,
                                        resolved=resolved, lane=None, probe=None)}
    probe = entry_probe(python, entry)
    recorded = probe.returncode == 0 and "1 passed" in probe.stdout
    if not recorded:
        return {"ok": False, "lane": lane, "isolated_import": isolated_ok,
                "runner": resolved, "probe_returncode": probe.returncode,
                "reason": "the trusted entry could not execute and report one "
                          "synthetic test",
                "lines": _refusal_lines(python=python, isolated_ok=isolated_ok,
                                        resolved=resolved, lane=lane, probe=probe)}
    where = "host lane" if lane is not None else "image lane"
    detail = f" ({HOST_LANE_ENV}={lane})" if lane is not None else ""
    return {"ok": True, "lane": lane, "isolated_import": isolated_ok,
            "runner": resolved, "probe_returncode": 0,
            "reason": f"the protected landing test runtime executes and reports "
                      f"via the {where}",
            "lines": [f"  PASS  landing test runtime is executable via the "
                      f"{where}{detail}"]}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Refuse the landing ONCE, attributably, when the protected "
                     "test runtime cannot produce a record on this host."))
    parser.add_argument(
        "--programs", default=str(Path(__file__).resolve().parent),
        help="the plugin programs directory holding trusted_pytest_entry.py")
    parser.add_argument("--json", action="store_true",
                        help="emit the decision as one JSON object on stdout")
    args = parser.parse_args(argv)

    result = preflight(programs=Path(args.programs))
    if args.json:
        payload = {key: value for key, value in result.items() if key != "lines"}
        print(json.dumps(payload, sort_keys=True))
    else:
        stream = sys.stdout if result["ok"] else sys.stderr
        for line in result["lines"]:                      # type: ignore[union-attr]
            print(line, file=stream)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
