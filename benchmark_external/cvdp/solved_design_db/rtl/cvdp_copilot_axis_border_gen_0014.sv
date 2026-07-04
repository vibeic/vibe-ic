module axis_border_gen_with_resize #(
    parameter IMG_WIDTH_IN   = 640,
    parameter IMG_HEIGHT_IN  = 480,
    parameter IMG_WIDTH_OUT  = 320,
    parameter IMG_HEIGHT_OUT = 240,
    parameter BORDER_COLOR   = 16'hFFFF,
    parameter DATA_WIDTH     = 16
)(
    input  wire                  clk,
    input  wire                  resetn,
    input  wire [DATA_WIDTH-1:0] s_axis_tdata,
    input  wire                  s_axis_tvalid,
    output wire                  s_axis_tready,
    input  wire                  s_axis_tlast,
    input  wire                  s_axis_tuser,
    output wire [DATA_WIDTH-1:0] m_axis_tdata,
    output wire                  m_axis_tvalid,
    input  wire                  m_axis_tready,
    output wire                  m_axis_tlast,
    output wire                  m_axis_tuser
);
    wire [DATA_WIDTH-1:0] rz_tdata;
    wire                  rz_tvalid;
    wire                  rz_tready;
    wire                  rz_tlast;
    wire                  rz_tuser;

    axis_image_resizer #(
        .IMG_WIDTH_IN  (IMG_WIDTH_IN),
        .IMG_HEIGHT_IN (IMG_HEIGHT_IN),
        .IMG_WIDTH_OUT (IMG_WIDTH_OUT),
        .IMG_HEIGHT_OUT(IMG_HEIGHT_OUT),
        .DATA_WIDTH    (DATA_WIDTH)
    ) resizer_inst (
        .clk          (clk),
        .resetn       (resetn),
        .s_axis_tdata (s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .s_axis_tlast (s_axis_tlast),
        .s_axis_tuser (s_axis_tuser),
        .m_axis_tdata (rz_tdata),
        .m_axis_tvalid(rz_tvalid),
        .m_axis_tready(rz_tready),
        .m_axis_tlast (rz_tlast),
        .m_axis_tuser (rz_tuser)
    );

    axis_image_border_gen #(
        .IMG_WIDTH   (IMG_WIDTH_OUT),
        .IMG_HEIGHT  (IMG_HEIGHT_OUT),
        .BORDER_COLOR(BORDER_COLOR),
        .DATA_WIDTH  (DATA_WIDTH)
    ) border_gen_inst (
        .clk          (clk),
        .resetn       (resetn),
        .s_axis_tdata (rz_tdata),
        .s_axis_tvalid(rz_tvalid),
        .s_axis_tready(rz_tready),
        .s_axis_tlast (rz_tlast),
        .s_axis_tuser (rz_tuser),
        .m_axis_tdata (m_axis_tdata),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready),
        .m_axis_tlast (m_axis_tlast),
        .m_axis_tuser (m_axis_tuser)
    );
endmodule


module axis_image_border_gen #(
    parameter IMG_WIDTH    = 5,
    parameter IMG_HEIGHT   = 5,
    parameter BORDER_COLOR = 16'hFFFF,
    parameter DATA_WIDTH   = 16
)(
    input  wire                  clk,
    input  wire                  resetn,
    input  wire [DATA_WIDTH-1:0] s_axis_tdata,
    input  wire                  s_axis_tvalid,
    output wire                  s_axis_tready,
    input  wire                  s_axis_tlast,
    input  wire                  s_axis_tuser,

    output wire [DATA_WIDTH-1:0] m_axis_tdata,
    output wire                  m_axis_tvalid,
    input  wire                  m_axis_tready,
    output wire                  m_axis_tlast,
    output wire                  m_axis_tuser
);
    localparam integer NEEDED = IMG_WIDTH * IMG_HEIGHT;

    reg [DATA_WIDTH-1:0] rz_mem [0:NEEDED-1];

    integer recv_cnt;
    reg     recving;
    reg     out_active;
    integer ox, oy;

    // Accept resized pixels until the buffer is full.
    assign s_axis_tready = resetn & recving;

    wire is_border = (ox == 0) || (ox == IMG_WIDTH + 1) ||
                     (oy == 0) || (oy == IMG_HEIGHT + 1);

    wire [31:0] inner_idx = is_border ? 32'd0
                                      : ((oy - 1) * IMG_WIDTH + (ox - 1));

    assign m_axis_tvalid = out_active;
    assign m_axis_tlast  = out_active && (ox == IMG_WIDTH + 1);
    assign m_axis_tuser  = out_active && (ox == 0) && (oy == 0);
    assign m_axis_tdata  = is_border ? BORDER_COLOR[DATA_WIDTH-1:0]
                                     : rz_mem[inner_idx];

    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            recv_cnt   <= 0;
            recving    <= 1'b1;
            out_active <= 1'b0;
            ox         <= 0;
            oy         <= 0;
        end else begin
            // ---- RECEIVE: buffer the resized frame ----
            if (recving && s_axis_tvalid && s_axis_tready) begin
                rz_mem[recv_cnt] <= s_axis_tdata;
                if (recv_cnt == NEEDED-1) begin
                    recving    <= 1'b0;
                    out_active <= 1'b1;
                    ox         <= 0;
                    oy         <= 0;
                end
                recv_cnt <= recv_cnt + 1;
            end

            // ---- OUTPUT: stream the bordered frame ----
            if (out_active && m_axis_tready) begin
                if (ox == IMG_WIDTH + 1) begin
                    ox <= 0;
                    if (oy == IMG_HEIGHT + 1)
                        out_active <= 1'b0; // frame done
                    else
                        oy <= oy + 1;
                end else begin
                    ox <= ox + 1;
                end
            end
        end
    end
