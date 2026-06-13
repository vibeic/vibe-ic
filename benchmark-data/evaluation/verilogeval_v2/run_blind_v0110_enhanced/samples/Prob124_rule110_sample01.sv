module TopModule(
    input              clk,
    input              load,
    input      [511:0] data,
    output reg [511:0] q = 512'b0
);
    wire [511:0] left  = {1'b0, q[511:1]};   // left[i]  = q[i+1], q[512]=0
    wire [511:0] right = {q[510:0], 1'b0};    // right[i] = q[i-1], q[-1]=0

    // Rule 110: next = (C & ~L) | (C & ~R) | (~C & R)
    wire [511:0] next_q = (q & ~left) | (q & ~right) | (~q & right);

    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= next_q;
    end
endmodule
