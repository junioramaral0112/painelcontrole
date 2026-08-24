"""
Teste de fumaça das telas, usando o AppTest do próprio Streamlit.

Os testes do test_offline.py cobrem os parsers e as queries; estes aqui
cobrem o que falta: se as telas realmente executam de ponta a ponta sem
estourar exceção. Sem isto, um erro de digitação num nome de coluna só
apareceria quando alguém abrisse o painel na TV.

Roda contra o banco de demonstração (seed_demo.py), então precisa dele:

    python seed_demo.py
    python test_ui.py
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = os.path.dirname(os.path.abspath(__file__))
DB_DEMO = os.path.join(RAIZ, "control_tower_demo.db")

if not os.path.exists(DB_DEMO):
    print("Banco de demonstração não encontrado. Rode antes: python seed_demo.py")
    raise SystemExit(1)

os.environ["DB_PATH"] = DB_DEMO
# Mesmo cuidado do test_offline: os testes de UI rodam contra o SQLite
# demo, nunca contra um DATABASE_URL de produção.
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, RAIZ)

from streamlit.testing.v1 import AppTest  # noqa: E402

TEMPO_LIMITE = 60


def executar(caminho: str, estado: dict = None) -> AppTest:
    """Renderiza uma tela já autenticada.

    O portão de login bloqueia as telas sem `ct_autenticado` no
    session_state; como estes testes cobrem o CONTEÚDO das telas, o
    estado de autenticado entra por padrão. O portão em si tem o seu
    próprio teste no fim do arquivo.
    """
    app = AppTest.from_file(caminho, default_timeout=TEMPO_LIMITE)
    app.session_state["ct_autenticado"] = True
    for chave, valor in (estado or {}).items():
        app.session_state[chave] = valor
    app.run()
    if app.exception:
        for erro in app.exception:
            print(f"\n!! Exceção em {caminho}:\n{erro.value}\n{erro.stack_trace}")
        raise AssertionError(f"{caminho} levantou exceção ao renderizar")
    return app


print("== Tela de Tempo Real ==")
tempo_real = executar("app.py")
assert not tempo_real.error, tempo_real.error
print(f"OK: app.py renderizou · {len(tempo_real.dataframe)} tabelas, "
      f"{len(tempo_real.metric)} métricas")

print("\n== Painel Histórico por Região ==")
historico = executar("pages/1_Historico.py")
assert not historico.error, historico.error
# 2 tabelas Top 5 + 8 cards de KPI (4 do dia, 4 do mês) + 2 gráficos.
assert len(historico.dataframe) == 2, (
    f"Esperava as 2 tabelas Top 5, vieram {len(historico.dataframe)}"
)
print(f"OK: pages/1_Historico.py renderizou · {len(historico.dataframe)} tabelas Top 5")

# O painel tem que sair de pé para TODAS as regiões, inclusive as que
# tiverem pouco dado.
import config  # noqa: E402

for numero, nome in config.REGIONS.items():
    tela = executar("pages/1_Historico.py", {"ct_regiao_alvo": numero,
                                             "ct_modo_apresentacao": True})
    assert not tela.error, f"{nome}: {tela.error}"
    print(f"OK: modo apresentação renderizou o painel de {nome}")

print("\n== Modo apresentação na tela de Tempo Real ==")
tv = executar("app.py", {"ct_modo_apresentacao": True})
assert not tv.error, tv.error
print("OK: app.py renderizou em modo apresentação")

print("\n== Painel de uma região sem nenhum dado ==")
# Região que não existe no banco: tem que mostrar o aviso da seção 6, não
# quebrar nem mostrar um painel zerado sem explicação.
vazio = executar("pages/1_Historico.py", {"ct_regiao_alvo": 6,
                                          "ct_modo_apresentacao": True})
assert not vazio.error
print("OK: região sem dados tratada sem exceção")

print("\n== Tela de login (sem autenticação) ==")
# O portão precisa segurar as DUAS páginas: páginas multi-page rodam
# scripts separados, e quem acertar a URL direto não pode ver dados.
portao = AppTest.from_file("app.py", default_timeout=TEMPO_LIMITE)
portao.run()
assert not portao.exception, portao.exception
assert len(portao.text_input) == 2, (
    f"Esperava os campos Usuário e Senha, vieram {len(portao.text_input)}"
)
from streamlit.proto.TextInput_pb2 import TextInput  # noqa: E402
assert portao.text_input[1].proto.type == TextInput.Type.PASSWORD, (
    "A senha precisa ser mascarada (type=password)"
)
assert len(portao.dataframe) == 0, "Nenhum dado pode aparecer antes do login"
print("OK: app.py bloqueado — formulário Usuário/Senha (senha mascarada), sem dados")

portao_h = AppTest.from_file("pages/1_Historico.py", default_timeout=TEMPO_LIMITE)
portao_h.run()
assert not portao_h.exception, portao_h.exception
assert len(portao_h.dataframe) == 0, "O Histórico também precisa bloquear sem login"
print("OK: pages/1_Historico.py bloqueado sem login")

print("\n✅ Todas as telas renderizaram sem exceção.")
