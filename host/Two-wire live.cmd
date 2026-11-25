@echo off
python.exe "%~dp0tfm_gl_host.py" --settings "%~dp0presets\gelatin-two-wire-best.json"
if errorlevel 1 pause
