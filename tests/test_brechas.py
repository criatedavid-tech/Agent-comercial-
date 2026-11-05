"""Brechas: o que a empresa perde ou deixa de ganhar, com evidência, valor e status (sem IA, sem custo)."""

import asyncio
from decimal import Decimal

import pytest

from agente.brechas import AREAS, OPEN, STATUSES, BrechaError, BrechaStore, cents, documents
from agente.core import PLUGIN_DIR, SKILLS, brechas_tools
from agente.subagents import AGENTS

EVIDENCE = "alertas_gestao (financeiro), outubro: duas linhas de despesas com o mesmo documento"


@pytest.fixture
def store(tmp_path):
    return BrechaStore(tmp_path / "brechas.db")


def test_register_creates_a_new_brecha_with_values_in_cents(store):
    brecha, what = store.register("NF 18777 do Boi Bom paga duas vezes", "financeiro", EVIDENCE,
                                  "pedir estorno ao fornecedor", once="R$ 2.340,00")
    assert what == "criada" and brecha.status == "nova" and brecha.area == "financeiro"
    assert brecha.once_cents == 234000 and brecha.monthly_cents == 0
    assert brecha.value() == "R$ 2.340,00 uma vez"
    assert "#1 [nova] financeiro" in brecha.describe() and "pedir estorno" in brecha.describe()


@pytest.mark.parametrize("value, expected", [
    (None, 0), ("", 0), (1500, 150000), ("1500.5", 150050), ("R$ 1.234,56", 123456), ("0,10", 10), (Decimal("2.345"), 235),
])
def test_values_are_parsed_without_float_errors(value, expected):
    assert cents(value, "valor") == expected


@pytest.mark.parametrize("value", ["muito", "-5", "99999999999"])
def test_absurd_values_are_refused(value):
    with pytest.raises(BrechaError):
        cents(value, "valor")


def test_without_evidence_there_is_no_brecha(store):
    with pytest.raises(BrechaError, match="evidência"):
        store.register("Desconto alto", "financeiro", "  ")
    with pytest.raises(BrechaError, match="título"):
        store.register("", "financeiro", EVIDENCE)
    with pytest.raises(BrechaError, match="área"):
        store.register("Algo", "marketing", EVIDENCE)
    assert store.items() == []


def test_same_title_updates_the_open_one(store):
    first, _ = store.register("Caixa com diferença", "financeiro", EVIDENCE, monthly=100)
    second, what = store.register("caixa com  DIFERENÇA", "financeiro", "conferido de novo em novembro", monthly=150)
    assert what == "atualizada" and second.id == first.id
    assert second.monthly_cents == 15000 and "novembro" in second.evidence
    assert len(store.items()) == 1


def test_update_without_new_values_keeps_the_old_ones(store):
    store.register("Gasto com frete subiu", "financeiro", EVIDENCE, "renegociar", monthly=300)
    again, _ = store.register("Gasto com frete subiu", "financeiro", "outra conferência")
    assert again.monthly_cents == 30000 and again.action == "renegociar"


def test_same_document_in_the_title_is_not_a_second_brecha(store):
    """Dois especialistas achando a mesma nota: uma brecha só, com a observação do segundo."""
    first, _ = store.register("NF 18777 paga duas vezes", "financeiro", EVIDENCE, once=2340)
    twin, what = store.register("Pagamento em duplicidade da nota fiscal 18777", "operacao", "visto no pedido ao fornecedor", once=99)
    assert what == "anotada" and twin.id == first.id
    assert twin.once_cents == 234000 and twin.area == "financeiro"  # o segundo não troca área nem valor
    assert len(store.items()) == 1 and "mesmo documento" in store.notes(first.id)[0]
    assert documents("Nota 4410 e boleto 77") == {"nota4410"}  # número curto (menos de 3 dígitos) não conta


def test_different_documents_are_different_brechas(store):
    store.register("NF 18777 paga duas vezes", "financeiro", EVIDENCE, once=2340)
    store.register("NF 18778 paga duas vezes", "financeiro", EVIDENCE, once=100)
    assert len(store.items()) == 2


def test_a_resolved_brecha_does_not_absorb_a_new_finding(store):
    old, _ = store.register("Caixa com diferença", "financeiro", EVIDENCE)
    store.update(old.id, "resolvida")
    new, what = store.register("Caixa com diferença", "financeiro", "voltou em dezembro")
    assert what == "criada" and new.id != old.id


def test_registering_never_changes_the_status(store):
    brecha, _ = store.register("Estoque sem venda", "operacao", EVIDENCE)
    store.update(brecha.id, "proposta")
    again, _ = store.register("Estoque sem venda", "operacao", "conferido de novo")
    assert again.status == "proposta"


def test_update_status_and_notes(store):
    brecha, _ = store.register("Estoque sem venda", "operacao", EVIDENCE, once=800)
    done = store.update(brecha.id, "aprovada", "o dono disse sim")
    assert done.status == "aprovada" and "o dono disse sim" in store.notes(brecha.id)[0]
    with pytest.raises(BrechaError, match="status"):
        store.update(brecha.id, "perdida")
    with pytest.raises(BrechaError, match="não existe"):
        store.update(99, "resolvida")
    with pytest.raises(BrechaError, match="anotação"):
        store.update(brecha.id)


