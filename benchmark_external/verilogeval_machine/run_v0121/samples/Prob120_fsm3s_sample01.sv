module TopModule (
  input clk,
  input in,
  input reset,
  output out
);

  localparam A = 2'd0, B = 2'd1, C = 2'd2, D = 2'd3;
  reg [1:0] state = A, next;

  always @(*) begin
    case (state)
      A: next = in ? B : A;
      B: next = in ? B : C;
      C: next = in ? D : A;
      D: next = in ? B : C;
      default: next = A;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= A;
    else
      state <= next;
  end

  assign out = (state == D);

endmodule
