# Evidence index

Every file here, and the claim in `../RESULT.md` / `../recoveries.json` it backs.
An artefact nothing points at reads as evidence for something without saying
what, so this index exists in both directions: no claim without a file, no file
without a claim.

## F1 — the step read the wrong PDK view

| file | the claim it backs |
|---|---|
| `repro_f1.py` | drives the PRE-FIX producer at a distribution that declares its site in the tech view. Backs: the refusal already enumerated the file it read, so the disclosure form of the rule was satisfied by the code that had the bug. |
| `prior_art_claims_VERIFIED.txt` | Claim A: the canonical disclosure predicate, run on that refusal text, MATCHES — a disclosure guard really is clean on the buggy tree. Claim B: 6 programs reference an upstream tree and compare, none pins our computation against upstream's. |
| `f1_population_MEASURED.txt` | the population of the upstream-contract rule: 5 of 1232 programs declare an upstream contract AND cite it by path. |
| `f1_sweep_scoping1_MEASURED.txt` | formulation 1, natural scoping: 63 upstream reads, 43 unaccounted, fires 4/5. |
| `f1_sweep_scoping2_MEASURED.txt` | formulation 1, narrowed by upstream's own `pdk=True` flag: 19 unaccounted, fires 3/5 — **and the control on the pre-fix tree returns `[]`**, which is what ends it. |
| `upstream_input_set_MEASURED.txt` | the two variable sets side by side, with the harvest definition stated, and the note that a second defensible denominator gives a different cardinal over the same finding. |
| `f1_input_set_pin_REFUTED.txt` | the three scopings written up together, and why no scoping can contain the dropped variable. |
| `f1_view_coverage_probe.py` | formulation 2 — **DROPPED**. Kept because it is the artefact that made formulation 2 look clean: it measures the right two arms on the fixture and nothing else, which is exactly how an unswept rule passes. |
| `f1_formulation2_sweep_MEASURED.txt` | formulation 2's false-positive sweep: population 14. |
| `f1_formulation2_inscope_MEASURED.txt` | of those, 10 refuse after a lookup into a distribution view and **8 of the 10 read exactly one view** — the measurement that dropped it. |
| `f1_final_probe.py` | formulation 3, both arms **with the negative control**: name findable in an unread view → fires and names the file; name declared nowhere → silent, and a genuine absence stays a genuine absence. |
| `f1_substring_fp_probe.py` | the false-positive test of formulation 3's SUBSTRING form on the real PDKs — the one I should have run before adopting it. |
| `f1_declaration_grammar_probe.py` | the same question asked through the step's own declaration parser. |
| `f1_formulation3_fp_MEASURED.txt` | both results side by side: substring fires on 2 unrelated files per PDK; declaration grammar is clean on all four probes on both. |
| `f1_three_formulations.txt` | all three in order, and the lesson: a rule is not a rule until it has been run over its own population. |

## F2 — the extent came from the oriented footprint

| file | the claim it backs |
|---|---|
| `f2_pin_probe.py` | the AST taint walk, run against both trees: RED on `origin/main` (16 orientation-tainted names, `along` among them), GREEN on the fix branch (2, both corner extents). |
| `f2_generality_sweep_MEASURED.txt` | the sweep I owed this rule and did not run until three rounds later: the shape the predicate keys on occurs at **224 sites** across the population, so detection alone cannot be the program. Backs the rule's change of shape to declare-then-check. |

Upstream's own side arithmetic was read directly out of the pinned image and is
quoted in `../RESULT.md`; it is not reproduced here as a file because it is
upstream's source, not our measurement.

## F3 — the rotation arguments

| file | the claim it backs |
|---|---|
| `probe.def`, `one.tcl`, `run.sh` | the two-arm probe: one argument pair per process, so no row from an earlier pass can be reused by a later one. |
| `rotation_two_arm_MEASURED.txt` | the result: varying the HORIZONTAL argument moves WEST/EAST, varying the VERTICAL argument moves SOUTH/NORTH. The two are applied to each other's rows. |
| `loc.tcl`, `run2.sh`, `rotation_row_identity_MEASURED.txt` | row identity confirmed by DIE POSITION rather than by trusting the row names — the west-row pad sits at the offset from the low-X edge, the south-row pad at the offset from the low-Y edge. |
| `rotation_arguments_GOLDEN.txt` | the golden, labelled DERIVED not observed, with the two things it is derived from: the argument names, and the tool's own script layer dumped from the running binary. |
| `f3b_population_MEASURED.txt` | the unhonoured-knob class has FOUR instances on this tree, in four subsystems (77 raw hits → 12 narrowed → 4 read by hand). |
| `f3b_contract_status_MEASURED.txt` | of those four, **0 carry the non-honouring as a machine-readable record** — all four wrote it as prose in whichever module found it. |

## F4 — the component vocabulary

| file | the claim it backs |
|---|---|
| `f4_population_MEASURED.txt` | the population is **one**: exactly one validator in 1232 programs carries a `PREFIX:IDENTIFIER` alternation. A real defect, but a single instance rather than a class — recorded so it is not read as a general rule by association. |
