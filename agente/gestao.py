"""Gestão da empresa: lê as planilhas da loja e aponta onde está o dinheiro e onde estão os problemas.

As planilhas ficam na pasta de dados (AGENT_DADOS_DIR; sem ela, `dados/` ou o exemplo fictício em
`exemplos/dados/`), em CSV exportado do sistema da loja ou de uma planilha:

- vendas.csv: cada item de cada OS ou venda (data, os, cliente, item, quantidade, valores, desconto,
  pagamento, funcionário, status);
- despesas.csv: contas pagas (data, categoria, descrição, fornecedor, valor);
- estoque.csv: movimentos de estoque (data, produto, entrada/saída/ajuste, quantidade, custo, os, funcionário);
- caixa.csv: fechamento de caixa (data, funcionário, dinheiro registrado no sistema, dinheiro contado).

Toda conta e todo alerta saem daqui, do código: o modelo só explica e sugere o que fazer. Os alertas
sobre pessoas são **indícios para conferir**, nunca acusação: um lançamento faltando pode ser só esquecimento.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from .empresa import brl, normalize

FILES = ("vendas", "despesas", "estoque", "caixa")
WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")

# Nomes de coluna aceitos (planilhas de sistemas diferentes chamam a mesma coisa de jeitos diferentes).
ALIASES = {
    "data": ("data", "dia", "date", "data_venda", "data_os", "emissao", "data_pagamento", "vencimento"),
    "os": ("os", "ordem", "ordem_servico", "ordem_de_servico", "numero_os", "numero_da_os", "n_os", "no_os", "num_os",
           "pedido", "venda", "documento"),
    "cliente": ("cliente", "nome_cliente"),
    "veiculo": ("veiculo", "carro", "placa", "modelo"),
    "item": ("item", "produto", "servico", "descricao_item", "codigo", "peca"),
    "tipo": ("tipo", "tipo_item", "movimento", "natureza"),
    "quantidade": ("quantidade", "qtd", "qtde", "quant"),
    "valor_unitario": ("valor_unitario", "preco", "preco_unitario", "unitario", "custo_unitario", "custo"),
    "desconto": ("desconto", "valor_desconto", "desc"),
    "total": ("total", "valor_total", "valor", "liquido", "valor_pago"),
    "pagamento": ("pagamento", "forma_pagamento", "forma"),
    "funcionario": ("funcionario", "vendedor", "atendente", "responsavel", "mecanico", "usuario", "operador"),
    "status": ("status", "situacao"),
    "categoria": ("categoria", "conta", "plano_de_contas", "centro_de_custo"),
    "descricao": ("descricao", "historico", "obs", "observacao"),
    "fornecedor": ("fornecedor", "favorecido", "credor"),
    "motivo": ("motivo", "justificativa"),
    "registrado": ("registrado", "dinheiro_registrado", "valor_sistema", "esperado", "sistema"),
    "contado": ("contado", "dinheiro_contado", "valor_contado", "conferido", "real"),
}


class DataError(ValueError):
    """Planilha com coluna faltando ou valor que não dá para ler (a mensagem diz arquivo e linha)."""


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", normalize(name)).strip("_")


def parse_date(text: str) -> date | None:
    text = str(text).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def parse_money(text: str) -> Decimal:
    """1.234,56 · 1234.56 · R$ 50 · -30,00 · (vazio = 0)."""
    raw = str(text or "").replace("R$", "").replace(" ", "").strip()
    if not raw:
        return Decimal("0")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"valor inválido '{text}'") from None


def read_rows(path: Path, required: Iterable[str]) -> list[dict]:
    """Lê um CSV (vírgula ou ponto e vírgula), trocando os nomes de coluna pelos nomes padrão."""
    text = path.read_text(encoding="utf-8-sig")
    dialect = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    reader = csv.DictReader(text.splitlines(), delimiter=dialect)
    names = {}
    for column in reader.fieldnames or []:
        k = _key(column)
        std = next((s for s, options in ALIASES.items() if k in options), k)
        names.setdefault(std, column)
    missing = [r for r in required if r not in names]
    if missing:
        raise DataError(f"{path.name}: faltam as colunas {', '.join(missing)} (aceito também: "
                        + "; ".join(f"{m} = {', '.join(ALIASES.get(m, ()))}" for m in missing) + ")")
    rows = []
    for n, raw in enumerate(reader, start=2):
        row = {std: (raw.get(col) or "").strip() for std, col in names.items()}
        if not any(row.values()):
            continue
        row["_linha"] = n
        rows.append(row)
    return rows


@dataclass
class Sale:
    day: date
    order: str
    item: str
    kind: str  # "servico" ou "peca"
    quantity: Decimal
    unit: Decimal
    discount: Decimal
    total: Decimal
    payment: str
    employee: str
    status: str  # "fechada" ou "cancelada"
    customer: str = ""
    vehicle: str = ""

    @property
    def gross(self) -> Decimal:
        return self.total + self.discount

    @property
    def closed(self) -> bool:
        return not normalize(self.status).startswith("cancel")


@dataclass
class Expense:
    day: date
    category: str
    description: str
    supplier: str
    value: Decimal


@dataclass
class StockMove:
    day: date
    product: str
    kind: str  # "entrada", "saida" ou "ajuste"
    quantity: Decimal  # ajuste negativo = perda
    cost: Decimal
    order: str
    employee: str
    reason: str = ""


@dataclass
class CashClose:
    day: date
    employee: str
    registered: Decimal
    counted: Decimal

    @property
    def difference(self) -> Decimal:
        return self.counted - self.registered


@dataclass
class Data:
    sales: list[Sale] = field(default_factory=list)
    expenses: list[Expense] = field(default_factory=list)
    stock: list[StockMove] = field(default_factory=list)
    cash: list[CashClose] = field(default_factory=list)
    root: Path | None = None
    loaded: tuple[str, ...] = ()

    def last_day(self) -> date | None:
        days = [r.day for rows in (self.sales, self.expenses, self.stock, self.cash) for r in rows]
        return max(days) if days else None


def _row_date(row: dict, where: str) -> date:
    d = parse_date(row.get("data", ""))
    if d is None:
        raise DataError(f"{where} linha {row['_linha']}: data inválida '{row.get('data', '')}' (use 2026-10-28 ou 28/10/2026)")
    return d


def _money(row: dict, col: str, where: str) -> Decimal:
    try:
        return parse_money(row.get(col, ""))
    except ValueError as e:
        raise DataError(f"{where} linha {row['_linha']}, coluna {col}: {e}") from None


def load_data(root: Path) -> Data:
    """Lê as planilhas que existirem na pasta. Nenhuma é obrigatória; coluna essencial faltando é erro."""
    data = Data(root=root)
    loaded = []
    if (path := root / "vendas.csv").exists():
        for r in read_rows(path, ("data", "item", "total")):
            qty = _money(r, "quantidade", "vendas.csv") or Decimal(1)
            total = _money(r, "total", "vendas.csv")
            unit = _money(r, "valor_unitario", "vendas.csv") or (total / qty if qty else total)
            kind = "servico" if normalize(r.get("tipo", "")).startswith("serv") else "peca"
            data.sales.append(Sale(
                _row_date(r, "vendas.csv"), r.get("os", ""), r["item"], kind, qty, unit,
                _money(r, "desconto", "vendas.csv"), total, r.get("pagamento", ""), r.get("funcionario", ""),
                r.get("status", "") or "fechada", r.get("cliente", ""), r.get("veiculo", "")))
        loaded.append("vendas")
    if (path := root / "despesas.csv").exists():
        for r in read_rows(path, ("data", "total")):  # "valor", "valor_pago" etc. viram "total"
            data.expenses.append(Expense(
                _row_date(r, "despesas.csv"), r.get("categoria", "") or "sem categoria", r.get("descricao", ""),
                r.get("fornecedor", ""), abs(_money(r, "total", "despesas.csv"))))
        loaded.append("despesas")
    if (path := root / "estoque.csv").exists():
        for r in read_rows(path, ("data", "item", "tipo", "quantidade")):
            kind = normalize(r["tipo"])
            kind = "saida" if kind.startswith("sai") else "entrada" if kind.startswith("ent") else "ajuste"
            data.stock.append(StockMove(
                _row_date(r, "estoque.csv"), r["item"], kind, _money(r, "quantidade", "estoque.csv"),
                _money(r, "valor_unitario", "estoque.csv"), r.get("os", ""), r.get("funcionario", ""), r.get("motivo", "")))
        loaded.append("estoque")
    if (path := root / "caixa.csv").exists():
        for r in read_rows(path, ("data", "registrado", "contado")):
            data.cash.append(CashClose(
                _row_date(r, "caixa.csv"), r.get("funcionario", ""), _money(r, "registrado", "caixa.csv"),
                _money(r, "contado", "caixa.csv")))
        loaded.append("caixa")
    data.loaded = tuple(loaded)
    return data


# --- período -------------------------------------------------------------------------

@dataclass(frozen=True)
class Period:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous(self) -> "Period":
        return Period(self.start - timedelta(days=self.days), self.start - timedelta(days=1))

    def has(self, d: date) -> bool:
        return self.start <= d <= self.end

    def label(self) -> str:
        return f"{self.start:%d/%m/%Y} a {self.end:%d/%m/%Y}"


def period_from(text: str = "", start: str = "", end: str = "", today: date | None = None) -> Period:
    """Período em formas naturais: "este mês", "mês passado", "últimos 30 dias", "outubro", "semana", ou datas.
    Sem nada: últimos 30 dias até `today` (o último dia com dados, para não analisar um mês vazio)."""
    today = today or date.today()
    s, e = parse_date(start), parse_date(end)
    if s or e:
        return Period(s or (e or today) - timedelta(days=29), e or today)
    t = normalize(text)
    months = ("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro",
              "outubro", "novembro", "dezembro")
    if m := re.search(r"(ultimos|ultimas)\s+(\d+)\s+dias", t):
        return Period(today - timedelta(days=int(m[2]) - 1), today)
    if "mes passado" in t or "mes anterior" in t:
        first = today.replace(day=1)
        last = first - timedelta(days=1)
        return Period(last.replace(day=1), last)
    if "este mes" in t or "esse mes" in t or "mes atual" in t or t.strip() == "mes":
        return Period(today.replace(day=1), today)
    if "semana" in t:
        return Period(today - timedelta(days=6), today)
    for n, name in enumerate(months, start=1):
        if re.search(rf"\b{name}\b", t):
            year = today.year if n <= today.month else today.year - 1
            first = date(year, n, 1)
            nxt = date(year + (n == 12), n % 12 + 1, 1)
            return Period(first, min(nxt - timedelta(days=1), today) if (year, n) == (today.year, today.month) else nxt - timedelta(days=1))
    return Period(today - timedelta(days=29), today)


# --- análises ----------------------------------------------------------------------------

@dataclass
class Finding:
    severity: str  # "alta", "media", "baixa"
    area: str  # "financeiro", "estoque", "caixa", "equipe", "comercial", "funcionamento"
    title: str
    detail: str
    evidence: list[str] = field(default_factory=list)

    def describe(self, max_evidence: int = 8) -> str:
        rows = [f"[{self.severity.upper()} · {self.area}] {self.title}", f"  {self.detail}"]
        rows += [f"  - {e}" for e in self.evidence[:max_evidence]]
        if len(self.evidence) > max_evidence:
            rows.append(f"  - ... e mais {len(self.evidence) - max_evidence}")
        return "\n".join(rows)


SEVERITY_ORDER = {"alta": 0, "media": 1, "baixa": 2}


def pct(part: Decimal, whole: Decimal) -> Decimal:
    return (Decimal(part) / Decimal(whole) * 100).quantize(Decimal("0.1")) if whole else Decimal("0")


def summary(data: Data, period: Period) -> dict:
    """Números do período e a comparação com o período anterior de mesmo tamanho."""

    def numbers(p: Period) -> dict:
        sales = [s for s in data.sales if p.has(s.day) and s.closed]
        revenue = sum((s.total for s in sales), Decimal(0))
        discounts = sum((s.discount for s in sales), Decimal(0))
        orders = {s.order or f"{s.day}-{i}" for i, s in enumerate(sales)}
        expenses = [x for x in data.expenses if p.has(x.day)]
        spent = sum((x.value for x in expenses), Decimal(0))
        by_category = defaultdict(Decimal)
        for x in expenses:
            by_category[x.category] += x.value
        services = sum((s.total for s in sales if s.kind == "servico"), Decimal(0))
        return {
            "receita": revenue, "descontos": discounts, "os": len(orders),
            "ticket_medio": (revenue / len(orders)).quantize(Decimal("0.01")) if orders else Decimal(0),
            "despesas": spent, "resultado": revenue - spent,
            "margem_pct": pct(revenue - spent, revenue), "servicos": services, "pecas": revenue - services,
            "despesas_por_categoria": dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
            "cancelamentos": sum(1 for s in data.sales if p.has(s.day) and not s.closed),
        }

    now, before = numbers(period), numbers(period.previous())
    return {"periodo": period, "atual": now, "anterior": before}


def describe_summary(result: dict) -> str:
    now, before, p = result["atual"], result["anterior"], result["periodo"]

    def change(key: str) -> str:
        if not before[key]:
            return ""
        delta = pct(now[key] - before[key], before[key])
        return f" ({'+' if delta >= 0 else ''}{delta}% vs. período anterior)"

    rows = [f"Período: {p.label()}",
            f"Receita: {brl(now['receita'])}{change('receita')} · serviços {brl(now['servicos'])} · peças {brl(now['pecas'])}",
            f"OS/vendas: {now['os']}{change('os')} · ticket médio {brl(now['ticket_medio'])}",
            f"Descontos dados: {brl(now['descontos'])} ({pct(now['descontos'], now['receita'] + now['descontos'])}% do valor cheio)",
            f"Despesas: {brl(now['despesas'])}{change('despesas')}",
            f"Resultado (receita − despesas): {brl(now['resultado'])} · margem {now['margem_pct']}%",
            f"Cancelamentos: {now['cancelamentos']}"]
    if now["despesas_por_categoria"]:
        rows.append("Despesas por categoria: " + "; ".join(
            f"{k} {brl(v)}" for k, v in list(now["despesas_por_categoria"].items())[:8]))
    return "\n".join(rows)


def comparison_periods(period: Period, n: int = 3) -> list[Period]:
    """Períodos anteriores para comparar gastos. Período que começa no dia 1 é comparado com os meses cheios
    anteriores (contas mensais e quinzenais caem inteiras); os demais, com janelas do mesmo tamanho."""
    out, p = [], period
    for _ in range(n):
        if period.start.day == 1:
            end = p.start - timedelta(days=1)
            p = Period(end.replace(day=1), end)
        else:
            p = p.previous()
        out.append(p)
    return out


def unusual_expenses(data: Data, period: Period) -> list[Finding]:
    """Categoria gastando bem acima da média dos 3 períodos anteriores, e contas lançadas duas vezes."""
    out = []
    history = comparison_periods(period)
    current: defaultdict[str, Decimal] = defaultdict(Decimal)
    for x in data.expenses:
        if period.has(x.day):
            current[x.category] += x.value
    for category, value in current.items():
        past = [sum((x.value for x in data.expenses if h.has(x.day) and x.category == category), Decimal(0)) for h in history]
        past = [v for v in past if v]
        if not past:
            continue
        avg = sum(past, Decimal(0)) / len(past)
        if value > avg * Decimal("1.4") and value - avg >= 300:
            out.append(Finding(
                "alta" if value > avg * 2 else "media", "financeiro",
                f"Gasto com {category} acima do normal",
                f"{brl(value)} no período contra média de {brl(avg)} nos 3 períodos anteriores "
                f"(+{pct(value - avg, avg)}%).",
                [f"{x.day:%d/%m} {x.description or x.supplier}: {brl(x.value)}"
                 for x in sorted(data.expenses, key=lambda x: -x.value) if period.has(x.day) and x.category == category]))
    seen: dict[tuple, Expense] = {}
    dupes = []
    for x in sorted((x for x in data.expenses if period.has(x.day)), key=lambda x: x.day):
        key = (normalize(x.supplier or x.description), x.value)
        prev = seen.get(key)
        if prev and (x.day - prev.day).days <= 5 and x.value >= 100:
            dupes.append(f"{x.supplier or x.description}: {brl(x.value)} em {prev.day:%d/%m} e de novo em {x.day:%d/%m}")
        seen[key] = x
    if dupes:
        out.append(Finding("media", "financeiro", "Possíveis contas pagas em duplicidade",
                           "Mesmo fornecedor e mesmo valor em poucos dias: confira se não foi pago duas vezes.", dupes))
    return out


def stock_without_sale(data: Data, period: Period) -> list[Finding]:
    """Peça que saiu do estoque sem OS fechada: pode ser lançamento esquecido, garantia, uso interno ou desvio.

    Compara pela OS, não pelo nome: o serviço consome peças com outro nome (a OS diz "troca de óleo",
    do estoque sai "óleo 5W30" e "filtro"), então exigir o mesmo nome daria alarme falso em toda troca.
    """
    closed = {normalize(s.order) for s in data.sales if s.order and s.closed}
    cancelled = {normalize(s.order) for s in data.sales if s.order and not s.closed} - closed
    by_employee: dict[str, list[str]] = defaultdict(list)
    cost_by_employee: Counter = Counter()
    for m in data.stock:
        if m.kind != "saida" or not period.has(m.day):
            continue
        order = normalize(m.order)
        if order in closed:
            continue
        why = "sem OS" if not order else (f"OS {m.order} cancelada" if order in cancelled else f"OS {m.order} não existe nas vendas")
        who = m.employee or "(sem funcionário)"
        by_employee[who].append(f"{m.day:%d/%m} {m.quantity:g} × {m.product} ({why})" + (f" · custo {brl(m.cost * m.quantity)}" if m.cost else ""))
        cost_by_employee[who] += float(m.cost * m.quantity)
    out = []
    total_lines = sum(len(v) for v in by_employee.values())
    for who, rows in sorted(by_employee.items(), key=lambda kv: -len(kv[1])):
        share = len(rows) / total_lines
        severity = "alta" if len(rows) >= 5 and share >= 0.5 else "media" if len(rows) >= 3 else "baixa"
        out.append(Finding(
            severity, "estoque", f"Saídas de estoque sem venda correspondente: {who}",
            f"{len(rows)} saída(s) no período sem OS fechada"
            + (f", custo de {brl(Decimal(str(round(cost_by_employee[who], 2))))}" if cost_by_employee[who] else "")
            + ". Indício para conferir: pode ser esquecimento de lançar na OS, garantia, uso interno ou desvio.",
            rows))
    losses = defaultdict(list)
    for m in data.stock:
        if m.kind == "ajuste" and m.quantity < 0 and period.has(m.day):
            losses[m.employee or "(sem funcionário)"].append(f"{m.day:%d/%m} {m.quantity:g} × {m.product} ({m.reason or 'sem motivo'})")
    for who, rows in losses.items():
        if len(rows) >= 3:
            out.append(Finding("media", "estoque", f"Muitos ajustes de perda de estoque: {who}",
                               f"{len(rows)} ajustes negativos no período. Confira os motivos.", rows))
    return out


def discounts_by_employee(data: Data, period: Period) -> list[Finding]:
    """Quem dá muito mais desconto ou cancela muito mais que o resto da equipe."""
    gross, disc = Counter(), Counter()
    orders, cancelled_orders = defaultdict(set), defaultdict(set)  # por OS: uma OS de 3 itens é um cancelamento
    for i, s in enumerate(data.sales):
        if not period.has(s.day) or not s.employee:
            continue
        key = s.order or f"linha-{i}"
        orders[s.employee].add(key)
        if not s.closed:
            cancelled_orders[s.employee].add(key)
            continue
        gross[s.employee] += float(s.gross)
        disc[s.employee] += float(s.discount)
    count = Counter({who: len(v) for who, v in orders.items()})
    cancelled = Counter({who: len(v) for who, v in cancelled_orders.items()})
    out = []
    team_rate = sum(disc.values()) / sum(gross.values()) * 100 if sum(gross.values()) else 0
    for who in gross:
        rate = disc[who] / gross[who] * 100 if gross[who] else 0
        others_gross = sum(gross.values()) - gross[who]
        others = (sum(disc.values()) - disc[who]) / others_gross * 100 if others_gross else 0
        if rate >= 5 and rate >= 2 * max(others, 0.5):
            out.append(Finding(
                "alta" if rate >= 10 else "media", "equipe", f"Desconto bem acima do resto da equipe: {who}",
                f"{rate:.1f}% de desconto sobre o valor cheio ({brl(Decimal(str(round(disc[who], 2))))} no período), "
                f"contra {others:.1f}% dos demais (média da loja {team_rate:.1f}%). Confira se há autorização para esses descontos.",
                [f"{s.day:%d/%m} OS {s.order} {s.item}: desconto {brl(s.discount)} sobre {brl(s.gross)}"
                 for s in sorted(data.sales, key=lambda s: -s.discount) if period.has(s.day) and s.employee == who and s.discount]))
    total_cancel = sum(cancelled.values())
    for who, n in cancelled.items():
        rate = n / count[who]
        others = (total_cancel - n) / max(1, sum(count.values()) - count[who])
        if n >= 3 and rate >= 2 * max(others, 0.02):
            out.append(Finding("media", "equipe", f"Cancelamentos acima do normal: {who}",
                               f"{n} de {count[who]} lançamentos cancelados ({rate:.0%}) contra {others:.0%} dos demais. "
                               "Venda cancelada depois de recebida é um padrão comum de desvio: confira.",
                               [f"{s.day:%d/%m} OS {s.order} {s.item} {brl(s.total)}" for s in data.sales
                                if period.has(s.day) and s.employee == who and not s.closed]))
    return out


def cash_differences(data: Data, period: Period, tolerance: Decimal = Decimal("20")) -> list[Finding]:
    """Caixa contado diferente do registrado no sistema, por funcionário."""
    by_employee = defaultdict(list)
    for c in data.cash:
        if period.has(c.day) and abs(c.difference) > tolerance:
            by_employee[c.employee or "(sem funcionário)"].append(c)
    out = []
    for who, closes in by_employee.items():
        missing = sum((c.difference for c in closes if c.difference < 0), Decimal(0))
        severity = "alta" if len(closes) >= 3 and missing <= -150 else "media" if len(closes) >= 2 else "baixa"
        out.append(Finding(
            severity, "caixa", f"Diferença de caixa: {who}",
            f"{len(closes)} fechamento(s) com diferença acima de {brl(tolerance)}; faltando no total {brl(-missing)}.",
            [f"{c.day:%d/%m}: registrado {brl(c.registered)}, contado {brl(c.counted)} ({brl(c.difference)})" for c in closes]))
    return out


def operations(data: Data, period: Period) -> dict:
    """Funcionamento: movimento por dia da semana, serviços que mais faturam, vendas por funcionário."""
    sales = [s for s in data.sales if period.has(s.day) and s.closed]
    orders_by_day = defaultdict(set)
    for s in sales:
        orders_by_day[s.day.weekday()].add(s.order or id(s))
    weeks = max(1, period.days / 7)
    by_item, by_employee = Counter(), Counter()
    for s in sales:
        by_item[s.item] += float(s.total)
        by_employee[s.employee or "(sem funcionário)"] += float(s.total)
    return {
        "os_por_dia_semana": {WEEKDAYS[d]: round(len(v) / weeks, 1) for d, v in sorted(orders_by_day.items())},
        "itens_que_mais_faturam": by_item.most_common(8),
        "vendas_por_funcionario": by_employee.most_common(),
    }


def describe_operations(ops: dict) -> str:
    rows = ["Média de OS por dia da semana: " + "; ".join(f"{d} {n}" for d, n in ops["os_por_dia_semana"].items())]
    rows.append("Itens que mais faturam: " + "; ".join(f"{i} {brl(Decimal(str(round(v, 2))))}" for i, v in ops["itens_que_mais_faturam"]))
    rows.append("Vendas por funcionário: " + "; ".join(f"{e} {brl(Decimal(str(round(v, 2))))}" for e, v in ops["vendas_por_funcionario"]))
    return "\n".join(rows)


def bottlenecks(data: Data, period: Period) -> list[Finding]:
    ops = operations(data, period)
    per_day = ops["os_por_dia_semana"]
    out = []
    if len(per_day) >= 3:
        avg = sum(per_day.values()) / len(per_day)
        busy = [d for d, n in per_day.items() if n >= avg * 1.5]
        idle = [d for d, n in per_day.items() if n <= avg * 0.5]
        if busy or idle:
            out.append(Finding("baixa", "funcionamento", "Movimento desigual na semana",
                               f"Média de {avg:.1f} OS por dia. "
                               + (f"Dias cheios: {', '.join(busy)} (fila e espera). " if busy else "")
                               + (f"Dias vazios: {', '.join(idle)} (dá para puxar agendamentos e promoções para eles)." if idle else ""),
                               [f"{d}: {n} OS/dia" for d, n in per_day.items()]))
    return out


def crm_funnel(crm, days: int = 30, now: datetime | None = None) -> dict:
    """Funil do atendente: leads por etapa, origem, retomadas e motivos de perda (do crm.db)."""
    now = now or datetime.now()
    since = now - timedelta(days=days)
    contacts = [c for c in crm.contacts(limit=100000) if datetime.fromisoformat(c.created) >= since]
    stages = Counter(c.stage for c in contacts)
    reasons, followups = Counter(), 0
    for c in contacts:
        for i in crm.interactions(c.phone, limit=500):
            if i.direction == "retomada":
                followups += 1
            elif i.direction == "evento" and "motivo provável:" in i.text:
                reasons[i.text.split("motivo provável:")[1].strip()] += 1
    total = len(contacts)
    return {"dias": days, "leads": total, "por_etapa": dict(stages), "retomadas": followups,
            "motivos": dict(reasons), "opt_out": sum(1 for c in contacts if c.opt_out),
            "conversao_pct": round(stages.get("ganho", 0) / total * 100, 1) if total else 0.0}


def describe_funnel(f: dict) -> str:
    order = ("novo", "qualificando", "qualificado", "orcamento", "ganho", "perdido")
    stages = " → ".join(f"{s} {f['por_etapa'].get(s, 0)}" for s in order)
    rows = [f"Leads nos últimos {f['dias']} dias: {f['leads']}", f"Funil: {stages}",
            f"Conversão em venda: {f['conversao_pct']}% · retomadas enviadas: {f['retomadas']} · pediram para parar: {f['opt_out']}"]
    if f["motivos"]:
        rows.append("Motivos prováveis de quem parou de responder: " + "; ".join(f"{k} {v}" for k, v in f["motivos"].items()))
    return "\n".join(rows)


ANALYSES = {
    "financeiro": unusual_expenses,
    "estoque": stock_without_sale,
    "equipe": discounts_by_employee,
    "caixa": cash_differences,
    "funcionamento": bottlenecks,
}


def audit(data: Data, period: Period, areas: Iterable[str] = ()) -> list[Finding]:
    """Todos os alertas do período, os mais graves primeiro."""
    chosen = [a for a in areas if a in ANALYSES] or list(ANALYSES)
    findings = [f for a in chosen for f in ANALYSES[a](data, period)]
    return sorted(findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))


def report(data: Data, period: Period, crm=None) -> str:
    """Relatório completo em texto: números, alertas e funcionamento."""
    if not data.loaded:
        return (f"Nenhuma planilha encontrada em {data.root}. Coloque lá vendas.csv, despesas.csv, estoque.csv "
                "e/ou caixa.csv exportados do sistema da loja (veja docs/gestao.md).")
    parts = [f"Planilhas lidas: {', '.join(data.loaded)}", describe_summary(summary(data, period))]
    findings = audit(data, period)
    parts.append(f"\nAlertas ({len(findings)}):" if findings else "\nNenhum alerta no período.")
    parts += [f.describe() for f in findings]
    if data.sales:
        parts.append("\nFuncionamento:\n" + describe_operations(operations(data, period)))
    if crm is not None:
        parts.append("\nAtendimento (WhatsApp):\n" + describe_funnel(crm_funnel(crm, days=period.days)))
    return "\n".join(parts)


def find_rows(data: Data, table: str, query: str = "", employee: str = "", period: Period | None = None,
              limit: int = 50) -> list[str]:
    """Lançamentos de uma planilha, filtrados, para conferir um alerta."""
    rows = {"vendas": data.sales, "despesas": data.expenses, "estoque": data.stock, "caixa": data.cash}.get(table)
    if rows is None:
        raise ValueError(f"tabela desconhecida '{table}'; use uma de: {', '.join(FILES)}")
    q, who = normalize(query), normalize(employee)
    out = []
    for r in rows:
        if period and not period.has(r.day):
            continue
        text = " | ".join(f"{k}={v}" for k, v in vars(r).items())
        if q and q not in normalize(text):
            continue
        if who and who not in normalize(getattr(r, "employee", "")):
            continue
        out.append(text.replace("day=", "data="))
        if len(out) >= limit:
            break
    return out
