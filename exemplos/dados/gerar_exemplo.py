"""Gera as planilhas fictícias do Auto Center Rota Certa (agosto a outubro de 2026).

Os dados são inventados e trazem problemas plantados em outubro, para os alertas de gestão terem
o que encontrar (e os testes conferirem que encontram):

- Diego tira peças do estoque sem OS ou com número de OS que não existe;
- Paulo dá desconto muito acima do resto da equipe;
- a conta de manutenção de equipamentos dispara, e uma nota do fornecedor de lubrificantes é paga duas vezes;
- o caixa da Juliana fecha faltando dinheiro em vários dias;
- sábado é o dia mais cheio e terça o mais vazio.

Rodar: python exemplos/dados/gerar_exemplo.py (reescreve os CSV desta pasta; sempre o mesmo resultado).
"""

import csv
from datetime import date, timedelta
from pathlib import Path
import random

HERE = Path(__file__).resolve().parent
START, END = date(2026, 8, 1), date(2026, 10, 28)
SELLERS = ["Rafael", "Juliana", "Paulo"]
MECHANICS = ["Bruno", "Diego"]
# item, tipo, preço, peças que o serviço consome no estoque (produto, quantidade, custo unitário)
ITEMS = [
    ("Troca de óleo com filtro", "servico", 189.90, [("Óleo 5W30 sintético 1L", 4, 28.00), ("Filtro de óleo", 1, 18.00)]),
    ("Alinhamento 3D", "servico", 89.90, []),
    ("Alinhamento + balanceamento", "servico", 149.90, [("Chumbo de balanceamento", 1, 6.00)]),
    ("Troca de pastilhas dianteiras", "servico", 249.90, [("Pastilha de freio dianteira", 1, 85.00)]),
    ("Higienização do ar-condicionado", "servico", 149.90, [("Espuma higienizadora", 1, 22.00)]),
    ("Diagnóstico com scanner", "servico", 120.00, []),
    ("Pneu 175/70 R14", "peca", 389.00, [("Pneu 175/70 R14", 1, 255.00)]),
    ("Pneu 185/65 R15", "peca", 429.00, [("Pneu 185/65 R15", 1, 290.00)]),
    ("Bateria 60 Ah", "peca", 499.00, [("Bateria 60 Ah", 1, 320.00)]),
]
WEIGHTS = [30, 14, 18, 10, 6, 6, 8, 6, 4]
ORDERS_PER_DAY = {0: 6, 1: 3, 2: 5, 3: 5, 4: 7, 5: 9}  # segunda..sábado; domingo fechado
PAYMENTS = ["pix", "credito", "debito", "dinheiro"]
FIXED = [("aluguel", "Aluguel do galpão", "Imobiliária Centro", 6500.00, 5), ("energia", "Conta de luz", "CPFL", 900.00, 12),
         ("agua", "Conta de água", "Sanasa", 180.00, 12), ("internet", "Internet", "Vivo", 150.00, 10),
         ("folha", "Salários", "Equipe", 14500.00, 5), ("sistema", "Sistema de gestão", "SoftOficina", 189.00, 15)]


def money(v: float) -> str:
    return f"{v:.2f}"


