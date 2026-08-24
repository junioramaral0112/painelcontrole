"""
Modo Apresentação vs Modo Estático (seção 5.4 da especificação).

- Modo Estático (padrão): dashboard normal, com filtros e navegação
  manual. É o modo de quem está analisando.
- Modo Apresentação: alterna sozinho entre Tempo Real -> painel de cada
  região (só as marcadas no multiselect do controle) -> volta ao começo,
  a cada N segundos, sem ninguém mexer. É o modo da TV do chão de fábrica.

Como funciona a troca de tela:

    st.session_state guarda o modo e a posição na rotação (o session_state
    é compartilhado entre as páginas da mesma sessão do navegador, então o
    estado sobrevive à troca de página).

    st_autorefresh é armado com o tempo que FALTA para a próxima troca, e
    não com um tique fixo. Assim cada tela faz exatamente um rerun por
    rotação, em vez de ficar re-renderizando a cada segundo só para
    conferir as horas — numa TV ligada 24h isso é a diferença entre uma
    troca limpa e um piscar constante.

    Quando o tempo acaba, st.switch_page leva para a próxima tela da
    rotação.
"""
import time

import streamlit as st
from streamlit_autorefresh import st_autorefresh

import config

# Chaves do session_state, todas com prefixo para não colidir com os
# widgets das telas.
_MODO = "ct_modo_apresentacao"
_INTERVALO = "ct_intervalo_apresentacao"
_POSICAO = "ct_posicao_rotacao"
_ULTIMA_TROCA = "ct_ultima_troca"
_REGIAO_ALVO = "ct_regiao_alvo"
_REGIOES = "ct_regioes_rotacao"

PAGINA_TEMPO_REAL = "app.py"
PAGINA_HISTORICO = "pages/1_Historico.py"

# Ordem-mestra da rotação: primeiro a visão geral, depois um painel por
# região. A rotação EFETIVA é `rotacao_atual()`, que filtra as regiões
# marcadas no multiselect do controle.
# (None = tela de Tempo Real; um número = painel daquela região.)
ROTACAO = [None] + list(config.REGIONS.keys())


def rotacao_atual() -> list:
    """A rotação efetiva: visão geral + só as regiões marcadas no controle.

    A visão geral (None) entra sempre — sem ela a TV ficaria presa nos
    painéis de região sem nunca passar pela tela de Tempo Real. Se o
    usuário desmarcar tudo, a rotação vira só a visão geral.
    """
    escolhidas = st.session_state.get(_REGIOES, list(config.REGIONS.keys()))
    return [None] + [r for r in config.REGIONS if r in escolhidas]


def _init():
    st.session_state.setdefault(_MODO, False)
    st.session_state.setdefault(_INTERVALO, config.PRESENTATION_INTERVAL_SECONDS)
    st.session_state.setdefault(_POSICAO, 0)
    st.session_state.setdefault(_ULTIMA_TROCA, time.time())
    st.session_state.setdefault(_REGIOES, list(config.REGIONS.keys()))
    rotacao = rotacao_atual()
    st.session_state.setdefault(_REGIAO_ALVO, rotacao[1] if len(rotacao) > 1 else None)


def ativo() -> bool:
    _init()
    return bool(st.session_state[_MODO])


def regiao_alvo():
    """Região que o modo apresentação quer mostrar agora (usada pela tela
    histórica quando ela é aberta pela rotação, e não pelo filtro)."""
    _init()
    return st.session_state[_REGIAO_ALVO]


def ligar():
    _init()
    st.session_state[_MODO] = True
    st.session_state[_POSICAO] = 0
    st.session_state[_ULTIMA_TROCA] = time.time()
    # Recalcula o alvo na ativação: as regiões marcadas podem ter mudado
    # desde a última vez que o modo ficou ligado.
    rotacao = rotacao_atual()
    st.session_state[_REGIAO_ALVO] = rotacao[1] if len(rotacao) > 1 else None


def desligar():
    _init()
    st.session_state[_MODO] = False


