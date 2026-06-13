// Prob135_m2014_q6b — combinational case on {y[3:1],w}.
// y declared [3:1] (3 bits), w 1 bit -> 4-bit index. Mapping per prompt.
module TopModule (
  input [3:1] y,
  input w,
  output reg Y2
);

  always @(*) begin
    case ({y, w})
      4'h0: Y2 = 1'b0;
      4'h1: Y2 = 1'b0;
      4'h2: Y2 = 1'b1;
      4'h3: Y2 = 1'b1;
      4'h4: Y2 = 1'b0;
      4'h5: Y2 = 1'b1;
      4'h6: Y2 = 1'b0;
      4'h7: Y2 = 1'b0;
      4'h8: Y2 = 1'b0;
      4'h9: Y2 = 1'b1;
      4'ha: Y2 = 1'b1;
      4'hb: Y2 = 1'b1;
      default: Y2 = 1'b0;
    endcase
  end

endmodule
