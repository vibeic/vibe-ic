# batch68's two gates landed without the fixtures the repo requires — closing that

WIP. Batch 68 added two gates to `tools/ci/repo_hygiene_gates.sh`:

    :334   table rows belong to tables            doc_table_row_placement_check.py
    :1208  a printed population agrees with its pin  emitter_population_pin_check.py

`gate_mutation_fixture_check` states the repo's rule: "A gate lands with both
directions or it does not land." Both gates are NEW-OR-UNEXCUSED — they carry
neither a CAN-PASS nor a CAN-FAIL fixture, and they are not in
`gate_fixture_debt.json`.

The measurement report records this as a defect batch68 introduced inside a test
that was ALREADY RED, so no id-level differential could report it.

The forbidden repair is adding two entries to `gate_fixture_debt.json`: that is a
baseline rewrite to make a failure go away. The honest repair is to write the two
fixtures. That is what this branch does.
