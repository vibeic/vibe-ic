module search_binary_search_tree #(
    parameter DATA_WIDTH = 32,         // Width of the data (of a single element)
    parameter ARRAY_SIZE = 15          // Maximum number of elements in the BST
) (
    input clk,                         // Clock signal
    input reset,                       // Reset signal
    input start,                       // Start signal to initiate the search
    input [DATA_WIDTH-1:0] search_key,              // Key to search in the BST
    input [$clog2(ARRAY_SIZE):0] root,              // Root node of the BST
    input [ARRAY_SIZE*DATA_WIDTH-1:0] keys,         // Node keys in the BST
    input [ARRAY_SIZE*($clog2(ARRAY_SIZE)+1)-1:0] left_child,  // Left child pointers
    input [ARRAY_SIZE*($clog2(ARRAY_SIZE)+1)-1:0] right_child, // Right child pointers
    output reg [$clog2(ARRAY_SIZE):0] key_position,     // Position of the found key
    output reg complete_found,         // Signal indicating search completion
    output reg search_invalid          // Signal indicating invalid search
);

    // Pointer width (index + 1 bit so all-1s is a distinct null pointer)
    localparam PW = $clog2(ARRAY_SIZE) + 1;
    localparam [PW-1:0] NULLP = {PW{1'b1}};

    // FSM states
    localparam S_IDLE     = 4'd0,
               S_INIT     = 4'd1,
               S_CMP      = 4'd2,   // compare search_key with current node
               S_RSIZE    = 4'd3,   // count SIZE of a right-turn node's left subtree
               S_RMOVE    = 4'd4,   // move to the right child
               S_FISTART  = 4'd5,   // ==root : one setup cycle
               S_FIDESC   = 4'd6,   // ==root : in-order descend (push left spine)
               S_FIVISIT  = 4'd7,   // ==root : in-order visit (count rank)
               S_FSIZE    = 4'd8,   // descent-found : count found node's left subtree
               S_FEXTRA   = 4'd9,   // descent-found : settle cycle
               S_COMPLETE = 4'd10,
               S_INVALID  = 4'd11;

    reg [3:0]      state;
    reg [PW-1:0]   cur;     // current node on the BST search path
    reg [PW-1:0]   pos;     // accumulated in-order rank
    reg            moved;   // have we moved off the root yet?
    reg [PW-1:0]   c2;      // pointer for the counting sub-traversals
    reg [PW-1:0]   cstack [0:ARRAY_SIZE];  // stack for the sub-traversals
    reg [PW:0]     csp;     // stack pointer

    integer i;
    reg [PW-1:0] n;         // blocking temp (popped node)

    // Combinational views of the current pointers (stable pre-edge values)
    wire [DATA_WIDTH-1:0] cur_key   = keys       [cur*DATA_WIDTH +: DATA_WIDTH];
    wire [PW-1:0]         cur_left  = left_child  [cur*PW         +: PW];
    wire [PW-1:0]         cur_right = right_child [cur*PW         +: PW];
    wire [PW-1:0]         c2_left   = left_child  [c2*PW          +: PW];

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            state          <= S_IDLE;
            complete_found <= 1'b0;
            search_invalid <= 1'b0;
            key_position   <= NULLP;
            cur            <= {PW{1'b0}};
            pos            <= {PW{1'b0}};
            moved          <= 1'b0;
            c2             <= {PW{1'b0}};
            csp            <= {(PW+1){1'b0}};
            for (i = 0; i <= ARRAY_SIZE; i = i + 1)
                cstack[i] <= NULLP;
        end else begin
            case (state)
                // ----------------------------------------------------------
                S_IDLE: begin
                    complete_found <= 1'b0;
                    search_invalid <= 1'b0;
                    if (start) begin
                        key_position <= NULLP;
                        pos          <= {PW{1'b0}};
                        moved        <= 1'b0;
                        csp          <= {(PW+1){1'b0}};
                        if (root == NULLP) begin
                            state <= S_INVALID;   // empty tree
                        end else begin
                            cur   <= root;
                            state <= S_CMP;       // compare with root next cycle
                        end
                    end
                end
                // ----------------------------------------------------------
                S_CMP: begin
                    if (search_key == cur_key) begin
                        if (!moved) begin
                            // == at the root
                            if (cur_left == NULLP) begin
                                state <= S_COMPLETE;          // position 0
                            end else begin
                                c2    <= cur_left;
                                csp   <= {(PW+1){1'b0}};
                                state <= S_FISTART;           // in-order count of left subtree
                            end
                        end else begin
                            // == after descending
                            if (cur_left == NULLP) begin
                                state <= S_FEXTRA;
                            end else begin
                                cstack[0] <= cur_left;
                                csp       <= {{PW{1'b0}}, 1'b1};
                                state     <= S_FSIZE;
                            end
                        end
                    end else if (search_key < cur_key) begin
                        if (cur_left == NULLP) begin
                            state <= S_INVALID;
                        end else begin
                            cur   <= cur_left;
                            moved <= 1'b1;
                            state <= S_CMP;
                        end
                    end else begin
                        // search_key > cur_key : this node and its left subtree precede it
                        pos <= pos + 1'b1;
                        if (cur_left == NULLP) begin
                            state <= S_RMOVE;
                        end else begin
                            cstack[0] <= cur_left;
                            csp       <= {{PW{1'b0}}, 1'b1};
                            state     <= S_RSIZE;
                        end
                    end
                end
                // ----------------------------------------------------------
                // Pre-order SIZE count of a left subtree (right-turn case)
                S_RSIZE: begin
                    n   = cstack[csp-1'b1];
                    pos <= pos + 1'b1;
                    if ((right_child[n*PW +: PW] != NULLP) &&
                        (left_child [n*PW +: PW] != NULLP)) begin
                        cstack[csp-1'b1] <= right_child[n*PW +: PW];
                        cstack[csp]      <= left_child [n*PW +: PW];
                        csp              <= csp + 1'b1;
                        state            <= S_RSIZE;
                    end else if (right_child[n*PW +: PW] != NULLP) begin
                        cstack[csp-1'b1] <= right_child[n*PW +: PW];
                        state            <= S_RSIZE;
                    end else if (left_child[n*PW +: PW] != NULLP) begin
                        cstack[csp-1'b1] <= left_child[n*PW +: PW];
                        state            <= S_RSIZE;
                    end else begin
                        csp <= csp - 1'b1;
                        if (csp == {{PW{1'b0}}, 1'b1}) state <= S_RMOVE;
                        else                            state <= S_RSIZE;
                    end
                end
                // ----------------------------------------------------------
                S_RMOVE: begin
                    if (cur_right == NULLP) begin
                        state <= S_INVALID;
                    end else begin
                        cur   <= cur_right;
                        moved <= 1'b1;
                        state <= S_CMP;
                    end
                end
                // ----------------------------------------------------------
                // Pre-order SIZE count of a descent-found node's left subtree
                S_FSIZE: begin
                    n   = cstack[csp-1'b1];
                    pos <= pos + 1'b1;
                    if ((right_child[n*PW +: PW] != NULLP) &&
                        (left_child [n*PW +: PW] != NULLP)) begin
                        cstack[csp-1'b1] <= right_child[n*PW +: PW];
                        cstack[csp]      <= left_child [n*PW +: PW];
                        csp              <= csp + 1'b1;
                        state            <= S_FSIZE;
                    end else if (right_child[n*PW +: PW] != NULLP) begin
                        cstack[csp-1'b1] <= right_child[n*PW +: PW];
                        state            <= S_FSIZE;
                    end else if (left_child[n*PW +: PW] != NULLP) begin
                        cstack[csp-1'b1] <= left_child[n*PW +: PW];
                        state            <= S_FSIZE;
                    end else begin
                        csp <= csp - 1'b1;
                        if (csp == {{PW{1'b0}}, 1'b1}) state <= S_FEXTRA;
                        else                            state <= S_FSIZE;
                    end
                end
                // ----------------------------------------------------------
                S_FEXTRA: begin
                    state <= S_COMPLETE;
                end
                // ----------------------------------------------------------
                // ==root : in-order traversal of the left subtree (counts rank)
                S_FISTART: begin
                    state <= S_FIDESC;
                end
                S_FIDESC: begin
                    cstack[csp] <= c2;
                    csp         <= csp + 1'b1;
                    if (c2_left != NULLP) begin
                        c2    <= c2_left;
                        state <= S_FIDESC;
                    end else begin
                        state <= S_FIVISIT;
                    end
                end
                S_FIVISIT: begin
                    n   = cstack[csp-1'b1];
                    pos <= pos + 1'b1;
                    if (right_child[n*PW +: PW] != NULLP) begin
                        csp   <= csp - 1'b1;
                        c2    <= right_child[n*PW +: PW];
                        state <= S_FIDESC;
                    end else begin
                        csp <= csp - 1'b1;
                        if (csp == {{PW{1'b0}}, 1'b1}) state <= S_COMPLETE;
                        else                            state <= S_FIVISIT;
                    end
                end
                // ----------------------------------------------------------
                S_COMPLETE: begin
                    complete_found <= 1'b1;
                    key_position   <= pos;
                    search_invalid <= 1'b0;
                    state          <= S_IDLE;
                end
                // ----------------------------------------------------------
                S_INVALID: begin
                    search_invalid <= 1'b1;
                    complete_found <= 1'b0;
                    key_position   <= NULLP;
                    state          <= S_IDLE;
                end
                // ----------------------------------------------------------
                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
