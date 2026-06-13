module TopModule (
  input clk,
  input load,
  input [511:0] data,
  output reg [511:0] q = 512'b0
);
    // Rule 110: next[i] = f(left=q[i+1], center=q[i], right=q[i-1])
    // next = (center & ~(left & right)) | (~center & right)
    // boundaries q[-1]=0, q[512]=0
    wire [511:0] left  = {1'b0, q[511:1]};   // left[i]  = q[i+1]  (q[512]=0)
    wire [511:0] right = {q[510:0], 1'b0};   // right[i] = q[i-1]  (q[-1]=0)
    wire [511:0] next  = (q & ~(left & right)) | (~q & right);

    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= next;
    end
endmodule
