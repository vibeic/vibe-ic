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

// One-hot mask for the currently accessed way (NWAYS bits wide).
wire [NWAYS-1:0] way_onehot = { {(NWAYS-1){1'b0}}, 1'b1 } << way_select;

integer reset_counter;
always_ff @ (posedge clock or posedge reset) begin
    if (reset) begin
        // Reset: initialise all recency bits of every set to zero (power-up safe).
        for (reset_counter = 0; reset_counter < NINDEXES; reset_counter = reset_counter + 1) begin
            recency[reset_counter] <= {NWAYS{1'b0}};
        end
    end else begin
        // Upon a hit, set the corresponding recency bit to one.
        if (access && hit) begin
            if ((recency[index] | way_onehot) == {NWAYS{1'b1}}) begin
                // pseudo-LRU roll-over: setting this bit would make every bit 1.
                // Keep only the just-accessed way's bit set, reset all others to zero.
                recency[index] <= way_onehot;
            end else begin
                recency[index] <= recency[index] | way_onehot;
            end
        end
    end
end

// Replacement selection: a way is a candidate if its recency bit is zero.
// Point to the free slot with the smallest way index first (NMRU / pseudo-LRU victim).
reg [$clog2(NWAYS)-1:0] way_replace_r;
integer sel_i;
always_comb begin
    way_replace_r = {$clog2(NWAYS){1'b0}};
    // Scan high->low so the lowest-index zero bit wins (last assignment).
    for (sel_i = NWAYS-1; sel_i >= 0; sel_i = sel_i - 1) begin
        if (recency[index][sel_i] == 1'b0)
            way_replace_r = sel_i[$clog2(NWAYS)-1:0];
    end
end

assign way_replace = way_replace_r;

endmodule : pseudo_lru_nmru_policy
