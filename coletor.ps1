<#
.SYNOPSIS
    Coletor do Control Tower em PowerShell nativo — para PCs corporativos
    sem Python, sem admin e sem executáveis desconhecidos.

.DESCRIPTION
    Faz login no VoiceLink, coleta os endpoints mapeados, faz o parse dos
    payloads e grava os registros na API REST do Supabase (PostgREST), em
    loop a cada POLL_INTERVAL_SECONDS (padrão 60s).

    É o equivalente em PowerShell do collector.py: mesmas tabelas, mesmos
    campos e a mesma semântica de contadores ACUMULADOS — o dashboard
    Streamlit lê o mesmo Supabase e não sabe qual dos dois coletou.

    PRÉ-REQUISITOS NO SUPABASE:
      * as tabelas precisam existir com as MESMAS colunas criadas pelo
        init_db() do projeto Python (rode UMA vez o collector.py com
        DATABASE_URL apontando para este projeto, ou crie as tabelas no
        SQL Editor do Supabase);
      * a chave usada precisa ter permissão de INSERT nas tabelas
        (service_role, ou anon com política RLS liberada).

    CONFIGURAÇÃO (3 opções, em ordem de prioridade):
      1. arquivo coletor.config.ps1 na MESMA pasta deste script
         (está no .gitignore — NUNCA commitar; o repositório é público):
             $VOICELINK_USER     = "usuario_de_servico"
             $VOICELINK_PASSWORD = "senha"
             $SUPABASE_KEY       = "eyJhbGciOi..."
      2. variáveis de ambiente: CT_VOICELINK_USER, CT_VOICELINK_PASSWORD,
         CT_SUPABASE_URL, CT_SUPABASE_KEY
      3. os valores do bloco CONFIGURAÇÃO abaixo.

    EXECUÇÃO (não precisa de admin):
        powershell -ExecutionPolicy Bypass -File coletor.ps1

    IMPORTANTE: rode OU este script OU o collector.py contra o mesmo
    Supabase — nunca os dois ao mesmo tempo, senão os snapshots duplicam.
    A retenção de histórico (>60 dias) é feita pelo collector.py quando
    ele está em uso; este script não apaga dados.
#>

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO
# ---------------------------------------------------------------------------
$VOICELINK_BASE_URL  = "https://172.24.232.145:9444/VoiceLink"
$VOICELINK_USER      = ""
$VOICELINK_PASSWORD  = ""

$SUPABASE_URL = "https://hegqpfpsfohfmoitmsyn.supabase.co/rest/v1"
$SUPABASE_KEY = ""

$POLL_INTERVAL_SECONDS       = 60
$REQUEST_TIMEOUT_SECONDS     = 15
# Contagem de pedidos por operador (coluna "Qtda Pedido"): DESLIGADA por
# padrão, igual ao collector.py — o endpoint envolvido também devolve
# dados de CLIENTE. O parser descarta tudo (allowlist), mas a chamada
# trafega PII; ligar é decisão consciente (seção 5.2 do README).
$COLLECT_ORDER_COUNTS        = $false
$ORDER_POLL_INTERVAL_SECONDS = 900

$REGIOES = [ordered]@{
    6 = "Reg Foods"
    7 = "Reg Caixas"
    8 = "Reg Bolsas"
    9 = "Reg de caixas com etiquetas"
}

# Configuração local opcional (nunca commitada)
$configLocal = Join-Path $PSScriptRoot "coletor.config.ps1"
if (Test-Path $configLocal) { . $configLocal }

# Variáveis de ambiente têm prioridade sobre tudo
if ($env:CT_VOICELINK_USER)     { $VOICELINK_USER = $env:CT_VOICELINK_USER }
if ($env:CT_VOICELINK_PASSWORD) { $VOICELINK_PASSWORD = $env:CT_VOICELINK_PASSWORD }
if ($env:CT_SUPABASE_URL)       { $SUPABASE_URL = $env:CT_SUPABASE_URL }
if ($env:CT_SUPABASE_KEY)       { $SUPABASE_KEY = $env:CT_SUPABASE_KEY }

