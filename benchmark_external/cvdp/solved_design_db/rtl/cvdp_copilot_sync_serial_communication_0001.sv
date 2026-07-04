// Synchronous serial communication link.
//   Top      : sync_serial_communication_tx_rx (instantiates tx_block + rx_block)
//   tx_block : serialises data_in[N-1:0] (N selected by sel) onto serial_out, one
//              bit per clock, LSB-first, and emits serial_clk active only while a
//              serial bit is valid (gated when idle).
//   rx_block : captures serial_out while serial_clk is active and reconstructs the
//              parallel data_out, asserting done HIGH for one clock when complete.
//
//   sel : 1->8 | 2->16 | 3->32 | 4->64 | other->0 bits (idle, no transfer)
//
// Whole design is in a single clock domain (all signals registered on clk) so
// there are no gated-clock sampling races; serial_clk is an active-high transfer
// strobe (gated off when no data is being transmitted).

// ---------------------------------------------------------------------------
module tx_block (
    input  logic        clk,
    input  logic        reset_n,     // active-low asynchronous reset
    input  logic [63:0] data_in,
    input  logic [2:0]  sel,
    output logic        serial_out,
    output logic        done,
    output logic        serial_clk
);
    logic [6:0] n_bits;
    always_comb begin
        case (sel)
            3'd1:    n_bits = 7'd8;
            3'd2:    n_bits = 7'd16;
            3'd3:    n_bits = 7'd32;
            3'd4:    n_bits = 7'd64;
            default: n_bits = 7'd0;
        endcase
    end

    logic [63:0] shiftreg;
    logic [6:0]  count;
    logic        busy;
    logic        started;
    logic        active;     // high while a valid serial bit is on serial_out

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            shiftreg   <= 64'd0;
            count      <= 7'd0;
            busy       <= 1'b0;
            started    <= 1'b0;
            active     <= 1'b0;
            serial_out <= 1'b0;
            done       <= 1'b0;
        end else begin
            done   <= 1'b0;
            active <= 1'b0;
            if (!busy && !started && (n_bits != 7'd0)) begin
                // launch one transaction after reset is released
                shiftreg <= data_in;
                count    <= 7'd0;
                busy     <= 1'b1;
                started  <= 1'b1;
            end else if (busy) begin
                // emit one bit per clock, LSB first
                serial_out <= shiftreg[count[5:0]];
                active     <= 1'b1;
                count      <= count + 7'd1;
                if (count == n_bits - 7'd1) begin
                    busy <= 1'b0;
                    done <= 1'b1;   // tx-side completion (rx.done is the system done)
                end
            end
        end
    end

    // serial_clk is gated: active only while a serial bit is being transmitted.
    assign serial_clk = active;
endmodule

// ---------------------------------------------------------------------------
module rx_block (
    input  logic        clk,
    input  logic        reset_n,     // active-low asynchronous reset
    input  logic        data_in,     // serial input
    input  logic [2:0]  sel,
    input  logic        serial_clk,  // active-high transfer strobe
    output logic [63:0] data_out,
    output logic        done
);
    logic [6:0] n_bits;
    always_comb begin
        case (sel)
            3'd1:    n_bits = 7'd8;
            3'd2:    n_bits = 7'd16;
            3'd3:    n_bits = 7'd32;
            3'd4:    n_bits = 7'd64;
            default: n_bits = 7'd0;
        endcase
    end

    logic [63:0] rx_data;
    logic [6:0]  rx_count;
    logic        last_bit;

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            rx_data  <= 64'd0;
            rx_count <= 7'd0;
            last_bit <= 1'b0;
            data_out <= 64'd0;
            done     <= 1'b0;
        end else begin
            done     <= 1'b0;
            last_bit <= 1'b0;
            if (serial_clk) begin
                rx_data[rx_count[5:0]] <= data_in;   // LSB-first placement
                if (rx_count == n_bits - 7'd1)
                    last_bit <= 1'b1;                 // last bit captured this cycle
                rx_count <= rx_count + 7'd1;
            end
            if (last_bit) begin
                // one cycle later rx_data holds the complete word
                data_out <= rx_data;
                done     <= 1'b1;
            end
        end
    end
endmodule

// ---------------------------------------------------------------------------
module sync_serial_communication_tx_rx (
    input  logic        clk,
    input  logic        reset_n,
    input  logic [63:0] data_in,
    input  logic [2:0]  sel,
    output logic [63:0] data_out,
    output logic        done
);
    logic s_serial_out;
    logic s_serial_clk;
    logic s_tx_done;

    tx_block u_tx (
        .clk        (clk),
        .reset_n    (reset_n),
        .data_in    (data_in),
        .sel        (sel),
        .serial_out (s_serial_out),
        .done       (s_tx_done),
        .serial_clk (s_serial_clk)
    );

    rx_block u_rx (
        .clk        (clk),
        .reset_n    (reset_n),
        .data_in    (s_serial_out),
        .sel        (sel),
        .serial_clk (s_serial_clk),
        .data_out   (data_out),
        .done       (done)
    );
endmodule
