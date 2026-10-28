"""Arquivos da VPS coerentes entre si e com o código (o teste de verdade roda num container Ubuntu)."""

import configparser
from pathlib import Path
import re
import shutil
import subprocess
import tomllib

import pytest

from agente import web
from agente.config import ROOT

DEPLOY = ROOT / "deploy"
SCRIPTS = ["provisionar.sh", "atualizar.sh"]


def unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # systemd diferencia maiúsculas
    parser.read(DEPLOY / name, encoding="utf-8")
    return parser


def console_scripts() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]


@pytest.mark.parametrize("name", SCRIPTS + ["agente.service", "Caddyfile"])
def test_files_use_lf(name):
    assert b"\r\n" not in (DEPLOY / name).read_bytes(), f"{name} tem CRLF: o Linux não roda"


@pytest.mark.parametrize("name", SCRIPTS)
def test_scripts_are_strict_and_parse(name):
    text = (DEPLOY / name).read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in text
    if shutil.which("bash"):
        assert subprocess.run(["bash", "-n", f"deploy/{name}"], cwd=ROOT).returncode == 0


def test_gitattributes_forces_lf_for_deploy():
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in text and "deploy/* text eol=lf" in text


def test_services_run_installed_commands():
    scripts = console_scripts()
    for name in ("agente.service", "agente-backup.service", "agente-vigia.service"):
        service = unit(name)["Service"]
        command = service["ExecStart"].split()[0]
        assert command.startswith("/opt/agente/.venv/bin/")
        assert Path(command).name in scripts, f"{name} chama {command}, que não está no pyproject"
        assert service["User"] == "agente" and service["NoNewPrivileges"] == "true"


def test_main_service_is_jailed():
    service = unit("agente.service")["Service"]
    assert service["Restart"] == "always"
    assert service["ProtectSystem"] == "strict" and service["ProtectHome"] == "true"
    read_only = service["ReadOnlyPaths"].split()
    for path in ("/opt/agente/agente", "/opt/agente/.env", "/opt/agente/.venv", "/opt/agente/plugin"):
        assert f"-{path}" in read_only, f"{path} deveria ser só leitura para o agente"


def test_timers_point_to_existing_services():
    for timer in ("agente-backup.timer", "agente-vigia.timer"):
        assert (DEPLOY / timer.replace(".timer", ".service")).exists()
        assert unit(timer)["Install"]["WantedBy"] == "timers.target"
    assert unit("agente-backup.timer")["Timer"]["Persistent"] == "true"


def test_caddy_exposes_only_the_webhook_and_the_remote_screen():
    text = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    proxied = re.findall(r"handle\s+(\S+)\s*\{\s*reverse_proxy", text)
    # a tela remota é pública, mas o servidor só a abre com link temporário válido (tests/test_sessoes.py)
    assert proxied == [web.WEBHOOK, f"{web.REMOTE}/*", f"/ws{web.REMOTE}/*"], "nada além disso pode ser público"
    assert 'respond "Not found" 404' in text
    assert "DOMINIO_AQUI" in text


def test_provisioning_installs_every_unit_and_keeps_ssh_safe():
    text = (DEPLOY / "provisionar.sh").read_text(encoding="utf-8")
    assert 'deploy/agente*.service "$APP_DIR"/deploy/agente*.timer' in text
    assert "AGENT_BROWSER_HEADLESS=true" in text  # VPS não tem tela
    assert "chmod 600" in text  # .env legível só pelo agente
    assert "AGENT_PUBLIC_URL=https://$DOMINIO" in text  # links da tela remota com o domínio da VM
    # só desliga senha no SSH se houver chave cadastrada
    assert text.index("TEM_CHAVE") < text.index("PasswordAuthentication no")
