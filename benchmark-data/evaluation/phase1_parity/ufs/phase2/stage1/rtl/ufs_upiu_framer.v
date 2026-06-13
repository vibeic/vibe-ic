// =====================================================================
// ufs_upiu_framer.v  —  UFS UPIU Basic-Header framer / parser sub-block
// ---------------------------------------------------------------------
// Universal Flash Storage (JEDEC JESD220 / UFS 4.0)
//
// SCOPE (honest): this is a SMALL, COMPLETE, synthesizable UFS SUB-BLOCK
// — the UPIU Basic-Header assemble/parse engine — NOT a full UFS
// controller (UniPro + M-PHY SerDes + SCSI command set are out of single
// -block GDS scope; see RESULT_e2e_pilot.md).
//
// Function:
//   * BUILD path  : host CPU programs the 12 UPIU Basic-Header fields
//                   through the synchronous register interface, then
//                   pulses build_start. A small FSM serialises the
//                   12-byte UPIU Basic Header out on tx_byte/tx_valid in
//                   canonical big-endian wire order (byte 0 first).
//   * PARSE path  : an incoming UPIU is streamed in on rx_byte/rx_valid
//                   (byte 0 first). The FSM latches each header field
//                   into the parsed-field registers and asserts
//                   parse_done with a structural-validity verdict.
//
// Grounding (Phase-1 L-docs, UFS-genuine content only):
//   L3 upiu_header_format.fields  -> the 8 named Basic-Header fields
//       (Transaction Type / Flags / LUN / Task Tag / Command Set Type /
//        Query-Task Function / Total EHS Length / Data Segment Length)
//   L8 upiu_transaction_type_enum -> the 12 transaction-type codes
//   L8 well_known_lun_enum        -> W-LUN constants
//   L6 fsm_states_device          -> IDLE / COMMAND_EXEC style control
//
// UPIU Basic Header wire layout (JEDEC JESD220, 12 bytes, big-endian):
//   byte  0 : [7:6]=hdr-flags(rsvd here) [5:0]=Transaction Type
//   byte  1 : Flags
//   byte  2 : LUN
//   byte  3 : Task Tag
//   byte  4 : [7:4]=IID  [3:0]=Command Set Type
//   byte  5 : Query / Task-Management Function  (a.k.a. opcode field)
//   byte  6 : Response
//   byte  7 : Status
//   byte  8 : Total EHS Length
//   byte  9 : Device Information
//   byte 10 : Data Segment Length [15:8]   (MSB)
//   byte 11 : Data Segment Length [7:0]     (LSB)
//
// Design rules: single clock (clk), synchronous active-high reset (rst),
//               no latches, no tri-state, fully synthesizable.
// =====================================================================

`timescale 1ns/1ps
`default_nettype none

