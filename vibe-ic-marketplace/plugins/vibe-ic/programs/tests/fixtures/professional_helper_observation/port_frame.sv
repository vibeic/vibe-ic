module port_frame(input logic clk_i, rst_n, input logic [7:0] data_i,
                  output logic [7:0] out_o);
always_comb begin
  if (!rst_n) out_o = 0;
  else if (data_i[0]) out_o = data_i ^ 8'h3a;
  else out_o = data_i ^ 8'h3a;
end
endmodule
