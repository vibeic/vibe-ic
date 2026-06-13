module TopModule (
  input clk,
  input reset,
  input w,
  output z
);

  localparam A = 3'd0;
  localparam B = 3'd1;
  localparam C = 3'd2;
  localparam D = 3'd3;
  localparam E = 3'd4;
  localparam F = 3'd5;

  reg [2:0] state, next;

  always @(*) begin
    case (state)
      A: next = w ? A : B;
      B: next = w ? D : C;
      C: next = w ? D : E;
      D: next = w ? A : F;
      E: next = w ? D : E;
      F: next = w ? D : C;
      default: next = A;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= A;
    else
      state <= next;
  end

  assign z = (state == E) || (state == F);

endmodule
