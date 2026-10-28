"""Configuração da empresa: dados, catálogo, FAQ e políticas lidos da pasta empresa/.

Tudo o que o atendente sabe do negócio vem daqui. Preço é sempre calculado no código
(`Catalog.quote`), com Decimal, a partir do catálogo: o modelo nunca faz conta de dinheiro.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
import csv
import re
import tomllib
import unicodedata

REQUIRED_FILES = ("empresa.toml", "catalogo.csv")
MAX_QUANTITY = 1000  # pedido maior que isso é caso para a equipe, não para o atendente


class CompanyError(ValueError):
    """Pasta da empresa incompleta ou com dado inválido."""


def normalize(text: str) -> str:
    """Minúsculas e sem acento, para comparar o que o cliente escreve com o catálogo."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.lower()).strip()


def words(text: str) -> list[str]:
    """Palavras com 3 letras ou mais (tira "de", "um", "o"...), com plural simples cortado."""
    out = []
    for w in re.findall(r"[a-z0-9]+", normalize(text)):
        if len(w) < 3:
            continue
        out.append(w[:-1] if len(w) > 4 and w.endswith("s") else w)
    return out


def brl(value: Decimal) -> str:
    """R$ 1.234,56"""
    text = f"{value.quantize(Decimal('0.01'), ROUND_HALF_UP):,.2f}"
    return "R$ " + text.replace(",", "_").replace(".", ",").replace("_", ".")


@dataclass(frozen=True)
class Item:
    code: str
    name: str
    category: str
    price: Decimal
    unit: str = ""
    conditions: str = ""
    description: str = ""

    def describe(self) -> str:
        unit = f" ({self.unit})" if self.unit else ""
        extra = f"; condições: {self.conditions}" if self.conditions else ""
        about = f" — {self.description}" if self.description else ""
        return f"[{self.code}] {self.name}{unit}: {brl(self.price)}{extra}{about}"


@dataclass(frozen=True)
class QuoteLine:
    item: Item
    quantity: int

    @property
    def total(self) -> Decimal:
        return self.item.price * self.quantity


@dataclass(frozen=True)
class Quote:
    lines: tuple[QuoteLine, ...]
    problems: tuple[str, ...] = ()

    @property
    def total(self) -> Decimal:
        return sum((line.total for line in self.lines), Decimal("0"))

    def amounts(self) -> set[Decimal]:
        """Valores que o atendente pode citar depois deste orçamento."""
        return {self.total, *(line.total for line in self.lines)}

    def describe(self) -> str:
        rows = [f"- {l.quantity} × {l.item.name} ({l.item.code}) a {brl(l.item.price)} = {brl(l.total)}"
                for l in self.lines]
        rows.append(f"Total: {brl(self.total)} (preço de catálogo, sem desconto; frete e condições à parte)")
        return "\n".join(rows)


class Catalog:
    def __init__(self, items: list[Item]):
        self.items = items
        self._by_code = {i.code.upper(): i for i in items}

    @classmethod
    def from_csv(cls, path: Path) -> "Catalog":
        items = []
        with path.open(encoding="utf-8-sig", newline="") as f:
            for n, row in enumerate(csv.DictReader(f), start=2):
                row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
                if not row.get("codigo") or not row.get("nome"):
                    raise CompanyError(f"catalogo.csv linha {n}: falta codigo ou nome")
                items.append(Item(
                    code=row["codigo"], name=row["nome"], category=row.get("categoria", ""),
                    price=parse_price(row.get("preco", ""), f"catalogo.csv linha {n}"),
                    unit=row.get("unidade", ""), conditions=row.get("condicoes", ""),
                    description=row.get("descricao", ""),
                ))
        if not items:
            raise CompanyError("catalogo.csv está vazio")
        return cls(items)

    def get(self, code: str) -> Item | None:
        return self._by_code.get(str(code).strip().upper())

    def categories(self) -> list[str]:
        return sorted({i.category for i in self.items if i.category})

    def search(self, query: str = "", category: str = "", limit: int = 10) -> list[Item]:
        """Itens que batem com a busca (nome, código, categoria, descrição), mais relevantes primeiro."""
        pool = [i for i in self.items if not category or normalize(i.category) == normalize(category)]
        terms = words(query)
        if not terms:
            return pool[:limit]
        exact = self.get(query)
        scored = []
        for item in pool:
            haystack = set(words(f"{item.code} {item.name} {item.category} {item.description}"))
            name = set(words(item.name))
            score = sum(2 if t in name else 1 for t in terms if t in haystack) + (5 if item is exact else 0)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda s: -s[0])
        return [item for _, item in scored[:limit]]

    def find(self, ref: str) -> Item | None:
        """Item por código ou, se não for código, pelo nome mais parecido."""
        hit = self.get(ref)
        if hit:
            return hit
        found = self.search(ref, limit=1)
        return found[0] if found else None

    def quote(self, wanted: list[tuple[str, int]]) -> Quote:
        """Orçamento com preço de catálogo. Itens desconhecidos ou quantidade inválida viram problemas."""
        lines, problems = [], []
        for ref, quantity in wanted:
            item = self.find(ref)
            if not item:
                problems.append(f"'{ref}' não está no catálogo")
            elif not 1 <= quantity <= MAX_QUANTITY:
                problems.append(f"quantidade de {item.name} precisa ser de 1 a {MAX_QUANTITY}")
            else:
                lines.append(QuoteLine(item, quantity))
        return Quote(tuple(lines), tuple(problems))


