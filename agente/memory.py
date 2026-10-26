"""Memória de longo prazo: arquivos Markdown em memory/."""

from pathlib import Path


def load(memory_dir: Path) -> str:
    """Junta todos os arquivos de memória num bloco de texto para o system prompt."""
    parts = []
    for path in sorted(memory_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if content:
            parts.append(f"<arquivo nome=\"{path.name}\">\n{content}\n</arquivo>")
    return "\n\n".join(parts)
