module ping_pong_fifo_2_axi_stream #(
  parameter int                                DATA_WIDTH          = 24,
  parameter int                                STROBE_WIDTH        = DATA_WIDTH / 8,
  parameter int                                USE_KEEP            = 0,
  parameter int                                USER_IN_DATA        = 1
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

  // Internal control state
  localparam logic [2:0] ST_IDLE    = 3'd0,
                         ST_REQ     = 3'd1,
                         ST_WAIT    = 3'd2,
                         ST_PRESENT = 3'd3,
                         ST_STREAM  = 3'd4;

  logic [2:0]  state;
  logic [23:0] word_count;

  // The strobed word is the last beat of the block when the FIFO word
  // carries its own last marker (MSB of i_block_fifo_data) or when this is
  // the final word of the advertised block size.
  logic        last_word;
  assign last_word = i_block_fifo_data[DATA_WIDTH] ||
                     (word_count + 24'd1 >= i_block_fifo_size);

  always_ff @(posedge i_axi_clk or posedge rst) begin
    if (rst) begin
      state            <= ST_IDLE;
      o_block_fifo_act <= 1'b0;
      o_block_fifo_stb <= 1'b0;
      o_axi_valid      <= 1'b0;
      o_axi_data       <= '0;
      o_axi_last       <= 1'b0;
      o_axi_user       <= 4'b0;
      word_count       <= 24'd0;
    end else begin
      // Strobe is a single-cycle read pulse: default low every cycle.
      o_block_fifo_stb <= 1'b0;

      case (state)
        // ------------------------------------------------------------
        // Idle: wait for the FIFO to advertise a ready block.
        // ------------------------------------------------------------
        ST_IDLE: begin
          o_axi_valid      <= 1'b0;
          o_block_fifo_act <= 1'b0;
          if (i_block_fifo_rdy) begin
            o_block_fifo_act <= 1'b1;   // claim the block
            word_count       <= 24'd0;
            state            <= ST_REQ;
          end
        end

        // ------------------------------------------------------------
        // Request: strobe the FIFO to read the current word.  The FIFO
        // presents the word on i_block_fifo_data in response to stb.
        // ------------------------------------------------------------
        ST_REQ: begin
          o_block_fifo_stb <= 1'b1;
          state            <= ST_WAIT;
        end

        // ------------------------------------------------------------
        // Wait: allow the FIFO one cycle to present the strobed word on
        // i_block_fifo_data before it is latched.
        // ------------------------------------------------------------
        ST_WAIT: begin
          state <= ST_PRESENT;
        end

        // ------------------------------------------------------------
        // Present: the strobed word is now valid on i_block_fifo_data.
        // Latch it and drive it onto the AXI-Stream interface.
        // ------------------------------------------------------------
        ST_PRESENT: begin
          o_axi_data  <= i_block_fifo_data[DATA_WIDTH-1:0];
          // Last beat: either the FIFO word carries its own last marker
          // (top bit) or this is the final word of the advertised block.
          o_axi_last  <= last_word;
          o_axi_user  <= i_axi_user;
          o_axi_valid <= 1'b1;
          // The word has already been strobed out of the FIFO, so once the
          // final word of the block is read the block claim can be released
          // immediately; the AXI handshake completes independently.
          if (last_word) begin
            o_block_fifo_act <= 1'b0;
          end
          state       <= ST_STREAM;
        end

        // ------------------------------------------------------------
        // Stream: hold the beat until the AXI sink accepts it
        // (o_axi_valid && i_axi_ready).  Then either finish the block or
        // fetch the next word.
        // ------------------------------------------------------------
        ST_STREAM: begin
          if (o_axi_valid && i_axi_ready) begin
            o_axi_valid <= 1'b0;
            if (o_axi_last) begin
              o_block_fifo_act <= 1'b0;   // block already released
              state            <= ST_IDLE;
            end else begin
              word_count  <= word_count + 24'd1;
              state       <= ST_REQ;       // read the next word
            end
          end
        end

        default: state <= ST_IDLE;
      endcase
    end
  end

endmodule
