module TopModule (
    input              clk,
    input              load,
    input      [511:0] data,
    output reg [511:0] q = 512'b0
);
    // next q[i] = q[i-1] ^ q[i+1], boundaries q[-1]=q[512]=0
    //   {q[510:0],1'b0} -> bit i = q[i-1] (bit 0 = 0)
    //   {1'b0,q[511:1]} -> bit i = q[i+1] (bit 511 = 0)
    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= {q[510:0], 1'b0} ^ {1'b0, q[511:1]};
    end
endmodule
