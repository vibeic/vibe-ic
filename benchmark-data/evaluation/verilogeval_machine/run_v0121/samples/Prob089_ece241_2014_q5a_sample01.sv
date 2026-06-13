module TopModule (
  input clk,
  input areset,
  input x,
  output z
);

  localparam [1:0] A = 2'd0, B = 2'd1, C = 2'd2;
  reg [1:0] state;

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= A;
    else begin
      case (state)
        A: state <= x ? C : A;
        B: state <= x ? B : C;
        C: state <= x ? B : C;
        default: state <= A;
      endcase
    end
  end

  assign z = (state == C);

endmodule
