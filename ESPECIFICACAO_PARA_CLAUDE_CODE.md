# Control Tower — Vocollect VoiceLink v5.2 — Especificação para desenvolvimento

> Este documento é para o **Claude Code** implementar o projeto. Um protótipo
> inicial (`control_tower_voicelink/`) já foi criado e testado com dados
> reais extraídos do VoiceLink — use-o como base em vez de recomeçar do zero.
> Os parsers e o schema do banco já foram validados (`test_offline.py` passa
> 100%). O que falta é: painel histórico por região, modo apresentação, e as
> duas pendências de dados descritas na seção 5.

---

## 1. Objetivo

Substituir a coleta manual por print de tela por um pipeline automático que:
1. Autentica no VoiceLink e coleta dados a cada 60s (coletor Python, já pronto)
2. Grava tudo em SQLite com timestamp (schema já pronto)
3. Exibe em um dashboard Streamlit com **duas visões**:
   - **Tempo real** (página principal) — já implementada no protótipo
   - **Histórico por região** (nova, estilo dos painéis PepsiCo anexados) — a construir
4. Tem um **modo apresentação** (rotação automática, estilo TV de chão de
   fábrica) alternável com o **modo estático** (navegação manual) — a construir

## 2. Arquitetura (já implementada, não mudar)

```
VoiceLink (Honeywell)
      │  5 chamadas GET/POST autenticadas, a cada 60s
      ▼
collector.py  (processo independente, roda em loop)
      │  grava snapshots com timestamp
      ▼
control_tower.db  (SQLite)
      │  o dashboard só LÊ, nunca chama o VoiceLink
      ▼
app.py  (Streamlit)
```

Importante manter essa separação: o coletor grava; o(s) dashboard(s) só leem.
Isso permite abrir o painel em vários monitores/TVs sem multiplicar chamadas
ao VoiceLink.

## 3. Autenticação e endpoints (mapeados e confirmados manualmente, um por um, contra o VoiceLink real — não são suposições)

| # | Endpoint | Método | Uso |
|---|---|---|---|
| Login | `POST {BASE_URL}/j_spring_security_check` | POST | Campos `j_username`, `j_password`. Sem token CSRF. Spring Security padrão. |
| Resumo da Tarefa | `GET {BASE_URL}/selection/assignment/getSummaryData.action?viewId=-1105` | GET | Total, Em andamento, Disponível, Concluído por região |
| Resumo do Trabalho | `GET {BASE_URL}/selection/workgroup/getSummaryData.action?viewId=-1106` | GET | Itens Restantes, Operadores Trabalhando/Atribuídos, Itens Selecionados |
| Produtividade por Região | `GET {BASE_URL}/selection/assignment/getSummaryData.action?viewId=-1016` | GET | % Meta, Produtividade Atual, Meta, Quantidade Total, Nº Operadores |
| Produtos em Falta | `GET {BASE_URL}/selection/short/getSummaryData.action?viewId=-1107` | GET | Total, Em falta, Atribuído, Marcado (base para Pareto) |
| Produtividade por Operador | `GET {BASE_URL}/selection/labor/getOperatorLaborSummaryData.action?viewId=-1022` | GET | Uma chamada **por região**, filtrando via `submittedFilterCriterion` com `value1 = region.number` |

`BASE_URL = https://172.24.232.145:9444/VoiceLink` (rede interna, IP pode
variar por ambiente — deixar configurável). SSL é autoassinado, `verify=False`
necessário (já implementado).

Mapeamento `region.number`: Reg Foods=6, Reg Caixas=7, Reg Bolsas=8,
Reg de caixas com etiquetas=9. Metas (`goalRate`) confirmadas por região:
Reg Bolsas=1350, Reg Caixas=336, Reg Foods=50, Reg de caixas com
etiquetas=300 — essas batem com os painéis PepsiCo existentes (confirmação
cruzada de que os dados estão corretos).

### Endpoint que existe mas NÃO deve ser usado no coletor de rotina

