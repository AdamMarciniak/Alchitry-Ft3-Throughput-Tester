# Faster 12 cm capture with receiver feedback

The host now has a **12 cm fast** button. It prepares all 48 elements, a 3208-word
(6416-sample) receive window, a 50 µs post-receive gap and one-sweep averaging.
It keeps the transmit waveform and switch settle/inhibit/dead-time settings.
When shortening depth, it scales the TGC endpoint to preserve the prior linear
gain slope instead of making the ramp steeper. It leaves transmission off.

With the latest recorded 4.48 µs chirp and 16 µs receive offset:

| Configuration | Nominal 48-shot aperture | Nominal maximum sweep rate | RF link load |
|---|---:|---:|---:|
| Recorded 17 cm, 313 µs gap | 28.09 ms | 35.6/s | 31.1 MB/s |
| 12 cm, 313 µs gap | 24.88 ms | 40.2/s | 24.8 MB/s |
| 12 cm, 50 µs gap | 12.26 ms | 81.6/s | 50.3 MB/s |

These are timing-model estimates, not measured hardware rates. Grid alignment,
element trims and USB stalls add time. The depth slider retains its existing
1496 m/s window-sizing convention; displayed range also includes the receive
offset and the selected reconstruction sound speed. The complete heart may
require more than a 12 cm view in some positions.

## Why the FPGA change matters

The old pulser advanced through elements on its own timer. If USB backpressure
kept the receiver draining a window after that timer expired, the next firing
could arrive while capture was busy and be ignored. Earlier 50 µs-gap water
tests showed missing element acquisitions. Making the nominal period shorter
alone would repeat that failure mode.

`ctrl_decode.capture_ready` now feeds `tx_sequencer` in the same 100 MHz clock
domain. The pulser waits for both its configured quiet interval and actual
receiver readiness before shifting the next MUX word. It checks readiness again
before issuing the sample-grid trigger. Receiver readiness requires completed
RF drain, completed DAC gap, an observed empty ADC FIFO between shots, and TX
FIFO availability. The first sample's timing still never depends on USB.

Capture backpressure can therefore lengthen an interval instead of silently
skipping an element. It does not cure insufficient sustained USB throughput or
every possible in-window FIFO overrun. RF sequence/integrity checks remain
necessary. The per-state watchdog still faults a prolonged stalled transaction.
Other source modes retain standalone pulser operation. Disarm/lease expiry
still park the outputs and clear the MUX.

The runtime-info packet advertises the interlock in flags bit 2. The new button
uses a fresh nonce query and refuses fast timing on older firmware. The checked
bench harness continues to verify an exact build ID. The button releases its
temporary query lease while disarmed and does not start scanning. Manual
settings and old files retain their existing behavior.

The live status and exported `stream.sweeps_per_s` now count **complete valid
sweeps**, excluding rejected sweeps and incomplete frames displayed by the
existing fail-open path. `packet_equivalent_sweeps_per_s` retains the old packet
rate/48 metric for comparison. Render/display FPS is a separate quantity.

## Validation and use

The tests run the actual controller and pulser together with a 40 MSPS ADC FIFO
model. A 500 µs downstream stall extends a shot interval without changing the
receive origin, emitting MUX clocks during an active capture, losing payload
continuity or skipping/reordering the 48 elements. They also disarm during a
second stall and verify that releasing backpressure cannot restart firing.
Reset, lease expiry/renewal and runtime-info tests are separate build gates.

The build runner freezes and hashes source/test inputs, runs both RTL suites,
then requires nonnegative setup/hold slack and no Error/Critical Warning DRC
violations before producing a programmable artifact. Older checked builds can
still be used for rollback; builds advertising the new capability additionally
require the capture-ready simulation pass.

After programming the checked build in a **water-bench setup**, restart the TFM
host and select **12 cm fast**, then explicitly start the pulser. Verify actual
valid sweeps/s, zero new holes/skips, complete RF and wire-image quality. Save RF
and settings. Compare with 12 cm / 313 µs gap at the same wire position. If the
link cannot sustain about 50 MB/s, investigate USB negotiation/throughput; do not
treat a higher nominal FPS label as a successful acquisition.

At unchanged burst energy, roughly doubling the firing rate also roughly doubles
the average transmitted energy rate. Neither this digital simulation nor the
earlier slow water test validates the acoustic output, analog recovery, heating
or on-body safety of the faster mode. Hardware validation is still required.

Timing calculations and disarmed comparison settings are in
`bench_runs/fast12/timing.json`; the FPGA build/validation receipt is recorded
alongside the resulting bitstream under `bench_runs/builds`.

Checked build **ae607960** is in
`bench_runs/builds/20260910T045007Z-eee5ed` (September 9 local time).
Both RTL simulations passed; routed setup slack is +0.267 ns, hold slack
+0.059 ns, and the Error/Critical Warning DRC count is zero. The current RTL
hashes match the frozen build inputs. The host suite passed 55 tests. The
bitstream has been built and validated digitally, but has **not been programmed
or tested on the physical setup** in this change.
