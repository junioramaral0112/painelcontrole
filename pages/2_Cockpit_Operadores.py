"""
Cockpit de Velocímetros — visão executiva por operador (Plotly).

Velocímetro individual por colaborador: ponteiro de 0 a 150% da meta
(arco vermelho <85%, amarelo 85-99,9%, verde >=100%) + mini-resumo
(Qtd Realizada, Tempo, Meta, Prod. Real).

Duas abas por setor:
  * 📦 Caixas & Caixas c/ Etiquetas -> Reg Caixas + Reg de caixas com etiquetas
  * 🛍️ Bolsas                        -> Reg Bolsas

Como as demais telas, esta só LÊ o banco (alimentado pelo coletor) e
respeita o slider "Tempo de atualização" da barra lateral.
"""
import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# A pasta pages/ não está no sys.path quando o Streamlit executa a página.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config          # noqa: E402
import database as db  # noqa: E402
import presentation    # noqa: E402
import ui              # noqa: E402

ui.configurar_pagina("Cockpit de Velocímetros — Control Tower", "🚀")

intervalo_dados = st.session_state.get(
    "ct_intervalo_dados", config.DASHBOARD_REFRESH_SECONDS
)
modo_tv = presentation.ativo()
if modo_tv:
    ui.esconder_navegacao()
    ui.css_modo_apresentacao()
else:
    # Esta página não participa da rotação de TV: o autorefresh respeita
    # apenas o slider da barra lateral.
    presentation.tick("cockpit", intervalo_dados * 1000)
    presentation.controles_sidebar()

# --- Cabeçalho ------------------------------------------------------------
col_titulo, col_badge = st.columns([3, 1])
with col_titulo:
    ui.cabecalho(
        "CONTROL TOWER — COCKPIT DE VELOCÍMETROS",
        "Produtividade individual por operador · atualização automática",
    )
with col_badge:
    st.markdown(ui.badge_ao_vivo(), unsafe_allow_html=True)

st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

# --- Dados -----------------------------------------------------------------
trabalho = pd.DataFrame(db.get_latest_snapshot("resumo_trabalho"))
prod_regiao = pd.DataFrame(db.get_latest_por_regiao("produtividade_regiao"))
operadores = pd.DataFrame(db.get_latest_snapshot("produtividade_operador"))

# --- KPIs no topo -----------------------------------------------------------
total_selecionado = trabalho["itens_selecionados"].sum() if not trabalho.empty else 0
total_restante = trabalho["itens_restantes"].sum() if not trabalho.empty else 0
operadores_ativos = len(operadores)

if not prod_regiao.empty:
    valores_meta = prod_regiao["pct_meta"].dropna()
    media_meta = valores_meta.mean() if not valores_meta.empty else None
    if media_meta is None:
        classe_meta, valor_meta = "", "—"
    else:
        if media_meta >= 100:
            classe_meta = "ct-kpi-bom"
        elif media_meta >= 85:
            classe_meta = "ct-kpi-medio"
        else:
            classe_meta = "ct-kpi-ruim"
        valor_meta = f"{media_meta:.1f}%"
else:
    classe_meta, valor_meta = "", "—"

k1, k2, k3, k4 = st.columns(4)
with k1:
    ui.card_kpi_topo("Itens Selecionados", ui._formatar(total_selecionado))
with k2:
    ui.card_kpi_topo("Itens Restantes", ui._formatar(total_restante))
with k3:
    ui.card_kpi_topo("Operadores Ativos", str(operadores_ativos))
with k4:
    ui.card_kpi_topo("Atingimento Médio da Meta", valor_meta, classe_meta)

st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

# --- Setores (abas) ---------------------------------------------------------
aba_caixas, aba_bolsas = st.tabs([
    "📦 Caixas & Caixas c/ Etiquetas",
    "🛍️ Bolsas",
])

