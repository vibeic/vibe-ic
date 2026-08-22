# tests/fixtures/si_mcf_zero_coupling/

Two complete `si_mcf_sta_check` project directories that differ by **exactly one
line**: a 4-token (2-node) coupling `*CAP` entry. They exist so the claim
"the SI gate signed off on a zero it measured itself" can be re-measured by
anyone, on any machine, without a benchmark artefact.

## Why a shipped fixture and not the tracked artefact

The finding was first stated against
`benchmark-data/ic/spm/v1.5.58_ihp-sg13g2/reports/phase3/si_mcf_sta.json`, whose
`coupling_pairs: 0` sits next to `verdict: PASS`. That report is real, but its
`spef` field names an **absolute path inside the authoring machine's campaign
directory**. On any other host the gate exits down its missing-SPEF branch and
never reaches the coupling-count decision, so the before/after numbers could not
be reproduced by a reviewer. A verdict that depends on a path outside the tree
answers differently on CI than on the author's box — which is its own version of
the bug this fixture demonstrates.

Everything here is therefore **relative**. `si_mcf_sta.json` names
`design.spef`, not `/home/<user>/...`. Run the gate with this directory as the
process cwd.

## The measurement, by hand

    cd programs/tests/fixtures/si_mcf_zero_coupling/grounded_only
    python3 ../../../../si_mcf_sta_check.py . --json /tmp/si_gate.json
    echo "rc=$?"        # rc=2  VACUOUS_PASS  (examined 0 of 0)

    cd ../coupled
    python3 ../../../../si_mcf_sta_check.py . --json /tmp/si_gate.json
    echo "rc=$?"        # rc=0  PASS          (examined 2 of 4)

Always pass `--json` to a path outside the repository: without it the gate
writes its report into `reports/phase3/` of the project it was pointed at, and
that project is this tracked fixture.

Against the gate as it stood **before** the fix, both directories exit `rc 0`
with `verdict PASS` and a summary whose every verdict-bearing field
(`pass`, `errors_count`, `findings_count`) is identical. The only field that
differed was `coupling_pairs` — counted, printed, and never turned into a
finding. That is the defect, and
`programs/tests/test_si_zero_coupling_fixture_transition.py` pins both halves of
it from the emitted JSON.

## What is in each directory

| file | what it is |
|---|---|
| `design.spef` | the extraction the STA numbers claim to come from — hand-authored, IEEE-1481 detailed format, two nets |
| `design.mcf_setup.spef` | the setup-corner bounded SPEF, **emitted by `si_mcf_sta.rewrite_spef_folded`** |
| `design.mcf_hold.spef` | the hold-corner bounded SPEF, same emitter |
| `reports/phase3/si_mcf_sta.json` | the emitter's report the gate re-derives against |

The two bounded SPEFs are not hand-written expected output: the shipped test
re-derives them from `design.spef` with the real emitter and asserts byte
equality, so they cannot silently drift into a hand-maintained answer key.

`coupled/` is the arm that must stay a `PASS`. It is here so the change can
never become a blanket FAIL on the coupling axis, and so the fixture measures
that axis and nothing else.

chip-AGNOSTIC: net and instance names are `net_a` / `net_b` / `ua` / `ub`, cells
are `BUF` / `DFF`. No design, PDK, vendor, foundry or cell-library literal
appears in this directory.
