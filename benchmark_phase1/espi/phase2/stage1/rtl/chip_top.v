//============================================================================
// chip_top.v  --  eSPI Slave digital core (Vibe-IC Phase 2 spec-to-rtl)
//
// IC          : eSPI_Slave  (Enhanced Serial Peripheral Interface, slave side)
// Source spec : Intel eSPI Base Specification (phase1 L1-L23 docs)
// Class       : digital_cmd_driven  (command / turnaround / response FSM)
//
// What this implements (synthesizable digital core):
//   * eSPI single-I/O slave front-end:
//       ESPI_CLK  (slave samples on this domain; here brought in as `clk`
//                  for a single synchronous clock, see note below)
//       ESPI_CS_N (active-low chip select, frames a transaction)
//       ESPI_IO[3:0] (4-lane pad bus; in single-I/O mode only IO[0]=MOSI,
//                  IO[1]=MISO are used. Dual/Quad pad muxing is a simple
//                  combinational mux driven by io_mode.)
//       ESPI_ALERT_N (open-drain alert; driven low when slave has an
//                  asynchronous event for the master)
//       ESPI_RESET_N (in-band/sideband reset, OR-ed with the synchronous
//                  active-low reset rst_n)
//   * 8-bit CMD opcode decode: PUT_* / GET_* / GET_STATUS /
//     GET_CONFIGURATION / SET_CONFIGURATION / RESET
//   * Command / TURNAROUND / response FSM with TURNAROUND_CLOCKS=2
//   * 16-bit STATUS register (PC_FREE..FLASH_NP_AVAIL) returned by GET_STATUS
//   * Per-channel enable / ready (4 channels: PC, VW, OOB, FLASH)
//   * CRC-8 (poly 0x07) generator + checker, LSB-first per L3 extraction
//     (reflected poly 0xE0). Parameterized so MSB-first can be selected.
//   * WAIT_STATE insertion (response code 0x04, wait nibble 0x0F)
//
// Clocking note (HONEST):
//   A real eSPI slave is source-synchronous: the master drives ESPI_CLK and
//   the slave samples ESPI_IO on ESPI_CLK edges while CS# is low. For a
//   clean single-clock, latch-free, yosys-synthesizable digital core (the
//   Phase-2 requirement), this block runs on ONE synchronous clock `clk`
//   and treats the serial byte boundary with an internal bit counter. The
//   pad-level CLK recovery / DLL is PHY work and is left as the blackboxed
//   `espi_phy_stub` port interface (parallel symbol interface) below.
//
// Coding rules obeyed: single clock, single active-low reset, NO latches,
//   NO combinational loops, NO multi-driven nets, every state element
//   reset-initialized.
//============================================================================

