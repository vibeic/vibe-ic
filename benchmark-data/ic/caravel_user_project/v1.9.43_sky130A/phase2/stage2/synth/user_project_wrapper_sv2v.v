`default_nettype none
`default_nettype none
`default_nettype none
module user_proj_example (
	wb_clk_i,
	wb_rst_i,
	wbs_stb_i,
	wbs_cyc_i,
	wbs_we_i,
	wbs_sel_i,
	wbs_dat_i,
	wbs_adr_i,
	wbs_ack_o,
	wbs_dat_o,
	la_data_in,
	la_data_out,
	la_oenb,
	io_in,
	io_out,
	io_oeb,
	irq
);
	parameter BITS = 16;
	input wb_clk_i;
	input wb_rst_i;
	input wbs_stb_i;
	input wbs_cyc_i;
	input wbs_we_i;
	input [3:0] wbs_sel_i;
	input [31:0] wbs_dat_i;
	input [31:0] wbs_adr_i;
	output wire wbs_ack_o;
	output wire [31:0] wbs_dat_o;
	input [127:0] la_data_in;
	output wire [127:0] la_data_out;
	input [127:0] la_oenb;
	input [BITS - 1:0] io_in;
	output wire [BITS - 1:0] io_out;
	output wire [BITS - 1:0] io_oeb;
	output wire [2:0] irq;
	wire clk;
	wire rst;
	wire [BITS - 1:0] rdata;
	wire [BITS - 1:0] wdata;
	wire [BITS - 1:0] count;
	wire valid;
	wire [3:0] wstrb;
	wire [BITS - 1:0] la_write;
	assign valid = wbs_cyc_i && wbs_stb_i;
	assign wstrb = wbs_sel_i & {4 {wbs_we_i}};
	assign wbs_dat_o = {{32 - BITS {1'b0}}, rdata};
	assign wdata = wbs_dat_i[BITS - 1:0];
	assign io_out = count;
	assign io_oeb = {BITS {rst}};
	assign irq = 3'b000;
	assign la_data_out = {{128 - BITS {1'b0}}, count};
	assign la_write = ~la_oenb[63:64 - BITS] & ~{BITS {valid}};
	assign clk = (~la_oenb[64] ? la_data_in[64] : wb_clk_i);
	assign rst = (~la_oenb[65] ? la_data_in[65] : wb_rst_i);
	counter #(.BITS(BITS)) counter(
		.clk(clk),
		.reset(rst),
		.ready(wbs_ack_o),
		.valid(valid),
		.rdata(rdata),
		.wdata(wbs_dat_i[BITS - 1:0]),
		.wstrb(wstrb),
		.la_write(la_write),
		.la_input(la_data_in[63:64 - BITS]),
		.count(count)
	);
endmodule
module counter (
	clk,
	reset,
	valid,
	wstrb,
	wdata,
	la_write,
	la_input,
	ready,
	rdata,
	count
);
	parameter BITS = 16;
	input clk;
	input reset;
	input valid;
	input [3:0] wstrb;
	input [BITS - 1:0] wdata;
	input [BITS - 1:0] la_write;
	input [BITS - 1:0] la_input;
	output reg ready;
	output reg [BITS - 1:0] rdata;
	output reg [BITS - 1:0] count;
	always @(posedge clk)
		if (reset) begin
			count <= 1'b0;
			ready <= 1'b0;
		end
		else begin
			ready <= 1'b0;
			if (~|la_write)
				count <= count + 1'b1;
			if (valid && !ready) begin
				ready <= 1'b1;
				rdata <= count;
				if (wstrb[0])
					count[7:0] <= wdata[7:0];
				if (wstrb[1])
					count[15:8] <= wdata[15:8];
			end
			else if (|la_write)
				count <= la_write & la_input;
		end
endmodule
`default_nettype wire
`default_nettype none
module user_project_wrapper (
	wb_clk_i,
	wb_rst_i,
	wbs_stb_i,
	wbs_cyc_i,
	wbs_we_i,
	wbs_sel_i,
	wbs_dat_i,
	wbs_adr_i,
	wbs_ack_o,
	wbs_dat_o,
	la_data_in,
	la_data_out,
	la_oenb,
	io_in,
	io_out,
	io_oeb,
	analog_io,
	user_clock2,
	user_irq
);
	parameter BITS = 32;
	input wb_clk_i;
	input wb_rst_i;
	input wbs_stb_i;
	input wbs_cyc_i;
	input wbs_we_i;
	input [3:0] wbs_sel_i;
	input [31:0] wbs_dat_i;
	input [31:0] wbs_adr_i;
	output wire wbs_ack_o;
	output wire [31:0] wbs_dat_o;
	input [127:0] la_data_in;
	output wire [127:0] la_data_out;
	input [127:0] la_oenb;
	input [37:0] io_in;
	output wire [37:0] io_out;
	output wire [37:0] io_oeb;
	inout [28:0] analog_io;
	input user_clock2;
	output wire [2:0] user_irq;
	user_proj_example mprj(
		.wb_clk_i(wb_clk_i),
		.wb_rst_i(wb_rst_i),
		.wbs_cyc_i(wbs_cyc_i),
		.wbs_stb_i(wbs_stb_i),
		.wbs_we_i(wbs_we_i),
		.wbs_sel_i(wbs_sel_i),
		.wbs_adr_i(wbs_adr_i),
		.wbs_dat_i(wbs_dat_i),
		.wbs_ack_o(wbs_ack_o),
		.wbs_dat_o(wbs_dat_o),
		.la_data_in(la_data_in),
		.la_data_out(la_data_out),
		.la_oenb(la_oenb),
		.io_in({io_in[37:30], io_in[7:0]}),
		.io_out({io_out[37:30], io_out[7:0]}),
		.io_oeb({io_oeb[37:30], io_oeb[7:0]}),
		.irq(user_irq)
	);
endmodule
`default_nettype wire
