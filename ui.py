"""
Elementos visuais compartilhados entre as telas do Control Tower.

Concentra aqui o que as duas telas (Tempo Real e Histórico por Região)
precisam ter igual: paleta, CSS, cards de KPI, avatares e o padrão dos
gráficos. Assim o modo apresentação pode alternar entre as telas sem que
uma pareça de um produto e a outra de outro.

A paleta é a paleta de referência de data-viz, no modo CLARO, validada
contra a superfície #fcfcfb. Verde e vermelho aqui são cores de ESTADO
(acima/abaixo da meta), não séries de dados: por isso nunca aparecem
sozinhas — sempre acompanhadas de uma seta e do número com sinal, que é
o que garante a leitura para quem tem daltonismo.

Se um dia for preciso voltar ao fundo escuro, troque o bloco de
constantes abaixo pelos valores escuros da paleta (superfície #1a1a19,
plano #0d0d0d, tinta #ffffff, tinta2 #c3c2b7, grade #2c2c2a, base
#383835, borda branca a 10%, série #3987e5, bom #0ca30c) e ajuste o
.streamlit/config.toml junto — o resto do arquivo é escrito em cima
destas constantes e acompanha sozinho.
"""
import base64
import html
import os
import zlib
from functools import lru_cache

import plotly.graph_objects as go
import streamlit as st

import auth
import config
import database as db

# --- Paleta (modo claro da paleta de referência) --------------------------
SUPERFICIE = "#fcfcfb"     # superfície dos gráficos e cards
PLANO = "#f9f9f7"          # fundo da página
TINTA = "#0b0b0b"          # texto primário
TINTA_2 = "#52514e"        # texto secundário
TINTA_MUDA = "#898781"     # eixos e rótulos (igual nos dois modos)
GRADE = "#e1e0d9"          # linha de grade (hairline)
LINHA_BASE = "#c3c2b7"     # eixo/baseline
BORDA = "rgba(11,11,11,0.10)"

SERIE = "#2a78d6"          # hue única dos gráficos (série única)
SERIE_WASH = "rgba(42,120,214,0.10)"   # área a ~10% de opacidade

# Cores de ESTADO. O verde é o passo de "texto de sucesso" do fundo
# claro (#006300), mais escuro que o verde de marca — porque aqui ele é
# usado como TEXTO, e o verde claro não teria contraste suficiente.
BOM = "#006300"            # estado: acima da meta
RUIM = "#d03b3b"           # estado: abaixo da meta (4,68:1 no fundo claro)

# Ordem categórica para os gráficos de várias séries (as 4 regiões).
# Esta ordem saiu do validador de paleta: azul -> laranja -> violeta ->
# verde passa em todos os testes no fundo claro, inclusive contraste
# >= 3:1 nos quatro. A ORDEM importa e não é estética: laranja
# encostado em verde reprova em protanopia (ΔE 3,2), e o violeta no
# meio é o que separa os dois. Não reordene sem rodar o validador.
CATEGORICAS = ["#2a78d6", "#eb6834", "#4a3aa7", "#008300"]

# Ramp sequencial (uma hue só, claro -> escuro) para quando a cor
# precisa mesmo codificar magnitude. Começa no passo 250 e não no mais
# claro do ramp: num fundo claro os primeiros passos se dissolvem na
# superfície, e uma barra invisível é pior que uma barra sem gradiente.
SEQUENCIAL = ["#86b6ef", "#5598e7", "#2a78d6", "#256abf", "#184f95", "#0d366b"]

FONTE = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Cores dos avatares: passos escuros do ramp azul, só para dar identidade
# visual ao operador — não codificam nenhum dado. São escuros de
# propósito: as iniciais são brancas por cima, então o círculo precisa
# segurar o contraste do texto, e não o do fundo da página.
_CORES_AVATAR = ["#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b", "#2a78d6"]


