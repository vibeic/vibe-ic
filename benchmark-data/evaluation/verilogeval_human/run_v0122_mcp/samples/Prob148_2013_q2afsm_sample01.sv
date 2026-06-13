module TopModule (
  input        clk,
  input        resetn,
  input  [3:1] r,
  output [3:1] g
);

  // Priority arbiter. r1>r2>r3. State A=idle, B=grant1, C=grant2, D=grant3.
  localparam A = 2'd0, B = 2'd1, C = 2'd2, D = 2'd3;

  reg [1:0] state, next;

  // separate always block for the state table
  always @(*) begin
    case (state)
      A: begin
           if (r[1])      next = B;             // highest priority
           else if (r[2]) next = C;
           else if (r[3]) next = D;             // r3 only when it alone requests
           else           next = A;
         end
      B: next = r[1] ? B : A;                   // hold grant while request held
      C: next = r[2] ? C : A;
      D: next = r[3] ? D : A;
      default: next = A;
    endcase
  end

  // separate always block for the state flip-flops
  always @(posedge clk) begin
    if (!resetn) state <= A;
    else         state <= next;
  end

  // FSM outputs by continuous assignment
  assign g[1] = (state == B);
  assign g[2] = (state == C);
  assign g[3] = (state == D);

endmodule
