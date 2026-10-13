#!/usr/bin/env python3
"""formal_proof_evidence_check.py — Step 5 formal proof EVIDENCE-CHAIN
gate (ORGANIC-20260606 #448).

The audited residual (after #440 removed the runner's placeholder/
re-label emission): the flow gate itself still trusted the bare
`all_proved` field — a hand-planted `{"all_proved": true}` results.json
passed with no .sby and no SymbiYosys run anywhere. `all_proved: true`
is a CLAIM; this gate verifies the chain that substantiates it:

  (a) a `.sby` task exists under formal/ and every RTL/assertion file
      it references actually exists (it could elaborate);
  (b) a SymbiYosys log exists (sby/smtbmc tool signature) whose status
      is PASS;
  (c) results.json's `evidence` pointer (when path-shaped, per the
      #433 convention) dereferences to an existing non-empty file;
  (d) #1974 — a COMPLETED claim also states what it claims OVER: a
      positive `property_denominator` covered by `authored_property_count`,
      a non-empty `bounded_vs_unbounded_scope`, `elaborated_sby` agreeing
      with `sby`, `proof_transcript` agreeing with `evidence`, and a
      dereferenceable receipt whenever `expert_fallback_required`. Proof
      evidence without a denominator is a claim about a subset nobody
      stated, so (d) decides the VERDICT exactly as (a)-(c) do.

      The last three are ALIASES: the emitter sets `elaborated_sby` from
      `sby`, `proof_transcript` from `evidence` and
      `bounded_vs_unbounded_scope` from `bounded_vs_unbounded`, so a
      manifest that cites the fact once under the older name has cited it
      (G15). The DENOMINATOR is not an alias — nothing before #1974
      carried it (`property_count` counts .sby tasks) — and it is not
      grandfathered: a completed claim that never stated its scope is the
      claim #1974 exists to refuse, whenever it was written.

WHAT DOES NOT DECIDE THE VERDICT: a dangling reference in a `.sby` the
manifest never cited. #417 reports it (`SBY_REFS_DANGLING`, tagged
`non-verdict`) while `sby_ok` stays set by the chain results.json does
cite — failing the cell for a sibling artefact its own manifest never
claimed is what that quantifier is deliberately NOT doing. Read a FAIL on
a cell carrying `SBY_REFS_DANGLING` as coming from (a)-(d), never from the
dangling sibling.

Verdicts / exit codes (chip-AGNOSTIC — structural artifacts only):
  0 = all_proved:true with a complete evidence chain (PASS)
  1 = all_proved claimed without the chain, or chain broken, or no
      proof claim at all (FAIL — a bare field is not a proof)
  2 = results.json honestly self-reports SKIPPED-CONDITION (no proof
      ran; the #440 manifest shape) — vacuous for THIS gate, OR
      (ORGANIC #675) results.json is ABSENT but a co-located sibling
      self-skip artifact (e.g. `formal/formal_not_run.json`,
      verdict=SKIPPED-CONDITION) honestly discloses that no proof ran.
      The phase2 runner (#440) emits ONLY `formal_not_run.json`, never
      `results.json`, so the absent-results.json path used to hard-FAIL
      (rc=1) despite the honest disclosure → cascade-blocked Phase 3.

§4.05 no-leak: rc=2 fires ONLY when results.json is absent AND a sibling
self-reports a self-skip verdict. A REAL authored proof
(results.json + .sby + sby PASS log) gates normally (rc=0/1); a real
formal FAIL (results.json present with all_proved:false, or a broken
chain) still FAILs (rc=1) — no skip leak.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent))
import _flow_reason_taxonomy as _reason_taxonomy  # noqa: E402
import _path_layout as _pl  # noqa: E402

# SymbiYosys transcript signatures + pass markers. Tool-output shapes,
# not chip-class literals.
_SBY_SIG_RE = re.compile(
    r"SBY|symbiyosys|smtbmc|engine_\d|summary:\s*Elapsed", re.IGNORECASE)
_SBY_PASS_RE = re.compile(
    r"DONE \(PASS", re.IGNORECASE)
_SBY_FAIL_RE = re.compile(
    r"DONE \(FAIL|DONE \(ERROR|Status:\s*FAILED|Assert failed",
    re.IGNORECASE)
# files a .sby references: `read -formal <f>` / `read_verilog <f>` in
# [script], plus the [files] / [file <dst>] section entries.
# ORGANIC #550 (b) — skip ANY number of leading `-flag` tokens before the
# filename. The old single-flag form `(?:-formal\s+|-sv\s+)?` captured a flag
# as the "referenced file" on a multi-flag read line
# (`read_verilog -sv -DPROP1 -DPROP2 dut.sv` → captured `-DPROP1`), which then
# resolved to nothing and false-FAILed SBY_CHAIN_BROKEN.
_SBY_READ_RE = re.compile(
    r"^\s*read(?:_verilog|_sv)?\s+(?:-\S+\s+)*([^\s-]\S*)",
    re.IGNORECASE | re.MULTILINE)
_SBY_SECTION_RE = re.compile(r"^\[(\w+)(?:\s+(\S+))?\]\s*$")


def _sby_file_refs(txt: str):
    """ORGANIC-20260606 #453 — collect referenced files from BOTH the
    [script] read lines AND the [files]/[file <dst>] sections. A legit
    SymbiYosys task may list its sources only under [files] (each line
    `<dst> <src>` or just `<src>`); the old [script]-only walker
    false-FAILed those as SBY_CHAIN_BROKEN."""
    refs = list(_SBY_READ_RE.findall(txt))
    section = None
    for line in txt.splitlines():
        m = _SBY_SECTION_RE.match(line.strip())
        if m:
            section = m.group(1).lower()
            continue
        if section in ("files", "file"):
            tok = line.strip()
            if not tok or tok.startswith("#"):
                continue
            # `[files]` line shape: `<dst> <src>` (copy-rename) or `<src>`
            parts = tok.split()
            refs.append(parts[-1])
    # de-dup, keep order
    seen = set()
    out = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _resolve(sby_dir: Path, formal_dir: Path, project: Path, token: str):
    """Resolve a `.sby` reference the way SymbiYosys would.

    #418. This function's docstring already said "relative to the .sby dir",
    and the code had never used the .sby dir — it resolved against
    `formal_dir`. For a `.sby` at the top of `formal/` those are the same
    directory, so the difference was unobservable until #412 made NESTED
    `.sby` files discoverable. After that, `reset_safety/spm_reset_safety.sby`
    naming a bare `spm.v` — which SymbiYosys reads as `reset_safety/spm.v`,
    absent — resolved to `formal/spm.v` one level up, and a `.sby` that
    `sby -f` could not run was reported as elaboratable. The gate's own words
    for what it checks are "an elaboratable .sby".

    The unrestricted `formal_dir.rglob(basename)` last resort is gone with
    it: any file of the right NAME anywhere beneath `formal/` used to satisfy
    a reference, which is not evidence the `.sby` could elaborate. Measured
    across every `.sby` in the published corpus before removing it: 7
    references resolve from the `.sby`'s own directory, 3 from the staging
    fallback below, 1 only from `formal_dir` (the false clean above), 2 are
    genuinely unresolved — and ZERO used the unrestricted rglob.

    ORGANIC #550 (a) IS KEPT, and it is the reason this is not simply
    tightened: a `[files]` entry is copied into the task workdir as
    `<task>/src/<basename>`, so after a real run the original source path can
    be gone while the proof evidence lives under `src/`. Three references in
    the corpus depend on that. Removing it would false-FAIL genuinely proved
    cells — the opposite error, in the direction that costs more.
    """
    if any(ch in token for ch in "*?["):
        hits = (list(sby_dir.glob(token)) + list(project.glob(token)))
        return hits[0] if hits else None
    for base in (sby_dir, project):
        p = base / token
        if p.is_file():
            return p
    # #550(a) staging fallback: the file copied to <task>/src/<basename>.
    basename = Path(token).name
    if basename:
        staged = sorted(formal_dir.rglob(f"src/{basename}"))
        if staged:
            return staged[0]
    return None


_SELF_SKIP_VERDICTS = frozenset({"SKIP", "SKIPPED", "SKIPPED-CONDITION"})


def _sibling_self_skip(formal_dir: Path):
    """ORGANIC #675 — when formal/results.json is absent, return the basename
    of a co-located sibling *.json that HONESTLY self-reports a self-skip
    verdict (verdict ∈ SKIP/SKIPPED/SKIPPED-CONDITION), else None. The phase2
    runner emits `formal_not_run.json` (verdict=SKIPPED-CONDITION) when no
    proof tool ran. chip-AGNOSTIC: scans only the verdict field of JSON files
    in formal/, no chip/vendor/class literal. A sibling whose verdict is NOT a
    self-skip verdict (a real FAIL) returns None → the caller hard-FAILs."""
    try:
        siblings = sorted(formal_dir.glob("*.json"))
    except OSError:
        return None
    for sib in siblings:
        if sib.name == "results.json":
            continue
        try:
            data = json.loads(sib.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        vd = str(data.get("verdict", "")).upper().replace("_", "-")
        if vd in _SELF_SKIP_VERDICTS:
            return sib.name
    return None


def _sibling_payload(formal_dir: Path, name: str):
    """The parsed JSON of a sibling this module already matched, or None.

    Read back rather than threaded through `_sibling_self_skip`'s return: that
    helper's `-> basename or None` contract is asserted by four tests, and a
    tuple return would move them for a reason that has nothing to do with what
    they measure.
    """
    try:
        data = json.loads((formal_dir / name).read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _sibling_env_gap(formal_dir: Path):
    """#216 — return `(basename, env_gap_dict)` of a co-located sibling that
    discloses an unreachable formal ENGINE, else None.

    Deliberately NOT folded into `_SELF_SKIP_VERDICTS`: an environment gap is
    not a self-skip. A self-skip makes this gate vacuous (rc=2); an
    environment gap keeps it a hard FAIL and only changes the ATTRIBUTION, so
    the reader learns what to install instead of "nothing claims a proof".
    chip-AGNOSTIC: reads only the verdict + env_gap fields.
    """
    try:
        siblings = sorted(formal_dir.glob("*.json"))
    except OSError:
        return None
    for sib in siblings:
        if sib.name == "results.json":
            continue
        try:
            data = json.loads(sib.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        vd = str(data.get("verdict", "")).upper().replace("_", "-")
        if vd == "ENV-UNAVAILABLE":
            gap = data.get("env_gap")
            return sib.name, (gap if isinstance(gap, dict) else {})
    return None


def _sibling_authoring_incomplete(formal_dir: Path):
    """Return the applicable authoring request that still has no sound SVA.

    INCOMPLETE is deliberately separate from self-skip: somebody must return
    to these named declaration/property obligations.
    """
    try:
        siblings = sorted(formal_dir.glob("*.json"))
    except OSError:
        return None
    for sib in siblings:
        if sib.name == "results.json":
            continue
        try:
            data = json.loads(sib.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        vd = str(data.get("verdict", "")).upper().replace("_", "-")
        if vd == "INCOMPLETE":
            return sib.name, data
    return None


def _authored_sby_files(formal_dir):
    """Every AUTHORED `.sby` under `formal/`, recursively.

    ORGANIC #412 — discovery was INCONSISTENT: transcripts were found with
    `rglob`, `.sby` and `results.json` only at the top level. A cell whose
    evidence is organised one level down (`formal/<campaign>/`,
    `formal/<property>/`) therefore got "results.json absent — nothing claims
    a proof" for evidence this same function had already located. Measured on
    the published ihp-sg13g2 cell: `.sby`, `.sby.log` and `results.json` all
    present under `campaign_v1558/`, verdict FAIL / NO_RESULTS.

    SymbiYosys writes its OWN copy of the config into each task workdir as
    `config.sby`, so a bare `rglob("*.sby")` would count the tool's generated
    artefact as a second authored proof. One is tracked in this repo today.
    Skipped STRUCTURALLY — `config.sby` beside a `status` or `logfile.txt`
    is a workdir, not an authored task — rather than by name alone, so an
    authored file that happens to be called `config.sby` still counts.
    """
    out = []
    for f in sorted(formal_dir.rglob("*.sby")):
        if f.name == "config.sby" and (
                (f.parent / "status").exists()
                or (f.parent / "logfile.txt").exists()):
            continue
        out.append(f)
    return out


def _first_results_json(formal_dir):
    """`formal/results.json`, else the first one found recursively (#412)."""
    top = formal_dir / "results.json"
    if top.is_file():
        return top
    for f in sorted(formal_dir.rglob("results.json")):
        if f.is_file():
            return f
    return top          # non-existent top-level path, for the message



def _declared_skip_class(data) -> str:
    """The reason class for a self-reported skip, from the DECLARER.

    TYPED (#1978). `_flow_reason_taxonomy.infer_nonverdict_reason` falls closed
    to EXECUTION_ERROR — "the gate blew up" — for any rc=2 whose report names
    no class, and this gate does not blow up on this branch: it reads an honest
    disclosure and agrees with it. MEASURED before this: the flow booked the
    #675 self-skip as EXECUTION_ERROR, `check_step` promoted step 5 to
    INCOMPLETE, and `required_outputs` then made it MISSING — which is the
    Phase-3 cascade block #675 exists to remove.

    THE CLASS IS THE DECLARER'S, not this gate's guess. If the manifest names
    one, it is used verbatim. Only when it names none does this gate say
    DESIGN_DECLARED_NA, and that word is earned by the branch's own narrowness,
    not by matching prose: results.json is absent, a sibling explicitly
    self-reports a self-skip VERDICT, it is not an authoring-incomplete
    manifest (that branch returned INCOMPLETE above) and it is not an
    ENV_UNAVAILABLE manifest (that branch hard-FAILs below, on purpose — an
    unreachable engine is never vacuous here). What is left is a runner
    declaring that the condition for running a proof was not met, which is what
    the flow renders as SKIPPED-CONDITION.
    """
    if isinstance(data, dict):
        declared = _reason_taxonomy.report_reason_class(data)
        if declared:
            return declared
    return _reason_taxonomy.DESIGN_DECLARED_NA


DISCHARGED_BY_BINDING = "DISCHARGED_BY_BINDING"
BINDING_OUTSTANDING = "BINDING_OUTSTANDING"
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_PROPERTY_RE = re.compile(r"\bproperty\s+(\w+)\s*;(.*?)\bendproperty\b", re.S)


def strip_comments(text: str) -> str:
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", text))


def _harness_files(project: Path, formal_dir: Path, results: dict) -> List[Path]:
    """The harness (and any expert fragment it includes) the .sby names."""
    names: List[str] = []
    sby = results.get("sby")
    sby_path = project / sby if isinstance(sby, str) else None
    if sby_path is not None and sby_path.is_file():
        names = re.findall(r"^\s*(formal_[\w.-]+\.svh?)\s*$",
                           sby_path.read_text(errors="replace"), re.M)
    if not names:
        names = [p.name for p in sorted(formal_dir.glob("formal_*.sv"))]
    return [formal_dir / Path(n).name for n in dict.fromkeys(names)
            if (formal_dir / Path(n).name).is_file()]


def _harness_not_proven(files: List[Path], results: dict) -> Optional[str]:
    """None when every harness file on disk is byte-identical (sha256) to the
    one the recorded proof read (`results["proof_inputs"]`); else why not."""
    import hashlib
    recorded = (results.get("proof_inputs") or {}).get("files")
    if not isinstance(recorded, dict):
        return "the proof does not name the harness it proved (no proof_inputs)"
    if not files:
        return "no harness file on disk"
    for f in files:
        try:
            now = hashlib.sha256(f.read_bytes()).hexdigest()
        except OSError:
            now = None
        if recorded.get(f.name) != now:
            return (f"harness not the one proven: {f.name} sha256 {str(now)[:12]} "
                    f"!= proved {str(recorded.get(f.name))[:12]}")
    return None


def _dut_instance(harness: str) -> tuple[str | None, dict[str, str]]:
    """DUT module and its named port connections, excluding other instances."""
    instance = re.search(r"\b([A-Za-z_]\w*)\s*(?:#\s*\([^;]*?\)\s*)?dut\s*\(",
                         harness, re.S)
    if not instance:
        return None, {}
    start = instance.end()
    depth = 1
    end = start
    while end < len(harness) and depth:
        if harness[end] == "(":
            depth += 1
        elif harness[end] == ")":
            depth -= 1
        end += 1
    if depth or not re.match(r"\s*;", harness[end:]):
        return None, {}
    connections = harness[start:end - 1]
    # A direct identifier is the only connection that can bind the asserted
    # signal. Empty, concatenated, sliced, and expression connections fail closed.
    ports = {m.group(1): m.group(2).strip() for m in re.finditer(
        r"\.\s*([A-Za-z_]\w*)\s*\(\s*([^()]*)\s*\)", connections)}
    return instance.group(1), ports


def _harness_connects(harness: str, port: str) -> bool:
    """The proved DUT instance directly connects `.port(port)`."""
    _, ports = _dut_instance(harness)
    return ports.get(port) == port


def _harness_binds_reset(harness: str, port: str) -> bool:
    """The generated reset-active expression reads `port` (`rst_active = [!]port`)."""
    return bool(re.search(
        rf"\bwire\s+rst_active\s*=\s*[!~]?\s*{re.escape(port)}\s*;", harness))


def _dut_output_ports(project: Path, harness: str) -> set[str]:
    """Output ports of the DUT instance actually named by the proved harness."""
    import formal_harness_gen as _fhg
    name, _ = _dut_instance(harness)
    if name is None:
        return set()
    rtl_dir = project / "phase2/stage1/rtl"
    for path in sorted(list(rtl_dir.rglob("*.v")) + list(rtl_dir.rglob("*.sv"))):
        iface = _fhg.parse_module(path.read_text(errors="replace"), name)
        if iface is not None:
            return {p.name for p in iface.ports if p.direction == "output"}
    return set()


_RESET_LITERAL = r"(?:'0|'1|\d+'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ]+|[01])"
_RESET_PREDICATE_RE = re.compile(
    rf"^\s*\(?\s*(?P<output>[A-Za-z_]\w*)\s*==\s*{_RESET_LITERAL}\s*\)?\s*$")


def _substantive_reset_predicate(harness: str, predicate: str,
                                 output_ports: set[str] | None) -> bool:
    """A direct reset-value check on a connected DUT output, not a tautology."""
    match = _RESET_PREDICATE_RE.fullmatch(predicate)
    if not match:
        return False
    output = match.group("output")
    return ((output_ports is None or output in output_ports)
            and _harness_connects(harness, output))


def _reset_guarded_properties(harness: str,
                              output_ports: set[str] | None = None) -> List[str]:
    """Asserted, reset-guarded checks of a connected DUT output's reset value.

    `formal_harness_gen` emits concurrent `assert property` statements for
    `read_verilog -sv`. Its equivalent `read_slang` form is an immediate
    labelled assertion inside `if (f_past_valid && rst_active)`. Both forms
    are proved by the same SBY tasks; recognize both as binding evidence.
    """
    asserted = set(re.findall(r"\bassert\s+property\s*\(\s*(\w+)\s*\)", harness))
    concurrent = set()
    for name, body in _PROPERTY_RE.findall(harness):
        consequent = re.search(
            r"\(\s*f_past_valid\s*&&\s*rst_active(?:_q)?\s*\)\s*\|->\s*"
            r"\((?P<predicate>[^;]+)\)\s*;", body)
        if (name in asserted and consequent and
                _substantive_reset_predicate(harness, consequent.group("predicate"),
                                             output_ports)):
            concurrent.add(name)
    # Accept the immediate form the generator actually emits. Merely finding
    # `rst_active` somewhere in an if condition is insufficient: under `||`,
    # the assertion may run when reset is inactive and prove no reset binding.
    immediate = {m.group("name") for m in re.finditer(
        r"\bif\s*\(\s*f_past_valid\s*&&\s*rst_active(?:_q)?\s*\)\s*"
        r"(?P<name>[A-Za-z_]\w*)\s*:\s*assert\s*\((?P<predicate>[^;]+)\)\s*;",
        harness) if _substantive_reset_predicate(harness, m.group("predicate"),
                                                 output_ports)}
    return sorted(concurrent | immediate)


def binding_dispositions(project: Path, formal_dir: Path, results: dict) -> List[dict]:
    """R-0924-2 — a NAME obligation (`resets.N.name`) is discharged
    STRUCTURALLY: the harness binds the declared port as the reset (the DUT
    port is connected to it and the reset-active expression reads it) AND a
    property guarded by that reset is asserted AND this run PROVED it
    (every task PASS, at least one unbounded). Otherwise it stays outstanding
    with the reason. Never a trace proof; never dropped silently."""
    import formal_harness_gen as _fhg
    rows = [(r, _fhg.binding_obligation(r, project))
            for r in results.get("unresolved_obligations") or []]
    rows = [(r, b) for r, b in rows if b]
    if not rows:
        return []
    hfiles = _harness_files(project, formal_dir, results)
    stale = _harness_not_proven(hfiles, results)
    harness = strip_comments("\n".join(f.read_text(errors="replace") for f in hfiles))
    tasks = [t for t in results.get("properties") or [] if isinstance(t, dict)]
    proven = (results.get("all_proved") is True and bool(tasks)
              and all(str(t.get("status")) == "PASS" for t in tasks)
              and any(t.get("bound") == "unbounded" for t in tasks))
    proof_status = ", ".join(f"{t.get('task')}:{t.get('status')}"
                             f"({t.get('bound')})" for t in tasks) or "no proof task"
    covering = _reset_guarded_properties(harness, _dut_output_ports(project, harness))
    out: List[dict] = []
    for row, b in rows:
        rec = {"id": str(row.get("id")), "kind": "binding", "role": b["role"],
               "port": b["port"], "property": None, "proof_status": proof_status,
               "proved_harness_sha256": {
                   f.name: ((results.get("proof_inputs") or {}).get("files") or {}).get(f.name)
                   for f in hfiles}}
        why = []
        if not _harness_connects(harness, b["port"]):
            why.append(f"the harness does not connect the DUT port {b['port']!r}")
        if not _harness_binds_reset(harness, b["port"]):
            why.append(f"the harness does not bind {b['port']!r} as the reset "
                       f"(no `rst_active = [!]{b['port']}`)")
        if covering:
            rec["property"] = covering[0]
        else:
            why.append("no substantive reset assertion on a connected DUT output is guarded by that reset")
        if stale:
            why.append(stale)
        if not proven:
            why.append(f"the covering property is not proven ({proof_status})")
        if why:
            rec.update(status=BINDING_OUTSTANDING, reason="; ".join(why))
        else:
            rec.update(status=DISCHARGED_BY_BINDING, reason=(
                f"harness binds DUT port {b['port']!r} as the reset and "
                f"{covering[0]}, guarded by it, is PROVEN ({proof_status})"))
        out.append(rec)
    return out


def _chip_read_stale(project: Path, results: dict) -> List[str]:
    """What differs between the chip read the proof recorded and the chip
    (R-0915-157 round 9). Empty = the proof is about the chip."""
    import _chip_synth_read as _csr
    proved = results.get("chip_read")
    if not isinstance(proved, dict) or not proved.get("top"):
        return ["the proof recorded no chip read"]
    try:
        now = _csr.current_chip_read(project, str(proved["top"]))
    except Exception as e:  # noqa: BLE001 — unknown is not "the same"
        return [f"the chip read could not be taken now ({e})"]
    out = [f"now — {d}" for d in _csr.chip_read_differences(proved, now)]
    built = _csr.built_record_path(project)
    if built.is_file():
        try:
            rec = json.loads(built.read_text())
        except (OSError, ValueError):
            rec = None
        if not isinstance(rec, dict):
            out.append(f"phase-3 synthesis — {built.name} unreadable")
        else:
            out += [f"phase-3 synthesis — {d}"
                    for d in _csr.chip_read_differences(proved, rec)]
    return out


def audit(project: Path) -> dict:
    formal_dir = _pl.formal_dir(project)
    results_path = _first_results_json(formal_dir)
    rep = {"program": "formal_proof_evidence_check", "version": "1.0.0",
           "findings": []}

    if not results_path.is_file():
        # ORGANIC #675 — results.json is the canonical proof artifact, but
        # the phase2 runner (#440) emits ONLY a sibling self-skip manifest
        # (`formal/formal_not_run.json`, verdict=SKIPPED-CONDITION) when no
        # SymbiYosys proof ran, and NEVER results.json. Before declaring a
        # hard FAIL, honor that honest disclosure: if ANY *.json in formal/
        # self-reports a self-skip verdict, this gate is vacuous (rc=2), the
        # same way an in-results.json SKIPPED-CONDITION already is. This is
        # the program-first root-cause fix for the formal-step cascade block.
        # §4.05 no-leak: only the absent-results.json + honest-sibling-skip
        # pair defers; a real proof has results.json present (this branch is
        # not taken), and a sibling with a non-skip verdict (a real FAIL) is
        # NOT matched → falls through to the hard FAIL below.
        incomplete = _sibling_authoring_incomplete(formal_dir)
        if incomplete is not None:
            sib, data = incomplete
            unresolved = data.get("unresolved_obligations") or []
            ids = [str(row.get("id", "?")) for row in unresolved
                   if isinstance(row, dict)]
            rep.update(verdict="INCOMPLETE", rc=0,
                       property_denominator=data.get("property_denominator"),
                       unresolved_obligations=unresolved,
                       fallback_skill=data.get("fallback_skill", "formal-verify"))
            rep["findings"].append(
                f"AUTHORING_INCOMPLETE (#1974): results.json absent and "
                f"'{sib}' names applicable declaration/property work with no "
                f"sound authored property: {', '.join(ids) or 'unnamed obligation'}; "
                f"invoke {rep['fallback_skill']} (this is not a skip and not a "
                f"missing tool capability)")
            return rep
        skip_sib = _sibling_self_skip(formal_dir)
        if skip_sib is not None:
            rep.update(verdict="SKIPPED-CONDITION", rc=2,
                       reason_class=_declared_skip_class(
                           _sibling_payload(formal_dir, skip_sib)))
            rep["findings"].append(
                f"SELF_REPORTED_SKIP (#675): results.json absent but the "
                f"co-located sibling '{skip_sib}' honestly self-reports no "
                f"proof ran (verdict=SKIPPED-CONDITION, #440 manifest "
                f"shape) — vacuous for this gate, NOT a fabricated PASS")
            return rep
        # #216 — when the proof ENGINE was never reached, the runner leaves
        # an ENV_UNAVAILABLE manifest naming the missing capability, the
        # search location and the remedy. This is STILL a hard FAIL — an
        # unreachable environment is not a self-skip and must never be
        # vacuous — but the finding carries the actionable detail instead of
        # the bare "nothing claims a proof", which is a dead end for whoever
        # has to fix the host.
        env_gap = _sibling_env_gap(formal_dir)
        if env_gap is not None:
            sib, gap = env_gap
            rep.update(verdict="FAIL", rc=1)
            rep["findings"].append(
                f"ENV_UNAVAILABLE (#216): no proof ran because the formal "
                f"engine was never reached — missing capability "
                f"{gap.get('missing_capability', '?')!r}, looked for it at "
                f"{gap.get('searched', '?')}. Remedy: "
                f"{gap.get('remedy', '?')} "
                f"(disclosed by '{sib}'). This is an ENVIRONMENT gap, not a "
                f"design defect and not an inconclusive proof — but it is "
                f"NOT vacuous: Step 5 has no proof evidence, so this gate "
                f"FAILs until the engine is reachable or the step is waived "
                f"through a reviewed waivers.json entry.")
            return rep
        rep.update(verdict="FAIL", rc=1)
        rep["findings"].append(
            "NO_RESULTS: formal/results.json absent — nothing claims a "
            "proof (step 5 reports its capability gap upstream)")
        return rep
    try:
        results = json.loads(results_path.read_text(errors="replace"))
    except (OSError, ValueError):
        rep.update(verdict="FAIL", rc=1)
        rep["findings"].append("BAD_JSON: results.json unparseable")
        return rep

    verdict_field = str(results.get("verdict", "")).upper().replace("_", "-")
    if verdict_field == "SKIPPED-CONDITION":
        rep.update(verdict="SKIPPED-CONDITION", rc=2,
                   reason_class=_declared_skip_class(results))
        rep["findings"].append(
            "SELF_REPORTED_SKIP: results.json honestly reports no proof "
            "ran (#440 manifest shape) — vacuous for this gate")
        return rep

    # R-0915-144 — two program answers that are NOT "work not yet done":
    #   * a structural check that REFUTED a declaration measured the design
    #     contradicting its own spec. That is a refutation, like a
    #     counterexample, so it FAILS — it must never read as INCOMPLETE.
    #   * a refused hierarchical reference: the proof would have been about a
    #     free variable, so it did not run; the refusal is named.
    refutations = results.get("structural_refutations") or []
    if refutations:
        rep.update(verdict="FAIL", rc=1, structural_refutations=refutations)
        rep["findings"].append(
            "STRUCTURAL_REFUTED (R-0915-144): the program's structural check "
            "measured the RTL contradicting its declaration: "
            + "; ".join(f"{r.get('id')}: {r.get('reason')}" for r in refutations
                        if isinstance(r, dict)))
        return rep
    if results.get("refusal"):
        rep["findings"].append(str(results["refusal"]))
    # R-0924-2 — name obligations, answered structurally before anything
    # counts the open denominator. Recorded either way; a discharged one leaves
    # `unresolved_obligations` and is published as DISCHARGED_BY_BINDING, never
    # as an authored (trace) property.
    bindings = binding_dispositions(project, formal_dir, results)
    by_binding: List[str] = []
    if bindings:
        rep["binding_obligations"] = bindings
        by_binding = [b["id"] for b in bindings if b["status"] == DISCHARGED_BY_BINDING]
        for b in bindings:
            rep["findings"].append(
                f"{b['status']} (R-0924-2): {b['id']} — {b['reason']}")
    if by_binding:
        remaining = [r for r in results.get("unresolved_obligations") or []
                     if not (isinstance(r, dict) and str(r.get("id")) in by_binding)]
        results = dict(results, unresolved_obligations=remaining)
        rep["discharged_by_binding"] = by_binding
        if verdict_field == "INCOMPLETE" and not remaining:
            # the contract was open ONLY on what the binding just closed
            verdict_field = str(results.get("proof_verdict") or "PASS").upper()
    # R-0915-157 round 9 — A PROGRAM-CLOSED PROOF MUST BE ABOUT THE CHIP. The
    # proof recorded the exact read it proved (`chip_read`); it is compared
    # with the chip read as it stands NOW and with the read phase-3 synthesis
    # BUILT, when that exists. Any difference (the define decision, the file
    # set or contents, the top) makes every program closure STALE: refused as
    # NOT_DISCHARGED with what differs, never PASS.
    _closed = [str(x) for x in results.get("program_discharged_obligations") or []]
    if _closed:
        _stale = _chip_read_stale(project, results)
        if _stale:
            _why = "proof read a different chip: " + "; ".join(_stale)
            _rows = [r for r in results.get("unresolved_obligations") or []
                     if isinstance(r, dict)]
            _have = {str(r.get("id")) for r in _rows}
            _rows += [{"id": oid, "status": "NOT_DISCHARGED", "description": _why}
                      for oid in _closed if oid not in _have]
            results = dict(results, unresolved_obligations=_rows)
            rep["chip_read_stale"] = _stale
            rep["findings"].append(
                f"CHIP_READ_STALE (R-0915-157): {len(_closed)} program-closed "
                f"obligation(s) NOT_DISCHARGED — {_why}")
    contract_incomplete = (verdict_field == "INCOMPLETE"
                           or bool(results.get("unresolved_obligations")))
    if results.get("all_proved") is not True:
        rep.update(verdict="FAIL", rc=1)
        rep["findings"].append(
            "NO_PROOF_CLAIM: all_proved is not true — no proof to gate")
        return rep

    # (a) an elaboratable .sby ----------------------------------------------
    sby_ok = False
    sby_missing_refs = []
    sby_files = _authored_sby_files(formal_dir)
    sby_no_refs = []
    for sby in sby_files:
        txt = sby.read_text(errors="replace")
        refs = _sby_file_refs(txt)   # [script] reads + [files] entries (#453)
        if not refs:
            sby_no_refs.append(sby.name)
            continue
        missing = [t for t in refs
                   if _resolve(sby.parent, formal_dir, project, t) is None]
        if not missing:
            # #417: record the FIRST intact chain, but do NOT break. The loop
            # used to stop here, so every later .sby went unexamined and its
            # dangling references could not be reported at all.
            if not sby_ok:
                sby_ok = True
                rep["sby"] = str(sby.relative_to(project))
            continue
        sby_missing_refs.append(f"{sby.name}: {', '.join(missing[:4])}")
    if not sby_ok:
        # #453 — message split: "no .sby at all" vs ".sby present but no
        # parseable refs" vs "refs missing on disk" (the old single
        # message claimed "(no .sby found)" while the file existed).
        if not sby_files:
            detail = " (no .sby found under formal/)"
        elif sby_missing_refs:
            detail = f" — missing: {'; '.join(sby_missing_refs[:3])}"
        else:
            detail = (f" — .sby present ({', '.join(sby_no_refs[:3])}) but "
                      f"carries no parseable [script] read / [files] entry")
        rep["findings"].append(
            "SBY_CHAIN_BROKEN (#448): no .sby whose referenced files all "
            "exist" + detail)
    elif sby_missing_refs:
        # #417. SBY_CHAIN_BROKEN quantifies over ALL .sby ("no .sby whose
        # refs all exist"), so one intact chain made it unreachable for every
        # other chain in the directory, however broken. Landing #415 walked
        # straight through that hole: the gate had been naming TWO broken
        # chains in spm/v1.5.58_ihp-sg13g2, #415 restored the DUT for one of
        # them, and the other went silent without having changed.
        #
        # The VERDICT stays quantified the way it was, deliberately. What the
        # gate answers is whether results.json's `all_proved` stands up, and
        # it stands up on the chain results.json actually cites; a separate,
        # later regeneration that happens to live under formal/ is not the
        # claim being made, and failing the cell for it would fail cells for
        # artefacts their own manifest never claimed. What was wrong was not
        # the quantifier on the verdict — it was that a true, previously
        # reported fact had no way to be said once some other chain was fine.
        rep["findings"].append(
            f"SBY_REFS_DANGLING (#417, non-verdict): the verdict rests on "
            f"{rep.get('sby', '(an intact .sby)')}, but "
            f"{len(sby_missing_refs)} other .sby reference file(s) that do "
            f"not exist — {'; '.join(sby_missing_refs[:3])}")

    # (b) a SymbiYosys log with PASS status ---------------------------------
    log_ok = False
    log_candidates = (list(formal_dir.glob("*.log"))
                      + list(formal_dir.rglob("logfile.txt"))
                      + list(formal_dir.rglob("*.sby.log")))
    for lg in sorted(set(log_candidates)):
        try:
            txt = lg.read_text(errors="replace")
        except OSError:
            continue
        if _SBY_SIG_RE.search(txt) and _SBY_PASS_RE.search(txt) \
                and not _SBY_FAIL_RE.search(txt):
            log_ok = True
            rep["sby_log"] = str(lg.relative_to(project))
            break
    if not log_ok:
        rep["findings"].append(
            "SBY_LOG_MISSING (#448): no SymbiYosys transcript "
            "(sby/smtbmc signature) with PASS status under formal/ — "
                "all_proved without a proof run is a bare field, not a proof")

    # (d) completed Step 5 cites the denominator and proof scope ------------
    contract_ok = True
    denominator = results.get("property_denominator")
    authored = results.get("authored_property_count")
    if not isinstance(denominator, int) or denominator <= 0:
        contract_ok = False
        rep["findings"].append(
            "PROPERTY_DENOMINATOR_MISSING (#1974): completed Step 5 must state "
            "the positive declaration/property denominator")
    if (not contract_incomplete and isinstance(denominator, int)
            and (not isinstance(authored, int)
                 or authored + len(by_binding) < denominator)):
        contract_ok = False
        rep["findings"].append(
            f"PROPERTY_DENOMINATOR_OPEN (#1974): authored={authored!r}, "
            f"denominator={denominator}; a completed row must cover every "
            "applicable obligation")
    # G15 — three of (d)'s five obligations are cited by the emitter under TWO
    # names. `formal_property_run._attach_property_contract` ends with
    #     results["elaborated_sby"]             = results.get("sby")
    #     results["proof_transcript"]           = results.get("evidence")
    #     results["bounded_vs_unbounded_scope"] = list(bounded_vs_unbounded)
    # — unconditional aliases carrying no fact the pre-#1974 name did not already
    # carry. Reading ONLY the #1974 spelling therefore converted three CITED
    # facts into three "not cited" findings on every manifest written before the
    # alias existed, which is a verdict about the spelling and not about the
    # chain. The docstring words (d) as `elaborated_sby` AGREEING with `sby` and
    # `proof_transcript` AGREEING with `evidence`; a manifest that states the
    # fact once, under the older name, does not disagree with itself.
    #
    # This is scoped to the alias half deliberately. `property_denominator` /
    # `authored_property_count` are NOT aliases — they are read from the harness
    # and the obligation contract, and no pre-#1974 field carries them
    # (`property_count` counts .sby TASKS: the ihp cell's 2 are `bmc` and
    # `safety`, not two obligations). "Proof evidence without a denominator is a
    # claim about a subset nobody stated" is a statement about the artefact, not
    # about its vintage, so it keeps deciding the verdict for old cells too and
    # gets NO grandfather clause here.
    scope = results.get("bounded_vs_unbounded_scope")
    if not isinstance(scope, list) or not scope:
        scope = results.get("bounded_vs_unbounded")
    if not isinstance(scope, list) or not scope:
        contract_ok = False
        rep["findings"].append(
            "PROOF_SCOPE_MISSING (#1974): bounded/unbounded scope is not cited")
    elaborated = (results["elaborated_sby"] if "elaborated_sby" in results
                  else results.get("sby"))
    if elaborated != results.get("sby"):
        contract_ok = False
        rep["findings"].append(
            "ELABORATED_SBY_MISSING (#1974): results do not cite the elaborated "
            ".sby task as `elaborated_sby`")
    transcript = (results["proof_transcript"] if "proof_transcript" in results
                  else results.get("evidence"))
    if transcript != results.get("evidence"):
        contract_ok = False
        rep["findings"].append(
            "PROOF_TRANSCRIPT_MISSING (#1974): results do not cite the proof "
            "transcript as `proof_transcript`")
    # #3063: a completed floor clears its active queue, not the historical
    # authoring request. Recheck that identity and executable dispositions even
    # when expert_fallback_required is now false.
    import formal_harness_gen as _fhg
    try:
        authoring_contract = json.loads((formal_dir / _fhg.PROPERTY_CONTRACT).read_text())
    except (OSError, ValueError):
        authoring_contract = {}
    if not isinstance(authoring_contract, dict):
        authoring_contract = {}
    contract_rows = (authoring_contract.get("covered_obligations") or []) + (
        authoring_contract.get("unresolved_obligations") or [])
    expert_rows = [r for r in contract_rows if isinstance(r, dict)
                   and r.get("author") == "formal-verify" and r.get("property")]
    if results.get("expert_fallback_requested") or expert_rows:
        snapshot = _fhg._authoring_request_snapshot(formal_dir)
        valid = (snapshot is not None
                 and results.get("expert_fallback_request_sha256") == snapshot["sha256"])
        requested = json.loads(snapshot["text"]) if snapshot is not None else {}
        valid = (valid and results.get("expert_fallback_skill") == requested.get("fallback_skill")
                 and isinstance(requested.get("property_denominator"), int)
                 and isinstance(denominator, int)
                 and denominator >= requested["property_denominator"])
        status = results.get("expert_fallback_invocation_status")
        if status == "INVOKED" and results.get("expert_fallback_invoked") is True:
            try:
                receipt = json.loads((formal_dir / "formal_expert_review.json").read_text())
            except (OSError, ValueError):
                receipt = {}
            if not isinstance(receipt, dict):
                receipt = {}
            valid = (valid and receipt.get("invocation_status") == "INVOKED"
                     and receipt.get("fallback_skill", "formal-verify") == requested.get("fallback_skill")
                     and receipt.get("request_sha256") == snapshot["sha256"]
                     and results.get("expert_fallback_receipt") == str(
                         (formal_dir / "formal_expert_review.json").relative_to(project)))
            htext = "\n".join(p.read_text(errors="replace") for p in
                              _harness_files(project, formal_dir, results))
            closed = {r["id"] for r in _fhg._expert_closed_obligations(
                formal_dir, contract_rows, htext)}
            # A partial invocation remains a historical fact. A complete claim
            # still needs every original requested ID, never closure by omission.
            if not contract_incomplete:
                import formal_property_run as _fpr
                program_closed, _, _ = _fpr._verified_program_closures(formal_dir)
                ids = {r.get("id") for r in requested.get("unresolved_obligations", [])
                       if isinstance(r, dict)}
                valid = (valid and ids <= closed | set(program_closed) | set(by_binding)
                         and {r.get("id") for r in expert_rows} <= closed)
        elif status == "INVOKED_BY_PROGRAM" and results.get("expert_fallback_invoked") is True:
            import formal_property_run as _fpr
            closed, refuted, _ = _fpr._verified_program_closures(formal_dir)
            valid = (valid and bool(closed or refuted)
                     and results.get("expert_fallback_receipt") == str(
                         (formal_dir / _fpr.PROGRAM_RECEIPT).relative_to(project)))
        elif not contract_incomplete and expert_rows:
            valid = False
        if not valid:
            contract_ok = False
            rep["findings"].append(
                "EXPERT_AUTHORING_IDENTITY_INVALID (#3063): original request, role, "
                "receipt or executable dispositions do not support this invocation")
    if results.get("expert_fallback_required"):
        # R-0915-125. THIS NO LONGER FAILS THE CLAIM, and the reason is that a
        # FAIL is reserved for a proof that RAN and FAILED.
        #
        # What stood here asked whether an expert had been INVOKED, and made the
        # answer a contract violation. In a headless, program-only front-door run
        # nobody invokes `/formal-verify`, so `expert_fallback_invoked` is False
        # on every run and this clause could never be satisfied -- the gate was
        # unpassable by construction, not by evidence. MEASURED on spm run13 AND
        # run8 (8HD-4, `_lane_icspm5`), both digital DIEs, identically:
        #
        #     expert_fallback_required = True
        #     expert_fallback_invoked  = False
        #     expert_fallback_receipt  = None
        #     5 request obligation(s) against a denominator of 6
        #
        # "nobody invoked the skill" is a fact about THE RUNNER'S OPERATOR, not
        # about the design, and it must never become a design verdict.
        #
        # The obligations do not disappear: they are already carried as
        # `unresolved_obligations`, which drives `contract_incomplete` ->
        # INCOMPLETE below and is REPORTED WITH ITS IDS. An unresolved obligation
        # keeps the claim from being COMPLETE; it does not make it FAILED.
        receipt_rel = results.get("expert_fallback_receipt")
        receipt_path = project / receipt_rel if isinstance(receipt_rel, str) else None
        status = str(results.get("expert_fallback_invocation_status") or "").upper()
        if receipt_path is not None and receipt_path.is_file():
            # A receipt that EXISTS is still held to its contract. Two
            # invocation statuses are accepted and they are kept DISTINCT on
            # purpose (R-0915-125(a)): `INVOKED` is a human/skill answer and
            # `INVOKED_BY_PROGRAM` is one the runner discharged itself. An AI
            # answer and a program answer must never be indistinguishable in
            # the record, so this reads the status rather than collapsing both
            # into the boolean.
            if status and status not in ("INVOKED", "INVOKED_BY_PROGRAM"):
                contract_ok = False
                rep["findings"].append(
                    f"EXPERT_RECEIPT_STATUS_UNKNOWN (R-0915-125): the expert "
                    f"receipt exists but records invocation_status "
                    f"{status!r}, which is neither INVOKED nor "
                    f"INVOKED_BY_PROGRAM")
        else:
            # NO receipt. Enumeration only (R-0915-125(b)): the ids stay
            # visible and keep blocking their own layer; nothing is re-routed
            # and nothing is laundered into a pass.
            outstanding = [
                str(row.get("id", "?"))
                for row in (results.get("unresolved_obligations") or [])
                if isinstance(row, dict)]
            rep.setdefault("expert_fallback_outstanding", outstanding)
            rep["findings"].append(
                "EXPERT_FALLBACK_OUTSTANDING (R-0915-125): the deterministic "
                "floor requested formal authoring and no expert receipt is "
                "present. This is NOT a failed proof — it is work not yet "
                "done, and it is reported by id rather than as a verdict: "
                + (", ".join(outstanding) if outstanding else "(none enumerated)"))

    # (c) evidence pointer dereferences (path-shaped only, #433 convention) -
    ev_ok = True
    ev = results.get("evidence")
    if isinstance(ev, str) and "/" in ev:
        tgt = project / ev
        if not tgt.is_file() or tgt.stat().st_size == 0:
            ev_ok = False
            rep["findings"].append(
                f"EVIDENCE_MISSING (#448): results.json evidence "
                f"'{ev}' does not exist or is empty")

    if sby_ok and log_ok and ev_ok and contract_ok:
        if contract_incomplete:
            unresolved = results.get("unresolved_obligations") or []
            ids = [str(row.get("id", "?")) for row in unresolved
                   if isinstance(row, dict)]
            rep.update(verdict="INCOMPLETE", rc=0,
                       property_denominator=denominator,
                       unresolved_obligations=unresolved,
                       fallback_skill="formal-verify")
            rep["findings"].append(
                "PROOF_CHAIN_PARTIAL (#1974): authored properties have an "
                "elaborated .sby + PASS transcript, but the declaration "
                f"denominator remains open: {', '.join(ids)}")
        else:
            rep.update(verdict="PASS", rc=0,
                       property_denominator=denominator)
            rep["findings"].append(
                "PROOF_CHAIN_OK: all_proved substantiated by an "
                "elaboratable .sby + SymbiYosys PASS transcript; property "
                f"denominator {denominator}/{denominator} closed with "
                "bounded/unbounded scope disclosed"
                + (f" ({len(by_binding)} by binding, R-0924-2 — not trace proofs)"
                   if by_binding else ""))
    else:
        rep.update(verdict="FAIL", rc=1)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1
    rep = audit(args.project_dir.resolve())
    rc = rep.pop("rc")
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    if rep.get("verdict") == "INCOMPLETE":
        print("INCOMPLETE: applicable formal declaration/property work remains")
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
