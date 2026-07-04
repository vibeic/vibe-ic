module line_buffer #(
    parameter NBW_DATA  = 'd8,  // Bit width of grayscale input/output data
    parameter NS_ROW    = 'd10, // Number of rows
    parameter NS_COLUMN = 'd8,  // Number of columns
    parameter NBW_ROW   = 'd4,  // log2(NS_ROW). Bit width of i_image_row_start
    parameter NBW_COL   = 'd3,  // log2(NS_COLUMN). Bit width of i_image_col_start
    parameter NBW_MODE  = 'd3,  // Bit width of mode input
    parameter NS_R_OUT  = 'd4,  // Number of rows of the output window
    parameter NS_C_OUT  = 'd3,  // Number of columns of the output window
    parameter CONSTANT  = 'd255 // Constant value to use in PAD_CONSTANT mode
) (
    input  logic                                  clk,
    input  logic                                  rst_async_n,
    input  logic [NBW_MODE-1:0]                   i_mode,
    input  logic                                  i_valid,
    input  logic                                  i_update_window,
    input  logic [NBW_DATA*NS_COLUMN-1:0]         i_row_image,
    input  logic [NBW_ROW-1:0]                    i_image_row_start,
    input  logic [NBW_COL-1:0]                    i_image_col_start,
    output logic [NBW_DATA*NS_R_OUT*NS_C_OUT-1:0] o_image_window
);

// ----------------------------------------
// - Wires/Registers creation
// ----------------------------------------
logic [NBW_DATA-1:0] image_buffer_ff [NS_ROW][NS_COLUMN];
logic [NBW_DATA-1:0] row_image [NS_COLUMN];
logic [NBW_DATA-1:0] window [NS_R_OUT][NS_C_OUT];
logic [NBW_DATA*NS_R_OUT*NS_C_OUT-1:0] image_window_ff;

// ----------------------------------------
// - Output generation (window extraction)
//   Mirrors the reference model update_inputs(): the output cell
//   (row,col) maps to line buffer position (row_start+row, col_start+col)
//   with per-axis border handling. Row and column out-of-range are
//   handled INDEPENDENTLY (the reference clamps/mirrors/wraps r and c
//   separately), so both-axis overflow is covered for every mode.
// ----------------------------------------
always_comb begin : window_assignment
    int r0, c0;     // raw (unbounded) source row / column
    int ra, ca;     // resolved buffer indices
    for (int row = 0; row < NS_R_OUT; row++) begin
        for (int col = 0; col < NS_C_OUT; col++) begin
            r0 = i_image_row_start + row;
            c0 = i_image_col_start + col;
            ra = r0;
            ca = c0;
            case (i_mode)
                3'd0: begin // NO_BOUND_PROCESS: out of range -> 0
                    if (r0 >= NS_ROW || c0 >= NS_COLUMN)
                        window[row][col] = '0;
                    else
                        window[row][col] = image_buffer_ff[r0][c0];
                end
                3'd1: begin // PAD_CONSTANT: out of range -> CONSTANT
                    if (r0 >= NS_ROW || c0 >= NS_COLUMN)
                        window[row][col] = CONSTANT[NBW_DATA-1:0];
                    else
                        window[row][col] = image_buffer_ff[r0][c0];
                end
                3'd2: begin // EXTEND_NEAR: clamp each axis to nearest edge
                    ra = (r0 >= NS_ROW)    ? (NS_ROW-1)    : r0;
                    ca = (c0 >= NS_COLUMN) ? (NS_COLUMN-1) : c0;
                    window[row][col] = image_buffer_ff[ra][ca];
                end
                3'd3: begin // MIRROR_BOUND: mirror each axis about the edge
                    ra = (r0 >= NS_ROW)    ? (2*NS_ROW-1-r0)    : r0;
                    ca = (c0 >= NS_COLUMN) ? (2*NS_COLUMN-1-c0) : c0;
                    window[row][col] = image_buffer_ff[ra][ca];
                end
                3'd4: begin // WRAP_AROUND: wrap each axis modulo the size
                    ra = (r0 >= NS_ROW)    ? (r0-NS_ROW)    : r0;
                    ca = (c0 >= NS_COLUMN) ? (c0-NS_COLUMN) : c0;
                    window[row][col] = image_buffer_ff[ra][ca];
                end
                default: begin // invalid modes -> 0
                    window[row][col] = '0;
                end
            endcase
        end
    end
end

// ----------------------------------------
// - Input control
// ----------------------------------------
generate
    for (genvar col = 0; col < NS_COLUMN; col++) begin : unpack_row_image
        assign row_image[NS_COLUMN-col-1] = i_row_image[(col+1)*NBW_DATA-1-:NBW_DATA];
    end
endgenerate

always_ff @(posedge clk or negedge rst_async_n) begin : ctrl_regs
    if(~rst_async_n) begin
        image_window_ff <= 0;
        for (int row = 0; row < NS_ROW; row++) begin
            for (int col = 0; col < NS_COLUMN; col++) begin
                image_buffer_ff[row][col] <= 0;
            end
        end
    end else begin
        if(i_valid) begin
            for (int col = 0; col < NS_COLUMN; col++) begin
                image_buffer_ff[0][col] <= row_image[col];
            end

            for (int row = 1; row < NS_ROW; row++) begin
                for (int col = 0; col < NS_COLUMN; col++) begin
                    image_buffer_ff[row][col] <= image_buffer_ff[row-1][col];
                end
            end
        end

        if(i_update_window) begin
            image_window_ff <= o_image_window;
        end
    end
end

// ----------------------------------------
// - Output packing
// ----------------------------------------
generate
    for(genvar row = 0; row < NS_R_OUT; row++) begin : out_row
        for(genvar col = 0; col < NS_C_OUT; col++) begin : out_col
            always_comb begin
                if(i_update_window) begin
                    o_image_window[(row*NS_C_OUT+col+1)*NBW_DATA-1-:NBW_DATA] = window[row][col];
                end else begin
                    o_image_window[(row*NS_C_OUT+col+1)*NBW_DATA-1-:NBW_DATA] = image_window_ff[(row*NS_C_OUT+col+1)*NBW_DATA-1-:NBW_DATA];
                end
            end
        end
    end
endgenerate

endmodule : line_buffer
