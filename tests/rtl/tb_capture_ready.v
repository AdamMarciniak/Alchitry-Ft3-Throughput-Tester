`timescale 1ns/1ps
// Production controller + pulser, with a 40 MSPS ADC FIFO model and deliberate
// downstream stalls longer than one nominal shot. No vendor simulation models.
module tb_capture_ready;
    reg clk=0, rst=1, ctrl_empty=1, tx_full=0;
    reg [31:0] ctrl_word=0;
    wire [31:0] tx_data;
    wire tx_valid, adc_read, ready, arm, sync, fault, mux_clk, ina, inb, oe;
    wire [1:0] method, kind;
    wire [3:0] fault_code, pulse_state;
    wire [15:0] pulse_frames;
    wire [5:0] elem;
    wire [23:0] rx_time;
    wire [11:0] tgc_code;
    wire tgc_en;
    reg adc_tog=0;
    integer cyc=0, div=0, grid=0, head=0, tail=0, count=0, sequence=0;
    reg [31:0] memory [0:4095];
    wire adc_empty=(count==0);
    wire [31:0] adc_word=memory[head];
    integer test_method=0, half_count=0;
    reg prev_drive=0;
    reg [7:0] signs=0;
    integer on_at=0;
    integer shots=0, packets=0, words=0, last_data=0, previous_shot=-1;
    integer first_period=0, stalled_period=0, stall_started=0;
    integer gate_at=-1, sync_at=-1, rx_end_at=-1;
    reg previous_rx=0;
    reg pop_now, saw_tgc_hold=0;
    always #5 clk=~clk;

    ctrl_decode ctrl(.clk(clk),.rst(rst),.ctrl_word(ctrl_word),.ctrl_empty(ctrl_empty),
        .tx_full(tx_full),.tx_wr_rst_busy(1'b0),.tx_din(tx_data),.tx_wr_en(tx_valid),
        .adc_word(adc_word),.adc_empty(adc_empty),.adc_rd_en(adc_read),
        .tgc_code(tgc_code),.tgc_en(tgc_en),
        .tx_sync(sync),.tx_kind(kind),.pls_method(method),.tx_elem(elem),.capture_ready(ready),
        .pls_fault(fault),.pls_fault_code(fault_code),.pls_frames(pulse_frames),.pls_state(pulse_state),
        .pls_arm(arm),.pls_t_rx(rx_time));
    tx_sequencer #(.T_OE_WAIT(100),.CHAIN_CHECK(0)) pulser(
        .clk(clk),.rst(rst),.adc_sync_tog(adc_tog),.capture_ready(ready),
        .arm(arm),.start_frame(1'b0),.continuous(1'b1),.fault_clr(1'b0),
        .cfg_n_cycles(8'd2),.cfg_t_drive(16'd10),.cfg_t_dead(16'd4),
        .cfg_method(method),.shot_kind(kind),.cfg_chirp_len(8'd0),.ch_wr(1'b0),.ch_wr_addr(8'd0),.ch_wr_data(16'd0),
        .cfg_t_settle(24'd500),.cfg_t_inhibit(24'd450),.cfg_t_ring(24'd300),
        .cfg_t_rx(rx_time),.el_wr(1'b0),.el_wr_addr(6'd0),.el_wr_data(6'd0),
        .cfg_list_len(7'd48),.tr_wr(1'b0),.tr_wr_addr(6'd0),.tr_wr_data(12'd0),
        .mux_dout(1'b0),.mux_clk(mux_clk),.pulse_ina(ina),.pulse_inb(inb),.pulse_oe(oe),
        .tx_sync(sync),.element_current(elem),.fault(fault),.fault_code(fault_code),
        .frame_count(pulse_frames),.dbg_state(pulse_state));

    // Independent reference schedule across the complete 48-TX aperture.
    function integer expected_tx(input integer index);
        integer k;
        begin
            k = index % 142;
            expected_tx = test_method == 3 ? (k+1)/3 :
                          (test_method == 1 ? index/2 : index)%48;
        end
    endfunction
    function integer expected_kind(input integer index);
        integer k;
        begin
            k = index % 142;
            expected_kind = test_method == 3 ? (k==0 ? 0 : (k+1)%3) :
                            test_method == 1 ? 1+index%2 : test_method == 2 ? 3 : 0;
        end
    endfunction
    integer last_shot;
    // Consume the old FWFT head on the same edge as the production controller.
    // Produce one packed word every 5 clocks, monotonically tagged for checking.
    always @(posedge clk) begin
        cyc=cyc+1;
        pop_now=adc_read && !adc_empty;
        if (!rst) begin
            if (sync) begin
                if (ctrl.sstate!==3'd1 || !ready) $fatal(1,"Shot while capture unavailable");
                if (elem !== expected_tx(shots)) $fatal(1,"Skipped/reordered physical element");
                if (previous_shot>=0) begin
                    if (shots==1) first_period=cyc-previous_shot;
                    if (shots==2) stalled_period=cyc-previous_shot;
                end
                if (rx_end_at>=0 && cyc-rx_end_at<5000) $fatal(1,"DAC gap shortened");
                if (kind !== expected_kind(shots))
                    $fatal(1,"Unexpected pulse member tag");
                half_count=0; signs=0;
                previous_shot=cyc;sync_at=cyc;shots=shots+1;
            end
            if (oe && (ina == inb) && !prev_drive) begin
                signs[half_count]=!ina;half_count=half_count+1;on_at=cyc;
            end
            if (prev_drive && ina!=inb && arm && cyc-on_at!=10)
                $fatal(1,"Wrong drive width");
            prev_drive=oe && (ina == inb);
            if (ctrl.sstate==3'd4 && !previous_rx) begin
                if (test_method==1 && (half_count!=8 || signs!==(shots%2 ? 8'h6a : 8'h9a)))
                    $fatal(1,"Incorrect complementary sequence");
                if (test_method==2 && (pulser.switching_rx || pulser.shift_data == 0 ||
                    pulser.shift_data !== rx_word(elem ^ 6'd1))) $fatal(1,"Incorrect receive switch");

                if (test_method==3 && (pulser.switching_rx ||
                    pulser.shift_data !== rx_word(elem + (expected_kind(shots-1)==1 ? -1 :
                                                          expected_kind(shots-1)==2 ? 1 : 0))))
                    $fatal(1,"Wrong center/left/right receive switch");
                gate_at=cyc;
                if (gate_at-sync_at != (test_method>=2 ? 2202 : 1602)) $fatal(1,"Receive origin changed with backpressure: %0d",gate_at-sync_at);
            end
            previous_rx=(ctrl.sstate==3'd4);
            if (tgc_en && tgc_code > 12'd1000) $fatal(1,"TGC exceeded programmed ceiling");
            if (ctrl.sstate==3'd4 && tgc_code==12'd1000) saw_tgc_hold=1;
            // Explicit disarm aborts acquisition and clears/self-tests the MUX.
            if (arm && ((ctrl.sstate==3'd2 && test_method<2) || ctrl.sstate==3'd4) && mux_clk)
                $fatal(1,"MUX clocks during capture");
            if (fault) $fatal(1,"Unexpected pulser fault");
            if (ina && !inb) $fatal(1,"Shoot-through combination");
            if (tx_valid) begin
                if (tx_data[31:24]==(test_method==3 ? 8'hE2 : 8'hE1)) begin
                    if (words!=0) $fatal(1,"Torn frame");
                    if (tx_data[23:22] !== expected_kind(packets))
                        $fatal(1,"Incorrect packet method");
                    if (tx_data[21:16] !== expected_tx(packets)) $fatal(1,"Wrong packet element");
                    if (tx_data[15:0] !== packets) $fatal(1,"Wrong packet counter");
                    words=3208;
                    last_data=-1;
                end else begin
                    if (words==0) $fatal(1,"Data without header");
                    if (last_data>=0 && tx_data!=last_data+1) $fatal(1,"Noncontiguous RF payload");
                    last_data=tx_data;
                    words=words-1;
                    if (words==0) begin packets=packets+1;rx_end_at=cyc;end
                end
            end
        end
        // Delay model updates until all DUT blocks have sampled the old FIFO.
        #1;
        if (rst) begin head=0;tail=0;count=0;sequence=0;div=0;grid=0;end
        else begin
            if (pop_now) begin head=(head+1)%4096;count=count-1;end
            if (div==4) begin
                div=0;
                if (count<4096) begin memory[tail]=sequence;tail=(tail+1)%4096;count=count+1;end
                sequence=sequence+1;
            end else div=div+1;
            if (grid==19) begin adc_tog=~adc_tog;grid=0;end else grid=grid+1;
        end
    end
    function [63:0] rx_word(input [5:0] position);
        reg [5:0] hw;
        begin
            hw=pulser.mux_code(position);
            rx_word=(64'h1 << (16+16*hw[5:4]+hw[3:0])) |
                    (64'h1 << (hw[5:4]==0 ? 5 : hw[5:4]==1 ? 7 : 11));
        end
    endfunction
    task command(input [31:0] value);
        begin @(negedge clk);ctrl_word=value;ctrl_empty=0;
              @(negedge clk);ctrl_empty=1;end
    endtask
    initial begin
        if ($test$plusargs("METHOD1")) test_method=1; else if ($test$plusargs("METHOD2")) test_method=2;
        if ($test$plusargs("METHOD3")) test_method=3;
        last_shot=test_method==3 ? 145 : 50;
        repeat(4) @(negedge clk);rst=0;
        command(32'h20000000 | test_method);
        command(32'h0b000c88); // 3208 packed words, ~12 cm plus receive offset
        command(test_method>=2 ? 32'h0c000898 : 32'h0c000640); // 16 us
        command(32'h0e001388); // 50 us DAC recovery gap
        command(32'h0f000064); // TGC starts at 100
        command(32'h210003e8); // TGC ceiling/hold at 1000
        command(32'h0d004000); // reach the ceiling early enough to verify hold
        command(32'h17005c58); // 236.40 us conservative host RX budget
        command(32'h07000002);command(32'h01000000);command(32'h10000001);
        wait(shots==2);@(negedge clk);tx_full=1;stall_started=cyc;
        repeat(50000) @(negedge clk); // 500 us: exceeds nominal period and FIFO slack
        if (shots!=2) $fatal(1,"Pulser advanced during stalled receive");
        tx_full=0;
        wait(packets==49);
        if (stalled_period<=first_period+20000) $fatal(1,"Stall did not stretch shot interval");
        wait(shots==last_shot);@(negedge clk);tx_full=1;
        repeat(30000) @(negedge clk);
        if (shots!=last_shot) $fatal(1,"New shot during second stall");
        command(32'h10000000);
        repeat(5) @(negedge clk);
        if (oe || ina || !inb) $fatal(1,"Disarm did not park outputs");
        tx_full=0;repeat(1000) @(negedge clk);
        if (shots!=last_shot) $fatal(1,"Stall release rearmed pulser");
        if (!saw_tgc_hold) $fatal(1,"TGC never reached its programmed hold code");
        $display("CAPTURE_READY_TEST_PASS shots=%0d packets=%0d normal_cycles=%0d stalled_cycles=%0d",shots,packets,first_period,stalled_period);
        $finish;
    end
    initial begin #50000000;$fatal(1,"Test timed out");end
endmodule
