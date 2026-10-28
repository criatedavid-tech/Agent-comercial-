"""Gestão: leitura das planilhas, contas, alertas (com os problemas plantados no exemplo) e ferramentas do operador."""

import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from agente import gestao
from agente.config import EXAMPLE_DATA
from agente.core import gestao_tools
from agente.crm import Crm
from agente.gestao import Period, load_data, parse_money, period_from

OCT = Period(date(2026, 10, 1), date(2026, 10, 28))
SEP = Period(date(2026, 9, 1), date(2026, 9, 30))


@pytest.fixture(scope="module")
def data():
    return load_data(EXAMPLE_DATA)


def titles(findings):
    return [f.title for f in findings]


def write(folder, name, text):
    (folder / name).write_text(text, encoding="utf-8")


# --- leitura -------------------------------------------------------------------------------

def test_example_data_loads(data):
    assert data.loaded == ("vendas", "despesas", "estoque", "caixa")
    assert data.last_day() == date(2026, 10, 28)
    assert len(data.sales) > 500 and len(data.stock) > 500


@pytest.mark.parametrize("text,value", [("1.234,56", "1234.56"), ("1234.56", "1234.56"), ("R$ 50", "50"),
                                        ("-30,00", "-30.00"), ("", "0")])
def test_parse_money(text, value):
    assert parse_money(text) == Decimal(value)


def test_reads_other_column_names_and_semicolon(tmp_path):
    write(tmp_path, "vendas.csv", "Data;Nº OS;Serviço;Qtd;Valor Total;Vendedor;Situação\n"
                                  "28/10/2026;123;Alinhamento;1;89,90;Rafael;Fechada\n")
    write(tmp_path, "despesas.csv", "data_pagamento,favorecido,valor_pago,plano_de_contas\n2026-10-05,CPFL,\"900,00\",energia\n")
    data = load_data(tmp_path)
    [sale] = data.sales
    assert (sale.order, sale.item, sale.total, sale.employee, sale.closed) == ("123", "Alinhamento", Decimal("89.90"), "Rafael", True)
    [expense] = data.expenses
    assert (expense.supplier, expense.value, expense.category) == ("CPFL", Decimal("900.00"), "energia")


def test_bad_spreadsheet_says_file_line_and_column(tmp_path):
    write(tmp_path, "vendas.csv", "data,item,total\n2026-10-01,Óleo,abc\n")
    with pytest.raises(gestao.DataError, match="vendas.csv linha 2, coluna total"):
        load_data(tmp_path)
    write(tmp_path, "vendas.csv", "data,item,total\n31/31/2026,Óleo,10\n")
    with pytest.raises(gestao.DataError, match="data inválida"):
        load_data(tmp_path)
    write(tmp_path, "vendas.csv", "dia,coisa\n2026-10-01,x\n")
    with pytest.raises(gestao.DataError, match="faltam as colunas item, total"):
        load_data(tmp_path)


def test_no_spreadsheets_explains_what_to_do(tmp_path):
    data = load_data(tmp_path)
    assert data.loaded == () and "vendas.csv" in gestao.report(data, OCT)


# --- período -------------------------------------------------------------------------------

TODAY = date(2026, 10, 28)


@pytest.mark.parametrize("text,start,end", [
    ("", date(2026, 9, 29), TODAY),
    ("últimos 7 dias", date(2026, 10, 22), TODAY),
    ("este mês", date(2026, 10, 1), TODAY),
    ("mês passado", date(2026, 9, 1), date(2026, 9, 30)),
    ("setembro", date(2026, 9, 1), date(2026, 9, 30)),
    ("outubro", date(2026, 10, 1), TODAY),
    ("dezembro", date(2025, 12, 1), date(2025, 12, 31)),
    ("semana", date(2026, 10, 22), TODAY),
])
def test_period_from_words(text, start, end):
    assert period_from(text, today=TODAY) == Period(start, end)


def test_period_from_dates():
    assert period_from(start="01/10/2026", end="2026-10-15") == Period(date(2026, 10, 1), date(2026, 10, 15))


