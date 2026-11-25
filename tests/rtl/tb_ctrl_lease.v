`timescale 1ns/1ps
module tb_ctrl_lease;
    reg clk=0, rst=1, empty=1;
    reg [31:0] word=0;
    wire arm;
    wire [31:0] data;
    wire valid;
    integer i;
    always #5 clk=~clk;
    ctrl_decode #(.LEASE_CYCLES_PER_MS(4)) dut (
        .clk(clk), .rst(rst), .ctrl_word(word), .ctrl_empty(empty),
        .tx_full(1'b0), .tx_wr_rst_busy(1'b0), .adc_word(32'd0),
        .adc_empty(1'b1), .tx_sync(1'b0), .tx_elem(6'd0), .pls_arm(arm),
        .pls_fault(1'b0), .pls_fault_code(4'd0), .pls_frames(16'd0), .pls_state(4'd0),
        .tx_din(data), .tx_wr_en(valid)
    );
    task command(input [31:0] value);
        begin
            @(negedge clk); word=value; empty=0;
            @(negedge clk); empty=1;
        end
    endtask
    task cycles(input integer count);
        begin repeat(count) @(negedge clk); end
    endtask
    initial begin
        cycles(3); rst=0; cycles(2);
        if (arm !== 0) $fatal(1,"Boot must be disarmed");
        command(32'h10000001); cycles(20);
        if (arm !== 1) $fatal(1,"Legacy manual arm must work without a lease");
        command(32'h10000000);
        command(32'h1e000008); command(32'h10000001); cycles(12);
        if (arm !== 1) $fatal(1,"Lease ended early");
        command(32'h1e000008); cycles(20);
        if (arm !== 1) $fatal(1,"Renewal did not extend the lease");
        command(32'h1e000000); // cannot disable watchdog while armed
        cycles(34);
        if (arm !== 0) $fatal(1,"Missing heartbeat did not disarm");
        command(32'h10000001);
        if (arm !== 0) $fatal(1,"Expired lease allowed rearm");
        command(32'h1e000008);
        if (arm !== 0) $fatal(1,"Renewal must never arm automatically");
        command(32'h10000001);
        if (arm !== 1) $fatal(1,"Fresh lease plus explicit ARM failed");
        command(32'h10000000); command(32'h1e000000);
        command(32'h10000001); cycles(50);
        if (arm !== 1) $fatal(1,"Disarmed lease disable failed");
        rst=1; cycles(2); rst=0; cycles(2);
        if (arm !== 0 || dut.lease_enabled !== 0) $fatal(1,"Reset did not park pulser");
        command(32'h1f123456); command(32'h07000003);
        command(32'h03000000); command(32'h01000000);
        for (i=0; i<16; i=i+1) begin
            if (!valid) $fatal(1,"Info query did not stream");
            case (i)
                0: if (data !== 32'hB34D0001) $fatal(1,"Bad info signature");
                1: if (data !== 32'h00123456) $fatal(1,"Bad echoed query nonce");
                2: if (data !== 32'h00000000) $fatal(1,"Unexpected default build tag");
                3: if (data !== 32'h0001004c) $fatal(1,"Bad lease/disarm/capture-ready capability flags");
                5: if (data !== 32'd2047) $fatal(1,"Bad receive-length readback");
            endcase
            @(negedge clk);
        end
        command(32'h10000001);
        if (valid !== 0) $fatal(1,"Info mode must not stream while armed");
        command(32'h10000000); command(32'h02000000);
        $display("LEASE_TEST_PASS");
        $finish;
    end
    initial begin #100000; $fatal(1,"Test timed out"); end
endmodule
