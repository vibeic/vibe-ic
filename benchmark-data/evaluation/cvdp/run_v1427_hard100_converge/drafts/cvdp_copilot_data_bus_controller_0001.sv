// -----------------------------------------------------------------------------
// data_bus_controller
// -----------------------------------------------------------------------------
// Two master ready-valid interfaces (m0, m1) arbitrated onto a single slave
// ready-valid interface.
//
//  - The slave's ready (s_read) is transferred directly to both masters'
//    ready outputs (m0_read, m1_read).
//  - A master transaction is accepted on a cycle where its valid and its
//    ready are both high; the accepted transaction is presented to the slave
//    one cycle later (one-cycle latency, registered s_valid / s_data).
//  - Different-cycle requests are served first come, first served.
//  - If both masters present a valid transaction in the SAME cycle, the
//    parameter AFINITY selects the winner:
//        AFINITY == 0 -> m0 transaction is driven to the slave, m1 ignored
//        AFINITY == 1 -> m1 transaction is driven to the slave, m0 ignored
//  - Once s_valid is asserted, s_data is held stable until the slave accepts
//    the transfer (s_valid && s_read in the same cycle).
// -----------------------------------------------------------------------------
module data_bus_controller #(
  parameter AFINITY = 0
  )(
  input         clk      ,
  input         rst_n    ,

  output        m0_read  ,
  input         m0_valid ,
  input [31:0]  m0_data  ,

  output        m1_read  ,
  input         m1_valid ,
  input [31:0]  m1_data  ,

  input         s_read   ,
  output        s_valid  ,
  output [31:0] s_data
);

  // ---------------------------------------------------------------------------
  // Slave ready transferred to both masters' ready outputs
  // ---------------------------------------------------------------------------
  assign m0_read = s_read;
  assign m1_read = s_read;

  // ---------------------------------------------------------------------------
  // Handshake detection (valid && ready high in the same cycle)
  // ---------------------------------------------------------------------------
  wire m0_hs = m0_valid & m0_read;
  wire m1_hs = m1_valid & m1_read;

  // Winner selection:
  //  - both masters handshake in the same cycle -> AFINITY decides
  //      (the losing master's transaction is ignored)
  //  - otherwise the single handshaking master is taken (FCFS)
  wire        take_m1  = (m0_hs & m1_hs) ? (AFINITY != 0) : m1_hs;
  wire [31:0] mux_data = take_m1 ? m1_data : m0_data;

  // ---------------------------------------------------------------------------
  // One-cycle-latency registered slave interface.
  // The registered beat is held stable until the slave takes it
  // (s_valid && s_read handshake), per the ready-valid protocol.
  // ---------------------------------------------------------------------------
  reg        s_valid_q;
  reg [31:0] s_data_q;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      s_valid_q <= 1'b0;
      s_data_q  <= 32'd0;
    end else begin
      if (m0_hs | m1_hs) begin
        // New transaction accepted this cycle. The slave was ready this
        // cycle (m*_read == s_read), so any currently presented beat is
        // consumed in this same cycle; loading a new beat is safe.
        s_valid_q <= 1'b1;
        s_data_q  <= mux_data;
      end else if (s_valid_q && s_read) begin
        // Presented beat consumed by the slave, no new transaction.
        s_valid_q <= 1'b0;
      end
      // else: hold s_valid_q / s_data_q until the slave accepts.
    end
  end

  assign s_valid = s_valid_q;
  assign s_data  = s_data_q;

endmodule
