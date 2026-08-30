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

# Intervalo de releitura dos dados: o slider da barra lateral grava o
# valor no session_state, e esta leitura roda ANTES de o widget ser
# desenhado — então o valor aplicado aqui é o escolhido no rerun
# anterior, que é justamente o ciclo que o autorefresh dispara.
intervalo_dados = st.session_state.get(
    "ct_intervalo_dados", config.DASHBOARD_REFRESH_SECONDS
)

# No modo estático isto só reprograma a releitura do banco; no modo
# apresentação é o que dispara a troca para o painel da próxima região.
presentation.tick("tempo_real", intervalo_dados * 1000)

modo_tv = presentation.ativo()
if modo_tv:
    ui.esconder_navegacao()
    ui.css_modo_apresentacao()
    presentation.barra_apresentacao("Tempo Real")
else:
    presentation.controles_sidebar()
    with st.sidebar:
        st.divider()
        st.caption("ATUALIZAÇÃO")
        st.slider(
            "Tempo de atualização (segundos)",
            min_value=10, max_value=300, value=config.DASHBOARD_REFRESH_SECONDS,
            step=5, key="ct_intervalo_dados",
            help="De quanto em quanto tempo a tela relê o banco.",
        )

# Tamanhos das fontes dos gráficos: o SVG do Plotly não responde a CSS,
# então no modo apresentação o tamanho da TV precisa vir daqui.
FONTE_CHART = 18 if modo_tv else 14
TITULO_CHART = 24 if modo_tv else 18

col_title, col_status = st.columns([2, 1])
with col_title:
    # O emoji saiu do título agora que a logo carrega a identidade —
    # os dois juntos brigavam pelo mesmo espaço.
    ui.cabecalho(
        "CONTROL TOWER — OPERAÇÕES DE SELEÇÃO",
        "Honeywell Vocollect VoiceLink v5.2 · Reg Bolsas / Reg Caixas / "
        "Reg Foods / Reg de caixas com etiquetas",
    )

with col_status:
    # Badge "Ao Vivo": ponto verde pulsante + horário da última coleta
    # registrada no coleta_log. Verde = sincronizado; vermelho = última
    # tentativa falhou; cinza = coletor ainda não rodou.
    status = db.get_last_collection_status()
    if status is None:
        badge = (
            '<div class="ct-live-badge ct-live-off"><span class="ct-live-dot"></span>'
            'Aguardando primeira coleta</div>'
        )
    elif status["sucesso"]:
        hora = status["captured_at"][11:19]
        badge = (
            f'<div class="ct-live-badge"><span class="ct-live-dot"></span>'
            f'Operação Ao Vivo • Sincronizado às {hora}</div>'
        )
    else:
        hora = status["captured_at"][11:19]
        badge = (
            f'<div class="ct-live-badge ct-live-erro"><span class="ct-live-dot"></span>'
            f'Sincronização falhou às {hora}</div>'
        )
    st.markdown(badge, unsafe_allow_html=True)

st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

# --- Carrega os snapshots mais recentes de cada tabela --------------------
# produtividade_regiao usa "último por região": se uma região foi gravada
# num instante ligeiramente diferente das demais (retry/ciclo parcial),
# ela ainda aparece — o último snapshot GLOBAL a faria sumir.
tarefa = pd.DataFrame(db.get_latest_snapshot("resumo_tarefa"))
trabalho = pd.DataFrame(db.get_latest_snapshot("resumo_trabalho"))
prod_regiao = pd.DataFrame(db.get_latest_por_regiao("produtividade_regiao"))
falta = pd.DataFrame(db.get_latest_snapshot("produtos_falta"))
operadores = pd.DataFrame(db.get_latest_snapshot("produtividade_operador"))

if tarefa.empty:
    st.info("Nenhum dado coletado ainda. Rode `python collector.py` para começar a popular o painel.")
    st.stop()

# --- KPIs no topo (cards modernos) ----------------------------------------
total_selecionado = trabalho["itens_selecionados"].sum() if not trabalho.empty else 0
total_restante = trabalho["itens_restantes"].sum() if not trabalho.empty else 0
operadores_ativos = len(operadores)

# Cor contextual do valor da meta: >=100 verde, 85-99 laranja, <85 vermelho.
# Média simples de pct_meta das regiões ativas, ignorando nulos (região
# que não trouxe percentual não derruba o KPI).
if not prod_regiao.empty:
    valores_meta = prod_regiao["pct_meta"].dropna()
    media_meta = valores_meta.mean() if not valores_meta.empty else None
    if media_meta is not None:
        if media_meta >= 100:
            classe_meta = "ct-kpi-bom"
        elif media_meta >= 85:
            classe_meta = "ct-kpi-medio"
        else:
            classe_meta = "ct-kpi-ruim"
        valor_meta = f"{media_meta:.1f}%"
    else:
        classe_meta, valor_meta = "", "—"
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

