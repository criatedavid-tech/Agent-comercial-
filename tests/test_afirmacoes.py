"""Lições do Maestro do Hiago: senha em outra linha não vai para o log e "anotei" sem ferramenta é avisado."""

import pytest

from agente.atendente import Attendant
from agente.core import Agent, unbacked_claim
from agente.knowledge import redact_secrets


# --- senha na linha de baixo (caso real: e-mail numa linha, senha na outra) ---------------

def test_email_then_password_on_the_next_line_is_removed():
    text = "entre no meu sistema\n\nlogin e senha\n\nfulano@exemplo.com\nAbc9fake77Zq!\n\nobrigado"
    out, removed = redact_secrets(text)
    assert "Abc9fake77Zq!" not in out and "fulano@exemplo.com" in out
    assert removed == ["senha"]


def test_label_then_password_on_the_next_line_is_removed():
    out, removed = redact_secrets("senha:\nabc123xyz")
    assert "abc123xyz" not in out and removed == ["senha"]


@pytest.mark.parametrize("text", [
    "meu e-mail é fulano@exemplo.com\nobrigado",          # palavra comum depois do e-mail
    "fulano@exemplo.com\n11999998888",                    # telefone, só número
    "fulano@exemplo.com\nhttps://exemplo.com/entrar",     # endereço
    "me chame em fulano@exemplo.com\nsegunda de manhã",   # texto com espaço
])
def test_ordinary_lines_after_an_email_are_kept(text):
    assert redact_secrets(text) == (text, [])


def test_old_patterns_still_work():
    out, removed = redact_secrets("a senha é segredo99 e o cartão 4111 1111 1111 1111")
    assert "segredo99" not in out and "4111" not in out and set(removed) == {"senha", "número de cartão"}


def test_attendant_does_not_log_the_customers_password():
    """O CRM guardava o texto cru do cliente; agora entra com o segredo já tirado."""
    import inspect

    source = inspect.getsource(Attendant.ask)
    assert source.index("redact_secrets") < source.index('self.contact.log("entrada"')


# --- "anotei" sem ferramenta -------------------------------------------------------------

def test_claim_without_a_write_tool_is_flagged():
    assert unbacked_claim("Anotei no cadastro: sua empresa vende jogos.", set()) == "anotei"
    assert unbacked_claim("Pronto, já agendei para sexta.", {"mcp__knowledge__buscar_conhecimento"}) == "agendei"


@pytest.mark.parametrize("tools", [
    {"mcp__agenda__agendar_tarefa"}, {"Write"}, {"Edit"}, {"mcp__conhecimento__salvar_conhecimento"},
    {"mcp__brechas__registrar_brecha"}, {"mcp__agenda__reuniao_semanal"},
])
def test_claim_backed_by_a_tool_is_not_flagged(tools):
    assert unbacked_claim("Anotei e agendei.", tools) is None


def test_text_without_a_claim_is_not_flagged():
    assert unbacked_claim("Vou verificar e te aviso.", set()) is None
    assert unbacked_claim("", set()) is None


def test_only_the_operator_checks_claims():
    assert Agent.check_claims is True and Attendant.check_claims is False
