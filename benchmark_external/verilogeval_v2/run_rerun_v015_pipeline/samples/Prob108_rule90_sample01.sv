module TopModule (
    input          clk,
    input          load,
    input  [511:0] data,
    output [511:0] q
);
    reg [511:0] q_reg;
    integer i;
    reg left, right;
    always @(posedge clk) begin
        if (load)
            q_reg <= data;
        else begin
            // next[i] = q[i-1] ^ q[i+1], boundaries are 0
            q_reg <= { q_reg[510:0], 1'b0 } ^ { 1'b0, q_reg[511:1] };
        end
    end
    assign q = q_reg;
endmodule
