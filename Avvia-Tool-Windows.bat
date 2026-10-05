@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python non trovato. Installa Python 3 e riprova.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Impossibile creare l'ambiente Python.
        pause
        exit /b 1
    )
)

if not exist ".venv\requirements-installed-word" (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Installazione delle dipendenze non riuscita.
        pause
        exit /b 1
    )
    type nul > ".venv\requirements-installed-word"
)

".venv\Scripts\python.exe" -m streamlit run app.py
if errorlevel 1 (
    echo Il programma si e' chiuso con un errore.
    pause
)
