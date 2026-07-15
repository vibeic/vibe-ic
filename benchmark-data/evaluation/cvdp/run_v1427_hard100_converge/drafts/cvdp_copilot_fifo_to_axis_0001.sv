module ping_pong_fifo_2_axi_stream #(
  parameter logic                              DATA_WIDTH          = 24,
  parameter logic                              STROBE_WIDTH        = DATA_WIDTH / 8,
  parameter logic                              USE_KEEP            = 0,
  parameter logic                              USER_IN_DATA        = 1
)(
  input  logic                                 rst,

  // Ping Pong FIFO Read Interface
  input  logic                                 i_block_fifo_rdy,
  output logic                                 o_block_fifo_act,
  input  logic [23:0]                          i_block_fifo_size,
  input  logic [(DATA_WIDTH + 1) - 1:0]        i_block_fifo_data,
  output logic                                 o_block_fifo_stb,
  input  logic [3:0]                           i_axi_user,

  // AXI Stream Output
  input  logic                                 i_axi_clk,
  output logic [3:0]                           o_axi_user,
  input  logic                                 i_axi_ready,
  output logic [DATA_WIDTH - 1:0]              o_axi_data,
  output logic                                 o_axi_last,
  output logic                                 o_axi_valid
);

// Internal signals
logic [DATA_WIDTH - 1:0] fifo_data_buffer;
logic fifo_valid_buffer;
logic fifo_last_buffer;

// A new word is fetched from the Ping Pong FIFO whenever the FIFO reports
// data available AND the internal buffer is either empty or is being drained
// by the AXI Stream sink in this same cycle (valid && ready handshake).
// This gives full back-to-back throughput while guaranteeing that a beat
// stalled by a deasserted i_axi_ready is never overwritten or lost.
logic fifo_fetch;
assign fifo_fetch = i_block_fifo_rdy && (!fifo_valid_buffer || i_axi_ready);

// Reset Condition
always_ff @(posedge i_axi_clk or posedge rst) begin
  if (rst) begin
    o_block_fifo_act   <= 1'b0;
    o_axi_valid        <= 1'b0;
    fifo_data_buffer   <= {DATA_WIDTH{1'b0}};
    fifo_valid_buffer  <= 1'b0;
    fifo_last_buffer   <= 1'b0;
  end else begin
    // Activate the FIFO read side whenever the FIFO has data available;
    // release it as soon as the FIFO is no longer ready.  While
    // i_block_fifo_rdy is deasserted no read is ever performed.
    o_block_fifo_act <= i_block_fifo_rdy;

    if (fifo_fetch) begin
      // Capture the next word (payload + embedded 'last' flag in the MSB)
      // from the FIFO into the internal transfer buffer and mark a beat
      // pending on the AXI Stream output.
      fifo_data_buffer  <= i_block_fifo_data[DATA_WIDTH-1:0];
      fifo_last_buffer  <= i_block_fifo_data[DATA_WIDTH];
      fifo_valid_buffer <= 1'b1;
      o_axi_valid       <= 1'b1;
    end else if (fifo_valid_buffer && i_axi_ready) begin
      // Current beat has been accepted by the AXI Stream sink and no new
      // word is available from the FIFO: the buffer drains.
      fifo_valid_buffer <= 1'b0;
      o_axi_valid       <= 1'b0;
    end
    // Otherwise: the AXI sink is stalling (i_axi_ready == 0) with a beat
    // pending, or there is nothing to send - data/last/valid are held
    // perfectly stable so no beat is dropped or altered while waiting
    // for the handshake.
  end
end

// AXI Stream outputs are driven from the internal buffer so that a stalled
// beat stays stable until i_axi_ready allows the transfer to complete.
assign o_axi_data = fifo_data_buffer;
assign o_axi_last = fifo_last_buffer & fifo_valid_buffer;

// User sideband: pass the user-defined input through to the AXI Stream
// user output.
assign o_axi_user = i_axi_user;

// Strobe back to the FIFO in the same cycle a word is being fetched so the
// FIFO advances exactly once per word consumed (one strobe pulse per beat).
assign o_block_fifo_stb = fifo_fetch & ~rst;

endmodule
