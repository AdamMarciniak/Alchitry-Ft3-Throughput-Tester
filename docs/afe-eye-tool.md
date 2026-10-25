# AFE eye-alignment tool

`host/afe_eye_tool.py` measures and aligns the AFE5804 OUT1 and FCLK LVDS
sampling eyes using the diagnostic UART already implemented in the FPGA.
It does not modify the bitstream.

## Before running

1. Stop the pulser.
2. Close the imaging host so it cannot use test-pattern data as ultrasound RF.
3. Connect the Alchitry USB serial interface.

Use Python 3 explicitly. On this machine, `py` starts Python 2 and must not be
used for this tool.

```powershell
python host/afe_eye_tool.py --list-ports
python host/afe_eye_tool.py --port COM5
```

Replace `COM5` with the FPGA USB serial port shown by the first command. The
program asks for confirmation before changing AFE test patterns; add `--yes`
only when the pulser is already stopped.

## What it does

The tool performs the following operations:

1. Establishes a known delay-tap starting point.
2. Enables the sync pattern and scans all 32 FCLK taps.
3. Enables the deskew pattern and scans all 32 DATA taps independently.
4. Rejects stuck or incorrect constant values instead of treating them as a
   valid data eye.
5. Requires a zero-error eye at least six taps wide with two taps of centre
   margin.
6. Applies the two independent eye centres.
7. Runs BITSLIP until the DATA and FCLK word boundaries agree.
8. Validates 8192 assembled samples with the AFE ramp pattern.
9. Turns all AFE test patterns off, including when calibration fails.

Example successful maps look like this:

```text
FCLK: .....##########.................
DATA : .......#########................
PASS - AFE eye alignment complete
  DATA tap 11, FCLK tap 09, BITSLIPs 2
```

`#` is a zero-error tap and `.` is a failing tap. A one-to-three-tap passing
region is not considered safe. An eye touching tap 0 or tap 31 is reported as
clipped because the tool could not observe both edges.

The latest JSON report is written to
`host/settings/afe_eye_latest.json`. It contains every tap's error counts, the
chosen centres, eye widths, BITSLIP count and ramp result.

## Stronger bench test

The defaults use 16 raw captures per tap. Increase this after basic alignment
works to look for intermittent errors:

```powershell
python host/afe_eye_tool.py --port COM5 --scan-captures 128 --validation-captures 256
```

Run the stronger test several times from cold startup and again after the board
has warmed up. The selected centre may move slightly, but the passing windows
should remain broad and substantially overlap.

The selected taps are volatile FPGA state. Run the tool again after every FPGA
reset until the corrected independent training algorithm is incorporated into
the boot-time RTL.
