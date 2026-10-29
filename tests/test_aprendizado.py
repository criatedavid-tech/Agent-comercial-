"""Aprendizado dos sistemas: o agente navega uma vez num "ERP" falso, grava a rotina e o código repete sozinho."""

import asyncio
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

from agente import aprendizado
from agente.aprendizado import LearningError, SystemMemory, host_of, parse_params, parse_range, steps_from_journal
from agente.browser import Browser, BrowserError
from agente.core import browser_tools

PAGES = {
    "index.html": """<html><head><meta charset="utf-8"><title>ERP Teste</title></head><body>
        <nav><a href="clientes.html">Clientes</a> <a href="relatorios.html">Relatórios</a></nav><p>Bem-vindo, Loja Centro</p></body></html>""",
    "clientes.html": """<html><head><meta charset="utf-8"><title>Clientes</title></head><body><p>Lista de clientes</p></body></html>""",
    "relatorios.html": """<html><head><meta charset="utf-8"><title>Relatórios</title></head><body>
        <form action="resultado.html"><label for="data">Data inicial</label><input id="data" name="data">
        <button type="submit">Gerar relatório</button></form></body></html>""",
    "resultado.html": """<html><head><meta charset="utf-8"><title>Resultado</title></head><body><p id="r"></p>
        <script>document.getElementById('r').innerText = 'Vendas de ' +
          new URLSearchParams(location.search).get('data') + ': R$ 1.079,70';</script></body></html>""",
}


@pytest.fixture(scope="module")
def erp(tmp_path_factory):
    root = tmp_path_factory.mktemp("erp")
    for name, html in PAGES.items():
        (root / name).write_text(html, encoding="utf-8")
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def run_with_browser(tmp_path, scenario):
    async def main():
        browser = Browser(tmp_path / "perfil", tmp_path / "capturas", headless=True, allow_private=True)
        try:
            return await scenario(browser)
        finally:
            await browser.close()

    try:
        return asyncio.run(main())
    except BrowserError as e:
        if "não consegui abrir o navegador" in str(e) or "Playwright não está instalado" in str(e):
            pytest.skip(f"Chromium indisponível: {e}")
        raise


def text(reply):
    return reply["content"][0]["text"]


# --- funções puras ---------------------------------------------------------------------------

def test_params_ranges_and_hosts():
    assert parse_params("data=01/10/2026; Loja=Centro") == {"data": "01/10/2026", "loja": "Centro"}
    assert parse_params('{"pedido": 123}') == {"pedido": "123"}
    assert parse_range("3-9", 10) == (3, 9) and parse_range("", 4) == (1, 4) and parse_range("2", 5) == (2, 5)
    with pytest.raises(LearningError):
        parse_range("9-3", 10)
    assert host_of("https://www.portal.ifood.com.br/vendas") == "portal.ifood.com.br"


def test_example_values_become_parameters():
    journal = [{"action": "open", "url": "https://erp.com/rel?ini=01/10/2026"},
               {"action": "fill", "url": "x", "label": "Data", "value": "01/10/2026", "submit": True}]
    steps = steps_from_journal(journal, {"data": "01/10/2026"})
    assert steps[0]["url"] == "https://erp.com/rel?ini={data}" and steps[1]["value"] == "{data}"
    assert aprendizado.fill_in(steps[1], {"data": "29/10/2026"})["value"] == "29/10/2026"
    with pytest.raises(LearningError, match="falta o parâmetro data"):
        aprendizado.fill_in(steps[1], {})


def test_memory_keeps_notes_and_routines(tmp_path):
    mem = SystemMemory(tmp_path / "sistemas.db")
    mem.note("erp.com", "relatórios ficam no menu do topo")
    mem.save("erp.com", "Vendas do Dia", "vendas de uma data", [{"action": "open", "url": "https://erp.com"}], ["data"])
    r = mem.routine("vendas do dia")
    mem.mark(r, True)
    text = mem.describe("erp.com")
    assert "relatórios ficam no menu do topo" in text and "vendas do dia (parâmetros: data)" in text
    assert "deu certo 1x" in text and mem.describe("outro.com") == ""
    with pytest.raises(LearningError, match="não conheço"):
        mem.routine("estoque")