CSS = f"""
<style>
  /* Tamanho-base da página em 18px (o padrão do navegador é 16px). É ele
     que dimensiona as CÉLULAS DAS TABELAS: o Streamlit desenha o grid em
     canvas (Glide Data Grid), que não aceita CSS, e o grid lê o
     font-size do <html> para calcular o tamanho do texto. */
  html {{ font-size: 18px; }}

  .stApp {{ background-color: {PLANO}; }}

  /* Elementos nativos do Streamlit. O texto deles vem do CSS-in-JS do
     próprio Streamlit (em px, fora do nosso alcance direto), então são
     subidos aqui para acompanhar o tamanho do resto do painel. */
  [data-testid="stHeading"] {{ font-size: 24px; }}
  [data-testid="stMetricValue"] {{ font-size: 40px; }}
  [data-testid="stMetricLabel"] {{ font-size: 16px; }}
  [data-testid="stCaptionContainer"] p {{ font-size: 16px; }}
  [data-testid="stWidgetLabel"] p {{ font-size: 15px; }}
  [data-testid="stAlert"] {{ font-size: 16px; }}
  [data-testid="stSidebar"] {{ font-size: 16px; }}
  [data-testid="stSelectbox"] {{ font-size: 16px; }}
  [data-testid="stRadio"] {{ font-size: 16px; }}
  button {{ font-size: 16px; }}

  /* Cabeçalho de tela */
  .ct-header {{
      display: flex; align-items: baseline; justify-content: space-between;
      gap: 16px; flex-wrap: wrap; margin-bottom: 4px;
  }}
  .ct-brand {{
      display: flex; align-items: center; gap: 16px; margin-bottom: 4px;
  }}

  /* No fundo claro a logo não precisa mais da placa branca que existia
     na versão escura: ela é predominantemente azul-marinho (#002040) e
     laranja, que sobre #f9f9f7 aparecem com folga. Uma placa branca
     sobre fundo branco seria só um retângulo invisível ocupando espaço. */
  .ct-logo {{
      display: inline-flex; align-items: center; flex: 0 0 auto;
  }}
  .ct-logo img {{ height: clamp(28px, 2.6vw, 40px); display: block; }}
  .ct-title {{
      font-family: {FONTE}; font-size: clamp(24px, 2.4vw, 36px); font-weight: 600;
      color: {TINTA}; letter-spacing: -0.01em; margin: 0;
  }}
  .ct-sub {{ font-family: {FONTE}; font-size: 16px; color: {TINTA_MUDA}; margin: 0; }}

  /* Card de KPI */
  .ct-card {{
      background: {SUPERFICIE}; border: 1px solid {BORDA}; border-radius: 10px;
      padding: 16px 18px; height: 100%;
  }}
  .ct-card-label {{
      font-family: {FONTE}; font-size: 15px; color: {TINTA_2};
      margin: 0 0 6px 0; font-weight: 500;
  }}
  /* O tamanho acompanha a largura da tela: são 4 cards lado a lado, e um
     número grande (ex.: 1.284.930 no acumulado do mês) estouraria a
     largura da coluna num monitor pequeno. Em vez de cortar o número,
     ele encolhe — na TV, que é o caso de uso principal, fica no
     tamanho cheio. */
  .ct-card-value {{
      font-family: {FONTE}; font-size: clamp(26px, 2.8vw, 42px);
      font-weight: 600; color: {TINTA};
      line-height: 1.15; margin: 0; overflow-wrap: anywhere;
  }}
  .ct-card-unit {{ font-size: 17px; font-weight: 500; color: {TINTA_MUDA}; margin-left: 4px; }}
  .ct-card-foot {{ font-family: {FONTE}; font-size: 15px; margin: 8px 0 0 0; color: {TINTA_MUDA}; }}
  .ct-delta-bom {{ color: {BOM}; font-weight: 600; }}
  .ct-delta-ruim {{ color: {RUIM}; font-weight: 600; }}

  /* Faixa que separa a linha "Dia" da linha "Mês" */
  .ct-rowlabel {{
      font-family: {FONTE}; font-size: 14px; font-weight: 700;
      letter-spacing: 0.08em; text-transform: uppercase;
      color: {TINTA_MUDA}; margin: 6px 0 8px 0;
  }}

  /* Barra do modo apresentação */
  .ct-pres-bar {{
      background: {SUPERFICIE}; border: 1px solid {BORDA}; border-radius: 8px;
      padding: 8px 14px; font-family: {FONTE}; font-size: 15px; color: {TINTA_2};
      display: flex; align-items: center; gap: 10px; margin-bottom: 10px;
  }}
  .ct-dot {{
      width: 8px; height: 8px; border-radius: 50%; background: {BOM};
      display: inline-block;
  }}
</style>
"""


