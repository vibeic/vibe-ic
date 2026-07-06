Complete the given partial SystemVerilog code for the `pseudo_lru_nmru_policy` module. This module should implement a pseudo-LRU (Least Recently Used) and NMRU (Not Most Recently Used) hybrid policy for cache replacement in a set-associative cache. Use a recency bit array to track access patterns for cache ways.

## Specification

### Module Name: `pseudo_lru_nmru_policy`

### Parameters
- **NWAYS**: Number of ways in the cache (default: 4). Must be a power of 2 and at least 4.
- **NINDEXES**:  Number of indexes in the cache (default: 32). Must be a power of 2.

### Ports

| Port Name       | Direction | Size                          | Description                                           |
|------------------|-----------|-------------------------------|-------------------------------------------------------|
| `clock`         | Input     | 1 bit                         | Clock signal                                          |
| `reset`         | Input     | 1 bit                         | Asynchronous reset signal, active high               |
| `index`         | Input     | `ceil(log2(NINDEXES))` bits   | Index to select the cache set                        |
| `way_select`    | Input     | `ceil(log2(NWAYS))` bits      | Cache way selected for access                        |
| `access`        | Input     | 1 bit                         | Signal indicating a cache access                     |
| `hit`           | Input     | 1 bit                         | Signal indicating a cache hit                        |
| `way_replace`   | Output    | `ceil(log2(NWAYS))` bits      | Way selected for replacement                         |

### Functionality
- The `recency` array tracks access recency for each cache way for all indexes.
- During reset, all bits in `recency` are initialized to zero.
- A cache way is marked for replacement if its `recency` bit is zero.
- Upon a hit, the corresponding `recency` bit is set to one.
- If only one `recency` bit is zero, it behaves as an LRU policy, selecting that way for replacement. The selected bit is then set to one, and all others are reset to zero.
- When multiple bits are zero, the module operates as an NMRU policy, allowing any zero bit to be replaced. In this implementation the free slot with the smallest index is pointed first.

### Instructions to Complete the RTL

Complete the given partial SystemVerilog code for the `pseudo_lru_nmru_policy` module. This module tracks the recency of access for cache ways and determines the way to replace based on the pseudo-LRU and NMRU policy.

```systemverilog
module pseudo_lru_nmru_policy #(
    NWAYS = 4,
    NINDEXES = 32
) (
    input clock,
    input reset,
    input [$clog2(NINDEXES)-1:0] index,
    input [$clog2(NWAYS)-1:0] way_select,
    input access,
    input hit,
    output [$clog2(NWAYS)-1:0] way_replace
);

reg [NWAYS-1:0] recency [NINDEXES-1:0];

integer reset_counter;
always_ff @ (posedge clock or posedge reset) begin
    if (reset) begin
        for (reset_counter = 0; reset_counter < NINDEXES; reset_counter = reset_counter + 1) begin
            recency[reset_counter] <= {NWAYS{1'b0}};
        end
    end else begin

    end
end

endmodule : pseudo_lru_nmru_policy
```

### Requirements
1. Implement logic to update the `recency` array upon hits (`hit` signal).
2. Implement logic to determine the `way_replace` signal based on the `recency` bits.
3. Ensure proper handling of reset to initialize the `recency` array.
4. Use SystemVerilog constructs for clarity and efficiency.