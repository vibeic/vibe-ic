// Neutral native producer controls; no electrical or protocol qualification.
module cdc_population_mixed(input clk_a, clk_b, input [1:0] data_i,
                            output [1:0] data_o);
  reg launch_safe, launch_unsafe, sync1, sync2, capture_unsafe;
  always @(posedge clk_a) begin
    launch_safe <= data_i[0];
    launch_unsafe <= data_i[1];
  end
  always @(posedge clk_b) begin
    sync1 <= launch_safe;
    sync2 <= sync1;
    capture_unsafe <= launch_unsafe;
  end
  assign data_o = {capture_unsafe, sync2};
endmodule

module cdc_population_single(input clk, data_i, output data_o);
  reg stage1, stage2;
  always @(posedge clk) begin stage1 <= data_i; stage2 <= stage1; end
  assign data_o = stage2;
endmodule

module cdc_population_comb(input data_i, output data_o);
  assign data_o = data_i;
endmodule
