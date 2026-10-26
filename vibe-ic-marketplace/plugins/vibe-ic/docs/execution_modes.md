# Execution modes: canonical Default routing and Ultra qualification

The execution policy has two deliberately separate paths. User/operator flow
instructions bind them through the Flow109 public entry and stable IDs in
`flow/flow109.json`:

* **Default mode** is program-first. The caller owns the one canonical producer
  for the row and its declared gates. The policy seam returns to that caller;
  it does not run a candidate arm, wait for an AI choice, or adopt a receipt.
  One local driver runs all phases in the same project directory. The normal
  Default CLI starts directly, without an execution-authority supervisor,
  capability socket, copied worker project, or candidate source snapshot.
  D22/34 synthesis input preparation and D31/51 floorplan publication are
  typed producer preparation and still do not call `Controller.run` or
  `adopt`.
* **Ultra mode** is the qualification path. It may run the registered candidate
  arms through `Controller`, preserve isolated receipts, and let AI adopt an
  eligible result. Ultra evidence never changes the Default producer contract.

The public Default form is:

```bash
python3 programs/vibe_ic_one_shot_runner.py PROJECT --route ic \
  --flow 109 --flow109-manifest MANIFEST.json \
  --entry-step D09 --exit-step D09 --execution-mode default
```

Both window endpoints are current Flow109 IDs, never positions and never former
step numbers. The registry records D09/17, D11/19, D13/21, D22/34, D23/35,
D30/42 and D50/72. Position is display/audit metadata only. A row without a
registered dispatch refuses rather than entering another producer.

Default uses each canonical producer's declared inputs, native outputs and
existing quality gates in place. A failed design gate still stops progression;
removing candidate transport does not turn a failed or unmeasured IC into PASS.
Ultra uses the same resolved dependency manifest for copied input preparation,
worker preflight and downstream consumption. This routing completion does not
claim that either benchmark IC has passed.

The public portfolio is `programs/data/execution_modes_portfolio.json`. It imports
the historical source/policy inventory bound to main
`f88175263d96c3a76b4cb18f72c7714c68ec6627`, inventory SHA256
`d364f39fc37b77f5ba711cea7cab879345de56c157784cf847a66108ebc518bc`:
70 canonical step IDs, 63 tools, 333 arm descriptions. Private receipt paths and
Chinese fields are omitted. Public capability links and historical source
integration do not establish present installation, a license seat or an executable
controller adapter. Every arm says `controller_runnable: false`. Licensed
candidates explicitly require both a license and a completed adapter.

`current_default` describes the pinned existing source; `policy_default` describes
the policy target and retains its deployment limitations. The `meta.default_mode`
record is the static 70-row routing contract, not a whole-flow verdict. A9 keeps its native
L22-selected ngspice / `d_cosim` primary with Icarus libvvp. A2 retains explicit
topology choice, A3 retains the own netlist producer with ngspice validation, and
A4 retains its current ngspice sweep. PyOPUS, Xschem, CACE and SpiceBind remain
proposals pending same-input target proof. The resource changes no producer.

## Policy API

`mode(None)` returns `default-mode`. Only the exact strings `default-mode` and
`ultra-mode` are accepted; invalid strings refuse. Native `direct`, `librelane`
and `dual` are separate implementation identities supplied in `Context`; they
are never interpreted as aliases for execution policy. An ambiguous native
identity refuses. Existing switches and class defaults remain with
`librelane_contract.selected_mode`.

An owning source adapter declares applicability, availability, qualification,
the exact tool version and source/binary file digests, engine families, an
ordered component command list, required output files, canonical-output
mappings and an actual output consumer. Registration verifies the source and
executable bindings. A portfolio description alone cannot register an executor.
Adapters and validators are trusted reviewed implementation code, not commands
loaded from a public JSON file or a security boundary against hostile programs.

The standalone qualification API
`Controller.plan(context, execution_mode, superiority)` selects one applicable,
available, qualified primary in default mode: LibreLane, then OpenROAD, then
another qualified tool. Own code needs an explicit scoped no-applicable-tool
reason; an external adapter that is unavailable, unresolved or failed cannot
justify own fallback. There is no automatic rerun/fallback after a process error.
Ranking can be overridden only with complete eligible measured receipts bound
to the same input digests, source SHA, exact adapter/binary versions and declared
objective/metric/direction. The output validator is reconsumed for both arms.
Canonical required gates cannot be dropped; each ready arm must map every
canonical output contract to its required files. Glob/alternative resolution is
the source adapter's responsibility and needs executable producer evidence.

Ultra mode runs declared available useful independent producer arms through a
bounded weighted scheduler. Shared engine families are disclosed and excluded
as independent candidates, including an orchestrator using the same backend as
a direct tool. Complementary/checker roles stay outside candidate selection;
their obligations remain mandatory gates. CPU affinity and RAM address-space
limits bound each component; CPU/RAM reservations and license seats bound
concurrent admission. Components within an arm run in order. Each arm receives
its own copied inputs and output directory. Frozen and current input hashes are
checked before execution, between components and again at selection.

