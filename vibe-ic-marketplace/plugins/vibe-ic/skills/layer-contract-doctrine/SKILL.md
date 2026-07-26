---
name: layer-contract-doctrine
description: Read BEFORE authoring or revising an L-layer emitter, an L-layer schema field, or a layer gate. Answers the three questions no program can decide for you — WHICH of the 27 layers a given fact belongs in (the layer that CONSUMES it, not any layer that mentions it), WHETHER the thing you are specifying is structural (closed, enumerable, correct-by-construction, therefore a program) or behavioural (no unique correct implementation, therefore synthesis and not expansion), and WHETHER a declarative layer should align to IP-XACT / SystemRDL semantics instead of inventing schema. Produces a Layer Contract Decision record. Pairs with l_doc_consumer_contract.py and l_doc_symbolic_width_resolve.py.
tier: judgment
paired_program: l_doc_consumer_contract.py
---

# Layer Contract Doctrine

**Purpose.** The L1-L27 corpus is a layered intermediate representation:
natural language in, structured JSON through, RTL and back end out. Every gate
we own checks a layer against a contract. Nothing in the tree states what the
contract IS, so each author re-derives it, and each re-derivation is one more
chance to put a fact in a layer that nothing downstream reads.

This skill is that statement. It is deliberately short on things a program can
check and long on the three judgements a program cannot make.

Chip-AGNOSTIC: every rule below is a property of the layering, not of any
design, PDK, vendor or part number. The measured evidence names L-doc fields,
program files and line numbers — never a customer part.

---

## 1. Why the layers exist

The 27 layers are not a filing cabinet. They are **refinement**, in the
Gajski-Kuhn sense (Y-chart, IEEE Computer 16(12), 1983): a design is modelled
across behavioural / structural / physical domains at descending abstraction
levels, and the flow is stepwise refinement down the levels with
transformation across domains at a level. The load-bearing consequence:

> **Each layer's output is the next layer's specification.**

That single sentence decides most layer-assignment arguments. A fact belongs
in the layer whose CONSUMER dereferences it, because that layer is the spec
the consumer is built against.

Two sibling traditions say the same thing from other directions, and are worth
knowing because they tell you what a layered IR is *for*:

* **ESL / executable golden model + formal equivalence.** spec -> executable
  C/C++/SystemC model -> RTL, with combinational (LEC), sequential (SEC) and
  transaction equivalence proving that each refinement step preserved
  behaviour. The strongest available guarantee — and note its boundary: the
  golden model's own fidelity to the natural-language spec is still human
  review. A layered IR is exactly the reviewable bridge across that gap.
* **MDA / MDE traceability.** CIM -> PIM -> PSM -> code, with bidirectional
  requirement->design->verification links (ReqIF, DOORS, and a compliance
  requirement under ISO 26262 / DO-254). Traceability is what makes
  change-impact answerable: *this spec line moved, which layers and which RTL
  are now stale?*

Assertion-based design is the third: SVA/PSL as the machine-executable form of
design intent, reusable in both simulation and formal. We already emit some of
this (`assertion_covers_l3_constraints_check`, `assertion_property_check`,
`protocol_timeline_assert_gen`, `formal_property_run`); we do not emit a
C/SystemC golden model, so sequential and transaction equivalence are not
available to us. Say so when someone claims the flow is "formally verified".

---

## 2. The consuming-layer rule

> **A value present in a producing layer but unresolvable by its consuming
> layer is a DEFECT — even when both layers pass their own gates
> individually.**

This is promoted here from a docstring on `programs/l_doc_consumer_contract.py`
(landed 5782025c7), where it was true, correct, and read by nobody before
authoring. Five measurements of our own, not literature:

1. **L21 supply pin — the post-mortem the rule comes from.** A hard macro's
   supply pin appeared 7x in `L1_DATASHEET` and 8x in `L2_FRS`, so the global
   completeness check reported CAPTURED. `L21_POWER_INTENT` — the layer the
   BACK END consumes — contained it 0 times. The PDN was built with no rail
   for it, synthesis tied the pin off, a SIGNAL net landed on a POWER
   terminal, and TritonRoute aborted the detailed route: **3278 nets, 0
   routed**, discovered five steps downstream.

2. **L1 parametric bus width — present, adjacent, and never joined.** The same
   L-doc corpus carries `parameters[] = [{"name": <P>, "default": "32"}]` and
   `pin_table[]` / `top_ports[] = [{"width_symbolic": "<P>-1:0", "msb": null,
   "lsb": null}]`. `phase1_doc_one_shot_runner._parse_port_width` (line 2021)
   returns `(None, None, 0, "<P>-1:0")` and its docstring says the textual
   form is kept "so downstream consumers can resolve at elaboration time" — no
   consumer did. The sharpest form: the string
   ``"N-bit(`[<P>-1:0]`, parameter `<P>` default 32)"`` goes IN and the
   default comes back OUT discarded. `l1_pin_bus_width_actionable_check.py:31`
   records the shape on ONE cell across **13 independent runs**. Phase2
   derives port declarations from that table, so the bus was emitted as a
   1-bit scalar.
   *Resolved by `programs/l_doc_symbolic_width_resolve.py`* — see §6.

