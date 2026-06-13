module TopModule(
    input  clk,
    input  a,
    input  b,
    output q,
    output state
);
    reg ff;

    // next state = carry = majority(ff, a, b)
    always @(posedge clk) begin
        ff <= (ff & a) | (ff & b) | (a & b);
    end

    assign state = ff;
    assign q     = ff ^ a ^ b;   // sum
endmodule