def configurar_pagina(titulo: str, icone: str = "📡"):
    """set_page_config + CSS + garantia de schema. Chamar no topo de cada tela."""
    st.set_page_config(page_title=titulo, page_icon=icone, layout="wide")
    # init_db é idempotente: garante que um banco criado por uma versão
    # anterior (sem a tabela de pedidos) ganhe as tabelas novas antes de
    # qualquer consulta.
    db.init_db()
    st.markdown(CSS, unsafe_allow_html=True)


CHAVE_AUTENTICADO = "ct_autenticado"


def exigir_login() -> None:
    """Portão de login: bloqueia a página até validar contra o VoiceLink.

    Chamar no topo de CADA página (as páginas multi-page do Streamlit
    rodam scripts separados, então cada uma precisa do seu portão).

    Regras:

      * a fonte de verdade é o VoiceLink — a credencial digitada é
        validada com a MESMA chamada de login que o coletor usa
        (auth.login_voicelink); não existe lista de usuários local;
      * a senha existe só durante a chamada de validação — não vai para
        banco, arquivo, log nem session_state; a variável morre no fim
        desta função;
      * a autenticação vive em session_state: morre junto com a aba/
        navegador — cada pessoa que abrir o painel loga de novo;
      * não interfere no coletor: ele segue com a credencial de serviço
        do .env, independente de quem está (ou não) logado no dashboard.
    """
    if st.session_state.get(CHAVE_AUTENTICADO):
        return

    st.markdown(
        '<p class="ct-title">CONTROL TOWER — OPERAÇÕES DE SELEÇÃO</p>',
        unsafe_allow_html=True,
    )
    st.caption("Entre com a sua conta do VoiceLink para ver o painel.")

    with st.form("ct_login"):
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        enviar = st.form_submit_button("Entrar")

    if enviar:
        if not usuario or not senha:
            st.error("Preencha usuário e senha.")
        else:
            with st.spinner("Validando no VoiceLink…"):
                sessao = auth.login_voicelink(usuario, senha)
            if sessao is not None:
                sessao.close()  # o dashboard só precisa da validação
                st.session_state[CHAVE_AUTENTICADO] = True
                st.rerun()
            else:
                st.error(
                    "Login inválido. Verifique usuário e senha "
                    "(ou se a rede do VoiceLink está acessível)."
                )

    st.stop()


@lru_cache(maxsize=1)
def logo_data_uri() -> str:
    """Logo do cabeçalho, embutida como data URI.

    Vai embutida no HTML em vez de ser servida como arquivo estático
    porque o painel roda numa rede isolada e assim não depende de
    nenhuma rota extra do Streamlit.

    Fica em cache porque as telas se redesenham a cada 15s numa TV
    ligada o dia inteiro — não faz sentido reler o arquivo toda vez.
    Trocar o logo.png exige reiniciar o Streamlit para o cache soltar.

    Devolve "" se o arquivo não existir: o cabeçalho aparece só com o
    título, em vez de quebrar a tela inteira por causa de uma imagem.
    """
    caminho = config.LOGO_PATH
    if not caminho or not os.path.exists(caminho):
        return ""
    try:
        with open(caminho, "rb") as arquivo:
            dados = arquivo.read()
    except OSError:
        return ""

    extensao = os.path.splitext(caminho)[1].lower()
    tipo = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml", ".webp": "image/webp"}.get(extensao, "image/png")
    return f"data:{tipo};base64,{base64.b64encode(dados).decode('ascii')}"


