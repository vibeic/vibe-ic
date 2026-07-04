module binary_search_tree_sort #(
    parameter DATA_WIDTH = 32,
    parameter ARRAY_SIZE = 8
) (
    input clk,
    input reset,
    input reg [ARRAY_SIZE*DATA_WIDTH-1:0] data_in, // Input data to be sorted
    input start,
    output reg [ARRAY_SIZE*DATA_WIDTH-1:0] sorted_out, // Sorted output
    output reg done
);

    // Parameters for top-level FSM states
    parameter IDLE = 2'b00, BUILD_TREE = 2'b01, SORT_TREE = 2'b10;

    // Sub-FSM state encodings (BUILD_TREE)
    localparam INIT     = 2'd0,  // load next number / detect completion
               LOAD     = 2'd1,  // root insertion or start of traversal
               TRAVERSE = 2'd2,  // descend tree to find insertion point
               COMPLETE = 2'd3;  // build finished

    // Sub-FSM state encodings (SORT_TREE) -- in-order traversal.
    // The pop phase is split so that each visited node costs exactly three
    // cycles (store output / assign right child / check right child), which is
    // what the spec's SORT_TREE latency (4*ARRAY_SIZE + 3) requires.
    localparam S_INIT  = 3'd0,   // assign root to current_node
               S_LEFT  = 3'd1,   // push and walk left (also empty-stack done)
               S_POP   = 3'd2,   // pop + store output
               S_RIGHT = 3'd3,   // assign right child of popped node
               S_DONE  = 3'd4;   // traversal finished

    // Pointer width and null encoding
    localparam PW = $clog2(ARRAY_SIZE) + 1;
    localparam [PW-1:0] NULLP = {PW{1'b1}};

    // Registers for FSM states
    reg [1:0] top_state, build_state;
    reg [2:0] sort_state;        // widened: SORT_TREE has five states

    // BST representation
    reg [ARRAY_SIZE*DATA_WIDTH-1:0] keys; // Array to store node keys
    reg [ARRAY_SIZE*($clog2(ARRAY_SIZE)+1)-1:0] left_child; // Left child pointers
    reg [ARRAY_SIZE*($clog2(ARRAY_SIZE)+1)-1:0] right_child; // Right child pointers
    reg [$clog2(ARRAY_SIZE):0] root; // Root node pointer
    reg [$clog2(ARRAY_SIZE):0] next_free_node; // Pointer to the next free node

    // Stack for in-order traversal
    reg [ARRAY_SIZE*($clog2(ARRAY_SIZE)+1)-1:0] stack; // Stack for traversal
    reg [$clog2(ARRAY_SIZE):0] sp; // Stack pointer

    // Working registers
    reg [$clog2(ARRAY_SIZE):0] current_node; // Current node being processed
    reg [$clog2(ARRAY_SIZE):0] input_index; // Index for input data
    reg [$clog2(ARRAY_SIZE):0] output_index; // Index for output data
    reg [DATA_WIDTH-1:0] temp_data; // Temporary data register
    reg [PW-1:0] popped_node; // Node id popped from the stack (for right-child step)

    // Latched input array (ignore changes on data_in during operation)
    reg [ARRAY_SIZE*DATA_WIDTH-1:0] data_latched;

    // Combinational read of the top-of-stack node id
    wire [PW-1:0] sp_top = (sp != 0) ? stack[(sp-1)*PW +: PW] : NULLP;

    // Initialize all variables
    integer i;

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            // Reset all states and variables
            top_state <= IDLE;
            build_state <= INIT;
            sort_state <= S_INIT;

            root <= {($clog2(ARRAY_SIZE)+1){1'b1}}; // Null pointer
            next_free_node <= 0;
            sp <= 0;
            input_index <= 0;
            output_index <= 0;
            popped_node <= NULLP;
            done <= 0;
            sorted_out <= {(ARRAY_SIZE*DATA_WIDTH){1'b0}};

            // Clear tree arrays
            for (i = 0; i < ARRAY_SIZE; i = i + 1) begin
                keys[i*DATA_WIDTH +: DATA_WIDTH] <= 0;
                left_child[i*($clog2(ARRAY_SIZE)+1) +: ($clog2(ARRAY_SIZE)+1)] <= {($clog2(ARRAY_SIZE)+1){1'b1}};
                right_child[i*($clog2(ARRAY_SIZE)+1) +: ($clog2(ARRAY_SIZE)+1)] <= {($clog2(ARRAY_SIZE)+1){1'b1}};
                stack[i*($clog2(ARRAY_SIZE)+1) +: ($clog2(ARRAY_SIZE)+1)] <= {($clog2(ARRAY_SIZE)+1){1'b1}};
            end

        end else begin
            case (top_state)
                IDLE: begin
                    done <= 0;
                    sorted_out <= {(ARRAY_SIZE*DATA_WIDTH){1'b0}};
                    input_index <= 0;
                    output_index <= 0;
                    root <= {($clog2(ARRAY_SIZE)+1){1'b1}}; // Null pointer
                    next_free_node <= 0;
                    sp <= 0;
                    for (i = 0; i < ARRAY_SIZE+1; i = i + 1) begin
                        keys[i*DATA_WIDTH +: DATA_WIDTH] <= 0;
                        left_child[i*($clog2(ARRAY_SIZE)+1) +: ($clog2(ARRAY_SIZE)+1)] <= {($clog2(ARRAY_SIZE)+1){1'b1}};
                        right_child[i*($clog2(ARRAY_SIZE)+1) +: ($clog2(ARRAY_SIZE)+1)] <= {($clog2(ARRAY_SIZE)+1){1'b1}};
                        stack[i*($clog2(ARRAY_SIZE)+1) +: ($clog2(ARRAY_SIZE)+1)] <= {($clog2(ARRAY_SIZE)+1){1'b1}};
                    end
                    if (start) begin
                        // Load input data into input array
                        data_latched <= data_in;
                        top_state <= BUILD_TREE;
                        build_state <= INIT;
                    end
                end

                BUILD_TREE: begin
                    case (build_state)

                        INIT: begin
                            if (input_index >= ARRAY_SIZE) begin
                                build_state <= COMPLETE;
                            end else begin
                                temp_data   <= data_latched[input_index*DATA_WIDTH +: DATA_WIDTH];
                                build_state <= LOAD;
                            end
                        end

                        LOAD: begin
                            if (root == NULLP) begin
                                // Empty tree: insert the root node
                                keys[next_free_node*DATA_WIDTH +: DATA_WIDTH] <= temp_data;
                                root           <= next_free_node;
                                next_free_node <= next_free_node + 1'b1;
                                input_index    <= input_index + 1'b1;
                                build_state    <= INIT;
                            end else begin
                                current_node <= root;
                                build_state  <= TRAVERSE;
                            end
                        end

                        TRAVERSE: begin
                            if (temp_data > keys[current_node*DATA_WIDTH +: DATA_WIDTH]) begin
                                // Go right
                                if (right_child[current_node*PW +: PW] == NULLP) begin
                                    right_child[current_node*PW +: PW] <= next_free_node;
                                    keys[next_free_node*DATA_WIDTH +: DATA_WIDTH] <= temp_data;
                                    next_free_node <= next_free_node + 1'b1;
                                    input_index    <= input_index + 1'b1;
                                    build_state    <= INIT;
                                end else begin
                                    current_node <= right_child[current_node*PW +: PW];
                                end
                            end else begin
                                // Go left
                                if (left_child[current_node*PW +: PW] == NULLP) begin
                                    left_child[current_node*PW +: PW] <= next_free_node;
                                    keys[next_free_node*DATA_WIDTH +: DATA_WIDTH] <= temp_data;
                                    next_free_node <= next_free_node + 1'b1;
                                    input_index    <= input_index + 1'b1;
                                    build_state    <= INIT;
                                end else begin
                                    current_node <= left_child[current_node*PW +: PW];
                                end
                            end
                        end

                        COMPLETE: begin
                            // Tree construction complete
                            top_state <= SORT_TREE;
                            sort_state <= S_INIT;
                        end

                    endcase
                end

                SORT_TREE: begin
                    case (sort_state)

                        S_INIT: begin
                            // Assign root to current_node (1 cycle)
                            current_node <= root;
                            sort_state   <= S_LEFT;
                        end

                        S_LEFT: begin
                            if (current_node != NULLP) begin
                                // Push current node and descend left
                                stack[sp*PW +: PW] <= current_node;
                                sp           <= sp + 1'b1;
                                current_node <= left_child[current_node*PW +: PW];
                            end else if (sp == 0) begin
                                // Stack empty and no current node -> traversal done.
                                // Folding the empty-stack check in here keeps the
                                // per-node pop cost at exactly three cycles.
                                sort_state <= S_DONE;
                            end else begin
                                sort_state <= S_POP;
                            end
                        end

                        S_POP: begin
                            // Store output (pop the top-of-stack node, emit its key)
                            sorted_out[output_index*DATA_WIDTH +: DATA_WIDTH] <= keys[sp_top*DATA_WIDTH +: DATA_WIDTH];
                            output_index <= output_index + 1'b1;
                            popped_node  <= sp_top;
                            sp           <= sp - 1'b1;
                            sort_state   <= S_RIGHT;
                        end

                        S_RIGHT: begin
                            // Assign right child of the popped node, then go back
                            // to S_LEFT which checks whether it exists.
                            current_node <= right_child[popped_node*PW +: PW];
                            sort_state   <= S_LEFT;
                        end

                        S_DONE: begin
                            done      <= 1'b1;
                            top_state <= IDLE;
                        end

                    endcase
                end
            endcase
        end
    end
endmodule
