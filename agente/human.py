"""Ponte humana: o agente pausa uma tarefa e pede ao usuário o que só uma pessoa resolve.

Exemplos: CAPTCHA ou verificação de robô, código de dois fatores, login, uma decisão.
O agente nunca tenta burlar essas verificações; ele chama a ponte e espera.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import uuid


@dataclass
class HelpRequest:
    id: str
    reason: str
    link: str


class HumanBridge:
    """Liga a ferramenta `pedir_ajuda_humana` à interface que está conversando (web, terminal...)."""

    def __init__(self, timeout_min: float):
        self.timeout_min = timeout_min
        # A interface define como avisar o usuário (mandar no WebSocket, imprimir no terminal...).
        self.notify: Callable[[HelpRequest], Awaitable[None]] | None = None
        self._pending: dict[str, asyncio.Future[str]] = {}

    async def request(self, reason: str, link: str = "") -> str:
        """Avisa o usuário e espera a resposta dele (ou o tempo limite)."""
        if not self.notify:
            return "nenhuma pessoa conectada para ajudar agora; siga sem isso ou tente mais tarde"
        req = HelpRequest(uuid.uuid4().hex[:8], reason, link)
        future = asyncio.get_running_loop().create_future()
        self._pending[req.id] = future
        try:
            await self.notify(req)
            return await asyncio.wait_for(future, self.timeout_min * 60)
        except TimeoutError:
            return f"sem resposta em {self.timeout_min:g} minutos; siga sem isso e avise no final"
        finally:
            self._pending.pop(req.id, None)

    def answer(self, request_id: str, text: str) -> None:
        future = self._pending.get(request_id)
        if future and not future.done():
            future.set_result(text.strip() or "resolvido")

    def cancel_all(self, text: str = "o usuário saiu da conversa") -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_result(text)
