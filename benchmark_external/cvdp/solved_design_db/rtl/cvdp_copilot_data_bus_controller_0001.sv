module data_bus_controller #(
  parameter AFINITY = 0
  )(
  input         clk      ,
  input         rst_n    ,

  output        m0_ready ,
  input         m0_valid ,
  input [31:0]  m0_data  ,

  output        m1_ready ,
  input         m1_valid ,
  input [31:0]  m1_data  ,

  input         s_ready  ,
  output        s_valid  ,
  output [31:0] s_data
);

  // -----------------------------------------------------------------
  // Arbitration.  Both masters use a ready/valid handshake; one slave
  // accepts a single transaction per cycle.  On a same-cycle collision
  // AFINITY breaks the tie (0 -> m0 wins, 1 -> m1 wins); otherwise the
  // lone asserting master is served.
  //
  // The arbitration is written as procedural if/else priority so that an
  // un-driven (X) master valid is treated as "not requesting" (an `if`
  // condition that is X is taken as false) instead of poisoning the
  // selection with X.  The AFINITY-preferred master is tested first with
  // a bare `if (valid)`; the other master is the fallback.  This serves a
  // single asserting master correctly regardless of AFINITY and never
  // forwards X to the registered slave-side beat.
  // -----------------------------------------------------------------
  reg sel0, sel1;
  always @(*) begin
    sel0 = 1'b0;
    sel1 = 1'b0;
    if (AFINITY == 0) begin
      if (m0_valid)      sel0 = 1'b1;
      else if (m1_valid) sel1 = 1'b1;
    end else begin
      if (m1_valid)      sel1 = 1'b1;
      else if (m0_valid) sel0 = 1'b1;
    end
  end

  // One-cycle design latency: the slave-side beat is registered.
  reg        s_valid_r;
  reg [31:0] s_data_r;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      s_valid_r <= 1'b0;
      s_data_r  <= 32'b0;
    end else begin
      if (sel0) begin
        s_valid_r <= 1'b1;
        s_data_r  <= m0_data;
      end else if (sel1) begin
        s_valid_r <= 1'b1;
        s_data_r  <= m1_data;
      end else begin
        s_valid_r <= 1'b0;
      end
    end
  end

  assign s_valid = s_valid_r;
  assign s_data  = s_data_r;

  // The slave's ready is transferred back to the selected master only.
  assign m0_ready = sel0 & s_ready;
  assign m1_ready = sel1 & s_ready;

endmodule