3. **L19 die budget — a prose input the consumer cannot see.** An input
   document states a target die of 1500 x 1500 um; `L19_CONSTRAINTS_PDK`
   emits `"die_area_budget_um": null, "constraints_present": false`.
   `l19_pdk_floorplan_contract_check._design_fixed_die_mandates` derives a
   fixed-die mandate ONLY from `input/**/config.json` DIE_AREA and
   `input/**/*.tcl` DIE_AREA/FP_SIZING. A prose statement is not a source it
   reads, so the null still passes. Open gap; see §6 for where the fix goes.

4. **L19 PDK target — and the lesson about checking first.**
   `L19_CONSTRAINTS_PDK.json` carried a `pdk_target` while the back end had
   signed off on a different PDK, and nothing reconciled the two. The
   disclosure doctrine that should have caught it is analog-only and returns
   None when there is no analog directory. **This is now largely covered**:
   `l19_pdk_floorplan_contract_check.py` landed cb46a3f05 — L19-2 BLOCKS when
   a non-null `pdk_target` is not traceable to the design's own input corpus,
   L19-3 BLOCKS when the design stages a PDK enablement and `pdk_target` is
   null — and it landed AFTER the measurement. Residual: L19-2 checks
   traceability to INPUTS, not reconciliation against the PDK the back end
   actually consumed. Record measurements with their date, and re-check the
   tree before authoring against them.

5. **The class states itself.** `l22_verification_plan_measurable_check`
   produced this unprompted, and it is the cleanest statement of the rule we
   have:

   > "the design's own inputs state a MEASURABLE verification target in 1
   > input-doc location and 0 sibling-L-doc locations, but L22 — the layer a
   > coverage gate consumes — carries 0 measurable `coverage_goals[]`. The
   > target is present somewhere and absent from the layer that consumes it:
   > nothing downstream can compare a measured number against it."

**How to apply it when authoring.** Do not ask "did I capture the fact". Ask,
in this order:

1. Which program or step actually DEREFERENCES this fact? Name the file.
2. Which L-doc and which field does that consumer read? Name the key path.
3. Is the value in that field ACTIONABLE for that consumer — an integer where
   it needs an integer, an enumerable token where it switches on one — or is
   it prose that happens to contain the right characters?
4. If the answer to (1) is "nothing, yet", the fact does not need a layer
   field yet. A field no consumer reads is the same defect facing the other
   way.

---

## 3. The structural / behavioural boundary — and why it IS the ladder test

This is the most operationally useful section, because it decides Bucket
A vs Bucket B before you write anything.

**Structural** — registers, interfaces, connections, memory maps, hierarchy,
parameters, pinouts. These domains are **semantically closed and enumerable**:
there is a finite set of forms, each form maps to a UNIQUE RTL template, so
expansion is correct-by-construction. A structural fact can therefore be
handled by a **program**, and should be.

**Behavioural** — arbitrary datapath and control semantics. There is no unique
correct implementation of an arbitrary behaviour, so spec -> RTL is a
**synthesis** problem, not an expansion problem. No program can be written
that is correct-by-construction over it.

This is why the formal standards stop exactly where they stop, and it is not
an oversight — it is a stated exclusion:

| Standard | Covers | Deliberately excludes |
|---|---|---|
| IP-XACT (IEEE 1685-2022) | ports, bus interfaces, register/memory maps, hierarchy connections, parameters, power domains | behaviour — "IP-XACT does not handle module implementations" |
| SystemRDL 2.0 (Accellera) | register semantics (w1c, counter, interrupt) -> RTL + UVM + docs + C header | arbitrary FSM / datapath behaviour |
| PSS 3.0 (Accellera) | behavioural scenarios | produces TESTS, not synthesizable RTL |

The industry's answer for behaviour is HLS (C/C++/SystemC -> RTL), not another
declarative standard. Register-map -> RTL is the one spec-to-RTL domain that
is fully mature, and it is mature precisely because it is closed.

**Operational rule.** A behavioural layer stays deterministic only if its
semantics are confined to a **finite closed vocabulary** — FSM templates,
pipeline templates, handshake templates. Outside that vocabulary it degrades
to LLM-plus-human-review, and must be labelled as such rather than presented
as generation.

**So, the ladder test, in one line:**

> If the fact is structural and its consumer is identified, it is Bucket A —
> write the program, and the program must be correct-by-construction, not a
> heuristic. If it is behavioural and outside the closed vocabulary, no
> program is correct; it is Bucket B at best, and a gate can only verify a
> contract somebody else authored.

A gate is never the answer to "the inputs are already complete and nobody
joined them" — that is Bucket A by definition, and writing a gate there
repeats the exact failure measured in §2.2: *a FAILing gate was written, the
resolver never was.*

---

## 4. Declarative-layer alignment rule (forward-looking)