`Controller.run` writes the full portfolio, adapter admissions, objective,
budget and frozen binding in `plan.json`. Each arm writes `receipt.json` with
actual PID/argv/rc, monotonic process intervals, stdout/stderr and digests,
source/version identity, output digests and consumed gate evidence. Timeout or
explicit cancellation kills only the controller's component process group and
reaps it; partial logs/files remain. These finite-component deadlines are not a
proposal to change existing EDA progress watchdog or native tool-stop policy.
Address-space limits are per process, not a cgroup aggregate RSS limit; production
container/process-tree memory and license leases still require the owning runner.

The source run also issues `issued-plan.json` and an arm-local
`issued-completion.json` from the actual observed process completion. Its live
process keeps a separate immutable serialized transcript and signing key outside
the editable run directory. Adoption verifies both issuance and the process
transcript; replacing receipt rc/status/evidence and selecting its new digest
cannot upgrade a real nonzero execution. A signature alone cannot fabricate
source issuance. The original plan, native rc, logs and output proof remain
auditable. Gate evidence is still independently consumed: an issued rc0 grants
no design PASS, and measured FAIL retains precedence over NOT_MEASURED gates.

This issuer is scoped to one interpreter lifetime and source-owned trusted code.
Another controller in that process can consume the same issued run; restarting
the interpreter loses authority and fails closed. Persistent external supervisor
authority and cross-process key/lease management are unimplemented. These
process transcripts do not claim protection against arbitrary hostile Python
code executing inside the issuer process.

Process rc0 and file existence never establish eligibility. Actual measured
`FAIL` gates yield `FAIL`; missing/failed execution, stale/unbound evidence and
`NOT_MEASURED` gates stay `NOT_MEASURED`. No run automatically selects an arm:
`result.json` reports `AWAITING_AI_SELECTION`. The AI supplies `arm_id`, the
current binding, exact receipt digest, reviewer identity and rationale to
`Controller.adopt`. Missing choice, changed inputs/outputs, incomplete gates,
unmeasured candidates, wrong source or changed tool identity refuse. Adoption
reconsumes the actual output validator and persists `adoption.json`; it records
adoption without publishing into the project's native outputs. The ordinary
Ultra dispatcher then owns native import and continuation; an isolated
`Controller.adopt` call alone does not perform that import.

Adoption also checks the currently relevant applicability, qualification,
availability, license-seat/resource declarations and selection policy against
the source-issued original run. These are declared controller admission checks,
not proof of an actual production license lease. The same checks, source/current
input/frozen input/output hashes and issued completion are checked again after
the source validator returns. A validator may pause; its earlier hashes cannot
authorize bytes another thread changed during validation.

The exact validated artifacts are copied into a unique `selected/<generation>`
directory, with a source-issued manifest binding run, arm, inputs and output
digests. The generation and relevant current identities are checked before the
atomic adoption record is committed. `selected_generation` identifies those
captured bytes, rather than leaving the record pointed at mutable candidate
outputs. Read-only files plus issued hashes expose later disk changes; they are
not a host security sandbox. Any future native import must consume the exact
generation and verify its manifest/digests. The ordinary
`execution_policy.dispatch_fixed_step` uses `execution_production.import_selected`
for Step 9, a journal for the other ordinary selected outputs, and the existing
analog consumer for A6-A8. Their success remains a separate per-invocation
obligation.

Arm IDs reject dot traversal and the controller-reserved plan/result/adoption,
refusal, issued-plan and selected-generation names. Legitimate names such as
`neutral.a` keep their existing output layout. Unavailable output directories or
adoption records return named finite refusals, rather than raw filesystem errors.

## Integration boundary and remaining work

The normal Default CLI does not call this standalone planning API; its canonical
caller executes the configured producer directly.

The canonical runners now select the execution policy at their existing front
door. Default rows continue through their source-owned producer and gate
functions. Ultra rows build a `Context` from the current frozen project inputs,
objective, canonical gates, and output contract; the source-owned adapter freezes
the transitive tool/PDK/config inputs and binds the deployed image and license
probe before `Controller.run`.

The policy change is a routing completion, not an EDA qualification claim. The
following remain per invocation or outside the Default routing contract:

* native tool availability, exact image/PDK provenance, and licensed seats;
* actual synthesis, P&R, signoff, and physical evidence for a design;
* Ultra candidate qualification, AI adoption, and native selected-output import;
* external or unavailable rows whose producer is an attested handoff rather than
  a local executable.

Every consumer must propagate a producer or gate refusal before advancing. A
component receipt, a source wiring check, or a direct LibreLane/OpenROAD run is
not a whole IC PASS.

