module TopModule (
  input  clk,
  input  resetn,
  input  [3:1] r,
  output [3:1] g
);

  // Priority arbiter (r1 > r2 > r3). Moore: g[i]=1 in the corresponding grant state.
  // Active-low synchronous reset to A.
  localparam A = 2'd0;  // idle, no grant
  localparam B = 2'd1;  // grant device 1 (g1)
  localparam C = 2'd2;  // grant device 2 (g2)
  localparam D = 2'd3;  // grant device 3 (g3)

  reg [1:0] state, next;

  // State table
  always @(*) begin
    case (state)
      A: begin
        if      (r[1]) next = B;
        else if (r[2]) next = C;
        else if (r[3]) next = D;
        else           next = A;
      end
      B: next = r[1] ? B : A;   // hold grant while requested
      C: next = r[2] ? C : A;
      D: next = r[3] ? D : A;
      default: next = A;
    endcase
  end

  // State flip-flops
  always @(posedge clk) begin
    if (!resetn)
      state <= A;
    else
      state <= next;
  end

  // Moore outputs
  assign g[1] = (state == B);
  assign g[2] = (state == C);
  assign g[3] = (state == D);

endmodule
