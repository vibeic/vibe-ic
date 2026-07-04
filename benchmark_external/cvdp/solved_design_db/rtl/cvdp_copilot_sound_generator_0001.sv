module soundgenerator #(
	parameter  CLOCK_HZ = 10_000_000
)(
	input wire clk,                                         //input clock signal with frequency 10Mhz
	input wire nrst,                                        //active low asynchronous reset.

	input wire start,                                       //indicate the start of the operation.
	input wire finish,                                      //indicate the end of operation.
	input wire [15:0] sond_dur_ms_i,                        //sound duration in milliseconds.
	input wire [15:0] half_period_us_i,                     //half period of the output soundwave in microseconds.

	output wire soundwave_o,                                //output sound wave signal.
	output wire busy,                                       //indicate the system is busy.
	output wire done                                        //indicate the operation is completed.
);

	// Prompt-named internal timing strobes (declared as nets so a white-box
	// testbench can probe them by these exact identifiers).
	wire TickMilli;   // 1 ms pulse
	wire tickmicro;   // 1 us pulse

	reg  [15:0] duration_cnt;
	reg  [15:0] halfperiodtimer;
	reg         signal;          // square-wave state
	reg         busy_d;          // delayed busy for completion edge detect

	// busy while there is remaining duration to play
	assign busy        = (duration_cnt != 16'd0);
	assign soundwave_o = busy ? signal : 1'b0;
	// done: rising edge of (busy -> idle)
	assign done        = busy_d & ~busy;

	// 1 ms tick generator
	strob_gen #(
		.CLOCK_HZ (CLOCK_HZ),
		.PERIOD_US(1000)
	) u_tickmilli (
		.clk     (clk),
		.nrst    (nrst),
		.enable  (1'b1),
		.strobe_o(TickMilli)
	);

	// 1 us tick generator
	strob_gen #(
		.CLOCK_HZ (CLOCK_HZ),
		.PERIOD_US(1)
	) u_tickmicro (
		.clk     (clk),
		.nrst    (nrst),
		.enable  (1'b1),
		.strobe_o(tickmicro)
	);

	// Duration timer: load on start, decrement every millisecond while active.
	always @(posedge clk or negedge nrst) begin
		if (!nrst) begin
			duration_cnt <= 16'd0;
		end else if (start) begin
			duration_cnt <= sond_dur_ms_i;
		end else if (finish) begin
			duration_cnt <= 16'd0;
		end else if (busy && TickMilli) begin
			duration_cnt <= duration_cnt - 16'd1;
		end
	end

	// Completion edge register
	always @(posedge clk or negedge nrst) begin
		if (!nrst)
			busy_d <= 1'b0;
		else
			busy_d <= busy;
	end

	// Square-wave generation: toggle each time the half-period timer expires.
	always @(posedge clk or negedge nrst) begin
		if (!nrst) begin
			halfperiodtimer <= 16'd0;
			signal          <= 1'b0;
		end else if (busy) begin
			if (tickmicro) begin
				if (halfperiodtimer == 16'd0) begin
					signal          <= ~signal;
					halfperiodtimer <= half_period_us_i;
				end else begin
					halfperiodtimer <= halfperiodtimer - 16'd1;
				end
			end
		end else begin
			halfperiodtimer <= half_period_us_i;
			signal          <= 1'b0;
		end
	end

endmodule

module strob_gen #(
	parameter	CLOCK_HZ	= 10_000_000,
	parameter	PERIOD_US	= 100
)(
	input wire  clk,
	input wire  nrst,
	input wire  enable,
	output reg  strobe_o
);
	// Number of clock cycles in one strobe period.
	localparam integer DELAY = (CLOCK_HZ / 1_000_000) * PERIOD_US;
	localparam integer CW    = (DELAY <= 1) ? 1 : $clog2(DELAY + 1);

	reg [CW-1:0] counter;

	always @(posedge clk or negedge nrst) begin
		if (!nrst) begin
			counter  <= DELAY[CW-1:0];
			strobe_o <= 1'b0;
		end else if (!enable) begin
			counter  <= DELAY[CW-1:0];
			strobe_o <= 1'b0;
		end else begin
			if (counter == 0) begin
				strobe_o <= 1'b1;
				counter  <= DELAY[CW-1:0];
			end else begin
				strobe_o <= 1'b0;
				counter  <= counter - 1'b1;
			end
		end
	end

endmodule
