module TopModule (
    input  clk,
    input  a,
    input  b,
    output q,
    output state
);
    reg s;
    always @(posedge clk) begin
        s <= s ? (a | b) : (a & b);
    end
    assign state = s;
    assign q = a ^ b ^ s;
endmodule