def parse_price(text: str, where: str) -> Decimal:
    """Aceita 39.90, 39,90 e 1.234,56."""
    raw = text.replace("R$", "").strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise CompanyError(f"{where}: preço inválido '{text}'") from None
    if value < 0:
        raise CompanyError(f"{where}: preço negativo")
    return value


@dataclass(frozen=True)
class Section:
    source: str  # "faq" ou "politicas"
    title: str
    text: str


def sections(markdown: str, source: str) -> list[Section]:
    """Divide o Markdown pelos títulos ## (cada pergunta ou política vira um trecho)."""
    out, title, body = [], "", []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if title or "".join(body).strip():
                out.append(Section(source, title, "\n".join(body).strip()))
            title, body = line[3:].strip(), []
        elif not line.startswith("# "):
            body.append(line)
    if title or "".join(body).strip():
        out.append(Section(source, title, "\n".join(body).strip()))
    return [s for s in out if s.text]


@dataclass(frozen=True)
class Member:
    name: str
    role: str
    whatsapp: str


@dataclass(frozen=True)
class Company:
    name: str
    segment: str
    tone: str
    assistant: str
    city: str
    hours: dict[str, str]
    team: tuple[Member, ...]
    rules: dict
    catalog: Catalog
    info: tuple[Section, ...] = field(default_factory=tuple)
    root: Path | None = None

    @property
    def can_quote(self) -> bool:
        return bool(self.rules.get("informar_preco", True))

    @property
    def can_schedule(self) -> bool:
        return bool(self.rules.get("agendar_retorno", True))

    def hours_text(self) -> str:
        labels = {"seg_sex": "segunda a sexta", "sab": "sábado", "dom": "domingo"}
        parts = [f"{labels.get(k, k)} {v}" if v else f"{labels.get(k, k)} fechado" for k, v in self.hours.items()]
        return "; ".join(parts) or "não informado"

    def team_numbers(self) -> set[str]:
        return {m.whatsapp for m in self.team if m.whatsapp}

    def search_info(self, query: str, limit: int = 3) -> list[Section]:
        """Trechos de FAQ e políticas que mais batem com a pergunta."""
        terms = words(query)
        scored = []
        for s in self.info:
            title, body = set(words(s.title)), set(words(s.text))
            score = sum(3 if t in title else 1 for t in terms if t in title or t in body)
            if score:
                scored.append((score, s))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:limit]]

    def public_text(self) -> str:
        """Todo o texto público da empresa (para conferir percentuais e valores citados pelo atendente)."""
        return "\n".join([*(s.text for s in self.info), *(i.describe() for i in self.catalog.items)])


def load_company(root: Path) -> Company:
    """Lê a pasta da empresa. Erros dizem qual arquivo e linha corrigir."""
    missing = [f for f in REQUIRED_FILES if not (root / f).exists()]
    if missing:
        raise CompanyError(f"pasta {root} sem {', '.join(missing)}")
    try:
        data = tomllib.loads((root / "empresa.toml").read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise CompanyError(f"empresa.toml inválido: {e}") from None
    if not str(data.get("nome", "")).strip():
        raise CompanyError("empresa.toml sem nome")
    team = tuple(
        Member(str(m.get("nome", "")), str(m.get("funcao", "")), re.sub(r"\D", "", str(m.get("whatsapp", ""))))
        for m in data.get("equipe", [])
    )
    info: list[Section] = []
    for name in ("faq", "politicas"):
        path = root / f"{name}.md"
        if path.exists():
            info += sections(path.read_text(encoding="utf-8"), name)
    return Company(
        name=data["nome"].strip(),
        segment=str(data.get("segmento", "")),
        tone=str(data.get("tom", "cordial e direto")),
        assistant=str(data.get("assistente", "assistente virtual")),
        city=str(data.get("cidade", "")),
        hours={k: str(v) for k, v in data.get("horario", {}).items()},
        team=team,
        rules=dict(data.get("regras", {})),
        catalog=Catalog.from_csv(root / "catalogo.csv"),
        info=tuple(info),
        root=root,
    )
