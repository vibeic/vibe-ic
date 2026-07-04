module axis_resize (

  input                                           clk,          //Global clock signal: Signals are sampled on the rising edge of clk
  input                                           resetn,       //The global reset signal: resetn is synchronous active-LOW reset.

  input                                           s_valid,      //The s_axis_valid signal indicates that the slave is driving a valid transfer.
  output  reg                                     s_ready,      //The s_axis_ready indicates that the slave can accept a transfer in the current cycle.
  input       [15:0]  s_data,                                   //The s_axis_data is the primary payload data from slave.

  output  reg                                     m_valid,      //The m_axis_valid indicates that the master is driving a valid transfer.
  input                                           m_ready,      //The m_axis_ready indicates that the slave can accept a transfer in the current cycle.
  output  reg [7:0] m_data                                      //The m_axis_data is the primary payload data to master.
);

  // 2:1 downsizer: one 16-bit slave word becomes two 8-bit master beats.
  // phase 0 : accept a new word and present its high byte
  // phase 1 : present the low byte of the captured word
  reg        phase;
  reg [15:0] data_q;

  always @(posedge clk) begin
    if (!resetn) begin
      phase   <= 1'b0;
      s_ready <= 1'b1;
      m_valid <= 1'b0;
      m_data  <= 8'b0;
      data_q  <= 16'b0;
    end else begin
      if (phase == 1'b0) begin
        if (s_valid) begin
          // capture word, drive high byte first
          data_q  <= s_data;
          m_data  <= s_data[15:8];
          m_valid <= 1'b1;
          s_ready <= 1'b0;
          phase   <= 1'b1;
        end else begin
          // idle: ready for a new word, nothing to drive
          m_valid <= 1'b0;
          s_ready <= 1'b1;
          phase   <= 1'b0;
        end
      end else begin
        // low byte of the captured word
        m_data  <= data_q[7:0];
        m_valid <= 1'b1;
        s_ready <= 1'b1;
        phase   <= 1'b0;
      end
    end
  end

endmodule
