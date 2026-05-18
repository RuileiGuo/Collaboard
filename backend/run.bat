@echo off
cd /d "%~dp0.."
if "%COLLABOARD_HOST%"=="" set "COLLABOARD_HOST=0.0.0.0"
if "%COLLABOARD_PORT%"=="" set "COLLABOARD_PORT=8000"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m uvicorn backend.main:app --host %COLLABOARD_HOST% --port %COLLABOARD_PORT% --reload
) else (
  python -m uvicorn backend.main:app --host %COLLABOARD_HOST% --port %COLLABOARD_PORT% --reload
)
