"""
Configuração central do Control Tower - Vocollect VoiceLink v5.2

Todas as credenciais são lidas de variáveis de ambiente — NUNCA deixe
usuário/senha escritos diretamente neste arquivo.

Antes de rodar, defina (Windows PowerShell):
    $env:VOICELINK_USER = "usuario_de_servico"
    $env:VOICELINK_PASSWORD = "senha_aqui"

Ou crie um arquivo .env na raiz do projeto (veja .env.example) e use
python-dotenv (já incluso no requirements.txt).
"""
import os
from dotenv import load_dotenv

load_dotenv()  # carrega variáveis de um arquivo .env, se existir

# --- Conexão com o VoiceLink ---------------------------------------------
BASE_URL = os.getenv("VOICELINK_BASE_URL", "https://172.24.232.145:9444/VoiceLink")
USERNAME = os.getenv("VOICELINK_USER", "")
PASSWORD = os.getenv("VOICELINK_PASSWORD", "")

# Certificado da rede interna é autoassinado -> desabilita verificação SSL.
# Isso é aceitável apenas porque o servidor é interno (172.24.x.x) e não
# está exposto à internet. Não faça isso para servidores públicos.
VERIFY_SSL = False

# --- Regiões monitoradas ---------------------------------------------------
# region.number, usado no filtro do endpoint de produtividade por operador
REGIONS = {
    6: "Reg Foods",
    7: "Reg Caixas",
    8: "Reg Bolsas",
    9: "Reg de caixas com etiquetas",
}

# --- Coletor -----------------------------------------------------------
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
REQUEST_TIMEOUT_SECONDS = 15

# --- Contagem de pedidos por operador (seção 5.2) -------------------------
# DESLIGADO POR PADRÃO, de propósito.
#
# A contagem de pedidos ("Qtda Pedido") vem do endpoint de detalhe de
# atribuições, que é o único que devolve dados de cliente (nome, endereço,
# customerNumber). O parser descarta esses campos antes de qualquer
# gravação — mas a chamada em si continua trafegando PII, então ligar isso
# é uma decisão consciente de quem opera, não um padrão.
#
# Antes de ligar, vale o passo 1 da seção 5.2: conferir na aba Network do
# navegador se algum dos 5 endpoints já mapeados não traz essa contagem
# de um jeito mais barato (algo como totalOrders ou numberOfAssignments).
# Se trouxer, é melhor usar de lá e deixar isto desligado para sempre.
#
# Com isto desligado o painel funciona normalmente: a coluna "Qtda Pedido"
# e os KPIs derivados dela aparecem como "—".
COLLECT_ORDER_COUNTS = os.getenv("COLLECT_ORDER_COUNTS", "false").lower() in ("1", "true", "yes", "sim")

# Esse endpoint é bem mais pesado que os outros (uma única região trouxe
# 155 registros no exemplo real), então roda num intervalo bem mais
# espaçado que os 60s dos demais.
ORDER_POLL_INTERVAL_SECONDS = int(os.getenv("ORDER_POLL_INTERVAL_SECONDS", "900"))

# --- Dashboard -----------------------------------------------------------
# Modo apresentação: segundos que cada tela fica no ar antes de rodar
# para a próxima (seção 5.4).
PRESENTATION_INTERVAL_SECONDS = int(os.getenv("PRESENTATION_INTERVAL_SECONDS", "15"))

# De quanto em quanto tempo as telas releem o banco no modo estático.
DASHBOARD_REFRESH_SECONDS = int(os.getenv("DASHBOARD_REFRESH_SECONDS", "15"))

# Logo exibida no cabeçalho das duas telas. Se o arquivo não existir, o
# cabeçalho aparece só com o título — não quebra nada.
LOGO_PATH = os.getenv("LOGO_PATH", os.path.join(os.path.dirname(__file__), "logo.png"))

# --- Banco de dados ------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "control_tower.db"))
