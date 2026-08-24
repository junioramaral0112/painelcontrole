"""
Teste offline: valida os parsers e a gravação no banco usando os JSONs
REAIS que você extraiu do navegador (colados nesta conversa), sem
precisar de rede até o VoiceLink. Roda local, não é parte do produto.
"""
import os
import sys
import tempfile

# O console do Windows abre em cp1252/cp850, que não dá conta dos acentos
# e dos símbolos usados aqui. Sem isto o teste passa mas quebra no print
# final, o que parece falha de teste sem ser.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Banco temporário próprio para o teste — via tempfile, que resolve para
# um caminho válido no Windows e no Linux (o "/tmp" fixo que estava aqui
# só funcionava fora do Windows, que é justamente onde o painel roda).
DB_TESTE = os.path.join(tempfile.gettempdir(), "test_control_tower.db")
os.environ["DB_PATH"] = DB_TESTE
# O teste roda SEMPRE no SQLite local, mesmo que o ambiente tenha
# DATABASE_URL definida (nada de apontar os testes para o Postgres).
os.environ.pop("DATABASE_URL", None)

import database as db
from sqlalchemy import text as _text
from collector import (
    parse_resumo_tarefa, parse_resumo_trabalho,
    parse_produtividade_regiao, parse_produtos_falta,
    parse_produtividade_operador, parse_atribuicoes_sem_pii,
)

# JSON real de viewId=-1105 (Resumo da Tarefa) que você colou
resumo_tarefa_payload = {
    "objects": [
        {"site": {"name": "7832"}, "nonComplete": 56, "totalAssignments": 155,
         "inProgress": 3, "available": 52, "region": {"number": 8, "name": "Reg Bolsas"}, "complete": 99},
        {"site": {"name": "7832"}, "nonComplete": 0, "totalAssignments": 29,
         "inProgress": 0, "available": 0, "region": {"number": 7, "name": "Reg Caixas"}, "complete": 29},
    ],
    "count": 2,
}

# JSON real de viewId=-1106 (Resumo do Trabalho) que você colou
resumo_trabalho_payload = {
    "objects": [
        {"operatorsWorkingIn": 3, "operatorsAssigned": 0, "totalItemsRemaining": 2384,
         "totalItemsPicked": 10550, "estimatedCompleted": 0.59,
         "region": {"number": 8, "name": "Reg Bolsas", "goalRate": 1350}},
    ],
    "count": 1,
}

# JSON real de viewId=-1016 (Produtividade por Região)
prod_regiao_payload = {
    "objects": [
        {"totalQuantity": 10727, "actualRate": 839.81, "numberOfOperators": 5,
         "percentOfGoal": 62.21, "totalTime": "12:46:23", "goalRate": 1350,
         "region": {"number": 8, "name": "Reg Bolsas"}},
    ],
    "count": 1,
}

# JSON real de viewId=-1107 (Produtos em Falta)
produtos_falta_payload = {
    "objects": [
        {"markedout": 0, "totalShorts": 2, "assigned": 0, "shorted": 2,
         "region": {"number": 8, "name": "Reg Bolsas"}},
    ],
    "count": 1,
}

# JSON real de produtividade por operador (Reg Bolsas), incluindo um caso
# zerado que a regra de negócio deve descartar
prod_operador_payload = {
    "objects": [
        {"totalQuantity": 1646, "actualRate": 895.51, "totalTime": "01:50:17",
         "percentOfGoal": 66.33, "goalRate": 1350, "filterType": "Seleção",
         "operator": {"common": {"operatorIdentifier": "09524025"}}},
        {"totalQuantity": 0, "actualRate": 0, "totalTime": "00:00:00",
         "percentOfGoal": 0, "goalRate": 1350, "filterType": "Outro",
         "operator": {"common": {"operatorIdentifier": "00000000"}}},
    ],
    "count": 2,
}

print("== Testando parsers ==")
tarefa = parse_resumo_tarefa(resumo_tarefa_payload)
assert len(tarefa) == 2 and tarefa[0]["region_name"] == "Reg Bolsas"
print("OK: parse_resumo_tarefa ->", tarefa)

