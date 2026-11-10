"""Núcleo do agente: opções do SDK, ferramentas próprias, skills e conversão de mensagens em eventos."""

import asyncio

import pytest
import json
import re

from claude_agent_sdk import (
    AssistantMessage,
    SystemMessage,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from agente import guard
from agente.core import (PLUGIN_DIR, SKILLS, TOOLS, Agent, agenda_tools, brechas_tools, browser_tools, comercial_tools, gestao_tools, google_tools,
                         human_tools, knowledge_tools)
from agente.subagents import AGENTS


def tool_by_name(tools, name):
    return next(t for t in tools if t.name == name)


def text_of(reply):
    return reply["content"][0]["text"]


# --- opções do SDK -----------------------------------------------------------

def test_options_wire_everything(cfg):
    options = Agent(cfg)._options()
    assert options.permission_mode == "bypassPermissions"
    assert options.max_turns == cfg.max_turns and options.max_budget_usd == cfg.max_budget_usd
    assert set(options.mcp_servers) == {"conhecimento", "humano", "agenda", "navegador", "gestao", "comercial", "brechas", "google"}
    assert set(options.agents) == {"pesquisador", "organizador", "verificador", "comercial", "financeiro", "operacao"}
    assert options.skills == SKILLS
    assert options.setting_sources == []  # não herda configurações pessoais do Claude Code
    assert "PreToolUse" in options.hooks
    assert options.plugins == [{"type": "local", "path": str(PLUGIN_DIR)}]
    assert str(cfg.knowledge_dir) in options.add_dirs


def test_tool_timeout_is_longer_than_human_wait(cfg):
    env = Agent(cfg)._options().env
    wait_ms = cfg.help_timeout_min * 60_000
    assert int(env["MCP_TOOL_TIMEOUT"]) > wait_ms
    assert int(env["CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT"]) > wait_ms


def test_system_prompt_has_memory_and_knowledge(cfg):
    (cfg.memory_dir / "perfil.md").write_text("- Nome: Teste", encoding="utf-8")
    agent = Agent(cfg)
    agent.kb.save("financas", "Aluguel", "1500")
    prompt = agent._options().system_prompt
    assert "- Nome: Teste" in prompt
    assert "financas: 1 nota(s); recentes: Aluguel" in prompt
    assert "pedir_ajuda_humana" in prompt and "NÃO tente passar" in prompt
    assert "agendar_tarefa" in prompt and "America/Sao_Paulo" in prompt


def test_all_allowed_tools_exist(cfg):
    names = {f"mcp__conhecimento__{t.name}" for t in knowledge_tools(Agent(cfg).kb)}
    names |= {f"mcp__humano__{t.name}" for t in human_tools(Agent(cfg).human)}
    names |= {f"mcp__agenda__{t.name}" for t in agenda_tools(Agent(cfg).agenda)}
    names |= {f"mcp__navegador__{t.name}" for t in browser_tools(Agent(cfg).browser)}
    names |= {f"mcp__gestao__{t.name}" for t in gestao_tools(cfg)}
    names |= {f"mcp__comercial__{t.name}" for t in comercial_tools(cfg)}
    names |= {f"mcp__brechas__{t.name}" for t in brechas_tools(cfg)}
    names |= {f"mcp__google__{t.name}" for t in google_tools(cfg)}
    custom = {t for t in TOOLS if t.startswith("mcp__")}
    assert custom == names


# --- skills e subagentes -------------------------------------------------------

def test_every_skill_has_valid_frontmatter():
    assert SKILLS, "nenhuma skill encontrada em plugin/skills"
    for name in SKILLS:
        folder = name.split(":", 1)[1]
        text = (PLUGIN_DIR / "skills" / folder / "SKILL.md").read_text(encoding="utf-8")
        head = re.match(r"---\n(.*?)\n---\n", text, re.S)
        assert head, f"{folder}: sem cabeçalho ---"
        assert f"name: {folder}\n" in head.group(1) + "\n", f"{folder}: name diferente da pasta"
        assert re.search(r"description: .{40,}", head.group(1)), f"{folder}: description curta demais"


def test_plugin_manifest():
    manifest = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "agente"
    assert all(s.startswith("agente:") for s in SKILLS)


def test_subagents_use_only_known_tools():
    known = set(TOOLS) - {"Agent"}
    for name, agent in AGENTS.items():
        assert agent.description and agent.prompt, name
        assert set(agent.tools) <= known, f"{name} usa ferramenta desconhecida"
        assert "Agent" not in agent.tools, f"{name} não deve criar outros subagentes"


# --- ferramentas próprias ------------------------------------------------------

def test_knowledge_tools_save_and_search(cfg):
    agent = Agent(cfg)
    tools = knowledge_tools(agent.kb)
    save, search = tool_by_name(tools, "salvar_conhecimento"), tool_by_name(tools, "buscar_conhecimento")

    saved = asyncio.run(save.handler({"area": "saude", "titulo": "Exame", "conteudo": "LDL 130", "tags": "", "nicho": "", "fonte": ""}))
    assert not saved["is_error"] and "conhecimento" in text_of(saved)

    found = asyncio.run(search.handler({"consulta": "ldl", "area": ""}))
    assert "## Exame (saude)" in text_of(found)
    assert text_of(asyncio.run(search.handler({"consulta": "xyz", "area": ""}))) == "nada encontrado"


def test_knowledge_tool_reports_refusal_as_error(cfg):
    save = tool_by_name(knowledge_tools(Agent(cfg).kb), "salvar_conhecimento")
    reply = asyncio.run(save.handler({"area": "geral", "titulo": "x", "conteudo": "senha: 123", "tags": "", "nicho": "", "fonte": ""}))
    assert reply["is_error"] and "não salvei" in text_of(reply)


def test_human_tool_returns_answer(cfg):
    agent = Agent(cfg)
    ask = tool_by_name(human_tools(agent.human), "pedir_ajuda_humana")

    async def scenario():
        async def notify(req):
            asyncio.get_running_loop().call_later(0.01, agent.human.answer, req.id, "resolvido")

        agent.human.notify = notify
        return await ask.handler({"motivo": "captcha", "link": ""})

    assert text_of(asyncio.run(scenario())) == "resposta do usuário: resolvido"


# --- loop: mensagens do SDK viram eventos -------------------------------------

class FakeClient:
    def __init__(self, messages):
        self.messages = messages
        self.sent = []

    async def query(self, text):
        self.sent.append(text)

    async def receive_response(self):
        for msg in self.messages:
            yield msg


def collect(agent, text):
    async def run():
        return [e async for e in agent.ask(text)]

    return asyncio.run(run())


def test_ask_converts_messages_to_events_and_logs(cfg):
    agent = Agent(cfg)
    deny = f"{guard.DENY_PREFIX}: comando bloqueado (formatar disco). Não tente contornar."
    agent.client = FakeClient([
        AssistantMessage(content=[
            TextBlock(text="Vou anotar."),
            ToolUseBlock(id="t1", name="mcp__conhecimento__salvar_conhecimento", input={"titulo": "Aluguel"}),
            ToolUseBlock(id="t2", name="Bash", input={"command": "format C:"}),
        ], model="claude-opus-5-5"),
        UserMessage(content=[ToolResultBlock(tool_use_id="t2", content=deny, is_error=True)]),
        ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=2,
                      session_id="s", total_cost_usd=0.0123),
    ])

    events = collect(agent, "anota meu aluguel")
    assert [(e.kind, e.text) for e in events] == [
        ("text", "Vou anotar."),
        ("tool", "salvar_conhecimento Aluguel"),  # prefixo mcp__ removido
        ("tool", "Bash format C:"),
        ("blocked", "comando bloqueado (formatar disco)"),
        ("result", "ok · 2 passos · US$ 0.0123"),
    ]
    assert agent.client.sent == ["anota meu aluguel"]

    log = [json.loads(line) for line in next(cfg.logs_dir.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()]
    assert [e["type"] for e in log] == ["user", "text", "tool", "tool", "tool_error", "result"]
    assert log[-1]["cost_usd"] == 0.0123


def test_password_pasted_in_chat_never_reaches_the_model(cfg):
    """Visto no teste real: o usuário colou e-mail e senha da Shopee e o gerente repassou ao subagente."""
    agent = Agent(cfg)
    agent.client = FakeClient([])
    events = collect(agent, "compre na Shopee. credenciais: eu@exemplo.com\nsenha: Segredo123")
    assert events[0].kind == "blocked" and "senha" in events[0].text
    [sent] = agent.client.sent
    assert "Segredo123" not in sent and "eu@exemplo.com" in sent and "removeu" in sent
    log = next(cfg.logs_dir.glob("*.jsonl")).read_text(encoding="utf-8")
    assert "Segredo123" not in log


def test_image_error_from_a_text_only_model_tells_what_to_do(cfg):
    """Visto no teste real: 'entre no meu criate' fez o modelo ler um PNG e o provedor respondeu 400."""
    agent = Agent(cfg)
    agent.client = FakeClient([AssistantMessage(content=[TextBlock(text="API Error: 400 No endpoints found that support image input")],
                                                model="m")])
    [event] = collect(agent, "entre no meu criate")
    assert event.kind == "text" and "Nova conversa" in event.text and "AGENT_MODEL" in event.text
    assert "No endpoints found that support image input" in event.text  # a mensagem original continua visível
    agent.client = FakeClient([AssistantMessage(content=[TextBlock(text="API Error: 500 erro do provedor")], model="m")])
    assert collect(agent, "x")[0].text == "API Error: 500 erro do provedor"  # outros erros ficam como vieram


def test_prompt_sends_login_requests_to_the_browser(cfg):
    prompt = Agent(cfg)._options().system_prompt
    assert "entre no meu Criate" in prompt and "Não procure o sistema em arquivos" in prompt


def test_result_status_on_errors(cfg):
    agent = Agent(cfg)

    def status(subtype, is_error):
        agent.client = FakeClient([ResultMessage(subtype=subtype, duration_ms=1, duration_api_ms=1,
                                                 is_error=is_error, num_turns=1, session_id="s")])
        return collect(agent, "x")[-1].text.split(" · ")[0]

    assert status("success", True) == "erro"  # ex.: falha de autenticação
    assert status("error_max_budget_usd", True) == "parou: error_max_budget_usd"


def test_checkpoints_and_resume_options(cfg):
    options = Agent(cfg)._options()
    assert options.enable_file_checkpointing
    assert "replay-user-messages" in options.extra_args  # sem isso o SDK não devolve o id do pedido
    assert options.resume is None
    assert Agent(cfg, resume="abc")._options().resume == "abc"


def test_history_records_session_and_checkpoint(cfg):
    agent = Agent(cfg)
    agent.client = FakeClient([
        SystemMessage(subtype="init", data={"session_id": "sess-1"}),
        UserMessage(content="anota meu aluguel", uuid="uuid-pedido"),  # eco do pedido
        AssistantMessage(content=[TextBlock(text="Anotado.")], model="m"),
        ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                      session_id="sess-1", total_cost_usd=0.01),
    ])
    events = collect(agent, "anota meu aluguel")
    assert ("checkpoint", "uuid-pedido") in [(e.kind, e.text) for e in events]
    assert agent.session_id == "sess-1"
    recorded = [(r.kind, r.text) for r in agent.history.events("sess-1")]
    assert recorded == [("user", "anota meu aluguel"), ("checkpoint", "uuid-pedido"), ("text", "Anotado."),
                        ("result", "ok · 1 passos · US$ 0.0100")]
    [session] = agent.history.sessions()
    assert session.cost_usd == 0.01


