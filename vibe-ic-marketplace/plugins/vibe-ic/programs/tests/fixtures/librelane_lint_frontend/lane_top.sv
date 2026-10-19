module lane_top import word_types::*; (
  input logic [W-1:0] value_i,
  output logic [W-1:0] value_o
);
  assign value_o = value_i ^ {W{1'b1}};
endmodule
