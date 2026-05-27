module TopModule (
    input        clk,
    input        in,
    output reg   out
);
    initial out = 1'b0;
    // D = in XOR out ; positive-edge clocked, no reset.
    always @(posedge clk)
        out <= in ^ out;
endmodule
