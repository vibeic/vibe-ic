module TopModule (
    input      cpu_overheated,
    output reg shut_off_computer,
    input      arrived,
    input      gas_tank_empty,
    output reg keep_driving
);

    // Bug fix: the original always-blocks had no else branch, so
    // shut_off_computer / keep_driving were only conditionally assigned
    // (inferring unwanted latches / leaving stale values). Give each
    // combinational block a full, else-covered assignment.
    always @(*) begin
        if (cpu_overheated)
            shut_off_computer = 1'b1;
        else
            shut_off_computer = 1'b0;
    end

    always @(*) begin
        if (~arrived)
            keep_driving = ~gas_tank_empty;
        else
            keep_driving = 1'b0;
    end

endmodule
