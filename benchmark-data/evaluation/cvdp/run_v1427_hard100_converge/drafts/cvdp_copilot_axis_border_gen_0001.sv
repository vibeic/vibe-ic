`timescale 1ps / 1ps

module axis_image_border_gen #(
    parameter IMG_WIDTH  = 336,               // Image width (X resolution)
    parameter IMG_HEIGHT = 256,              // Image height (Y resolution)
    parameter BORDER_COLOR = 16'hFFFF,       // Border pixel value
    parameter DATA_MASK    = 16'h0000        // Mask for input pixels
)(
    input  wire            clk,              // AXI clock
    input  wire            resetn,           // Active-low reset

    // AXI Stream input interface
    input  wire [15:0]     s_axis_tdata,     // Input stream data
    input  wire            s_axis_tvalid,    // Input data valid
    output wire            s_axis_tready,    // Output ready
    input  wire            s_axis_tlast,     // Input last signal
    input  wire            s_axis_tuser,     // Frame start signal

    // AXI Stream output interface
    output wire [15:0]     m_axis_tdata,     // Output stream data
    output wire            m_axis_tvalid,    // Output data valid
    input  wire            m_axis_tready,    // Input ready
    output wire            m_axis_tlast,     // Output last signal
    output wire            m_axis_tuser      // Frame start signal
);

    // State definitions
    localparam [2:0] ST_IDLE        = 3'd0;  // Wait for a new frame start (s_axis_tuser)
    localparam [2:0] ST_ROW_FIRST   = 3'd1;  // Emit the first (top border) row
    localparam [2:0] ST_PROCESS_ROW = 3'd2;  // Emit middle rows: left/right border + image data
    localparam [2:0] ST_BORDER_ROW  = 3'd3;  // Emit the bottom border row
    localparam [2:0] ST_ROW_LAST    = 3'd4;  // Frame complete, return to idle

    // Output frame geometry: input image plus a one-pixel border ring
    localparam integer OUT_WIDTH  = IMG_WIDTH  + 2;
    localparam integer OUT_HEIGHT = IMG_HEIGHT + 2;
    localparam integer FRAME_PIX  = (IMG_WIDTH * IMG_HEIGHT < 1) ? 1
                                                                 : IMG_WIDTH * IMG_HEIGHT;

    // State and Counter Registers
    reg [2:0] state, next_state;
    reg [15:0] x_count, y_count;
    reg border_valid;

    // Internal Control Signals
    wire is_top_row     = (y_count == 16'd0);
    wire is_bottom_row  = (y_count == IMG_HEIGHT + 1);
    wire is_left_border  = (x_count == 16'd0);
    wire is_right_border = (x_count == IMG_WIDTH + 1);
    wire is_border_pixel = (is_top_row || is_bottom_row || is_left_border || is_right_border);

    // ------------------------------------------------------------------
    // Input (receive) side: store-and-forward full-frame buffer.
    // The input pixel count (W*H) differs from the output pixel count
    // ((W+2)*(H+2)), so input and output are decoupled through a frame
    // buffer: a RECEIVE phase fills the buffer, then the FSM emits the
    // bordered frame.
    // ------------------------------------------------------------------
    reg [15:0] frame_buf [0:FRAME_PIX-1];
    reg        rx_active;                     // Currently capturing a frame
    reg        frame_done;                    // Full frame stored; emitting
    reg [31:0] rx_count;                      // Write index into frame_buf

    wire s_beat    = s_axis_tvalid && s_axis_tready;
    wire rx_take   = s_beat && (rx_active || s_axis_tuser);
    wire emit_done = (state == ST_ROW_LAST);

    // Ready to accept input whenever a full frame is not being emitted
    assign s_axis_tready = resetn && !frame_done;

    // Frame buffer write
    always @(posedge clk) begin
        if (rx_take)
            frame_buf[rx_count] <= s_axis_tdata;
    end

    // Receive control
    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            rx_active  <= 1'b0;
            frame_done <= 1'b0;
            rx_count   <= 32'd0;
        end else begin
            if (rx_take) begin
                if (rx_count == FRAME_PIX - 1) begin
                    rx_active  <= 1'b0;
                    frame_done <= 1'b1;
                    rx_count   <= 32'd0;
                end else begin
                    rx_active  <= 1'b1;
                    rx_count   <= rx_count + 32'd1;
                end
            end
            if (emit_done)
                frame_done <= 1'b0;
        end
    end

    // ------------------------------------------------------------------
    // FSM and Counter Logic (output / emit side)
    // ------------------------------------------------------------------
    wire m_beat  = m_axis_tvalid && m_axis_tready;
    wire row_end = (x_count == OUT_WIDTH - 1);

    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            // Reset the variables
            state        <= ST_IDLE;
            x_count      <= 16'd0;
            y_count      <= 16'd0;
            border_valid <= 1'b0;
        end else begin
            state        <= next_state;
            border_valid <= m_axis_tvalid && is_border_pixel;
            case (state)
                ST_IDLE: begin
                    x_count <= 16'd0;
                    y_count <= 16'd0;
                end
                ST_ROW_FIRST,
                ST_PROCESS_ROW,
                ST_BORDER_ROW: begin
                    // Advance output position only on an accepted beat
                    if (m_beat) begin
                        if (row_end) begin
                            x_count <= 16'd0;
                            y_count <= y_count + 16'd1;
                        end else begin
                            x_count <= x_count + 16'd1;
                        end
                    end
                end
                ST_ROW_LAST: begin
                    x_count <= 16'd0;
                    y_count <= 16'd0;
                end
                default: begin
                    x_count <= 16'd0;
                    y_count <= 16'd0;
                end
            endcase
        end
    end

    // FSM next-state logic
    always @* begin
        next_state = state;
        case (state)
            ST_IDLE: begin
                if (frame_done)
                    next_state = ST_ROW_FIRST;
            end
            ST_ROW_FIRST: begin
                if (m_beat && row_end)
                    next_state = (IMG_HEIGHT == 0) ? ST_BORDER_ROW : ST_PROCESS_ROW;
            end
            ST_PROCESS_ROW: begin
                if (m_beat && row_end && (y_count == IMG_HEIGHT))
                    next_state = ST_BORDER_ROW;
            end
            ST_BORDER_ROW: begin
                if (m_beat && row_end)
                    next_state = ST_ROW_LAST;
            end
            ST_ROW_LAST: begin
                next_state = ST_IDLE;
            end
            default: begin
                next_state = ST_IDLE;
            end
        endcase
    end

    // ------------------------------------------------------------------
    // Buffer read: inner pixel at (x_count-1, y_count-1)
    // ------------------------------------------------------------------
    wire [15:0] ix = x_count - 16'd1;
    wire [15:0] iy = y_count - 16'd1;
    wire [31:0] rd_index = is_border_pixel ? 32'd0 : (iy * IMG_WIDTH + ix);
    wire [15:0] inner_pixel = frame_buf[rd_index];

    // ------------------------------------------------------------------
    // AXI Stream output signals
    // ------------------------------------------------------------------
    assign m_axis_tvalid = (state == ST_ROW_FIRST) ||
                           (state == ST_PROCESS_ROW) ||
                           (state == ST_BORDER_ROW);
    assign m_axis_tdata  = is_border_pixel ? BORDER_COLOR[15:0]
                                           : (inner_pixel | DATA_MASK[15:0]);
    assign m_axis_tlast  = m_axis_tvalid && row_end;
    assign m_axis_tuser  = m_axis_tvalid && (state == ST_ROW_FIRST) && (x_count == 16'd0);

endmodule