**When authoring or revising a layer that is a register map, an interface, a
memory map or a hierarchy connection, align its field semantics to IP-XACT
(IEEE 1685-2022) / SystemRDL 2.0 rather than inventing schema.** The payoff is
not purity, it is reuse: PeakRDL / reggen generators, UVM RAL, C headers and
generated documentation all become available assets instead of things we would
have to write.

Current coverage, measured:
`grep -rilE "ip-xact|ipxact|systemrdl|peakrdl|reggen"` across the whole plugin
returns exactly ONE file, `benchmark/cvdp_gate.py`. Zero hits in `programs/`,
`skills/` or `docs/`.

**Scope, stated so it cannot drift: this is a FORWARD AUTHORING RULE, not a
migration.** Nobody is asked to re-shape the existing 27 layers. It applies
when a declarative layer or field is being added or revised anyway, and its
cost at that moment is close to zero.

---

## 5. The anti-duplication boundary

`phase1-completeness-deep-review` and this skill are **paired, not
overlapping**, and the distinction is the whole point:

| | question it asks |
|---|---|
| `phase1-completeness-deep-review` (+ `phase1_doc_input_completeness_check.py`) | did the fact from the input documents land **SOMEWHERE** in `L*.json`? |
| **this skill** (+ `l_doc_consumer_contract.py`) | did it reach the layer that **CONSUMES** it, **in an actionable form**? |

Measurement §2.1 is the case where the first says CAPTURED and the second says
defect: 7x + 8x in two layers, 0x in the one the back end reads. If you find
yourself writing a completeness argument here, it belongs in the other skill.

---

## 6. Where the residue is (recorded, not silently dropped)

* **§2.2 is closed by a program**, not a gate:
  `programs/l_doc_symbolic_width_resolve.py` joins `width_symbolic` against
  the `parameters[]` defaults the same corpus declares, using the
  `_specrtl_common._safe_eval_int` / `_resolve_bracket_width` evaluator that
  already shipped. It is a strict no-op wherever any identifier is
  unresolvable. It is NOT wired into the runner — wiring changes what a real
  run emits and is the flow owner's call.
* **§2.3 is an open gap with a known home.** The fix is one more derivation
  limb on `l19_pdk_floorplan_contract_check._design_fixed_die_mandates`,
  reading prose inputs through `l_doc_consumer_contract.framed_hits` — NOT a
  new program. An unnecessary program is worse than none.
* **Cross-layer traceability IDs** (a unique id per layer element plus
  explicit `consumes` references) would generalise §2 into something
  checkable. It is a schema change to all 27 layer emitters, not one
  workflow; on today's tree no emitter declares what it consumes, so a
  general reference gate would resolve zero references on every design — a
  gate that fires on nothing. Not taken. Note the reference-DISCOVERY half
  already exists, scoped to L2, in
  `programs/l2_named_constant_resolvable_check.py`, including the narrowing
  lesson that unanchored `L<n>.<ident>` matching false-positives on 100% of
  runs.

---

## Why a program cannot decide any of this

The ladder requires this be recorded, not assumed:

* **§1 and the layer-assignment judgement in §2** — deciding which of 27
  layers a fact's consumer lives in requires reading what each downstream
  consumer actually dereferences and whether the form it needs is satisfied.
  Natural-language input underdetermines that; the answer is a reading of code
  and intent, not a lookup.
* **§3** — whether a behaviour fits a finite closed vocabulary or needs
  synthesis has no decision procedure. If it did, the industry would have
  standardised behaviour and HLS would not exist.
* **§4** — whether a declarative layer should align to SystemRDL is an
  interoperability trade-off against schema churn, weighed per layer.
* **§2's mechanical half is already programs** — `l_doc_consumer_contract.py`
  and the L20/L22/L23/L24/L25/L19/L1/L2 gates do it. This skill deliberately
  keeps only the residue those programs cannot decide.

A program can VERIFY a declared contract. It cannot AUTHOR one.

---

## Output / Handoff

Emit a **Layer Contract Decision** record — one per fact or field under
discussion — and save it to a file so the compliance gate can audit it:

```markdown
## Layer Contract Decision — <field or fact>

Producing layer: L<n> (<file>.json key path)
Consuming layer: L<m> (<file>.json key path)
Consumer program: <programs/....py> — the file that dereferences it
Boundary class: structural | behavioural
  (if behavioural: inside the closed vocabulary? FSM / pipeline / handshake / none)
Declarative alignment: IP-XACT | SystemRDL | n/a — <one line of reasoning>
Actionable form required: <integer bit width | enumerable token | ...>
Bucket A (program) | Bucket B (skill) | Bucket C (expert-DB): <one line of why>
evidence: <file:line, gate verdict, or measured run this rests on>

**Verdict**: <CONTRACT_OK | DEFECT_CONSUMING_LAYER | NOT_A_LAYER_FACT>

Next: /vibe-ic-phase1
```

The `evidence:` line is not optional. A layer-assignment argument with no
measured backing is a preference, and preferences are how facts end up in the
layer that was easiest to write to.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/layer-contract-doctrine/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
