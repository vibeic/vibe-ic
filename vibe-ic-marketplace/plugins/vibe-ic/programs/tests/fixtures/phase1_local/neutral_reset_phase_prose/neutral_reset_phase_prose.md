# NeutralCore

The module **`reset_bridge`** has the following hardware interfaces defined.

| Signal | Direction | Width | Type |
|---|---|---|---|
| core_clock | input | 1 | logic |
| entropy_clock | input | 1 | logic |
| rst_n | input | 1 | logic |

| Clock | Reset | Polarity | Assertion | Release | Release synchronizer stages |
|---|---|---|---|---|---:|
| core_clock | rst_n | active-low | asynchronous | synchronous to core_clock | 2 |
| entropy_clock | rst_n | active-low | asynchronous | synchronous to entropy_clock | 2 |

rst_n remains the same active-low system reset for both domains, with asynchronous assertion and separate two-stage synchronous release.
