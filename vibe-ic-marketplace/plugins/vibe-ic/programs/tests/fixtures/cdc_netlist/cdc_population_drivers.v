// Native multiple-driver boundary, not an electrical qualification fixture.
module cdc_population_ambiguous(input clk_a, clk_b, input [1:0] data_i,
                               output reg data_o);
  reg source_a, source_b;
  wire joined;
  always @(posedge clk_a) begin source_a <= data_i[0]; source_b <= data_i[1]; end
  assign joined = source_a;
  assign joined = source_b;
  always @(posedge clk_b) data_o <= joined;
endmodule

module cdc_population_unambiguous(input clk_a, clk_b, input [1:0] data_i,
                                 output reg data_o);
  reg source_a;
  always @(posedge clk_a) source_a <= data_i[0];
  always @(posedge clk_b) data_o <= source_a;
endmodule
