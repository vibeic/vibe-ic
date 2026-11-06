# CUT_W2 item 2: shared native extraction authority

The chip path defaults step 22 to `librelane`. Step 22 and the step-32
candidate chain use `OpenROAD.RCX`, with its declared PDK rulesets and
`-lef_res`. Each chain extracts its own route basis. Step 32 precedes the
post-tail step-22 publication and cannot consume a future step-22 result.

Step 32 passes the RCX state and its digest to the retained signoff-scene STA
consumer. That consumer checks the input route, declared scene patterns,
producer-owned SPEF paths, capacitance and coupling, and reads those exact
SPEFs. It does not run another extraction. Step 22 applies the same route
technology overlay and output checks before publication. RCX reuse includes
the mounted ruleset and physical LEF bytes; a PDK change during the native
run refuses the receipt. Existing extraction and provenance gates still judge
the published artifacts.

The producer receipt now binds the extraction-time route and current output
bytes at cache reuse, shared binding, direct handoff and publication. Missing
receipt hashes refuse reuse; current aliases cannot conceal changed DEF/ODB
bytes. Publication checks all declared runtime STA scenes, the complete
rules-owned SPEF population, unique RC aliases and the producing design top.
Every adopted census number and capacitance/resistance row must be finite;
finite totals cannot excuse a NaN row.

## Harvest and retained gaps

No legacy extractor or STA code is deleted in this change.

| Obligation | Destination and status |
|---|---|
| Extraction before `write_spef` | Existing native `OpenROAD.RCX` implementation. |
| Declared rulesets, per-corner technology | Native resolver/RCX, with the route's existing digest-bound via-legalization overlay when applied. |
| Current PDK input identity and output ownership | RCX input fingerprint and shared `bind_rcx_spefs` audit; this feature awaits review/merge. |
| Coupled output on a PDK with rules | Native OpenRCX SPEF, audited before use; no analytical augmentation on this path. |
| Rule-less PDK LEF-RC fallback | **GAP_RCX_RULELESS**: native adapter refuses `LL_RCX_RULESETS_UNDECLARED`; legacy direct entry remains available through explicit mode selection. No automatic substitution. |
| Rule-less analytical coupling and optional field-solver accuracy arm | Existing direct/opt-in sources retained. Their custom-step/native destinations have not merged in this item. |
| AOCV-or-flat ordering, derate validation, serialized-SDC normalization | **SIGNOFF_SCENE_STA_HARVEST_PENDING_MERGE**: retained `_native_postroute_timing` STA consumes the native RCX SPEFs. A merged native corner configuration/custom step is required before removing this consumer. |
| All declared process/RC scenes and missing-scene refusal | Retained STA consumer and existing STAPostPNR completeness checks. |
| Standalone and tool STA diagnostics | Both native measurements remain recorded. The retained scene STA is still the controller's acceptance measurement. |
| SI coupling retention, path-SPICE RC network, per-corner SDF | Native coupled artifacts are preserved for those downstream consumers. Their migrations are outside item 2. |

The retained legacy extraction entry is an explicit compatibility arm. The
production step-32 caller always supplies the shared native RCX state.
Missing, ambiguous, stale or grounded-only native output is refused rather
than replaced with that legacy extraction.

## Bounded proof

The proof is pinned to official `ghcr.io/vibeic/vibeic-eda:0.3.87`, amd64
manifest `sha256:cf3c57c1a9ab05e352a1bc37e083c235f85e9d645b35f399de1f73c75a5c74f1`,
image `sha256:32cce4e448a53521c1bb94b16fada12d30b94674c03fd8bec40edaa96d9d515c`.
It compares the existing direct extraction settings with native RCX on one
retained SPM route, then runs the changed consumer on native RCX SPEFs at all
nine declared scenes. Containers use the existing supervised wrapper,
`--skip` first, 8 CPUs, 16 GiB RAM and no swap budget. Source is mounted read-only.

The native capacitance totals agree for all three RC corners. The native
resistor networks differ; resistor-entry sums are diagnostic values, not an
effective end-to-end resistance or a timing model. Actual STA measures the
timing effect. The proof publishes the same native producer's SPEFs through
the step-22 publication consumer without repeating extraction.

This retained route is distinct from the original CUT_W2 `cut_23` route.
That original `max_ss_125C_4v50` hold failure, **-0.0397 ns at three endpoints**,
remains unchanged and unwaived. Positive slack on this proof route does not
close that finding. This item runs no repair actuator or full IC flow.

Raw source controls, mutations, tool argv, admissions, PID/CID/rc records,
native artifacts and hashes are retained in the validation workspace under
`evidence/` and `native/`. Its result record is `result.json`.

## Original first-pair source repair

The original correctness and integrity reviews found five source gaps after
the native proof at `bee09d713467754548ed7d41e133f751e2829251`. Their unchanged
C19 and I25 source controls are reproduced on that commit, then rerun against
the producer/consumer guards above. A concrete NaN-ground-row control retains
finite 4 pF net totals and 1 pF coupling while requiring refusal. Reversing the
guards must restore the original invalid acceptances. The original author
value obligations and frozen nine-scene native producer bytes remain usable.

This continuation launches no native tools and establishes source contracts
only. The earlier native proof and original SS hold failure remain immutable;
fresh numerical accuracy, physical signoff and shipping receive no credit.
The exact repair receipt is
`repair/result.json`.
Root sends that source to the same original reviewers for bounded closure.

Historical evidence locators in this document are relative to the original
operator workspace. They identify retained artifacts; they are not runtime
paths on an installation. Original artifact SHA256 values and evidence remain
unchanged.