trabalho = parse_resumo_trabalho(resumo_trabalho_payload)
assert trabalho[0]["itens_restantes"] == 2384
print("OK: parse_resumo_trabalho ->", trabalho)

pr = parse_produtividade_regiao(prod_regiao_payload)
assert pr[0]["pct_meta"] == 62.21
print("OK: parse_produtividade_regiao ->", pr)

falta = parse_produtos_falta(produtos_falta_payload)
assert falta[0]["em_falta"] == 2
print("OK: parse_produtos_falta ->", falta)

ops = parse_produtividade_operador(prod_operador_payload, 8, "Reg Bolsas")
assert len(ops) == 1, "Filtro de quantidade > 0 deveria remover o operador zerado"
assert ops[0]["operador_id"] == "09524025"
print("OK: parse_produtividade_operador (filtro aplicado) ->", ops)

print("\n== Testando gravação no banco ==")
if os.path.exists(DB_TESTE):
    os.remove(DB_TESTE)

db.init_db()
db.insert_resumo_tarefa(tarefa)
db.insert_resumo_trabalho(trabalho)
db.insert_produtividade_regiao(pr)
db.insert_produtos_falta(falta)
db.insert_produtividade_operador(ops)
db.log_coleta(sucesso=True, detalhe="teste offline")

snap = db.get_latest_snapshot("resumo_tarefa")
assert len(snap) == 2
print("OK: get_latest_snapshot(resumo_tarefa) ->", snap)

status = db.get_last_collection_status()
assert status["sucesso"] == 1
print("OK: get_last_collection_status ->", status)


# =========================================================================
# Seção 5.2 — a contagem de pedidos não pode vazar dado de cliente
# =========================================================================
print("\n== Testando descarte de PII no parser de atribuições ==")

# Payload no formato do endpoint de detalhe, com os campos de cliente que
# ele realmente devolve. O parser tem que ignorar todos.
atribuicoes_payload = {
    "objects": [
        {
            "id": 884412,
            "status": "Complete",
            "operator": {"common": {"operatorIdentifier": "09524025"}},
            "customerInfo": {
                "name": "SUPERMERCADO EXEMPLO LTDA",
                "address": "RUA DAS FLORES 1234, SAO PAULO SP",
                "customerNumber": "12345678000199",
            },
            "region": {"number": 8, "name": "Reg Bolsas"},
        },
        {
            "id": 884413,
            "status": "In Progress",
            "operator": {"common": {"operatorIdentifier": "09524025"}},
            "customerInfo": {"name": "MERCADINHO TESTE", "customerNumber": "98765432000111"},
            "region": {"number": 8, "name": "Reg Bolsas"},
        },
        # Sem operador: não dá para atribuir, tem que ser ignorada.
        {"id": 884414, "status": "Available", "operator": {"common": {}}},
    ],
    "count": 3,
}

pedidos = parse_atribuicoes_sem_pii(atribuicoes_payload, 8, "Reg Bolsas")
assert len(pedidos) == 2, f"Esperava 2 atribuições com operador, veio {len(pedidos)}"

# O contrato é a allowlist: exatamente estas chaves, nem uma a mais.
esperado = {"region_number", "region_name", "operador_id", "pedido_ref", "status"}
for registro in pedidos:
    assert set(registro) == esperado, f"Chaves inesperadas: {set(registro) - esperado}"

# E a verificação que importa de verdade: nenhum fragmento de PII pode
# aparecer em lugar nenhum da saída, nem dentro de um valor.
import json as _json
saida = _json.dumps(pedidos, ensure_ascii=False)
for proibido in ("SUPERMERCADO", "RUA DAS FLORES", "12345678000199",
                 "MERCADINHO", "98765432000111", "customerInfo",
                 "customerNumber", "address"):
    assert proibido not in saida, f"VAZAMENTO DE PII: '{proibido}' sobreviveu ao parser"
print("OK: parse_atribuicoes_sem_pii — nenhum campo de cliente sobreviveu ->", pedidos)

db.insert_pedidos_operador(pedidos)
# Regravar a mesma coleta não pode inflar a contagem.
db.insert_pedidos_operador(pedidos)
hoje_iso = db._now()[:10]
assert db.get_pedidos_dia(8, hoje_iso) == 2, "Coleta repetida duplicou pedidos"
print("OK: pedidos não duplicam entre coletas ->", db.get_pedidos_dia(8, hoje_iso))