`GET {BASE_URL}/selection/assignment/getAssignmentData.action?viewId=-1009`
— retorna o detalhe de cada atribuição/pedido individual, incluindo
**dados de cliente** (nome, endereço, CPF/CNPJ embutido). Fora do escopo do
Control Tower. **Exceção controlada** descrita na seção 5.2: pode ser usado
só para *contar* pedidos por operador, sem persistir nenhum campo de
cliente.

## 4. Regras de negócio (já implementadas no protótipo, manter)

- Na tabela de produtividade por operador: **remover a coluna Função**
  (`filterType`) e **excluir operadores com quantidade produzida = 0**.
- Cada ciclo de coleta grava um snapshot com o mesmo `captured_at` para
  todas as tabelas (permite juntar os dados de um mesmo instante).
- O dashboard nunca chama o VoiceLink — só lê do banco.

## 5. O que falta construir

### 5.1. Painel Histórico por Região (nova tela)

Estilo dos 3 painéis PepsiCo enviados como referência (fotos anexadas na
conversa original — "Painel de Produtividade - Região Bolsas/Caixas/Caixa
com Etiqueta"). Um painel por região, com:

**Filtro de data no topo:** seletor de ano → mês → dia (abas clicáveis,
como nos painéis de referência). Default: dia atual (D) ou D-1, a definir
com o usuário se não estiver claro no protótipo.

**Duas tabelas Top 5 lado a lado:**
- *Top 5 — Separação*: ranking dos 5 operadores com maior quantidade
  separada no período filtrado. Colunas: foto, nome/ID, Qtda Total
  (itens), Qtda Pedido (nº de pedidos — ver 5.2).
- *Top 5 — Produtividade*: ranking dos 5 operadores com maior produtividade
  (itens/hora) no período. Colunas: foto, nome/ID, Produtividade.

**4 cards de KPI em grade 2x2**, comparando com a meta (`goalRate` da
região), replicando o padrão dos painéis de referência:
- Linha "Dia": Qtd Separada, Qtda Pedidos, [unidade]/Pedido, Separado/Hora
  (com % vs meta, cor verde se acima, vermelho se abaixo — ver exemplo
  "Meta: 1350 (-34,75%)" no painel de referência).
- Linha "Mês": mesmas 4 métricas, acumuladas no mês.

**Dois gráficos na parte inferior:**
- *Separação/Dia*: total separado por dia, acumulado ao longo dos últimos
  dias do mês filtrado (gráfico de área, eixo X = dias).
- *Produtividade/Dia*: produtividade hora a hora **do dia selecionado**
  (gráfico de área, eixo X = horas 0–23, valores zerados fora do turno,
  como no exemplo de referência).

Essas agregações (diária, mensal, por hora) devem ser calculadas via query
SQL sobre as tabelas já existentes (`resumo_trabalho`,
`produtividade_operador` etc.) agrupando por data/hora do `captured_at` —
não é necessário criar tabelas novas além do que a seção 5.2 exige.

### 5.2. Contagem de pedidos por operador (`Qtda Pedido`)

**Decisão do usuário: antes de recorrer ao endpoint com PII, investigar se
o VoiceLink expõe essa contagem em algum lugar mais simples.** Passos
recomendados, nesta ordem:

1. **Testar primeiro** se algum dos 5 endpoints já mapeados (ou variações
   próximas de `viewId`) já trazem uma contagem de pedidos por operador
   sem precisar do endpoint de detalhe. Vale inspecionar de novo a aba
   Network do navegador enquanto o usuário navega até a tela "Produtividade"
   por operador do VoiceLink — pode existir uma coluna ou um campo
   (`totalOrders`, `numberOfAssignments`, etc.) que passou despercebido nos
   payloads já coletados.
2. **Se não existir**, a alternativa é o endpoint de detalhe
   `getAssignmentData.action?viewId=-1009`, que também traz dados de
   cliente. Nesse caso, a regra é obrigatória: o parser deve extrair
   **apenas** `operator.common.operatorIdentifier`, `region`, `status` e um
   identificador não-PII do pedido (ex: `id` numérico interno) — e
   descartar imediatamente `customerInfo` (nome, endereço,
   `customerNumber`) antes de qualquer gravação no banco. Nunca persistir
   esses campos. Se o volume dessa chamada for grande (no exemplo real
   coletado, uma única região trouxe 155 registros), considerar coletar
   isso em intervalo mais espaçado que os outros 5 endpoints (ex: a cada
   15 min em vez de 1 min), para não sobrecarregar o VoiceLink.
3. **Se nenhuma das duas for viável a tempo**, a coluna "Qtda Pedido" pode
   ficar de fora da v1 do painel histórico e ser adicionada depois — não é
   bloqueante para o restante do projeto.

### 5.3. Fotos dos operadores

**Decisão do usuário: v1 sem fotos.** Usar avatar genérico ou iniciais do
operador nas tabelas Top 5, em vez de foto real. Não é necessário montar
pasta de fotos nem pedir fonte de imagens para esta versão — isso fica
como possível melhoria futura, não como pendência bloqueante.

### 5.4. Modo Apresentação vs Modo Estático

- **Modo Estático** (default): dashboard interativo normal, com filtros e
  navegação manual entre a tela de Tempo Real e os painéis Históricos por
  região.
- **Modo Apresentação**: alterna automaticamente entre as telas (Tempo
  Real → painel de cada região → repete) a cada N segundos (configurável,
  sugestão inicial: 15s), sem interação do usuário — pensado para rodar
  full-screen numa TV do chão de fábrica.
- Um controle simples na interface (ex: toggle ou botão) alterna entre os
  dois modos. Implementação sugerida em Streamlit: usar
  `st.session_state` para o modo atual + `streamlit_autorefresh` (já usado
  no protótipo) para disparar a troca de tela automaticamente quando em
  modo apresentação.

## 6. Histórico de dados

O filtro por data só terá dados a partir do momento em que o `collector.py`
começar a rodar continuamente — não há como reconstruir dias anteriores ao
início da coleta. Vale deixar isso claro na interface (ex: desabilitar
datas sem dados, ou mostrar "sem dados" de forma explícita).

## 7. Segurança — pontos já identificados, manter em mente

- Credenciais do coletor via variável de ambiente / `.env`, nunca no
  código-fonte (já implementado em `config.py`).
- SSL autoassinado (`verify=False`) é aceitável apenas por ser rede
  interna — não expor esse serviço à internet.
- A tela de gestão de operadores do próprio VoiceLink expõe senhas em
  texto puro — isso é uma falha do sistema terceiro, não do nosso projeto,
  mas vale reportar à TI/segurança da PepsiCo separadamente. Não usar
  nenhuma credencial de operador vista ali.
- O endpoint de detalhe de pedidos (`getAssignmentData.action`) contém PII
  de clientes — seguir estritamente a regra da seção 5.2 se for usado.

## 8. Arquivos do protótipo já entregues (usar como base)

| Arquivo | Status |
|---|---|
| `config.py` | Pronto — URLs, credenciais via `.env`, regiões, intervalos |
| `database.py` | Pronto — schema SQLite + todas as queries (única camada SQL) |
| `collector.py` | Pronto — login + 5 chamadas + parsers + gravação, testado com JSON reais |
| `app.py` | Pronto — dashboard de Tempo Real (a tela histórica da seção 5.1 é nova, vai num arquivo separado, ex: `pages/historico.py` se for usar multi-page do Streamlit) |
| `test_offline.py` | Pronto — testes com dados reais, sem precisar de rede |
| `requirements.txt` | Pronto |
| `README.md` | Pronto — instruções de instalação e execução |

Sugestão de organização para as novas telas: usar o recurso de
multi-página nativo do Streamlit (pasta `pages/`), mantendo `app.py` como
a tela de Tempo Real (padrão ao abrir) e criando
`pages/1_Historico.py` e possivelmente um toggle de modo apresentação
acessível de qualquer tela.
