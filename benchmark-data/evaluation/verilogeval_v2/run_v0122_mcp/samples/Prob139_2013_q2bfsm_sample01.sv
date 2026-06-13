module TopModule (
    input  clk,
    input  resetn,   // synchronous active-low reset
    input  x,
    input  y,
    output f,
    output g
);

    localparam A  = 4'd0,  // reset state
               B  = 4'd1,  // f=1 for one cycle
               S1 = 4'd2,  // watching for first 1 of x
               S2 = 4'd3,  // saw "1"
               S3 = 4'd4,  // saw "10"
               G1 = 4'd5,  // g=1, y-check cycle 1
               G2 = 4'd6,  // g=1, y-check cycle 2
               GH = 4'd7,  // g=1 permanent
               GO = 4'd8;  // g=0 permanent

    reg [3:0] state, nxt;

    always @(*) begin
        case (state)
            A:  nxt = B;                    // reset deasserted -> f cycle next
            B:  nxt = S1;                   // after one f cycle, start watching x
            S1: nxt = x ? S2 : S1;
            S2: nxt = x ? S2 : S3;          // have "1"; on 0 -> "10"
            S3: nxt = x ? G1 : S1;          // "101" detected -> G1 (g=1 next)
            G1: nxt = y ? GH : G2;          // y within cycle 1
            G2: nxt = y ? GH : GO;          // y within cycle 2
            GH: nxt = GH;                   // g=1 permanent
            GO: nxt = GO;                   // g=0 permanent
            default: nxt = A;
        endcase
    end

    always @(posedge clk) begin
        if (!resetn)
            state <= A;
        else
            state <= nxt;
    end

    // Moore outputs
    assign f = (state == B);
    assign g = (state == G1) || (state == G2) || (state == GH);

endmodule
