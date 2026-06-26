@echo off
setlocal

cd /d "%~dp0"

echo ==========================================
echo      GTIN - INSTALACAO
echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERRO] Python nao encontrado.
    echo.
    echo Instale o Python 3.12+ e marque a opcao:
    echo     Add Python to PATH
    echo.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Criando ambiente virtual...
    python -m venv .venv
)

call ".venv\Scripts\activate.bat"

echo.
echo Atualizando pip...
python -m pip install --upgrade pip

echo.
echo Instalando dependencias...
pip install -r requirements.txt

echo.
echo Instalando navegadores do Playwright...
playwright install

echo.
echo Instalando navegador do Camoufox...
python -m camoufox fetch

echo.
echo ==========================================
echo      INSTALACAO CONCLUIDA
echo ==========================================
echo.
echo Agora utilize o arquivo run.bat para iniciar a aplicacao.
echo.

pause