def test_tool_result_echo_is_not_a_checkpoint(cfg):
    agent = Agent(cfg)
    agent.client = FakeClient([
        UserMessage(content=[ToolResultBlock(tool_use_id="t", content="ok")], uuid="x"),
        UserMessage(content="resposta de subagente", uuid="y", parent_tool_use_id="t"),
    ])
    assert [e.kind for e in collect(agent, "oi")] == []


def test_reset_and_resume_change_session(cfg):
    import asyncio

    agent = Agent(cfg, resume="velha")
    calls = []

    async def fake_start():
        calls.append(("start", agent._resume))

    async def fake_stop():
        calls.append(("stop", None))

    agent.start, agent.stop = fake_start, fake_stop
    asyncio.run(agent.reset())
    assert agent.session_id is None and calls[-1] == ("start", None)
    asyncio.run(agent.resume("outra"))
    assert agent.session_id == "outra" and calls[-1] == ("start", "outra")


def test_resume_falls_back_to_new_conversation(cfg):
    import asyncio

    agent = Agent(cfg)
    attempts = []

    async def fake_start():
        attempts.append(agent._resume)
        if agent._resume == "sumiu":
            raise RuntimeError("--resume requires a valid session ID")

    async def fake_stop():
        pass

    agent.start, agent.stop = fake_start, fake_stop
    assert asyncio.run(agent.resume("sumiu")) is False
    assert attempts == ["sumiu", None] and agent.session_id is None
    assert asyncio.run(agent.resume("existe")) is True and agent.session_id == "existe"


