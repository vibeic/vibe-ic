module TopModule (
  input  clk,
  input  reset,
  input  in,
  output out
);
  localparam A = 2'd0, B = 2'd1, C = 2'd2, D = 2'd3;
  reg [1:0] state;

  always @(posedge clk) begin
    if (reset)
      state <= A;
    else begin
      case (state)
        A: state <= in ? B : A;
        B: state <= in ? B : C;
        C: state <= in ? D : A;
        D: state <= in ? B : C;
      endcase
    end
  end

  assign out = (state == D);
endmodule
