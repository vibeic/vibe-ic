// ============================================================================
// ahb_apb_gpio.v  —  AHB-Lite Subordinate  ->  AHB-to-APB Bridge  ->  APB GPIO
// ----------------------------------------------------------------------------
// A canonical SoC integration block, authored BLIND from the Phase-1 L-docs of
// the AMBA AHB-Lite (ARM IHI 0033C) + APB (ARM IHI 0024C) specifications:
//   - L17  exact signal names / widths / directions for AHB-Lite + APB
//   - L6   APB FSM IDLE -> SETUP -> ACCESS  (PSELx/PENABLE/PREADY handshake)
//          AHB-Lite Subordinate per-transfer FSM (sample on HREADY, wait via
//          HREADYOUT, OKAY response)
//   - L8   width parameters, HTRANS encoding (IDLE/BUSY/NONSEQ/SEQ),
//          HRESP OKAY/ERROR, apb_min_transfer_cycles=2
//   - L9   AHB-to-APB bridge role (AHB Subordinate + APB Manager; PSLVERR->HRESP)
//
// Design unit choice (stated): an APB GPIO peripheral *with a register file*
// fronted by an AHB-Lite-to-APB bridge.  This is THE canonical SoC integration
// block: it exercises (a) the AHB-Lite subordinate address/data pipeline +
// HREADYOUT wait-state insertion, (b) the APB SETUP/ACCESS 2-cycle FSM with the
// PSEL/PENABLE/PREADY handshake, and (c) a register decode / write-read-back
// register file driving real GPIO pads.
//
// Signoff-friendliness (stated): SINGLE clock domain (HCLK == PCLK), SYNCHRONOUS
// active-low reset (HRESETn), NO latches, no tri-state inside the core (GPIO pad
// direction is exported as gpio_out + gpio_oe so a real pad ring can build the
// bidirectional pin).  All registers are flip-flops.
//
// Blind doctrine: authored from the L-docs + AMBA protocol knowledge only;
// no reference AHB/APB RTL was read.
// ============================================================================