SETORES = {
    "caixas": ("Reg Caixas", "Reg de caixas com etiquetas"),
    "bolsas": ("Reg Bolsas",),
}


def _velocimetro(pct_meta: float) -> go.Figure:
    """Gauge de 0 a 150% com arco vermelho/amarelo/verde.

    Estilo agulha clássica: a `bar` do Plotly é o ponteiro — fina
    (thickness 0.05) e grafite, apontando até o valor, em cima das
    faixas coloridas do arco. Sem a barra grossa de progresso, as cores
    e o ponteiro ganham o destaque.
    """
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=pct_meta,
        number={"suffix": "%", "font": {"size": 44, "color": "#0b0b0b"}},
        gauge={
            "axis": {"range": [0, 150], "tickmode": "linear", "tick0": 0,
                     "dtick": 25, "tickfont": {"size": 12}},
            "bar": {"color": "#263238", "thickness": 0.05},  # agulha grafite
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 84.9], "color": "#ef5350"},   # 🔴 abaixo da meta
                {"range": [85, 99.9], "color": "#ffb300"},  # 🟡 perto da meta
                {"range": [100, 150], "color": "#43a047"},  # 🟢 meta batida
            ],
        },
    ))
    fig.update_layout(
        height=230,
        margin=dict(l=20, r=20, t=35, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=ui.FONTE, color=ui.TINTA_MUDA),
    )
    return fig


def _card_operador(linha) -> None:
    """Card individual: título + velocímetro + mini-resumo."""
    nome = ui.nome_operador(linha["operador_id"])
    pct = float(linha["pct_meta"] or 0.0)
    with st.container(border=True):
        # Nome maior para leitura nítida em TV.
        st.markdown(
            f'<p style="font-weight:700;font-size:1.25rem;margin:0;">{nome}</p>'
            f'<p style="color:#898781;font-size:0.95rem;margin:0 0 6px;">'
            f'{linha["region_name"]}</p>',
            unsafe_allow_html=True,
        )
        st.plotly_chart(
            _velocimetro(pct),
            width="stretch", config={"displayModeBar": False},
            key=f"gauge_{linha['region_number']}_{linha['operador_id']}",
        )
        meta_txt = ui._formatar(linha["meta"], 0) if linha["meta"] else "—"
        prod_txt = (
            ui._formatar(linha["produtividade_real"], 0)
            if linha["produtividade_real"] is not None else "—"
        )
        # Rodapé ampliado: valores em negrito para destaque.
        st.markdown(
            '<div style="font-size:1.05rem;color:#0b0b0b;line-height:1.7;">'
            f'<b>Qtd Realizada:</b> '
            f'<span style="font-weight:600;">{ui._formatar(linha["quantidade"])}</span>'
            f' &nbsp;·&nbsp; <b>Tempo:</b> '
            f'<span style="font-weight:600;">{linha["tempo_total"] or "—"}</span><br>'
            f'<b>Meta:</b> <span style="font-weight:600;">{meta_txt}</span>'
            f' &nbsp;·&nbsp; <b>Prod. Real:</b> '
            f'<span style="font-weight:600;">{prod_txt}/h</span>'
            "</div>",
            unsafe_allow_html=True,
        )


def _grade_do_setor(nomes_regioes: tuple[str, ...]) -> None:
    """Grid de 3 colunas com os cards dos operadores do setor."""
    linhas = operadores[operadores["region_name"].isin(nomes_regioes)]
    if linhas.empty:
        st.info("Nenhum operador ativo neste setor no momento.")
        return
    linhas = linhas.sort_values("pct_meta", ascending=False)
    colunas = st.columns(3)
    for indice, (_, linha) in enumerate(linhas.iterrows()):
        with colunas[indice % 3]:
            _card_operador(linha)


with aba_caixas:
    _grade_do_setor(SETORES["caixas"])

with aba_bolsas:
    _grade_do_setor(SETORES["bolsas"])