# --- de ponta a ponta, com navegador real ----------------------------------------------------------

def test_learn_once_then_replay_with_another_date(cfg, tmp_path, erp):
    async def scenario(browser: Browser):
        tools = {t.name: t for t in browser_tools(browser, cfg)}

        async def call(name, args):
            return await tools[name].handler(args)

        # 1ª vez: o agente navega e acha o caminho
        await call("abrir_pagina", {"url": f"{erp}/index.html"})
        await browser.click(await browser.find_ref("Relatórios"))
        await browser.fill(await browser.find_ref("Data inicial"), "01/10/2026")
        await browser.click(await browser.find_ref("Gerar relatório"))
        steps = text(await call("ver_passos", {}))
        saved = text(await call("salvar_rotina", {"nome": "Vendas do dia", "descricao": "vendas de uma data no ERP",
                                                    "parametros": "data=01/10/2026"}))
        # da próxima vez: abrir o ERP já mostra o que foi aprendido, e a rotina vai direto ao resultado
        await browser.open(f"{erp}/clientes.html")
        reopened = text(await call("abrir_pagina", {"url": f"{erp}/index.html"}))
        replayed = await call("executar_rotina", {"nome": "vendas do dia", "parametros": "data=29/10/2026"})
        missing = await call("executar_rotina", {"nome": "vendas do dia"})
        return steps, saved, reopened, text(replayed), text(missing)

    steps, saved, reopened, replayed, missing = run_with_browser(tmp_path, scenario)
    assert "clicar em \"Relatórios\"" in steps and "preencher \"Data inicial\" com \"01/10/2026\"" in steps
    assert "rotina gravada em 127.0.0.1" in saved and "{data}" in saved and "4 passos" in saved
    assert "📘 Já conheço 127.0.0.1" in reopened and "vendas do dia (parâmetros: data)" in reopened
    assert "concluída" in replayed and "Vendas de 29/10/2026: R$ 1.079,70" in replayed
    assert "faltam os parâmetros: data" in missing


def test_replay_stops_where_the_site_changed(cfg, tmp_path, erp):
    async def scenario(browser: Browser):
        tools = {t.name: t for t in browser_tools(browser, cfg)}
        mem = SystemMemory(cfg.knowledge_dir / "sistemas.db")
        mem.save("127.0.0.1", "estoque", "estoque atual",
                 [{"action": "open", "url": f"{erp}/index.html"}, {"action": "click", "url": "", "label": "Estoque"}], [])
        out = await tools["executar_rotina"].handler({"nome": "estoque"})
        return text(out), mem.routine("estoque")

    out, routine = run_with_browser(tmp_path, scenario)
    assert "parou no passo 2 de 2" in out and "clicar em \"Estoque\"" in out and "grave a rotina de novo" in out
    assert routine.fail == 1


def test_replay_keeps_the_purchase_lock(cfg, tmp_path):
    """Rotina não fura a trava: um passo "clicar em Finalizar pedido" é recusado como no uso normal."""
    async def scenario(browser: Browser):
        page = tmp_path / "loja.html"
        page.write_text('<meta charset="utf-8"><button>Finalizar pedido</button>', encoding="utf-8")
        routine = aprendizado.Routine("loja", "comprar", "x", [
            {"action": "open", "url": page.as_uri()}, {"action": "click", "url": "", "label": "Finalizar pedido"}], [])

        class Opener:  # file:// não passa no check_url; abre direto e usa o clique de verdade
            async def open(self, url):
                pg = await browser._get_page()
                await pg.goto(url)
                return "Página: loja"

            def __getattr__(self, name):
                return getattr(browser, name)

        return await aprendizado.replay(Opener(), routine, {})

    ok, out = run_with_browser(tmp_path, scenario)
    assert not ok and "parou no passo 2" in out and "quem clica é o usuário" in out