def _required(tools, name):
    """Campos obrigatórios. Visto no primeiro teste real: com todos obrigatórios o modelo errava e repetia a chamada."""
    tool = next(t for t in tools if t.name == name)
    return set(tool.input_schema["required"])


def test_required_fields(cfg):
    agent = Agent(cfg)
    kb, human, agenda, browser = (knowledge_tools(agent.kb), human_tools(agent.human),
                                  agenda_tools(agent.agenda), browser_tools(agent.browser))
    assert _required(kb, "salvar_conhecimento") == {"area", "titulo", "conteudo"}
    assert _required(kb, "buscar_conhecimento") == {"consulta"}
    assert _required(human, "pedir_ajuda_humana") == {"motivo"}
    assert _required(agenda, "agendar_tarefa") == {"titulo"}
    assert _required(browser, "ler_pagina") == set()
    assert _required(browser, "preencher") == {"ref", "texto"}


def test_tools_work_with_only_required_fields(cfg):
    agent = Agent(cfg)
    save, search = knowledge_tools(agent.kb)
    reply = asyncio.run(save.handler({"area": "financas", "titulo": "Aluguel", "conteudo": "R$ 1.500, dia 5",
                                      "tags": '["aluguel", "fixo"]'}))
    assert not reply["is_error"]
    assert "tags: aluguel, fixo" in next((cfg.knowledge_dir / "financas").glob("*.md")).read_text(encoding="utf-8")
    assert "Aluguel" in text_of(asyncio.run(search.handler({"consulta": "aluguel"})))
    schedule = agenda_tools(agent.agenda)[0]
    reply = asyncio.run(schedule.handler({"titulo": "Água", "instrucao": "Beba água", "modo": "lembrete",
                                          "tipo": "diaria", "hora": "10:00"}))
    assert not reply["is_error"], text_of(reply)


