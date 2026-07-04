module ping_pong_buffer (
    input  logic clk,
    input  logic rst_n,
    input  logic write_enable,
    input  logic read_enable,
    input  logic [7:0] data_in,
    output logic [7:0] data_out,
    output logic buffer_full,
    output logic buffer_empty,
    output reg   buffer_select
);

    localparam DEPTH      = 256;
    localparam ADDR_WIDTH = 8;

    logic [ADDR_WIDTH-1:0] write_ptr, read_ptr;

    // Per-bank "completely written, ready to be read" status.
    reg   [1:0] bank_full;

    logic [7:0] data_out0, data_out1;

    // Write into the active bank while it still has room; read from the
    // active bank only once it holds a complete frame.
    wire do_write = write_enable & ~bank_full[buffer_select];
    wire do_read  = read_enable  &  bank_full[buffer_select];

    dual_port_memory memory0 (
        .clk        (clk),
        .we         (do_write & (buffer_select == 1'b0)),
        .write_addr (write_ptr),
        .din        (data_in),
        .read_addr  (read_ptr),
        .dout       (data_out0)
    );

    dual_port_memory memory1 (
        .clk        (clk),
        .we         (do_write & (buffer_select == 1'b1)),
        .write_addr (write_ptr),
        .din        (data_in),
        .read_addr  (read_ptr),
        .dout       (data_out1)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            write_ptr     <= {ADDR_WIDTH{1'b0}};
            read_ptr      <= {ADDR_WIDTH{1'b0}};
            buffer_select <= 1'b0;
            bank_full     <= 2'b00;
            data_out      <= 8'b0;
        end else begin
            // Write : fill the active bank; when it tops out, mark it ready
            // and toggle buffer_select to the other (free) bank.
            if (do_write) begin
                if (write_ptr == DEPTH-1) begin
                    write_ptr                <= {ADDR_WIDTH{1'b0}};
                    bank_full[buffer_select] <= 1'b1;
                    buffer_select            <= ~buffer_select;
                end else begin
                    write_ptr <= write_ptr + 1'b1;
                end
            end

            // Read : drain the active bank; when it empties, clear its ready
            // flag so the buffer reports empty again.
            if (do_read) begin
                data_out <= buffer_select ? data_out1 : data_out0;
                if (read_ptr == DEPTH-1) begin
                    read_ptr                 <= {ADDR_WIDTH{1'b0}};
                    bank_full[buffer_select] <= 1'b0;
                end else begin
                    read_ptr <= read_ptr + 1'b1;
                end
            end
        end
    end

    // Empty for reading until the active bank is full; "full" once either
    // physical bank holds a complete frame.
    assign buffer_empty = ~bank_full[buffer_select];
    assign buffer_full  =  |bank_full;

endmodule


module dual_port_memory (
    input logic clk,
    input logic we,
    input logic [7:0] write_addr,
    input logic [7:0] din,
    input logic [7:0] read_addr,
    output logic [7:0] dout
);

    logic [7:0] mem [255:0];

    always_ff @(posedge clk) begin
        if (we) begin
            mem[write_addr] <= din;
        end
    end

    assign dout = mem[read_addr];
endmodule