# Control Tower — Vocollect VoiceLink v5.2

Painel em tempo real da operação de seleção (picking), sem prints de tela.
Dados extraídos diretamente da API interna do VoiceLink, atualizados a
cada minuto.

## Arquitetura

```
VoiceLink (Honeywell)
      │  5 chamadas GET/POST autenticadas, a cada 60s
      ▼
collector.py  (roda sozinho, em background)
      │  grava snapshots com timestamp
      ▼
control_tower.db  (SQLite)
      │  o app só LÊ, nunca chama o VoiceLink
      ▼
app.py  (Streamlit — o dashboard que todo mundo acessa)
```

O coletor e o dashboard são **processos separados de propósito**: o
coletor roda uma vez só, gravando no banco; quantas pessoas quiserem
podem abrir o dashboard ao mesmo tempo sem multiplicar as chamadas ao
VoiceLink.

## Instalação

```bash
cd control_tower_voicelink
pip install -r requirements.txt
```

## Configuração

1. Copie `.env.example` para `.env`:
   ```bash
   cp .env.example .env
   ```
2. Edite `.env` e preencha `VOICELINK_USER` e `VOICELINK_PASSWORD` com
   uma conta de serviço do VoiceLink (recomendado: peça à TI uma conta
   dedicada, em vez de usar seu login pessoal).

## Coletor em PowerShell (PC corporativo sem Python)

Para o PC corporativo bloqueado (sem Python, sem admin, sem executáveis
desconhecidos), existe o `coletor.ps1` — coletor nativo em PowerShell
que faz a MESMA coleta do `collector.py` (login no VoiceLink, os 5
endpoints, parsers idênticos campo a campo, inclusive a allowlist de PII
da seção 5.2) e grava direto na API REST do Supabase.

Configuração: crie um arquivo `coletor.config.ps1` na mesma pasta (está
no `.gitignore` — **nunca** commitar; o repositório é público):

```powershell
$VOICELINK_USER     = "usuario_de_servico"
$VOICELINK_PASSWORD = "senha"
$SUPABASE_KEY       = "chave-do-supabase-com-permissao-de-INSERT"
```

Também vale variável de ambiente (`CT_VOICELINK_USER`,
`CT_VOICELINK_PASSWORD`, `CT_SUPABASE_KEY`). Para rodar (sem admin):

```powershell
powershell -ExecutionPolicy Bypass -File coletor.ps1
```

Requisitos: as tabelas precisam existir no Supabase com as mesmas
colunas do `init_db()` (rode uma vez o `collector.py` com `DATABASE_URL`
apontando para o projeto), e a chave precisa poder inserir nelas. Rode
OU o `coletor.ps1` OU o `collector.py` contra o mesmo banco — nunca os
dois ao mesmo tempo, senão os snapshots duplicam.

## Banco de dados: SQLite local ou PostgreSQL (Supabase)

Por padrão o projeto usa SQLite local (`control_tower.db`), sem servidor
nenhum. Para ambientes sem disco persistente (ex.: Streamlit Cloud), ou
quando coletor e painel rodam em máquinas diferentes, defina
`DATABASE_URL` no `.env` (ou nos Secrets do Streamlit Cloud) com uma
conexão PostgreSQL, ex.:

    DATABASE_URL=postgresql+psycopg2://usuario:senha@host:5432/postgres

As tabelas e índices são criados automaticamente na inicialização, em
qualquer backend. O SQL das queries é escrito para funcionar nos dois
(parâmetros nomeados, `substr` em vez de `date()`/`strftime`); os pontos
em que os dialetos divergem (DDL, upsert, janela das "últimas 8h") são
ramificados dentro do `database.py`.

Retenção: o coletor apaga snapshots com mais de `RETENCAO_DIAS` dias
(padrão 60) — uma vez na subida e depois no máximo 1x por dia, via
`limpar_historico_antigo()`.

No Streamlit Cloud o coletor NÃO roda (a plataforma só executa o app
quando alguém acessa): deixe o coletor rodando numa máquina da empresa
apontando para o MESMO `DATABASE_URL`, e o app da nuvem lê o mesmo
banco.

## Rodando

Abra **dois terminais**:

**Terminal 1 — coletor** (fica rodando o tempo todo, em background):
```bash
python collector.py
```

**Terminal 2 — dashboard**:
```bash
streamlit run app.py
```

O painel abre em `http://localhost:8501`. Para acessar de outros
computadores/TVs na mesma rede da empresa, use o IP da máquina que está
rodando o Streamlit, ex: `http://10.x.x.x:8501`.

Atenção: o hot-reload do Streamlit só reexecuta o `app.py` (e as
páginas). Mudanças em módulos importados (`ui.py`, `presentation.py`,
`database.py`, `config.py`) **só entram no ar reiniciando o processo** do
Streamlit — sem isso o servidor continua servindo a versão antiga do
módulo, e o painel passa a misturar código novo com velho.

## As duas telas

