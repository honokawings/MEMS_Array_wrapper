@echo off
setlocal
pushd "%~dp0"
python run_all.py %*
set "MEMS_EXIT=%ERRORLEVEL%"
popd
exit /b %MEMS_EXIT%
