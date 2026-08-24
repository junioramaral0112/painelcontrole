"""
Gera dados de demonstração para conferir o painel histórico sem precisar
esperar o coletor acumular dias de histórico.

É uma ferramenta de desenvolvimento, não faz parte do produto.

Por segurança, grava num banco SEPARADO (control_tower_demo.db) e se
recusa a mexer num banco que já tenha dados reais — misturar número
inventado com número de produção num painel que a fábrica usa para tomar
decisão seria bem pior do que não ter demo nenhuma.

Uso:
    python seed_demo.py                 # cria control_tower_demo.db
    streamlit run app.py                # com DB_PATH apontando pro demo

    # PowerShell:
    $env:DB_PATH="control_tower_demo.db"; streamlit run app.py
"""
import os
import random
import sys
from datetime import date, datetime, timedelta

DB_DEMO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "control_tower_demo.db")
os.environ.setdefault("DB_PATH", DB_DEMO)

import config      # noqa: E402
import database as db  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Metas reais por região, confirmadas contra os painéis existentes.
METAS = {6: 50, 7: 336, 8: 1350, 9: 300}

DIAS = 12                # quantos dias de histórico gerar
HORA_INICIO, HORA_FIM = 6, 16
INTERVALO_MIN = 10       # um snapshot a cada 10 min (o coletor real usa 1 min)

random.seed(42)          # histórico reproduzível


def operadores_da_regiao(region_number: int, dia: date) -> list:
    """Escalação do dia: 3 a 6 operadores, cada um com o seu ritmo."""
    quantidade = random.randint(3, 6)
    base = region_number * 1000
    return [
        {
            "id": f"{base + i:08d}",
            # Cada operador rende entre 55% e 115% da meta.
            "ritmo": METAS[region_number] * random.uniform(0.55, 1.15),
            "entrada": HORA_INICIO + random.choice([0, 0, 0, 1]),
        }
        for i in range(1, quantidade + 1)
    ]


def gerar():
    if config.DATABASE_URL:
        print(
            "DATABASE_URL está definida — o banco ativo é o PostgreSQL de "
            "produção. Este script NUNCA escreve dados de demonstração lá: "
            "desative a variável para gerar o demo local."
        )
        raise SystemExit(1)
    if os.path.exists(DB_DEMO):
        os.remove(DB_DEMO)
    db.init_db()

    hoje = date.today()
    total_snapshots = 0

    for offset in range(DIAS - 1, -1, -1):
        dia = hoje - timedelta(days=offset)
        if dia.weekday() == 6:     # domingo não tem operação
            continue

        escala = {r: operadores_da_regiao(r, dia) for r in config.REGIONS}
        acumulado = {r: {o["id"]: 0.0 for o in escala[r]} for r in config.REGIONS}
        # Horas-operador acumuladas, que sobem junto com a quantidade. É o
        # que o VoiceLink devolve em totalTime e o denominador de toda
        # taxa do painel — por isso precisa acumular do mesmo jeito, e não
        # ser recalculado a cada snapshot.
        horas = {r: {o["id"]: 0.0 for o in escala[r]} for r in config.REGIONS}

        # No dia de hoje, só gera até a hora atual — senão o painel do dia
        # corrente mostraria produção "do futuro".
        hora_limite = min(HORA_FIM, datetime.now().hour) if offset == 0 else HORA_FIM

        for hora in range(HORA_INICIO, hora_limite + 1):
            for minuto in range(0, 60, INTERVALO_MIN):
                ts = datetime(dia.year, dia.month, dia.day, hora, minuto).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                _gravar_snapshot(ts, escala, acumulado, horas, hora)
                total_snapshots += 1

    print(f"Banco de demonstração criado: {DB_DEMO}")
    print(f"{total_snapshots} snapshots · {DIAS} dias · {len(config.REGIONS)} regiões")
    print("\nPara ver o painel com esses dados (PowerShell):")
    print('  $env:DB_PATH="control_tower_demo.db"; streamlit run app.py')


