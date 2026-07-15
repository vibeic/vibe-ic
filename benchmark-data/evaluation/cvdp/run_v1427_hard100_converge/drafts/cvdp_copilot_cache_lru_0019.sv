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

    localparam integer NBITS_TREE = NWAYS - 1;
    localparam integer TREE_DEPTH = $clog2(NWAYS);

    // Recency array to track next way to be replaced (level-order tree per set)
    reg [NBITS_TREE-1:0] recency [NINDEXES-1:0];

    wire [NBITS_TREE-1:0]    recency_updated;
    wire [$clog2(NWAYS)-1:0] pseudo_lru_slot;

    integer i;

    // Sequential logic for reset and recency updates
    always_ff @ (posedge clock or posedge reset) begin
        if (reset) begin
            for (i = 0; i < NINDEXES; i++) begin
                recency[i] <= {NBITS_TREE{1'b0}};
            end
        end else begin
            if (access) begin
                recency[index] <= recency_updated;
            end
        end
    end

    // Way that becomes Most Recently Used (MRU) on this access:
    //  - hit  : the accessed way (way_select)
    //  - miss : the way just selected for replacement (pseudo_lru_slot)
    wire [$clog2(NWAYS)-1:0] mru_way = hit ? way_select : pseudo_lru_slot;

    logic [NBITS_TREE-1:0]    recency_next;
    logic [$clog2(NWAYS)-1:0] mru_pos;
    logic                     mru_bit;
    integer d;

    // Update recency tree: descend along the MRU way's path (MSB = depth 0),
    // pointing every visited node AWAY from the MRU way. Off-path nodes keep
    // their previous value. Node at depth d, position p lives at (2^d - 1) + p.
    always_comb begin
        recency_next = recency[index];
        mru_pos      = '0;
        mru_bit      = 1'b0;
        for (d = 0; d < TREE_DEPTH; d = d + 1) begin
            // Update recency tree for hit / Update tree to mark replaced way as MRU
            mru_bit = mru_way[TREE_DEPTH-1-d];
            recency_next[(2**d - 1) + mru_pos] = ~mru_bit; // point toward LRU side
            mru_pos = (mru_pos << 1) | mru_bit;            // descend to MRU child
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

    localparam integer MAX_DEPTH = $clog2(NWAYS);

    integer depth;
    logic [$clog2(NWAYS)-1:0] step;
    logic direction;

    // Find the Pseudo LRU way index: follow each stored node bit directly
    // (it points toward the replacement / LRU side). Node at depth 'depth',
    // position 'step' lives at array index (2^depth - 1) + step.
    always_comb begin
        step      = '0;
        direction = 1'b0;
        for (depth = 0; depth < MAX_DEPTH; depth = depth + 1) begin
            direction = array[(2**depth - 1) + step];
            step      = (step << 1) | direction;
        end
        index = step;
    end

endmodule : slot_select_pseudo_lru_tree
