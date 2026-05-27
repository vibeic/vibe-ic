module TopModule (
  input clk,
  input in,
  input reset,
  output out
);
  localparam A = 1'b0, B = 1'b1;
  reg state = B;

  always @(posedge clk) begin
    if (reset)
      state <= B;
    else begin
      case (state)
        A: state <= in ? A : B;
        B: state <= in ? B : A;
        default: state <= B;
      endcase
    end
  end

  assign out = (state == B);
endmodule
