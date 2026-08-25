"""
Painel Histórico por Região (seção 5.1 da especificação).

Um painel por região, no estilo dos painéis de referência da PepsiCo:

    filtro ano -> mês -> dia
    Top 5 Separação  |  Top 5 Produtividade
    4 KPIs (linha Dia) + 4 KPIs (linha Mês), comparados com a meta
    Separação/Dia (mês)  |  Produtividade/Dia (hora a hora)

Como todas as telas, esta só LÊ o banco — quem fala com o VoiceLink é o
collector.py, rodando em outro processo.
"""
import os
import sys
from datetime import date

import pandas as pd
import streamlit as st

# A pasta pages/ não está no sys.path quando o Streamlit executa a página,
# então os módulos da raiz do projeto precisam ser alcançáveis daqui.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config          # noqa: E402
import database as db  # noqa: E402
import presentation    # noqa: E402
import ui              # noqa: E402

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

ui.configurar_pagina("Histórico por Região — Control Tower", "📊")

# Mesmo intervalo de releitura do slider da tela de Tempo Real — o
# session_state é compartilhado entre as páginas da mesma sessão.
intervalo_dados = st.session_state.get(
    "ct_intervalo_dados", config.DASHBOARD_REFRESH_SECONDS
)
presentation.tick("historico", intervalo_dados * 1000)

modo_tv = presentation.ativo()
if modo_tv:
    ui.esconder_navegacao()
    ui.css_modo_apresentacao()


# --- Seleção da região ----------------------------------------------------
# 0 = "Todas as Regiões" (as regiões reais vão de 6 a 9, então não
# colide). No modo apresentação quem manda é a rotação; no estático, o
# usuário — com a visão consolidada como primeira opção.
TODAS = 0
if modo_tv:
    regiao_num = presentation.regiao_alvo()
    if regiao_num not in config.REGIONS:
        regiao_num = next(iter(config.REGIONS))
else:
    presentation.controles_sidebar()
    with st.sidebar:
        st.divider()
        st.caption("REGIÃO")
        regiao_num = st.radio(
            "Região", options=[TODAS, *config.REGIONS.keys()],
            format_func=lambda n: "Todas as Regiões" if n == TODAS else config.REGIONS[n],
            label_visibility="collapsed",
        )

if regiao_num == TODAS:
    regiao_nome = "Todas as Regiões"
    regioes_alvo = list(config.REGIONS.keys())
else:
    regiao_nome = config.REGIONS[regiao_num]
    regioes_alvo = [regiao_num]

if modo_tv:
    presentation.barra_apresentacao(regiao_nome)


# --- Filtro de data (ano -> mês -> dia) -----------------------------------
# Datas disponíveis: na visão "Todas as Regiões", a união dos dias que
# têm dados em QUALQUER região.
if regiao_num == TODAS:
    datas = sorted({
        dia
        for r in regioes_alvo
        for dia in db.get_datas_disponiveis(r)
    })
else:
    datas = db.get_datas_disponiveis(regiao_num)

ui.cabecalho(f"Painel de Produtividade — {regiao_nome}")

if not datas:
    st.info(
        f"Ainda não há dados coletados para **{regiao_nome}**.\n\n"
        "O histórico começa a existir a partir do momento em que o "
        "`collector.py` entra no ar — não é possível reconstruir dias "
        "anteriores ao início da coleta. Deixe o coletor rodando e este "
        "painel se preenche sozinho."
    )
    st.stop()

# As opções de cada nível saem dos dias que realmente têm dados, então é
# impossível escolher uma data vazia (seção 6 da especificação).
dias_por_ano_mes = {}
for d in datas:
    dias_por_ano_mes.setdefault(d[:4], {}).setdefault(d[5:7], []).append(d)

anos = sorted(dias_por_ano_mes, reverse=True)
hoje = date.today().isoformat()

def _abas(rotulo: str, opcoes: list, padrao, chave: str, formatar=str):
    """Abas clicáveis, como nos painéis de referência.

    st.segmented_control em modo single permite desmarcar a opção ativa
    (devolvendo None); como um filtro de data sem valor não faz sentido,
    a seleção vazia volta para o padrão.
    """
    if len(opcoes) == 1:
        return opcoes[0]
    escolha = st.segmented_control(
        rotulo, opcoes, default=padrao, format_func=formatar,
        key=chave, label_visibility="collapsed",
    )
    return escolha if escolha is not None else padrao


if modo_tv:
    # Na TV não há quem clique num filtro: mostra sempre o dia mais
    # recente que tem dado (hoje, se o coletor estiver rodando).
    dia_sel = datas[-1]
    ano_sel, mes_sel = dia_sel[:4], dia_sel[5:7]
else:
    ano_sel = _abas("Ano", anos, anos[0], f"ano_{regiao_num}")

    meses = sorted(dias_por_ano_mes[ano_sel], reverse=True)
    mes_sel = _abas(
        "Mês", meses, meses[0], f"mes_{regiao_num}_{ano_sel}",
        formatar=lambda m: MESES[int(m) - 1],
    )

    dias = sorted(dias_por_ano_mes[ano_sel][mes_sel], reverse=True)
    # Default: o dia atual se ele tiver dados, senão o mais recente — que
    # na prática é D-1 quando o painel é aberto antes da coleta do dia.
    dia_sel = _abas(
        "Dia", dias, hoje if hoje in dias else dias[0],
        f"dia_{regiao_num}_{ano_sel}_{mes_sel}",
        formatar=lambda d: d[8:10],
    )