# =========================================================================
# Seção 5.1 — agregações do painel histórico
# =========================================================================
# O ponto crítico: os contadores do VoiceLink são ACUMULADOS. Somar os
# snapshots de um dia multiplicaria o total pelo número de coletas, então
# os testes abaixo usam números em que somar dá um resultado bem
# diferente de pegar o máximo — se alguém trocar MAX por SUM, quebra.
print("\n== Testando agregações do painel histórico ==")

REGIAO_TESTE = 99  # região fictícia, para não colidir com os dados acima


def _snapshot_regiao(ts, quantidade, taxa, tempo, meta=1350):
    with db.get_connection() as conn:
        conn.execute(
            _text(
                """INSERT INTO produtividade_regiao
               (captured_at, region_number, region_name, quantidade_total,
                produtividade_atual, numero_operadores, pct_meta, tempo_total, meta)
               VALUES (:captured_at, :region_number, :region_name, :quantidade_total,
                       :produtividade_atual, :numero_operadores, :pct_meta,
                       :tempo_total, :meta)"""
            ),
            {"captured_at": ts, "region_number": REGIAO_TESTE,
             "region_name": "Reg Teste", "quantidade_total": quantidade,
             "produtividade_atual": taxa, "numero_operadores": 2,
             "pct_meta": taxa / meta * 100, "tempo_total": tempo, "meta": meta},
        )


def _snapshot_operador(ts, operador, quantidade, taxa, tempo, meta=1350):
    with db.get_connection() as conn:
        conn.execute(
            _text(
                """INSERT INTO produtividade_operador
               (captured_at, region_number, region_name, operador_id, quantidade,
                tempo_total, meta, produtividade_real, pct_meta)
               VALUES (:captured_at, :region_number, :region_name, :operador_id,
                       :quantidade, :tempo_total, :meta, :produtividade_real,
                       :pct_meta)"""
            ),
            {"captured_at": ts, "region_number": REGIAO_TESTE,
             "region_name": "Reg Teste", "operador_id": operador,
             "quantidade": quantidade, "tempo_total": tempo, "meta": meta,
             "produtividade_real": taxa, "pct_meta": taxa / meta * 100},
        )


# Dia 20: contador subindo 500 -> 1500 -> 2400 ao longo de 3 horas.
_snapshot_regiao("2026-08-20 08:30:00", 500, 500.0, "01:00:00")
_snapshot_regiao("2026-08-20 09:30:00", 1500, 750.0, "02:00:00")
_snapshot_regiao("2026-08-20 10:30:00", 2400, 800.0, "03:00:00")
# Dia 21, mais curto.
_snapshot_regiao("2026-08-21 08:30:00", 400, 400.0, "01:00:00")
_snapshot_regiao("2026-08-21 09:30:00", 1000, 500.0, "02:00:00")

# Operador A termina o dia com 1400; operador B com 1000.
_snapshot_operador("2026-08-20 08:30:00", "A001", 300, 300.0, "01:00:00")
_snapshot_operador("2026-08-20 09:30:00", "A001", 900, 450.0, "02:00:00")
_snapshot_operador("2026-08-20 10:30:00", "A001", 1400, 466.67, "03:00:00")
_snapshot_operador("2026-08-20 08:30:00", "B002", 200, 200.0, "01:00:00")
_snapshot_operador("2026-08-20 09:30:00", "B002", 600, 300.0, "02:00:00")
_snapshot_operador("2026-08-20 10:30:00", "B002", 1000, 333.33, "03:00:00")

datas = db.get_datas_disponiveis(REGIAO_TESTE)
assert datas == ["2026-08-20", "2026-08-21"], datas
print("OK: get_datas_disponiveis ->", datas)

dia = db.get_totais_regiao_dia(REGIAO_TESTE, "2026-08-20")
assert dia["quantidade"] == 2400, (
    f"Total do dia deveria ser o MAX (2400), veio {dia['quantidade']} "
    "— se veio 4400, alguém somou os snapshots acumulados"
)
assert dia["produtividade_atual"] == 800.0, "A taxa tem que vir do último snapshot"
print("OK: get_totais_regiao_dia -> quantidade=%s taxa=%s" % (dia["quantidade"], dia["produtividade_atual"]))

