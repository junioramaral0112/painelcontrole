"""
Camada de banco de dados do Control Tower.

Usa SQLite por simplicidade (arquivo único, sem servidor separado).
Se o volume de dados crescer muito ou for necessário acesso concorrente
mais pesado, trocar por PostgreSQL é direto: as funções aqui isolam todo
o SQL, então só este arquivo precisaria mudar.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS resumo_tarefa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    region_number INTEGER NOT NULL,
    region_name TEXT NOT NULL,
    total INTEGER,
    em_andamento INTEGER,
    disponivel INTEGER,
    concluido INTEGER,
    nao_concluido INTEGER
);

CREATE TABLE IF NOT EXISTS resumo_trabalho (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    region_number INTEGER NOT NULL,
    region_name TEXT NOT NULL,
    operadores_trabalhando INTEGER,
    operadores_atribuidos INTEGER,
    itens_restantes INTEGER,
    itens_selecionados INTEGER,
    estimado_concluido REAL,
    meta_regiao INTEGER
);

CREATE TABLE IF NOT EXISTS produtividade_regiao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    region_number INTEGER NOT NULL,
    region_name TEXT NOT NULL,
    quantidade_total INTEGER,
    produtividade_atual REAL,
    numero_operadores INTEGER,
    pct_meta REAL,
    tempo_total TEXT,
    meta REAL
);

CREATE TABLE IF NOT EXISTS produtos_falta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    region_number INTEGER NOT NULL,
    region_name TEXT NOT NULL,
    total_faltas INTEGER,
    em_falta INTEGER,
    atribuido INTEGER,
    marcado INTEGER
);

CREATE TABLE IF NOT EXISTS produtividade_operador (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    region_number INTEGER NOT NULL,
    region_name TEXT NOT NULL,
    operador_id TEXT NOT NULL,
    quantidade INTEGER,
    tempo_total TEXT,
    meta REAL,
    produtividade_real REAL,
    pct_meta REAL
);

CREATE TABLE IF NOT EXISTS coleta_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    sucesso INTEGER NOT NULL,
    detalhe TEXT
);

-- Contagem de pedidos por operador (coluna "Qtda Pedido" do painel
-- histórico — seção 5.2 da especificação).
--
-- ATENÇÃO: esta tabela é alimentada a partir do endpoint de detalhe de
-- atribuições, que TAMBÉM devolve dados de cliente (nome, endereço,
-- customerNumber). Nenhum desses campos pode chegar aqui: o parser usa
-- uma allowlist e só deixa passar as 4 colunas abaixo. Não adicione
-- colunas a esta tabela sem reler a seção 5.2 da especificação.
--
-- `pedido_ref` é o id numérico interno da atribuição, não o número do
-- pedido do cliente.
CREATE TABLE IF NOT EXISTS pedidos_operador (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    dia TEXT NOT NULL,
    region_number INTEGER NOT NULL,
    region_name TEXT NOT NULL,
    operador_id TEXT NOT NULL,
    pedido_ref TEXT NOT NULL,
    status TEXT,
    UNIQUE (dia, region_number, operador_id, pedido_ref)
);

-- Índices para acelerar as consultas do dashboard (curva de evolução etc.)
CREATE INDEX IF NOT EXISTS idx_tarefa_time ON resumo_tarefa (captured_at);
CREATE INDEX IF NOT EXISTS idx_trabalho_time ON resumo_trabalho (captured_at);
CREATE INDEX IF NOT EXISTS idx_prodregiao_time ON produtividade_regiao (captured_at);
CREATE INDEX IF NOT EXISTS idx_falta_time ON produtos_falta (captured_at);
CREATE INDEX IF NOT EXISTS idx_prodoperador_time ON produtividade_operador (captured_at);

-- Índices por (região, dia): o painel histórico sempre filtra por essas
-- duas dimensões juntas, então o índice composto evita varrer a tabela
-- inteira conforme o histórico cresce.
CREATE INDEX IF NOT EXISTS idx_prodoperador_regiao_dia
    ON produtividade_operador (region_number, captured_at);
CREATE INDEX IF NOT EXISTS idx_prodregiao_regiao_dia
    ON produtividade_regiao (region_number, captured_at);
CREATE INDEX IF NOT EXISTS idx_pedidos_regiao_dia
    ON pedidos_operador (region_number, dia);
"""


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Cria as tabelas se ainda não existirem. Chamar uma vez ao iniciar."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def insert_resumo_tarefa(rows):
    """rows: lista de dicts vindos do parser de viewId=-1105"""
    ts = _now()
    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO resumo_tarefa
               (captured_at, region_number, region_name, total, em_andamento,
                disponivel, concluido, nao_concluido)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(ts, r["region_number"], r["region_name"], r["total"],
              r["em_andamento"], r["disponivel"], r["concluido"],
              r["nao_concluido"]) for r in rows],
        )


