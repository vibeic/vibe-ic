# `l17_e1_rail` — the population the E1 rail is defined over, owned by the test

Five L17 channel-catalog documents, one per cell of the truth table that
`l17_channel_catalog_consumer_contract_check`'s **E1
TEMPLATE_WITHOUT_EXTRACTION** rail is defined over:

    E1 fires  ⟺  extraction_status ∈ _STATUS_FOUND_NOTHING
                 AND channels == []
                 AND global_signals == []
                 AND some narrative field is populated
                 AND no catalog container was refused as unreadable

| file                              | status         | channels | globals | narrative | E1   |
|-----------------------------------|----------------|----------|---------|-----------|------|
| `fires_template_without_extraction`| FOUND_NOTHING | 0        | 0       | populated | ✅ fires |
| `channels_declared`               | FOUND_NOTHING  | 2        | 0       | populated | ❌ silent |
| `globals_declared`                | FOUND_NOTHING  | 0        | 2       | populated | ❌ silent |
| `no_narrative`                    | FOUND_NOTHING  | 0        | 0       | empty     | ❌ silent |
| `status_extracted`                | EXTRACTED      | 0        | 0       | populated | ❌ silent |

## Why these exist

`test_e1_is_still_the_narrow_rail_the_remeasurement_left_it_as` used to pin
three integers counted over **every published cell under `benchmark-data/`** —
`fired == 21`, `status_nothing == 103`, `populated_anyway == 81`. Those numbers
are properties of the publication set, not of the rail. Two corpus
reorganisations (#905: `b96cdd48` and `e73601fe`, which moved IC-level strays
into their published cells) changed the set, and the test went red at
`fired == 16` with the rail byte-for-byte unchanged. A test that only passes
while nobody has republished anything is measuring the release schedule.

The two rows that carry the actual claim — `channels_declared` and
`globals_declared` — are the ones the increment behind #377 asked to relax by
dropping the `channels == 0 and global_signals == 0` conjunct. Deleting that
conjunct makes E1 fire on them, which is what the owning test detects.

Every document here is synthetic and chip-AGNOSTIC: the entity names are
`chan_a` / `chan_b` / `sig_ready` and carry no PDK, vendor or design literals.