operadores_dia = db.get_operadores_do_dia(REGIAO_TESTE, "2026-08-20")
assert len(operadores_dia) == 2, operadores_dia
por_id = {o["operador_id"]: o for o in operadores_dia}
assert por_id["A001"]["quantidade"] == 1400, por_id["A001"]
assert por_id["B002"]["quantidade"] == 1000, por_id["B002"]
assert por_id["A001"]["produtividade_real"] == 466.67, "Taxa tem que ser a do fechamento"
assert por_id["A001"]["pedidos"] is None, "Sem coleta de pedidos, a coluna fica vazia"
assert operadores_dia[0]["operador_id"] == "A001", "Deveria vir ordenado por quantidade"
print("OK: get_operadores_do_dia ->", [(o["operador_id"], o["quantidade"]) for o in operadores_dia])

serie = db.get_serie_por_dia(REGIAO_TESTE, "2026-08")
assert [(s["dia"], s["quantidade"]) for s in serie] == [
    ("2026-08-20", 2400), ("2026-08-21", 1000)
], serie
print("OK: get_serie_por_dia ->", [(s["dia"], s["quantidade"]) for s in serie])

mes = db.get_totais_regiao_mes(REGIAO_TESTE, "2026-08")
assert mes["quantidade"] == 3400, f"Mês = soma dos dias (2400+1000), veio {mes['quantidade']}"
# 3h no dia 20 + 2h no dia 21 = 5 horas-operador; 3400/5 = 680/h.
assert abs(mes["horas"] - 5.0) < 0.01, mes["horas"]
assert abs(mes["produtividade_atual"] - 680.0) < 0.01, (
    f"Produtividade do mês é ponderada por hora (680), veio {mes['produtividade_atual']}"
)
print("OK: get_totais_regiao_mes ->", mes)

horas = db.get_acumulado_por_hora(REGIAO_TESTE, "2026-08-20")
assert [(h["hora"], h["acumulado"]) for h in horas] == [(8, 500), (9, 1500), (10, 2400)], horas

series = db.derivar_series_horarias(horas)
assert len(series) == 24
por_hora = {s["hora"]: s for s in series}
assert por_hora[8]["itens"] == 500, por_hora[8]
assert por_hora[9]["itens"] == 1000, f"Hora 9 produziu 1500-500=1000, veio {por_hora[9]['itens']}"
assert por_hora[10]["itens"] == 900, f"Hora 10 produziu 2400-1500=900, veio {por_hora[10]['itens']}"
assert por_hora[7]["itens"] == 0 and por_hora[11]["itens"] == 0, "Fora do turno = zero"
assert sum(s["itens"] for s in series) == 2400, "A soma das horas fecha com o total do dia"

# O ponto que mais importa: produtividade tem que ser por HORA-OPERADOR,
# não a vazão da região. Os snapshots de teste acumulam 1h de tempo de
# operador por hora de relógio, então na hora 9 foram 1000 itens em 1
# hora-operador = 1000/h. Se alguém voltar a plotar a vazão bruta, este
# teste continua passando aqui — mas o de baixo, com 2 operadores, não.
assert por_hora[9]["horas_operador"] == 1.0, por_hora[9]
assert por_hora[9]["produtividade"] == 1000.0, por_hora[9]
print("OK: derivar_series_horarias -> itens por hora 8,9,10 =",
      [por_hora[h]["itens"] for h in (8, 9, 10)])

# Dois operadores trabalhando a hora inteira: 2 horas-operador para 1
# hora de relógio. 1200 itens no total = 600 por hora-operador, que é o
# número que dá para comparar com a meta.
dois_operadores = db.derivar_series_horarias([
    {"hora": 8, "acumulado": 0, "tempo_acumulado": "00:00:00"},
    {"hora": 9, "acumulado": 1200, "tempo_acumulado": "02:00:00"},
])
assert dois_operadores[9]["itens"] == 1200
assert dois_operadores[9]["horas_operador"] == 2.0
assert dois_operadores[9]["produtividade"] == 600.0, (
    f"Produtividade tem que ser por hora-operador (600), veio "
    f"{dois_operadores[9]['produtividade']} — 1200 seria a vazão da região, "
    "que não é comparável com a meta por operador"
)
print("OK: produtividade é por hora-operador ->",
      f"{dois_operadores[9]['itens']:.0f} itens / "
      f"{dois_operadores[9]['horas_operador']:.0f}h-op = "
      f"{dois_operadores[9]['produtividade']:.0f}/h-op")

