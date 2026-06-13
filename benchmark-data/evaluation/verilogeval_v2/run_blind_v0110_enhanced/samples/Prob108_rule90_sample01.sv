module TopModule (
    input  wire          clk,
    input  wire          load,
    input  wire [511:0]  data,
    output reg  [511:0]  q = 512'b0
);
    always @(posedge clk) begin
        if (load)
            q <= data;
        else begin
            // next[i] = q[i-1] ^ q[i+1], boundaries zero
            q <= {1'b0, q[511:1]} ^ {q[510:0], 1'b0};
        end
    end
endmodule
