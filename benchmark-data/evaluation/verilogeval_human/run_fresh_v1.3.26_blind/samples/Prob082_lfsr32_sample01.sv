module TopModule (
    input  clk,
    input  reset,
    output reg [31:0] q
);

    reg [31:0] q_next;
    always @(*) begin
        q_next = {q[0], q[31:1]};   // Galois shift-right, MSB <- q[0]
        q_next[21] = q_next[21] ^ q[0];
        q_next[1] = q_next[1] ^ q[0];
        q_next[0] = q_next[0] ^ q[0];
    end

    always @(posedge clk) begin
        if (reset)
            q <= 32'h1;
        else
            q <= q_next;
    end

endmodule
