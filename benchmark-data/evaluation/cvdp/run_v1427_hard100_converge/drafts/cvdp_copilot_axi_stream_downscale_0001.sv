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

  // ---------------------------------------------------------------
  // 16-bit -> 8-bit AXI-Stream width downsizer.
  //
  // One accepted slave transfer is split into two master beats:
  //   beat 0 : high byte  s_data[15:8]
  //   beat 1 : low  byte  s_data[7:0]
  //
  // The wide word is captured into a holding register on the
  // accepting cycle and every sub-word is emitted from that
  // captured copy (never from the live s_data, which may change).
  // s_ready is deasserted for the whole multi-beat drain so the
  // slave word cannot be overwritten mid-split.  All outputs are
  // registered and cleared by the active-low synchronous reset.
  // ---------------------------------------------------------------

  localparam [1:0] ST_IDLE = 2'd0,   // waiting for a slave word
                   ST_HIGH = 2'd1,   // high byte currently on m_data
                   ST_LOW  = 2'd2;   // low  byte currently on m_data

  reg [1:0] state;
  reg [7:0] low_byte;                // holding register for beat 1

  always @(posedge clk) begin
    if (!resetn) begin
      state    <= ST_IDLE;
      s_ready  <= 1'b0;
      m_valid  <= 1'b0;
      m_data   <= 8'd0;
      low_byte <= 8'd0;
    end else begin
      case (state)

        ST_IDLE: begin
          s_ready <= 1'b1;
          if (s_valid && s_ready) begin
            // Accepting cycle: capture the wide word, present the
            // high byte first, and stall the slave for the drain.
            low_byte <= s_data[7:0];
            m_data   <= s_data[15:8];
            m_valid  <= 1'b1;
            s_ready  <= 1'b0;
            state    <= ST_HIGH;
          end
        end

        ST_HIGH: begin
          // High byte is being presented; advance only on handshake.
          if (m_valid && m_ready) begin
            m_data <= low_byte;
            state  <= ST_LOW;
          end
        end

        ST_LOW: begin
          // Low byte is being presented; on handshake the split is
          // complete, re-open the slave side.
          if (m_valid && m_ready) begin
            m_valid <= 1'b0;
            s_ready <= 1'b1;
            state   <= ST_IDLE;
          end
        end

        default: begin
          state   <= ST_IDLE;
          s_ready <= 1'b0;
          m_valid <= 1'b0;
        end

      endcase
    end
  end

endmodule