This repair updates the existing front door, Phase-1/2/3 runners and
`librelane_contract.py`; it does not replace the canonical flow YAML or
`CAPTURE_ROUTING.json` with a new flow.

### Default Step 8 ordering

In native `direct` mode, Phase 2 runs the existing SDC syntax and L8 contract
checks immediately and requires their newly written, nonempty reports. In
`librelane` or `dual` mode, the early Step-8 observation is deferred until the
mapped synthesis output exists. Phase 2 then calls the existing pre-layout
producer and its post-pre-layout SDC consumer before its own audit. This closes
the former cycle in which the Phase-2 audit required evidence that only the
later Phase-3 caller could produce. A failed or unmeasured producer retains
that verdict. A resumed window outside Step 8 does not repeat this work.

## Acceptance scope

The source-family census covers the 70 canonical rows: 20 frontend/Step 9,
23 backend, 14 release, three analog physical/hardmacro, six analog-front and
four mixed-signal rows. Six release entries describe external or unavailable
producers; the remaining 64 are source-backed software implementations. These
counts do not establish installed tool availability, native qualification or
70 passing design steps. A public catalog of 333 arm descriptions is not a
requirement to install every described or licensed arm.

The retained SPM/GF180 acceptance is 43 applicable contract rows on source
1.29.75, including its five typed partial disclosures, plus the separately
accepted source86 technical engineering release. New source or component
audits do not erase those records or convert their limits into a new PASS.
Analog A1-A9, mixed M1-M4 and the IP delivery row apply only to their declared
paths. FPGA rows 6/39 retain the existing conditional hardware policy;
manufacturing rows 40-44 are recorded as later service work and are outside
the pre-tapeout design acceptance goal. Whole-Ultra qualification remains
separate from Default and from a successful two-simulator component case.

`programs/tests/test_default_mode_routing_contract.py` loads the canonical YAML
and portfolio, checks all 70 IDs and source bindings, and proves that every
Default fixed-row dispatch returns to the caller while `Controller.run` and
`Controller.adopt` are guarded. The focused pinned-container suite also covers
the shared manifest, producer ownership, Step 7/9/15 wiring, and the direct
0.5ic gates.

`programs/tests/test_execution_modes.py` runs real finite subprocesses with an
explicit neutral text contract, not mocked EDA engines or fake production
adapters. It exercises concurrent intervals, serial resource admission,
isolated frozen inputs, ordered dependent components, actual rc, cancellation,
partial output, current source/digest checks and eligible-only selection.
A real-repository artifact test consumes the pinned canonical YAML and public
portfolio, preserves all 70 IDs, checks final A9 policy and rejects the empty
production registry. Reverse source mutations test the substantive evidence
guards separately. These tests establish routing and evidence contracts; they do
not prove an IC tape-out.

The initial review's two hash-bound original proof scripts are rerun unchanged
against the original reviewed source and the repair: 14 original negative
failures and 11 adjacent positives become 25 passing controls. They cover actual
rc7 receipt rewrites, currently withdrawn admission, four event-synchronized
validation races and five colliding arm names. The original 53 author assertions
and fixture bytes remain unchanged. Appended source controls additionally
challenge fabricated issuance, current resource/policy changes and the exact
committed artifact generation. These are neutral subprocess/controller proofs,
not additional EDA adapters or production rollout evidence.

## Layer Contract Decision — execution policy and portfolio

Producing layer: n/a — execution policy, environment availability and tool
portfolio are runner properties, not design facts in L1-L27.

Consuming layer: n/a — the canonical Default runners consume the mode and run
their source-owned producers; the Ultra controller consumes frozen inputs,
adapter registry and candidate evidence.

Consumer program: `programs/execution_policy.py` for live routing and
`programs/execution_modes.py` (`mode`, `Controller.plan`, `Controller.run`,
`Controller.adopt`) for Ultra candidate execution.

Boundary class: structural — two enumerable policies, explicit executable
adapter contracts and binding checks. AI selection remains judgement over
eligible evidence; the program cannot author the choice or design objective.

Declarative alignment: n/a — this is not a register, interface or L-layer schema.

Actionable form required: exact mode token, current input/source/tool digests,
declared objective, output mapping, gate verdicts and receipt-bound AI rationale.

Bucket A (program): deterministic admission, execution and evidence binding;
the best-result judgement remains Bucket B (skill/AI).

evidence: `programs/tests/test_default_mode_routing_contract.py` exercises every
canonical row; `programs/tests/test_execution_modes.py` executes the Ultra
controller; `programs/librelane_contract.py` `selected_mode` preserves the
separate native implementation switch.

**Verdict**: NOT_A_LAYER_FACT

Next: /vibe-ic-phase1 remains the unchanged design front door; runner owners
review the proposed hooks after independent source acceptance.
