@echo off
setlocal

REM ===========================================================================
REM  refresh_akdb_db.bat - refresh the live AKDB database, with backup + restart
REM
REM    refresh_akdb_db.bat            -> STATUS only (read-only, safe default)
REM    refresh_akdb_db.bat apply      -> swap in the default canonical DB
REM    refresh_akdb_db.bat apply PATH -> swap in PATH as the live DB
REM
REM  Runnable by double-click, or from WSL via interop:
REM    cmd.exe /c "D:\TinyToolDevelopment\ArchitecturalKnowledgeDB\scripts\refresh_akdb_db.bat" apply
REM
REM  After "apply", restart the MCP clients so their stdio servers reopen the DB.
REM  Single writer: the live DB cannot be overwritten while a client still holds
REM  it open; if the copy fails, close MCP clients and re-run.
REM ===========================================================================

set "REPO=D:\TinyToolDevelopment\ArchitecturalKnowledgeDB"
set "PY=C:\Users\YvesT\AppData\Local\Programs\Python\Python314\python.exe"
set "LIVE=%REPO%\.akdb\architectural_knowledge_db.sqlite"
set "PORT=8787"
set "MODE=%~1"
set "SOURCE=%~2"
if "%SOURCE%"=="" set "SOURCE=%REPO%\Temp\ttd-1a.sqlite"
if "%MODE%"=="" set "MODE=status"

cd /d "%REPO%"

echo === AKDB DB refresh (mode: %MODE%) ===
echo repo   : %REPO%
echo live   : %LIVE%
echo source : %SOURCE%
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){'port %PORT% : served by PID '+$c.OwningProcess}else{'port %PORT% : not running'}"

if /I not "%MODE%"=="apply" (
  echo.
  echo [status] read-only - no changes made. Pass "apply" to perform the swap.
  if exist "%SOURCE%" (
    "%PY%" -c "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);print('source projects:',[r[0] for r in c.execute('select project_id from projects')]);print('source links  :',c.execute('select count(*) from knowledge_links').fetchone()[0]);c.close()" "%SOURCE%"
  ) else (
    echo source DB NOT FOUND: %SOURCE%
  )
  goto :end
)

if not exist "%SOURCE%" (
  echo ERROR: source DB not found: %SOURCE%
  goto :end
)

echo.
echo [1/4] Stopping service on :%PORT% ...
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){Stop-Process -Id $c.OwningProcess -Force; Start-Sleep -Seconds 2; 'stopped PID '+$c.OwningProcess}else{'nothing to stop'}"

echo [2/4] Backing up live DB ...
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "TS=%%T"
if exist "%LIVE%" copy /Y "%LIVE%" "%REPO%\.akdb\backup-%TS%.sqlite" >nul && echo   backup: .akdb\backup-%TS%.sqlite
del /Q "%LIVE%-wal" "%LIVE%-shm" >nul 2>&1

echo [3/4] Installing fresh DB ...
copy /Y "%SOURCE%" "%LIVE%" >nul
if errorlevel 1 (
  echo ERROR: copy failed - the DB is still open by a client. Close MCP clients and re-run.
  goto :end
)

echo [4/4] Restarting service on :%PORT% ...
start "AKDB :%PORT%" /min "%PY%" -m architectural_knowledge_db.cli --db "%LIVE%" serve --host 127.0.0.1 --port %PORT%
echo.
echo Done. Live DB replaced (backup kept in .akdb\). Restart MCP clients to reopen the DB.

:end
endlocal