# --- números -------------------------------------------------------------------------------

def test_summary_numbers_match_the_rows(data):
    result = gestao.summary(data, OCT)["atual"]
    closed = [s for s in data.sales if OCT.has(s.day) and s.closed]
    assert result["receita"] == sum(s.total for s in closed)
    assert result["descontos"] == sum(s.discount for s in closed)
    assert result["despesas"] == sum(x.value for x in data.expenses if OCT.has(x.day))
    assert result["resultado"] == result["receita"] - result["despesas"]
    assert result["os"] == len({s.order for s in closed})
    text = gestao.describe_summary(gestao.summary(data, OCT))
    assert "Receita: R$" in text and "vs. período anterior" in text


# --- alertas: acha os problemas plantados e não inventa outros ------------------------------------

def test_october_finds_every_planted_problem(data):
    found = titles(gestao.audit(data, OCT))
    assert "Saídas de estoque sem venda correspondente: Diego" in found
    assert "Desconto bem acima do resto da equipe: Paulo" in found
    assert "Diferença de caixa: Juliana" in found
    assert "Gasto com manutencao_equipamentos acima do normal" in found
    assert "Possíveis contas pagas em duplicidade" in found
    # ninguém mais é apontado
    people = [t for t in found if ":" in t]
    assert all(t.endswith(("Diego", "Paulo", "Juliana")) for t in people)


def test_september_has_no_false_alarm(data):
    assert [f for f in gestao.audit(data, SEP) if f.severity in ("alta", "media")] == []


def test_alerts_sorted_by_severity_and_filtered_by_area(data):
    findings = gestao.audit(data, OCT)
    order = [gestao.SEVERITY_ORDER[f.severity] for f in findings]
    assert order == sorted(order)
    assert {f.area for f in gestao.audit(data, OCT, ["caixa"])} == {"caixa"}


def test_people_alerts_are_worded_as_indications(data):
    [diego] = [f for f in gestao.audit(data, OCT, ["estoque"]) if "Diego" in f.title]
    assert "Indício para conferir" in diego.detail and diego.severity == "alta"
    assert all("sem OS" in e or "não existe" in e for e in diego.evidence)


def test_stock_used_by_service_is_not_flagged():
    """A OS diz "Troca de óleo", do estoque sai "Óleo 5W30": é consumo do serviço, não desvio."""
    data = gestao.Data(
        sales=[gestao.Sale(date(2026, 10, 1), "OS-1", "Troca de óleo com filtro", "servico", Decimal(1),
                           Decimal("189.90"), Decimal(0), Decimal("189.90"), "pix", "Rafael", "fechada")],
        stock=[gestao.StockMove(date(2026, 10, 1), "Óleo 5W30 sintético 1L", "saida", Decimal(4), Decimal(28), "OS-1", "Bruno")],
    )
    assert gestao.stock_without_sale(data, OCT) == []
    data.sales[0].status = "cancelada"
    [finding] = gestao.stock_without_sale(data, OCT)
    assert "OS OS-1 cancelada" in finding.evidence[0]


def test_duplicate_expense_and_cash_rules():
    day = date(2026, 10, 10)
    data = gestao.Data(
        expenses=[gestao.Expense(day, "lub", "Óleo", "Lub", Decimal(1480)),
                  gestao.Expense(day + timedelta(days=3), "lub", "Óleo", "Lub", Decimal(1480)),
                  gestao.Expense(day + timedelta(days=20), "lub", "Óleo", "Lub", Decimal(1480))],  # mês seguinte: normal
        cash=[gestao.CashClose(day, "Ana", Decimal(500), Decimal(490)),  # dentro da tolerância
              gestao.CashClose(day, "Leo", Decimal(500), Decimal(400))],
    )
    [dupe] = [f for f in gestao.unusual_expenses(data, OCT) if "duplicidade" in f.title]
    assert len(dupe.evidence) == 1
    [cash] = gestao.cash_differences(data, OCT)
    assert cash.title.endswith("Leo") and "R$ 100,00" in cash.detail


