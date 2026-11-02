@echo off
rem 正式開店：雙擊這個檔案（SPEC B1）。視窗要一直開著，關掉就關店。
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
.venv\Scripts\python scripts\run_public.py
pause
