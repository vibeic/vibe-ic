# Native PPA exploration

`programs/flow_explore.py` runs the public entry on isolated project copies and
adopts the selected native overrides. Native artifacts remain in the selected
copy. `results.json` records the level, its source, every proposal/result, native
metrics, objective components, elapsed time and selected project.

```sh
python3 programs/flow_explore.py /path/project --output /path/exploration \
  --ppa-level 1 --cpus 8 --jobs 2 -- --route ip
```

CLI `--ppa-level` overrides document `PPA_LEVEL`; the explorer defaults to 2.
Level 0 executes the reference once. Level 1 proposes seven high-value native
configurations, including the reference: minimum-drive exclusion, power recovery,
resizer maximum utilization, and candidate cell area/leakage sizing limits.
Document-pinned settings are removed from the proposal space. Identical remaining
overrides are deduplicated, so a constrained design can have fewer candidates.

Level 2 samples up to24 effective native combinations using private seed42,
porting the old baseline-first Cartesian proposal policy with bounded index
sampling. It adds total-site global/detailed padding, native density targets,
timing/routability-driven placement, global/per-layer route adjustment and active
PL/GRT resizer settings. CTS cluster size/diameter are sampled when the reference
native log shows preclustering actually ran; a clustering announcement alone
does not establish this. The report names skipped/inactive axes. Padding aliases
and global/per-layer route aliases are deduplicated by their native effect.
Document density aliases pin the canonical density target. Native ORFS's density
addon is used by Stage A; LibreLane consumes its native density-target setting.
Execution stays local within the CPU budget by default. The optional
`--spool OUTPUT RESULTS` publishes self-contained jobs through the caller's
job-folder spool. Each folder contains `job.json` and `run.sh`; the worker writes
its native `exit-code.txt` after collecting the native project under `reports/`.
The adapter reads native reports and preserves failed results. It removes its
own published job copy after collection; returned evidence stays in RESULTS.
Container scratch comes from the job environment, with `VIBEIC_TMP` set to the
mounted scratch root. The adapter contains no host inventory or dispatcher.
Levels 3 and 4 require the native-tool result handoff and are not implemented by
this knob enumerator. Level 3 belongs to the unchanged native tools; Level 4
enhances their best all-PASS result. This change adds no independent search engine.

Reference execution precedes the other proposals. Subsequent runs occupy
disjoint CPU affinity groups; each group runs only one child at a time. The
8-CPU total budget is shared between at most two children. With a spool, the
same CPU count is declared per job and concurrency belongs to the external
dispatcher. Every proposal invokes the ordinary public entry with the same
forwarded route/window arguments. Reports include each child's kernel CPU time
and wall time; spool waiting/packaging is visible in total exploration wall time.

Only an all-PASS result with comparable native PPA can win. The objective retains
raw area, power and slack, and computes percentage improvement against the
reference. Performance uses ORFS's clipped effective period
`clock_period - min(setup_ws, 0)`. Our area term uses native instance area,
including physical fill when present; it does not use ORFS's utilization
complement. Final native violations and failed rows add penalties. Intermediate
router DRC iterations are not final penalties. Native failure remains ineligible.

Document `PPA_PERFORMANCE_WEIGHT`, `PPA_POWER_WEIGHT` and `PPA_AREA_WEIGHT`, or
L19 `fields.ppa_weights`, supply weights. Missing preferences inherit ORFS
PPAImprov's performance:power:area ratio10000:100:100, reported per axis as
"inherited, not chosen". The score is explicitly adapted to actual native area;
it is not described as an unchanged ORFS score. Missing numbers or comparison
basis produce NOT_MEASURED, never a measured zero. Losses remain in the report.

The new post-route controls are optional:

| Setting | Native operation |
|---|---|
| `VIBEIC_PRR_RECOVER_POWER_PCT` | Separate `repair_timing -recover_power` before ordinary setup and hold repair |
| `VIBEIC_PRR_MAX_UTIL_PCT` | `-max_utilization` on each recovery/setup/hold call |
| `VIBEIC_PRR_LIMIT_SIZING_AREA` | `set_opt_config -limit_sizing_area` candidate/current cell-area ratio |
| `VIBEIC_PRR_LIMIT_SIZING_LEAKAGE` | `set_opt_config -limit_sizing_leakage` candidate/current cell-leakage ratio |

Unset controls preserve native behavior. Native recovery percentage0 still
attempts at least one eligible endpoint; omission is the disabled state. Native
sizing ratios default to4.0 and can also be inherited from the input ODB. They
filter candidate cells, not document area or power limits. PL setup/hold maximum
utilization variables use LibreLane's existing post-CTS consumer. Forwarded but
inert hold-TNS and setup-buffer-percent options are not counted as search axes.

Recovery retains setup/hold, legalization, native routing and final
verification sequence. An emitted command or successful native return is not
evidence of a measured improvement; the complete public result decides adoption.
