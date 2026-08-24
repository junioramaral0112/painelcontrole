#!/usr/bin/env bash
# ============================================================
#  Control Tower - Painel de Controle
#  Inicia o coletor (em segundo plano) e o dashboard Streamlit.
#  Usa o ambiente virtual .venv quando ele existir; caso
#  contrario, usa o python do PATH.
#
#  Parar: Ctrl+C encerra o dashboard e
#  `pkill -f collector.py` encerra o coletor.
# ============================================================
set -u
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
    echo "[ok] usando o ambiente .venv"
else
    PY="python"
    echo "[aviso] .venv nao encontrado - usando o python do PATH"
fi

echo "[1/2] Iniciando o coletor em segundo plano (collector.py)..."
nohup "$PY" collector.py > collector.log 2>&1 &

echo "[2/2] Iniciando o dashboard em http://localhost:8501 ..."
exec "$PY" -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0
