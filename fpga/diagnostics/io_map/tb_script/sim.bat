@echo off
python "%~dp0..\build.py" --sim-only
exit /b %errorlevel%
