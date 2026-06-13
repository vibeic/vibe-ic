`default_nettype none
module tb_cov_top(input wire clk, input wire rst_in, output wire gpio_o);
   localparam MEMSIZE=1024;
   wire [9:0] sa; wire [7:0] sw; reg [7:0] sr; wire swe, scyc;
   reg [7:0] mem [0:MEMSIZE-1]; integer i; reg init=0;
   always @(posedge clk) begin
      if (!init) begin for(i=0;i<MEMSIZE;i=i+1) mem[i]=8'h0; $readmemh("gpio_bytes.hex",mem); init<=1; end
      if (scyc & swe) mem[sa]<=sw;
      sr <= mem[sa];
   end
   subservient #(.MEMSIZE(MEMSIZE)) dut(.i_clk(clk),.i_rst(rst_in),.o_sram_addr(sa),.o_sram_wdata(sw),
      .i_sram_rdata(sr),.o_sram_we(swe),.o_sram_cyc(scyc),.o_gpio(gpio_o));
endmodule
`default_nettype wire
