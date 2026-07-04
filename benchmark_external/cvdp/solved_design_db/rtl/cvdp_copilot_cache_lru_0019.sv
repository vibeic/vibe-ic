module pseudo_lru_tree_policy #(
    parameter NWAYS = 4,
    parameter NINDEXES = 32
)(
    input clock,
    input reset,
    input [$clog2(NINDEXES)-1:0] index,
    input [$clog2(NWAYS)-1:0] way_select,
    input access,
    input hit,
    output [$clog2(NWAYS)-1:0] way_replace
);

    localparam int unsigned NBITS_TREE = NWAYS - 1;
    localparam int unsigned WAY_W      = $clog2(NWAYS);

    // Recency array to track next way to be replaced
    reg [NBITS_TREE-1:0] recency [NINDEXES-1:0];

    wire [NBITS_TREE-1:0] recency_updated;
    wire [$clog2(NWAYS)-1:0] pseudo_lru_slot;

    integer i;

    // Sequential logic for reset and recency updates
    always_ff @ (posedge clock or posedge reset) begin
        if (reset) begin
            for (i = 0; i < NINDEXES; i++) begin
                recency[i] <= NBITS_TREE'(0);
            end
        end else begin
            if (access) begin
                recency[index] <= recency_updated;
            end
        end
    end

    // Implement the code for recency_updated wire
    // On an access the way that becomes most-recently-used (MRU) is the hit way
    // on a hit, or the replaced (Pseudo-LRU) way on a miss.  Walking the tree
    // from the root toward that way, each node on the path is set to point
    // TOWARD it (the MRU direction is the way's own bit at that depth), so a
    // subsequent MRU traversal that follows the stored bits spells out the way.
    // Nodes off the path keep their previous value.
    wire [WAY_W-1:0] mru_way = hit ? way_select : pseudo_lru_slot;

    logic [NBITS_TREE-1:0] recency_next;
    integer d;
    logic [WAY_W-1:0] pos;
    logic tbit;
    always_comb begin
        recency_next = recency[index];
        pos          = '0;
        tbit         = 1'b0;
        for (d = 0; d < WAY_W; d++) begin
            // bit of the target way at this depth (root = MSB)
            tbit = mru_way[WAY_W-1-d];
            // Update recency tree to mark accessed/replaced way as MRU:
            // store the direction that points toward the way.
            recency_next[(1 << d) - 1 + pos] = tbit;
            pos = (pos << 1) | tbit;
        end
    end
    assign recency_updated = recency_next;

    // Select the Pseudo LRU slot
    slot_select_pseudo_lru_tree #(
        .NWAYS (NWAYS)
    ) slot_select_unit (
        .array (recency[index]),
        .index (pseudo_lru_slot)
    );

    assign way_replace = pseudo_lru_slot;

endmodule : pseudo_lru_tree_policy

module slot_select_pseudo_lru_tree #(
    parameter NWAYS = 4
)(
    input [NWAYS-2:0] array,
    output logic [$clog2(NWAYS)-1:0] index
);

    localparam int unsigned MAX_DEPTH = $clog2(NWAYS);

    integer depth;
    logic [$clog2(NWAYS)-1:0] step;
    logic direction;

    always_comb begin
        // Find the Pseudo LRU (least-recently-used) way by descending the tree
        // from the root.  Each stored bit points toward the MRU child, so the
        // LRU traversal follows the OPPOSITE direction (~bit) at every node.
        // The path of directions (root = MSB) spells the way to replace.
        index     = '0;
        step      = '0;
        direction = 1'b0;
        for (depth = 0; depth < MAX_DEPTH; depth++) begin
            direction = ~array[(1 << depth) - 1 + step];
            index[MAX_DEPTH-1-depth] = direction;
            step = (step << 1) | direction;
        end
    end

endmodule : slot_select_pseudo_lru_tree