ano_mes = f"{ano_sel}-{mes_sel}"
rotulo_dia = f"{dia_sel[8:10]}/{dia_sel[5:7]}/{dia_sel[:4]}"
st.markdown(
    f'<p class="ct-sub">{rotulo_dia} · acumulado de {MESES[int(mes_sel) - 1]} '
    f"de {ano_sel}</p>",
    unsafe_allow_html=True,
)
st.divider()


# --- Dados do dia e do mês ------------------------------------------------
# Na visão "Todas as Regiões" cada métrica é consolidada somando as
# regiões, com a mesma semântica do banco: contadores acumulados por
# região viram o total do conjunto, e a taxa é itens ÷ horas-operador
# somados (ponderada, não média de taxas). A meta fica vazia — goalRate
# é por região, e inventar uma meta consolidada seria mentir no card.
if regiao_num == TODAS:
    operadores = [
        op
        for r in regioes_alvo
        for op in db.get_operadores_do_dia(r, dia_sel)
    ]

    parciais_dia = [t for r in regioes_alvo
                    for t in [db.get_totais_regiao_dia(r, dia_sel)] if t]
    if parciais_dia:
        qtd_dia = sum(t["quantidade"] or 0 for t in parciais_dia)
        horas_dia = sum(db.parse_tempo_total(t["tempo_total"]) for t in parciais_dia)
        totais_dia = {
            "quantidade": qtd_dia,
            "produtividade_atual": (qtd_dia / horas_dia) if horas_dia > 0 else 0.0,
            "meta": None,
        }
    else:
        totais_dia = None

    parciais_mes = [t for r in regioes_alvo
                    for t in [db.get_totais_regiao_mes(r, ano_mes)] if t]
    if parciais_mes:
        qtd_mes = sum(t["quantidade"] or 0 for t in parciais_mes)
        horas_mes = sum(t["horas"] or 0 for t in parciais_mes)
        totais_mes = {
            "quantidade": qtd_mes,
            "horas": horas_mes,
            "produtividade_atual": (qtd_mes / horas_mes) if horas_mes > 0 else 0.0,
            "meta": None,
            "dias_com_dado": max(t["dias_com_dado"] for t in parciais_mes),
        }
    else:
        totais_mes = None

    por_dia = {}
    for r in regioes_alvo:
        for d in db.get_serie_por_dia(r, ano_mes):
            por_dia[d["dia"]] = por_dia.get(d["dia"], 0) + (d["quantidade"] or 0)
    serie_dias = [{"dia": dia, "quantidade": total}
                  for dia, total in sorted(por_dia.items())]
else:
    operadores = db.get_operadores_do_dia(regiao_num, dia_sel)
    totais_dia = db.get_totais_regiao_dia(regiao_num, dia_sel)
    totais_mes = db.get_totais_regiao_mes(regiao_num, ano_mes)
    serie_dias = db.get_serie_por_dia(regiao_num, ano_mes)

tem_pedidos = db.tem_dados_de_pedidos()
pedidos_dia = sum(db.get_pedidos_dia(r, dia_sel) for r in regioes_alvo) if tem_pedidos else None
pedidos_mes = sum(db.get_pedidos_mes(r, ano_mes) for r in regioes_alvo) if tem_pedidos else None

meta_regiao = (totais_dia or {}).get("meta") or (totais_mes or {}).get("meta")


# --- Top 5 lado a lado ----------------------------------------------------
def tabela_top5(dados: list, titulo: str, config_colunas: dict):
    st.markdown(f'<p class="ct-rowlabel">{titulo}</p>', unsafe_allow_html=True)
    if not dados:
        st.caption("Sem operadores com produção neste dia.")
        return
    tabela = pd.DataFrame(dados)
    # Nome legível no lugar do ID numérico; o avatar usa as iniciais do
    # nome (mesma paleta do avatar por ID).
    tabela.insert(0, "operador_nome", tabela["operador_id"].map(ui.nome_operador))
    tabela.insert(0, "avatar", tabela["operador_nome"].map(ui.avatar_data_uri))
    st.dataframe(
        tabela, hide_index=True, width="stretch",
        column_config=config_colunas,
        column_order=list(config_colunas.keys()),
    )


col_sep, col_prod = st.columns(2)

with col_sep:
    top_separacao = sorted(
        operadores, key=lambda o: o["quantidade"] or 0, reverse=True
    )[:5]
    colunas = {
        "avatar": st.column_config.ImageColumn("", width="small"),
        "operador_nome": st.column_config.TextColumn("Operador"),
        "quantidade": st.column_config.NumberColumn("Qtda Total", format="%d"),
    }
    if tem_pedidos:
        colunas["pedidos"] = st.column_config.NumberColumn("Qtda Pedido", format="%d")
    tabela_top5(top_separacao, "TOP 5 — SEPARAÇÃO", colunas)