def test_listing_is_open_only_and_sorted_by_yearly_value(store):
    small, _ = store.register("Gasto pequeno", "financeiro", EVIDENCE, monthly=50)  # R$ 600 no ano
    big, _ = store.register("Nota em dobro", "financeiro", EVIDENCE, once=2000)  # R$ 2.000
    closed, _ = store.register("Já resolvida", "financeiro", EVIDENCE, once=9000)
    store.update(closed.id, "resolvida")
    assert [b.id for b in store.items()] == [big.id, small.id]
    assert [b.id for b in store.items("resolvida")] == [closed.id]
    assert [b.id for b in store.items(area="operacao")] == []
    text = store.describe()
    assert "2 brecha(s) abertas" in text and "R$ 50,00/mês" in text and "R$ 2.000,00 para recuperar uma vez" in text
    assert "estimativas" in text
    summary = store.summary()
    assert summary["abertas"] == 2 and summary["maior"].id == big.id
    assert summary["mensal"] == Decimal("50") and summary["unico"] == Decimal("2000")


def test_empty_listing(store):
    assert store.describe() == "nenhuma brecha aberta"
    assert store.describe("resolvida", "financeiro") == "nenhuma brecha resolvida em financeiro"


def test_constants_are_consistent():
    assert set(OPEN) < set(STATUSES) and AREAS == ("financeiro", "comercial", "operacao")


# --- ferramentas e agentes -----------------------------------------------------------------------------

def call(cfg, name, args):
    tool = next(t for t in brechas_tools(cfg) if t.name == name)
    out = asyncio.run(tool.handler(args))
    return out["content"][0]["text"], out["is_error"]


def test_tools_register_list_and_update(cfg):
    text, error = call(cfg, "registrar_brecha", {"titulo": "NF 18777 paga duas vezes", "area": "financeiro",
                                                 "evidencia": EVIDENCE, "valor_unico": "2340"})
    assert not error and "brecha criada" in text and "R$ 2.340,00 uma vez" in text
    text, error = call(cfg, "registrar_brecha", {"titulo": "Duplicidade da NF 18777", "area": "operacao", "evidencia": "pedido"})
    assert not error and "anotei nela" in text
    text, _ = call(cfg, "listar_brechas", {})
    assert "1 brecha(s) abertas" in text and "#1 [nova]" in text
    text, error = call(cfg, "atualizar_brecha", {"id": 1, "status": "proposta", "nota": "contada ao dono"})
    assert not error and "[proposta]" in text


def test_tools_explain_the_mistake_instead_of_failing(cfg):
    text, error = call(cfg, "registrar_brecha", {"titulo": "Palpite", "area": "financeiro", "evidencia": ""})
    assert error and "evidência" in text
    text, error = call(cfg, "listar_brechas", {"status": "inventado"})
    assert error and "status:" in text
    text, error = call(cfg, "atualizar_brecha", {"id": 42, "status": "resolvida"})
    assert error and "não existe" in text


def test_register_tool_has_no_status_parameter(cfg):
    """Quem registra não escolhe o status: o gerente é quem atualiza."""
    tool = next(t for t in brechas_tools(cfg) if t.name == "registrar_brecha")
    assert "status" not in tool.input_schema["properties"]
    assert set(tool.input_schema["required"]) == {"titulo", "area", "evidencia"}


def test_specialists_register_but_only_the_manager_updates_status():
    for name in ("comercial", "financeiro", "operacao"):
        tools = AGENTS[name].tools
        assert "mcp__brechas__registrar_brecha" in tools and "mcp__brechas__listar_brechas" in tools
        assert "mcp__brechas__atualizar_brecha" not in tools
        assert "brechas" in AGENTS[name].mcpServers
    assert not any("brechas" in t for n in ("pesquisador", "organizador", "verificador") for t in AGENTS[n].tools)


def test_every_specialist_skill_exists():
    for name in ("comercial", "financeiro", "operacao"):
        for skill in AGENTS[name].skills or []:
            assert skill in SKILLS, f"{name} pede a skill {skill}, que não existe em plugin/skills"
    assert {"agente:raio-x-financeiro", "agente:fechamento-caixa", "agente:despesas-e-duplicidades",
            "agente:estoque-sem-venda", "agente:leads-parados"} <= set(SKILLS)


def test_playbooks_register_brechas_and_never_promise_money_movement():
    for folder in ("raio-x-financeiro", "fechamento-caixa", "despesas-e-duplicidades", "estoque-sem-venda", "leads-parados"):
        text = (PLUGIN_DIR / "skills" / folder / "SKILL.md").read_text(encoding="utf-8")
        assert f"name: {folder}" in text and "description:" in text
        assert "registrar_brecha" in text, folder
        assert "indício" in text or "só lê e recomenda" in text or "só analisa e recomenda" in text, folder
