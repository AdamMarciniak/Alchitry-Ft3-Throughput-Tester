@echo off
python.exe "%~dp0tfm_gl_host.py" --settings "%~dp0presets\gelatin-floor-timing.json"
if errorlevel 1 pause
