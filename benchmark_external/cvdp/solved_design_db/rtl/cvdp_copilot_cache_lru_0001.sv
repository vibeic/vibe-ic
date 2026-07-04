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

localparam WAY_IDX_W = $clog2(NWAYS);

reg [NWAYS-1:0] recency [NINDEXES-1:0];

integer reset_counter;
integer j;

// Combinational replacement selection: a way is a replacement candidate when
// its recency bit is 0; the free slot with the SMALLEST index is pointed first
// (NMRU when several bits are zero, LRU when only one is zero).
reg [WAY_IDX_W-1:0] repl_way;
always @(*) begin
    repl_way = {WAY_IDX_W{1'b0}};
    for (j = NWAYS-1; j >= 0; j = j - 1) begin
        if (recency[index][j] == 1'b0)
            repl_way = j[WAY_IDX_W-1:0];
    end
end
assign way_replace = repl_way;

// Recency update.  The way that becomes "most-recently-used" this access is:
//   - on a HIT  : the accessed way (way_select)
//   - on a MISS : the way currently pointed for replacement (way_replace); the
//                 replaced line is filled with new data and so becomes MRU.
//                 The way_select input is irrelevant on a miss.
// If marking that way as used would leave every recency bit at 1 (it was the
// last 0 bit -- the LRU corner), reset all other bits to 0 so a replacement
// candidate always exists: the just-used way becomes the only MRU bit.
reg [WAY_IDX_W-1:0]  target;
reg [NWAYS-1:0]      target_onehot;
reg [NWAYS-1:0]      next_recency;
always_ff @ (posedge clock or posedge reset) begin
    if (reset) begin
        for (reset_counter = 0; reset_counter < NINDEXES; reset_counter = reset_counter + 1) begin
            recency[reset_counter] <= {NWAYS{1'b0}};
        end
    end else begin
        if (access) begin
            target        = hit ? way_select : way_replace;
            target_onehot = {{(NWAYS-1){1'b0}}, 1'b1} << target;
            next_recency  = recency[index] | target_onehot;
            if (next_recency == {NWAYS{1'b1}})
                recency[index] <= target_onehot;
            else
                recency[index] <= next_recency;
        end
    end
end

endmodule : pseudo_lru_nmru_policy
