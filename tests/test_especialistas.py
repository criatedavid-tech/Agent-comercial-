"""Distribuição dos agentes: gerente + especialistas por área, cada um só com as ferramentas da área."""

import asyncio
import dataclasses

import pytest

from agente.core import TOOLS, Agent, comercial_tools
from agente.crm import Crm
from agente.scheduler import SUMMARY_PROMPT
from agente.subagents import AGENTS

SPECIALISTS = ("comercial", "financeiro", "operacao")


def mcp(agent):
    return [t for t in agent.tools if t.startswith("mcp__")]


def test_every_specialist_exists_and_answers_in_the_same_request():
    for name in SPECIALISTS:
        agent = AGENTS[name]
        assert agent.background is False and agent.model == "sonnet" and agent.maxTurns
        assert "não fala com o dono" in agent.prompt and "indício para conferir" in agent.prompt


def test_only_operations_uses_the_browser():
    """O navegador tem uma aba só: com dois agentes nele, um abre por cima do outro (visto no teste real)."""
    with_browser = [n for n, a in AGENTS.items() if any(t.startswith("mcp__navegador__") for t in a.tools)]
    assert with_browser == ["operacao"]
    assert all("navegador" not in (a.mcpServers or []) for n, a in AGENTS.items() if n != "operacao")


def test_each_area_sees_only_its_own_tools():
    comercial, financeiro, operacao = (set(mcp(AGENTS[n])) for n in SPECIALISTS)
    assert not any("comercial__" in t for t in financeiro | operacao)  # leads e conversas: só o comercial
    assert "mcp__gestao__consultar_lancamentos" not in comercial  # lançamentos de caixa e despesas: não
    assert "mcp__humano__pedir_ajuda_humana" in operacao  # login nos sistemas da loja
    for name in SPECIALISTS:  # nenhum especialista mexe em arquivo ou terminal
        assert not {"Bash", "Write", "Edit", "Read"} & set(AGENTS[name].tools)


def test_specialist_tools_and_servers_exist_in_the_manager(cfg):
    options = Agent(cfg)._options()
    for name, agent in AGENTS.items():
        unknown = [t for t in mcp(agent) if t not in TOOLS]
        assert not unknown, f"{name} usa ferramentas que não existem: {unknown}"
        assert set(agent.mcpServers or []) <= set(options.mcp_servers), name
    assert set(SPECIALISTS) <= set(options.agents)


def test_free_mode_keeps_the_specialists(cfg):
    alt = dataclasses.replace(cfg, base_url="https://openrouter.ai/api", auth_token="t", model="m:free")
    agents = Agent(alt)._options().agents
    assert set(SPECIALISTS) <= set(agents)
    assert agents["operacao"].tools == AGENTS["operacao"].tools


def test_manager_prompt_distributes_the_work(cfg):
    prompt = Agent(cfg)._options().system_prompt
    assert "você é o gerente" in prompt and "Pergunta rápida e direta" in prompt
    assert "Tarefa no navegador vai sempre para a operação" in prompt
    assert "UM resumo" in prompt
    assert "financeiro" in SUMMARY_PROMPT and "comercial" in SUMMARY_PROMPT


# --- ferramentas do comercial (leitura do CRM) ---------------------------------------------------

def call(cfg, name, args):
    tool = next(t for t in comercial_tools(cfg) if t.name == name)
    out = asyncio.run(tool.handler(args))
    return out["content"][0]["text"], out["is_error"]


@pytest.fixture
def crm(cfg):
    crm = Crm(cfg.crm_db)
    crm.ensure("5562911112222", "whatsapp", opt_in=True)
    crm.update("5562911112222", name="Ana", interest="milkshake de pistache", stage="orcamento")
    crm.log("5562911112222", "entrada", "quanto fica 3 de pistache?")
    crm.log("5562911112222", "saida", "a equipe confirma o valor")
    crm.ensure("5562933334444", "whatsapp", opt_in=True)
    crm.update("5562933334444", name="Bruno", stage="perdido")
    crm.set_handoff("5562933334444", "aguardando", "quer encomenda para festa")
    crm.ensure("sim-teste", "simulador", opt_in=True)
    return crm


def test_list_leads(cfg, crm):
    text, error = call(cfg, "listar_leads", {})
    assert not error and "2 lead(s)" in text and "Ana" in text and "sim-teste" not in text
    assert "milkshake de pistache" in text and "com a equipe (aguardando)" in text
    text, _ = call(cfg, "listar_leads", {"etapa": "orcamento"})
    assert "Ana" in text and "Bruno" not in text
    assert "sim-teste" in call(cfg, "listar_leads", {"simulados": True})[0]


def test_queue_and_conversation(cfg, crm):
    text, _ = call(cfg, "fila_atendimento", {})
    assert "Bruno" in text and "quer encomenda para festa" in text and "Ana" not in text
    text, error = call(cfg, "conversa_cliente", {"telefone": "5562911112222"})
    assert not error and "cliente: quanto fica 3 de pistache?" in text and "atendente: a equipe confirma" in text
    assert call(cfg, "conversa_cliente", {"telefone": "000"})[1]


def test_comercial_tools_only_read(cfg, crm):
    """Nenhuma ferramenta do comercial muda o CRM: contatos e mensagens ficam iguais depois de usar todas."""
    before = [vars(c) for c in crm.contacts()], len(crm.interactions("5562911112222"))
    for name, args in (("listar_leads", {}), ("fila_atendimento", {}), ("conversa_cliente", {"telefone": "5562911112222"})):
        call(cfg, name, args)
    assert ([vars(c) for c in crm.contacts()], len(crm.interactions("5562911112222"))) == before
