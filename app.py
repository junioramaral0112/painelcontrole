"""
Control Tower - Dashboard (Streamlit)

IMPORTANTE: este app NUNCA chama o VoiceLink diretamente. Ele só lê o
banco de dados que o collector.py alimenta em segundo plano. Isso evita
que múltiplos usuários abrindo o painel multipliquem as requisições ao
servidor do VoiceLink — o coletor roda uma vez, todo mundo lê do banco.

Rodar:
    streamlit run app.py

O painel se atualiza sozinho a cada 15s (dado novo aparece assim que o
coletor grava, sem precisar apertar F5).
"""
import pandas as pd
import plotly.express as px
import streamlit as st

import config
import database as db
import presentation
import ui

ui.configurar_pagina("Control Tower - Vocollect VoiceLink", "📡")

# No modo estático isto só reprograma a releitura do banco; no modo
# apresentação é o que dispara a troca para o painel da próxima região.
presentation.tick("tempo_real", config.DASHBOARD_REFRESH_SECONDS * 1000)

modo_tv = presentation.ativo()
if modo_tv:
    ui.esconder_navegacao()
    ui.css_modo_apresentacao()
    presentation.barra_apresentacao("Tempo Real")
else:
    presentation.controles_sidebar()

# Tamanhos das fontes dos gráficos: o SVG do Plotly não responde a CSS,
# então no modo apresentação o tamanho da TV precisa vir daqui.
FONTE_CHART = 18 if modo_tv else 14
TITULO_CHART = 24 if modo_tv else 18

col_title, col_status = st.columns([3, 1])
with col_title:
    # O emoji saiu do título agora que a logo carrega a identidade —
    # os dois juntos brigavam pelo mesmo espaço.
    ui.cabecalho(
        "CONTROL TOWER — OPERAÇÕES DE SELEÇÃO",
        "Honeywell Vocollect VoiceLink v5.2 · Reg Bolsas / Reg Caixas / "
        "Reg Foods / Reg de caixas com etiquetas",
    )

with col_status:
    status = db.get_last_collection_status()
    if status is None:
        st.warning("Coletor ainda não rodou. Inicie `python collector.py`.")
    elif status["sucesso"]:
        st.success(f"Última coleta: {status['captured_at']}")
    else:
        st.error(f"Falha na última coleta ({status['captured_at']}): {status['detalhe']}")

st.divider()

# --- Carrega os snapshots mais recentes de cada tabela --------------------
tarefa = pd.DataFrame(db.get_latest_snapshot("resumo_tarefa"))
trabalho = pd.DataFrame(db.get_latest_snapshot("resumo_trabalho"))
prod_regiao = pd.DataFrame(db.get_latest_snapshot("produtividade_regiao"))
falta = pd.DataFrame(db.get_latest_snapshot("produtos_falta"))
operadores = pd.DataFrame(db.get_latest_snapshot("produtividade_operador"))

if tarefa.empty:
    st.info("Nenhum dado coletado ainda. Rode `python collector.py` para começar a popular o painel.")
    st.stop()

# --- KPIs no topo ----------------------------------------------------------
k1, k2, k3, k4 = st.columns(4)
with k1:
    total_selecionado = trabalho["itens_selecionados"].sum() if not trabalho.empty else 0
    st.metric("Itens Selecionados", f"{total_selecionado:,.0f}")
with k2:
    total_restante = trabalho["itens_restantes"].sum() if not trabalho.empty else 0
    st.metric("Itens Restantes", f"{total_restante:,.0f}")
with k3:
    st.metric("Operadores Ativos", len(operadores))
with k4:
    media_meta = prod_regiao["pct_meta"].mean() if not prod_regiao.empty else 0
    st.metric("Atingimento Médio da Meta", f"{media_meta:.1f}%")

st.divider()

# --- Produtividade Individual por Operador ---------------------------------
st.subheader("👷 Produtividade Individual dos Operadores (apenas em produção)")

