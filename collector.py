"""
Coletor do Control Tower - Vocollect VoiceLink v5.2

Roda em loop, a cada POLL_INTERVAL_SECONDS (padrão 60s):
    1. Garante login válido (Spring Security)
    2. Chama os 5 endpoints mapeados
    3. Faz o parse de cada resposta para o formato do banco
    4. Grava tudo com o mesmo timestamp de captura

Este processo é INDEPENDENTE do dashboard Streamlit — pode (e deve)
rodar sozinho, como um serviço/task agendada, mesmo sem ninguém olhando
o painel. O Streamlit só lê o que este script grava.

Uso:
    python collector.py            # roda em loop contínuo
    python collector.py --once     # roda uma única coleta e sai (útil para testar)
"""
import sys
import time
import logging
import urllib3

import auth
import config
import database as db

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# O coletor fica rodando 24/7 num console do Windows, que abre em
# cp1252/cp850 e não dá conta dos acentos das mensagens de log. Sem isto,
# um log com acento derruba o processo por UnicodeEncodeError.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("collector")


class VoiceLinkSession:
    """Encapsula a sessão autenticada e as chamadas aos endpoints."""

    def __init__(self):
        self.session = None
        self._logged_in = False

    def login(self):
        """Autentica via Spring Security (j_spring_security_check).

        A lógica de login é compartilhada com a tela de login do
        dashboard (auth.py) — a única diferença é a credencial: aqui é a
        de serviço do .env, lá é a digitada por quem está abrindo o
        painel.
        """
        if not config.USERNAME or not config.PASSWORD:
            raise RuntimeError(
                "VOICELINK_USER / VOICELINK_PASSWORD não configurados. "
                "Copie .env.example para .env e preencha as credenciais."
            )

        self.session = auth.login_voicelink(config.USERNAME, config.PASSWORD)
        if self.session is None:
            raise RuntimeError("Login falhou: usuário ou senha inválidos.")

        self._logged_in = True
        log.info("Login realizado com sucesso.")

    def ensure_login(self):
        if not self._logged_in:
            self.login()

    def _get_json(self, path: str, params: dict) -> dict:
        url = f"{config.BASE_URL}{path}"
        resp = self.session.get(
            url, params=params, verify=config.VERIFY_SSL,
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()

    # --- Os 5 endpoints mapeados ------------------------------------------

    def get_resumo_tarefa(self) -> dict:
        return self._get_json(
            "/selection/assignment/getSummaryData.action",
            {
                "rowCount": 5000, "viewId": -1105, "firstTimeRun": "true",
                "rowsPerPage": 24, "refreshRequest": "true", "firstRowId": 0,
                "sortColumn": "region.name", "sortAsc": "true",
                "tempSiteID": -927, "startIndex": 0,
                "submittedFilterCriterion": "",
            },
        )

    def get_resumo_trabalho(self) -> dict:
        return self._get_json(
            "/selection/workgroup/getSummaryData.action",
            {
                "rowCount": 5000, "viewId": -1106, "firstTimeRun": "true",
                "rowsPerPage": 24, "refreshRequest": "true", "firstRowId": 0,
                "tempSiteID": -927, "startIndex": 0,
                "submittedFilterCriterion": "",
            },
        )

    def get_produtividade_regiao(self) -> dict:
        return self._get_json(
            "/selection/assignment/getSummaryData.action",
            {
                "rowCount": 5000, "viewId": -1016, "firstTimeRun": "true",
                "rowsPerPage": 24, "refreshRequest": "true", "firstRowId": 0,
                "sortColumn": "region.name", "sortAsc": "true",
                "tempSiteID": -927, "startIndex": 0,
                "submittedFilterCriterion": "",
            },
        )

    def get_produtos_falta(self) -> dict:
        return self._get_json(
            "/selection/short/getSummaryData.action",
            {
                "rowCount": 5000, "viewId": -1107, "firstTimeRun": "true",
                "rowsPerPage": 24, "refreshRequest": "true", "firstRowId": 0,
                "sortColumn": "region.name", "sortAsc": "true",
                "tempSiteID": -927, "startIndex": 0,
                "submittedFilterCriterion": "",
            },
        )

    def get_atribuicoes(self, region_number: int) -> dict:
        """Detalhe das atribuições de uma região (seção 5.2).

        ATENÇÃO: esta é a ÚNICA chamada do coletor que traz dados de
        cliente (nome, endereço, customerNumber) na resposta. Nada disso
        pode sair daqui: quem trata o retorno é
        `parse_atribuicoes_sem_pii`, que monta os registros a partir de
        uma allowlist. Não passe este payload para nenhum outro lugar.

        Só é chamada quando COLLECT_ORDER_COUNTS estiver ligado, e num
        intervalo bem mais espaçado que os outros endpoints.
        """
        import json

        filtro = json.dumps({
            "viewId": "-1009",
            "id": "0",
            "columnId": "-12109",
            "operandId": "-11",
            "value1": str(region_number),
            "value2": "",
            "locked": False,
        })
        return self._get_json(
            "/selection/assignment/getAssignmentData.action",
            {
                "rowCount": 5000, "viewId": -1009, "firstTimeRun": "true",
                "rowsPerPage": 24, "refreshRequest": "true", "firstRowId": 0,
                "sortColumn": "region.name", "sortAsc": "true",
                "tempSiteID": -927, "startIndex": 0,
                "submittedFilterCriterion": filtro,
            },
        )

    def get_produtividade_operador(self, region_number: int) -> dict:
        """Chamada de produtividade por operador é filtrada por região —
        precisa de uma chamada por região (padrão observado no navegador)."""
        import json
        import urllib.parse

        filtro = json.dumps({
            "viewId": "-1022",
            "id": "0",
            "columnId": "-12109",
            "operandId": "-11",
            "value1": str(region_number),
            "value2": "",
            "locked": False,
        })
        return self._get_json(
            "/selection/labor/getOperatorLaborSummaryData.action",
            {
                "rowCount": 5000, "viewId": -1022, "firstTimeRun": "true",
                "rowsPerPage": 24, "refreshRequest": "true", "firstRowId": 0,
                "sortColumn": "region.name", "sortAsc": "true",
                "startIndex": 0,
                "submittedFilterCriterion": filtro,
            },
        )


# --- Parsers: JSON do VoiceLink -> dicts prontos para o banco ----------

def parse_resumo_tarefa(payload: dict) -> list:
    out = []
    for obj in payload.get("objects", []):
        region = obj.get("region", {})
        out.append({
            "region_number": region.get("number"),
            "region_name": region.get("name"),
            "total": obj.get("totalAssignments"),
            "em_andamento": obj.get("inProgress"),
            "disponivel": obj.get("available"),
            "concluido": obj.get("complete"),
            "nao_concluido": obj.get("nonComplete"),
        })
    return out


def parse_resumo_trabalho(payload: dict) -> list:
    out = []
    for obj in payload.get("objects", []):
        region = obj.get("region", {})
        out.append({
            "region_number": region.get("number"),
            "region_name": region.get("name"),
            "operadores_trabalhando": obj.get("operatorsWorkingIn"),
            "operadores_atribuidos": obj.get("operatorsAssigned"),
            "itens_restantes": obj.get("totalItemsRemaining"),
            "itens_selecionados": obj.get("totalItemsPicked"),
            "estimado_concluido": obj.get("estimatedCompleted"),
            "meta_regiao": region.get("goalRate"),
        })
    return out


def parse_produtividade_regiao(payload: dict) -> list:
    out = []
    for obj in payload.get("objects", []):
        region = obj.get("region", {})
        out.append({
            "region_number": region.get("number"),
            "region_name": region.get("name"),
            "quantidade_total": obj.get("totalQuantity"),
            "produtividade_atual": obj.get("actualRate"),
            "numero_operadores": obj.get("numberOfOperators"),
            "pct_meta": obj.get("percentOfGoal"),
            "tempo_total": obj.get("totalTime"),
            "meta": obj.get("goalRate"),
        })
    return out


def parse_produtos_falta(payload: dict) -> list:
    out = []
    for obj in payload.get("objects", []):
        region = obj.get("region", {})
        out.append({
            "region_number": region.get("number"),
            "region_name": region.get("name"),
            "total_faltas": obj.get("totalShorts"),
            "em_falta": obj.get("shorted"),
            "atribuido": obj.get("assigned"),
            "marcado": obj.get("markedout"),
        })
    return out


def parse_produtividade_operador(payload: dict, region_number: int, region_name: str) -> list:
    """Aplica a regra de negócio: só operadores com quantidade > 0.
    A coluna 'Função' (filterType) é intencionalmente descartada."""
    out = []
    for obj in payload.get("objects", []):
        qtd = obj.get("totalQuantity") or 0
        if qtd <= 0:
            continue
        operador = obj.get("operator", {}).get("common", {}).get("operatorIdentifier", "")
        out.append({
            "region_number": region_number,
            "region_name": region_name,
            "operador_id": operador,
            "quantidade": qtd,
            "tempo_total": obj.get("totalTime"),
            "meta": obj.get("goalRate"),
            "produtividade_real": obj.get("actualRate"),
            "pct_meta": obj.get("percentOfGoal"),
        })
    return out


def parse_atribuicoes_sem_pii(payload: dict, region_number: int, region_name: str) -> list:
    """Extrai SÓ a contagem de pedidos por operador, descartando toda PII.

    O payload de origem contém dados de cliente. A regra da seção 5.2 é
    inegociável: nome, endereço e customerNumber não podem ser gravados
    em lugar nenhum.

    A garantia aqui é estrutural, não uma questão de disciplina: este
    parser monta um dicionário NOVO com quatro campos fixos, em vez de
    copiar o objeto de origem e apagar o que não presta. Uma allowlist
    não vaza um campo novo que a Honeywell resolva adicionar num update
    do VoiceLink; uma blocklist vazaria. Se um dia for preciso mais um
    campo aqui, ele entra escrito à mão nesta função — e aí alguém
    precisa olhar para o que está adicionando.

    `pedido_ref` é o id numérico interno da atribuição (não o número do
    pedido do cliente), usado só para não contar a mesma atribuição duas
    vezes entre coletas.
    """
    registros = []
    for obj in payload.get("objects", []):
        operador = (
            obj.get("operator", {}).get("common", {}).get("operatorIdentifier")
        )
        referencia = obj.get("id")
        # Sem operador não dá para atribuir o pedido a ninguém, e sem
        # referência não dá para deduplicar entre coletas.
        if not operador or referencia is None:
            continue

        registros.append({
            "region_number": region_number,
            "region_name": region_name,
            "operador_id": str(operador),
            "pedido_ref": str(referencia),
            "status": obj.get("status"),
        })
    return registros


# --- Ciclo de coleta -----------------------------------------------------

def coletar_pedidos(vl: VoiceLinkSession):
    """Coleta a contagem de pedidos por operador (seção 5.2).

    Roda no seu próprio ritmo, bem mais devagar que o ciclo principal —
    é a chamada mais pesada do conjunto.
    """
    total = 0
    for region_number, region_name in config.REGIONS.items():
        payload = vl.get_atribuicoes(region_number)
        registros = parse_atribuicoes_sem_pii(payload, region_number, region_name)
        db.insert_pedidos_operador(registros)
        total += len(registros)
    log.info("Pedidos coletados: %d atribuições (sem dados de cliente).", total)
    return total


def run_once(vl: VoiceLinkSession):
    vl.ensure_login()

    tarefa = parse_resumo_tarefa(vl.get_resumo_tarefa())
    db.insert_resumo_tarefa(tarefa)

    trabalho = parse_resumo_trabalho(vl.get_resumo_trabalho())
    db.insert_resumo_trabalho(trabalho)

    prod_regiao = parse_produtividade_regiao(vl.get_produtividade_regiao())
    db.insert_produtividade_regiao(prod_regiao)

    falta = parse_produtos_falta(vl.get_produtos_falta())
    db.insert_produtos_falta(falta)

    operadores_total = []
    for region_number, region_name in config.REGIONS.items():
        payload = vl.get_produtividade_operador(region_number)
        operadores_total.extend(
            parse_produtividade_operador(payload, region_number, region_name)
        )
    db.insert_produtividade_operador(operadores_total)

    db.log_coleta(sucesso=True, detalhe=f"{len(operadores_total)} operadores ativos")
    log.info(
        "Coleta concluída: %d regiões (tarefa), %d operadores ativos.",
        len(tarefa), len(operadores_total),
    )


def main():
    db.init_db()
    vl = VoiceLinkSession()

    once = "--once" in sys.argv

    # Retenção de histórico (config.RETENCAO_DIAS dias): limpa uma vez na
    # subida e depois no máximo 1x por dia — apagar a cada ciclo de 60s
    # seria desperdício de banco.
    try:
        apagados = db.limpar_historico_antigo(dias=config.RETENCAO_DIAS)
        log.info(
            "Limpeza de histórico (>%d dias): %d linhas apagadas (%s)",
            config.RETENCAO_DIAS, sum(apagados.values()), apagados,
        )
    except Exception as exc:  # noqa: BLE001 - limpeza não pode derrubar o coletor
        log.error("Falha na limpeza inicial do histórico: %s", exc)
    ultima_limpeza = time.monotonic()

    if config.COLLECT_ORDER_COUNTS:
        log.info(
            "Coleta de pedidos LIGADA (a cada %ds). Só a contagem por "
            "operador é gravada; dados de cliente são descartados no parser.",
            config.ORDER_POLL_INTERVAL_SECONDS,
        )

    # Marca o último instante em que os pedidos foram coletados. Começa em
    # 0 para a primeira coleta acontecer já no primeiro ciclo.
    ultima_coleta_pedidos = 0.0

    while True:
        try:
            run_once(vl)
        except Exception as exc:  # noqa: BLE001 - queremos logar qualquer falha e seguir
            log.error("Falha na coleta: %s", exc)
            db.log_coleta(sucesso=False, detalhe=str(exc))
            # Se a sessão expirou, força novo login na próxima tentativa
            vl._logged_in = False

        # Retenção de histórico: no máximo 1x por dia (a primeira já
        # rodou na subida). Em try separado de propósito — falha de
        # limpeza não pode interromper a coleta.
        if time.monotonic() - ultima_limpeza >= 24 * 60 * 60:
            try:
                db.limpar_historico_antigo(dias=config.RETENCAO_DIAS)
                ultima_limpeza = time.monotonic()
                log.info("Limpeza diária do histórico concluída.")
            except Exception as exc:  # noqa: BLE001
                log.error("Falha na limpeza diária do histórico: %s", exc)

        # A coleta de pedidos tem o seu próprio relógio, bem mais lento.
        # Fica num try separado de propósito: se ela falhar, o ciclo
        # principal (que é o que alimenta o painel de tempo real) segue
        # normalmente.
        if config.COLLECT_ORDER_COUNTS:
            agora = time.monotonic()
            if agora - ultima_coleta_pedidos >= config.ORDER_POLL_INTERVAL_SECONDS:
                try:
                    coletar_pedidos(vl)
                    ultima_coleta_pedidos = agora
                except Exception as exc:  # noqa: BLE001
                    log.error("Falha na coleta de pedidos: %s", exc)
                    # Não zera o relógio: erra e tenta de novo no próximo
                    # intervalo, em vez de insistir a cada 60s.
                    ultima_coleta_pedidos = agora

        if once:
            break
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