# Normaliza a URL do PostgREST: aceita "https://projeto.supabase.co" OU
# "https://projeto.supabase.co/rest/v1" (com ou sem barra final). Uma
# base SEM o sufixo /rest/v1 monta URLs que o PostgREST rejeita com
# {"error":"requested path is invalid"} — é o caso clássico desse erro.
$SUPABASE_URL = $SUPABASE_URL.TrimEnd("/")
if ($SUPABASE_URL -notmatch "/rest/v1$") {
    $SUPABASE_URL = "$SUPABASE_URL/rest/v1"
}

# ---------------------------------------------------------------------------
# Compatibilidade PowerShell 5.1 (padrão no Windows corporativo) e 7+
# ---------------------------------------------------------------------------
# Configuração explícita de conexão, ANTES de qualquer requisição web.
# O erro clássico do PS 5.1 em HTTPS — "A conexão subjacente estava
# fechada: Erro inesperado em um envio" — vem da negociação de protocolo
# e do Expect-100-Continue; o SecurityProtocol fixado resolve o primeiro
# e o Expect100Continue=$false o segundo. DefaultConnectionLimit sobe
# para os dois hosts (VoiceLink + Supabase) não brigarem por conexão.
try {
    [System.Net.ServicePointManager]::SecurityProtocol =
        [System.Net.SecurityProtocolType]::Tls12 -bor
        [System.Net.SecurityProtocolType]::Tls11 -bor
        [System.Net.SecurityProtocolType]::Tls
    [System.Net.ServicePointManager]::Expect100Continue = $false
    [System.Net.ServicePointManager]::DefaultConnectionLimit = 20
} catch { }