# Contador que zera no meio do dia (virada de turno) não pode gerar um
# valor negativo no gráfico.
reset = db.derivar_series_horarias([
    {"hora": 8, "acumulado": 1000, "tempo_acumulado": "02:00:00"},
    {"hora": 9, "acumulado": 200, "tempo_acumulado": "00:30:00"},
])
assert reset[9]["itens"] == 0, f"Delta negativo deveria virar 0, veio {reset[9]['itens']}"
assert reset[9]["produtividade"] == 0
print("OK: derivar_series_horarias trata reset de contador")

# Hora com itens mas sem tempo registrado não pode dividir por zero.
sem_tempo = db.derivar_series_horarias([
    {"hora": 8, "acumulado": 500, "tempo_acumulado": "00:00:00"},
])
assert sem_tempo[8]["produtividade"] == 0.0, "Divisão por zero não pode escapar"
print("OK: hora sem tempo-operador não divide por zero")

vazio_24h = db.derivar_series_horarias([])
assert len(vazio_24h) == 24 and all(s["itens"] == 0 for s in vazio_24h), \
    "Dia sem dados = 24 horas zeradas"

assert abs(db.parse_tempo_total("12:46:23") - 12.7730) < 0.001
assert db.parse_tempo_total("") == 0.0
assert db.parse_tempo_total(None) == 0.0
print("OK: parse_tempo_total ->", db.parse_tempo_total("12:46:23"))

# Região sem nenhuma coleta não pode explodir — tem que devolver vazio.
assert db.get_datas_disponiveis(12345) == []
assert db.get_totais_regiao_dia(12345, "2026-08-20") is None
assert db.get_totais_regiao_mes(12345, "2026-08") is None
assert db.get_operadores_do_dia(12345, "2026-08-20") == []
print("OK: região sem dados devolve vazio em vez de quebrar")


# =========================================================================
# Avatares (seção 5.3 — v1 sem fotos)
# =========================================================================
print("\n== Testando avatares por iniciais ==")
import ui

uri_a = ui.avatar_data_uri("09524025")
assert uri_a.startswith("data:image/svg+xml;base64,")
assert uri_a == ui.avatar_data_uri("09524025"), (
    "O mesmo operador tem que gerar sempre o mesmo avatar — se mudar entre "
    "chamadas, alguém trocou o CRC32 pelo hash() do Python, que muda a cada processo"
)
assert ui.avatar_data_uri("A001") != uri_a
assert ui.avatar_data_uri("") .startswith("data:image/svg+xml;base64,"), "ID vazio não pode quebrar"
print("OK: avatar_data_uri -> estável, único por operador e tolerante a ID vazio")


# Logo do cabeçalho: presente ou não, a tela tem que subir.
print("\n== Testando logo do cabeçalho ==")
import config as _config

uri_logo = ui.logo_data_uri()
if uri_logo:
    assert uri_logo.startswith("data:image/"), uri_logo[:40]
    print(f"OK: logo embutida ({len(uri_logo) / 1024:.0f} KB de data URI)")
else:
    print("OK: sem logo.png — cabeçalho cai para só o título")

# Arquivo ausente não pode derrubar o painel.
ui.logo_data_uri.cache_clear()
_caminho_real = _config.LOGO_PATH
_config.LOGO_PATH = os.path.join(tempfile.gettempdir(), "logo_que_nao_existe.png")
assert ui.logo_data_uri() == "", "Logo ausente tem que devolver vazio, não estourar"

# Arquivo ilegível/corrompido também não.
_quebrado = os.path.join(tempfile.gettempdir(), "logo_quebrado.png")
with open(_quebrado, "wb") as _f:
    _f.write(b"isto nao e um png")
