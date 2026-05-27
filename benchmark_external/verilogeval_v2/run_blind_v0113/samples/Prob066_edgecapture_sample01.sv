module TopModule (
    input         clk,
    input         reset,
    input  [31:0] in,
    output [31:0] out
);
    reg [31:0] prev;
    reg [31:0] cap;
    always @(posedge clk) begin
        if (reset)
            cap <= 32'b0;
        else
            cap <= cap | (prev & ~in);
        prev <= in;
    end
    assign out = cap;
endmodule
