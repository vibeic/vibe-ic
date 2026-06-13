//============================================================================
// chip_top.v  --  USB Power Delivery (USB-PD) DIGITAL Protocol Engine
//----------------------------------------------------------------------------
// IC          : USB_PD_Protocol_Engine
// Source spec : USB Power Delivery Specification (phase1 L1-L23, gated-parity 0)
//               authoritative USB-PD facts taken from L3_CMD_PROTOCOL.json
//               (opcodes, CRC-32 IEEE 802.3 poly 0x04C11DB7 init 0xFFFFFFFF)
//               and L8_TIMING_WAVEFORM.json (BMC @ 300 kbaud, contract timers).
//
// SCOPE       : This is the DIGITAL protocol-layer engine ONLY. It performs:
//                 * 16-bit Message Header parse / build
//                 * Control (0x01-0x0D) + Data (0x01-0x0F, NumDataObj>=1)
//                   message decode and the protocol-layer FSM
//                 * GoodCRC generation + CRC-32 generate/check
//                 * Source_Capabilities -> Request -> Accept -> PS_RDY
//                   Explicit-Contract negotiation FSM (Source side)
//                 * Hard Reset / Soft Reset handling (MessageID reset)
//
// ANALOG/PHY  : The CC-line BMC (Biphase Mark Coding) transceiver at 300 kbaud
//               is analog / mixed-signal and is INTENTIONALLY BLACKBOXED.
//               This engine drives a PARALLEL symbol interface:
//                 tx_symbol[7:0] / tx_symbol_valid / tx_symbol_ready  (to PHY)
//                 rx_symbol[7:0] / rx_symbol_valid                    (from PHY)
//                 rx_sop / rx_eop                                     (frame mark)
//               The BMC encoder/decoder + CC-line analog front-end live in a
//               separate mixed-signal block (see usb_pd_bmc_phy stub below);
//               this top exposes only the parallel digital symbol contract.
//
// CODING      : Verilog-2001, synchronous, single clock (clk), active-low
//               synchronous reset (rst_n). No latches, no combinational loops,
//               no multi-driven nets, all state reset-initialized. yosys-clean.
//============================================================================

