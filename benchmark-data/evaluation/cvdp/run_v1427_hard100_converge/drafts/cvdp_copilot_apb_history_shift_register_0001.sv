// APBGlobalHistoryRegister
// APB-accessible 8-bit global history shift register for branch prediction.
//   - predict_history updates on the rising edge of history_shift_valid
//     (modeled as a real clock; misprediction restore has strict priority).
//   - Glitch-free clock gating of pclk: clk_gate_en is latched on the negedge
//     of pclk before being ANDed with pclk (spec: clk_gate_en toggles only on
//     the negedge of pclk).
//   - Zero-wait-state APB slave: pready held high; reserved bits read 0;
//     predict_history is read-only; pslverr asserts on invalid addresses.
module APBGlobalHistoryRegister (
    // Clock & reset
    input  wire        pclk,                 // APB clock
    input  wire        presetn,              // async active-low reset

    // APB interface
    input  wire [9:0]  paddr,                // address bus
    input  wire        pselx,                // slave select
    input  wire        penable,              // enable / access phase
    input  wire        pwrite,               // 1 = write, 0 = read
    input  wire [7:0]  pwdata,               // write data
    output reg         pready,               // ready (zero-wait: held high)
    output reg  [7:0]  prdata,               // read data
    output reg         pslverr,              // slave error (invalid address)

    // History-shift interface (acts as a clock)
    input  wire        history_shift_valid,  // rising edge -> predict_history update

    // Clock-gating enable (toggles only on negedge of pclk)
    input  wire        clk_gate_en,          // assert to gate pclk internally

    // Status & interrupt signals
    output wire        history_full,         // predict_history == 8'hFF
    output wire        history_empty,        // predict_history == 8'h00
    output wire        error_flag,           // invalid-address error
    output wire        interrupt_full,       // driven by history_full
    output wire        interrupt_error       // driven by error_flag
);

    // ------------------------------------------------------------------
    // Register map
    // ------------------------------------------------------------------
    localparam [9:0] ADDR_CONTROL = 10'h000;  // control_register (R/W)
    localparam [9:0] ADDR_TRAIN   = 10'h001;  // train_history    (R/W)
    localparam [9:0] ADDR_PREDICT = 10'h002;  // predict_history  (RO)

    reg [7:0] control_register;  // [0]predict_valid [1]predict_taken
                                 // [2]train_mispredicted [3]train_taken
                                 // [7:4] reserved (read 0)
    reg [7:0] train_history;     // [6:0] history, [7] reserved (read 0)
    reg [7:0] predict_history;   // global history shift register

    // Control-field aliases
    wire predict_valid      = control_register[0];
    wire predict_taken      = control_register[1];
    wire train_mispredicted = control_register[2];
    wire train_taken        = control_register[3];

    // ------------------------------------------------------------------
    // Glitch-free clock gating.
    // clk_gate_en is guaranteed to toggle only on the negedge of pclk, so a
    // level-sensitive latch that captures the enable while pclk is low, ANDed
    // with pclk, yields a glitch-free gated clock (gclk).
    // ------------------------------------------------------------------
    reg clk_en_latch;
    always @(*) begin
        if (!presetn)
            clk_en_latch = 1'b1;          // clock enabled out of reset
        else if (!pclk)
            clk_en_latch = ~clk_gate_en;  // capture enable while pclk is low
    end
    wire gclk = pclk & clk_en_latch;

    // ------------------------------------------------------------------
    // Address decode + read mux (reserved bits read as zero)
    // ------------------------------------------------------------------
    wire addr_valid = (paddr == ADDR_CONTROL) ||
                      (paddr == ADDR_TRAIN)   ||
                      (paddr == ADDR_PREDICT);

    reg [7:0] rdata_mux;
    always @(*) begin
        case (paddr)
            ADDR_CONTROL: rdata_mux = {4'b0000, control_register[3:0]};
            ADDR_TRAIN:   rdata_mux = {1'b0,    train_history[6:0]};
            ADDR_PREDICT: rdata_mux = predict_history;
            default:      rdata_mux = 8'h00;
        endcase
    end

    // ------------------------------------------------------------------
    // APB response: zero wait states (pready always high after reset).
    //   - read data is presented whenever the slave is selected for a read,
    //     so it is valid throughout the ACCESS phase.
    //   - pslverr asserts on invalid addresses while the slave is selected.
    // ------------------------------------------------------------------
    always @(posedge gclk or negedge presetn) begin
        if (!presetn) begin
            pready  <= 1'b0;
            prdata  <= 8'h00;
            pslverr <= 1'b0;
        end else begin
            pready <= 1'b1;
            if (pselx) begin
                pslverr <= ~addr_valid;
                if (!pwrite)
                    prdata <= rdata_mux;
            end else begin
                pslverr <= 1'b0;
            end
        end
    end

    // ------------------------------------------------------------------
    // CSR writes: commit once in the ACCESS phase (pselx && penable && pwrite).
    // Reserved bits are stored as zero; predict_history is read-only via APB;
    // writes to undecoded addresses update nothing.
    // ------------------------------------------------------------------
    always @(posedge gclk or negedge presetn) begin
        if (!presetn) begin
            control_register <= 8'h00;
            train_history    <= 8'h00;
        end else if (pselx && penable && pwrite) begin
            case (paddr)
                ADDR_CONTROL: control_register <= {4'b0000, pwdata[3:0]};
                ADDR_TRAIN:   train_history    <= {1'b0,    pwdata[6:0]};
                default: ;  // read-only / invalid: ignore
            endcase
        end
    end

    // ------------------------------------------------------------------
    // Global history shift register.
    // history_shift_valid is used as a real clock (updates only on its rising
    // edge). Priority: misprediction restore > normal LSB shift-in.
    //   - normal : shift in predict_taken at the LSB (youngest -> bit[0]).
    //   - mispred: load {train_history[6:0], train_taken} (actual outcome at LSB).
    // ------------------------------------------------------------------
    always @(posedge history_shift_valid or negedge presetn) begin
        if (!presetn)
            predict_history <= 8'h00;
        else if (train_mispredicted)
            predict_history <= {train_history[6:0], train_taken};
        else if (predict_valid)
            predict_history <= {predict_history[6:0], predict_taken};
    end

    // ------------------------------------------------------------------
    // Status & interrupt outputs
    // ------------------------------------------------------------------
    assign history_full    = (predict_history == 8'hFF);
    assign history_empty   = (predict_history == 8'h00);
    assign error_flag      = pslverr;
    assign interrupt_full  = history_full;
    assign interrupt_error = error_flag;

endmodule