@pytest.mark.parametrize("args, expected", [
    # exatamente o que o modelo gratuito mandou no primeiro teste real
    ({"quando": "2026-10-28T09:00:00-03:00", "modo": "lembrete", "texto": "Pagar o aluguel", "titulo": "Pagar aluguel"},
     ("uma_vez", "2026-10-28", "09:00", "Pagar o aluguel", "lembrete")),
    ({"titulo": "Pagar aluguel", "quando": "2026-10-28 9:00"}, ("uma_vez", "2026-10-28", "09:00", "Pagar aluguel", "lembrete")),
    ({"titulo": "Água", "tipo": "diaria", "quando": "10:00"}, ("diaria", "", "10:00", "Água", "lembrete")),
    ({"titulo": "Gastos", "modo": "tarefa", "instrucao": "Some os gastos", "tipo": "semanal", "dias_semana": "seg",
      "hora": "09:00"}, ("semanal", "", "09:00", "Some os gastos", "tarefa")),
])
def test_task_from_natural_args(args, expected):
    from agente.core import task_from_args

    t = task_from_args(args)
    assert (t.kind, t.on_date, t.at, t.prompt, t.mode) == expected


def test_schedule_error_shows_examples(cfg):
    schedule = agenda_tools(Agent(cfg).agenda)[0]
    reply = asyncio.run(schedule.handler({"titulo": "Algo", "tipo": "lembrete"}))
    assert reply["is_error"] and "Exemplos que funcionam" in text_of(reply)