def insert_resumo_trabalho(rows):
    ts = _now()
    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO resumo_trabalho
               (captured_at, region_number, region_name, operadores_trabalhando,
                operadores_atribuidos, itens_restantes, itens_selecionados,
                estimado_concluido, meta_regiao)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(ts, r["region_number"], r["region_name"], r["operadores_trabalhando"],
              r["operadores_atribuidos"], r["itens_restantes"], r["itens_selecionados"],
              r["estimado_concluido"], r["meta_regiao"]) for r in rows],
        )


def insert_produtividade_regiao(rows):
    ts = _now()
    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO produtividade_regiao
               (captured_at, region_number, region_name, quantidade_total,
                produtividade_atual, numero_operadores, pct_meta, tempo_total, meta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(ts, r["region_number"], r["region_name"], r["quantidade_total"],
              r["produtividade_atual"], r["numero_operadores"], r["pct_meta"],
              r["tempo_total"], r["meta"]) for r in rows],
        )


def insert_produtos_falta(rows):
    ts = _now()
    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO produtos_falta
               (captured_at, region_number, region_name, total_faltas,
                em_falta, atribuido, marcado)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(ts, r["region_number"], r["region_name"], r["total_faltas"],
              r["em_falta"], r["atribuido"], r["marcado"]) for r in rows],
        )


def insert_produtividade_operador(rows):
    """rows: lista de dicts já FILTRADOS (quantidade > 0)"""
    ts = _now()
    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO produtividade_operador
               (captured_at, region_number, region_name, operador_id, quantidade,
                tempo_total, meta, produtividade_real, pct_meta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(ts, r["region_number"], r["region_name"], r["operador_id"],
              r["quantidade"], r["tempo_total"], r["meta"],
              r["produtividade_real"], r["pct_meta"]) for r in rows],
        )


def log_coleta(sucesso: bool, detalhe: str = ""):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO coleta_log (captured_at, sucesso, detalhe) VALUES (?, ?, ?)",
            (_now(), 1 if sucesso else 0, detalhe),
        )