endmodule


module axis_image_resizer #(
    parameter IMG_WIDTH_IN   = 640,
    parameter IMG_HEIGHT_IN  = 480,
    parameter IMG_WIDTH_OUT  = 320,
    parameter IMG_HEIGHT_OUT = 240,
    parameter DATA_WIDTH     = 16
)(
    input  wire                  clk,
    input  wire                  resetn,
    input  wire [DATA_WIDTH-1:0] s_axis_tdata,
    input  wire                  s_axis_tvalid,
    output wire                  s_axis_tready,
    input  wire                  s_axis_tlast,
    input  wire                  s_axis_tuser,

    output reg  [DATA_WIDTH-1:0] m_axis_tdata,
    output reg                   m_axis_tvalid,
    input  wire                  m_axis_tready,
    output reg                   m_axis_tlast,
    output reg                   m_axis_tuser
);
    localparam integer SX        = IMG_WIDTH_IN  / IMG_WIDTH_OUT;
    localparam integer SY        = IMG_HEIGHT_IN / IMG_HEIGHT_OUT;
    localparam integer NX        = (IMG_WIDTH_IN + SX - 1) / SX; // ceil(W_IN/SX)
    localparam integer TOTAL_IN  = IMG_WIDTH_IN * IMG_HEIGHT_IN;
    localparam integer NEEDED    = IMG_WIDTH_OUT * IMG_HEIGHT_OUT;

    reg [DATA_WIDTH-1:0] in_mem [0:TOTAL_IN-1];

    integer in_cnt;
    integer emit_cnt;
    reg     filling;
    reg     emitting;
    integer src_addr;

    // Accept input while still buffering the frame.
    assign s_axis_tready = resetn & filling;

    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            in_cnt        <= 0;
            emit_cnt      <= 0;
            filling       <= 1'b1;
            emitting      <= 1'b0;
            m_axis_tvalid <= 1'b0;
            m_axis_tdata  <= {DATA_WIDTH{1'b0}};
            m_axis_tlast  <= 1'b0;
            m_axis_tuser  <= 1'b0;
        end else begin
            // ---- FILL: buffer the whole input frame ----
            if (filling && s_axis_tvalid && s_axis_tready) begin
                in_mem[in_cnt] <= s_axis_tdata;
                if (in_cnt == TOTAL_IN-1) begin
                    filling  <= 1'b0;
                    emitting <= 1'b1;
                end
                in_cnt <= in_cnt + 1;
            end

            // ---- EMIT: stream the resized pixels in flat order ----
            if (emitting && (m_axis_tready || !m_axis_tvalid)) begin
                if (emit_cnt < NEEDED) begin
                    src_addr     = (emit_cnt / NX) * SY * IMG_WIDTH_IN
                                 + (emit_cnt % NX) * SX;
                    m_axis_tvalid <= 1'b1;
                    m_axis_tdata  <= in_mem[src_addr];
                    m_axis_tuser  <= (emit_cnt == 0);
                    m_axis_tlast  <= (((emit_cnt + 1) % IMG_WIDTH_OUT) == 0);
                    emit_cnt      <= emit_cnt + 1;
                end else begin
                    m_axis_tvalid <= 1'b0;
                    m_axis_tlast  <= 1'b0;
                    m_axis_tuser  <= 1'b0;
                    emitting      <= 1'b0;
                end
            end
        end
    end
endmodule