# Certificado autoassinado do VoiceLink. No PS 7+ existe o parâmetro
# -SkipCertificateCheck por chamada; no PS 5.1 o jeito é aceitar via
# callback (mesma decisão do verify=False no collector.py — rede interna).
$Script:SkipCertOk = "SkipCertificateCheck" -in (Get-Command Invoke-WebRequest).Parameters.Keys
if (-not $Script:SkipCertOk) {
    [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
}

# Console em UTF-8 (o PS 5.1 abre em cp1252 e estoura com acentos).
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

$Script:CapturedAt = ""
$Script:CapturedDia = ""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Get-Campo {
    param($Objeto, [string]$Nome)
    if ($null -eq $Objeto) { return $null }
    return $Objeto.$Nome
}

function To-NullableInt {
    param($Valor)
    if ($null -eq $Valor -or $Valor -is [DBNull]) { return $null }
    return [int]$Valor
}

function To-NullableDouble {
    param($Valor)
    if ($null -eq $Valor -or $Valor -is [DBNull]) { return $null }
    return [double]$Valor
}

function New-Timestamp {
    $Script:CapturedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $Script:CapturedDia = $Script:CapturedAt.Substring(0, 10)
}

function Test-FalhaTransitoria {
    param($Erro)
    # Retry só vale para falha de CONEXÃO. Erro de negócio (ex.: 401/403
    # do PostgREST com chave errada) se resolve no código, não tentando
    # de novo.
    $ex = $Erro.Exception
    $transitorios = @(
        [Net.WebExceptionStatus]::ConnectFailure,
        [Net.WebExceptionStatus]::ConnectionClosed,
        [Net.WebExceptionStatus]::SendFailure,
        [Net.WebExceptionStatus]::ReceiveFailure,
        [Net.WebExceptionStatus]::Timeout,
        [Net.WebExceptionStatus]::NameResolutionFailure,
        [Net.WebExceptionStatus]::KeepAliveFailure
    )
    if ($ex -is [Net.WebException] -and $transitorios -contains $ex.Status) {
        return $true
    }
    $msg = [string]$ex
    if ($msg -match "conexão subjacente|underlying connection|connection was closed|tempo limite|timed out|erro inesperado|unexpected error") {
        return $true
    }
    return $false
}

function Invoke-ComRetry {
    param([scriptblock]$Acao, [int]$Tentativas = 2, [string]$Descricao = "")
    # Retry defensivo para o sintoma "conexão fechada" do PS 5.1: tenta
    # de novo (com espera crescente) só quando a falha é transitória.
    $ultima = $null
    for ($i = 1; $i -le $Tentativas; $i++) {
        try {
            return & $Acao
        } catch {
            $ultima = $_
            if (-not (Test-FalhaTransitoria $ultima) -or $i -ge $Tentativas) {
                break
            }
            Write-Host "  (${Descricao}: tentativa $i de $Tentativas falhou — reconectando em $($i * 2)s...)" -ForegroundColor Yellow
            Start-Sleep -Seconds ($i * 2)
        }
    }
    throw $ultima
}

# ---------------------------------------------------------------------------
# VoiceLink
# ---------------------------------------------------------------------------
function Invoke-VoiceLinkLogin {
    param([string]$Usuario, [string]$Senha)

    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $params = @{
        Uri        = "$VOICELINK_BASE_URL/j_spring_security_check"
        Method     = "Post"
        Body       = @{ j_username = $Usuario; j_password = $Senha }
        WebSession = $session
        TimeoutSec = $REQUEST_TIMEOUT_SECONDS
    }
    if ($Script:SkipCertOk) { $params["SkipCertificateCheck"] = $true }

    $resp = Invoke-ComRetry { Invoke-WebRequest @params } -Descricao "login VoiceLink"

    # O VoiceLink não devolve um JSON claro de sucesso; o jeito confiável
    # é detectar a página de erro de credencial no HTML (como o
    # collector.py faz).
    if ($resp.Content -match "Nome do usu" -and $resp.Content -match "inv") {
        return $null
    }
    return $session
}

function Invoke-VoiceLinkJson {
    param($Session, [string]$Path, [hashtable]$Query)

    $pares = @()
    foreach ($chave in $Query.Keys) {
        $pares += "{0}={1}" -f [Uri]::EscapeDataString([string]$chave),
                                [Uri]::EscapeDataString([string]$Query[$chave])
    }
    $uri = "$VOICELINK_BASE_URL$Path"
    if ($pares.Count -gt 0) { $uri += "?" + ($pares -join "&") }

    $params = @{
        Uri        = $uri
        Method     = "Get"
        WebSession = $Session
        TimeoutSec = $REQUEST_TIMEOUT_SECONDS
    }
    if ($Script:SkipCertOk) { $params["SkipCertificateCheck"] = $true }

    return Invoke-ComRetry { Invoke-RestMethod @params } -Descricao "GET VoiceLink"
}

function Get-Query {
    param([int]$ViewId, [bool]$ComTempSite = $true)
    $q = [ordered]@{
        rowCount                = 5000
        viewId                  = $ViewId
        firstTimeRun            = "true"
        rowsPerPage             = 24
        refreshRequest          = "true"
        firstRowId              = 0
        sortColumn              = "region.name"
        sortAsc                 = "true"
        startIndex              = 0
        submittedFilterCriterion = ""
    }
    if ($ComTempSite) { $q["tempSiteID"] = -927 }
    return $q
}

function New-FiltroRegiao {
    param([int]$RegionNumber, [string]$ViewId)
    $filtro = [ordered]@{
        viewId   = $ViewId
        id       = "0"
        columnId = "-12109"
        operandId = "-11"
        value1   = [string]$RegionNumber
        value2   = ""
        locked   = $false
    }
    return ($filtro | ConvertTo-Json -Compress)
}

# ---------------------------------------------------------------------------
# Parsers: JSON do VoiceLink -> registros prontos para o Supabase
# (espelham os parsers do collector.py, campo por campo)
# ---------------------------------------------------------------------------
function Convert-ParseResumoTarefa {
    param($Payload)
    $out = @()
    foreach ($obj in $Payload.objects) {
        $regiao = Get-Campo $obj "region"
        $out += [pscustomobject]@{
            captured_at    = $Script:CapturedAt
            region_number  = To-NullableInt (Get-Campo $regiao "number")
            region_name    = Get-Campo $regiao "name"
            total          = To-NullableInt (Get-Campo $obj "totalAssignments")
            em_andamento   = To-NullableInt (Get-Campo $obj "inProgress")
            disponivel     = To-NullableInt (Get-Campo $obj "available")
            concluido      = To-NullableInt (Get-Campo $obj "complete")
            nao_concluido  = To-NullableInt (Get-Campo $obj "nonComplete")
        }
    }
    return $out
}

function Convert-ParseResumoTrabalho {
    param($Payload)
    $out = @()
    foreach ($obj in $Payload.objects) {
        $regiao = Get-Campo $obj "region"
        $out += [pscustomobject]@{
            captured_at            = $Script:CapturedAt
            region_number          = To-NullableInt (Get-Campo $regiao "number")
            region_name            = Get-Campo $regiao "name"
            operadores_trabalhando = To-NullableInt (Get-Campo $obj "operatorsWorkingIn")
            operadores_atribuidos  = To-NullableInt (Get-Campo $obj "operatorsAssigned")
            itens_restantes        = To-NullableInt (Get-Campo $obj "totalItemsRemaining")
            itens_selecionados     = To-NullableInt (Get-Campo $obj "totalItemsPicked")
            estimado_concluido     = To-NullableDouble (Get-Campo $obj "estimatedCompleted")
            meta_regiao            = To-NullableInt (Get-Campo $regiao "goalRate")
        }
    }
    return $out
}

function Convert-ParseProdutividadeRegiao {
    param($Payload)
    $out = @()
    foreach ($obj in $Payload.objects) {
        $regiao = Get-Campo $obj "region"
        $out += [pscustomobject]@{
            captured_at          = $Script:CapturedAt
            region_number        = To-NullableInt (Get-Campo $regiao "number")
            region_name          = Get-Campo $regiao "name"
            quantidade_total     = To-NullableInt (Get-Campo $obj "totalQuantity")
            produtividade_atual  = To-NullableDouble (Get-Campo $obj "actualRate")
            numero_operadores    = To-NullableInt (Get-Campo $obj "numberOfOperators")
            pct_meta             = To-NullableDouble (Get-Campo $obj "percentOfGoal")
            tempo_total          = Get-Campo $obj "totalTime"
            meta                 = To-NullableDouble (Get-Campo $obj "goalRate")
        }
    }
    return $out
}

function Convert-ParseProdutosFalta {
    param($Payload)
    $out = @()
    foreach ($obj in $Payload.objects) {
        $regiao = Get-Campo $obj "region"
        $out += [pscustomobject]@{
            captured_at   = $Script:CapturedAt
            region_number = To-NullableInt (Get-Campo $regiao "number")
            region_name   = Get-Campo $regiao "name"
            total_faltas  = To-NullableInt (Get-Campo $obj "totalShorts")
            em_falta      = To-NullableInt (Get-Campo $obj "shorted")
            atribuido     = To-NullableInt (Get-Campo $obj "assigned")
            marcado       = To-NullableInt (Get-Campo $obj "markedout")
        }
    }
    return $out
}

function Convert-ParseProdutividadeOperador {
    param($Payload, [int]$RegionNumber, [string]$RegionName)
    # Regra de negócio do collector.py: só operadores com quantidade > 0;
    # a coluna Função (filterType) é descartada de propósito.
    $out = @()
    foreach ($obj in $Payload.objects) {
        $qtd = To-NullableInt (Get-Campo $obj "totalQuantity")
        if ($null -eq $qtd -or $qtd -le 0) { continue }
        $operador = Get-Campo (Get-Campo (Get-Campo $obj "operator") "common") "operatorIdentifier"
        $out += [pscustomobject]@{
            captured_at         = $Script:CapturedAt
            region_number       = $RegionNumber
            region_name         = $RegionName
            operador_id         = [string]$operador
            quantidade          = $qtd
            tempo_total         = Get-Campo $obj "totalTime"
            meta                = To-NullableDouble (Get-Campo $obj "goalRate")
            produtividade_real  = To-NullableDouble (Get-Campo $obj "actualRate")
            pct_meta            = To-NullableDouble (Get-Campo $obj "percentOfGoal")
        }
    }
    return $out
}

function Convert-ParseAtribuicoesSemPii {
    param($Payload, [int]$RegionNumber, [string]$RegionName)
    # SÓ a contagem de pedidos por operador, descartando toda PII.
    #
    # O payload de origem contém dados de cliente (nome, endereço,
    # customerNumber). A regra da seção 5.2 é inegociável: nada disso
    # pode ser gravado. Como no collector.py, a garantia é estrutural:
    # este parser monta um registro NOVO com só 4 campos (allowlist) —
    # campo novo que a Honeywell inventar num update simplesmente não
    # passa. `pedido_ref` é o id numérico interno da atribuição, não o
    # número do pedido do cliente.
    $out = @()
    foreach ($obj in $Payload.objects) {
        $operador = Get-Campo (Get-Campo (Get-Campo $obj "operator") "common") "operatorIdentifier"
        $ref = Get-Campo $obj "id"
        if (-not $operador -or $null -eq $ref) { continue }
        $out += [pscustomobject]@{
            captured_at   = $Script:CapturedAt
            dia           = $Script:CapturedDia
            region_number = $RegionNumber
            region_name   = $RegionName
            operador_id   = [string]$operador
            pedido_ref    = [string]$ref
            status        = Get-Campo $obj "status"
        }
    }
    return $out
}

# ---------------------------------------------------------------------------
# Supabase (PostgREST)
# ---------------------------------------------------------------------------
function Send-SupabaseRows {
    param([string]$Tabela, [array]$Linhas, [string[]]$Conflito = @())
    if ($Linhas.Count -eq 0) { return }

    $headers = @{
        "apikey"       = $SUPABASE_KEY
        "Authorization" = "Bearer $SUPABASE_KEY"
        "Content-Type" = "application/json"
    }
    $uri = "$SUPABASE_URL/$Tabela"
    if ($Conflito.Count -gt 0) {
        # Upsert (pedidos): equivale ao INSERT OR REPLACE / ON CONFLICT
        # do collector.py — exige a constraint UNIQUE na tabela.
        $headers["Prefer"] = "resolution=merge-duplicates"
        $uri += "?on_conflict=" + ($Conflito -join ",")
    }

    # -InputObject @() garante que UMA linha vire array JSON (o PostgREST
    # aceita os dois, mas array é o formato do bulk insert). Os bytes vão
    # como UTF-8 explícito para acentos sobreviverem no PS 5.1.
    $json  = ConvertTo-Json -InputObject @($Linhas) -Depth 5 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)

    try {
        Invoke-ComRetry {
            Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -Body $bytes `
                -TimeoutSec $REQUEST_TIMEOUT_SECONDS -ErrorAction Stop | Out-Null
        } -Descricao "POST $Tabela"
    } catch {
        # Log de diagnóstico: URL exata chamada + status HTTP + corpo da
        # resposta. A mensagem sobe para o loop principal e vai parar no
        # coleta_log — o painel mostra o motivo da falha.
        $detalhe = "Falha no envio para $uri : $_"
        $resposta = $_.Exception.Response
        if ($null -ne $resposta) {
            try { $detalhe += " · HTTP $([int]$resposta.StatusCode)" } catch { }
            try {
                $stream = $resposta.GetResponseStream()
                if ($null -ne $stream) {
                    $leitor = New-Object IO.StreamReader($stream)
                    $corpo = $leitor.ReadToEnd()
                    $leitor.Close()
                    if ($corpo) { $detalhe += " · body: $corpo" }
                }
            } catch { }
        }
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $detalhe += " · body: $($_.ErrorDetails.Message)"
        }
        Write-Host $detalhe -ForegroundColor Yellow
        throw $detalhe
    }
}

# ---------------------------------------------------------------------------
# Ciclo de coleta
# ---------------------------------------------------------------------------
function Invoke-ColetaPedidos {
    param($Session)
    $total = 0
    foreach ($kv in $REGIOES.GetEnumerator()) {
        $q = Get-Query -ViewId -1009
        $q["submittedFilterCriterion"] = New-FiltroRegiao $kv.Key "-1009"
        $payload = Invoke-VoiceLinkJson $Session "/selection/assignment/getAssignmentData.action" $q
        $linhas = @(Convert-ParseAtribuicoesSemPii $payload $kv.Key $kv.Value)
        Send-SupabaseRows "pedidos_operador" $linhas @("dia", "region_number", "operador_id", "pedido_ref")
        $total += $linhas.Count
    }
    Write-Host "  pedidos coletados: $total atribuições (sem dados de cliente)"
}

function Invoke-Ciclo {
    param($Session)

    New-Timestamp

    # @(...) em volta dos parsers: função que devolve UM registro
    # desenrola o array na saída, e .Count quebraria no scalar.
    $q = Get-Query -ViewId -1105
    $tarefa = @(Convert-ParseResumoTarefa (Invoke-VoiceLinkJson $Session "/selection/assignment/getSummaryData.action" $q))
    Send-SupabaseRows "resumo_tarefa" $tarefa

    $q = Get-Query -ViewId -1106
    $trabalho = @(Convert-ParseResumoTrabalho (Invoke-VoiceLinkJson $Session "/selection/workgroup/getSummaryData.action" $q))
    Send-SupabaseRows "resumo_trabalho" $trabalho

    $q = Get-Query -ViewId -1016
    $prodRegiao = @(Convert-ParseProdutividadeRegiao (Invoke-VoiceLinkJson $Session "/selection/assignment/getSummaryData.action" $q))
    Send-SupabaseRows "produtividade_regiao" $prodRegiao

    $q = Get-Query -ViewId -1107
    $falta = @(Convert-ParseProdutosFalta (Invoke-VoiceLinkJson $Session "/selection/short/getSummaryData.action" $q))
    Send-SupabaseRows "produtos_falta" $falta

    $operadores = @()
    foreach ($kv in $REGIOES.GetEnumerator()) {
        $q = Get-Query -ViewId -1022 -ComTempSite $false
        $q["submittedFilterCriterion"] = New-FiltroRegiao $kv.Key "-1022"
        $payload = Invoke-VoiceLinkJson $Session "/selection/labor/getOperatorLaborSummaryData.action" $q
        $operadores += @(Convert-ParseProdutividadeOperador $payload $kv.Key $kv.Value)
    }
    Send-SupabaseRows "produtividade_operador" $operadores

    Send-SupabaseRows "coleta_log" @(
        @{
            captured_at = $Script:CapturedAt
            sucesso     = 1
            detalhe     = "$($operadores.Count) operadores ativos"
        }
    )
    # Contagem POR ENDPOINT: se algum endpoint voltar vazio (ex.:
    # prod_regiao=0), o log mostra qual é antes de qualquer suspeita no
    # banco ou no painel.
    Write-Host ("$($Script:CapturedAt) coleta concluída: " +
        "tarefa=$($tarefa.Count) trabalho=$($trabalho.Count) " +
        "prod_regiao=$($prodRegiao.Count) falta=$($falta.Count) " +
        "operadores=$($operadores.Count)")
}

function Send-LogFalha {
    param([string]$Mensagem)
    try {
        Send-SupabaseRows "coleta_log" @(
            @{
                captured_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
                sucesso     = 0
                detalhe     = $Mensagem.Substring(0, [Math]::Min(400, $Mensagem.Length))
            }
        )
    } catch {
        Write-Host "  (não foi possível registrar a falha no coleta_log: $_)"
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
function Invoke-Main {
    if (-not $VOICELINK_USER -or -not $VOICELINK_PASSWORD) {
        Write-Host "VOICELINK_USER / VOICELINK_PASSWORD não configurados. Crie o coletor.config.ps1 ao lado deste script (veja o cabeçalho)." -ForegroundColor Red
        exit 1
    }
    if (-not $SUPABASE_KEY) {
        Write-Host "SUPABASE_KEY não configurada. Crie o coletor.config.ps1 ao lado deste script (veja o cabeçalho)." -ForegroundColor Red
        exit 1
    }

    Write-Host "Control Tower — coletor PowerShell iniciado (loop a cada $POLL_INTERVAL_SECONDS s)."
    if ($COLLECT_ORDER_COUNTS) {
        Write-Host "Coleta de pedidos LIGADA (a cada $ORDER_POLL_INTERVAL_SECONDS s). Só a contagem por operador é gravada — PII descartada no parser."
    }

    $session = $null
    $ultimaColetaPedidos = [DateTime]::MinValue

    while ($true) {
        try {
            if ($null -eq $session) {
                $session = Invoke-VoiceLinkLogin $VOICELINK_USER $VOICELINK_PASSWORD
                if ($null -eq $session) { throw "Login falhou: usuário ou senha inválidos." }
                Write-Host "Login no VoiceLink OK."
            }

            Invoke-Ciclo $session

            # Pedidos: relógio próprio, bem mais espaçado (seção 5.2).
            if ($COLLECT_ORDER_COUNTS -and
                ((Get-Date) - $ultimaColetaPedidos).TotalSeconds -ge $ORDER_POLL_INTERVAL_SECONDS) {
                Invoke-ColetaPedidos $session
                $ultimaColetaPedidos = Get-Date
            }
        } catch {
            Write-Host "$(Get-Date -Format 'HH:mm:ss') Falha na coleta: $_" -ForegroundColor Yellow
            # Força novo login no próximo ciclo (sessão pode ter expirado).
            $session = $null
            Send-LogFalha ([string]$_.Exception.Message)
        }

        Start-Sleep -Seconds $POLL_INTERVAL_SECONDS
    }
}

# Rodar o main só quando executado diretamente; dot-source carrega as
# funções para teste sem iniciar o loop.
if ($MyInvocation.InvocationName -ne ".") { Invoke-Main }
