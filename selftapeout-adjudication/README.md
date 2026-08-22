# Six shuttle refusals, re-adjudicated on the self-tape-out path

Nine designs went through a shuttle pre-check and six came back NOT SUITABLE. Five of
those six were refused for the same reason — more signal bits than the shuttle
template's 52 pads. That is a true sentence about the SHUTTLE and not an answer about
the CHIP: on the self-tape-out path we assign the pads ourselves, and the binding
constraints are die area, pad-ring perimeter against pad pitch, power/ground pad count
and cost. None of them is 52.

This directory is the re-adjudication. **All six are decided.** PDK `gf180mcuD` (open).

| IC | tier | one line |
|---|---|---|
| `u_hawaii_adc` | NOT FEASIBLE | upheld — needs a 1.2 V core device; the PDK's lowest is **3.3 V (2.75×)** and no corner lib exists at any 1.2 V bracket. The "≥8 analog pins vs 6 max" half is OVERTURNED by 8.5× |
| `edge_llm_accel` | NOT FEASIBLE | upheld — for a reason its OWN documents give: its declared completion criterion is tape-out *simulation* on a different PDK. Its memory macro also ships no mask-level view, so it is unstreamable on every path |
| `caravel_user_project` | UNDETERMINED | original reason OVERTURNED — it declares a different PDK, a FIXED harness die and its own pre-check; 637 signal bits, **0** of them die pins |
| `opentitan_aes` | UNDETERMINED | original reason OVERTURNED — 512 of the 515 bits are one test wrapper's convenience |
| `ibex` | UNDETERMINED | original reason OVERTURNED — 173 of the 262 bits are a bus to on-die memory, 64 more are straps |
| `edge_llm_matmul_accel` | UNDETERMINED | original reason OVERTURNED, binding constraint MEASURED — **CORE-limited, never pad-limited.** 111 pads want 2.862 mm; the flow's own sizing rule wants a **6.139–6.171 mm** die = **2.145×–2.156×** that. Initial placement legalizes at **4.522 mm** and refuses at 4.022 mm |

**Not one of the six is refused by a pad budget here.** The four UNDETERMINED rows are
undetermined for a reason that is OURS, not theirs: no step in this flow instantiates
the PDK's IO cells into the netlist, so `pad_ring_gen` refuses with
`PAD_INSTANCE_NOT_IN_BLOCK`, no layout is produced, and the general pre-check answers
`NOT_DETERMINED` about each of the six in its own words.

## What is here

* **`RESULT.md`** — the report. Starts with a grep-findable `ALL SIX DECIDED`.
* **`findings.md`** — the journal, J0–J81, one entry per measurement including the ones
  that refuted earlier entries.
* **`controls/`** — the standing controls. Run these BEFORE quoting anything in
  `RESULT.md`; several published numbers are reads of live state and two of them have
  already moved once.
* **`probes/`** — the J80 clkbuf-downsize probe: what was predicted, when it was
  registered, and the Tcl that was run.

## Running the controls

```
controls/notfeasible_control.py        rc 0 = both NOT FEASIBLE verdicts still
                                       reproduce from their sources.  Has positive
                                       controls: point J79_PDK / J79_DESIGN_ROOT at a
                                       synthetic tree and it must FAIL.
controls/decay_ledger.py               rc 0 = no published live-state reading moved.
controls/cite_audit.py                 rc 0 = every file:line the report publishes
                                       resolves, in a named tree.
controls/posthold_verdict_predicate.py rc 2 = registered and still unanswered.
                                       rc 0 = it ANSWERED; read what it says.
controls/resolve_five.py               re-solves the build-to die from the arms' raw
                                       logs without reading a number out of the report.
```

**These are not portable.** They carry absolute paths into `/home/reyerchu/_jself_priv`
on host 8HD-d and read the live OpenROAD arms there. They are published as the RECORD
of what was run and as the thing to re-run on that host — not as a suite that will pass
anywhere. Saying so is the point: a control that silently scans nothing is worse than
no control, which is why `notfeasible_control.py` carries positive controls and the
repo's own source guard refuses a zero-file scan.

**The canonical copies live at `/home/reyerchu/_jself_priv/RESULT.md` and
`findings.md`**, which is where the brief asked for them. This directory is a durable,
named copy — the two branches an earlier dispatch pushed were both deleted from the
remote unlanded, so work that exists only on one disk has a measured way of vanishing.

## What is still open, and it is stated as open

No arm has printed `POST_HOLD_LEGALIZE_OK` or `_FAILED`. Five are inside the full-die
displacement rung. A predicate for that verdict was registered at **15:40:37** before
any of them could answer, and is in `controls/posthold_verdict_predicate.py`; its
stated REASON has since been partly refuted by the arms' own logs and the refutation is
recorded rather than edited out. **No verdict in the table above depends on it.**
