// -----------------------------------------------------------------------------
// axis_upscale
//
// AXI-Stream data upsizer: upscales a single-channel 24-bit input word to a
// 32-bit output word with optional data-format handling (MSB carry-forward /
// inversion and sign extension), through exactly one pipeline register stage.
//
//   - dfmt_enable = 0 : m_axis_data = {8'h00, s_axis_data}  (plain zero-extend)
//   - dfmt_enable = 1 :
//       carry bit   = dfmt_type ? ~s_axis_data[23] : s_axis_data[23]
//       upper fill  = dfmt_se   ? {8{carry bit}}   : 8'h00
//       m_axis_data = {upper fill, carry bit, s_axis_data[22:0]}
//
// Latency     : 1 clock cycle (m_axis_valid/m_axis_data follow s_axis_valid
//               by one cycle).
// Ready path  : s_axis_ready is a pure combinational pass-through of
//               m_axis_ready, so a slave transfer is only accepted in cycles
//               the downstream can absorb the pipelined result.
// Reset       : active-low synchronous; m_axis_valid and m_axis_data are
//               forced to zero while resetn is asserted low.
// -----------------------------------------------------------------------------

module axis_upscale (
  input  wire        clk,
  input  wire        resetn,

  input  wire        dfmt_enable,
  input  wire        dfmt_type,
  input  wire        dfmt_se,

  input  wire        s_axis_valid,
  input  wire [23:0] s_axis_data,
  input  wire        m_axis_ready,

  output wire        s_axis_ready,
  output wire        m_axis_valid,
  output wire [31:0] m_axis_data
);

  // ---------------------------------------------------------------------------
  // Combinational data-format (widen) logic.
  //
  // When formatting is enabled, the (optionally inverted) MSB of the slave data
  // REPLACES the original MSB position (bit 23 of the output) and, when sign
  // extension is selected, also drives the eight upper fill bits. When
  // formatting is disabled both format options are ignored and the word is a
  // plain zero-extension of the 24-bit input.
  // ---------------------------------------------------------------------------
  wire        dfmt_type_s;
  wire        dfmt_se_s;
  wire [31:0] wide_data_s;

  assign dfmt_type_s = (dfmt_enable & dfmt_type) ? ~s_axis_data[23]
                                                 :  s_axis_data[23];
  assign dfmt_se_s   = (dfmt_enable & dfmt_se)   ?  dfmt_type_s
                                                 :  1'b0;

  assign wide_data_s = {{8{dfmt_se_s}}, dfmt_type_s, s_axis_data[22:0]};

  // ---------------------------------------------------------------------------
  // Single pipeline register stage on the payload + valid path.
  // ---------------------------------------------------------------------------
  reg         valid_q;
  reg  [31:0] data_q;

  always @(posedge clk) begin
    if (resetn == 1'b0) begin
      valid_q <= 1'b0;
      data_q  <= 32'h0000_0000;
    end else begin
      valid_q <= s_axis_valid;
      data_q  <= wide_data_s;
    end
  end

  // ---------------------------------------------------------------------------
  // Handshake: ready is passed straight through combinationally.
  // ---------------------------------------------------------------------------
  assign s_axis_ready = m_axis_ready;
  assign m_axis_valid = valid_q;
  assign m_axis_data  = data_q;

endmodule
