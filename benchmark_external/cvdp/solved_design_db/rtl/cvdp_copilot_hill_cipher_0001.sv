// Hill cipher encryption: 3-letter blocks (5 bits/letter), 3x3 key matrix,
// all arithmetic mod 26.  Ciphertext_i = (sum_j K_ij * P_j) mod 26.
// Latency: 3 clock cycles from `start` HIGH to a valid ciphertext.
module hill_cipher (
    input  wire        clk,
    input  wire        reset,        // asynchronous, active HIGH; clears ciphertext
    input  wire        start,        // HIGH initiates an encryption
    input  wire [14:0] plaintext,    // [14:10]=P0, [9:5]=P1, [4:0]=P2
    input  wire [44:0] key,          // 3x3 matrix, 5 bits/element, row-major
    output reg  [14:0] ciphertext,   // [14:10]=C0, [9:5]=C1, [4:0]=C2
    output reg         done          // HIGH when encryption is complete
);

    // FSM states
    localparam IDLE   = 2'd0;
    localparam MUL    = 2'd1;
    localparam MODST  = 2'd2;
    localparam FINISH = 2'd3;

    reg [1:0]  state;

    // Latched operands
    reg [14:0] pt_reg;
    reg [44:0] key_reg;

    // Dot-product accumulators (max 25*25*3 = 1875 -> 11 bits, use 12)
    reg [11:0] sum0_reg, sum1_reg, sum2_reg;

    // Plaintext letters
    wire [4:0] p0 = pt_reg[14:10];
    wire [4:0] p1 = pt_reg[9:5];
    wire [4:0] p2 = pt_reg[4:0];

    // Key matrix elements
    wire [4:0] k00 = key_reg[44:40];
    wire [4:0] k01 = key_reg[39:35];
    wire [4:0] k02 = key_reg[34:30];
    wire [4:0] k10 = key_reg[29:25];
    wire [4:0] k11 = key_reg[24:20];
    wire [4:0] k12 = key_reg[19:15];
    wire [4:0] k20 = key_reg[14:10];
    wire [4:0] k21 = key_reg[9:5];
    wire [4:0] k22 = key_reg[4:0];

    // mod-26 reductions of the accumulated dot products
    wire [4:0] c0 = sum0_reg % 12'd26;
    wire [4:0] c1 = sum1_reg % 12'd26;
    wire [4:0] c2 = sum2_reg % 12'd26;

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            state      <= IDLE;
            ciphertext <= 15'd0;
            done       <= 1'b0;
            pt_reg     <= 15'd0;
            key_reg    <= 45'd0;
            sum0_reg   <= 12'd0;
            sum1_reg   <= 12'd0;
            sum2_reg   <= 12'd0;
        end else begin
            case (state)
                IDLE: begin
                    done <= 1'b0;
                    if (start) begin
                        pt_reg  <= plaintext;
                        key_reg <= key;
                        state   <= MUL;
                    end
                end
                MUL: begin
                    sum0_reg <= (k00 * p0) + (k01 * p1) + (k02 * p2);
                    sum1_reg <= (k10 * p0) + (k11 * p1) + (k12 * p2);
                    sum2_reg <= (k20 * p0) + (k21 * p1) + (k22 * p2);
                    state    <= MODST;
                end
                MODST: begin
                    ciphertext <= {c0, c1, c2};
                    done       <= 1'b1;
                    state      <= FINISH;
                end
                FINISH: begin
                    done <= 1'b1;          // hold done until re-armed
                    if (!start)
                        state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end

endmodule
