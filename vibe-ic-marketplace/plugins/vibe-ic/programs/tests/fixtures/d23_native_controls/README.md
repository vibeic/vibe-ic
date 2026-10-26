# Portable D23 control unit fixture

`input_mapped.v`, `chained.v`, and `native_chain.log` are byte-exact small neutral two-DFF artifacts from the retained actual Fault run, CID8f50930e56f6e7619f1e8708bb2fc7e1ef7d6a575c3488924bcafd9f4170afdd. Native source packet manifest:ba5e3865bb299fbf611bd8e9ae0d99ee26f727603fc88d524d26912b3a2d77d1. Return1 full-Liberty/native integration evidence manifest:a60e9521c988b42329c226d52f4ba49a58f1a99b76fcfe158970c8178a82ad35.

`semantic.lib` is a deliberately function-only UNIT model of the two cells used by this payload. It carries no timing tables, PDK qualification or new native execution claim. The separate retained native/full-Liberty evidence remains authoritative for that integration. Tests intercept native I/O and run the real source consumers on this portable payload; no private environment, external artifact mount or full PDK library is required.
