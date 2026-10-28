"""Configuração da empresa (catálogo, FAQ, políticas) e CRM por contato."""

from decimal import Decimal

import pytest

from agente.config import EXAMPLE_COMPANY
from agente.crm import ATTENDANT_STAGES, Crm, clean_phone
from agente.empresa import Catalog, CompanyError, brl, load_company, parse_price, sections


@pytest.fixture
def company():
    return load_company(EXAMPLE_COMPANY)


@pytest.fixture
def crm(tmp_path):
    return Crm(tmp_path / "crm.db")


# --- empresa ------------------------------------------------------------------

def test_example_company_loads(company):
    assert company.name == "Casa Verde Jardinagem"
    assert company.assistant == "Flora"
    assert len(company.team) == 2 and company.team_numbers() == {"5519999990001", "5519999990002"}
    assert company.can_quote and company.can_schedule
    assert "segunda a sexta 08:00-18:00" in company.hours_text() and "domingo fechado" in company.hours_text()
    assert {"plantas", "servicos", "gramas"} <= set(company.catalog.categories())
    assert {s.source for s in company.info} == {"faq", "politicas"}


def test_catalog_search_ignores_accents_and_plural(company):
    assert company.catalog.search("orquideas")[0].code == "ORQ-01"
    assert company.catalog.search("Orquídea")[0].code == "ORQ-01"
    assert company.catalog.search("ORQ-01")[0].code == "ORQ-01"
    assert company.catalog.search("helicóptero") == []
    assert {i.category for i in company.catalog.search(category="vasos")} == {"vasos"}


def test_quote_is_computed_with_catalog_prices(company):
    quote = company.catalog.quote([("ORQ-01", 2), ("vaso de cerâmica", 1), ("GRAMA-M2", 30)])
    assert quote.total == Decimal("79.90") * 2 + Decimal("64.00") + Decimal("16.90") * 30
    assert quote.total == Decimal("730.80")
    assert "Total: R$ 730,80" in quote.describe() and "sem desconto" in quote.describe()
    assert Decimal("159.80") in quote.amounts()


def test_quote_rejects_unknown_items_and_bad_quantities(company):
    quote = company.catalog.quote([("PIANO", 1), ("ORQ-01", 0), ("ORQ-01", 5000), ("JIB-01", 1)])
    assert [l.item.code for l in quote.lines] == ["JIB-01"]
    assert len(quote.problems) == 3


def test_brl_and_prices():
    assert brl(Decimal("1234.5")) == "R$ 1.234,50"
    assert parse_price("39,90", "x") == Decimal("39.90")
    assert parse_price("1.234,56", "x") == Decimal("1234.56")
    with pytest.raises(CompanyError):
        parse_price("caro", "x")
    with pytest.raises(CompanyError):
        parse_price("-1", "x")


def test_faq_search(company):
    [best, *_] = company.search_info("vocês entregam em Valinhos?")
    assert best.title == "Vocês entregam?"
    assert company.search_info("trocas")[0].title == "Trocas e garantia"
    assert company.search_info("xyzw") == []


def test_sections_split_by_heading():
    parts = sections("# FAQ\n\n## Um\ntexto 1\n\n## Dois\ntexto 2\n## Vazio\n", "faq")
    assert [(s.title, s.text) for s in parts] == [("Um", "texto 1"), ("Dois", "texto 2")]


def test_broken_company_folder_says_what_to_fix(tmp_path):
    with pytest.raises(CompanyError, match="empresa.toml"):
        load_company(tmp_path)
    (tmp_path / "empresa.toml").write_text('nome = "X"', encoding="utf-8")
    (tmp_path / "catalogo.csv").write_text("codigo,nome,preco\nA,Item,abc\n", encoding="utf-8")
    with pytest.raises(CompanyError, match="linha 2"):
        load_company(tmp_path)
    (tmp_path / "empresa.toml").write_text("nome = ", encoding="utf-8")
    with pytest.raises(CompanyError, match="inválido"):
        load_company(tmp_path)


def test_catalog_needs_rows(tmp_path):
    path = tmp_path / "c.csv"
    path.write_text("codigo,nome,preco\n", encoding="utf-8")
    with pytest.raises(CompanyError, match="vazio"):
        Catalog.from_csv(path)


# --- CRM ------------------------------------------------------------------------

def test_contact_is_created_once_with_opt_in(crm):
    first = crm.ensure("+55 (19) 99999-0000", "whatsapp", opt_in=True)
    assert first.phone == "5519999990000" and first.stage == "novo" and first.opt_in
    again = crm.ensure("5519999990000", "outra origem")
    assert again.origin == "whatsapp" and again.created == first.created


def test_update_keeps_existing_fields(crm):
    crm.ensure("1")
    crm.update("1", name="Ana", interest="orquídea")
    contact = crm.update("1", stage="qualificando", interest="", deadline="sábado")
    assert (contact.name, contact.interest, contact.deadline, contact.stage) == ("Ana", "orquídea", "sábado", "qualificando")
    with pytest.raises(ValueError, match="campo desconhecido"):
        crm.update("1", telefone="2")
    with pytest.raises(ValueError, match="não existe"):
        crm.update("999", name="X")


def test_attendant_view_cannot_mark_sale_won(crm):
    crm.ensure("1")
    view = crm.view("1")
    assert "ganho" not in ATTENDANT_STAGES
    with pytest.raises(ValueError, match="não permitida"):
        view.update(stage="ganho")
    assert crm.update("1", stage="ganho").stage == "ganho"  # a equipe (operador) pode


def test_view_is_locked_to_one_contact(crm):
    crm.ensure("1")
    crm.ensure("2")
    crm.update("2", name="Outro cliente")
    view = crm.view("1")
    view.update(name="Ana")
    view.log("entrada", "oi")
    view.add_followup("segunda", "orçamento")
    assert crm.get("2").name == "Outro cliente"
    assert crm.interactions("2") == [] and crm.followups("2") == []
    assert [f.reason for f in view.followups()] == ["orçamento"]
    assert not hasattr(view, "contacts") and not hasattr(view, "delete")


def test_interactions_keep_order(crm):
    crm.ensure("1")
    for i in range(5):
        crm.log("1", "entrada", f"m{i}")
    assert [i.text for i in crm.interactions("1", limit=3)] == ["m2", "m3", "m4"]


def test_delete_contact_removes_everything(crm):
    crm.ensure("1")
    crm.log("1", "entrada", "oi")
    crm.add_followup("1", "amanhã", "x")
    assert crm.delete("1")
    assert crm.get("1") is None and crm.interactions("1") == [] and crm.followups("1") == []
    assert not crm.delete("1")


def test_followup_needs_when(crm):
    crm.ensure("1")
    with pytest.raises(ValueError):
        crm.add_followup("1", "  ", "x")


def test_clean_phone():
    assert clean_phone("+55 19 99999-0000") == "5519999990000"
    assert clean_phone("sim-AB12!") == "sim-ab12"


def test_company_dir_resolution(tmp_path, monkeypatch):
    from agente import config
    monkeypatch.setattr(config, "ROOT", tmp_path)
    assert config.company_dir("") == config.EXAMPLE_COMPANY  # sem empresa/: usa o exemplo
    (tmp_path / "empresa").mkdir()
    (tmp_path / "empresa" / "empresa.toml").write_text('nome = "X"', encoding="utf-8")
    assert config.company_dir("") == tmp_path / "empresa"
    assert config.company_dir("outra") == tmp_path / "outra"
    assert config.company_dir(str(tmp_path / "abs")) == tmp_path / "abs"
