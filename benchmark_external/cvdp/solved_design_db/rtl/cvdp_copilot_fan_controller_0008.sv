module fan_controller (
    input wire clk, input wire reset, output reg fan_pwm_out,
    input  wire psel, input wire penable, input wire pwrite,
    input  wire [7:0] paddr, input wire [7:0] pwdata,
    output reg  [7:0] prdata, output reg pready, output reg pslverr
);
    reg [7:0] TEMP_LOW, TEMP_MED, TEMP_HIGH, temp_adc_in;
    reg setup;
    wire setup_ph  = psel & ~penable & ~setup;
    wire access_ph = psel &  penable &  setup;
    wire sa=(paddr==8'h0a), sb=(paddr==8'h0b), sc=(paddr==8'h0c), sf=(paddr==8'h0f);
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            prdata<=0; pready<=0; pslverr<=0;
            TEMP_LOW<=8'd30; TEMP_MED<=8'd60; TEMP_HIGH<=8'd90; setup<=0;
        end else begin
            pready <= access_ph; setup <= setup_ph;
            if (access_ph) begin
                pslverr <= ~(sa|sb|sc|sf);
                if (pwrite) begin
                    if (sa) TEMP_LOW<=pwdata; if (sb) TEMP_MED<=pwdata;
                    if (sc) TEMP_HIGH<=pwdata; if (sf) temp_adc_in<=pwdata;
                end else
                    prdata <= sa?TEMP_LOW : sb?TEMP_MED : sc?TEMP_HIGH : sf?temp_adc_in : prdata;
            end
        end
    end
    reg [7:0] pwm_duty_cycle, pwm_counter;
    always @(posedge clk or posedge reset)
        if (reset) pwm_duty_cycle<=0;
        else pwm_duty_cycle <= (temp_adc_in<TEMP_LOW)?8'd64:(temp_adc_in<TEMP_MED)?8'd128:(temp_adc_in<TEMP_HIGH)?8'd11:8'd255;
    always @(posedge clk or posedge reset)
        if (reset) begin pwm_counter<=0; fan_pwm_out<=0; end
        else begin pwm_counter<=pwm_counter+1; fan_pwm_out<=(pwm_counter<pwm_duty_cycle); end
endmodule
