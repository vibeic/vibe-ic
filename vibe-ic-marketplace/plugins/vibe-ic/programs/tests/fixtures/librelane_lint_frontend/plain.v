module plain(input [7:0] value_i, output [7:0] value_o);
  assign value_o = ~value_i;
endmodule
