@echo off
setlocal

cd /d "%~dp0"

echo ==========================================
echo      GTIN SCRAPER
echo ==========================================
echo.

if not exist ".venv" (
    echo [ERRO] Ambiente virtual nao encontrado.
    echo Execute install.bat primeiro.
    echo.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

python main.py

if errorlevel 1 (
    echo.
    echo A aplicacao foi encerrada com erro.
)

echo.
pause