c1, c2 = st.columns([1.3, 1])
with c1:
    if operadores.empty:
        st.info("Nenhum operador com produção registrada no momento.")
    else:
        st.dataframe(
            operadores[["operador_id", "region_name", "quantidade", "tempo_total",
                        "meta", "produtividade_real", "pct_meta"]]
            .sort_values("pct_meta", ascending=False)
            .rename(columns={
                "operador_id": "Operador", "region_name": "Região",
                "quantidade": "Quantidade", "tempo_total": "Tempo Total",
                "meta": "Meta", "produtividade_real": "Produtividade Real",
                "pct_meta": "% Meta",
            }),
            hide_index=True, width="stretch",
            column_config={
                "% Meta": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=150),
            },
        )
with c2:
    if not operadores.empty:
        # Aqui a cor codifica pct_meta, que é uma variável diferente da
        # altura (produtividade_real) — então o gradiente tem razão de
        # existir. Só não pode ser um que comece no branco: usa o ramp
        # limitado do ui.py, que nunca se dissolve na superfície.
        fig_ops = px.bar(
            operadores, x="operador_id", y="produtividade_real", color="pct_meta",
            title="Produtividade Real por Operador",
            color_continuous_scale=ui.SEQUENCIAL,
        )
        fig_ops.update_layout(template="plotly_white", paper_bgcolor=ui.SUPERFICIE, plot_bgcolor=ui.SUPERFICIE,
        font=dict(family=ui.FONTE, color=ui.TINTA_MUDA, size=FONTE_CHART), title_font=dict(color=ui.TINTA, size=TITULO_CHART),height=320, xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig_ops, width="stretch", key="graf_operadores")

st.divider()

# --- Resumo da Tarefa / Resumo do Trabalho --------------------------------
c3, c4 = st.columns(2)
with c3:
    st.subheader("📋 Resumo da Tarefa de Seleção")
    st.dataframe(
        tarefa[["region_name", "total", "em_andamento", "disponivel", "concluido"]]
        .rename(columns={
            "region_name": "Região", "total": "Total", "em_andamento": "Em andamento",
            "disponivel": "Disponível", "concluido": "Concluído",
        }),
        hide_index=True, width="stretch",
    )
with c4:
    st.subheader("⚙️ Resumo do Trabalho Atual")
    if trabalho.empty:
        st.info("Aguardando dados da coleta...")
    else:
        st.dataframe(
            trabalho[["region_name", "itens_restantes", "operadores_trabalhando",
                      "itens_selecionados", "operadores_atribuidos"]]
            .rename(columns={
                "region_name": "Região", "itens_restantes": "Itens Restantes",
                "operadores_trabalhando": "Operadores Trabalhando",
                "itens_selecionados": "Itens Selecionados",
                "operadores_atribuidos": "Operadores Atribuídos",
            }),
            hide_index=True, width="stretch",
        )

st.divider()

# --- Produtividade por Região + gráfico -----------------------------------
c5, c6 = st.columns([1.2, 1])
with c5:
    st.subheader("📊 Produtividade por Região")
    if prod_regiao.empty:
        st.info("Aguardando dados da coleta...")
    else:
        st.dataframe(
            prod_regiao[["region_name", "pct_meta", "produtividade_atual", "meta", "quantidade_total"]]
            .rename(columns={
                "region_name": "Região", "pct_meta": "% da Meta",
                "produtividade_atual": "Produtividade (un/h)", "meta": "Meta",
                "quantidade_total": "Quantidade",
            }),
            hide_index=True, width="stretch",
            column_config={"% da Meta": st.column_config.NumberColumn(format="%.1f%%")},
        )