module ufs_upiu_framer #(
    parameter integer HDR_BYTES = 12          // UPIU Basic Header length
) (
    input  wire        clk,
    input  wire        rst,                    // synchronous, active-high

    // ---------------- synchronous register-write interface ----------------
    // Host programs the outgoing-UPIU header fields here (build path).
    input  wire        reg_we,                 // write strobe
    input  wire [3:0]  reg_addr,               // field selector (see localparams)
    input  wire [15:0] reg_wdata,              // write data (16b covers DSL)

    // ---------------- build (assemble outgoing UPIU) ----------------------
    input  wire        build_start,            // pulse to begin serialising
    output reg  [7:0]  tx_byte,                // outgoing header byte
    output reg         tx_valid,               // tx_byte is valid this cycle
    output reg         build_done,             // pulses 1 cycle when build complete

    // ---------------- parse (receive incoming UPIU) -----------------------
    input  wire [7:0]  rx_byte,                // incoming header byte
    input  wire        rx_valid,               // rx_byte is valid this cycle
    output reg         parse_done,             // pulses 1 cycle when header parsed
    output reg         parse_valid,            // structural validity of parsed header

    // ---------------- parsed-field outputs (latched after parse) ----------
    output reg  [5:0]  p_txn_type,
    output reg  [7:0]  p_flags,
    output reg  [7:0]  p_lun,
    output reg  [7:0]  p_task_tag,
    output reg  [3:0]  p_iid,
    output reg  [3:0]  p_cmd_set_type,
    output reg  [7:0]  p_query_func,
    output reg  [7:0]  p_response,
    output reg  [7:0]  p_status,
    output reg  [7:0]  p_ehs_len,
    output reg  [7:0]  p_dev_info,
    output reg  [15:0] p_data_seg_len,

    // ---------------- status ---------------------------------------------
    output reg         busy
);

    // ------------------------------------------------------------------
    // Register-field addresses (build path). reg_addr selects which
    // outgoing-header field reg_wdata writes.
    // ------------------------------------------------------------------
    localparam [3:0] A_TXN_TYPE   = 4'd0;   // [5:0]
    localparam [3:0] A_FLAGS      = 4'd1;   // [7:0]
    localparam [3:0] A_LUN        = 4'd2;   // [7:0]
    localparam [3:0] A_TASK_TAG   = 4'd3;   // [7:0]
    localparam [3:0] A_IID_CST    = 4'd4;   // [7:4]=IID [3:0]=CmdSetType
    localparam [3:0] A_QUERY_FUNC = 4'd5;   // [7:0]
    localparam [3:0] A_RESPONSE   = 4'd6;   // [7:0]
    localparam [3:0] A_STATUS     = 4'd7;   // [7:0]
    localparam [3:0] A_EHS_LEN    = 4'd8;   // [7:0]
    localparam [3:0] A_DEV_INFO   = 4'd9;   // [7:0]
    localparam [3:0] A_DSL        = 4'd10;  // [15:0] Data Segment Length

    // ------------------------------------------------------------------
    // UPIU transaction-type codes  (L8 upiu_transaction_type_enum; JEDEC
    // JESD220 6-bit Transaction Type field codes).
    // ------------------------------------------------------------------
    localparam [5:0] TT_NOP_OUT      = 6'h00;
    localparam [5:0] TT_COMMAND      = 6'h01;
    localparam [5:0] TT_DATA_OUT     = 6'h02;
    localparam [5:0] TT_TASK_MGMT_RQ = 6'h04;
    localparam [5:0] TT_QUERY_RQ     = 6'h16;
    localparam [5:0] TT_NOP_IN       = 6'h20;
    localparam [5:0] TT_RESPONSE     = 6'h21;
    localparam [5:0] TT_DATA_IN      = 6'h22;
    localparam [5:0] TT_RTT          = 6'h31;  // Ready To Transfer
    localparam [5:0] TT_TASK_MGMT_RS = 6'h24;
    localparam [5:0] TT_QUERY_RS     = 6'h36;
    localparam [5:0] TT_REJECT       = 6'h3F;

    // ------------------------------------------------------------------
    // Outgoing-header field storage (build path).
    // ------------------------------------------------------------------
    reg [5:0]  o_txn_type;
    reg [7:0]  o_flags;
    reg [7:0]  o_lun;
    reg [7:0]  o_task_tag;
    reg [3:0]  o_iid;
    reg [3:0]  o_cmd_set_type;
    reg [7:0]  o_query_func;
    reg [7:0]  o_response;
    reg [7:0]  o_status;
    reg [7:0]  o_ehs_len;
    reg [7:0]  o_dev_info;
    reg [15:0] o_data_seg_len;

    // ------------------------------------------------------------------
    // FSM (grounded in L6 control style: single host-mastered engine that
    // is IDLE until a build or parse is requested).
    // ------------------------------------------------------------------
    localparam [1:0] S_IDLE  = 2'd0;
    localparam [1:0] S_BUILD = 2'd1;
    localparam [1:0] S_PARSE = 2'd2;

    reg [1:0]              state;
    reg [4:0]              byte_idx;   // 0..HDR_BYTES (counts emitted/received bytes)

    // ------------------------------------------------------------------
    // Combinational: byte-mux that maps byte_idx -> outgoing header byte.
    // Pure function of the latched outgoing fields, no storage.
    // ------------------------------------------------------------------
    reg [7:0] tx_byte_mux;
    always @(*) begin
        case (byte_idx)
            5'd0:    tx_byte_mux = {2'b00, o_txn_type};
            5'd1:    tx_byte_mux = o_flags;
            5'd2:    tx_byte_mux = o_lun;
            5'd3:    tx_byte_mux = o_task_tag;
            5'd4:    tx_byte_mux = {o_iid, o_cmd_set_type};
            5'd5:    tx_byte_mux = o_query_func;
            5'd6:    tx_byte_mux = o_response;
            5'd7:    tx_byte_mux = o_status;
            5'd8:    tx_byte_mux = o_ehs_len;
            5'd9:    tx_byte_mux = o_dev_info;
            5'd10:   tx_byte_mux = o_data_seg_len[15:8];
            5'd11:   tx_byte_mux = o_data_seg_len[7:0];
            default: tx_byte_mux = 8'h00;
        endcase
    end

    // ------------------------------------------------------------------
    // Combinational: structural validity of the just-parsed transaction
    // type (is the 6-bit code one of the 12 defined UPIU types?).
    // ------------------------------------------------------------------
    function automatic valid_txn_type;
        input [5:0] tt;
        begin
            case (tt)
                TT_NOP_OUT, TT_COMMAND, TT_DATA_OUT, TT_TASK_MGMT_RQ,
                TT_QUERY_RQ, TT_NOP_IN, TT_RESPONSE, TT_DATA_IN,
                TT_RTT, TT_TASK_MGMT_RS, TT_QUERY_RS, TT_REJECT:
                    valid_txn_type = 1'b1;
                default:
                    valid_txn_type = 1'b0;
            endcase
        end
    endfunction

    // ==================================================================
    // Sequential logic — single always block, synchronous reset.
    // ==================================================================
    always @(posedge clk) begin
        if (rst) begin
            state          <= S_IDLE;
            byte_idx       <= 5'd0;
            busy           <= 1'b0;

            tx_byte        <= 8'h00;
            tx_valid       <= 1'b0;
            build_done     <= 1'b0;

            parse_done     <= 1'b0;
            parse_valid    <= 1'b0;

            o_txn_type     <= 6'd0;
            o_flags        <= 8'd0;
            o_lun          <= 8'd0;
            o_task_tag     <= 8'd0;
            o_iid          <= 4'd0;
            o_cmd_set_type <= 4'd0;
            o_query_func   <= 8'd0;
            o_response     <= 8'd0;
            o_status       <= 8'd0;
            o_ehs_len      <= 8'd0;
            o_dev_info     <= 8'd0;
            o_data_seg_len <= 16'd0;

            p_txn_type     <= 6'd0;
            p_flags        <= 8'd0;
            p_lun          <= 8'd0;
            p_task_tag     <= 8'd0;
            p_iid          <= 4'd0;
            p_cmd_set_type <= 4'd0;
            p_query_func   <= 8'd0;
            p_response     <= 8'd0;
            p_status       <= 8'd0;
            p_ehs_len      <= 8'd0;
            p_dev_info     <= 8'd0;
            p_data_seg_len <= 16'd0;
        end else begin
            // default single-cycle strobes
            tx_valid    <= 1'b0;
            build_done  <= 1'b0;
            parse_done  <= 1'b0;

            // ----- register writes (only when IDLE: header is stable) -----
            if (reg_we && state == S_IDLE) begin
                case (reg_addr)
                    A_TXN_TYPE:   o_txn_type     <= reg_wdata[5:0];
                    A_FLAGS:      o_flags        <= reg_wdata[7:0];
                    A_LUN:        o_lun          <= reg_wdata[7:0];
                    A_TASK_TAG:   o_task_tag     <= reg_wdata[7:0];
                    A_IID_CST:    {o_iid, o_cmd_set_type} <= reg_wdata[7:0];
                    A_QUERY_FUNC: o_query_func   <= reg_wdata[7:0];
                    A_RESPONSE:   o_response     <= reg_wdata[7:0];
                    A_STATUS:     o_status       <= reg_wdata[7:0];
                    A_EHS_LEN:    o_ehs_len      <= reg_wdata[7:0];
                    A_DEV_INFO:   o_dev_info     <= reg_wdata[7:0];
                    A_DSL:        o_data_seg_len <= reg_wdata[15:0];
                    default:      ; // no-op
                endcase
            end

            case (state)
                // --------------------------------------------------------
                S_IDLE: begin
                    busy <= 1'b0;
                    if (build_start) begin
                        state    <= S_BUILD;
                        byte_idx <= 5'd0;
                        busy     <= 1'b1;
                    end else if (rx_valid) begin
                        // first incoming byte starts a parse
                        state              <= S_PARSE;
                        busy               <= 1'b1;
                        // latch byte 0 immediately (Transaction Type)
                        p_txn_type         <= rx_byte[5:0];
                        byte_idx           <= 5'd1;
                    end
                end

                // --------------------------------------------------------
                // BUILD : emit one header byte per cycle, byte 0 .. 11.
                // --------------------------------------------------------
                S_BUILD: begin
                    tx_byte  <= tx_byte_mux;
                    tx_valid <= 1'b1;
                    if (byte_idx == HDR_BYTES[4:0] - 5'd1) begin
                        byte_idx   <= 5'd0;
                        build_done <= 1'b1;
                        state      <= S_IDLE;
                        busy       <= 1'b0;
                    end else begin
                        byte_idx <= byte_idx + 5'd1;
                    end
                end

                // --------------------------------------------------------
                // PARSE : latch each incoming header byte into its field.
                // byte_idx already == 1 on entry (byte 0 latched in IDLE).
                // --------------------------------------------------------
                S_PARSE: begin
                    if (rx_valid) begin
                        case (byte_idx)
                            5'd1:  p_flags                <= rx_byte;
                            5'd2:  p_lun                  <= rx_byte;
                            5'd3:  p_task_tag             <= rx_byte;
                            5'd4:  {p_iid, p_cmd_set_type}<= rx_byte;
                            5'd5:  p_query_func           <= rx_byte;
                            5'd6:  p_response             <= rx_byte;
                            5'd7:  p_status               <= rx_byte;
                            5'd8:  p_ehs_len              <= rx_byte;
                            5'd9:  p_dev_info             <= rx_byte;
                            5'd10: p_data_seg_len[15:8]   <= rx_byte;
                            5'd11: p_data_seg_len[7:0]    <= rx_byte;
                            default: ; // no-op
                        endcase

                        if (byte_idx == HDR_BYTES[4:0] - 5'd1) begin
                            byte_idx    <= 5'd0;
                            parse_done  <= 1'b1;
                            parse_valid <= valid_txn_type(p_txn_type);
                            state       <= S_IDLE;
                            busy        <= 1'b0;
                        end else begin
                            byte_idx <= byte_idx + 5'd1;
                        end
                    end
                end

                // --------------------------------------------------------
                default: begin
                    state <= S_IDLE;
                    busy  <= 1'b0;
                end
            endcase
        end
    end

endmodule

`default_nettype wire
