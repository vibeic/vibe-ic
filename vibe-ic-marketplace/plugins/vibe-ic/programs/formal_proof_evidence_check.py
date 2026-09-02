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

sys.path.insert(0, str(Path(__file__).parent))
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
            rep.update(verdict="SKIPPED-CONDITION", rc=2)
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
        rep.update(verdict="SKIPPED-CONDITION", rc=2)
        rep["findings"].append(
            "SELF_REPORTED_SKIP: results.json honestly reports no proof "
            "ran (#440 manifest shape) — vacuous for this gate")
        return rep

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
            and (not isinstance(authored, int) or authored < denominator)):
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
    if results.get("expert_fallback_required"):
        receipt_rel = results.get("expert_fallback_receipt")
        receipt_path = project / receipt_rel if isinstance(receipt_rel, str) else None
        if (results.get("expert_fallback_invoked") is not True
                or receipt_path is None or not receipt_path.is_file()):
            contract_ok = False
            rep["findings"].append(
                "EXPERT_FALLBACK_NOT_INVOKED (#1974): the deterministic floor "
                "requested formal-verify, but the completed claim has no "
                "dereferenceable INVOKED expert receipt")

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
                "bounded/unbounded scope disclosed")
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