with c6:
    if not prod_regiao.empty:
        # Cor sólida: a altura da barra já diz a magnitude, então pintar
        # por pct_meta era codificar duas vezes a mesma coisa — e no fundo
        # claro a ponta baixa da escala "Blues" fica quase invisível,
        # justamente nas regiões que mais precisam ser vistas.
        fig = px.bar(
            prod_regiao, x="region_name", y="pct_meta",
            title="% Atingimento da Meta por Região",
            text_auto=".1f", color_discrete_sequence=[ui.SERIE],
        )
        fig.update_layout(template="plotly_white", paper_bgcolor=ui.SUPERFICIE, plot_bgcolor=ui.SUPERFICIE,
        font=dict(family=ui.FONTE, color=ui.TINTA_MUDA, size=FONTE_CHART), title_font=dict(color=ui.TINTA, size=TITULO_CHART),height=280, xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig, width="stretch", key="graf_pct_meta")

st.divider()

# --- Produtos em Falta (base para Pareto) -----------------------------------
st.subheader("🚨 Produtos em Falta de Seleção")
if not falta.empty:
    c7, c8 = st.columns([1, 1.2])
    with c7:
        st.dataframe(
            falta[["region_name", "total_faltas", "em_falta", "atribuido", "marcado"]]
            .rename(columns={
                "region_name": "Região", "total_faltas": "Total",
                "em_falta": "Em falta", "atribuido": "Atribuído", "marcado": "Marcado",
            }),
            hide_index=True, width="stretch",
        )
    with c8:
        falta_ordenada = falta[falta["em_falta"] > 0].sort_values("em_falta", ascending=False)
        if not falta_ordenada.empty:
            fig_falta = px.bar(
                falta_ordenada, x="region_name", y="em_falta",
                title="Itens em Falta por Região",
                # Vermelho de ESTADO (crítico) da paleta, que é o mesmo
                # usado nos deltas abaixo da meta — 4,68:1 no fundo claro.
                color_discrete_sequence=[ui.RUIM],
            )
            fig_falta.update_layout(template="plotly_white", paper_bgcolor=ui.SUPERFICIE, plot_bgcolor=ui.SUPERFICIE,
        font=dict(family=ui.FONTE, color=ui.TINTA_MUDA, size=FONTE_CHART), title_font=dict(color=ui.TINTA, size=TITULO_CHART),height=280, xaxis_title=None, yaxis_title=None)
            st.plotly_chart(fig_falta, width="stretch", key="graf_falta")
        else:
            st.success("Nenhum item em falta no momento. 🎉")

st.divider()

# --- Curva de Evolução -------------------------------------------------
st.subheader("📈 Curva de Evolução — Itens Selecionados (últimas 8h)")
historico = pd.DataFrame(db.get_history("resumo_trabalho", hours=8))
if historico.empty:
    st.info("Ainda não há histórico suficiente. A curva aparece conforme o coletor acumula snapshots.")
else:
    historico["captured_at"] = pd.to_datetime(historico["captured_at"])
    evolucao = historico.groupby(["captured_at", "region_name"])["itens_selecionados"].sum().reset_index()
    # Única série múltipla do painel: usa a ordem categórica validada do
    # ui.py. As 4 cores passam no contraste no fundo claro e se
    # distinguem em daltonismo — o que a escala padrão do Plotly não
    # garante, e aqui são 4 linhas finas se cruzando.
    fig_evolucao = px.line(
        evolucao, x="captured_at", y="itens_selecionados", color="region_name",
        title=None, markers=True,
        color_discrete_sequence=ui.CATEGORICAS,
    )
    fig_evolucao.update_layout(template="plotly_white", paper_bgcolor=ui.SUPERFICIE, plot_bgcolor=ui.SUPERFICIE,
        font=dict(family=ui.FONTE, color=ui.TINTA_MUDA, size=FONTE_CHART), title_font=dict(color=ui.TINTA, size=TITULO_CHART),height=320, xaxis_title=None, yaxis_title="Itens Selecionados")
    st.plotly_chart(fig_evolucao, width="stretch", key="graf_evolucao")
