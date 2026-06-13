module TopModule (
  input clk,
  input j,
  input k,
  output reg Q
);
    // JK flip-flop: Q+ = (J & ~Q) | (~K & Q)
    initial Q = 1'b0;              // deterministic power-up (no reset port)
    always @(posedge clk) begin
        case ({j, k})
            2'b00: Q <= Q;     // hold
            2'b01: Q <= 1'b0;  // reset
            2'b10: Q <= 1'b1;  // set
            2'b11: Q <= ~Q;    // toggle
            default: Q <= Q;
        endcase
    end
endmodule
