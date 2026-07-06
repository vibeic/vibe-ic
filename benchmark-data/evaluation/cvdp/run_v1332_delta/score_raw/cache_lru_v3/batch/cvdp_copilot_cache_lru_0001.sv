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
    output reg [$clog2(NWAYS)-1:0] way_replace
);

localparam WW = $clog2(NWAYS);

reg [NWAYS-1:0] recency [NINDEXES-1:0];

integer reset_counter;
integer i;
reg [NWAYS-1:0] cur_recency;
reg [NWAYS-1:0] nxt_recency;
reg [WW-1:0]    set_way;
reg [WW-1:0]    next_replace;
reg             found_zero;

always_ff @ (posedge clock or posedge reset) begin
    if (reset) begin
        for (reset_counter = 0; reset_counter < NINDEXES; reset_counter = reset_counter + 1) begin
            recency[reset_counter] <= {NWAYS{1'b0}};
        end
        way_replace <= {WW{1'b0}};
    end else begin
        if (access) begin
            cur_recency = recency[index];

            // Way whose recency bit is set by this access:
            //   HIT  -> the accessed way (way_select) is now most-recently-used
            //   MISS -> the victim way (current way_replace) is filled, becomes MRU
            if (hit)
                set_way = way_select;
            else
                set_way = way_replace;

            // Reference: set that way's recency bit to one.
            nxt_recency = cur_recency;
            nxt_recency[set_way] = 1'b1;

            // Rollover (spec: when only one zero remains and it is being set,
            // the selected bit is set to one and all others are reset to zero,
            // i.e. never allow the recency array to become all-ones).
            if (nxt_recency == {NWAYS{1'b1}}) begin
                nxt_recency = {NWAYS{1'b0}};
                nxt_recency[set_way] = 1'b1;
            end

            recency[index] <= nxt_recency;

            // Next victim = free slot (recency bit 0) with the smallest index.
            found_zero   = 1'b0;
            next_replace = {WW{1'b0}};
            for (i = 0; i < NWAYS; i = i + 1) begin
                if (!found_zero && (nxt_recency[i] == 1'b0)) begin
                    next_replace = i[WW-1:0];
                    found_zero   = 1'b1;
                end
            end
            way_replace <= next_replace;
        end
    end
end

endmodule : pseudo_lru_nmru_policy
