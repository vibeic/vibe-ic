module TopModule (
    input  clk,
    input  a,
    input  b,
    output q,
    output state
);
    reg ff;

    always @(posedge clk) begin
        if (ff)
            ff <= a | b;   // when state=1, leave only when a|b is 0
        else
            ff <= a & b;   // when state=0, set only when a&b
    end

    assign state = ff;
    assign q     = a ^ b ^ ff;  // a^b when state=0, a~^b when state=1
endmodule
