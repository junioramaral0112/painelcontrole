"""
Autenticação contra o VoiceLink, compartilhada pelo coletor e pelo dashboard.

O coletor usa a credencial de serviço do .env (VOICELINK_USER/PASSWORD);
o dashboard usa a credencial digitada na tela de login. A fonte de
verdade é sempre o próprio VoiceLink — não existe lista de usuários
local para manter em sincronia.

Regra de segurança: a senha existe só DENTRO da chamada de login. Ela
não é gravada em arquivo, banco, log ou session_state — termina a função,
terminou a senha.
"""
import requests

import config


def login_voicelink(usuario: str, senha: str):
    """Faz login no VoiceLink e devolve a sessão autenticada, ou None.

    A sessão devolvida carrega o cookie de sessão do Spring Security —
    é ela que o coletor reutiliza nas chamadas de dados. O dashboard só
    precisa saber se o login funcionou, então descarta a sessão logo em
    seguida.

    Devolve None tanto para credenciais inválidas quanto para falha de
    conexão (rede fora, servidor fora do ar): para quem está na tela de
    login, os dois casos têm o mesmo efeito — não liberar o painel.
    """
    if not usuario or not senha:
        return None

    sessao = requests.Session()
    sessao.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ControlTower/1.0",
    })

    login_url = f"{config.BASE_URL}/j_spring_security_check"
    try:
        resp = sessao.post(
            login_url,
            data={"j_username": usuario, "j_password": senha},
            verify=config.VERIFY_SSL,
            timeout=config.REQUEST_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None

    # O VoiceLink não devolve um JSON claro de sucesso no login; a forma
    # confiável de validar é detectar a página de erro de credencial no
    # HTML de retorno.
    if "Nome do usu" in resp.text and "inv" in resp.text.lower():
        return None

    return sessao
