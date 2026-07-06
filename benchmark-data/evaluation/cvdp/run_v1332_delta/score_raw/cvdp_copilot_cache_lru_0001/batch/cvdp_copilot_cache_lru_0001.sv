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

// One-hot mask (NWAYS wide) selecting the accessed way.
wire [NWAYS-1:0] sel_mask = ({{(NWAYS-1){1'b0}}, 1'b1} << way_select);

// Recency vector of the currently addressed set after applying the hit.
wire [NWAYS-1:0] next_recency = recency[index] | sel_mask;

integer reset_counter;
always_ff @ (posedge clock or posedge reset) begin
    if (reset) begin
        for (reset_counter = 0; reset_counter < NINDEXES; reset_counter = reset_counter + 1) begin
            recency[reset_counter] <= {NWAYS{1'b0}};
        end
    end else begin
        // Update recency only on an accessing hit.
        if (access && hit) begin
            // If setting this way's recency bit would leave every way marked
            // as recently-used (no free slot for replacement), wrap around:
            // keep only the just-accessed way set and reset all others.
            if (next_recency == {NWAYS{1'b1}}) begin
                recency[index] <= sel_mask;
            end else begin
                recency[index] <= next_recency;
            end
        end
    end
end

// Combinational replacement selection:
//   A way is a replacement candidate when its recency bit is zero.
//   Among all zero (not-recently-used) ways, point the smallest index first.
//   Scanning high->low and overwriting on each zero leaves the lowest zero.
integer i;
reg [$clog2(NWAYS)-1:0] way_replace_r;
always_comb begin
    way_replace_r = {$clog2(NWAYS){1'b0}};
    for (i = NWAYS-1; i >= 0; i = i - 1) begin
        if (recency[index][i] == 1'b0) begin
            way_replace_r = i[$clog2(NWAYS)-1:0];
        end
    end
end

assign way_replace = way_replace_r;

endmodule : pseudo_lru_nmru_policy
