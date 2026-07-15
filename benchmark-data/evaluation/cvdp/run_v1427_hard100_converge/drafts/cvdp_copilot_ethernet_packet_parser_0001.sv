// ethernet_packet_parser
// Extracts the 2 most-significant bytes (data[31:16]) of the 2nd beat of a
// burst on a simple vld/sof/eof bus and presents them on `field` with
// `field_vld` asserted until `eof` ends the burst.
//
// State machine (2-bit):
//   IDLE       (0): wait for vld && sof; clear beat_cnt / field / field_vld
//   EXTRACTING (1): count beats; at the 2nd beat (beat_cnt == 1) capture
//                   data[31:16] into temp_extracted_field
//   DONE       (2): transfer temp_extracted_field to field, assert field_vld
//   FAIL_FINAL (3): on eof, clear field_vld and return to IDLE

module ethernet_packet_parser (
    input  wire        clk,
    input  wire        rst,
    input  wire        vld,
    input  wire        sof,
    input  wire [31:0] data,
    input  wire        eof,
    output wire        ack,
    output reg  [15:0] field,
    output reg         field_vld
);

    // FSM state encoding (per spec)
    localparam [1:0] IDLE       = 2'd0;
    localparam [1:0] EXTRACTING = 2'd1;
    localparam [1:0] DONE       = 2'd2;
    localparam [1:0] FAIL_FINAL = 2'd3;

    reg [1:0]  state;
    reg [3:0]  beat_cnt;             // counts valid beats within the burst
    reg [15:0] temp_extracted_field; // temporary storage for the extracted bytes
    reg        eof_pend;             // remembers an eof seen before FAIL_FINAL

    // Receiver never back-pressures the transmitter
    assign ack = 1'b1;

    // Power-up determinism (pre-reset sampling safety)
    initial begin
        state                = IDLE;
        beat_cnt             = 4'd0;
        temp_extracted_field = 16'd0;
        eof_pend             = 1'b0;
        field                = 16'd0;
        field_vld            = 1'b0;
    end

    always @(posedge clk) begin
        if (rst) begin
            state                <= IDLE;
            beat_cnt             <= 4'd0;
            temp_extracted_field <= 16'd0;
            eof_pend             <= 1'b0;
            field                <= 16'd0;
            field_vld            <= 1'b0;
        end else begin
            // Beat counter: increments with each valid beat of the burst.
            // The SOF beat is the 1st beat (beat_cnt becomes 1 after it), so
            // during the 2nd beat beat_cnt reads 1.
            if (state == IDLE) begin
                if (vld && sof)
                    beat_cnt <= 4'd1;
                else
                    beat_cnt <= 4'd0;
            end else if (vld) begin
                beat_cnt <= beat_cnt + 4'd1;
            end

            case (state)
                IDLE: begin
                    field     <= 16'd0;
                    field_vld <= 1'b0;
                    eof_pend  <= 1'b0;
                    if (vld && sof)
                        state <= EXTRACTING;
                end

                EXTRACTING: begin
                    if (vld) begin
                        if (beat_cnt == 4'd1) begin
                            // 2nd beat: capture the 2 most-significant bytes
                            temp_extracted_field <= data[31:16];
                            state                <= DONE;
                            if (eof)
                                eof_pend <= 1'b1;
                        end else if (eof) begin
                            // burst ended before the 2nd beat: back to idle
                            state <= IDLE;
                        end
                    end
                end

                DONE: begin
                    // present the extracted bytes and flag them valid
                    field     <= temp_extracted_field;
                    field_vld <= 1'b1;
                    state     <= FAIL_FINAL;
                    if (eof)
                        eof_pend <= 1'b1;
                end

                FAIL_FINAL: begin
                    // wait for end of burst, then clear the valid flag
                    if (eof || eof_pend) begin
                        field_vld <= 1'b0;
                        eof_pend  <= 1'b0;
                        state     <= IDLE;
                    end
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
