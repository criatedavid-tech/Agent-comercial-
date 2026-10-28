"""Regras do atendente aplicadas no código, sobre o texto que ele vai mandar ao cliente.

O prompt pede e as ferramentas não permitem; ainda assim um modelo enganado por prompt injection
pode *escrever* "te dou 90% de desconto" ou "pedido confirmado". Este filtro tira essas frases
antes de o cliente ver:

- desconto, abatimento ou percentual que não está nas políticas da empresa;
- valor em reais que não veio do catálogo, das políticas ou de um orçamento calculado pelo código;
- venda, pedido, reserva ou pagamento dado como fechado;
- dizer que é humano (e, quando o cliente pergunta, garantir que ele saiba que fala com um assistente).
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re

from .empresa import normalize

MONEY = re.compile(r"r\$\s*(\d[\d.]*(?:,\d{1,2})?)|(\d[\d.]*(?:,\d{1,2})?)\s*reais")
PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|por cento)")
DISCOUNT = re.compile(r"\bdesconto|\babatimento|\bpromocao especial|%\s*off\b|\bmais barato pra (voce|vc)")
# Frases de recusa ou de passar para a equipe: "não posso dar desconto", "só a equipe de vendas confirma"...
# "a equipe" sozinho não basta: "pedido confirmado, a equipe entrega" continua sendo pedido fechado.
TEAM = r"(equipe|vendedor|vendedora|vendas|consultor|consultora|time)"
NEGATION = rf"\b(nao|nem|nunca|infelizmente)\b|\bquem (confirma|fecha|finaliza|decide)\b|\bso (a|o|com a|com o|pela|pelo)\s+{TEAM}"
REFUSES = re.compile(NEGATION)
DEFLECT = re.compile(rf"{NEGATION}|\bsem desconto\b|\b(com|para|pra|pela|pelo) (a |o )?{TEAM}\b")
CLOSING = re.compile(
    r"\b(pedido|compra|venda|reserva|pagamento|negocio|orcamento)\s+(esta\s+|foi\s+|ja\s+esta\s+)?"
    r"(confirmad|fechad|finalizad|realizad|garantid|aprovad|efetivad)"
    r"|\b(vou|ja|pode deixar que)\s+(reservar|separar|confirmar|fechar|registrar)\s+((o|a|os|as|seu|sua|seus|suas)\s+)*(pedido|compra|venda|reserva)"
    r"|\bchave pix\b|\bpode (fazer|mandar|enviar) o pix\b|\bfechado[!.]?$"
)
HUMAN_CLAIM = re.compile(
    r"(?<!nao )\bsou\s+(um\s+|uma\s+)?(humano|humana|pessoa|gente|atendente humano|atendente humana|funcionari[oa])\b"
    r"|\bnao\s+sou\s+(um\s+|uma\s+)?(robo|bot|ia|inteligencia artificial|assistente virtual|maquina|programa)\b"
)
IDENTITY_QUESTION = re.compile(
    r"\b(voce|vc|tu|ce)\s+(e|eh|seria)\s+(um\s+|uma\s+)?(robo|bot|ia|humano|humana|pessoa|maquina|gente|real|de verdade|inteligencia artificial|virtual)"
    r"|\b(falando|conversando)\s+com\s+(um\s+|uma\s+)?(robo|bot|ia|pessoa|humano|humana|maquina|gente)"
    r"|\be\s+(um\s+)?(robo|bot)\b|\b(robo|bot)\s*\?"
)
DISCLOSED = re.compile(r"\b(assistente virtual|inteligencia artificial|ia|robo|bot|virtual|automatico|automatica)\b")
BUDGET_WORDS = re.compile(r"\b(orcamento|verba|faixa|gastar|investir|pretende|disponivel|ate)\b")


def money_values(text: str) -> set[Decimal]:
    """Valores em reais citados no texto ("R$ 39,90", "R$ 1.200", "50 reais")."""
    out = set()
    for a, b in MONEY.findall(normalize(text)):
        raw = (a or b).rstrip(".")
        try:
            out.add(Decimal(raw.replace(".", "").replace(",", ".")))
        except InvalidOperation:
            pass
    return out


def percent_values(text: str) -> set[Decimal]:
    return {Decimal(p.replace(",", ".")) for p in PERCENT.findall(normalize(text))}


def asks_identity(text: str) -> bool:
    """O cliente quer saber se fala com uma pessoa ou com um robô."""
    return bool(IDENTITY_QUESTION.search(normalize(text)))


@dataclass
class Allowed:
    """O que o atendente pode citar: valores e percentuais do catálogo, das políticas e dos orçamentos."""

    amounts: set[Decimal] = field(default_factory=set)
    percents: set[Decimal] = field(default_factory=set)
    customer_amounts: set[Decimal] = field(default_factory=set)  # o orçamento que o próprio cliente disse

    @classmethod
    def from_text(cls, text: str, prices: set[Decimal] | None = None) -> "Allowed":
        return cls(money_values(text) | set(prices or ()), percent_values(text))


@dataclass
class Screened:
    text: str
    violations: list[str]


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _violation(sentence: str, allowed: Allowed) -> str:
    s = normalize(sentence)
    if HUMAN_CLAIM.search(s):
        return "disse ser humano"
    deflects = bool(DEFLECT.search(s))
    if CLOSING.search(s) and not REFUSES.search(s):
        return "deu venda ou pedido como fechado"
    unknown_percent = percent_values(sentence) - allowed.percents
    if DISCOUNT.search(s) and not deflects:
        return "ofereceu desconto"
    if unknown_percent and not deflects:
        return f"citou percentual fora das políticas ({', '.join(str(p) for p in sorted(unknown_percent))}%)"
    values = money_values(sentence)
    ok = allowed.amounts | (allowed.customer_amounts if BUDGET_WORDS.search(s) else set())
    unknown = {v for v in values if v not in ok}
    if unknown:
        return f"citou valor fora do catálogo ({', '.join(f'R$ {v}' for v in sorted(unknown))})"
    return ""


def screen(text: str, allowed: Allowed, fallback: str) -> Screened:
    """Tira as frases que quebram as regras; se tirou alguma, acrescenta `fallback` (passa para a equipe)."""
    kept, violations = [], []
    for sentence in _sentences(text):
        reason = _violation(sentence, allowed)
        if reason:
            violations.append(reason)
        else:
            kept.append(sentence)
    if not violations:
        return Screened(text, [])
    kept.append(fallback)
    return Screened("\n".join(kept), violations)


def disclose(reply: str, intro: str) -> str:
    """Se o cliente perguntou se é robô e a resposta não deixa claro, o código deixa."""
    if DISCLOSED.search(normalize(reply)):
        return reply
    return f"{intro} {reply}".strip()