**Tempo Real** (`app.py`) — a tela que abre por padrão. Visão geral das
4 regiões: itens selecionados/restantes, produtividade por região,
operadores em produção, produtos em falta e a curva das últimas 8h.

### Acesso ao painel

O painel abre **direto**, sem tela de login: quem tiver acesso à URL (na
rede interna ou via VPN) vê as métricas. O controle de acesso fica por
conta da rede — por isso é importante NÃO expor o Streamlit à internet
(a seção de segurança tem os porquês). O `auth.py` continua no projeto:
é a autenticação que o coletor usa contra o VoiceLink.

**Histórico por Região** (`pages/1_Historico.py`) — um painel por região,
no estilo dos painéis de produtividade já usados na fábrica:

- filtro de data em abas clicáveis: **ano → mês → dia** (só aparecem
  datas que realmente têm coleta);
- **Top 5 Separação** e **Top 5 Produtividade**, lado a lado;
- **8 cards de KPI**: linha *Dia* e linha *Mês*, cada uma com Qtd
  Separada, Qtda Pedidos, Itens/Pedido e Separado/Hora — este último
  comparado com a meta da região (verde ▲ acima, vermelho ▼ abaixo);
- **Separação/Dia** (total por dia ao longo do mês) e
  **Produtividade/Dia** (hora a hora do dia selecionado).

### Logo do cabeçalho

As duas telas mostram `logo.png` no canto superior esquerdo, ao lado do
título. Para trocar, é só substituir o arquivo (ou apontar `LOGO_PATH`
no `.env` para outro caminho) e reiniciar o Streamlit — a imagem fica em
cache para não ser relida a cada atualização de tela. Se o arquivo não
existir, o cabeçalho aparece só com o título.

O painel inteiro usa o tema claro — fundo da página `#f9f9f7` em `ui.py`,
com o tema do Streamlit combinando em `.streamlit/config.toml`. A logo é
predominantemente azul-marinho (`#002040`) e laranja, cores que aparecem
com folga sobre o fundo claro, então ela é exibida direto, sem placa. Se
um dia a logo mudar para uma versão clara (dessas feitas para fundo
escuro), é o caso de reintroduzir uma placa escura atrás dela: a regra é
a `.ct-logo` no `ui.py`.

### Modo apresentação (TV do chão de fábrica)

Na barra lateral, o multiselect **Regiões na rotação** escolhe quais
regiões o modo apresentação percorre (padrão: todas). A visão geral
(Tempo Real) entra sempre, antes dos painéis de região — dá para deixar
só uma região, duas, ou nenhuma (aí a TV fica só na visão geral). Com a
seleção feita, o toggle **Modo apresentação** liga a rotação automática
a cada N segundos (padrão 15s, ajustável no próprio toggle). Nesse modo
a navegação lateral some e fica só uma faixa fina no topo com o botão
**⏹ Sair**, para voltar ao modo interativo sem reiniciar nada.

No modo apresentação os tamanhos crescem em três camadas (tudo no
`ui.py`): o `font-size` base do `html` vai a 22px — é o que escala as
células das tabelas, que o Streamlit desenha em canvas e não aceitam
CSS —, o CSS sobe os px dos elementos nativos e das classes `ct-*`, e as
telas pedem `ampliar=True` nos gráficos Plotly (o SVG deles também não
responde a CSS). NÃO use `zoom` para ampliar a página: sob zoom o layout
de colunas do Streamlit quebra e os gráficos invadem as tabelas
vizinhas (verificado em navegador real).

Para deixar numa TV: abra o painel no navegador, ligue o modo
apresentação e aperte F11 (tela cheia).

### Ver o painel antes de ter histórico

O filtro de data só enxerga dias em que o coletor esteve rodando — não
dá para reconstruir o passado. Para conhecer a tela antes disso, dá para
gerar um banco de demonstração separado:

```bash
python seed_demo.py
```

```powershell
# PowerShell — aponta o painel para o banco de demonstração
$env:DB_PATH="control_tower_demo.db"; streamlit run app.py
```

Ele cria `control_tower_demo.db` com 12 dias de dados fictícios e **não
encosta** no `control_tower.db` de produção.

### Testar sem acesso ao VoiceLink

`python collector.py --once` roda uma única coleta e sai — útil para
testar login e conexão antes de deixar rodando em loop.

`python test_offline.py` roda os testes dos parsers e das agregações com
dados de exemplo reais (sem precisar de rede).

`python test_ui.py` renderiza as duas telas de ponta a ponta e falha se
alguma levantar exceção (precisa do `seed_demo.py` rodado antes).

## Contagem de pedidos por operador ("Qtda Pedido") — LEIA ANTES DE LIGAR

Esta é a única parte do projeto que está **implementada mas desligada**,
e a decisão de ligar é sua, não do código.

