@echo off
REM Faugus launch wrapper for HorizonXI.
REM
REM Forces d3d8to9 (kept as Game\d3d8.dll) to take precedence over the Wine
REM builtin d3d8 that Proton copies into syswow64 on every launch. Runs as the
REM Faugus addapp_bat (with games.json "addapp_enabled": "addapp_enabled"), so
REM cmd.exe inside Wine executes it BEFORE Ashita-cli.exe loads any DLLs.
REM
REM After the copy it launches the game and stays attached until it exits, so
REM Faugus/Proton see a normal game lifecycle.
REM
REM NO EDITING REQUIRED: %~dp0 is this script's own directory (with a trailing
REM backslash), so the wrapper works from whatever path you installed the game
REM to, as long as it sits in the same folder as d3d8.dll and Ashita-cli.exe.
REM
REM %SystemRoot% is the Windows directory inside the Wine prefix. syswow64 is
REM correct here: FFXI is a 32-bit process, and that is where Proton drops its
REM builtin d3d8.dll on each launch.

set "GAME_DIR=%~dp0"
set "TARGET=%SystemRoot%\syswow64\d3d8.dll"

if not exist "%GAME_DIR%d3d8.dll" (
    echo [wrapper] WARNING: d3d8.dll not found in "%GAME_DIR%"
    echo [wrapper] Wine builtin d3d8 will be used - the state-block leak is NOT fixed.
) else (
    copy /Y "%GAME_DIR%d3d8.dll" "%TARGET%" >nul
)

"%GAME_DIR%Ashita-cli.exe" %*
