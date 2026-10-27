"""Chat com o agente pelo terminal."""

import asyncio

from rich.console import Console
from rich.markdown import Markdown

from . import config
from .core import Agent
from .human import HelpRequest

console = Console()


async def run() -> None:
    agent = Agent(config.load())

    async def ask_human(req: HelpRequest) -> None:
        # No terminal o agente está parado esperando; a resposta vem direto do teclado.
        console.print(f"\n[bold yellow]⚠ O agente precisa de você:[/bold yellow] {req.reason}")
        if req.link:
            console.print(f"[yellow]{req.link}[/yellow]")
        text = await asyncio.to_thread(
            console.input, "[yellow]Enter quando resolver (ou escreva um código, escolha ou 'não consegui') › [/yellow]"
        )
        agent.human.answer(req.id, text)

    agent.human.notify = ask_human
    await agent.start()
    console.print(
        "[bold]Agente pessoal[/bold] · [cyan]sair[/cyan] encerra · [cyan]/nova[/cyan] recomeça · "
        "[cyan]/conversas[/cyan] lista · [cyan]/retomar N[/cyan] volta a uma conversa · "
        "[cyan]/desfazer[/cyan] volta os arquivos do último pedido\n"
    )
    checkpoint: str | None = None  # último pedido, para /desfazer
    # O terminal não roda a agenda (quem roda é o agente-web), mas mostra o que ela entregou.
    unread = agent.agenda.unread()
    for item in unread:
        console.print(f"[bold cyan]⏰ {item.title}[/bold cyan] [dim]{item.created:%d/%m %H:%M}[/dim]")
        console.print(Markdown(item.text))
        console.print()
    agent.agenda.mark_read([i.id for i in unread])
    try:
        while True:
            text = (await asyncio.to_thread(console.input, "[bold green]você › [/bold green]")).strip()
            if not text:
                continue
            if text.lower() in ("sair", "exit", "quit"):
                break
            if text == "/nova":
                await agent.reset()
                console.print("[dim]conversa nova[/dim]\n")
                checkpoint = None
                continue
            if text == "/conversas":
                for i, s in enumerate(agent.history.sessions(limit=15), 1):
                    console.print(f"[cyan]{i:>2}[/cyan] {s.title} [dim]{s.updated[:16].replace('T', ' ')} · "
                                  f"{s.requests} pedido(s) · US$ {s.cost_usd:.4f}[/dim]")
                console.print()
                continue
            if text.startswith("/retomar"):
                sessions = agent.history.sessions(limit=15)
                arg = text.removeprefix("/retomar").strip()
                if not arg.isdigit() or not 1 <= int(arg) <= len(sessions):
                    console.print("[dim]use /conversas e depois /retomar N[/dim]\n")
                    continue
                chosen = sessions[int(arg) - 1]
                resumed = await agent.resume(chosen.id)
                checkpoint = None
                if resumed:
                    console.print(f"[dim]conversa retomada: {chosen.title}[/dim]\n")
                else:
                    console.print("[dim]não deu para retomar o contexto (o registro não existe mais); conversa nova[/dim]\n")
                continue
            if text == "/desfazer":
                if not checkpoint:
                    console.print("[dim]nada para desfazer nesta conversa[/dim]\n")
                    continue
                await agent.rewind(checkpoint)
                checkpoint = None
                console.print("[dim]arquivos voltaram ao estado de antes do último pedido[/dim]\n")
                continue
            async for event in agent.ask(text):
                if event.kind == "checkpoint":
                    checkpoint = event.text
                elif event.kind == "text":
                    console.print(Markdown(event.text))
                elif event.kind == "blocked":
                    console.print(f"[red]🛡 bloqueado: {event.text}[/red]")
                elif event.kind == "tool":
                    console.print(f"[dim]⚙ {event.text}[/dim]")
                else:
                    console.print(f"[dim]{event.text}[/dim]\n")
    finally:
        await agent.stop()
        await agent.browser.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
