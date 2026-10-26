"""Hooks de segurança: regras no código que barram ações perigosas antes de executar.

O agente roda com autonomia total (bypassPermissions); estes hooks são a trava.
São uma proteção contra erros e prompt injection, não uma sandbox: um comando
criativo ainda pode escapar. Por isso a VPS deve rodar com usuário sem root.
"""

from collections.abc import Callable
from pathlib import Path
import re
from typing import Any

from claude_agent_sdk import HookMatcher

from .config import Config

# Comandos de terminal que nunca devem rodar, com o motivo que o agente recebe.
BLOCKED_COMMANDS = [
    (r"\brm\s+(-\w*\s+)*-\w*[rf]\w*\s+(-\w+\s+)*(/|~|\$HOME|/\*|[a-z]:[\\/]?)(\s|$|\*)", "apagar a raiz ou a pasta do usuário"),
    (r"(?i)\b(remove-item|rd|rmdir|del)\b.*\s(-recurse|/s)\b.*\s[a-z]:[\\/]?(\s|$|\*)", "apagar um disco inteiro"),
    (r"(?i)\b(mkfs|format(\.com)?\s+[a-z]:|diskpart)\b", "formatar disco"),
    (r"\bdd\s+.*\bof=/dev/", "escrever direto num disco"),
    (r"(?i)\b(shutdown|reboot|halt|poweroff|stop-computer|restart-computer)\b", "desligar ou reiniciar a máquina"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "fork bomb"),
    (r"(?i)\b(curl|wget|iwr|invoke-webrequest)\b[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b|\biex\b.*\b(iwr|irm|invoke-webrequest|invoke-restmethod)\b", "baixar e executar script da internet"),
    (r"\bchmod\s+(-R\s+)?[0-7]*777\s+/(\s|$)", "liberar permissão total na raiz"),
    (r"\bgit\s+push\b.*(--force|-f)\b", "push forçado no git"),
    (r"(?i)\b(useradd|usermod|passwd|net\s+user|reg\s+(add|delete)|set-itemproperty\s+.*hk(lm|cu))\b", "mexer em usuários ou no registro do sistema"),
    (r"(?i)\bcrontab\s+-r\b", "apagar tarefas agendadas"),
]

# Arquivos que o agente nunca lê nem altera, por nenhum caminho.
SECRET_FILES = re.compile(r"(?i)(^|[\\/\s\"'=])(\.env|id_rsa|id_ed25519|\.ssh|\.aws[\\/]credentials|\.git-credentials|\.netrc)([\\/\s\"']|$)")

DENY_PREFIX = "Bloqueado pela segurança do agente"

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def check(tool: str, args: dict[str, Any], cfg: Config) -> str | None:
    """Devolve o motivo do bloqueio, ou None se a ação pode seguir."""
    if tool == "Bash":
        command = str(args.get("command", ""))
        for pattern, reason in BLOCKED_COMMANDS:
            if re.search(pattern, command):
                return f"comando bloqueado ({reason})"
        if SECRET_FILES.search(command):
            return "comando bloqueado (toca em arquivo de credenciais, como .env ou chaves SSH)"
        return None

    path = args.get("file_path") or args.get("notebook_path") or args.get("path")
    if not path:
        return None
    if SECRET_FILES.search(str(path)):
        return "arquivo de credenciais (.env, chaves SSH etc.) é proibido"
    if tool in WRITE_TOOLS:
        target = _resolve(path, cfg)
        allowed = (cfg.workdir, cfg.memory_dir, cfg.knowledge_dir)
        if not any(target.is_relative_to(d.resolve()) for d in allowed):
            names = ", ".join(f"{d.name}/" for d in allowed)
            return f"só posso criar ou editar arquivos nas pastas {names}; {target} está fora"
    return None


def _resolve(path: str, cfg: Config) -> Path:
    p = Path(path).expanduser()
    return (p if p.is_absolute() else cfg.workdir / p).resolve()


def hooks(cfg: Config, log: Callable[[dict], None]) -> dict:
    """Hooks para o ClaudeAgentOptions: valem para o agente principal e os subagentes."""

    async def before_tool(data: dict, tool_use_id: str | None, context: Any) -> dict:
        reason = check(data["tool_name"], data.get("tool_input", {}), cfg)
        if not reason:
            return {}
        log({"type": "blocked", "tool": data["tool_name"], "input": data.get("tool_input"), "reason": reason})
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"{DENY_PREFIX}: {reason}. "
                "Não tente contornar; se for mesmo necessário, explique ao usuário e peça que ele faça.",
            }
        }

    return {"PreToolUse": [HookMatcher(matcher=None, hooks=[before_tool])]}

