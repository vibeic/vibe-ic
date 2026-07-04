module sipo_top#(parameter DATA_WIDTH = 16,
                 parameter SHIFT_DIRECTION = 1,
                 parameter CODE_WIDTH = DATA_WIDTH + $clog2(DATA_WIDTH + 1),
                 parameter CRC_WIDTH = DATA_WIDTH/2,
                 parameter POLY = 8'b10101010
                 ) (
   input clk,
   input reset_n,
   input serial_in,
   input shift_en,
   input [CODE_WIDTH-1:0] received,
   input [CRC_WIDTH-1:0] received_crc,
   output done,
   output [DATA_WIDTH-1:0] data_out,
   output [CODE_WIDTH-1:0] encoded,
   output error_detected,
   output error_corrected,
   output [CRC_WIDTH-1:0] crc_out,
   output crc_error
   );

wire [DATA_WIDTH-1:0] parallel_out;

serial_in_parallel_out_8bit  #(.WIDTH(DATA_WIDTH), .SHIFT_DIRECTION(SHIFT_DIRECTION)) uut_sipo (
        .clk           (clk),
        .reset_n       (reset_n),
        .sin           (serial_in),
        .shift_en      (shift_en),
        .done          (done),
        .parallel_out  (parallel_out)
    );

// The SIPO keeps shifting while shift_en is high; the CRC is taken over the
// parallel word delayed by two clocks so it lines up with the completed word.
reg [DATA_WIDTH-1:0] parallel_out_q1, crc_data;
always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
        parallel_out_q1 <= {DATA_WIDTH{1'b0}};
        crc_data        <= {DATA_WIDTH{1'b0}};
    end else begin
        parallel_out_q1 <= parallel_out;
        crc_data        <= parallel_out_q1;
    end
end

onebit_ecc#(.DATA_WIDTH(DATA_WIDTH),.CODE_WIDTH(CODE_WIDTH)) uut_onebit_ecc1 (
    .data_in(parallel_out),
    .encoded(encoded),
    .received(received),
    .data_out(data_out),
    .error_detected(error_detected),
    .error_corrected(error_corrected)
    );

crc_generator #(.DATA_WIDTH(DATA_WIDTH), .CRC_WIDTH(CRC_WIDTH), .POLY(POLY)) crc_gen (
    .clk     (clk),
    .rst     (reset_n),
    .data_in (crc_data),
    .crc_out (crc_out)
    );

assign crc_error = (crc_out != received_crc);

endmodule

module serial_in_parallel_out_8bit  #(
    parameter WIDTH = 64,
    parameter SHIFT_DIRECTION = 1
)(
    input clk,
    input reset_n,
    input sin,
    input shift_en,
    output reg done,
    output reg [WIDTH-1:0] parallel_out
);
    localparam COUNT_WIDTH = $clog2(WIDTH);
    reg [COUNT_WIDTH:0] shift_count;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            parallel_out     <= {WIDTH{1'b0}};
            done             <= 1'b0;
            shift_count      <= {COUNT_WIDTH{1'b0}};
        end else begin
            if (shift_en) begin
                if (SHIFT_DIRECTION) begin
                    parallel_out    <= {parallel_out[WIDTH-2:0], sin};
                end else begin
                    parallel_out    <= {sin, parallel_out[WIDTH-1:1]};
                end
                shift_count   <= shift_count + 1;
            end
            if (shift_count == (WIDTH - 1)) begin
                done         <= 1'b1;
                shift_count  <= {COUNT_WIDTH{1'b0}};
            end else begin
                done         <= 1'b0;
            end
        end
    end
endmodule

module onebit_ecc #(
    parameter DATA_WIDTH = 4,
    parameter CODE_WIDTH = DATA_WIDTH + $clog2(DATA_WIDTH + 1)
)(
    input [DATA_WIDTH-1:0] data_in,
    output reg [CODE_WIDTH-1:0] encoded,
    input [CODE_WIDTH-1:0] received,
    output reg [DATA_WIDTH-1:0] data_out,
    output reg error_detected,
    output reg error_corrected
);
    localparam PARITY_BITS = CODE_WIDTH - DATA_WIDTH;
    reg [PARITY_BITS-1:0] syndrome;
    reg [CODE_WIDTH-1:0] corrected_data;
    integer idx_i, idx_j, idx_k;
    integer idx_m, idx_n;
    integer idx_p, idx_q;

    always @(*) begin
        encoded = 0;
        idx_k = 0;
        for (idx_i = 0; idx_i < CODE_WIDTH; idx_i = idx_i + 1) begin
            if ((idx_i + 1) & (idx_i)) begin
                encoded[idx_i] = data_in[idx_k];
                idx_k = idx_k + 1;
            end
        end
        for (idx_i = 0; idx_i < PARITY_BITS; idx_i = idx_i + 1) begin
            encoded[(1 << idx_i) - 1] = 0;
            for (idx_j = 0; idx_j < CODE_WIDTH; idx_j = idx_j + 1) begin
                if (((idx_j + 1) & (1 << idx_i)) && ((idx_j + 1) != (1 << idx_i))) begin
                    encoded[(1 << idx_i) - 1] = encoded[(1 << idx_i) - 1] ^ encoded[idx_j];
                end
            end
        end
    end

    always @(*) begin
        syndrome = 0;
        for (idx_m = 0; idx_m < PARITY_BITS; idx_m = idx_m + 1) begin
            for (idx_n = 0; idx_n < CODE_WIDTH; idx_n = idx_n + 1) begin
                if ((idx_n + 1) & (1 << idx_m)) begin
                    syndrome[idx_m] = syndrome[idx_m] ^ received[idx_n];
                end
            end
        end
    end

    always @(*) begin
        error_detected = |syndrome;
    end

    always @(*) begin
        corrected_data = received;
        if (error_detected) begin
            corrected_data[syndrome - 1] = ~corrected_data[syndrome - 1];
        end
    end

    always @(*) begin
        idx_q = 0;
        for (idx_p = 0; idx_p < CODE_WIDTH; idx_p = idx_p + 1) begin
            if ((idx_p + 1) & (idx_p)) begin
                data_out[idx_q] = corrected_data[idx_p];
                idx_q = idx_q + 1;
            end
        end
    end

    always @(*) begin
        error_corrected = error_detected;
    end
endmodule

module crc_generator #(
    parameter DATA_WIDTH = 16,
    parameter CRC_WIDTH  = 8,
    parameter POLY       = 8'b10101010
)(
    input                       clk,
    input                       rst,
    input  [DATA_WIDTH-1:0]     data_in,
    output reg [CRC_WIDTH-1:0]  crc_out
);
    integer i;
    reg [CRC_WIDTH-1:0] crc;
    always @(*) begin
        crc = {CRC_WIDTH{1'b0}};
        for (i = DATA_WIDTH-1; i >= 0; i = i - 1) begin
            if (crc[CRC_WIDTH-1] ^ data_in[i])
                crc = (crc << 1) ^ POLY[CRC_WIDTH-1:0];
            else
                crc = (crc << 1);
        end
        crc_out = crc;
    end
endmodule