// ----------------------------------------------------------------------------
// APB GPIO peripheral (APB3 Subordinate) with a 4-register file.
//   Register map (PADDR[3:2] word-select, byte addresses 0x0/0x4/0x8/0xC):
//     0x0  GPIO_DATA  R/W   output data driven onto pads (when DIR bit = 1)
//     0x4  GPIO_DIR   R/W   direction: 1 = output (drive), 0 = input (hi-Z)
//     0x8  GPIO_IN    RO    live synchronized value sampled from the input pads
//     0xC  GPIO_CTRL  R/W   control: bit0 = soft-clear DATA on write of 1 (W1C-ish)
//   Fixed-2-cycle peripheral: PREADY tied HIGH (per L6
//   default_ready_state_recommendation: "Fixed-2-cycle peripherals may tie
//   PREADY HIGH").  PSLVERR tied LOW (no error class for in-range word access).
// ----------------------------------------------------------------------------
module apb_gpio #(
    parameter integer PADDR_WIDTH = 12,   // APB address width (L8: up to 32)
    parameter integer PDATA_WIDTH = 32,   // APB data width   (L8: up to 32)
    parameter integer GPIO_WIDTH  = 8     // number of GPIO pads
) (
    input  wire                      PCLK,     // L17 APB clock
    input  wire                      PRESETn,  // L17 APB reset, active LOW
    // ---- APB Subordinate interface (driven by the bridge) ----
    input  wire [PADDR_WIDTH-1:0]    PADDR,    // L17 APB address bus
    input  wire                      PSEL,     // L17 per-peripheral select
    input  wire                      PENABLE,  // L17 second cycle of transfer
    input  wire                      PWRITE,   // L17 1=write, 0=read
    input  wire [PDATA_WIDTH-1:0]    PWDATA,   // L17 write data
    output reg  [PDATA_WIDTH-1:0]    PRDATA,   // L17 read data
    output wire                      PREADY,   // L17 slave ready
    output wire                      PSLVERR,  // L17 transfer failure (optional)
    // ---- GPIO pads (split bidirectional for clean synthesis) ----
    output wire [GPIO_WIDTH-1:0]     gpio_out, // value to drive onto pads
    output wire [GPIO_WIDTH-1:0]     gpio_oe,  // 1 = drive (output), 0 = hi-Z
    input  wire [GPIO_WIDTH-1:0]     gpio_in   // value sampled from pads
);
    // Register file
    reg [GPIO_WIDTH-1:0] r_data;   // 0x0 GPIO_DATA
    reg [GPIO_WIDTH-1:0] r_dir;    // 0x4 GPIO_DIR
    reg [GPIO_WIDTH-1:0] r_ctrl;   // 0xC GPIO_CTRL
    reg [GPIO_WIDTH-1:0] r_in_sync;// double-flop synchronizer for gpio_in (CDC)
    reg [GPIO_WIDTH-1:0] r_in_meta;

    // Fixed-2-cycle peripheral: always ready, never errors (L6/L8).
    assign PREADY  = 1'b1;
    assign PSLVERR = 1'b0;

    // Drive pads: output value gated by direction; output-enable = direction.
    assign gpio_out = r_data;
    assign gpio_oe  = r_dir;

    // APB ACCESS-phase qualifiers per L6 FSM: PSEL & PENABLE define ACCESS.
    wire apb_access = PSEL & PENABLE;          // we are in the ACCESS phase
    wire apb_wr     = apb_access & PWRITE;      // write strobe (ACCESS + PWRITE)
    wire [1:0] word_sel = PADDR[3:2];           // word-aligned register select

    // ------------------------------------------------------------------
    // Write path + input synchronizer (synchronous active-low reset).
    // ------------------------------------------------------------------
    always @(posedge PCLK) begin
        if (!PRESETn) begin
            r_data    <= {GPIO_WIDTH{1'b0}};
            r_dir     <= {GPIO_WIDTH{1'b0}};   // all inputs on reset (safe)
            r_ctrl    <= {GPIO_WIDTH{1'b0}};
            r_in_meta <= {GPIO_WIDTH{1'b0}};
            r_in_sync <= {GPIO_WIDTH{1'b0}};
        end else begin
            // 2-flop input synchronizer (gpio_in is asynchronous to PCLK)
            r_in_meta <= gpio_in;
            r_in_sync <= r_in_meta;

            // Soft-clear: if CTRL bit0 set, DATA self-clears next cycle
            if (r_ctrl[0])
                r_data <= {GPIO_WIDTH{1'b0}};

            if (apb_wr) begin
                case (word_sel)
                    2'd0: r_data <= PWDATA[GPIO_WIDTH-1:0]; // GPIO_DATA
                    2'd1: r_dir  <= PWDATA[GPIO_WIDTH-1:0]; // GPIO_DIR
                    // 2'd2 GPIO_IN is read-only; writes ignored
                    2'd3: r_ctrl <= PWDATA[GPIO_WIDTH-1:0]; // GPIO_CTRL
                    default: ;
                endcase
            end
        end
    end

    // ------------------------------------------------------------------
    // Read path: combinational mux on word_sel, registered nowhere needed
    // (APB read data is sampled by the master in ACCESS; combinational is fine).
    // ------------------------------------------------------------------
    always @(*) begin
        PRDATA = {PDATA_WIDTH{1'b0}};
        case (word_sel)
            2'd0: PRDATA[GPIO_WIDTH-1:0] = r_data;
            2'd1: PRDATA[GPIO_WIDTH-1:0] = r_dir;
            2'd2: PRDATA[GPIO_WIDTH-1:0] = r_in_sync; // live input pads
            2'd3: PRDATA[GPIO_WIDTH-1:0] = r_ctrl;
            default: PRDATA = {PDATA_WIDTH{1'b0}};
        endcase
    end
endmodule


// ----------------------------------------------------------------------------
// AHB-Lite Subordinate  ->  APB Manager bridge.
//   Per L9 ahb_to_apb_bridge_role: appears as an AHB Subordinate and the APB
//   Manager; inserts AHB wait states while completing the multi-cycle APB
//   transfer; APB PSLVERR maps to AHB HRESP=ERROR.
//
//   AHB-Lite Subordinate FSM (L6 ahb_subordinate_per_transfer_fsm):
//     - Sample HSEL/HADDR/HTRANS/HWRITE only when HREADY=HIGH (addr phase).
//     - For HTRANS=IDLE/BUSY: zero-wait OKAY, transfer ignored.
//     - For HTRANS=NONSEQ/SEQ: perform access; drive HREADYOUT=LOW to wait.
//     - On completion: HREADYOUT=HIGH with HRESP=OKAY.
//
//   APB Manager FSM (L6 apb_fsm_states / apb_fsm_transitions):
//     IDLE  (PSEL=0,PENABLE=0)
//       -> SETUP  on transfer-required
//     SETUP (PSEL=1,PENABLE=0)  drive PADDR/PWRITE/PWDATA
//       -> ACCESS unconditional next PCLK
//     ACCESS(PSEL=1,PENABLE=1)  sample PREADY/PRDATA/PSLVERR
//       -> ACCESS while PREADY=0 (wait)
//       -> IDLE   on PREADY=1 + no further transfer
// ----------------------------------------------------------------------------
module ahb_apb_bridge #(
    parameter integer HADDR_WIDTH = 32,
    parameter integer HDATA_WIDTH = 32,   // bridge supports 32-bit AHB/APB
    parameter integer PADDR_WIDTH = 12
) (
    // ---- AHB-Lite global (L17 global signals) ----
    input  wire                      HCLK,      // bus clock
    input  wire                      HRESETn,   // bus reset, active LOW
    // ---- AHB-Lite Subordinate interface (L17 manager->subordinate) ----
    input  wire                      HSEL,      // L17 decoder select (HSELx)
    input  wire [HADDR_WIDTH-1:0]    HADDR,     // L17 byte address
    input  wire [1:0]                HTRANS,    // L17 transfer type
    input  wire                      HWRITE,    // L17 1=write
    input  wire [2:0]                HSIZE,     // L17 transfer size (unused decode)
    input  wire [2:0]                HBURST,    // L17 burst type (single only used)
    input  wire [HDATA_WIDTH-1:0]    HWDATA,    // L17 write data
    input  wire                      HREADY,    // L17 combined ready (mux in)
    output wire [HDATA_WIDTH-1:0]    HRDATA,    // L17 read data
    output reg                       HREADYOUT, // L17 per-subordinate ready
    output reg                       HRESP,     // L17 0=OKAY 1=ERROR (2-cycle)
    // ---- APB Manager interface (L17 bridge->subordinate) ----
    output reg  [PADDR_WIDTH-1:0]    PADDR,
    output reg                       PSEL,
    output reg                       PENABLE,
    output reg                       PWRITE,
    output reg  [HDATA_WIDTH-1:0]    PWDATA,
    input  wire [HDATA_WIDTH-1:0]    PRDATA,
    input  wire                      PREADY,
    input  wire                      PSLVERR
);
    // HTRANS encoding (L8 ahb_transfer_type_encoding_HTRANS)
    localparam [1:0] HTRANS_IDLE   = 2'b00;
    localparam [1:0] HTRANS_BUSY   = 2'b01;
    localparam [1:0] HTRANS_NONSEQ = 2'b10;
    localparam [1:0] HTRANS_SEQ    = 2'b11;

    // APB Manager FSM states (L6 apb_fsm_states)
    localparam [1:0] ST_IDLE   = 2'd0;
    localparam [1:0] ST_SETUP  = 2'd1;
    localparam [1:0] ST_ACCESS = 2'd2;

    reg [1:0] state, state_n;

    // Latched address-phase request (sampled when HREADY=HIGH).
    reg                    req_valid;   // a NONSEQ/SEQ access is pending
    reg                    req_write;
    reg [PADDR_WIDTH-1:0]  req_addr;
    reg [HDATA_WIDTH-1:0]  req_wdata;   // write data captured in the data phase
    reg                    wdata_pend;  // a write whose data phase is due next cyc

    // AHB address phase is "valid access" only for NONSEQ/SEQ + HSEL + HREADY.
    wire ahb_active = HSEL & HREADY & (HTRANS == HTRANS_NONSEQ ||
                                       HTRANS == HTRANS_SEQ);

    // Read data + error captured at end of APB ACCESS, returned in AHB data phase.
    reg [HDATA_WIDTH-1:0] rdata_q;
    reg                   err_q;     // sticky over the 2-cycle ERROR response

    assign HRDATA = rdata_q;

    // ------------------------------------------------------------------
    // Address-phase capture.  Per L6 the AHB pipeline lets the address phase
    // of transfer N+1 overlap the data phase of transfer N, so we must latch
    // a presented NONSEQ/SEQ address phase whenever HREADY is HIGH, regardless
    // of the APB FSM state, and hold it until the FSM consumes it.  The FSM
    // clears req_valid (req_consume) on the cycle it enters SETUP.
    // HWDATA is valid in the *data* phase (one cycle after the address phase);
    // PWDATA is therefore captured from HWDATA at the SETUP entry, not here.
    // ------------------------------------------------------------------
    reg req_consume;   // pulses HIGH the cycle the FSM accepts req into SETUP
    always @(posedge HCLK) begin
        if (!HRESETn) begin
            req_valid  <= 1'b0;
            req_write  <= 1'b0;
            req_addr   <= {PADDR_WIDTH{1'b0}};
            req_wdata  <= {HDATA_WIDTH{1'b0}};
            wdata_pend <= 1'b0;
        end else begin
            // Latch a new address-phase request when the bus presents one and
            // we are not already holding an unconsumed request.
            if (HREADY && ahb_active && !req_valid) begin
                req_valid  <= 1'b1;
                req_write  <= HWRITE;
                req_addr   <= HADDR[PADDR_WIDTH-1:0];
                // a write's data phase arrives on the NEXT cycle: flag it
                wdata_pend <= HWRITE;
            end else if (req_consume) begin
                req_valid  <= 1'b0;   // FSM has taken the request into SETUP
            end
            // Capture HWDATA exactly one cycle after the address phase
            // (the AHB data phase), independent of the APB FSM progress.
            if (wdata_pend) begin
                req_wdata  <= HWDATA;
                wdata_pend <= 1'b0;
            end
        end
    end

    // ------------------------------------------------------------------
    // APB Manager FSM — next-state (L6 apb_fsm_transitions).
    // ------------------------------------------------------------------
    // A request is ready to launch when it is valid AND (it is a read OR its
    // write data has already been captured, i.e. wdata_pend has cleared).
    wire req_ready = req_valid & (~req_write | ~wdata_pend);

    always @(*) begin
        state_n = state;
        case (state)
            ST_IDLE:   state_n = (req_ready) ? ST_SETUP : ST_IDLE;
            ST_SETUP:  state_n = ST_ACCESS;                 // unconditional
            ST_ACCESS: state_n = (PREADY) ? ST_IDLE         // PREADY=1 -> done
                                          : ST_ACCESS;       // PREADY=0 -> wait
            default:   state_n = ST_IDLE;
        endcase
    end

    // ------------------------------------------------------------------
    // APB outputs + AHB response (registered).  PSEL/PENABLE per L6 table:
    //   SETUP : PSEL=1, PENABLE=0
    //   ACCESS: PSEL=1, PENABLE=1
    //   IDLE  : PSEL=0, PENABLE=0
    // AHB HREADYOUT is LOW while a transfer is being serviced (wait states),
    // HIGH when no transfer is outstanding or on the completing cycle.
    // ------------------------------------------------------------------
    always @(posedge HCLK) begin
        if (!HRESETn) begin
            state     <= ST_IDLE;
            PSEL      <= 1'b0;
            PENABLE   <= 1'b0;
            PWRITE    <= 1'b0;
            PADDR     <= {PADDR_WIDTH{1'b0}};
            PWDATA    <= {HDATA_WIDTH{1'b0}};
            HREADYOUT <= 1'b1;
            HRESP     <= 1'b0;       // OKAY
            rdata_q   <= {HDATA_WIDTH{1'b0}};
            err_q     <= 1'b0;
            req_consume <= 1'b0;
        end else begin
            state <= state_n;
            // Defaults each cycle
            HRESP       <= 1'b0;    // OKAY unless we drive the 2-cycle ERROR
            req_consume <= 1'b0;    // pulse only when we accept a request

            case (state)
                // ------------------------------------------------------
                ST_IDLE: begin
                    PSEL    <= 1'b0;
                    PENABLE <= 1'b0;
                    err_q   <= 1'b0;
                    if (req_ready) begin
                        // Enter SETUP: drive address/control (L6 SETUP outputs)
                        PSEL    <= 1'b1;
                        PENABLE <= 1'b0;
                        PWRITE  <= req_write;
                        PADDR   <= req_addr;
                        PWDATA  <= req_wdata;     // captured data-phase value
                        HREADYOUT   <= 1'b0;      // start inserting wait states
                        req_consume <= 1'b1;      // clear the request buffer
                    end else begin
                        HREADYOUT <= 1'b1;        // bus free
                    end
                end
                // ------------------------------------------------------
                ST_SETUP: begin
                    // SETUP -> ACCESS unconditional: assert PENABLE
                    PSEL      <= 1'b1;
                    PENABLE   <= 1'b1;
                    HREADYOUT <= 1'b0;            // still waiting
                end
                // ------------------------------------------------------
                ST_ACCESS: begin
                    if (PREADY) begin
                        // Transfer completes this cycle.
                        PSEL    <= 1'b0;
                        PENABLE <= 1'b0;
                        rdata_q <= PRDATA;        // capture read data
                        // Map PSLVERR -> AHB ERROR (L9 PSLVERR->HRESP=ERROR).
                        // 2-cycle ERROR: drive HRESP=1 with HREADYOUT=0 this
                        // cycle, then HRESP=1 HREADYOUT=1 next cycle.
                        if (PSLVERR) begin
                            err_q     <= 1'b1;
                            HRESP     <= 1'b1;    // ERROR cycle 1
                            HREADYOUT <= 1'b0;
                        end else begin
                            HRESP     <= 1'b0;    // OKAY
                            HREADYOUT <= 1'b1;    // complete: ready high
                        end
                    end else begin
                        // PREADY=0: hold ACCESS, keep inserting wait states.
                        PSEL      <= 1'b1;
                        PENABLE   <= 1'b1;
                        HREADYOUT <= 1'b0;
                    end
                end
                // ------------------------------------------------------
                default: begin
                    PSEL    <= 1'b0;
                    PENABLE <= 1'b0;
                end
            endcase

            // Second cycle of the 2-cycle AHB ERROR response.
            if (err_q) begin
                HRESP     <= 1'b1;   // ERROR cycle 2
                HREADYOUT <= 1'b1;
                err_q     <= 1'b0;
            end
        end
    end
endmodule


// ----------------------------------------------------------------------------
// Top: ties the AHB-to-APB bridge to the APB GPIO.  This is the synthesizable
// SoC integration unit driven through Phase-3 signoff.
//   Single clock domain: clk drives both HCLK and PCLK.
//   Single synchronous active-low reset: rst_n drives HRESETn and PRESETn.
// ----------------------------------------------------------------------------
module ahb_apb_gpio #(
    parameter integer HADDR_WIDTH = 32,
    parameter integer HDATA_WIDTH = 32,
    parameter integer PADDR_WIDTH = 12,
    parameter integer GPIO_WIDTH  = 8
) (
    input  wire                      clk,       // HCLK == PCLK
    input  wire                      rst_n,     // HRESETn == PRESETn (active LOW)
    // ---- AHB-Lite Subordinate port (the SoC bus side) ----
    input  wire                      HSEL,
    input  wire [HADDR_WIDTH-1:0]    HADDR,
    input  wire [1:0]                HTRANS,
    input  wire                      HWRITE,
    input  wire [2:0]                HSIZE,
    input  wire [2:0]                HBURST,
    input  wire [HDATA_WIDTH-1:0]    HWDATA,
    input  wire                      HREADY,
    output wire [HDATA_WIDTH-1:0]    HRDATA,
    output wire                      HREADYOUT,
    output wire                      HRESP,
    // ---- GPIO pads ----
    output wire [GPIO_WIDTH-1:0]     gpio_out,
    output wire [GPIO_WIDTH-1:0]     gpio_oe,
    input  wire [GPIO_WIDTH-1:0]     gpio_in
);
    // Internal APB fabric (bridge Manager -> GPIO Subordinate)
    wire [PADDR_WIDTH-1:0] PADDR;
    wire                   PSEL;
    wire                   PENABLE;
    wire                   PWRITE;
    wire [HDATA_WIDTH-1:0] PWDATA;
    wire [HDATA_WIDTH-1:0] PRDATA;
    wire                   PREADY;
    wire                   PSLVERR;

    ahb_apb_bridge #(
        .HADDR_WIDTH(HADDR_WIDTH),
        .HDATA_WIDTH(HDATA_WIDTH),
        .PADDR_WIDTH(PADDR_WIDTH)
    ) u_bridge (
        .HCLK     (clk),
        .HRESETn  (rst_n),
        .HSEL     (HSEL),
        .HADDR    (HADDR),
        .HTRANS   (HTRANS),
        .HWRITE   (HWRITE),
        .HSIZE    (HSIZE),
        .HBURST   (HBURST),
        .HWDATA   (HWDATA),
        .HREADY   (HREADY),
        .HRDATA   (HRDATA),
        .HREADYOUT(HREADYOUT),
        .HRESP    (HRESP),
        .PADDR    (PADDR),
        .PSEL     (PSEL),
        .PENABLE  (PENABLE),
        .PWRITE   (PWRITE),
        .PWDATA   (PWDATA),
        .PRDATA   (PRDATA),
        .PREADY   (PREADY),
        .PSLVERR  (PSLVERR)
    );

    apb_gpio #(
        .PADDR_WIDTH(PADDR_WIDTH),
        .PDATA_WIDTH(HDATA_WIDTH),
        .GPIO_WIDTH (GPIO_WIDTH)
    ) u_gpio (
        .PCLK    (clk),
        .PRESETn (rst_n),
        .PADDR   (PADDR),
        .PSEL    (PSEL),
        .PENABLE (PENABLE),
        .PWRITE  (PWRITE),
        .PWDATA  (PWDATA),
        .PRDATA  (PRDATA),
        .PREADY  (PREADY),
        .PSLVERR (PSLVERR),
        .gpio_out(gpio_out),
        .gpio_oe (gpio_oe),
        .gpio_in (gpio_in)
    );
endmodule
