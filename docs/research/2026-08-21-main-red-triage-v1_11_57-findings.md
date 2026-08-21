# findings — agent `ptmo`, RUN 7: re-triage against v1.11.57

host 8hd-3 · 2026-08-21

## M0 — batch 4 landed; premise verified before use

```
git ls-remote origin refs/heads/main
  e4c5840d6f8ea75b9fa178bc943a0921d6159f3b
  e4c5840d6 ppa(runner): the power session links what its header claims, and the
            sign-off STA reports say what stage they are [v1.11.57]
plugin.json -> 1.11.57      6 commits since v1.11.51
```

Batch 4 in full:

```
e4c5840d6 [v1.11.57] the power session links what its header claims
88744ae35 [v1.11.56] matrix D9: a step verdict that stops nothing is a ninth way a cell can be unhealthy
7836956be [v1.11.55] ppa(search): a stub stops publishing an excuse as a verdict
38e481445 [v1.11.54] docs(triage): main's reds re-measured against v1.11.47   <- my run 5
3f5473a1b [v1.11.53] ppa(records): producers and consumer agree on the shape
89712cf64 [v1.11.52] 63x8: the rest of the matrix family
```

`88744ae35` is jm9's ninth dimension, and its subject is the exact question this
thread has been arguing: **a step verdict that stops nothing**.

## M1 — ITEM (2): I MIS-LOCATED THE FIX, and the correction matters

Last round I told the operator the fix would land in
`programs/_ppa/power.py:153`, where `_NETLIST_RE` parses a `# netlist:` report
header — "exactly where a header claiming post-PnR over a pre-PnR file would
originate". **That was a guess dressed as a location and it is wrong.**

`e4c5840d6` does not touch `_ppa/power.py` at all. The fix is in
`programs/phase3_one_shot_runner.py` (+364 lines):

```
- def _emit_power_report(project, top, pdk, container, power_rpt, notes):
+ def _emit_power_report(project, top, pdk, container, power_rpt, notes, basis="pre_pnr"):
+     # `basis="post_pnr"`: this is the SIGN-OFF power number, so the session
+     # links the ROUTED netlist + the extracted SPEF.
- ok = _emit_power_report(project, top, pdk, container, power_rpt, notes)
+ ok = _emit_power_report(project, top, pdk, container, power_rpt, notes, basis="post_pnr")
+ # BASIS STAMP — DERIVED from the netlist this call actually linked, never a[sserted]
+ f'puts $_f "STA_BASIS_NETLIST: {netlist.name}"'
```

with two new tests, `test_phase3_power_signoff_links_the_routed_netlist.py` (324
lines) and `test_multicorner_signoff_reports_declare_their_stage.py` (249).

The shape of the repair is worth noting because it is the same doctrine as the
rest of this thread: **the basis stamp is DERIVED from the netlist actually
linked, never asserted** — a header can no longer claim a stage the file does
not have.

## M2 — ITEM (2), THE RE-READ: the two flagged reds are NOT explained by it

I flagged `test_d3_required_outputs_are_produced[step19]` (CTS) and `[step20]`
(Post-CTS hold fixing) for re-reading, and deliberately did not count them as
explained. Measured against the fix now that it is in the tree:

```
occurrences of "post_cts" in the whole of e4c5840d6   -> 0
flow yaml / matrix / d3 files in the commit           -> none (only matrix_63x8/README.md, 13 lines)
```

Their failure is *"1 declared output(s) cite a run root NO corpus can supply"*
about `phase3/stage3/pnr/post_cts.def` — a matrix-D3 declared-output/run-root
question. The v1.11.57 fix changes which netlist the POWER session links and
what the STA reports stamp. **Different concern; the flag is cleared, not
converted into an explanation.** Both remain counted on their own merits by the
v1.11.57 run.

## M3 — RESULT AT v1.11.57: 97/97, the current red list is 25

```
   GREEN-BOTH    70     closed
   BOTH          22     real about main, red in BOTH lanes
   IMAGE-ONLY     3     test_pad_and_seal_ring_on_the_chip_path (x3)
   HOST-ONLY      0     <- CLOSED by batch 4
   FLAKY-KNOWN    2
   NOT_MEASURED   0
```

**The current red list is 25 IDs** (22 BOTH + 3 IMAGE-ONLY), from 31 at v1.11.51.

### ITEM (1), and it needs two clauses, not one zero

* **HOST-ONLY is back to 0.**
  `test_matrix_63x8_coverage::test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress`
  was host-only at v1.11.47 (6/6 vs 0/6 interleaved) and at v1.11.51. Batch 4's
  matrix work closed it. **Nothing on the other agents' list is a host artefact
  — that verdict holds, and it is now measured five times.**
* **IMAGE-ONLY is still 3**, the same three seal-ring IDs, now on a THIRD tree.
  Batch 4 did not close them. The standing exception is the REVERSE of a
  phantom: three defects the image catches that a host without a PDK
  structurally cannot reach, because the failing branch is only entered when a
  PDK is present.

### ITEM (2), the re-read: COMPLETE AND NEGATIVE

`d3[step19]` and `d3[step20]` are still BOTH-red at v1.11.57 with unchanged
messages. Measured against the fix now that it is in the tree:

```
occurrences of "post_cts" in the whole of e4c5840d6   -> 0
flow yaml / matrix / d3 files in the commit           -> none
```

They fail on *"1 declared output(s) cite a run root NO corpus can supply"* for
`phase3/stage3/pnr/post_cts.def` — a matrix-D3 declared-output/run-root
question. The v1.11.57 fix changes which netlist the POWER session links and
what the STA reports stamp. **Flag cleared, not converted into an explanation.**
Both stay counted on their own merits.

### The 22 BOTH, grouped

```
 6  test_d3_required_outputs_are_produced[step15/17/19/20/30/32]  declared outputs not produced
 3  test_issue901_*                                               vacuity tier granted without its count
 3  test_matrix_mutation_ledger  (incl. [step1.6x] and the coverage count)
 2  test_flow_manifest_declaration_parity                         flow yaml vs evidence manifest
 2  test_matrix_63x8_coverage                                     NA precondition; enforced-while-red
 2  test_v0_2_96_issue460_coverage_bridge                          e2e oracle vs coverage
 1  each: flow_compliance_check_gate, issue306_register_paydown,
        issue490_drc_report_check_argv, organic900_901_ratchet
```

The `1.6x` remainder I named last round is still exactly right and still open:
`matrix_mutation_ledger` has no named mutation for step `1.6x`, so its coverage
count is short by one. Two of the 22.