def main() -> None:
    rnd = random.Random(2026)
    sales, stock, expenses, cash = [], [], [], []
    order_no = 1000
    day = START
    while day <= END:
        october = day.month == 10
        if day.weekday() in ORDERS_PER_DAY:
            cash_registered = 0.0
            cashier = "Juliana" if day.weekday() in (0, 2, 4) else "Rafael"
            for _ in range(max(1, ORDERS_PER_DAY[day.weekday()] + rnd.randint(-1, 1))):
                order_no += 1
                os_id = f"OS-{order_no}"
                seller = rnd.choice(SELLERS)
                mechanic = rnd.choice(MECHANICS)
                payment = rnd.choice(PAYMENTS)
                status = "cancelada" if rnd.random() < 0.02 else "fechada"
                chosen = rnd.choices(range(len(ITEMS)), WEIGHTS, k=rnd.choice([1, 1, 2, 2, 3]))
                for idx in sorted(set(chosen)):
                    name, kind, price, parts = ITEMS[idx]
                    qty = 4 if name.startswith("Pneu") and rnd.random() < 0.5 else (2 if name.startswith("Pneu") else 1)
                    gross = price * qty
                    rate = rnd.choice([0, 0, 0, 0.03, 0.05])
                    if seller == "Paulo" and october:
                        rate = rnd.choice([0.10, 0.15, 0.20])  # plantado: desconto alto
                    discount = round(gross * rate, 2)
                    total = round(gross - discount, 2)
                    sales.append([day.isoformat(), os_id, f"Cliente {order_no}", item_vehicle(rnd), name, kind, qty,
                                  money(price), money(discount), money(total), payment, seller, status])
                    if status == "fechada" and payment == "dinheiro":
                        cash_registered += total
                    if status == "fechada":
                        for product, pqty, cost in parts:
                            stock.append([day.isoformat(), product, "saida", pqty * qty, money(cost), os_id, mechanic, ""])
            if cash_registered:
                counted = cash_registered
                if cashier == "Juliana" and october and rnd.random() < 0.6:
                    counted -= rnd.choice([60, 80, 100, 120])  # plantado: caixa faltando
                elif rnd.random() < 0.1:
                    counted += rnd.choice([-5, 5, -10])
                cash.append([day.isoformat(), cashier, money(cash_registered), money(counted)])
            if october and day.weekday() in (1, 3) and day.day % 3 != 0:
                # plantado: Diego tira peças sem OS ou com OS que não existe
                product, pqty, cost = rnd.choice([("Pastilha de freio dianteira", 1, 85.00), ("Óleo 5W30 sintético 1L", 4, 28.00),
                                                  ("Bateria 60 Ah", 1, 320.00)])
                fake_os = "" if rnd.random() < 0.5 else f"OS-{rnd.randint(9000, 9999)}"
                stock.append([day.isoformat(), product, "saida", pqty, money(cost), fake_os, "Diego", ""])
        for category, description, supplier, value, dom in FIXED:
            if day.day == dom:
                expenses.append([day.isoformat(), category, description, supplier, money(value * rnd.uniform(0.95, 1.05) if category in ("energia", "agua") else value)])
        if day.day in (3, 17):
            expenses.append([day.isoformat(), "pecas", "Compra de peças e pneus", "Distribuidora AutoPeças", money(rnd.uniform(5200, 6800))])
        if day.day == 10:
            expenses.append([day.isoformat(), "lubrificantes", "Óleo e filtros", "Distribuidora Lub", money(1480.00)])
        if day.day == 20:
            expenses.append([day.isoformat(), "manutencao_equipamentos", "Manutenção do elevador e compressor", "TecEquip",
                             money(3200.00 if october else rnd.uniform(450, 700))])  # plantado: disparou em outubro
        if october and day.day == 13:
            expenses.append([day.isoformat(), "lubrificantes", "Óleo e filtros", "Distribuidora Lub", money(1480.00)])  # plantado: duplicada
        day += timedelta(days=1)

    write("vendas.csv", ["data", "os", "cliente", "veiculo", "item", "tipo", "quantidade", "valor_unitario", "desconto",
                         "total", "pagamento", "funcionario", "status"], sales)
    write("estoque.csv", ["data", "produto", "tipo", "quantidade", "custo_unitario", "os", "funcionario", "motivo"], stock)
    write("despesas.csv", ["data", "categoria", "descricao", "fornecedor", "valor"], expenses)
    write("caixa.csv", ["data", "funcionario", "registrado", "contado"], cash)


def item_vehicle(rnd: random.Random) -> str:
    return rnd.choice(["Onix 2019", "HB20 2018", "Gol 2015", "Corolla 2020", "Argo 2021", "Ka 2017", "Civic 2016"])


def write(name: str, header: list[str], rows: list[list]) -> None:
    with (HERE / name).open("w", encoding="utf-8", newline="") as f:
        out = csv.writer(f)
        out.writerow(header)
        out.writerows(rows)


if __name__ == "__main__":
    main()