def get_latest_snapshot(table: str):
    """Retorna as linhas do timestamp mais recente de uma tabela."""
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT captured_at FROM {table} ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return []
        latest_ts = row["captured_at"]
        cur = conn.execute(
            f"SELECT * FROM {table} WHERE captured_at = ? ORDER BY region_name",
            (latest_ts,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_history(table: str, hours: int = 8):
    """Retorna histórico das últimas N horas, para curva de evolução."""
    with get_connection() as conn:
        cur = conn.execute(
            f"""SELECT * FROM {table}
                WHERE captured_at >= datetime('now', ?)
                ORDER BY captured_at""",
            (f"-{hours} hours",),
        )
        return [dict(r) for r in cur.fetchall()]


def get_last_collection_status():
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM coleta_log ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def insert_pedidos_operador(rows):
    """rows: dicts já passados pela allowlist do parser (seção 5.2).

    Usa INSERT OR REPLACE para que uma nova coleta atualize o `status` de
    um pedido já visto no mesmo dia, sem duplicar a contagem — a chave
    única é (dia, região, operador, pedido).
    """
    if not rows:
        return
    ts = _now()
    with get_connection() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO pedidos_operador
               (captured_at, dia, region_number, region_name, operador_id,
                pedido_ref, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(ts, ts[:10], r["region_number"], r["region_name"],
              r["operador_id"], r["pedido_ref"], r["status"]) for r in rows],
        )


# =========================================================================
# Painel Histórico por Região (seção 5.1)
# =========================================================================
#
# COMO OS CONTADORES DO VOICELINK FUNCIONAM — leia antes de mexer nestas
# queries, porque é aqui que mora o erro fácil de cometer:
#
# `quantidade` e `quantidade_total` são contadores ACUMULADOS do dia, não
# incrementos. O snapshot das 14h já contém tudo o que foi separado desde
# o início do turno. Consequências:
#
#   * O total de um dia é o MAIOR valor observado naquele dia (MAX) —
#     NUNCA a soma dos snapshots. Como o coletor grava 1x por minuto,
#     somar os snapshots inflaria o número em ~600x.
#   * As TAXAS (`produtividade_real`, `produtividade_atual`, que são
#     quantidade ÷ tempo) vêm do ÚLTIMO snapshot do dia — essa é a média
#     do dia fechado. Um MAX sobre a taxa pegaria o pico artificial dos
#     primeiros minutos, quando o denominador de tempo ainda é quase zero.
#   * A produção de UMA hora específica é a DIFERENÇA entre o acumulado do
#     fim e o do começo daquela hora (ver `derivar_producao_horaria`).
#
# Por isso as funções abaixo combinam MAX(quantidade) com um JOIN no
# último snapshot: cada métrica é agregada do jeito que faz sentido para
# ela, e não do mesmo jeito para todas.


def _fetch(sql: str, params: dict):
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_datas_disponiveis(region_number: int) -> list:
    """Dias (YYYY-MM-DD) que têm pelo menos um snapshot desta região.

    Alimenta o filtro ano -> mês -> dia. Só existem dados a partir do
    momento em que o collector.py passou a rodar (seção 6): dias
    anteriores a isso simplesmente não aparecem na lista.
    """
    rows = _fetch(
        """SELECT DISTINCT date(captured_at) AS dia
             FROM produtividade_regiao
            WHERE region_number = :r
            ORDER BY dia""",
        {"r": region_number},
    )
    return [r["dia"] for r in rows]


def get_operadores_do_dia(region_number: int, dia: str) -> list:
    """Um registro por operador que produziu na região naquele dia.

    `quantidade` = MAX do contador acumulado (total do dia).
    `produtividade_real` / `pct_meta` = valores do ÚLTIMO snapshot do dia.
    `pedidos` = contagem de pedidos distintos, ou None se a coleta de
    pedidos (seção 5.2) estiver desligada — nesse caso o painel mostra
    "—" na coluna Qtda Pedido em vez de um zero enganoso.
    """
    return _fetch(
        """
        SELECT
            agg.operador_id,
            agg.quantidade,
            ult.tempo_total,
            ult.meta,
            ult.produtividade_real,
            ult.pct_meta,
            ped.pedidos
        FROM (
            SELECT operador_id,
                   MAX(quantidade)  AS quantidade,
                   MAX(captured_at) AS ultimo_ts
              FROM produtividade_operador
             WHERE region_number = :r AND date(captured_at) = :d
             GROUP BY operador_id
        ) AS agg
        JOIN produtividade_operador AS ult
          ON ult.operador_id   = agg.operador_id
         AND ult.captured_at   = agg.ultimo_ts
         AND ult.region_number = :r
        LEFT JOIN (
            SELECT operador_id, COUNT(DISTINCT pedido_ref) AS pedidos
              FROM pedidos_operador
             WHERE region_number = :r AND dia = :d
             GROUP BY operador_id
        ) AS ped
          ON ped.operador_id = agg.operador_id
        GROUP BY agg.operador_id
        ORDER BY agg.quantidade DESC
        """,
        {"r": region_number, "d": dia},
    )


def get_totais_regiao_dia(region_number: int, dia: str):
    """Totais da região num dia: quantidade acumulada + taxa de fechamento.

    Retorna None se não houve coleta nesse dia.
    """
    rows = _fetch(
        """
        SELECT
            (SELECT MAX(quantidade_total)
               FROM produtividade_regiao
              WHERE region_number = :r AND date(captured_at) = :d) AS quantidade,
            ult.produtividade_atual,
            ult.pct_meta,
            ult.meta,
            ult.tempo_total,
            ult.numero_operadores,
            ult.captured_at
        FROM produtividade_regiao AS ult
        WHERE ult.region_number = :r AND date(ult.captured_at) = :d
        ORDER BY ult.captured_at DESC
        LIMIT 1
        """,
        {"r": region_number, "d": dia},
    )
    return rows[0] if rows else None


def get_serie_por_dia(region_number: int, ano_mes: str) -> list:
    """Total separado por dia ao longo de um mês (YYYY-MM).

    Serve para duas coisas: o gráfico "Separação/Dia" e o cálculo dos
    KPIs mensais (que são a soma desta série, não um MAX sobre o mês).
    Traz também `tempo_total` do fim de cada dia, necessário para a
    produtividade mensal ponderada.
    """
    return _fetch(
        """
        SELECT
            d.dia,
            d.quantidade,
            ult.tempo_total,
            ult.meta,
            ult.produtividade_atual
        FROM (
            SELECT date(captured_at)      AS dia,
                   MAX(quantidade_total)  AS quantidade,
                   MAX(captured_at)       AS ultimo_ts
              FROM produtividade_regiao
             WHERE region_number = :r
               AND strftime('%Y-%m', captured_at) = :mes
             GROUP BY dia
        ) AS d
        JOIN produtividade_regiao AS ult
          ON ult.captured_at   = d.ultimo_ts
         AND ult.region_number = :r
        GROUP BY d.dia
        ORDER BY d.dia
        """,
        {"r": region_number, "mes": ano_mes},
    )


def get_acumulado_por_hora(region_number: int, dia: str) -> list:
    """Maior acumulado observado em cada hora do dia (itens e horas).

    Ainda são os contadores ACUMULADOS — para virar produtividade hora a
    hora precisa passar por `derivar_series_horarias`.

    `tempo_acumulado` é a soma das horas-OPERADOR do dia (não o relógio
    de parede): 5 pessoas trabalhando 1h somam 5h aqui. É o denominador
    que o próprio VoiceLink usa para calcular a taxa, então é ele que
    torna o número comparável com a meta.
    """
    return _fetch(
        """
        SELECT CAST(strftime('%H', captured_at) AS INTEGER) AS hora,
               MAX(quantidade_total)                        AS acumulado,
               MAX(tempo_total)                             AS tempo_acumulado
          FROM produtividade_regiao
         WHERE region_number = :r AND date(captured_at) = :d
         GROUP BY hora
         ORDER BY hora
        """,
        {"r": region_number, "d": dia},
    )


def derivar_series_horarias(linhas: list) -> list:
    """Converte os acumulados por hora no que aconteceu EM cada hora.

    Recebe o resultado de `get_acumulado_por_hora` e devolve 24 registros
    (hora 0..23), cada um com:

        itens          -> itens separados naquela hora (vazão da região)
        horas_operador -> horas-operador gastas naquela hora
        produtividade  -> itens por hora-operador  <-- comparável com a meta

    A distinção entre as duas últimas colunas é o ponto delicado aqui. A
    meta (`goalRate`, ex.: 1350) é POR OPERADOR: o próprio VoiceLink
    calcula `actualRate = totalQuantity / totalTime`, onde totalTime é a
    soma das horas-operador — foi assim que os 62,21% da amostra real
    bateram. Plotar a vazão da região (que com 5 operadores é ~5x maior)
    contra essa meta faria a linha da meta parecer baixíssima e o painel
    mentiria para quem olha da TV.

    Horas sem coleta ficam zeradas (fora do turno), como nos painéis de
    referência. Deltas negativos são cortados em zero: isso só acontece
    se o VoiceLink zerar o contador no meio do dia (virada de turno), e
    um número negativo num gráfico de produção seria pior que um zero.

    Se o coletor ficar fora do ar por algumas horas no meio do turno,
    essas horas aparecem como zero e a produção acumulada durante a
    lacuna cai toda na primeira hora que voltou a ter coleta. O total do
    dia continua certo; a distribuição dentro da lacuna é que se perde —
    não há como reconstruí-la sem os snapshots que faltaram.
    """
    itens_por_hora = {int(r["hora"]): (r["acumulado"] or 0) for r in linhas}
    tempo_por_hora = {
        int(r["hora"]): parse_tempo_total(r.get("tempo_acumulado")) for r in linhas
    }

    series = []
    itens_antes, tempo_antes = 0.0, 0.0
    for hora in range(24):
        if hora not in itens_por_hora:
            series.append({"hora": hora, "itens": 0.0,
                           "horas_operador": 0.0, "produtividade": 0.0})
            continue

        itens_agora = float(itens_por_hora[hora])
        tempo_agora = tempo_por_hora.get(hora, 0.0)

        itens = max(0.0, itens_agora - itens_antes)
        horas = max(0.0, tempo_agora - tempo_antes)

        series.append({
            "hora": hora,
            "itens": itens,
            "horas_operador": horas,
            # Sem horas-operador registradas na hora não dá para calcular
            # taxa nenhuma — fica zero em vez de dividir por zero.
            "produtividade": (itens / horas) if horas > 0 else 0.0,
        })
        itens_antes, tempo_antes = itens_agora, tempo_agora

    return series


def parse_tempo_total(tempo: str) -> float:
    """Converte "HH:MM:SS" em horas decimais.

    O VoiceLink devolve horas-operador acumuladas, que passam de 24h sem
    problema (ex.: "12:46:23" = 5 operadores durante ~2,5h cada). Por isso
    não dá para usar datetime.strptime aqui.
    """
    if not tempo:
        return 0.0
    partes = str(tempo).split(":")
    try:
        horas = float(partes[0])
        minutos = float(partes[1]) if len(partes) > 1 else 0.0
        segundos = float(partes[2]) if len(partes) > 2 else 0.0
    except (ValueError, IndexError):
        return 0.0
    return horas + minutos / 60.0 + segundos / 3600.0


def get_totais_regiao_mes(region_number: int, ano_mes: str):
    """KPIs mensais: soma dos totais diários + produtividade ponderada.

    A produtividade do mês NÃO é a média das produtividades diárias (isso
    daria o mesmo peso a um dia de 1h e a um dia de 12h). É o total de
    itens dividido pelo total de horas-operador do mês.
    """
    dias = get_serie_por_dia(region_number, ano_mes)
    if not dias:
        return None

    quantidade = sum(d["quantidade"] or 0 for d in dias)
    horas = sum(parse_tempo_total(d["tempo_total"]) for d in dias)
    metas = [d["meta"] for d in dias if d["meta"]]

    return {
        "quantidade": quantidade,
        "horas": horas,
        "produtividade_atual": (quantidade / horas) if horas > 0 else 0.0,
        "meta": metas[-1] if metas else None,
        "dias_com_dado": len(dias),
    }


# --- Pedidos (seção 5.2) --------------------------------------------------

def tem_dados_de_pedidos() -> bool:
    """A coleta de pedidos é opcional e desligada por padrão. O painel usa
    isto para decidir entre mostrar a coluna ou um "—" honesto."""
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM pedidos_operador LIMIT 1").fetchone()
        return row is not None


def get_pedidos_dia(region_number: int, dia: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT COUNT(DISTINCT pedido_ref) AS n
                 FROM pedidos_operador
                WHERE region_number = :r AND dia = :d""",
            {"r": region_number, "d": dia},
        ).fetchone()
        return row["n"] if row else 0


def get_pedidos_mes(region_number: int, ano_mes: str) -> int:
    """Soma dos pedidos de cada dia do mês.

    Conta (dia, pedido) distintos e não só (pedido): um pedido que
    atravessa a virada do dia conta nos dois dias. É proposital — assim a
    soma dos números diários bate com o número mensal mostrado ao lado.
    """
    with get_connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM (
                   SELECT DISTINCT dia, pedido_ref
                     FROM pedidos_operador
                    WHERE region_number = :r AND substr(dia, 1, 7) = :mes
               )""",
            {"r": region_number, "mes": ano_mes},
        ).fetchone()
        return row["n"] if row else 0
