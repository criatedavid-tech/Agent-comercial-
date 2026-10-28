"""Backup dos dados do agente: memória, base de conhecimento, agenda, conversas, CRM e empresa.

Os bancos SQLite são copiados com a API de backup do SQLite, que gera uma cópia consistente
mesmo com o agente rodando. Gera um .tar.gz por execução e mantém só os N mais recentes.

Uso:  agente-backup [--destino PASTA] [--manter 14] [--com-navegador]
Restaurar: pare o serviço, extraia o arquivo dentro da pasta do projeto e inicie de novo.
"""

import argparse
from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
import tarfile
import tempfile

from . import config
from .config import EXAMPLE_COMPANY, EXAMPLE_DATA, ROOT, Config

PREFIX = "agente-backup-"


def _copy_sqlite(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(src)) as source, closing(sqlite3.connect(dst)) as target:
        source.backup(target)


def sources(cfg: Config, with_browser: bool = False) -> list[Path]:
    """O que entra no backup. O .env fica de fora (chaves): guarde-o à parte, num cofre de senhas."""
    paths = [cfg.memory_dir, cfg.knowledge_dir, cfg.agenda_db, cfg.logs_dir / "conversas.db",
             cfg.crm_db, cfg.logs_dir / "atendimento.db"]
    if cfg.company_dir != EXAMPLE_COMPANY:
        paths.append(cfg.company_dir)  # catálogo e regras da empresa (a de exemplo já está no git)
    if cfg.data_dir != EXAMPLE_DATA:
        paths.append(cfg.data_dir)  # planilhas da loja
    if with_browser:
        paths.append(cfg.browser_profile)  # logins dos sites: só se o destino for seguro
    return [p for p in paths if p.exists()]


def create(cfg: Config, dest: Path, keep: int = 14, with_browser: bool = False, root: Path = ROOT,
           now: datetime | None = None) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    archive = dest / f"{PREFIX}{stamp}.tar.gz"
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(archive, "w:gz") as tar:
        for path in sources(cfg, with_browser):
            name = path.relative_to(root)
            if path.is_dir():
                for file in sorted(path.rglob("*")):
                    if file.is_file():
                        tar.add(_snapshot(file, Path(tmp), root), arcname=str(file.relative_to(root)))
            else:
                tar.add(_snapshot(path, Path(tmp), root), arcname=str(name))
    rotate(dest, keep)
    return archive


def _snapshot(file: Path, tmp: Path, root: Path) -> Path:
    """Banco SQLite vira uma cópia consistente; os outros arquivos vão como estão."""
    if file.suffix != ".db":
        return file
    copy = tmp / file.relative_to(root)
    _copy_sqlite(file, copy)
    return copy


def rotate(dest: Path, keep: int) -> list[Path]:
    """Apaga os backups mais antigos, mantendo os `keep` mais recentes. Devolve os apagados."""
    archives = sorted(dest.glob(f"{PREFIX}*.tar.gz"))
    old = archives[:-keep] if keep > 0 else []
    for path in old:
        path.unlink()
    return old


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup dos dados do agente")
    parser.add_argument("--destino", type=Path, default=ROOT / "backups")
    parser.add_argument("--manter", type=int, default=14, help="quantos backups guardar")
    parser.add_argument("--com-navegador", action="store_true", help="inclui os logins do navegador próprio")
    args = parser.parse_args()
    archive = create(config.load(), args.destino, args.manter, args.com_navegador)
    print(f"backup criado: {archive} ({archive.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