ui.logo_data_uri.cache_clear()
_config.LOGO_PATH = _quebrado
assert ui.logo_data_uri().startswith("data:image/png"), (
    "Arquivo corrompido vira data URI mesmo assim — quem decide se "
    "renderiza é o navegador; o importante é o Python não quebrar"
)
_config.LOGO_PATH = _caminho_real
ui.logo_data_uri.cache_clear()
print("OK: logo ausente ou corrompida não derruba a tela")


# =========================================================================
# Retenção de histórico (limpar_historico_antigo)
# =========================================================================
print("\n== Testando limpar_historico_antigo (retenção) ==")

from datetime import datetime as _dt              # noqa: E402

_ts_antigo = "2020-01-01 10:00:00"
_ts_novo = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
_snapshot_regiao(_ts_antigo, 100, 100.0, "01:00:00")
_snapshot_regiao(_ts_novo, 200, 200.0, "01:00:00")

_apagados = db.limpar_historico_antigo(dias=60)
assert _apagados.get("produtividade_regiao", 0) == 1, (
    f"Apenas o snapshot de 2020 deveria sair; veio {_apagados}"
)
with db.get_connection() as _conn:
    _sobras = _conn.execute(
        _text("SELECT captured_at FROM produtividade_regiao ORDER BY captured_at")
    ).fetchall()
_ts_sobras = [r._asdict()["captured_at"] for r in _sobras]
assert _ts_antigo not in _ts_sobras, "O snapshot antigo tinha que ter sido apagado"
assert _ts_novo in _ts_sobras, "O snapshot recente não pode ser apagado"
print("OK: limpar_historico_antigo apaga só o que tem mais de 60 dias")


# =========================================================================
# Auth compartilhado (tela de login do dashboard)
# =========================================================================
# O login é validado contra o VoiceLink na vida real; aqui o requests é
# simulado para provar a lógica sem rede.
import auth          # noqa: E402
import requests      # noqa: E402
from unittest import mock  # noqa: E402

print("\n== Testando auth.login_voicelink (requests simulado) ==")


class _RespFake:
    def __init__(self, texto="", http_ok=True):
        self.text = texto
        self._http_ok = http_ok

    def raise_for_status(self):
        if not self._http_ok:
            raise requests.RequestException("HTTP 500")


class _SessionFake:
    def __init__(self, texto="", http_ok=True):
        self._texto, self._http_ok = texto, http_ok
        self.headers = {}
        self.payload = None

    def post(self, url, **kwargs):
        self.url, self.payload = url, kwargs.get("data")
        return _RespFake(self._texto, self._http_ok)

    def close(self):
        pass


def _patcheado(texto="", http_ok=True):
    return mock.patch(
        "auth.requests.Session",
        mock.Mock(side_effect=lambda: _SessionFake(texto, http_ok)),
    )


# Login válido: página sem o texto de erro -> sessão devolvida, com as
# credenciais indo no POST (e não guardadas em nenhum outro lugar).
with _patcheado(texto="<html>página normal do VoiceLink</html>"):
    sessao = auth.login_voicelink("usuario", "senha")
assert sessao is not None, "Login válido deveria devolver a sessão"
assert sessao.payload == {"j_username": "usuario", "j_password": "senha"}, (
    "As credenciais digitadas vão no POST do login — nada além disso"
)
print("OK: login válido devolve a sessão com as credenciais no POST")

# Credencial errada: o VoiceLink devolve a página de erro -> None.
with _patcheado(texto="Nome do usuário ou senha inválida"):
    assert auth.login_voicelink("usuario", "senha_errada") is None
print("OK: página de erro do VoiceLink -> None (não autentica)")

# Falha de conexão/HTTP -> None (não libera o painel).
with _patcheado(http_ok=False):
    assert auth.login_voicelink("usuario", "senha") is None
print("OK: falha de conexão -> None (não autentica)")

# Credenciais vazias não chegam nem a sair do processo.
with _patcheado():
    assert auth.login_voicelink("", "") is None
    assert auth.login_voicelink("usuario", "") is None
print("OK: credenciais vazias -> None sem chamada de rede")

print("\n✅ Todos os testes offline passaram.")