def cabecalho(titulo: str, subtitulo: str = ""):
    """Cabeçalho padrão das duas telas: logo + título.

    As duas telas usam o mesmo cabeçalho de propósito — no modo
    apresentação elas se alternam a cada 15s, e um cabeçalho diferente em
    cada uma faria parecer que a TV trocou de sistema, não de tela.
    """
    logo = logo_data_uri()
    bloco_logo = f'<div class="ct-logo"><img src="{logo}" alt=""></div>' if logo else ""
    bloco_sub = (
        f'<p class="ct-sub">{html.escape(subtitulo)}</p>' if subtitulo else ""
    )
    st.markdown(
        f'<div class="ct-brand">{bloco_logo}'
        f'<div><p class="ct-title">{html.escape(titulo)}</p>{bloco_sub}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def esconder_navegacao():
    """Some com a navegação lateral — usado só no modo apresentação, para
    a TV do chão de fábrica não mostrar menu de navegação."""
    st.markdown(
        """
        <style>
          [data-testid="stSidebar"], [data-testid="stSidebarNav"],
          [data-testid="collapsedControl"], header { display: none !important; }
          .block-container { padding-top: 2rem !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def css_modo_apresentacao():
    """CSS extra do modo apresentação (TV do chão de fábrica).

    O tamanho cresce em três camadas, porque cada tecnologia de render do
    Streamlit escala de um jeito:

      * ``html { font-size: 22px }`` — as células das tabelas são
        desenhadas em canvas (Glide Data Grid) e NÃO aceitam CSS; o grid
        lê o font-size do <html> e dimensiona o texto a partir dele. É a
        única alavanca que alcança as tabelas.
      * os ``[data-testid]`` e as classes ``.ct-*`` — texto em DOM (o
        CSS-in-JS do Streamlit e o nosso), com px maiores aqui.
      * os gráficos Plotly — SVG com tamanhos definidos em Python; as
        telas passam ``ampliar=True`` ao construir as figuras.

    NÃO use ``zoom`` para isso: sob zoom o layout de colunas do
    Streamlit quebra e os gráficos invadem as tabelas vizinhas (verificado
    em navegador real).
    """
    st.markdown(
        """
        <style>
          html { font-size: 22px; }
          [data-testid="stHeading"] { font-size: 28px; }
          [data-testid="stMetricValue"] { font-size: 48px; }
          [data-testid="stMetricLabel"] { font-size: 19px; }
          [data-testid="stCaptionContainer"] p { font-size: 19px; }
          [data-testid="stAlert"] { font-size: 19px; }
          [data-testid="stSelectbox"] { font-size: 18px; }
          button { font-size: 18px; }

          .ct-title { font-size: clamp(30px, 3.2vw, 46px); }
          .ct-sub { font-size: 19px; }
          .ct-card-label { font-size: 18px; }
          .ct-card-value { font-size: clamp(34px, 3.6vw, 54px); }
          .ct-card-unit { font-size: 21px; }
          .ct-card-foot { font-size: 18px; }
          .ct-rowlabel { font-size: 17px; }
          .ct-pres-bar { font-size: 18px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# --- Avatares (seção 5.3: v1 sem fotos reais) -----------------------------

def avatar_data_uri(identificador: str) -> str:
    """SVG com as iniciais do operador, embutido como data URI.

    A v1 não usa fotos (decisão registrada na seção 5.3). O avatar é
    gerado a partir do próprio ID, sem nenhum arquivo de imagem e sem
    nenhuma requisição externa — o painel roda numa rede isolada.

    A cor vem de um CRC32 do identificador, e não do hash() do Python,
    que muda a cada processo: assim o mesmo operador aparece sempre com a
    mesma cor, inclusive entre a TV e o navegador de quem abrir o painel.
    """
    ident = (identificador or "?").strip()
    iniciais = html.escape(ident[:2].upper() or "?")
    cor = _CORES_AVATAR[zlib.crc32(ident.encode("utf-8")) % len(_CORES_AVATAR)]

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
        f'<circle cx="32" cy="32" r="32" fill="{cor}"/>'
        f'<text x="32" y="33" font-family="{html.escape(FONTE)}" font-size="26" '
        'font-weight="600" fill="#ffffff" text-anchor="middle" '
        f'dominant-baseline="central">{iniciais}</text>'
        "</svg>"
    )
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


# --- Cards de KPI ---------------------------------------------------------

def _formatar(valor, casas: int = 0) -> str:
    """Número no padrão brasileiro: 1.234,5"""
    if valor is None:
        return "—"
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def card_kpi(label: str, valor, unidade: str = "", casas: int = 0,
             meta=None, rodape: str = ""):
    """Card de KPI no padrão dos painéis de referência.

    Quando `meta` é informada, o rodapé mostra "Meta: X (±Y%)" com seta —
    igual ao "Meta: 1350 (-34,75%)" dos painéis da PepsiCo. A seta e o
    sinal são obrigatórios: verde e vermelho são cores de estado e nunca
    podem ser o único canal de leitura.

    Métricas sem meta definida no VoiceLink (quantidade separada, número
    de pedidos, itens por pedido) ficam sem essa linha em vez de ganhar
    uma meta inventada.
    """
    if valor is None:
        corpo_valor = '<p class="ct-card-value">—</p>'
    else:
        unidade_html = (
            f'<span class="ct-card-unit">{html.escape(unidade)}</span>' if unidade else ""
        )
        corpo_valor = (
            f'<p class="ct-card-value">{_formatar(valor, casas)}{unidade_html}</p>'
        )

    if meta and valor is not None and meta > 0:
        delta = (valor / meta - 1.0) * 100.0
        acima = delta >= 0
        seta = "▲" if acima else "▼"
        classe = "ct-delta-bom" if acima else "ct-delta-ruim"
        rodape_html = (
            f'<p class="ct-card-foot">Meta: {_formatar(meta, 0)} '
            f'<span class="{classe}">{seta} {_formatar(delta, 2)}%</span></p>'
        )
    elif rodape:
        rodape_html = f'<p class="ct-card-foot">{html.escape(rodape)}</p>'
    else:
        rodape_html = ""

    st.markdown(
        f'<div class="ct-card">'
        f'<p class="ct-card-label">{html.escape(label)}</p>'
        f"{corpo_valor}{rodape_html}</div>",
        unsafe_allow_html=True,
    )


# --- Gráficos -------------------------------------------------------------

def grafico_area(x, y, titulo: str, rotulo_x: str, rotulo_y: str,
                 meta=None, tickvals=None, ticktext=None,
                 altura: int = 260, ampliar: bool = False) -> go.Figure:
    """Gráfico de área de série única, no padrão da paleta.

    Série única não leva legenda: o título já diz o que está plotado, e
    uma caixa com um quadradinho só repetiria o título. A linha tem 2px e
    a área fica a ~10% de opacidade — a grade é hairline e recuada, para
    o dado ser a única coisa com peso visual na tela.

    `ampliar=True` (modo apresentação) multiplica as fontes e a altura
    por ~1,3: o SVG do Plotly não responde a CSS, então o tamanho para a
    TV precisa vir daqui.
    """
    k = 1.3 if ampliar else 1.0

    def tam(tamanho: int) -> int:
        return round(tamanho * k)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=list(x), y=list(y), mode="lines", fill="tozeroy",
            line=dict(color=SERIE, width=2, shape="linear"),
            fillcolor=SERIE_WASH,
            hovertemplate=f"<b>%{{x}}</b><br>{rotulo_y}: %{{y:,.0f}}<extra></extra>",
            name=rotulo_y,
        )
    )

    if meta:
        # A meta é uma referência, não uma série: linha fina e apagada,
        # com o valor anotado no canto em vez de entrar numa legenda.
        fig.add_hline(
            y=meta, line=dict(color=TINTA_MUDA, width=1),
            annotation_text=f"Meta {_formatar(meta, 0)}",
            annotation_position="top left",
            annotation_font=dict(color=TINTA_MUDA, size=tam(13), family=FONTE),
        )

    fig.update_layout(
        title=dict(text=titulo, font=dict(color=TINTA, size=tam(18), family=FONTE), x=0, xanchor="left"),
        height=max(altura, int(altura * k)),
        margin=dict(l=10, r=16, t=40, b=10),
        paper_bgcolor=SUPERFICIE,
        plot_bgcolor=SUPERFICIE,
        font=dict(family=FONTE, color=TINTA_MUDA, size=tam(14)),
        showlegend=False,
        hovermode="x unified",
        hoverlabel=dict(bgcolor=SUPERFICIE, bordercolor=BORDA,
                        font=dict(family=FONTE, color=TINTA, size=tam(14))),
    )
    fig.update_xaxes(
        title=dict(text=rotulo_x, font=dict(size=tam(13), color=TINTA_MUDA)),
        showgrid=False, zeroline=False,
        linecolor=LINHA_BASE, linewidth=1,
        tickfont=dict(color=TINTA_MUDA, size=tam(13)),
        tickvals=tickvals, ticktext=ticktext,
    )
    fig.update_yaxes(
        title=None,
        showgrid=True, gridcolor=GRADE, gridwidth=1, griddash="solid",
        zeroline=False, linecolor=LINHA_BASE,
        tickfont=dict(color=TINTA_MUDA, size=tam(13)),
        separatethousands=True,
    )
    return fig
