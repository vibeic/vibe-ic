module TopModule (
    input  clk,
    input  j,
    input  k,
    output reg Q = 1'b0
);
    // JK flip-flop, posedge clk.
    always @(posedge clk) begin
        case ({j, k})
            2'b00:   Q <= Q;     // hold
            2'b01:   Q <= 1'b0;  // reset
            2'b10:   Q <= 1'b1;  // set
            2'b11:   Q <= ~Q;    // toggle
            default: Q <= Q;     // hold (all cases already enumerated)
        endcase
    end
endmodule