A coluna "Qtda Pedido" e os KPIs derivados dela (Qtda Pedidos e
Itens/Pedido) precisam de uma contagem de pedidos por operador. Os 5
endpoints usados na rotina **não** trazem esse número. O único que traz é
o de detalhe de atribuições (`getAssignmentData.action`) — que também
devolve **nome, endereço e CNPJ do cliente**.

O que foi feito:

- o parser (`parse_atribuicoes_sem_pii`) monta um registro **novo** com
  exatamente 4 campos — operador, região, status e o id interno da
  atribuição. Nenhum campo de cliente é copiado. É uma *allowlist*, não
  uma lista de exclusão: se a Honeywell adicionar um campo novo num
  update do VoiceLink, ele simplesmente não passa;
- `test_offline.py` tem um teste que joga um payload cheio de PII no
  parser e falha se qualquer fragmento sobreviver;
- a coleta roda a cada **15 min** (e não a cada 60s), porque é a chamada
  mais pesada — uma única região trouxe 155 registros na amostra real;
- com isso desligado, o painel funciona normalmente e essas três células
  aparecem como "—", em vez de zero.

**Antes de ligar**, vale o passo que a especificação pede primeiro: abrir
a aba Network do navegador na tela de Produtividade por operador do
VoiceLink e conferir se algum dos endpoints já usados não traz essa
contagem de um jeito mais barato (algo como `totalOrders` ou
`numberOfAssignments`). Não deu para checar isso daqui — exige acesso ao
VoiceLink. Se existir, é melhor puxar de lá e deixar esta coleta
desligada para sempre.

Para ligar, no `.env`:

```
COLLECT_ORDER_COUNTS=true
```

## O que falta decidir com a TI

- **Conta de serviço**: usuário/senha dedicados para o coletor (evita
  usar credenciais pessoais e usar o mesmo usuário logado no
  navegador).
- **Onde rodar o coletor 24/7**: idealmente um servidor/máquina sempre
  ligada na rede da empresa — não a estação de trabalho de uma pessoa.
- **Retenção de dados**: o banco cresce continuamente (um snapshot por
  minuto). Vale definir uma rotina de limpeza/arquivamento de dados
  antigos (ex.: manter só os últimos 90 dias na tabela ativa).

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `config.py` | URLs, credenciais (via `.env`), regiões, intervalos |
| `auth.py` | Login contra o VoiceLink, usado pelo coletor |
| `database.py` | Schema SQLite e todas as queries (única camada que fala SQL) |
| `collector.py` | Login + as 5 chamadas ao VoiceLink + parsers + gravação |
| `app.py` | Tela de Tempo Real (Streamlit) — só lê do banco |
| `pages/1_Historico.py` | Painel Histórico por Região — só lê do banco |
| `ui.py` | Paleta, CSS, cards de KPI, avatares e padrão dos gráficos |
| `presentation.py` | Modo apresentação vs estático e a rotação entre telas |
| `seed_demo.py` | Gera banco de demonstração (ferramenta de dev) |
| `test_offline.py` | Testes dos parsers e das agregações, sem rede |
| `test_ui.py` | Renderiza as telas e falha se alguma quebrar |

## Como os números são calculados

Vale saber disto antes de mexer nas queries, porque é onde é fácil errar
sem perceber: **os contadores do VoiceLink são acumulados do dia, não
incrementos**. O snapshot das 14h já contém tudo que foi feito desde o
começo do turno. Então:

- o total de um dia é o **maior** valor observado no dia, nunca a soma
  dos snapshots (somar 1 snapshot por minuto multiplicaria por ~600);
- as **taxas** vêm do **último** snapshot do dia — é a média do dia
  fechado. Pegar o máximo daria o pico artificial dos primeiros minutos,
  quando o denominador de tempo ainda é quase zero;
- a produção de **uma hora** é a diferença entre o acumulado do fim e o
  do começo daquela hora;
- `totalTime` é a soma de **horas-operador**, não relógio de parede (5
  pessoas por 1h = 5h). Por isso a produtividade do painel está em
  *itens por hora-operador* — é a mesma unidade da meta (`goalRate`), e é
  o que torna a comparação com a meta válida. Confirmado contra a amostra
  real: 10727 itens ÷ 12:46:23 = 839,81/h = 62,21% de 1350, exatamente os
  números que o VoiceLink devolve.

Tudo isso está implementado em `database.py` e coberto por
`test_offline.py`.

## Endpoints do VoiceLink usados

| Endpoint | Quadro |
|---|---|
| `POST /j_spring_security_check` | Login (Spring Security) |
| `GET /selection/assignment/getSummaryData.action?viewId=-1105` | Resumo da Tarefa |
| `GET /selection/workgroup/getSummaryData.action?viewId=-1106` | Resumo do Trabalho Atual |
| `GET /selection/assignment/getSummaryData.action?viewId=-1016` | Produtividade por Região |
| `GET /selection/short/getSummaryData.action?viewId=-1107` | Produtos em Falta |
| `GET /selection/labor/getOperatorLaborSummaryData.action?viewId=-1022` | Produtividade por Operador (1 chamada por região) |
