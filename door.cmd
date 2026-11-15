@echo off
rem .\door <command> - the command line (.\door --help lists the commands).
rem The Windows twin of ./door: python -m door in the Poetry environment, with
rem src\ on PYTHONPATH, staying in the current directory.
setlocal
rem UTF-8 mode: text is never read or written in the code page (#132)
set "PYTHONUTF8=1"
set "REPO=%~dp0."
if defined PYTHONPATH set "PYTHONPATH=%REPO%\src;%PYTHONPATH%"
if not defined PYTHONPATH set "PYTHONPATH=%REPO%\src"
poetry -C "%REPO%" run python -m door %*
exit /b %ERRORLEVEL%
