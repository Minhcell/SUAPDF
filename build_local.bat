@echo off
chcp 65001 >nul
REM Build SuaPDF.exe tren may Windows co Python 3.10+ (can Internet de tai thu vien lan dau)
python -m pip install -r requirements.txt pyinstaller==6.22.3
pyinstaller --noconfirm --clean --onefile --windowed --name SuaPDF --icon icon.ico --collect-submodules pdf2docx --hidden-import selftest --hidden-import convert --hidden-import wordnative --hidden-import win32com.client --hidden-import pythoncom --hidden-import openpyxl --exclude-module tkinter --exclude-module matplotlib --exclude-module scipy --exclude-module pandas --exclude-module PyQt5.QtWebEngineWidgets app.py
echo.
echo Xong! File exe nam trong thu muc dist\SuaPDF.exe
pause
