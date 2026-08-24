@echo off
REM ============================================================
REM  Control Tower - Painel de Controle
REM  Inicia o coletor (em segundo plano) e o dashboard Streamlit.
REM  Usa o ambiente virtual .venv quando ele existir; caso
REM  contrario, usa o python do PATH.
REM
REM  Parar: feche a janela "Control Tower - Coletor" e depois
REM  esta janela (Ctrl+C encerra o Streamlit).
REM ============================================================
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    echo [ok] usando o ambiente .venv
) else (
    set "PY=python"
    echo [aviso] .venv nao encontrado - usando o python do PATH
)

echo [1/2] Iniciando o coletor em segundo plano (collector.py)...
start "Control Tower - Coletor" /min cmd /c ""%PY%" collector.py"

echo [2/2] Iniciando o dashboard em http://localhost:8501 ...
"%PY%" -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0

endlocal