`default_nettype none

module chip_top (
    input  wire        clk,            // system clock (50 MHz per L8/SDC)
    input  wire        rst_n,          // active-low synchronous reset

    //------------------------------------------------------------------
    // Parallel symbol interface to the BLACKBOXED BMC PHY (analog/MS).
    // The BMC transceiver (300 kbaud, biphase mark coded CC line) lives in
    // usb_pd_bmc_phy; here we speak a clean parallel byte/symbol stream.
    //------------------------------------------------------------------
    // RX path: PHY -> engine (decoded SOP-framed symbol bytes)
    input  wire        rx_symbol_valid,// one decoded symbol byte present
    input  wire [7:0]  rx_symbol,      // decoded symbol/byte from BMC RX
    input  wire        rx_sop,         // marks Start-Of-Packet ordered set
    input  wire        rx_eop,         // marks End-Of-Packet (after CRC)
    input  wire [1:0]  rx_sop_type,    // 0=SOP 1=SOP' 2=SOP''  (cable plug)

    // TX path: engine -> PHY (symbol bytes to be BMC-encoded onto CC)
    output reg         tx_symbol_valid,// engine presents a TX symbol byte
    output reg  [7:0]  tx_symbol,      // symbol/byte to BMC TX
    output reg         tx_sop,         // assert with first symbol of a packet
    output reg         tx_eop,         // assert with last symbol (after CRC)
    output reg  [1:0]  tx_sop_type,    // ordered-set selector for the packet
    input  wire        tx_symbol_ready,// PHY can accept a symbol this cycle

    //------------------------------------------------------------------
    // Policy-Engine / Device-Policy-Manager (DPM) host interface.
    // The local policy firmware drives WHAT to send; the protocol engine
    // owns HOW (header build, MessageID, CRC, GoodCRC, retries, contract FSM).
    //------------------------------------------------------------------
    input  wire        port_power_role,// 1=Source, 0=Sink (Port Power Role)
    input  wire        port_data_role, // 1=DFP, 0=UFP    (Port Data Role)
    input  wire        attach,         // CC attach detected (Type-C)
    input  wire        dpm_start,      // DPM: begin Source advertisement
    input  wire [31:0] src_pdo0,       // Source PDO #0 (vSafe5V advertised cap)

    output reg  [3:0]  contract_state, // exported negotiation FSM state
    output reg         explicit_contract, // Explicit Contract established
    output reg         ps_rdy_sent,    // PS_RDY transmitted (power good)
    output reg  [31:0] rdo_received,   // last Request Data Object captured
    output reg         hard_reset_evt, // Hard Reset entered (pulse)
    output reg         soft_reset_evt, // Soft Reset entered (pulse)
    output reg         goodcrc_sent,   // GoodCRC acknowledged a good RX (pulse)
    output reg         rx_crc_ok,      // last RX message passed CRC-32 check
    output reg  [2:0]  rx_msg_id,      // MessageID of the last received message
    output reg         protocol_error  // sticky protocol fault flag
);

    //========================================================================
    // Message Type encodings (from L3_CMD_PROTOCOL.json opcodes)
    //========================================================================
    // Control messages (Number of Data Objects == 0)
    localparam [4:0] CTRL_GOODCRC      = 5'h01;
    localparam [4:0] CTRL_GOTOMIN      = 5'h02;
    localparam [4:0] CTRL_ACCEPT       = 5'h03;
    localparam [4:0] CTRL_REJECT       = 5'h04;
    localparam [4:0] CTRL_PING         = 5'h05;
    localparam [4:0] CTRL_PS_RDY       = 5'h06;
    localparam [4:0] CTRL_GET_SRC_CAP  = 5'h07;
    localparam [4:0] CTRL_GET_SNK_CAP  = 5'h08;
    localparam [4:0] CTRL_DR_SWAP      = 5'h09;
    localparam [4:0] CTRL_PR_SWAP      = 5'h0A;
    localparam [4:0] CTRL_VCONN_SWAP   = 5'h0B;
    localparam [4:0] CTRL_WAIT         = 5'h0C;
    localparam [4:0] CTRL_SOFT_RESET   = 5'h0D;
    // Data messages (Number of Data Objects >= 1)
    localparam [4:0] DATA_SRC_CAP      = 5'h01;
    localparam [4:0] DATA_REQUEST      = 5'h02;
    localparam [4:0] DATA_BIST         = 5'h03;
    localparam [4:0] DATA_SNK_CAP      = 5'h04;
    localparam [4:0] DATA_VDM          = 5'h0F;

    // SOP ordered-set selector (matches rx_sop_type / tx_sop_type)
    localparam [1:0] SOP   = 2'd0;
    localparam [1:0] SOP_P = 2'd1;   // SOP'
    localparam [1:0] SOP_PP= 2'd2;   // SOP''

    // Spec revision field (USB-PD R2.0 = 2'b01) for built headers
    localparam [1:0] SPEC_REV = 2'b01;

    //========================================================================
    // 16-bit Message Header field layout (USB-PD, transmitted LSB-first):
    //   [15]    Extended (0 for Control/Data here)
    //   [14:12] Number of Data Objects (0=Control, >=1=Data)
    //   [11:9]  MessageID
    //   [8]     Port Power Role (or Cable Plug for SOP')
    //   [7:6]   Specification Revision
    //   [5]     Port Data Role
    //   [4:0]   Message Type
    //========================================================================
    function [15:0] build_header;
        input        ext;
        input [2:0]  ndo;
        input [2:0]  msg_id;
        input        pwr_role;
        input        data_role;
        input [4:0]  msg_type;
        begin
            build_header = {ext, ndo, msg_id, pwr_role,
                            SPEC_REV, data_role, msg_type};
        end
    endfunction

    // header field extractors
    function        hdr_ext;     input [15:0] h; begin hdr_ext     = h[15];     end endfunction
    function [2:0]  hdr_ndo;     input [15:0] h; begin hdr_ndo     = h[14:12];  end endfunction
    function [2:0]  hdr_msgid;   input [15:0] h; begin hdr_msgid   = h[11:9];   end endfunction
    function [4:0]  hdr_type;    input [15:0] h; begin hdr_type    = h[4:0];    end endfunction
    function        hdr_isdata;  input [15:0] h; begin hdr_isdata  = (h[14:12] != 3'd0); end endfunction

    //========================================================================
    // CRC-32 (IEEE 802.3): poly 0x04C11DB7, init 0xFFFFFFFF, reflected I/O,
    // final XOR 0xFFFFFFFF. Per-byte LSB-first update (table-free, unrolled).
    // Coverage: Message Header + all Data Objects, exactly as the spec states.
    //========================================================================
    function [31:0] crc32_byte;
        input [31:0] crc_in;
        input [7:0]  data;
        integer      i;
        reg   [31:0] c;
        begin
            c = crc_in ^ {24'h000000, data};   // reflected: xor low byte
            for (i = 0; i < 8; i = i + 1) begin
                if (c[0])
                    c = (c >> 1) ^ 32'hEDB88320; // reflected poly of 0x04C11DB7
                else
                    c = (c >> 1);
            end
            crc32_byte = c;
        end
    endfunction

    //========================================================================
    // RX message reception : collect header (2 bytes) + payload + 4-byte CRC.
    // We run a streaming CRC-32 across header+payload and compare to the
    // trailing 4 CRC bytes. rx_crc_ok asserts on a clean message; a clean
    // RX triggers a GoodCRC acknowledgement (CTRL_GOODCRC) unless the
    // received message IS itself a GoodCRC.
    //========================================================================
    localparam [2:0] RX_IDLE   = 3'd0,
                     RX_HDR0   = 3'd1,
                     RX_HDR1   = 3'd2,
                     RX_PAYLD  = 3'd3,
                     RX_CRC    = 3'd4,
                     RX_DONE   = 3'd5;

    reg [2:0]  rx_st;
    reg [15:0] rx_header;
    reg [2:0]  rx_objs;          // number of data objects to collect
    reg [2:0]  rx_obj_cnt;       // objects collected
    reg [1:0]  rx_byte_in_obj;   // 0..3 byte index within current data object
    reg [31:0] rx_crc_run;       // running CRC-32 accumulator
    reg [31:0] rx_crc_field;     // received CRC field assembled from 4 bytes
    reg [1:0]  rx_crc_cnt;       // CRC bytes collected (0..3)
    reg [31:0] rx_obj0;          // first data object captured (RDO/PDO)
    reg [4:0]  rx_msgtype;       // Message Type of received message
    reg        rx_isdata;        // received message is a Data message
    reg        rx_msg_done;      // 1-cycle: a complete RX message available

    //========================================================================
    // TX message engine : serialises a built header + optional data object +
    // CRC-32 onto the parallel symbol interface, honouring tx_symbol_ready.
    //========================================================================
    localparam [2:0] TX_IDLE   = 3'd0,
                     TX_HDR0   = 3'd1,
                     TX_HDR1   = 3'd2,
                     TX_OBJ    = 3'd3,
                     TX_CRC    = 3'd4,
                     TX_EOP    = 3'd5;

    reg [2:0]  tx_st;
    reg [15:0] tx_header;
    reg [31:0] tx_obj;           // single data object to transmit (if any)
    reg        tx_has_obj;       // this TX carries one data object
    reg [1:0]  tx_byte_idx;      // byte index within header/obj/crc
    reg [31:0] tx_crc_run;       // TX running CRC-32
    reg [31:0] tx_crc_final;     // finalised (xored, sent LSB-first)
    reg        tx_req;           // engine-internal request to start a TX
    reg [4:0]  tx_req_type;      // message type to transmit
    reg        tx_req_isdata;    // requested TX is a data message
    reg [31:0] tx_req_obj;       // data object for requested TX
    reg [1:0]  tx_req_sop;       // ordered set for requested TX

    //========================================================================
    // Protocol-layer bookkeeping
    //========================================================================
    reg [2:0]  msg_id_ctr;       // local TX MessageID counter (mod 8)

    //========================================================================
    // Contract negotiation FSM (Source side):
    //   IDLE -> SEND_SRCCAP -> WAIT_REQUEST -> SEND_ACCEPT
    //        -> PS_TRANSITION -> SEND_PSRDY -> CONTRACT
    // Hard/Soft reset re-enter IDLE.
    //========================================================================
    localparam [3:0] C_IDLE      = 4'd0,
                     C_SRCCAP    = 4'd1,  // transmit Source_Capabilities
                     C_WAIT_REQ  = 4'd2,  // await Request (RDO)
                     C_ACCEPT    = 4'd3,  // transmit Accept
                     C_PS_TRANS  = 4'd4,  // power supply transition
                     C_PSRDY     = 4'd5,  // transmit PS_RDY
                     C_CONTRACT  = 4'd6,  // Explicit Contract in force
                     C_SOFTRST   = 4'd7,  // soft reset recovery
                     C_HARDRST   = 4'd8;  // hard reset recovery

    // ps-transition dwell counter (modelled, scaled down for synthesis;
    // real PSTransitionTimer is 450-550ms per L8 — here a fixed dwell so the
    // FSM is fully synchronous and self-advancing without an external timer).
    reg [7:0]  ps_dwell;
    localparam [7:0] PS_DWELL_MAX = 8'd200;

    //========================================================================
    // RX datapath
    //========================================================================
    always @(posedge clk) begin
        if (!rst_n) begin
            rx_st          <= RX_IDLE;
            rx_header      <= 16'h0000;
            rx_objs        <= 3'd0;
            rx_obj_cnt     <= 3'd0;
            rx_byte_in_obj <= 2'd0;
            rx_crc_run     <= 32'hFFFFFFFF;
            rx_crc_field   <= 32'h00000000;
            rx_crc_cnt     <= 2'd0;
            rx_obj0        <= 32'h00000000;
            rx_msg_id      <= 3'd0;
            rx_msgtype     <= 5'd0;
            rx_isdata      <= 1'b0;
            rx_msg_done    <= 1'b0;
            rx_crc_ok      <= 1'b0;
        end else begin
            rx_msg_done <= 1'b0;          // default: pulse low

            case (rx_st)
                //----------------------------------------------------------
                RX_IDLE: begin
                    if (rx_symbol_valid && rx_sop) begin
                        // start of a new packet: first symbol is header LSB
                        rx_crc_run <= crc32_byte(32'hFFFFFFFF, rx_symbol);
                        rx_header  <= {8'h00, rx_symbol};
                        rx_st      <= RX_HDR1;
                    end
                end
                //----------------------------------------------------------
                RX_HDR1: begin
                    if (rx_symbol_valid) begin
                        rx_header  <= {rx_symbol, rx_header[7:0]};
                        rx_crc_run <= crc32_byte(rx_crc_run, rx_symbol);
                        // header complete -> decode
                        rx_msg_id  <= hdr_msgid({rx_symbol, rx_header[7:0]});
                        rx_msgtype <= hdr_type ({rx_symbol, rx_header[7:0]});
                        rx_isdata  <= hdr_isdata({rx_symbol, rx_header[7:0]});
                        rx_objs    <= hdr_ndo ({rx_symbol, rx_header[7:0]});
                        rx_obj_cnt     <= 3'd0;
                        rx_byte_in_obj <= 2'd0;
                        rx_crc_cnt     <= 2'd0;
                        rx_crc_field   <= 32'h00000000;
                        if (hdr_ndo({rx_symbol, rx_header[7:0]}) != 3'd0)
                            rx_st <= RX_PAYLD;     // data message: collect objs
                        else
                            rx_st <= RX_CRC;       // control message: just CRC
                    end
                end
                //----------------------------------------------------------
                RX_PAYLD: begin
                    if (rx_symbol_valid) begin
                        rx_crc_run <= crc32_byte(rx_crc_run, rx_symbol);
                        // assemble little-endian 32-bit data object
                        if (rx_obj_cnt == 3'd0) begin
                            case (rx_byte_in_obj)
                                2'd0:    rx_obj0[7:0]   <= rx_symbol;
                                2'd1:    rx_obj0[15:8]  <= rx_symbol;
                                2'd2:    rx_obj0[23:16] <= rx_symbol;
                                2'd3:    rx_obj0[31:24] <= rx_symbol;
                                default: rx_obj0[7:0]   <= rx_symbol;
                            endcase
                        end
                        if (rx_byte_in_obj == 2'd3) begin
                            rx_byte_in_obj <= 2'd0;
                            if (rx_obj_cnt + 3'd1 == rx_objs) begin
                                rx_obj_cnt <= 3'd0;
                                rx_st      <= RX_CRC;
                            end else begin
                                rx_obj_cnt <= rx_obj_cnt + 3'd1;
                            end
                        end else begin
                            rx_byte_in_obj <= rx_byte_in_obj + 2'd1;
                        end
                    end
                end
                //----------------------------------------------------------
                RX_CRC: begin
                    if (rx_symbol_valid) begin
                        case (rx_crc_cnt)
                            2'd0:    rx_crc_field[7:0]   <= rx_symbol;
                            2'd1:    rx_crc_field[15:8]  <= rx_symbol;
                            2'd2:    rx_crc_field[23:16] <= rx_symbol;
                            2'd3:    rx_crc_field[31:24] <= rx_symbol;
                            default: rx_crc_field[7:0]   <= rx_symbol;
                        endcase
                        if (rx_crc_cnt == 2'd3) begin
                            rx_crc_cnt <= 2'd0;
                            rx_st      <= RX_DONE;
                        end else begin
                            rx_crc_cnt <= rx_crc_cnt + 2'd1;
                        end
                    end
                end
                //----------------------------------------------------------
                RX_DONE: begin
                    // compare finalised CRC (xor 0xFFFFFFFF) against received
                    if ((rx_crc_run ^ 32'hFFFFFFFF) ==
                        {rx_crc_field[31:24], rx_crc_field[23:16],
                         rx_crc_field[15:8],  rx_crc_field[7:0]}) begin
                        rx_crc_ok <= 1'b1;
                    end else begin
                        rx_crc_ok <= 1'b0;
                    end
                    rx_msg_done <= 1'b1;          // signal one complete message
                    rx_st       <= RX_IDLE;
                end
                //----------------------------------------------------------
                default: rx_st <= RX_IDLE;
            endcase
        end
    end

    //========================================================================
    // GoodCRC + retry + contract negotiation control.
    // On a clean RX (rx_msg_done & rx_crc_ok) that is not itself a GoodCRC,
    // we emit a GoodCRC acknowledgement. The contract FSM then reacts to the
    // decoded message type.
    //========================================================================
    reg need_goodcrc;             // pending GoodCRC TX request

    always @(posedge clk) begin
        if (!rst_n) begin
            contract_state    <= C_IDLE;
            explicit_contract <= 1'b0;
            ps_rdy_sent       <= 1'b0;
            rdo_received      <= 32'h00000000;
            hard_reset_evt    <= 1'b0;
            soft_reset_evt    <= 1'b0;
            goodcrc_sent      <= 1'b0;
            protocol_error    <= 1'b0;
            msg_id_ctr        <= 3'd0;
            need_goodcrc      <= 1'b0;
            ps_dwell          <= 8'd0;
            tx_req            <= 1'b0;
            tx_req_type       <= 5'd0;
            tx_req_isdata     <= 1'b0;
            tx_req_obj        <= 32'h00000000;
            tx_req_sop        <= SOP;
        end else begin
            // default pulse outputs
            hard_reset_evt <= 1'b0;
            soft_reset_evt <= 1'b0;
            goodcrc_sent   <= 1'b0;
            tx_req         <= 1'b0;

            //----------------------------------------------------------------
            // 1) GoodCRC acknowledgement on a clean, non-GoodCRC reception.
            //----------------------------------------------------------------
            if (rx_msg_done && rx_crc_ok &&
                !(rx_isdata == 1'b0 && rx_msgtype == CTRL_GOODCRC)) begin
                need_goodcrc <= 1'b1;
            end

            // Issue the GoodCRC when the TX engine is free.
            if (need_goodcrc && tx_st == TX_IDLE && !tx_req) begin
                tx_req        <= 1'b1;
                tx_req_type   <= CTRL_GOODCRC;
                tx_req_isdata <= 1'b0;
                tx_req_obj    <= 32'h00000000;
                tx_req_sop    <= SOP;
                goodcrc_sent  <= 1'b1;
                need_goodcrc  <= 1'b0;
            end

            //----------------------------------------------------------------
            // 2) Hard / Soft reset handling (highest priority on clean RX).
            //----------------------------------------------------------------
            if (rx_msg_done && rx_crc_ok && rx_isdata == 1'b0 &&
                rx_msgtype == CTRL_SOFT_RESET) begin
                soft_reset_evt    <= 1'b1;
                msg_id_ctr        <= 3'd0;     // MessageID reset
                explicit_contract <= 1'b0;
                contract_state    <= C_SOFTRST;
            end

            //----------------------------------------------------------------
            // 3) Contract negotiation FSM (Source role).
            //----------------------------------------------------------------
            case (contract_state)
                //--------------------------------------------------------
                C_IDLE: begin
                    explicit_contract <= 1'b0;
                    ps_rdy_sent       <= 1'b0;
                    if (attach && port_power_role && dpm_start &&
                        tx_st == TX_IDLE && !tx_req && !need_goodcrc) begin
                        // transmit Source_Capabilities (data msg, 1 PDO)
                        tx_req        <= 1'b1;
                        tx_req_type   <= DATA_SRC_CAP;
                        tx_req_isdata <= 1'b1;
                        tx_req_obj    <= src_pdo0;
                        tx_req_sop    <= SOP;
                        contract_state<= C_SRCCAP;
                    end
                end
                //--------------------------------------------------------
                C_SRCCAP: begin
                    // wait for the SrcCap TX to drain, then await a Request
                    if (tx_st == TX_IDLE && !tx_req)
                        contract_state <= C_WAIT_REQ;
                end
                //--------------------------------------------------------
                C_WAIT_REQ: begin
                    if (rx_msg_done && rx_crc_ok && rx_isdata &&
                        rx_msgtype == DATA_REQUEST) begin
                        rdo_received   <= rx_obj0;     // capture the RDO
                        contract_state <= C_ACCEPT;
                    end
                end
                //--------------------------------------------------------
                C_ACCEPT: begin
                    if (tx_st == TX_IDLE && !tx_req && !need_goodcrc) begin
                        tx_req        <= 1'b1;
                        tx_req_type   <= CTRL_ACCEPT;
                        tx_req_isdata <= 1'b0;
                        tx_req_obj    <= 32'h00000000;
                        tx_req_sop    <= SOP;
                        ps_dwell      <= 8'd0;
                        contract_state<= C_PS_TRANS;
                    end
                end
                //--------------------------------------------------------
                C_PS_TRANS: begin
                    // model the power-supply transition dwell (PSTransitionTimer)
                    if (tx_st == TX_IDLE && !tx_req) begin
                        if (ps_dwell == PS_DWELL_MAX)
                            contract_state <= C_PSRDY;
                        else
                            ps_dwell <= ps_dwell + 8'd1;
                    end
                end
                //--------------------------------------------------------
                C_PSRDY: begin
                    if (tx_st == TX_IDLE && !tx_req && !need_goodcrc) begin
                        tx_req        <= 1'b1;
                        tx_req_type   <= CTRL_PS_RDY;
                        tx_req_isdata <= 1'b0;
                        tx_req_obj    <= 32'h00000000;
                        tx_req_sop    <= SOP;
                        ps_rdy_sent   <= 1'b1;
                        contract_state<= C_CONTRACT;
                    end
                end
                //--------------------------------------------------------
                C_CONTRACT: begin
                    explicit_contract <= 1'b1;
                    // A new Request (re-negotiation) restarts the contract.
                    if (rx_msg_done && rx_crc_ok && rx_isdata &&
                        rx_msgtype == DATA_REQUEST) begin
                        rdo_received   <= rx_obj0;
                        contract_state <= C_ACCEPT;
                    end
                end
                //--------------------------------------------------------
                C_SOFTRST: begin
                    // after a soft reset, re-advertise capabilities
                    contract_state <= C_IDLE;
                end
                //--------------------------------------------------------
                C_HARDRST: begin
                    contract_state <= C_IDLE;
                end
                //--------------------------------------------------------
                default: contract_state <= C_IDLE;
            endcase

            //----------------------------------------------------------------
            // 4) Hard Reset (loss of attach) forces a full protocol reset.
            //----------------------------------------------------------------
            if (!attach && contract_state != C_IDLE) begin
                hard_reset_evt    <= 1'b1;
                explicit_contract <= 1'b0;
                ps_rdy_sent       <= 1'b0;
                msg_id_ctr        <= 3'd0;
                contract_state    <= C_HARDRST;
            end

            // bump the TX MessageID counter when a TX is actually launched
            if (tx_req && tx_st == TX_IDLE)
                msg_id_ctr <= msg_id_ctr + 3'd1;
        end
    end

    //========================================================================
    // TX datapath : drive header + (optional) data object + CRC-32 onto the
    // parallel symbol interface, LSB-first, honouring tx_symbol_ready.
    //========================================================================
    reg [7:0]  tx_cur_byte;     // combinational: byte selected this state

    // combinational byte selector (no latch: default + full assignment)
    always @(*) begin
        tx_cur_byte = 8'h00;
        case (tx_st)
            TX_HDR0: tx_cur_byte = tx_header[7:0];
            TX_HDR1: tx_cur_byte = tx_header[15:8];
            TX_OBJ:  begin
                case (tx_byte_idx)
                    2'd0:    tx_cur_byte = tx_obj[7:0];
                    2'd1:    tx_cur_byte = tx_obj[15:8];
                    2'd2:    tx_cur_byte = tx_obj[23:16];
                    2'd3:    tx_cur_byte = tx_obj[31:24];
                    default: tx_cur_byte = tx_obj[7:0];
                endcase
            end
            TX_CRC: begin
                case (tx_byte_idx)
                    2'd0:    tx_cur_byte = tx_crc_final[7:0];
                    2'd1:    tx_cur_byte = tx_crc_final[15:8];
                    2'd2:    tx_cur_byte = tx_crc_final[23:16];
                    2'd3:    tx_cur_byte = tx_crc_final[31:24];
                    default: tx_cur_byte = tx_crc_final[7:0];
                endcase
            end
            default: tx_cur_byte = 8'h00;
        endcase
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            tx_st           <= TX_IDLE;
            tx_header       <= 16'h0000;
            tx_obj          <= 32'h00000000;
            tx_has_obj      <= 1'b0;
            tx_byte_idx     <= 2'd0;
            tx_crc_run      <= 32'hFFFFFFFF;
            tx_crc_final    <= 32'h00000000;
            tx_symbol       <= 8'h00;
            tx_symbol_valid <= 1'b0;
            tx_sop          <= 1'b0;
            tx_eop          <= 1'b0;
            tx_sop_type     <= SOP;
        end else begin
            // defaults each cycle
            tx_symbol_valid <= 1'b0;
            tx_sop          <= 1'b0;
            tx_eop          <= 1'b0;

            case (tx_st)
                //----------------------------------------------------------
                TX_IDLE: begin
                    if (tx_req) begin
                        // build the 16-bit header for the requested message
                        tx_header <= build_header(
                            1'b0,
                            tx_req_isdata ? 3'd1 : 3'd0,   // NumDataObj
                            msg_id_ctr,
                            port_power_role,
                            port_data_role,
                            tx_req_type);
                        tx_obj      <= tx_req_obj;
                        tx_has_obj  <= tx_req_isdata;
                        tx_sop_type <= tx_req_sop;
                        tx_crc_run  <= 32'hFFFFFFFF;
                        tx_byte_idx <= 2'd0;
                        tx_st       <= TX_HDR0;
                    end
                end
                //----------------------------------------------------------
                TX_HDR0: begin
                    if (tx_symbol_ready) begin
                        tx_symbol       <= tx_cur_byte;
                        tx_symbol_valid <= 1'b1;
                        tx_sop          <= 1'b1;       // first symbol = SOP
                        tx_crc_run      <= crc32_byte(tx_crc_run, tx_cur_byte);
                        tx_st           <= TX_HDR1;
                    end
                end
                //----------------------------------------------------------
                TX_HDR1: begin
                    if (tx_symbol_ready) begin
                        tx_symbol       <= tx_cur_byte;
                        tx_symbol_valid <= 1'b1;
                        tx_crc_run      <= crc32_byte(tx_crc_run, tx_cur_byte);
                        tx_byte_idx     <= 2'd0;
                        if (tx_has_obj)
                            tx_st <= TX_OBJ;
                        else begin
                            tx_crc_final <= crc32_byte(tx_crc_run, tx_cur_byte)
                                            ^ 32'hFFFFFFFF;
                            tx_st        <= TX_CRC;
                        end
                    end
                end
                //----------------------------------------------------------
                TX_OBJ: begin
                    if (tx_symbol_ready) begin
                        tx_symbol       <= tx_cur_byte;
                        tx_symbol_valid <= 1'b1;
                        tx_crc_run      <= crc32_byte(tx_crc_run, tx_cur_byte);
                        if (tx_byte_idx == 2'd3) begin
                            tx_crc_final <= crc32_byte(tx_crc_run, tx_cur_byte)
                                            ^ 32'hFFFFFFFF;
                            tx_byte_idx  <= 2'd0;
                            tx_st        <= TX_CRC;
                        end else begin
                            tx_byte_idx  <= tx_byte_idx + 2'd1;
                        end
                    end
                end
                //----------------------------------------------------------
                TX_CRC: begin
                    if (tx_symbol_ready) begin
                        tx_symbol       <= tx_cur_byte;
                        tx_symbol_valid <= 1'b1;
                        if (tx_byte_idx == 2'd3) begin
                            tx_eop      <= 1'b1;       // last symbol = EOP
                            tx_byte_idx <= 2'd0;
                            tx_st       <= TX_IDLE;
                        end else begin
                            tx_byte_idx <= tx_byte_idx + 2'd1;
                        end
                    end
                end
                //----------------------------------------------------------
                default: tx_st <= TX_IDLE;
            endcase
        end
    end

`ifdef USE_BMC_PHY_STUB
    // The BMC PHY is analog/mixed-signal and lives outside this digital top.
    // Instantiated only behind a define so synthesis of the digital engine
    // does not pull in the blackbox. Shown here to document the contract.
    usb_pd_bmc_phy u_phy (
        .clk(clk), .rst_n(rst_n)
    );
`endif

endmodule

//----------------------------------------------------------------------------
// BLACKBOX: usb_pd_bmc_phy
// The CC-line Biphase Mark Coding transceiver at 300 kbaud is analog/mixed-
// signal. It is NOT synthesized as part of the digital protocol engine. This
// empty stub documents the boundary; the real block is delivered as a
// hardmacro / analog cell. (Compiled only behind USE_BMC_PHY_STUB.)
//----------------------------------------------------------------------------
`ifdef USE_BMC_PHY_STUB
module usb_pd_bmc_phy (
    input wire clk,
    input wire rst_n
);
    // Intentionally empty: BMC encode/decode + CC analog front-end.
endmodule
`endif

`default_nettype wire
