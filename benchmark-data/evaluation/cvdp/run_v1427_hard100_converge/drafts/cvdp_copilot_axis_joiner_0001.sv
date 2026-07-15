`timescale 1ns/1ps
//------------------------------------------------------------------------------
// axis_joiner
//
// Merges three independent AXI-Stream inputs into a single AXI-Stream output.
//
//  * FSM states  : STATE_IDLE, STATE_1, STATE_2, STATE_3
//  * Arbitration : from STATE_IDLE the spec-stated precedence applies —
//                  stream 1 first, then stream 2, then stream 3.
//  * Packet hold : once a stream is selected the FSM stays with it until the
//                  beat carrying tlast is actually transferred on the merged
//                  output, then it returns to STATE_IDLE.
//  * Stall buffer: if m_axis_tready deasserts while the active stream presents
//                  a valid beat, that beat is captured into internal `temp`
//                  registers (temp flag set) and is driven onto the output
//                  until m_axis_tready reasserts — seamless, lossless transfer.
//  * tuser       : tags the source of every output beat (TAG_ID_1/2/3).
//  * rst         : asynchronous, active-high; initialises all state variables
//                  and output signals (m_axis_tvalid / busy / treadys all 0).
//  * busy        : high whenever the module is actively processing a stream.
//------------------------------------------------------------------------------

module axis_joiner (
    input  wire       clk,             // System clock
    input  wire       rst,             // Asynchronous active-high reset

    // AXI Stream input 1
    input  wire [7:0] s_axis_tdata_1,
    input  wire       s_axis_tvalid_1,
    output wire       s_axis_tready_1,
    input  wire       s_axis_tlast_1,

    // AXI Stream input 2
    input  wire [7:0] s_axis_tdata_2,
    input  wire       s_axis_tvalid_2,
    output wire       s_axis_tready_2,
    input  wire       s_axis_tlast_2,

    // AXI Stream input 3
    input  wire [7:0] s_axis_tdata_3,
    input  wire       s_axis_tvalid_3,
    output wire       s_axis_tready_3,
    input  wire       s_axis_tlast_3,

    // Merged AXI Stream output
    output wire [7:0] m_axis_tdata,
    output wire       m_axis_tvalid,
    input  wire       m_axis_tready,
    output wire       m_axis_tlast,
    output wire [1:0] m_axis_tuser,    // Source tag (TAG_ID) of the beat

    // Status
    output wire       busy             // Module is processing a stream
);

    //--------------------------------------------------------------------------
    // FSM state encoding
    //--------------------------------------------------------------------------
    localparam [1:0] STATE_IDLE = 2'd0;
    localparam [1:0] STATE_1    = 2'd1;
    localparam [1:0] STATE_2    = 2'd2;
    localparam [1:0] STATE_3    = 2'd3;

    // Source tags carried on m_axis_tuser
    localparam [1:0] TAG_ID_1 = 2'h1;
    localparam [1:0] TAG_ID_2 = 2'h2;
    localparam [1:0] TAG_ID_3 = 2'h3;

    reg [1:0] state;

    //--------------------------------------------------------------------------
    // temp (stall) buffer — retains the current beat while the output is
    // stalled (m_axis_tready deasserted) so no data is ever lost.
    //--------------------------------------------------------------------------
    reg       temp;
    reg [7:0] temp_tdata;
    reg       temp_tlast;
    reg [1:0] temp_tuser;

    //--------------------------------------------------------------------------
    // Input MUX — selects the active stream's tdata / tvalid / tlast / tuser
    // based on the current FSM state.
    //--------------------------------------------------------------------------
    reg [7:0] sel_tdata;
    reg       sel_tvalid;
    reg       sel_tlast;
    reg [1:0] sel_tuser;

    always @(*) begin
        case (state)
            STATE_1: begin
                sel_tdata  = s_axis_tdata_1;
                sel_tvalid = s_axis_tvalid_1;
                sel_tlast  = s_axis_tlast_1;
                sel_tuser  = TAG_ID_1;
            end
            STATE_2: begin
                sel_tdata  = s_axis_tdata_2;
                sel_tvalid = s_axis_tvalid_2;
                sel_tlast  = s_axis_tlast_2;
                sel_tuser  = TAG_ID_2;
            end
            STATE_3: begin
                sel_tdata  = s_axis_tdata_3;
                sel_tvalid = s_axis_tvalid_3;
                sel_tlast  = s_axis_tlast_3;
                sel_tuser  = TAG_ID_3;
            end
            default: begin // STATE_IDLE
                sel_tdata  = 8'd0;
                sel_tvalid = 1'b0;
                sel_tlast  = 1'b0;
                sel_tuser  = 2'd0;
            end
        endcase
    end

    //--------------------------------------------------------------------------
    // Output signal assignments — the retained (temp) beat has priority so the
    // stalled beat is presented, stable, until the output is ready again.
    //--------------------------------------------------------------------------
    assign m_axis_tdata  = temp ? temp_tdata : sel_tdata;
    assign m_axis_tvalid = temp ? 1'b1       : sel_tvalid;
    assign m_axis_tlast  = temp ? temp_tlast : sel_tlast;
    assign m_axis_tuser  = temp ? temp_tuser : sel_tuser;

    //--------------------------------------------------------------------------
    // tready management — only the active input stream is acknowledged, and
    // backpressure from the merged output propagates straight upstream.
    //--------------------------------------------------------------------------
    assign s_axis_tready_1 = (state == STATE_1) && m_axis_tready;
    assign s_axis_tready_2 = (state == STATE_2) && m_axis_tready;
    assign s_axis_tready_3 = (state == STATE_3) && m_axis_tready;

    // Busy whenever a stream is being serviced.
    assign busy = (state != STATE_IDLE);

    // Output-side handshake / end-of-packet detection.
    wire out_handshake = m_axis_tvalid && m_axis_tready;
    wire last_transfer = out_handshake && m_axis_tlast;

    //--------------------------------------------------------------------------
    // FSM — priority selection in IDLE (1 > 2 > 3), return to IDLE once the
    // packet's tlast beat has been transferred on the merged output.
    //--------------------------------------------------------------------------
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= STATE_IDLE;
        end else begin
            case (state)
                STATE_IDLE: begin
                    if (s_axis_tvalid_1)
                        state <= STATE_1;
                    else if (s_axis_tvalid_2)
                        state <= STATE_2;
                    else if (s_axis_tvalid_3)
                        state <= STATE_3;
                end
                STATE_1, STATE_2, STATE_3: begin
                    if (last_transfer)
                        state <= STATE_IDLE;
                end
                default: state <= STATE_IDLE;
            endcase
        end
    end

    //--------------------------------------------------------------------------
    // temp buffer control — capture the in-flight beat the moment the output
    // stalls, hold it (retention), release once m_axis_tready reasserts.
    //--------------------------------------------------------------------------
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            temp       <= 1'b0;
            temp_tdata <= 8'd0;
            temp_tlast <= 1'b0;
            temp_tuser <= 2'd0;
        end else begin
            if (m_axis_tready) begin
                // Downstream ready again — the retained beat drains this cycle
                temp <= 1'b0;
            end else if (!temp && sel_tvalid) begin
                // Output stalled while a valid beat is in flight: retain it
                temp       <= 1'b1;
                temp_tdata <= sel_tdata;
                temp_tlast <= sel_tlast;
                temp_tuser <= sel_tuser;
            end
        end
    end

endmodule