def _gravar_snapshot(ts: str, escala: dict, acumulado: dict, horas: dict, hora: int):
    """Um ciclo de coleta: avança os contadores e grava as 5 tabelas."""
    fracao = INTERVALO_MIN / 60.0
    linhas_operador, linhas_regiao, linhas_trabalho, linhas_tarefa, linhas_falta = \
        [], [], [], [], []

    for region_number, region_name in config.REGIONS.items():
        meta = METAS[region_number]

        for operador in escala[region_number]:
            if hora < operador["entrada"]:
                continue
            # Hora do almoço: produção cai bastante, mas o operador segue
            # logado — o tempo continua correndo, e é isso que faz a
            # produtividade cair no gráfico em vez de sumir.
            fator = 0.25 if hora == 11 else random.uniform(0.8, 1.2)
            acumulado[region_number][operador["id"]] += operador["ritmo"] * fracao * fator
            horas[region_number][operador["id"]] += fracao

            quantidade = int(acumulado[region_number][operador["id"]])
            if quantidade <= 0:
                continue

            horas_trabalhadas = horas[region_number][operador["id"]]
            taxa = quantidade / horas_trabalhadas if horas_trabalhadas > 0 else 0.0

            linhas_operador.append({
                "region_number": region_number, "region_name": region_name,
                "operador_id": operador["id"], "quantidade": quantidade,
                "tempo_total": _hhmmss(horas_trabalhadas), "meta": meta,
                "produtividade_real": round(taxa, 2),
                "pct_meta": round(taxa / meta * 100, 2),
            })

        total_regiao = int(sum(acumulado[region_number].values()))
        horas_acumuladas = sum(horas[region_number].values())
        taxa_regiao = total_regiao / horas_acumuladas if horas_acumuladas > 0 else 0.0

        linhas_regiao.append({
            "region_number": region_number, "region_name": region_name,
            "quantidade_total": total_regiao,
            "produtividade_atual": round(taxa_regiao, 2),
            "numero_operadores": len(escala[region_number]),
            "pct_meta": round(taxa_regiao / meta * 100, 2),
            "tempo_total": _hhmmss(horas_acumuladas), "meta": meta,
        })
        linhas_trabalho.append({
            "region_number": region_number, "region_name": region_name,
            "operadores_trabalhando": len(escala[region_number]),
            "operadores_atribuidos": 0,
            "itens_restantes": max(0, int(meta * 12) - total_regiao),
            "itens_selecionados": total_regiao,
            "estimado_concluido": round(random.uniform(0.4, 0.9), 2),
            "meta_regiao": meta,
        })
        concluido = total_regiao // max(1, int(meta / 8))
        linhas_tarefa.append({
            "region_number": region_number, "region_name": region_name,
            "total": concluido + 40, "em_andamento": len(escala[region_number]),
            "disponivel": 40 - len(escala[region_number]),
            "concluido": concluido, "nao_concluido": 40,
        })
        linhas_falta.append({
            "region_number": region_number, "region_name": region_name,
            "total_faltas": random.randint(0, 4), "em_falta": random.randint(0, 3),
            "atribuido": 0, "marcado": 0,
        })

    # Grava tudo com o MESMO captured_at, como faz o coletor real.
    _inserir_com_timestamp(ts, linhas_tarefa, linhas_trabalho, linhas_regiao,
                           linhas_falta, linhas_operador)


def _inserir_com_timestamp(ts, tarefa, trabalho, regiao, falta, operador):
    """Insere direto, para poder controlar o captured_at (as funções do
    database.py sempre carimbam a hora atual, que é o certo em produção
    mas não serve para gerar histórico).

    Parâmetros nomeados por causa do SQLAlchemy 2.x, que não aceita
    parâmetros posicionais — os dicts do gerador já têm as chaves com os
    nomes exatos das colunas.
    """
    from sqlalchemy import text

    with db.get_connection() as conn:
        conn.execute(
            text(
                """INSERT INTO resumo_tarefa (captured_at, region_number, region_name,
                   total, em_andamento, disponivel, concluido, nao_concluido)
                   VALUES (:captured_at, :region_number, :region_name, :total,
                           :em_andamento, :disponivel, :concluido, :nao_concluido)"""
            ),
            [dict(r, captured_at=ts) for r in tarefa],
        )
        conn.execute(
            text(
                """INSERT INTO resumo_trabalho (captured_at, region_number, region_name,
                   operadores_trabalhando, operadores_atribuidos, itens_restantes,
                   itens_selecionados, estimado_concluido, meta_regiao)
                   VALUES (:captured_at, :region_number, :region_name,
                           :operadores_trabalhando, :operadores_atribuidos,
                           :itens_restantes, :itens_selecionados,
                           :estimado_concluido, :meta_regiao)"""
            ),
            [dict(r, captured_at=ts) for r in trabalho],
        )
        conn.execute(
            text(
                """INSERT INTO produtividade_regiao (captured_at, region_number,
                   region_name, quantidade_total, produtividade_atual,
                   numero_operadores, pct_meta, tempo_total, meta)
                   VALUES (:captured_at, :region_number, :region_name,
                           :quantidade_total, :produtividade_atual,
                           :numero_operadores, :pct_meta, :tempo_total, :meta)"""
            ),
            [dict(r, captured_at=ts) for r in regiao],
        )
        conn.execute(
            text(
                """INSERT INTO produtos_falta (captured_at, region_number, region_name,
                   total_faltas, em_falta, atribuido, marcado)
                   VALUES (:captured_at, :region_number, :region_name,
                           :total_faltas, :em_falta, :atribuido, :marcado)"""
            ),
            [dict(r, captured_at=ts) for r in falta],
        )
        conn.execute(
            text(
                """INSERT INTO produtividade_operador (captured_at, region_number,
                   region_name, operador_id, quantidade, tempo_total, meta,
                   produtividade_real, pct_meta)
                   VALUES (:captured_at, :region_number, :region_name, :operador_id,
                           :quantidade, :tempo_total, :meta,
                           :produtividade_real, :pct_meta)"""
            ),
            [dict(r, captured_at=ts) for r in operador],
        )
        conn.execute(
            text(
                "INSERT INTO coleta_log (captured_at, sucesso, detalhe) "
                "VALUES (:captured_at, 1, :detalhe)"
            ),
            {"captured_at": ts, "detalhe": "dados de demonstração"},
        )


def _hhmmss(horas: float) -> str:
    total = int(horas * 3600)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


if __name__ == "__main__":
    gerar()
