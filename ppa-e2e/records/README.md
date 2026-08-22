# Published records — all 61 arms

One directory per arm: `baseline/` (the default configuration) and
`trials/t000..t059/` (the 60 search points). **Every trial is here, not only the
winner** — a search that publishes only its best result is an advertisement, not
a measurement.

| file | what it is |
|---|---|
| `records_flat.json` | the arm's full canonical `vibeic.ppa.metric.v1` record set, after the F-4 re-wrap and the F-9/F-10 collision resolution. This is *the* record set; everything else is derived from it or feeds it. |
| `signoff_bridge_records.json` | the F-3 bridge: canonical records for the nine feasibility axes, read from the arm's own sign-off artefacts. Authored by this lane, not by the flow. |
| `contract.json` | `vibeic.ppa.contract.v1`, built by the shipped `ppa_contract_build.py` and validated by `ppa_contract_check.py` (both rc=0 on every arm). |
| `declaration.json` | the input to the above, so the contract can be rebuilt. |
| `feasibility_shipped_only_report.json` | `ppa_feasibility_check.py` over `records_flat.json` alone — the verdict a downloaded plugin gets. |
| `feasibility_bridged_report.json` | the same, with the bridge records added. |
| `run.json` | the arm's knobs, the runner's exit code, and its own cgroup cost (wall / CPU / peak RSS). |
| `extraction.json` | what the extractor read, and every problem it reported. |
| `power.json` | the `vibeic.ppa.power.v1` envelope, with `stage_derivation` and `pvt_scope_derivation` — the F-7 and F-8 evidence. Kept for `baseline/` and `trials/t028/` only; for every other arm its records are already inside `records_flat.json`, byte for byte. |

`head_to_head*.json` are the two comparison records and the shipped checker's
reports on them. `summary.json` holds every figure `../RESULT.md` quotes, so the
prose and the artefacts cannot drift apart.