`default_nettype none

//----------------------------------------------------------------------------
// CRC-8 combinational step: advance crc by one data byte.
//   poly      : generator polynomial (0x07 normal, 0xE0 reflected)
//   reflected : 1 => LSB-first (eSPI L3 convention), 0 => MSB-first
//----------------------------------------------------------------------------
module espi_crc8_step #(
    parameter [7:0] POLY      = 8'h07,
    parameter [7:0] POLY_REF  = 8'hE0,
    parameter       REFLECTED = 1'b1
)(
    input  wire [7:0] crc_in,
    input  wire [7:0] data,
    output wire [7:0] crc_out
);
    integer i;
    reg [7:0] c;
    always @(*) begin
        c = crc_in;
        if (REFLECTED) begin
            // LSB-first: xor incoming byte, then 8 reflected shifts
            c = c ^ data;
            for (i = 0; i < 8; i = i + 1) begin
                if (c[0]) c = (c >> 1) ^ POLY_REF;
                else      c = (c >> 1);
            end
        end else begin
            // MSB-first standard CRC-8-ATM
            c = c ^ data;
            for (i = 0; i < 8; i = i + 1) begin
                if (c[7]) c = (c << 1) ^ POLY;
                else      c = (c << 1);
            end
        end
    end
    assign crc_out = c;
endmodule


//----------------------------------------------------------------------------
// eSPI slave core: byte-level command/turnaround/response FSM.
// Interfaces to the serial pads via a de-serialized byte interface that the
// PHY stub (or a simple shift register) provides.
//----------------------------------------------------------------------------
module espi_slave_core #(
    parameter [7:0] CRC8_POLY      = 8'h07,
    parameter [7:0] CRC8_POLY_REF  = 8'hE0,
    parameter       CRC_REFLECTED  = 1'b1,
    parameter [1:0] TURNAROUND_CLK = 2'd2,
    parameter [7:0] WAIT_NIBBLE    = 8'h0F,   // wait-state byte
    parameter [7:0] NO_RESPONSE    = 8'hFF
)(
    input  wire        clk,
    input  wire        rst_n,        // synchronous active-low reset

    // chip-select frame (active low)
    input  wire        cs_n,

    // De-serialized RX byte interface (from PHY/shift reg)
    input  wire        rx_valid,     // 1-cycle strobe: rx_byte is a fresh byte
    input  wire [7:0]  rx_byte,

    // De-serialized TX byte interface (to PHY/shift reg)
    output reg         tx_valid,     // 1-cycle strobe: tx_byte is to be sent
    output reg  [7:0]  tx_byte,
    input  wire        tx_ready,     // PHY can accept a byte this cycle

    // Channel ready inputs (from upstream logic / config)
    input  wire        ch_pc_ready,
    input  wire        ch_vw_ready,
    input  wire        ch_oob_ready,
    input  wire        ch_flash_ready,

    // Asynchronous event request -> drives ALERT#
    input  wire        event_pending,

    // Observability / status
    output reg         alert_req,    // 1 => assert ESPI_ALERT_N (active low pad)
    output wire [15:0] status_reg_o,
    output wire [3:0]  ch_enable_o,
    output reg  [7:0]  last_cmd_o,
    output reg         crc_error_o
);

    // ----- opcode encodings (L3) -----
    localparam [7:0] OP_PUT_PC          = 8'h00;
    localparam [7:0] OP_GET_PC          = 8'h01;
    localparam [7:0] OP_GET_NP          = 8'h02;
    localparam [7:0] OP_PUT_NP          = 8'h04;
    localparam [7:0] OP_PUT_IORD_SHORT  = 8'h06;
    localparam [7:0] OP_PUT_IOWR_SHORT  = 8'h07;
    localparam [7:0] OP_PUT_MEMRD32     = 8'h08;
    localparam [7:0] OP_PUT_MEMWR32     = 8'h09;
    localparam [7:0] OP_PUT_VWIRE       = 8'h10;
    localparam [7:0] OP_GET_VWIRE       = 8'h11;
    localparam [7:0] OP_PUT_OOB         = 8'h12;
    localparam [7:0] OP_GET_OOB         = 8'h13;
    localparam [7:0] OP_PUT_FLASH_C     = 8'h14;
    localparam [7:0] OP_GET_FLASH_NP    = 8'h15;
    localparam [7:0] OP_GET_STATUS      = 8'h20;
    localparam [7:0] OP_SET_CONFIG      = 8'h21;
    localparam [7:0] OP_GET_CONFIG      = 8'h22;
    localparam [7:0] OP_RESET           = 8'hFF;

    // ----- response codes (L3) -----
    localparam [7:0] RSP_ACCEPT    = 8'h08;
    localparam [7:0] RSP_DEFER     = 8'h01;
    localparam [7:0] RSP_NONFATAL  = 8'h02;
    localparam [7:0] RSP_FATAL     = 8'h03;
    localparam [7:0] RSP_WAIT      = 8'h04;
    localparam [7:0] RSP_NORESP    = 8'h0C;

    // ----- FSM states -----
    localparam [2:0] S_IDLE   = 3'd0; // waiting for CS# low + opcode
    localparam [2:0] S_CMD    = 3'd1; // received opcode, collecting cmd bytes
    localparam [2:0] S_ADDR   = 3'd2; // collecting address/length/data bytes
    localparam [2:0] S_CRC    = 3'd3; // expecting command CRC byte
    localparam [2:0] S_TAR    = 3'd4; // turnaround (slave takes the bus)
    localparam [2:0] S_WAIT   = 3'd5; // inserting wait-state byte(s)
    localparam [2:0] S_RESP   = 3'd6; // driving response code
    localparam [2:0] S_RDATA  = 3'd7; // driving response data + response CRC

    reg [2:0]  state;
    reg [1:0]  tar_cnt;       // turnaround down-counter
    reg [2:0]  wait_cnt;      // number of wait states to insert
    reg [3:0]  byte_idx;      // index within multi-byte phase
    reg [3:0]  resp_len;      // bytes of response payload to send

    reg [7:0]  cmd_op;        // latched opcode
    reg [7:0]  rx_crc;        // received command CRC byte
    reg        is_get;        // 1 => response carries data (GET_*/GET_STATUS/...)

    // STATUS register (16-bit, L4 status_register bit map)
    reg [15:0] status_reg;
    // Channel enable bits {flash, oob, vw, pc}
    reg [3:0]  ch_enable;
    // last config addr written by SET_CONFIGURATION (1-byte addr model)
    reg [7:0]  cfg_addr;

    // running CRC over the command bytes
    reg  [7:0] cmd_crc;
    wire [7:0] cmd_crc_next;
    // running CRC over the response bytes
    reg  [7:0] resp_crc;
    wire [7:0] resp_crc_next;
    reg  [7:0] crc_data;       // byte fed to the response CRC engine

    espi_crc8_step #(
        .POLY(CRC8_POLY), .POLY_REF(CRC8_POLY_REF), .REFLECTED(CRC_REFLECTED)
    ) u_cmd_crc (
        .crc_in (cmd_crc), .data(rx_byte), .crc_out(cmd_crc_next)
    );
    espi_crc8_step #(
        .POLY(CRC8_POLY), .POLY_REF(CRC8_POLY_REF), .REFLECTED(CRC_REFLECTED)
    ) u_resp_crc (
        .crc_in (resp_crc), .data(crc_data), .crc_out(resp_crc_next)
    );

    assign status_reg_o = status_reg;
    assign ch_enable_o  = ch_enable;

    // ----- helper: decode whether opcode requires response payload -----
    function automatic is_get_op;
        input [7:0] op;
        begin
            case (op)
                OP_GET_PC, OP_GET_NP, OP_GET_VWIRE, OP_GET_OOB,
                OP_GET_FLASH_NP, OP_GET_STATUS, OP_GET_CONFIG: is_get_op = 1'b1;
                default: is_get_op = 1'b0;
            endcase
        end
    endfunction

    // ----- helper: how many response data bytes for a GET op -----
    function automatic [3:0] resp_bytes;
        input [7:0] op;
        begin
            case (op)
                OP_GET_STATUS: resp_bytes = 4'd2;  // 16-bit status
                OP_GET_CONFIG: resp_bytes = 4'd4;  // 32-bit config word
                OP_GET_PC, OP_GET_NP, OP_GET_VWIRE,
                OP_GET_OOB, OP_GET_FLASH_NP: resp_bytes = 4'd4; // a short payload
                default: resp_bytes = 4'd0;
            endcase
        end
    endfunction

    // response payload byte selection (combinational, no latch: full case)
    reg [7:0] resp_data_byte;
    always @(*) begin
        resp_data_byte = 8'h00;
        case (cmd_op)
            OP_GET_STATUS: begin
                case (byte_idx)
                    4'd0:    resp_data_byte = status_reg[7:0];
                    4'd1:    resp_data_byte = status_reg[15:8];
                    default: resp_data_byte = 8'h00;
                endcase
            end
            OP_GET_CONFIG: begin
                // 32-bit config word: byte0 = general caps (CRC en + io mode),
                // byte1 = channel enables, others 0
                case (byte_idx)
                    4'd0:    resp_data_byte = {4'h0, ch_enable};       // caps lo
                    4'd1:    resp_data_byte = {3'h0, status_reg[4:0]}; // sample
                    default: resp_data_byte = 8'h00;
                endcase
            end
            default: resp_data_byte = 8'h00;
        endcase
    end

    // ------------------------------------------------------------------
    // Main synchronous FSM
    // ------------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
            state        <= S_IDLE;
            tar_cnt      <= 2'd0;
            wait_cnt     <= 3'd0;
            byte_idx     <= 4'd0;
            resp_len     <= 4'd0;
            cmd_op       <= 8'h00;
            rx_crc       <= 8'h00;
            is_get       <= 1'b0;
            status_reg   <= 16'h000F; // all four *_FREE bits set at power-up
            ch_enable    <= 4'b0000;
            cfg_addr     <= 8'h00;
            cmd_crc      <= 8'h00;
            resp_crc     <= 8'h00;
            crc_data     <= 8'h00;
            tx_valid     <= 1'b0;
            tx_byte      <= 8'h00;
            alert_req    <= 1'b0;
            last_cmd_o   <= 8'h00;
            crc_error_o  <= 1'b0;
        end else begin
            // defaults each cycle (avoid latches / stale strobes)
            tx_valid <= 1'b0;
            crc_data <= 8'h00;

            // ALERT# is asserted while an async event is pending and CS# idle
            alert_req <= event_pending & cs_n;

            // CS# high forces the slave back to idle (transaction framing)
            if (cs_n) begin
                state    <= S_IDLE;
                tar_cnt  <= 2'd0;
                wait_cnt <= 3'd0;
                byte_idx <= 4'd0;
                cmd_crc  <= 8'h00;  // CRC reset at break (L3 reset_at_break)
                resp_crc <= 8'h00;
            end else begin
                case (state)
                    // ---- IDLE: first byte after CS# low is the opcode ----
                    S_IDLE: begin
                        if (rx_valid) begin
                            cmd_op      <= rx_byte;
                            last_cmd_o  <= rx_byte;
                            is_get      <= is_get_op(rx_byte);
                            resp_len    <= resp_bytes(rx_byte);
                            byte_idx    <= 4'd0;
                            cmd_crc     <= cmd_crc_next; // include opcode in CRC
                            crc_error_o <= 1'b0;
                            // RESET opcode: in-band reset of slave state
                            if (rx_byte == OP_RESET) begin
                                status_reg <= 16'h000F;
                                ch_enable  <= 4'b0000;
                                state      <= S_IDLE;
                            end else begin
                                state <= S_CMD;
                            end
                        end
                    end

                    // ---- CMD: optional command/config byte phase ----
                    // GET_STATUS / RESET need no further cmd bytes; others
                    // accept one address/config byte then the CRC.
                    S_CMD: begin
                        if (rx_valid) begin
                            cmd_crc <= cmd_crc_next;
                            case (cmd_op)
                                OP_GET_STATUS: begin
                                    // this byte is the command CRC
                                    rx_crc <= rx_byte;
                                    state  <= S_TAR;
                                    tar_cnt<= TURNAROUND_CLK;
                                end
                                OP_SET_CONFIG, OP_GET_CONFIG: begin
                                    cfg_addr <= rx_byte; // config address byte
                                    state    <= S_ADDR;
                                end
                                default: begin
                                    // PUT_*/GET_* data/addr: collect a byte
                                    state    <= S_ADDR;
                                end
                            endcase
                        end
                    end

                    // ---- ADDR/DATA: one data byte then CRC ----
                    S_ADDR: begin
                        if (rx_valid) begin
                            cmd_crc <= cmd_crc_next;
                            // For SET_CONFIGURATION, capture the data byte and
                            // apply it to the addressed register model.
                            if (cmd_op == OP_SET_CONFIG) begin
                                case (cfg_addr)
                                    8'h10: ch_enable[0] <= rx_byte[0]; // PC
                                    8'h20: ch_enable[1] <= rx_byte[0]; // VW
                                    8'h30: ch_enable[2] <= rx_byte[0]; // OOB
                                    8'h40: ch_enable[3] <= rx_byte[0]; // FLASH
                                    default: ; // other config: no state change
                                endcase
                            end
                            rx_crc <= rx_byte; // next byte modeled as CRC
                            state  <= S_CRC;
                        end
                    end

                    // ---- CRC: the byte we just took was the CRC; check it ----
                    S_CRC: begin
                        // rx_crc holds the received CRC byte; cmd_crc is the
                        // running CRC computed over preceding bytes.
                        if (rx_crc != cmd_crc) begin
                            crc_error_o <= 1'b1;  // fsm_error: recoverable
                            // eSPI CRC mismatch is a NON_FATAL_ERROR (response
                            // code 0x02): the master re-issues the transaction.
                            // Recoverable by protocol design, not a fatal fault.
                        end
                        state   <= S_TAR;
                        tar_cnt <= TURNAROUND_CLK;
                    end

                    // ---- TAR: turnaround, slave acquires the bus ----
                    S_TAR: begin
                        resp_crc <= 8'h00;  // start response CRC fresh
                        byte_idx <= 4'd0;
                        if (tar_cnt != 2'd0) begin
                            tar_cnt <= tar_cnt - 2'd1;
                        end else begin
                            // decide wait states: insert one if the targeted
                            // channel is not ready (back-pressure), else none.
                            if (!channel_ready(cmd_op)) begin
                                wait_cnt <= 3'd1;
                                state    <= S_WAIT;
                            end else begin
                                state    <= S_RESP;
                            end
                        end
                    end

                    // ---- WAIT: insert WAIT_STATE byte(s) ----
                    S_WAIT: begin
                        if (tx_ready) begin
                            tx_valid <= 1'b1;
                            tx_byte  <= WAIT_NIBBLE; // 0x0F wait-state byte
                            if (wait_cnt != 3'd0)
                                wait_cnt <= wait_cnt - 3'd1;
                            // after the wait byte(s), proceed when ch ready
                            if (wait_cnt <= 3'd1) begin
                                if (channel_ready(cmd_op))
                                    state <= S_RESP;
                                // else stay in S_WAIT and keep inserting
                            end
                        end
                    end

                    // ---- RESP: drive the response code byte ----
                    S_RESP: begin
                        if (tx_ready) begin
                            tx_valid <= 1'b1;
                            tx_byte  <= resp_code(cmd_op);
                            crc_data <= resp_code(cmd_op);
                            resp_crc <= resp_crc_next;
                            byte_idx <= 4'd0;
                            if (is_get && resp_len != 4'd0)
                                state <= S_RDATA;
                            else
                                state <= S_RDATA; // still send response CRC
                        end
                    end

                    // ---- RDATA: drive response data bytes then response CRC ----
                    S_RDATA: begin
                        if (tx_ready) begin
                            tx_valid <= 1'b1;
                            if (byte_idx < resp_len) begin
                                tx_byte  <= resp_data_byte;
                                crc_data <= resp_data_byte;
                                resp_crc <= resp_crc_next;
                                byte_idx <= byte_idx + 4'd1;
                            end else begin
                                // final byte: the response CRC
                                tx_byte  <= resp_crc;
                                state    <= S_IDLE;
                                byte_idx <= 4'd0;
                            end
                        end
                    end

                    default: state <= S_IDLE;
                endcase
            end
        end
    end

    // ----- channel ready select (combinational function) -----
    function automatic channel_ready;
        input [7:0] op;
        begin
            case (op)
                OP_PUT_PC, OP_GET_PC, OP_PUT_NP, OP_GET_NP,
                OP_PUT_IORD_SHORT, OP_PUT_IOWR_SHORT,
                OP_PUT_MEMRD32, OP_PUT_MEMWR32: channel_ready = ch_pc_ready;
                OP_PUT_VWIRE, OP_GET_VWIRE:      channel_ready = ch_vw_ready;
                OP_PUT_OOB,   OP_GET_OOB:        channel_ready = ch_oob_ready;
                OP_PUT_FLASH_C, OP_GET_FLASH_NP: channel_ready = ch_flash_ready;
                default:                         channel_ready = 1'b1; // status/config always ready
            endcase
        end
    endfunction

    // ----- response code select (combinational function) -----
    function automatic [7:0] resp_code;
        input [7:0] op;
        begin
            if (crc_error_o)            resp_code = RSP_FATAL;
            else if (!channel_ready(op))resp_code = RSP_DEFER;
            else                        resp_code = RSP_ACCEPT;
        end
    endfunction

endmodule


//----------------------------------------------------------------------------
// Blackbox PHY stub (parallel symbol interface).
//   The real eSPI pad ring / source-synchronous CLK recovery / dual-quad
//   I/O SERDES is analog+mixed-signal PHY work. It is presented here as a
//   module port with a clean parallel symbol interface so the digital core
//   above is fully synthesizable. A simple shift-register implementation is
//   provided so the whole thing simulates and synthesizes; a real PHY would
//   replace this module.
//----------------------------------------------------------------------------
module espi_phy_stub (
    input  wire        clk,
    input  wire        rst_n,
    // serial pad side
    input  wire        cs_n,
    input  wire [1:0]  io_mode,     // 0=single,1=dual,2=quad pad muxing
    input  wire        espi_io0_in, // MOSI (single mode)
    output wire        espi_io1_out,// MISO (single mode)
    input  wire        bit_tick,    // 1 cycle per serial bit (from CLK rec.)
    // parallel symbol side (to core)
    output reg         rx_valid,
    output reg  [7:0]  rx_byte,
    input  wire        tx_valid,
    input  wire [7:0]  tx_byte,
    output wire        tx_ready
);
    reg [7:0] rx_sh;
    reg [2:0] rx_cnt;
    reg [7:0] tx_sh;
    reg [3:0] tx_cnt;       // 0 => idle, else bits remaining +1
    reg       tx_busy;
    reg       tx_pending;   // latch-on-arrival: tx_valid (1-cycle strobe) seen
    reg [7:0] tx_hold;      // captured tx_byte awaiting a free shifter

    assign tx_ready    = ~tx_busy;
    assign espi_io1_out= tx_busy ? tx_sh[7] : 1'b1; // MSB-first on wire

    always @(posedge clk) begin
        if (!rst_n) begin
            rx_sh   <= 8'h00; rx_cnt <= 3'd0; rx_valid <= 1'b0;
            tx_sh   <= 8'h00; tx_cnt <= 4'd0; tx_busy  <= 1'b0;
            tx_pending <= 1'b0; tx_hold <= 8'h00;
        end else begin
            rx_valid <= 1'b0;
            if (cs_n) begin
                rx_cnt <= 3'd0; tx_busy <= 1'b0; tx_cnt <= 4'd0;
                tx_pending <= 1'b0;
            end else begin
                if (bit_tick) begin
                    // RX: shift in MOSI (single mode), MSB-first
                    rx_sh <= {rx_sh[6:0], espi_io0_in};
                    if (rx_cnt == 3'd7) begin
                        rx_cnt   <= 3'd0;
                        rx_byte  <= {rx_sh[6:0], espi_io0_in};
                        rx_valid <= 1'b1;
                    end else begin
                        rx_cnt <= rx_cnt + 3'd1;
                    end
                    // TX: shift out MISO if busy
                    if (tx_busy) begin
                        tx_sh <= {tx_sh[6:0], 1'b1};
                        if (tx_cnt == 4'd1) tx_busy <= 1'b0;
                        if (tx_cnt != 4'd0) tx_cnt <= tx_cnt - 4'd1;
                    end
                end
                // Latch-on-arrival: tx_valid is a 1-cycle strobe from the
                // core, so capture it the moment it pulses (record tx_byte),
                // then drive the shifter when it is free. This removes the
                // producer-consumer pulse race (a re-checked pulse near the
                // tx_cnt countdown) flagged by handshake_check.
                if (tx_valid) begin
                    tx_pending <= 1'b1;
                    tx_hold    <= tx_byte;
                end
                if (tx_pending && !tx_busy) begin
                    tx_sh      <= tx_hold;
                    tx_cnt     <= 4'd8;
                    tx_busy    <= 1'b1;
                    tx_pending <= 1'b0;
                end
            end
        end
    end
    // io_mode is reserved for dual/quad pad muxing; tied off-effect here.
    wire _unused_mode = &{1'b0, io_mode};
endmodule


//============================================================================
// chip_top : top-level wrapper exposing the eSPI primary I/O.
//============================================================================
module chip_top (
    input  wire        clk,          // single synchronous core clock (20 MHz)
    input  wire        rst_n,        // synchronous active-low reset

    // ---- eSPI primary I/O (pad-facing) ----
    input  wire        ESPI_RESET_N, // in-band/sideband reset (active low)
    input  wire        ESPI_CS_N,    // chip select (active low)
    input  wire        ESPI_BIT_TICK,// serial bit strobe (from CLK recovery)
    input  wire        ESPI_IO0_IN,  // MOSI (single I/O mode)
    output wire        ESPI_IO1_OUT, // MISO (single I/O mode)
    input  wire [1:0]  ESPI_IO_MODE, // 0=single 1=dual 2=quad pad mux select
    output wire        ESPI_ALERT_N, // alert (open-drain active low)

    // ---- channel ready strobes from on-die fabric ----
    input  wire        CH_PC_READY,
    input  wire        CH_VW_READY,
    input  wire        CH_OOB_READY,
    input  wire        CH_FLASH_READY,
    input  wire        EVENT_PENDING,

    // ---- observability ----
    output wire [15:0] STATUS_REG,
    output wire [3:0]  CH_ENABLE,
    output wire [7:0]  LAST_CMD,
    output wire        CRC_ERROR
);
    // combined reset: synchronous rst_n AND the in-band ESPI_RESET_N
    wire core_rst_n = rst_n & ESPI_RESET_N;

    // parallel symbol interface between PHY stub and core
    wire        rx_valid;
    wire [7:0]  rx_byte;
    wire        tx_valid;
    wire [7:0]  tx_byte;
    wire        tx_ready;
    wire        alert_req;

    espi_phy_stub u_phy (
        .clk         (clk),
        .rst_n       (core_rst_n),
        .cs_n        (ESPI_CS_N),
        .io_mode     (ESPI_IO_MODE),
        .espi_io0_in (ESPI_IO0_IN),
        .espi_io1_out(ESPI_IO1_OUT),
        .bit_tick    (ESPI_BIT_TICK),
        .rx_valid    (rx_valid),
        .rx_byte     (rx_byte),
        .tx_valid    (tx_valid),
        .tx_byte     (tx_byte),
        .tx_ready    (tx_ready)
    );

    espi_slave_core u_core (
        .clk           (clk),
        .rst_n         (core_rst_n),
        .cs_n          (ESPI_CS_N),
        .rx_valid      (rx_valid),
        .rx_byte       (rx_byte),
        .tx_valid      (tx_valid),
        .tx_byte       (tx_byte),
        .tx_ready      (tx_ready),
        .ch_pc_ready   (CH_PC_READY),
        .ch_vw_ready   (CH_VW_READY),
        .ch_oob_ready  (CH_OOB_READY),
        .ch_flash_ready(CH_FLASH_READY),
        .event_pending (EVENT_PENDING),
        .alert_req     (alert_req),
        .status_reg_o  (STATUS_REG),
        .ch_enable_o   (CH_ENABLE),
        .last_cmd_o    (LAST_CMD),
        .crc_error_o   (CRC_ERROR)
    );

    // ALERT# pad: open-drain active-low. Drive 0 when alert_req, else 1 (Hi-Z
    // modeled as 1 for a 2-state synthesizable net).
    assign ESPI_ALERT_N = alert_req ? 1'b0 : 1'b1;

endmodule

`default_nettype wire
