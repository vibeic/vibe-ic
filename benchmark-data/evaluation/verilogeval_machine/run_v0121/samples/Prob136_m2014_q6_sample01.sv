module TopModule (
  input clk,
  input reset,   // synchronous reset to A
  input w,
  output z
);
  localparam A=3'd0, B=3'd1, C=3'd2, D=3'd3, E=3'd4, F=3'd5;
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
    if (reset) state <= A;
    else       state <= next;
  end

  assign z = (state == E) || (state == F);
endmodule
