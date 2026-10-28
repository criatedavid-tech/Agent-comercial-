"""agente-gestao: o relatório de gestão no terminal, sem modelo e sem custo.

Uso:  agente-gestao [PERÍODO] [--inicio AAAA-MM-DD] [--fim AAAA-MM-DD] [--alertas]
Ex.:  agente-gestao "mês passado"     agente-gestao outubro --alertas
"""

import argparse
import sys

from . import config, gestao
from .crm import Crm


def main() -> None:
    parser = argparse.ArgumentParser(description="Relatório de gestão a partir das planilhas da loja")
    parser.add_argument("periodo", nargs="?", default="", help="ex. 'este mês', 'mês passado', 'outubro', 'últimos 30 dias'")
    parser.add_argument("--inicio", default="")
    parser.add_argument("--fim", default="")
    parser.add_argument("--alertas", action="store_true", help="mostra só os alertas")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # o terminal do Windows não é UTF-8 por padrão
    cfg = config.load()
    try:
        data = gestao.load_data(cfg.data_dir)
    except gestao.DataError as e:
        sys.exit(f"planilha com problema: {e}")
    period = gestao.period_from(args.periodo, args.inicio, args.fim, today=data.last_day())
    if cfg.data_dir == config.EXAMPLE_DATA:
        print("(dados fictícios de exemplo: coloque as planilhas da loja em dados/)\n")
    if args.alertas:
        findings = gestao.audit(data, period)
        print("\n".join(f.describe(max_evidence=20) for f in findings) or f"nenhum alerta em {period.label()}")
    else:
        print(gestao.report(data, period, Crm(cfg.crm_db)))


if __name__ == "__main__":
    main()
