@echo off
REM Launch the NSE Breakout Scanner
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
python -m streamlit run app.py
pause
