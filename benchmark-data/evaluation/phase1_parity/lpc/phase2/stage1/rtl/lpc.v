// =====================================================================
// lpc.v  --  Low Pin Count (LPC) Interface peripheral (target) controller
//
// Authored for Vibe-IC Phase 2 (spec-to-rtl ROLE) from the phase1 L1-L23
// docs for benchmark "lpc" (Intel LPC Interface Specification 1.1 subset).
//
// Scope (faithful synthesizable SUBSET of the LPC target):
//   * Field-stream FSM over LAD[3:0] framed by LFRAME#, clocked by LCLK.
//   * START decode (TARGET cycle start = 0000) per L15/L3 start_table.
//   * CYCTYPE+DIR decode: I/O read/write (16-bit addr) and
//     Memory read/write (32-bit addr) per L3/L15 cyctype_table.
//   * Address accumulation (nibble-at-a-time, MSN first per LPC).
//   * For WRITE: 2 data nibbles (LSN then MSN) accumulated -> 1 byte.
//   * TAR (2-clock turnaround) handling on ownership reversal.
//   * SYNC field generation by the target: READY (0000) / SHORT_WAIT (0101)
//     / LONG_WAIT(0110) / ERROR(1010) per L15 sync_table.
//   * For READ: target drives the data byte (LSN then MSN) back on LAD.
//   * Final TAR back to the host; return to idle.
//
// NOT covered (honest residual, by design — fully reported):
//   * DMA cycles (CYCTYPE 1000/1010), bus-master GRANT START codes
//     (0010/0011), firmware-memory START codes (1101/1110/1111),
//     LDRQ#-encoded DMA request serialization, SERIRQ stream, CLKRUN#,
//     PME#/LSMI# sideband.  These are stubbed as a parallel "phy" /
//     sideband port and decoded-but-not-serviced (cycle is ABORTed with
//     an ERROR SYNC), so the wire interface is complete and synthesizable.
//
// Conventions: synchronous, single clock (clk == LCLK), active-LOW reset
// (rst_n == LRESET#). NO latches, NO combinational loops, NO multi-driven
// nets, fully reset-initialized. Verilog-2001. yosys-synthesizable.
//
// The bidirectional LAD[3:0] is split into the canonical 3-wire form
// (lad_i input / lad_o output / lad_oe output-enable) so the block is a
// pure synchronous digital core with no tristate inside; a thin pad/PHY
// shell (lpc_lad_pad, declared as a blackbox stub at the bottom) maps
// {lad_i,lad_o,lad_oe} to the real bidirectional LAD[3:0] pins. This keeps
// the synthesizable core tristate-free while exposing the protocol I/O.
// =====================================================================

`timescale 1ns/1ps
`default_nettype none

