"""Chat com o agente pelo terminal."""

import asyncio

from rich.console import Console
from rich.markdown import Markdown

from . import config
from .core import Agent

console = Console()


async def run() -> None:
    agent = Agent(config.load())
    await agent.start()
    console.print("[bold]Agente pessoal[/bold] · digite [cyan]sair[/cyan] para encerrar, [cyan]/nova[/cyan] para recomeçar\n")
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
                continue
            async for event in agent.ask(text):
                if event.kind == "text":
                    console.print(Markdown(event.text))
                elif event.kind == "tool":
                    console.print(f"[dim]⚙ {event.text}[/dim]")
                else:
                    console.print(f"[dim]{event.text}[/dim]\n")
    finally:
        await agent.stop()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