def _proxima_tela(tela_atual: str):
    """Avança um passo na rotação e vai para a próxima tela.

    A maior parte da rotação é de um painel de região para o painel de
    OUTRA região — ou seja, o mesmo arquivo, só com outro filtro. Nesse
    caso o certo é st.rerun() e não st.switch_page(): trocar de página
    para a página em que já se está é, na melhor das hipóteses, um
    no-op — e um no-op aqui faria a rotação pular regiões, porque a
    posição já teria avançado sem a tela ter mudado.
    """
    rotacao = rotacao_atual()
    posicao = (st.session_state[_POSICAO] + 1) % len(rotacao)
    st.session_state[_POSICAO] = posicao
    st.session_state[_ULTIMA_TROCA] = time.time()

    destino = rotacao[posicao]
    if destino is None:
        if tela_atual == "tempo_real":
            st.rerun()
        else:
            st.switch_page(PAGINA_TEMPO_REAL)
    else:
        st.session_state[_REGIAO_ALVO] = destino
        if tela_atual == "historico":
            st.rerun()
        else:
            st.switch_page(PAGINA_HISTORICO)


def tick(chave_tela: str, intervalo_dados_ms: int = 15_000):
    """Chamar uma vez no topo de cada tela, logo depois do set_page_config.

    No modo estático, só reprograma a releitura do banco (o painel se
    atualiza sozinho conforme o coletor grava).
    No modo apresentação, conta o tempo e troca de tela na hora certa.
    """
    _init()

    if not ativo():
        st_autorefresh(interval=intervalo_dados_ms, key=f"refresh_{chave_tela}")
        return

    intervalo = st.session_state[_INTERVALO]
    decorrido = time.time() - st.session_state[_ULTIMA_TROCA]
    restante = intervalo - decorrido

    if restante <= 0:
        _proxima_tela(chave_tela)
        return

    # Acorda exatamente quando faltar zero (com uma folga de 250ms para
    # não errar por arredondamento e ficar um ciclo inteiro a mais na
    # mesma tela).
    st_autorefresh(interval=int(restante * 1000) + 250, key=f"rotacao_{chave_tela}")


def controles_sidebar():
    """Controles do modo, na barra lateral (modo estático): regiões da
    rotação, toggle do modo e intervalo por tela."""
    _init()
    with st.sidebar:
        st.divider()
        st.caption("MODO DE EXIBIÇÃO")

        st.session_state[_REGIOES] = st.multiselect(
            "Regiões na rotação",
            options=list(config.REGIONS.keys()),
            default=list(config.REGIONS.keys()),
            format_func=lambda n: config.REGIONS[n],
            key="ct_multiselect_regioes",
            help="Regiões que o modo apresentação percorre. A visão geral "
                 "(Tempo Real) entra sempre, antes das regiões.",
        )

        ligado = st.toggle(
            "Modo apresentação",
            value=st.session_state[_MODO],
            help="Alterna sozinho entre a visão geral e o painel de cada "
                 "região. Pensado para a TV do chão de fábrica.",
        )

        st.session_state[_INTERVALO] = st.slider(
            "Segundos por tela", min_value=5, max_value=120,
            value=int(st.session_state[_INTERVALO]), step=5,
            disabled=not ligado,
        )

        if ligado and not st.session_state[_MODO]:
            ligar()
            st.rerun()
        elif not ligado and st.session_state[_MODO]:
            desligar()
            st.rerun()


def barra_apresentacao(nome_tela: str):
    """Faixa fina no topo, no modo apresentação, com o botão de sair.

    A navegação lateral fica escondida nesse modo, então precisa existir
    uma saída visível — senão só reiniciando o navegador para voltar ao
    modo interativo.
    """
    _init()
    posicao = st.session_state[_POSICAO] + 1
    total = len(rotacao_atual())
    intervalo = int(st.session_state[_INTERVALO])

    faixa, botao = st.columns([5, 1])
    with faixa:
        st.markdown(
            f'<div class="ct-pres-bar"><span class="ct-dot"></span>'
            f"<span><b>Modo apresentação</b> · {nome_tela} · tela {posicao} de "
            f"{total} · troca a cada {intervalo}s</span></div>",
            unsafe_allow_html=True,
        )
    with botao:
        if st.button("⏹ Sair", width="stretch"):
            desligar()
            st.rerun()
