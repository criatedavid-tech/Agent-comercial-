"""Passagem para a equipe: o cliente chama uma pessoa, alguém assume, conversa e devolve ao assistente.

Fluxo (decidido no código, não no modelo):
1. O cliente pede uma pessoa (`wants_human`, sem passar pelo modelo) ou o atendente chama a ferramenta
   `chamar_vendedor` (negociação, diagnóstico, reclamação...). O contato fica "aguardando" e a equipe
   recebe o aviso com o resumo da conversa, no WhatsApp e no painel (/atendimento).
2. Enquanto ninguém assume, o assistente fica quieto por `espera_equipe_min` minutos (empresa.toml
   [regras]); as mensagens do cliente vão para a equipe. Passado esse tempo, ele volta a responder o
   que puder, sem fechar o pedido: a equipe ainda pode assumir.
3. Alguém assume ("ASSUMIR 12" no WhatsApp da equipe ou o botão no painel): o contato fica "humano",
   o assistente não responde mais e tudo o que o cliente manda vai para quem assumiu.
4. "DEVOLVER" (ou o botão): o assistente volta a atender. A retomada automática não mexe em quem
   está com a equipe.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
import re

from .crm import Contact, Crm
from .empresa import Company, normalize
from .retomada import is_open

DEFAULT_WAIT_MIN = 15
PANEL = "painel"  # responsável quando quem assumiu foi o painel (/atendimento)
HISTORY_LINES = 8  # mensagens que vão no aviso para a equipe

# "quero falar com um atendente", "tem alguém aí de verdade?", "me passa pra um humano"
HUMAN = re.compile(
    r"\b(falar|conversar|atendimento|atendid[oa]|passa\w*|transfer\w*|chama\w*)\b.{0,25}"
    r"\b(atendente|humano|humana|pessoa|vendedor|vendedora|gerente|consultor|consultora|alguem|responsavel|dono)\b"
    r"|\b(pessoa|alguem|atendente|humano) de verdade\b|\batendimento humano\b|\bnao quero (falar com )?(robo|bot|maquina)\b"
)


def wants_human(text: str) -> bool:
    return bool(HUMAN.search(normalize(text)))


def member_name(company: Company, number: str) -> str:
    if number == PANEL:
        return "painel"
    found = next((m for m in company.team if m.whatsapp == number), None)
    return found.name.split()[0] if found else number


class Desk:
    """Estado e avisos da passagem. Os envios são injetados pela interface (web/WhatsApp); sem eles, só registra."""

    def __init__(
        self,
        crm: Crm,
        company: Company,
        to_team: Callable[[str, str], Awaitable[None]] | None = None,  # (título, texto) para a equipe toda
        to_member: Callable[[str, str], Awaitable[None]] | None = None,  # (número ou "painel", texto)
        to_customer: Callable[[str, str], Awaitable[bool]] | None = None,  # (telefone, texto)
        local_now: Callable[[], datetime] = datetime.now,  # agora no fuso da empresa (horário de atendimento)
    ):
        self.crm = crm
        self.company = company
        self.to_team = to_team
        self.to_member = to_member
        self.to_customer = to_customer
        self.local_now = local_now
        self.wait = timedelta(minutes=float(company.rules.get("espera_equipe_min", DEFAULT_WAIT_MIN)))

    # --- lado do cliente ----------------------------------------------------------------

    def silent(self, contact: Contact, now: datetime | None = None) -> bool:
        """O assistente deve ficar quieto: alguém assumiu, ou a equipe foi chamada há pouco."""
        if contact.handoff == "humano":
            return True
        if contact.handoff == "aguardando" and contact.handoff_at:
            return (now or datetime.now()) - datetime.fromisoformat(contact.handoff_at) < self.wait
        return False

    def customer_reply(self) -> str:
        """O que o cliente ouve ao ser passado para a equipe (escrito pelo código, sem modelo)."""
        team = " ou ".join(m.name.split()[0] for m in self.company.team[:2]) or "alguém da equipe"
        if is_open(self.company, self.local_now()):
            return f"Certo! Já chamei a equipe {self.company.of_name}: {team} continua com você por aqui em instantes."
        return (f"Certo! Já avisei a equipe {self.company.of_name}. Agora estamos fora do horário de atendimento "
                f"({self.company.hours_text()}); assim que abrir, {team} fala com você por aqui.")

    async def request(self, phone: str, reason: str) -> str:
        """Chama a equipe para este cliente. Devolve a frase para o cliente."""
        contact = self.crm.get(phone)
        if contact is None:
            raise ValueError("contato não existe")
        again = contact.handoff == "aguardando"
        if contact.handoff != "humano":
            self.crm.set_handoff(phone, "aguardando", reason)
        self.crm.log(phone, "evento", f"chamou a equipe: {reason}")
        contact = self.crm.get(phone)
        if contact.handoff == "humano" and self.to_member:
            await self.to_member(contact.assignee, f"🙋 #{contact.ticket} {self.label(contact)} pediu de novo: {reason}")
        elif self.to_team:
            title = f"Cliente chamando a equipe (#{contact.ticket})" + (" — de novo" if again else "")
            await self.to_team(title, self.briefing(contact, reason))
        return self.customer_reply()

    async def forward(self, contact: Contact, text: str) -> None:
        """Mensagem do cliente enquanto está com a equipe: vai para quem assumiu (ou para a equipe toda)."""
        line = f"💬 #{contact.ticket} {self.label(contact)}: {text}"
        if contact.handoff == "humano" and self.to_member:
            await self.to_member(contact.assignee, line)
        elif self.to_team:
            await self.to_team(f"Mensagem de cliente aguardando (#{contact.ticket})",
                               f"{line}\n\nResponda ASSUMIR {contact.ticket} para atender.")

    # --- lado da equipe ------------------------------------------------------------------

    def label(self, contact: Contact) -> str:
        return contact.name or contact.phone

    def briefing(self, contact: Contact, reason: str) -> str:
        """Resumo para quem vai assumir: motivo, ficha e as últimas mensagens."""
        lines = [f"Motivo: {reason}", contact.describe(self.company.subject_label or "objeto"),
                 f"Telefone: {contact.phone}", "", "Últimas mensagens:"]
        who = {"entrada": "Cliente", "saida": self.company.assistant, "humano": "Equipe", "retomada": "Retomada"}
        for i in self.crm.interactions(contact.phone, limit=40):
            if i.direction in who:
                lines.append(f"{who[i.direction]}: {i.text[:300]}")
        lines[5:-HISTORY_LINES] = []  # só as últimas, depois do cabeçalho
        lines += ["", f"Responda ASSUMIR {contact.ticket} para atender pelo WhatsApp, ou abra o painel em Atendimento."]
        return "\n".join(lines)

    def queue(self) -> list[Contact]:
        return self.crm.handoffs()

    def describe_queue(self) -> str:
        items = self.queue()
        if not items:
            return "Nenhum cliente com a equipe agora."
        states = {"aguardando": "aguardando", "humano": "com"}
        out = []
        for c in items:
            who = f" {member_name(self.company, c.assignee)}" if c.handoff == "humano" else ""
            out.append(f"#{c.ticket} {self.label(c)}: {states[c.handoff]}{who} · {c.handoff_reason or 'sem motivo'}")
        return "\n".join(out)

    def find(self, ticket: int | None, member: str) -> Contact | None:
        """Contato pelo número; sem número, o único aguardando (ou o único já com este membro)."""
        if ticket:
            found = self.crm.by_ticket(ticket)
            return found if found and found.handoff else None
        waiting = [c for c in self.queue() if c.handoff == "aguardando" or c.assignee == member]
        return waiting[0] if len(waiting) == 1 else None

    async def take(self, contact: Contact, member: str) -> str:
        """Alguém da equipe assume. Devolve o resumo para essa pessoa."""
        previous = contact.assignee if contact.handoff == "humano" else ""
        self.crm.set_handoff(contact.phone, "humano", assignee=member)
        name = member_name(self.company, member)
        self.crm.log(contact.phone, "evento", f"{name} assumiu o atendimento")
        if previous and previous != member and self.to_member:
            await self.to_member(previous, f"#{contact.ticket} {self.label(contact)} passou para {name}.")
        return self.briefing(self.crm.get(contact.phone), contact.handoff_reason or "atendimento")

    async def reply(self, contact: Contact, text: str, member: str) -> bool:
        """Resposta de quem assumiu para o cliente. Fica no CRM como mensagem da equipe."""
        if self.to_customer is None or not await self.to_customer(contact.phone, text):
            return False
        self.crm.log(contact.phone, "humano", text)
        if contact.handoff != "humano" or contact.assignee != member:
            self.crm.set_handoff(contact.phone, "humano", assignee=member)  # respondeu pelo painel sem assumir antes
        return True

    def release(self, contact: Contact, member: str) -> None:
        """Devolve o cliente ao assistente."""
        self.crm.set_handoff(contact.phone, "")
        self.crm.log(contact.phone, "evento", f"{member_name(self.company, member)} devolveu ao assistente")
