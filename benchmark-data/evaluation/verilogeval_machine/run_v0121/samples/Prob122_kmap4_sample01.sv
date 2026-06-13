module TopModule (
  input a,
  input b,
  input c,
  input d,
  output reg out
);

  // SPEC DEFECT: prose under-specifies the K-map (only 0000->0, 0101->0, 1111->1
  // are given). Most defensible reading consistent with all stated rows: AND of all.
  always @(*) begin
    case ({a, b, c, d})
      4'b1111: out = 1'b1;
      default: out = 1'b0;
    endcase
  end

endmodule