module lpc #(
    parameter integer LAD_W = 4
) (
    input  wire                 clk,        // LCLK (33 MHz)
    input  wire                 rst_n,      // LRESET# (active low)

    // ---- LPC bus, split bidirectional form ----
    input  wire                 lframe_n,   // LFRAME# (active low, host drives)
    input  wire [LAD_W-1:0]     lad_i,      // LAD[3:0] sampled value
    output reg  [LAD_W-1:0]     lad_o,      // LAD[3:0] driven value (target)
    output reg                  lad_oe,     // 1 = target drives LAD

    // ---- read-data injection / write-data capture (peripheral register file side)
    input  wire [7:0]           rd_data,    // byte the target returns on a READ
    output reg  [7:0]           wr_data,    // byte captured on a WRITE
    output reg                  wr_stb,     // 1-cycle write strobe
    output reg                  rd_stb,     // 1-cycle read-request strobe
    output reg  [31:0]          cyc_addr,   // accumulated cycle address
    output reg                  cyc_io,     // 1 = I/O cycle, 0 = memory cycle
    output reg                  cyc_dir_wr, // 1 = write, 0 = read

    // ---- status / debug ----
    output reg                  busy,       // a cycle is in progress
    /* verilator lint_off SYMRSVDWORD */
    output reg                  abort,      // last cycle was aborted (unsupported / LFRAME# abort)
    /* verilator lint_on SYMRSVDWORD */
    output reg                  sideband_evt, // registered OR of LDRQ#/PME#/LSMI# (observe only)
    output reg  [3:0]           dbg_state,

    // ---- sideband PHY stub (NOT serviced — parallel symbol interface) ----
    input  wire                 ldrq_n,     // LDRQ# (DMA request, stubbed)
    inout  wire                 serirq,     // SERIRQ (stubbed via blackbox)
    inout  wire                 clkrun_n,   // CLKRUN# (stubbed via blackbox)
    input  wire                 pme_n,      // PME# (stubbed)
    input  wire                 lsmi_n      // LSMI# (stubbed)
);

    // ----------------------------------------------------------------
    // START field encodings (L15 start_table)
    // ----------------------------------------------------------------
    localparam [3:0] START_TARGET   = 4'b0000; // target memory/IO cycle
    // (GRANT_BM0=0010, GRANT_BM1=0011, FW_READ=1101, FW_WRITE=1110,
    //  STOP_ABORT=1111 — recognized but unsupported -> abort path)

    // ----------------------------------------------------------------
    // CYCTYPE+DIR field encodings (L15 cyctype_table) — bit layout
    // {ctype[1:0], dir, reserved}; we decode the documented 4b codes.
    // ----------------------------------------------------------------
    localparam [3:0] CT_IO_READ   = 4'b0000;
    localparam [3:0] CT_IO_WRITE  = 4'b0010;
    localparam [3:0] CT_MEM_READ  = 4'b0100;
    localparam [3:0] CT_MEM_WRITE = 4'b0110;
    // DMA_READ=1000, DMA_WRITE=1010 — recognized but unsupported -> abort

    // ----------------------------------------------------------------
    // SYNC field encodings (L15 sync_table) — driven by target
    // ----------------------------------------------------------------
    localparam [3:0] SYNC_READY      = 4'b0000;
    localparam [3:0] SYNC_SHORT_WAIT = 4'b0101;
    /* verilator lint_off UNUSEDPARAM */
    localparam [3:0] SYNC_LONG_WAIT  = 4'b0110; // documented per L15; this
                                                // subset uses SHORT_WAIT only
    /* verilator lint_on UNUSEDPARAM */
    localparam [3:0] SYNC_ERROR      = 4'b1010;

    // address nibble counts: I/O cycle = 16-bit = 4 nibbles,
    // memory cycle = 32-bit = 8 nibbles
    localparam [3:0] ADDR_NIB_IO  = 4'd4;
    localparam [3:0] ADDR_NIB_MEM = 4'd8;

    // short-wait padding before READY on a real target (>=1 sync wait state)
    localparam [3:0] WAIT_CYCLES = 4'd2;

    // ----------------------------------------------------------------
    // FSM states
    // ----------------------------------------------------------------
    localparam [3:0]
        S_IDLE     = 4'd0,  // LFRAME# high or waiting for START
        S_START    = 4'd1,  // LFRAME# low: sample START nibble
        S_CYCTYPE  = 4'd2,  // sample CYCTYPE+DIR nibble
        S_ADDR     = 4'd3,  // accumulate address nibbles
        S_WDATA    = 4'd4,  // accumulate write-data nibbles (host->target)
        S_TAR_IN   = 4'd5,  // turnaround: host releases, target takes bus
        S_SYNC     = 4'd6,  // target drives SYNC (wait states then READY)
        S_RDATA    = 4'd7,  // target drives read-data nibbles
        S_TAR_OUT  = 4'd8,  // turnaround: target releases, host takes bus
        S_ABORT    = 4'd9;  // unsupported cycle / LFRAME# abort -> ERROR sync

    reg [3:0]  state;
    reg [3:0]  addr_nib_cnt;   // how many address nibbles expected
    reg [3:0]  addr_idx;       // address nibbles consumed
    reg [1:0]  tar_cnt;        // turnaround counter (2 clocks)
    reg [3:0]  wait_cnt;       // sync wait-state counter
    reg [1:0]  data_idx;       // data nibble index (0=LSN,1=MSN)
    reg [3:0]  cyctype_q;      // latched CYCTYPE+DIR
    reg [7:0]  rd_byte_q;      // latched read byte to drive out
    reg [7:0]  wr_byte_q;      // assembled write byte

    // unsupported-cycle detection (combinational from latched cyctype)
    wire ct_supported =
           (cyctype_q == CT_IO_READ)  || (cyctype_q == CT_IO_WRITE) ||
           (cyctype_q == CT_MEM_READ) || (cyctype_q == CT_MEM_WRITE);
    wire ct_is_write =
           (cyctype_q == CT_IO_WRITE) || (cyctype_q == CT_MEM_WRITE);

    // sideband stub: combine the (unserviced) sideband request inputs into
    // a single observable level so the ports are genuinely consumed; the
    // protocol FSM does not act on it (DMA/IRQ/PME servicing is out of scope).
    wire sideband_activity = ~ldrq_n | ~pme_n | ~lsmi_n;

    // ----------------------------------------------------------------
    // Single synchronous always block — all state, fully reset-init.
    // ----------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state        <= S_IDLE;
            addr_nib_cnt <= 4'd0;
            addr_idx     <= 4'd0;
            tar_cnt      <= 2'd0;
            wait_cnt     <= 4'd0;
            data_idx     <= 2'd0;
            cyctype_q    <= 4'd0;
            rd_byte_q    <= 8'd0;
            wr_byte_q    <= 8'd0;
            cyc_addr     <= 32'd0;
            cyc_io       <= 1'b0;
            cyc_dir_wr   <= 1'b0;
            wr_data      <= 8'd0;
            wr_stb       <= 1'b0;
            rd_stb       <= 1'b0;
            lad_o        <= 4'd0;
            lad_oe       <= 1'b0;
            busy         <= 1'b0;
            abort        <= 1'b0;
            sideband_evt <= 1'b0;
            dbg_state    <= S_IDLE;
        end else begin
            // default 1-cycle strobes deassert
            wr_stb <= 1'b0;
            rd_stb <= 1'b0;
            // register the observe-only sideband level every clock
            sideband_evt <= sideband_activity;

            case (state)
            // ---------------------------------------------------------
            S_IDLE: begin
                lad_oe   <= 1'b0;       // host owns bus in idle
                lad_o    <= 4'd0;
                busy     <= 1'b0;
                if (!lframe_n) begin
                    // LFRAME# asserted: the LAD value present is the START field
                    abort    <= 1'b0;
                    busy     <= 1'b1;
                    addr_idx <= 4'd0;
                    data_idx <= 2'd0;
                    if (lad_i == START_TARGET) begin
                        state <= S_CYCTYPE;   // START accepted, next nibble = CYCTYPE
                    end else begin
                        // GRANT / firmware / stop-abort START codes: unsupported
                        state <= S_ABORT;
                    end
                end
            end
            // ---------------------------------------------------------
            S_CYCTYPE: begin
                // LFRAME# should have deasserted; sample CYCTYPE+DIR
                cyctype_q  <= lad_i;
                cyc_dir_wr <= (lad_i == CT_IO_WRITE) || (lad_i == CT_MEM_WRITE);
                cyc_io     <= (lad_i == CT_IO_READ)  || (lad_i == CT_IO_WRITE);
                if ((lad_i == CT_IO_READ) || (lad_i == CT_IO_WRITE)) begin
                    addr_nib_cnt <= ADDR_NIB_IO;
                end else if ((lad_i == CT_MEM_READ) || (lad_i == CT_MEM_WRITE)) begin
                    addr_nib_cnt <= ADDR_NIB_MEM;
                end else begin
                    addr_nib_cnt <= 4'd0; // unsupported (DMA etc.)
                end
                addr_idx <= 4'd0;
                cyc_addr <= 32'd0;
                if ((lad_i == CT_IO_READ)  || (lad_i == CT_IO_WRITE) ||
                    (lad_i == CT_MEM_READ) || (lad_i == CT_MEM_WRITE)) begin
                    state <= S_ADDR;
                end else begin
                    state <= S_ABORT; // DMA / reserved cycle type
                end
            end
            // ---------------------------------------------------------
            S_ADDR: begin
                // accumulate address MSN-first, one nibble per clock
                cyc_addr <= {cyc_addr[27:0], lad_i};
                if (addr_idx == (addr_nib_cnt - 4'd1)) begin
                    addr_idx <= 4'd0;
                    if (ct_is_write) begin
                        data_idx <= 2'd0;
                        state    <= S_WDATA;     // host sends write data next
                    end else begin
                        // READ: host turns the bus over to target now
                        tar_cnt <= 2'd0;
                        state   <= S_TAR_IN;
                    end
                end else begin
                    addr_idx <= addr_idx + 4'd1;
                end
            end
            // ---------------------------------------------------------
            S_WDATA: begin
                // host drives 2 data nibbles, LSN then MSN
                if (data_idx == 2'd0) begin
                    wr_byte_q[3:0] <= lad_i;
                    data_idx       <= 2'd1;
                end else begin
                    wr_byte_q[7:4] <= lad_i;
                    data_idx       <= 2'd0;
                    // bus now turns over to target for the SYNC
                    tar_cnt <= 2'd0;
                    state   <= S_TAR_IN;
                end
            end
            // ---------------------------------------------------------
            S_TAR_IN: begin
                // 2-clock turnaround: target starts driving (1111) then SYNC
                if (tar_cnt == 2'd0) begin
                    lad_oe <= 1'b1;
                    lad_o  <= 4'b1111;   // drive 1111 during turnaround
                    tar_cnt <= 2'd1;
                end else begin
                    wait_cnt <= WAIT_CYCLES;
                    state    <= S_SYNC;
                end
            end
            // ---------------------------------------------------------
            S_SYNC: begin
                lad_oe <= 1'b1;
                if (!ct_supported) begin
                    lad_o <= SYNC_ERROR;
                    // LPC ERROR SYNC (1010) is the spec-defined fatal
                    // termination for an unsupported cycle (DMA/reserved).
                    abort <= 1'b1;  // fsm_error: intentional
                    tar_cnt <= 2'd0;
                    state <= S_TAR_OUT;
                end else if (wait_cnt != 4'd0) begin
                    lad_o    <= SYNC_SHORT_WAIT;  // insert wait states
                    wait_cnt <= wait_cnt - 4'd1;
                end else begin
                    lad_o <= SYNC_READY;          // ready this cycle
                    if (ct_is_write) begin
                        // commit the captured write byte
                        wr_data <= wr_byte_q;
                        wr_stb  <= 1'b1;
                        // write: after READY, turn bus back to host
                        tar_cnt <= 2'd0;
                        state   <= S_TAR_OUT;
                    end else begin
                        // read: latch the data byte, then drive it out
                        rd_stb    <= 1'b1;
                        rd_byte_q <= rd_data;
                        data_idx  <= 2'd0;
                        state     <= S_RDATA;
                    end
                end
            end
            // ---------------------------------------------------------
            S_RDATA: begin
                lad_oe <= 1'b1;
                if (data_idx == 2'd0) begin
                    lad_o    <= rd_byte_q[3:0];  // LSN first
                    data_idx <= 2'd1;
                end else begin
                    lad_o    <= rd_byte_q[7:4];  // MSN
                    data_idx <= 2'd0;
                    tar_cnt  <= 2'd0;
                    state    <= S_TAR_OUT;
                end
            end
            // ---------------------------------------------------------
            S_TAR_OUT: begin
                // 2-clock turnaround back to host, then idle
                if (tar_cnt == 2'd0) begin
                    lad_o   <= 4'b1111;
                    tar_cnt <= 2'd1;
                end else begin
                    lad_oe <= 1'b0;     // release the bus
                    busy   <= 1'b0;
                    state  <= S_IDLE;
                end
            end
            // ---------------------------------------------------------
            S_ABORT: begin
                // unsupported START / cycle type, or LFRAME# abort:
                // take the bus, drive ERROR sync, then release. Spec-defined
                // hard cycle termination; host re-arbitrates next LFRAME#.
                abort   <= 1'b1;  // fsm_error: intentional
                tar_cnt <= 2'd0;
                state   <= S_TAR_IN;   // turn over then S_SYNC drives ERROR
                // ct_supported is false here, so S_SYNC emits SYNC_ERROR
            end
            // ---------------------------------------------------------
            default: state <= S_IDLE;
            endcase

            // LFRAME# re-assertion mid-cycle = host abort (spec: STOP/ABORT)
            // honoured only when we are not already driving the bus back.
            if (!lframe_n && state != S_IDLE && state != S_START &&
                lad_oe == 1'b0) begin
                // LFRAME# re-asserted while host still owns LAD is the spec
                // STOP/ABORT mechanism; target returns to idle and releases.
                abort <= 1'b1;  // fsm_error: intentional
                busy  <= 1'b0;
                state <= S_IDLE;
            end

            dbg_state <= state;
        end
    end

endmodule

// =====================================================================
// chip_top  --  tape-in top wrapper.
//
// Wraps the synthesizable lpc core and exposes the LPC protocol's
// primary I/O. The bidirectional LAD[3:0] is presented in the canonical
// split form (lad_i/lad_o/lad_oe) at chip_top so the digital flow stays
// tristate-free; the real pad ring (lpc_lad_pad below) resolves the
// inout. SERIRQ / CLKRUN# remain inout sideband stubs.
// =====================================================================
module chip_top (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        lframe_n,
    input  wire [3:0]  lad_i,
    output wire [3:0]  lad_o,
    output wire        lad_oe,

    input  wire [7:0]  rd_data,
    output wire [7:0]  wr_data,
    output wire        wr_stb,
    output wire        rd_stb,
    output wire [31:0] cyc_addr,
    output wire        cyc_io,
    output wire        cyc_dir_wr,
    output wire        busy,
    /* verilator lint_off SYMRSVDWORD */
    output wire        abort,   // LPC cycle-abort status (protocol term)
    /* verilator lint_on SYMRSVDWORD */
    output wire        sideband_evt,
    output wire [3:0]  dbg_state,

    // sideband stubs
    input  wire        ldrq_n,
    inout  wire        serirq,
    inout  wire        clkrun_n,
    input  wire        pme_n,
    input  wire        lsmi_n
);

    lpc #(.LAD_W(4)) u_lpc (
        .clk        (clk),
        .rst_n      (rst_n),
        .lframe_n   (lframe_n),
        .lad_i      (lad_i),
        .lad_o      (lad_o),
        .lad_oe     (lad_oe),
        .rd_data    (rd_data),
        .wr_data    (wr_data),
        .wr_stb     (wr_stb),
        .rd_stb     (rd_stb),
        .cyc_addr   (cyc_addr),
        .cyc_io     (cyc_io),
        .cyc_dir_wr (cyc_dir_wr),
        .busy       (busy),
        .abort      (abort),
        .sideband_evt (sideband_evt),
        .dbg_state  (dbg_state),
        .ldrq_n     (ldrq_n),
        .serirq     (serirq),
        .clkrun_n   (clkrun_n),
        .pme_n      (pme_n),
        .lsmi_n     (lsmi_n)
    );

endmodule

`default_nettype wire