with col_prod:
    top_produtividade = sorted(
        operadores, key=lambda o: o["produtividade_real"] or 0, reverse=True
    )[:5]
    tabela_top5(
        top_produtividade, "TOP 5 — PRODUTIVIDADE",
        {
            "avatar": st.column_config.ImageColumn("", width="small"),
            "operador_nome": st.column_config.TextColumn("Operador"),
            "produtividade_real": st.column_config.NumberColumn(
                "Produtividade", format="%.0f /h"
            ),
        },
    )

if not tem_pedidos:
    st.caption(
        "A coluna **Qtda Pedido** aparece quando a coleta de pedidos por "
        "operador estiver ligada (`COLLECT_ORDER_COUNTS=true`). Veja a "
        "seção 5.2 do README antes de ligar — o endpoint envolvido "
        "trafega dados de cliente."
    )

st.divider()


# --- 4 KPIs x 2 linhas (Dia / Mês) ----------------------------------------
def linha_de_kpis(rotulo: str, quantidade, pedidos, taxa, meta):
    """Uma linha de 4 cards: Qtd Separada · Qtda Pedidos · Un/Pedido ·
    Separado/Hora. Só a última tem meta no VoiceLink — as outras três
    ficam sem a linha de meta em vez de ganhar uma inventada."""
    st.markdown(f'<p class="ct-rowlabel">{rotulo}</p>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        ui.card_kpi("Qtd Separada", quantidade, unidade="itens")
    with c2:
        ui.card_kpi("Qtda Pedidos", pedidos,
                    rodape="" if pedidos is not None else "coleta desligada")
    with c3:
        por_pedido = (quantidade / pedidos) if (pedidos and quantidade) else None
        ui.card_kpi("Itens/Pedido", por_pedido, casas=1)
    with c4:
        ui.card_kpi("Separado/Hora", taxa, unidade="/h", casas=0, meta=meta)


if totais_dia:
    linha_de_kpis(
        "DIA", totais_dia["quantidade"], pedidos_dia,
        totais_dia["produtividade_atual"], meta_regiao,
    )
else:
    st.caption("Sem coleta neste dia.")

st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

if totais_mes:
    linha_de_kpis(
        "MÊS", totais_mes["quantidade"], pedidos_mes,
        totais_mes["produtividade_atual"], meta_regiao,
    )

st.divider()


# --- Os dois gráficos -----------------------------------------------------
g1, g2 = st.columns(2)

with g1:
    if serie_dias:
        dias_do_mes = [int(d["dia"][8:10]) for d in serie_dias]
        quantidades = [d["quantidade"] or 0 for d in serie_dias]
        st.plotly_chart(
            ui.grafico_area(
                dias_do_mes, quantidades,
                titulo=f"Separação/Dia — {MESES[int(mes_sel) - 1]}",
                rotulo_x="Dia do mês", rotulo_y="Itens separados",
                ampliar=modo_tv,
            ),
            width="stretch", key="grafico_separacao_dia",
        )
    else:
        st.caption("Sem dados no mês selecionado.")

with g2:
    # Plota itens por HORA-OPERADOR, que é a mesma unidade da meta — e não
    # a vazão da região, que com vários operadores seria várias vezes
    # maior e faria a linha da meta parecer baixa. Na visão "Todas as
    # Regiões", itens e horas-operador de cada hora somam entre regiões
    # (a produtividade continua sendo itens ÷ hora-operador).
    if regiao_num == TODAS:
        itens_hora = [0.0] * 24
        horas_hora = [0.0] * 24
        for r in regioes_alvo:
            for h in db.derivar_series_horarias(
                db.get_acumulado_por_hora(r, dia_sel)
            ):
                itens_hora[h["hora"]] += h["itens"]
                horas_hora[h["hora"]] += h["horas_operador"]
        horas = [
            {
                "hora": h,
                "itens": itens_hora[h],
                "horas_operador": horas_hora[h],
                "produtividade": (itens_hora[h] / horas_hora[h])
                if horas_hora[h] > 0 else 0.0,
            }
            for h in range(24)
        ]
    else:
        horas = db.derivar_series_horarias(
            db.get_acumulado_por_hora(regiao_num, dia_sel)
        )
    st.plotly_chart(
        ui.grafico_area(
            [h["hora"] for h in horas], [h["produtividade"] for h in horas],
            titulo=f"Produtividade/Dia — {rotulo_dia}",
            rotulo_x="Hora", rotulo_y="Itens/hora-operador",
            meta=meta_regiao,
            tickvals=list(range(0, 24, 2)),
            ticktext=[f"{h:02d}h" for h in range(0, 24, 2)],
            ampliar=modo_tv,
        ),
        width="stretch", key="grafico_produtividade_hora",
    )

st.caption(
    "Cada hora é a diferença entre acumulados consecutivos do contador do "
    "VoiceLink; horas fora do turno aparecem zeradas. A produtividade está "
    "em itens por **hora-operador** — a mesma unidade da meta, e não a "
    "vazão total da região."
)
