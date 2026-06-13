module TopModule (
  input  [3:0] x,
  output       f
);
  // x[3]=x4, x[2]=x3, x[1]=x2, x[0]=x1 (per K-map labelling x[1..4]).
  // Don't-cares chosen as 0; required ones/zeros all satisfied.
  reg r;
  always @(*) begin
    case (x)
      4'd4, 4'd6, 4'd11, 4'd12, 4'd14: r = 1'b1;
      default: r = 1'b0;
    endcase
  end
  assign f = r;
endmodule
