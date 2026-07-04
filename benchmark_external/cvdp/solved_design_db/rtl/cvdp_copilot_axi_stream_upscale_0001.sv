module axis_upscale (
    input  wire        clk,
    input  wire        resetn,        // active-low synchronous reset

    input  wire        dfmt_enable,
    input  wire        dfmt_type,
    input  wire        dfmt_se,

    input  wire        s_axis_valid,
    input  wire [23:0] s_axis_data,
    input  wire        m_axis_ready,

    output wire        s_axis_ready,
    output reg         m_axis_valid,
    output reg  [31:0] m_axis_data
);

    // -----------------------------------------------------------------
    // Data-format upscale (24-bit -> 32-bit), combinational
    // -----------------------------------------------------------------
    wire        slave_msb  = s_axis_data[23];
    // dfmt_type : 1 -> carry the inverted slave MSB, 0 -> carry the slave MSB
    wire        carry_bit  = dfmt_type ? ~slave_msb : slave_msb;
    // dfmt_se   : 1 -> sign-extend with the carried bit, 0 -> extend with 0
    wire [7:0]  extend_bits = dfmt_se ? {8{carry_bit}} : 8'b0;

    wire [31:0] upscaled    = dfmt_enable ? {extend_bits, carry_bit, s_axis_data[22:0]}
                                          : {8'b0, s_axis_data};

    // -----------------------------------------------------------------
    // Single pipeline register stage with ready/valid handshake.
    // The slave-side ready is a direct pass-through of the master-side
    // ready: the slave can accept a transfer in exactly the cycles the
    // downstream master can accept the pipelined result.
    // -----------------------------------------------------------------
    assign s_axis_ready = m_axis_ready;

    always @(posedge clk) begin
        if (!resetn) begin
            m_axis_valid <= 1'b0;
            m_axis_data  <= 32'b0;
        end else begin
            m_axis_valid <= s_axis_valid;
            m_axis_data  <= upscaled;
        end
    end

endmodule
