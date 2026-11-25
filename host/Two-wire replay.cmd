@echo off
python.exe "%~dp0tfm_gl_host.py" --replay "%~dp0..\bench_runs\two-wire\gelatin-two-wire-balanced.rf.npz"
if errorlevel 1 pause
