@echo off
setlocal
cd /d "%~dp0"
echo === Building SUPERGO.exe ===
where py >nul 2>nul && (set PY=py -3) || (where python >nul 2>nul && (set PY=python) || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1))
%PY% -m venv .venv || (echo venv failed & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || (echo pip install failed & pause & exit /b 1)
pyinstaller --noconfirm --clean --onefile --windowed --name SUPERGO --icon supergo.ico ^
  --collect-all webview --collect-all pythonnet --collect-all clr_loader ^
  --add-data "supergo.png;." --add-data "supergo.ico;." --add-data "blocked_hosts.txt;." --add-data "blocklist.meta.json;." --add-data "servers.tsv.gz;." ^
  supergo_win.py || (echo PyInstaller failed & pause & exit /b 1)
echo.
echo Done: %~dp0dist\SUPERGO.exe
pause
