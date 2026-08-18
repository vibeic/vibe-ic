# Pin Configuration

This datasheet declares its interface ONLY as a markdown PIN-CONFIGURATION
table — no natural-language `- input d (8 bits)` bullets and no fenced
```verilog module(...)``` ANSI header. Prior to the contract-extractor
coverage fix (ORGANIC-20260527-spec-conformance-extractor-coverage) the
extractor returned 0 ports for this real datasheet shape, so port
conformance was silently skipped.

## Interface

| Signal   | Direction | Width  | Description                  |
|----------|-----------|--------|------------------------------|
| clk      | input     | 1      | system clock                 |
| rst_n    | input     | 1      | active-low synchronous reset |
| data_in  | input     | [15:0] | input operand                |
| valid_in | input     | 1      | input data valid             |
| data_out | output    | 16     | registered result            |
| valid_out| output    | 1      | output data valid            |

The reset is registered to the clock. The output is registered with one
clock cycle latency.