def test_find_rows_for_drill_down(data):
    rows = gestao.find_rows(data, "estoque", employee="Diego", period=OCT, query="bateria")
    assert rows and all("Diego" in r and "Bateria" in r for r in rows)
    with pytest.raises(ValueError, match="tabela desconhecida"):
        gestao.find_rows(data, "salarios")


# --- funil do atendimento ---------------------------------------------------------------------

def test_crm_funnel(tmp_path):
    crm = Crm(tmp_path / "crm.db")
    for phone, stage in [("1", "orcamento"), ("2", "ganho"), ("3", "perdido"), ("4", "novo")]:
        crm.ensure(phone, "whatsapp", opt_in=True)
        crm.update(phone, stage=stage)
    crm.log("3", "retomada", "Oi, ficou alguma dúvida?")
    crm.log("3", "evento", "retomada 1/2; motivo provável: achou caro")
    crm.set_opt_out("4")
    f = gestao.crm_funnel(crm, days=30)
    assert f["leads"] == 4 and f["conversao_pct"] == 25.0 and f["retomadas"] == 1 and f["opt_out"] == 1
    assert f["motivos"] == {"achou caro": 1}
    assert "Funil: novo 1 → qualificando 0 → qualificado 0 → orcamento 1 → ganho 1 → perdido 1" in gestao.describe_funnel(f)


# --- ferramentas do operador ---------------------------------------------------------------------

def call(cfg, name, args):
    tool = next(t for t in gestao_tools(cfg) if t.name == name)
    out = asyncio.run(tool.handler(args))
    return out["content"][0]["text"], out["is_error"]


@pytest.fixture
def gcfg(cfg):
    return replace(cfg, data_dir=EXAMPLE_DATA)


def test_report_tool(gcfg):
    text, error = call(gcfg, "relatorio_gestao", {"periodo": "outubro"})
    assert not error and "Período: 01/10/2026 a 28/10/2026" in text and "Diego" in text and "Atendimento (WhatsApp)" in text


def test_alerts_tool_by_area(gcfg):
    text, _ = call(gcfg, "alertas_gestao", {"periodo": "outubro", "area": "caixa"})
    assert "Juliana" in text and "Diego" not in text
    text, _ = call(gcfg, "alertas_gestao", {"inicio": "01/09/2026", "fim": "30/09/2026", "area": "caixa"})
    assert text.startswith("nenhum alerta")


def test_rows_tool(gcfg):
    text, error = call(gcfg, "consultar_lancamentos", {"planilha": "Estoque", "funcionario": "diego", "periodo": "outubro"})
    assert not error and "Diego" in text
    assert call(gcfg, "consultar_lancamentos", {"planilha": "salarios"})[1]


def test_tools_report_broken_spreadsheet(cfg, tmp_path):
    (tmp_path / "vendas.csv").write_text("data,item,total\nontem,Óleo,10\n", encoding="utf-8")
    text, error = call(replace(cfg, data_dir=tmp_path), "relatorio_gestao", {})
    assert error and "planilha com problema" in text


def test_operator_prompt_mentions_example_data(cfg):
    from agente.core import Agent
    prompt = Agent(replace(cfg, data_dir=EXAMPLE_DATA))._options().system_prompt
    assert "relatorio_gestao" in prompt and "dados fictícios de exemplo" in prompt
    assert "indício para conferir, nunca acusação" in prompt


def test_example_generator_is_reproducible(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("gerar", EXAMPLE_DATA / "gerar_exemplo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERE", tmp_path)
    module.main()
    for name in gestao.FILES:
        # compara linhas, não bytes: o git troca CRLF por LF conforme o sistema
        generated = (tmp_path / f"{name}.csv").read_text(encoding="utf-8").splitlines()
        assert generated == (EXAMPLE_DATA / f"{name}.csv").read_text(encoding="utf-8").splitlines()
