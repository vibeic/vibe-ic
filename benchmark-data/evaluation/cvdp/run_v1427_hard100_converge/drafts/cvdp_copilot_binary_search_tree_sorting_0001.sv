module binary_search_tree_sort #(
    parameter DATA_WIDTH = 32,
    parameter ARRAY_SIZE = 8
) (
    input clk,
    input reset,
    input [ARRAY_SIZE*DATA_WIDTH-1:0] data_in, // Input data to be sorted
    input start,
    output reg [ARRAY_SIZE*DATA_WIDTH-1:0] sorted_out, // Sorted output
    output reg done
);

    // Parameters for top-level FSM states
    parameter IDLE = 2'b00, BUILD_TREE = 2'b01, SORT_TREE = 2'b10;

    // Parameters for the BUILD_TREE FSM states
    parameter INIT       = 2'b00, // load next input element / check completion
              CHECK_ROOT = 2'b01, // insert as root, or start traversal at root
              TRAVERSE   = 2'b10, // walk down the tree to find a NULL position
              COMPLETE   = 2'b11; // tree construction complete

    // Parameters for the SORT_TREE FSM states
    parameter S_INIT          = 2'b00, // check root and load it as current_node
              S_TRAVERSE_LEFT = 2'b01, // push nodes while descending left
              S_POP           = 2'b10, // pop a node and store its key as output
              S_RIGHT         = 2'b11; // move to the popped node's right child

    // Pointer width: node-index width + 1 so the all-ones code is a distinct
    // NULL sentinel even for node index 0
    localparam PTR_W = $clog2(ARRAY_SIZE) + 1;

    // Registers for FSM states
    reg [1:0] top_state, build_state, sort_state;

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

    // Input array latched when start is accepted: any change on data_in in
    // the middle of the operation is ignored (the earlier value is retained)
    reg [ARRAY_SIZE*DATA_WIDTH-1:0] input_array;

    // Combinational views of the node addressed by current_node / stack top
    wire [PTR_W-1:0]      cur_left  = left_child [current_node*PTR_W +: PTR_W];
    wire [PTR_W-1:0]      cur_right = right_child[current_node*PTR_W +: PTR_W];
    wire [DATA_WIDTH-1:0] cur_key   = keys[current_node*DATA_WIDTH +: DATA_WIDTH];
    wire [PTR_W-1:0]      sp_m1     = sp - 1'b1;
    wire [PTR_W-1:0]      stack_top = stack[sp_m1*PTR_W +: PTR_W];
    wire [DATA_WIDTH-1:0] top_key   = keys[stack_top*DATA_WIDTH +: DATA_WIDTH];

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
            done <= 0;
            sorted_out <= 0;
            current_node <= {($clog2(ARRAY_SIZE)+1){1'b1}};
            temp_data <= 0;
            input_array <= 0;

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
                    sorted_out <= 0;
                    input_index <= 0;
                    output_index <= 0;
                    root <= {($clog2(ARRAY_SIZE)+1){1'b1}}; // Null pointer
                    next_free_node <= 0;
                    sp <= 0;
                    for (i = 0; i < ARRAY_SIZE; i = i + 1) begin
                        keys[i*DATA_WIDTH +: DATA_WIDTH] <= 0;
                        left_child[i*($clog2(ARRAY_SIZE)+1) +: ($clog2(ARRAY_SIZE)+1)] <= {($clog2(ARRAY_SIZE)+1){1'b1}};
                        right_child[i*($clog2(ARRAY_SIZE)+1) +: ($clog2(ARRAY_SIZE)+1)] <= {($clog2(ARRAY_SIZE)+1){1'b1}};
                        stack[i*($clog2(ARRAY_SIZE)+1) +: ($clog2(ARRAY_SIZE)+1)] <= {($clog2(ARRAY_SIZE)+1){1'b1}};
                    end
                    if (start) begin
                        // Load input data into input array
                        input_array <= data_in;
                        top_state <= BUILD_TREE;
                        build_state <= INIT;
                    end
                end

                BUILD_TREE: begin
                    case (build_state)

                        INIT: begin
                            // One cycle: read the next number from the input
                            // array, or detect that all elements are inserted
                            if (input_index < ARRAY_SIZE) begin
                                temp_data <= input_array[input_index*DATA_WIDTH +: DATA_WIDTH];
                                build_state <= CHECK_ROOT;
                            end else begin
                                build_state <= COMPLETE;
                            end
                        end

                        CHECK_ROOT: begin
                            if (root == {PTR_W{1'b1}}) begin
                                // Tree empty: insert temp_data as the root
                                keys[next_free_node*DATA_WIDTH +: DATA_WIDTH] <= temp_data;
                                root <= next_free_node;
                                next_free_node <= next_free_node + 1'b1;
                                input_index <= input_index + 1'b1;
                                build_state <= INIT;
                            end else begin
                                // Root exists: start traversal at the root
                                current_node <= root;
                                build_state <= TRAVERSE;
                            end
                        end

                        TRAVERSE: begin
                            // One cycle per level: compare and either insert
                            // at a NULL child or descend to the child
                            if (temp_data > cur_key) begin
                                if (cur_right == {PTR_W{1'b1}}) begin
                                    // Insert temp_data as right child
                                    right_child[current_node*PTR_W +: PTR_W] <= next_free_node;
                                    keys[next_free_node*DATA_WIDTH +: DATA_WIDTH] <= temp_data;
                                    next_free_node <= next_free_node + 1'b1;
                                    input_index <= input_index + 1'b1;
                                    build_state <= INIT;
                                end else begin
                                    current_node <= cur_right;
                                end
                            end else begin
                                if (cur_left == {PTR_W{1'b1}}) begin
                                    // Insert temp_data as left child
                                    left_child[current_node*PTR_W +: PTR_W] <= next_free_node;
                                    keys[next_free_node*DATA_WIDTH +: DATA_WIDTH] <= temp_data;
                                    next_free_node <= next_free_node + 1'b1;
                                    input_index <= input_index + 1'b1;
                                    build_state <= INIT;
                                end else begin
                                    current_node <= cur_left;
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
                            // One cycle: check root is not NULL and assign it
                            if (root != {PTR_W{1'b1}}) begin
                                current_node <= root;
                                sort_state <= S_TRAVERSE_LEFT;
                            end else begin
                                // Empty tree: nothing to output
                                done <= 1'b1;
                                top_state <= IDLE;
                            end
                        end

                        S_TRAVERSE_LEFT: begin
                            // Descend the left subtree, pushing each node;
                            // one extra cycle when left child is NULL to
                            // proceed to the popping state
                            if (current_node != {PTR_W{1'b1}}) begin
                                stack[sp*PTR_W +: PTR_W] <= current_node;
                                sp <= sp + 1'b1;
                                current_node <= cur_left;
                            end else begin
                                sort_state <= S_POP;
                            end
                        end

                        S_POP: begin
                            if (sp == 0) begin
                                // All nodes traversed: set the outputs
                                done <= 1'b1;
                                top_state <= IDLE;
                            end else begin
                                // Pop the stack and store the key as output
                                sorted_out[output_index*DATA_WIDTH +: DATA_WIDTH] <= top_key;
                                output_index <= output_index + 1'b1;
                                current_node <= stack_top;
                                sp <= sp_m1;
                                sort_state <= S_RIGHT;
                            end
                        end

                        S_RIGHT: begin
                            // Assign the right child of the popped node; the
                            // next S_TRAVERSE_LEFT cycle checks if it exists
                            current_node <= cur_right;
                            sort_state <= S_TRAVERSE_LEFT;
                        end

                    endcase
                end
            endcase
        end
    end
endmodule