# --- Abas: eliminam a rolagem vertical excessiva ---------------------------
aba_visao, aba_tarefas, aba_falta = st.tabs([
    "📊 Visão Geral & Operações",
    "📋 Resumo de Tarefas & Trabalho",
    "⚠️ Produtos em Falta",
])


# --- Aba 1: Visão Geral & Operações ----------------------------------------
# Nome legível do operador no lugar do ID numérico (o VoiceLink só
# entrega o ID) — usado pela tabela e pelo gráfico lado a lado.
operadores_com_nome = (
    operadores.assign(
        operador_nome=operadores["operador_id"].map(ui.nome_operador)
    )
    if not operadores.empty else operadores
)

with aba_visao:
    col_esq, col_dir = st.columns([3, 2])  # 60% / 40%

    with col_esq:
        st.subheader("👷 Produtividade Individual dos Operadores")
        if operadores_com_nome.empty:
            st.info("Nenhum operador com produção registrada no momento.")
        else:
            # Filtro multiseleção de regiões: tabela e gráfico mostram só
            # as regiões marcadas (todas por padrão).
            regioes_disponiveis = sorted(operadores_com_nome["region_name"].unique())
            filtro_regioes_op = st.multiselect(
                "Filtrar por Região",
                options=regioes_disponiveis,
                default=regioes_disponiveis,
                key="filtro_regioes_op",
            )
            operadores_visiveis = operadores_com_nome[
                operadores_com_nome["region_name"].isin(filtro_regioes_op)
            ]
            if operadores_visiveis.empty:
                st.info("Nenhum operador nas regiões selecionadas.")
            else:
                st.dataframe(
                    operadores_visiveis[["operador_nome", "region_name", "quantidade", "tempo_total",
                                         "meta", "produtividade_real", "pct_meta"]]
                    .sort_values("pct_meta", ascending=False)
                    .rename(columns={
                        "operador_nome": "Operador", "region_name": "Região",
                        "quantidade": "Quantidade", "tempo_total": "Tempo Total",
                        "meta": "Meta", "produtividade_real": "Produtividade Real",
                        "pct_meta": "% Meta",
                    }),
                    hide_index=True, width="stretch",
                    column_config={
                        "% Meta": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=150),
                    },
                )
                # Aqui a cor codifica pct_meta, que é uma variável diferente da
                # altura (produtividade_real) — então o gradiente tem razão de
                # existir. Só não pode ser um que comece no branco: usa o ramp
                # limitado do ui.py, que nunca se dissolve na superfície.
                fig_ops = px.bar(
                    operadores_visiveis, x="operador_nome", y="produtividade_real", color="pct_meta",
                    title="Produtividade Real por Operador",
                    color_continuous_scale=ui.SEQUENCIAL,
                )
                fig_ops.update_layout(template="plotly_white", paper_bgcolor=ui.SUPERFICIE, plot_bgcolor=ui.SUPERFICIE,
                font=dict(family=ui.FONTE, color=ui.TINTA_MUDA, size=FONTE_CHART), title_font=dict(color=ui.TINTA, size=TITULO_CHART),height=320, xaxis_title=None, yaxis_title=None)
                st.plotly_chart(fig_ops, width="stretch", key="graf_operadores")

    with col_dir:
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
            # Títulos explícitos nos eixos — e SEM title_font: um objeto
            # de título com fonte mas sem texto faz o plotly.js renderizar
            # a palavra "undefined" acima do gráfico. O subheader já
            # rotula o gráfico, então ele fica sem título mesmo.
            fig_evolucao.update_layout(template="plotly_white", paper_bgcolor=ui.SUPERFICIE, plot_bgcolor=ui.SUPERFICIE,
                font=dict(family=ui.FONTE, color=ui.TINTA_MUDA, size=FONTE_CHART),height=320, xaxis_title="Horário", yaxis_title="Itens Selecionados")
            st.plotly_chart(fig_evolucao, width="stretch", key="graf_evolucao")


# --- Aba 2: Resumo de Tarefas & Trabalho -----------------------------------
with aba_tarefas:
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

# --- Aba 3: Produtos em Falta ----------------------------------------------
with aba_falta:
    st.subheader("🚨 Produtos em Falta de Seleção")
    if falta.empty:
        st.info("Aguardando dados da coleta...")
    else:
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
