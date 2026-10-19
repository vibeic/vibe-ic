module neutral_bridge import neutral_cdc_types::*;
  (input logic clk_fast_i, input logic clk_aux_i,
   input logic rst_n, input sample_t data_i, output sample_t sampled_o);
  sample_t launch_q;
  always_ff @(posedge clk_fast_i or negedge rst_n)
    if (!rst_n) launch_q <= 1'b0; else launch_q <= data_i;
`ifdef SHORT_PIPE
  localparam integer Stages = 1;
`elsif SYNTHESIS
  localparam integer Stages = NormalStages;
`else
  localparam integer Stages = 1;
`endif
  sample_t capture_q[Stages];
  for (genvar k=0;k<Stages;k++) begin:receive_stage
    if (k==0) begin:first_stage
      always_ff @(posedge clk_aux_i or negedge rst_n)
        if (!rst_n) capture_q[k] <= 1'b0; else capture_q[k] <= launch_q;
    end else begin:later_stage
      always_ff @(posedge clk_aux_i or negedge rst_n)
        if (!rst_n) capture_q[k] <= 1'b0; else capture_q[k] <= capture_q[k-1];
    end
  end
  assign sampled_o = capture_q[Stages-1];
endmodule
module unselected_crossing(input logic clk_other_i,input logic clk_unused_i,input logic data_i,output logic data_o);
  logic launch_q;
  always_ff @(posedge clk_other_i) launch_q<=data_i;
  always_ff @(posedge clk_unused_i) data_o<=launch_q;
endmodule