def test_builtin_tools_are_restricted(cfg):
    options = Agent(cfg)._options()
    assert options.tools == ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "Agent", "Skill"]
    assert options.env["ENABLE_TOOL_SEARCH"] == "false"


def test_provider_env_for_openrouter(cfg):
    import dataclasses

    from agente.core import provider_env

    assert provider_env(cfg) == {}  # padrão: API da Anthropic
    alt = dataclasses.replace(cfg, base_url="https://openrouter.ai/api", auth_token="sk-or-x", model="vendor/modelo:free")
    env = Agent(alt)._options().env
    assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api" and env["ANTHROPIC_AUTH_TOKEN"] == "sk-or-x"
    assert env["ANTHROPIC_API_KEY"] == ""  # senão a chave da Anthropic teria prioridade
    # subagentes usam apelidos (sonnet): no provedor alternativo todos viram o modelo configurado
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == env["CLAUDE_CODE_SUBAGENT_MODEL"] == "vendor/modelo:free"
    assert alt.has_credentials


def test_no_auto_memory_and_no_background(cfg):
    """Vistos no teste real: o Claude Code carregava a memória de quem programa o projeto, e o subagente
    rodava em segundo plano e a resposta se perdia quando o pedido terminava."""
    env = Agent(cfg)._options().env
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"
    assert all(a.background is False for a in AGENTS.values())


def test_alternative_provider_does_not_show_fake_cost(cfg):
    import dataclasses

    alt = dataclasses.replace(cfg, base_url="https://openrouter.ai/api", auth_token="t", model="m:free")
    agent = Agent(alt)
    agent.client = FakeClient([ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                                             num_turns=4, session_id="s", total_cost_usd=1.241)])
    [event] = collect(agent, "x")
    assert event.text == "ok · 4 passos · custo: veja no painel do provedor"
    assert agent.history.sessions()[0].cost_usd == 0  # o painel não soma a estimativa falsa


def test_free_mode_has_no_paid_web_search(cfg):
    """No OpenRouter o WebSearch é cobrado por pesquisa: no modo provedor alternativo ele sai."""
    import dataclasses

    normal = Agent(cfg)._options()
    assert "WebSearch" in normal.tools and "WebSearch" in normal.agents["pesquisador"].tools
    assert "lite.duckduckgo.com" not in normal.system_prompt

    alt = dataclasses.replace(cfg, base_url="https://openrouter.ai/api", auth_token="t", model="m:free")
    options = Agent(alt)._options()
    assert "WebSearch" not in options.tools and "WebSearch" not in options.allowed_tools
    assert "WebFetch" in options.tools
    researcher = options.agents["pesquisador"]
    assert "WebSearch" not in researcher.tools and "lite.duckduckgo.com" in researcher.prompt
    assert "lite.duckduckgo.com" in options.system_prompt
    assert "WebSearch" in AGENTS["pesquisador"].tools  # o original não é alterado


def test_tool_results_are_logged_with_tool_name(cfg):
    """Para diagnosticar (visto na Amazon): o log guardava só o número clicado, não o que aconteceu."""
    agent = Agent(cfg)
    agent.client = FakeClient([
        AssistantMessage(content=[ToolUseBlock(id="t1", name="mcp__navegador__clicar", input={"ref": "72"})], model="m"),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="Cliquei em [72] Adicionar ao carrinho")]),
        ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s"),
    ])
    collect(agent, "x")
    log = [json.loads(line) for line in next(cfg.logs_dir.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()]
    result = next(e for e in log if e["type"] == "tool_result")
    assert result["name"] == "mcp__navegador__clicar" and result["result"].startswith("Cliquei em [72]")
