@echo off
REM Faugus launch wrapper for HorizonXI.
REM Used to force d3d8to9 (placed as Game\d3d8.dll) to take precedence over
REM the Wine builtin d3d8 that Proton copies into syswow64 on every launch.
REM Runs as the Faugus addapp_bat (with addapp_checkbox=addapp_enabled), so
REM cmd.exe inside Wine executes this BEFORE Ashita-cli.exe loads any DLLs.
REM
REM After the copy, launches the real game and stays attached until it exits
REM (so Faugus/Proton see normal game lifecycle).

copy /Y "C:\Program Files\HorizonXI\Game\d3d8.dll" "C:\windows\syswow64\d3d8.dll" >nul

"C:\Program Files\HorizonXI\Game\Ashita-cli.exe" %*
