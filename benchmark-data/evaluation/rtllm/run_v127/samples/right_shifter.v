// right_shifter — 8-bit right-shift register fed by 1-bit serial input d.
// Each rising clk: q shifts right by 1 and d enters the MSB (q[7]).
// q is an 8-bit register initialized to 0.
module right_shifter (
    input  wire       clk,
    input  wire       d,
    output reg  [7:0] q
);
    initial q = 8'b0;
    always @(posedge clk) begin
        q <= {d, q[7:1]};   // q >> 1 with d inserted at q[7]
    end
endmodule
