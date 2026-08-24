"""
Popula o control_tower.db — o banco que o dashboard abre por padrão — com
snapshots de exemplo, para ver o painel funcionando sem conexão com o
VoiceLink.

A geração dos números é a mesma do seed_demo.py (contadores acumulados do
dia, ritmo por operador, queda no horário do almoço, metas reais por
região), só que gravando no control_tower.db em vez do
control_tower_demo.db. São 3 dias de operação — hoje, ontem e o dia
anterior (domingo não tem operação e é pulado) — com um snapshot a cada
15 minutos entre 6h e 16h, com o MESMO captured_at nas 5 tabelas, como o
coletor real faz.

ATENÇÃO: dado de demonstração misturado com dado real fica
indistinguível no painel histórico — dia inventado apareceria como dia
de produção de verdade. Por isso o script se recusa a rodar se o banco
já tiver dados nas tabelas do coletor; use --force apenas se tiver
certeza de que o que está lá é descartável.

Uso:
    python seed_demo_data.py            # popula (recusa se já houver dados)
    python seed_demo_data.py --force    # apaga tudo e regenera
    streamlit run app.py                # ver o dashboard
"""
import os
import sys
from datetime import date, datetime, timedelta

RAIZ = os.path.dirname(os.path.abspath(__file__))

# Precisa vir ANTES dos imports abaixo: config.py lê DB_PATH do ambiente
# na importação, e é isso que aponta o database.py para o control_tower.db.
os.environ["DB_PATH"] = os.path.join(RAIZ, "control_tower.db")

import config      # noqa: E402
import database as db  # noqa: E402
import seed_demo  # noqa: E402 — reusa o gerador de dados realistas

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DIAS = 4                  # hoje + 3 dias atrás (o domingo é pulado)
HORA_INICIO, HORA_FIM = 6, 16
INTERVALO_MIN = 15        # o coletor real usa 1 min; 15 min bastam para a demo

TABELAS_DADOS = ["resumo_tarefa", "resumo_trabalho", "produtividade_regiao",
                 "produtos_falta", "produtividade_operador", "pedidos_operador"]


def _tem_dados() -> bool:
    with db.get_connection() as conn:
        return any(
            conn.execute(f"SELECT 1 FROM {tabela} LIMIT 1").fetchone() is not None
            for tabela in TABELAS_DADOS
        )


def _limpar():
    with db.get_connection() as conn:
        for tabela in TABELAS_DADOS:
            conn.execute(f"DELETE FROM {tabela}")
        conn.execute("DELETE FROM coleta_log")


def gerar():
    if config.DATABASE_URL:
        print(
            "DATABASE_URL está definida — o banco ativo é o PostgreSQL de "
            "produção. Este script NUNCA escreve dados de demonstração lá: "
            "desative a variável para usar o SQLite local."
        )
        raise SystemExit(1)
    if _tem_dados():
        if "--force" not in sys.argv:
            print(
                "control_tower.db já contém dados nas tabelas do coletor.\n"
                "Se forem dados REAIS do VoiceLink, não rode este script —\n"
                "misturar demo com produção no painel histórico é pior do que\n"
                "não ter demo. Se for descartável, rode com --force para\n"
                "apagar tudo e regenerar."
            )
            raise SystemExit(1)
        print("--force: apagando o conteúdo atual do control_tower.db...")
        _limpar()

    db.init_db()
    hoje = date.today()
    total_snapshots = 0

    for offset in range(DIAS - 1, -1, -1):
        dia = hoje - timedelta(days=offset)
        if dia.weekday() == 6:     # domingo não tem operação
            continue

        escala = {r: seed_demo.operadores_da_regiao(r, dia) for r in config.REGIONS}
        acumulado = {r: {o["id"]: 0.0 for o in escala[r]} for r in config.REGIONS}
        horas = {r: {o["id"]: 0.0 for o in escala[r]} for r in config.REGIONS}

        # No dia de hoje, só gera até a hora atual — senão o painel mostraria
        # produção "do futuro".
        hora_limite = min(HORA_FIM, datetime.now().hour) if offset == 0 else HORA_FIM

        for hora in range(HORA_INICIO, hora_limite + 1):
            for minuto in range(0, 60, INTERVALO_MIN):
                ts = datetime(dia.year, dia.month, dia.day, hora, minuto).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                seed_demo._gravar_snapshot(ts, escala, acumulado, horas, hora)
                total_snapshots += 1

    print(f"control_tower.db populado: {total_snapshots} snapshots de demonstração")
    print("\nAgora é só rodar o dashboard:")
    print("  streamlit run app.py")


if __name__ == "__main__":
    gerar()
