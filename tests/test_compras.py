"""Trava de compra e fluxo de carrinho numa loja falsa que imita a Amazon (Chromium de verdade, invisível)."""

import asyncio
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading

import pytest

from agente.browser import Browser, BrowserError, is_purchase_button

LOJA = Path(__file__).parent / "loja_falsa"


@pytest.mark.parametrize("text, element_id", [
    ("Finalizar pedido", ""), ("Confirmar compra", ""), ("Comprar agora", ""), ("Pagar", ""),
    ("  finalizar   a compra ", ""), ("Comprar com 1-Clique", ""), ("Place your order", ""), ("Assine agora", ""),
    ("", "buy-now-button"), ("Continuar", "placeYourOrder1"), ("x", "submitOrderButtonId"),
])
def test_detects_purchase_buttons(text, element_id):
    assert is_purchase_button(text, element_id)


@pytest.mark.parametrize("text", [
    "Fechar pedido", "Adicionar ao carrinho", "Ver carrinho", "Comprar outros itens", "Pagamento e envio",
    "Excluir", "Salvar para mais tarde", "Continuar comprando", "Política de pagamento",
])
def test_lets_normal_buttons_through(text):
    assert not is_purchase_button(text)


@pytest.fixture(scope="module")
def loja():
    handler = partial(SimpleHTTPRequestHandler, directory=str(LOJA))
    handler.log_message = lambda *a: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def run(tmp_path):
    def go(scenario):
        async def main():
            b = Browser(tmp_path / "perfil", tmp_path / "capturas", headless=True, allow_private=True)
            try:
                return await scenario(b)
            finally:
                await b.close()

        try:
            return asyncio.run(main())
        except BrowserError as e:
            if "não consegui abrir o navegador" in str(e) or "Playwright não está instalado" in str(e):
                pytest.skip(f"Chromium indisponível: {e}")
            raise

    return go


async def add_to_cart(b):
    """Adiciona o controle (botão principal) e vai para o carrinho, ignorando as recomendações."""
    await b.click(ref(await b.elements("DualSense"), "Adicionar ao carrinho"))
    await b.click(ref(await b.elements("Ir para o carrinho"), "Ir para o carrinho"))


def ref(listing: str, text: str) -> str:
    line = next(l for l in listing.splitlines() if text in l)
    return re.match(r"\[(\d+)\]", line).group(1)


def test_buttons_come_before_hundreds_of_menu_links(loja, run):
    async def scenario(b):
        await b.open(f"{loja}/produto.html")
        return await b.elements(), await b.elements("carrinho")

    everything, filtered = run(scenario)
    assert "Adicionar ao carrinho" in everything  # antes ficava além do limite, depois dos 250 links do menu
    assert "use o filtro" in everything
    assert filtered.count("\n") <= 2 and "Adicionar ao carrinho" in filtered


def test_buy_now_is_refused_and_add_to_cart_works_under_overlay(loja, run):
    async def scenario(b):
        await b.open(f"{loja}/produto.html")
        listing = await b.elements("comprar")
        with pytest.raises(BrowserError, match="quem clica é o usuário"):
            await b.click(ref(listing, "Comprar agora"))
        listing = await b.elements("carrinho")
        return await b.click(ref(listing, "Adicionar ao carrinho"))  # há uma barra fixa por cima do botão

    page = run(scenario)
    assert page.startswith("Cliquei em [") and "Adicionado ao carrinho" in page


def test_full_cart_flow_only_requested_item_and_final_click_refused(loja, run):
    async def scenario(b):
        await b.open(f"{loja}/produto.html")
        await add_to_cart(b)
        cart = await b.elements()
        # o carrinho já tinha itens do usuário: todos marcados, cada caixinha com o item a que pertence
        assert cart.count("☑ marcado") == 3
        for other in ("Headset Gamer", "Odisseia"):
            line = next(l for l in cart.splitlines() if "checkbox" in l and other in l)
            await b.click(re.match(r"\[(\d+)\]", line).group(1))
            cart = await b.elements()
        subtotal = await b.read("#subtotal")
        await b.click(ref(cart, "Fechar pedido"))  # leva à oferta do Prime e depois à revisão: permitido
        offer = await b.elements()
        with pytest.raises(BrowserError, match="quem clica é o usuário"):
            await b.click(ref(offer, "Assine o Amazon Prime"))  # assinatura no caminho: bloqueada
        review = await b.click(ref(offer, "Não, obrigado"))
        with pytest.raises(BrowserError, match="fecha uma compra"):
            await b.click(ref(await b.elements(), "Finalizar pedido"))
        status = await b.read("#status")
        return cart, subtotal, review, status

    cart, subtotal, review, status = run(scenario)
    assert cart.count("☑ marcado") == 1 and cart.count("☐ desmarcado") == 2
    assert "R$ 376,20" in subtotal and "(1 produtos)" in subtotal
    assert "Controle DualSense Branco" in review and "Headset" not in review and "Odisseia" not in review
    assert "PEDIDO FINALIZADO" not in status  # a trava impediu o clique final


def test_hidden_amazon_style_checkboxes_are_listed_with_their_item(loja, run):
    """Visto na Amazon real: a caixinha de verdade é transparente; sem isto, as 32 sumiam da lista."""
    async def scenario(b):
        await b.open(f"{loja}/produto.html")
        await add_to_cart(b)
        return await b.elements("Headset")

    listing = run(scenario)
    assert "input[checkbox]" in listing and "☑ marcado" in listing and "Headset Gamer" in listing


@pytest.mark.parametrize("text", [
    "Assine o Amazon Prime", "Experimente grátis por 30 dias", "Iniciar teste gratuito",
    "Obter frete GRÁTIS com o Prime", "Obter Prime", "Inscreva-se no Prime e economize", "Experimente o Prime grátis",
    "Programe e Poupe", "Programe e Poupe: economize 10%", "Assine e economize", "Subscribe & Save",
    "Assine o Kindle Unlimited", "Assinar Amazon Music Unlimited",
])
def test_subscription_offers_are_blocked(text):
    assert is_purchase_button(text)


@pytest.mark.parametrize("text", ["Não, obrigado(a)", "Voltar ao início", "Assinatura e pagamentos", "Compra única",
                                  "Adicionar ao carrinho", "Fechar pedido"])
def test_declining_offers_is_allowed(text):
    assert not is_purchase_button(text)


def test_enter_in_checkout_form_is_refused(run, loja):
    checkout = ('<meta charset="utf-8"><form><input id="cupom" placeholder="Cupom">'
                '<button>Finalizar pedido</button></form>')

    async def scenario(b):
        await b.open(f"{loja}/produto.html")
        await b._page.set_content(checkout)  # Enter num campo de cupom enviaria o formulário do pedido
        with pytest.raises(BrowserError, match="formulário de compra"):
            await b.fill(ref(await b.elements(), "Cupom"), "PROMO10", submit=True)
        return True

    assert run(scenario)


def test_buy_now_refusal_explains_the_cart_route(loja, run):
    async def scenario(b):
        await b.open(f"{loja}/produto.html")
        with pytest.raises(BrowserError) as err:
            await b.click(ref(await b.elements("comprar"), "Comprar agora"))
        return str(err.value)

    message = run(scenario)
    assert "Adicionar ao carrinho" in message and "desmarque" in message and "pedir_ajuda_humana" in message



def test_add_buttons_show_which_product_they_belong_to(loja, run):
    """Visto na Amazon real: os "Adicionar ao carrinho" das recomendações tinham o mesmo nome do principal,
    e o agente pôs um PS5 de R$ 3.783 e uma base no carrinho sem ninguém pedir."""
    async def scenario(b):
        await b.open(f"{loja}/produto.html")
        before = await b.elements("carrinho")
        clicked = await b.click(ref(before, "Adicionar ao carrinho"))
        after = await b.elements("Adicionar ao carrinho")
        return before, clicked, after

    before, clicked, after = run(scenario)
    assert "produto da página: Controle sem fio DualSense - Branco" in before
    assert clicked.startswith("Cliquei em [") and "Adicionar ao carrinho" in clicked
    lines = [l for l in after.splitlines() if "Adicionar ao carrinho" in l]
    assert len(lines) == 2  # as duas recomendações, cada uma com o seu produto
    assert any("PlayStation 5 Slim" in l for l in lines) and any("Base De Carregamento" in l for l in lines)


def test_click_reports_checkbox_change(loja, run):
    async def scenario(b):
        await b.open(f"{loja}/produto.html")
        await add_to_cart(b)
        listing = await b.elements("Headset")
        line = next(l for l in listing.splitlines() if "checkbox" in l)
        return await b.click(re.match(r"\[(\d+)\]", line).group(1))

    assert "(caixinha: marcada → desmarcada)" in run(scenario)


# --- regra expressa de não assinatura (visto na Amazon real: o agente assinou o Prime) ----------------------


async def go_to_offer(b, loja):
    await b.open(f"{loja}/produto.html")
    await add_to_cart(b)
    cart = await b.elements()
    await b.click(ref(cart, "Fechar pedido"))
    return await b.elements()


def test_offer_page_shows_real_button_names_and_warning(loja, run):
    """Na Amazon o botão é um input sem texto; o nome fica em outro elemento (aria-labelledby)."""
    listing = run(lambda b: go_to_offer(b, loja))
    assert listing.startswith("⚠ PÁGINA DE OFERTA DE ASSINATURA")
    assert "input[submit] Assine o Amazon Prime" in listing and "input[submit] Não, obrigado(a)" in listing


def test_offer_page_only_allows_declining(loja, run):
    async def scenario(b):
        offer = await go_to_offer(b, loja)
        errors = []
        for name in ("Assine o Amazon Prime", "Continuar"):
            try:
                await b.click(ref(offer, name))
            except BrowserError as e:
                errors.append(str(e))
        review = await b.click(ref(offer, "Não, obrigado"))
        subscribed = await b._page.evaluate("() => localStorage.getItem('assinou_prime')")
        return errors, review, subscribed

    errors, review, subscribed = run(scenario)
    assert len(errors) == 2  # assinar e "Continuar" (que também assinaria): os dois bloqueados
    assert "quem clica é o usuário" in errors[0] and "só é permitido recusar" in errors[1]
    assert "Revise seu pedido" in review and subscribed is None


def test_unnamed_button_is_never_clicked(run, loja):
    async def scenario(b):
        await b.open(f"{loja}/produto.html")
        await b._page.set_content('<meta charset="utf-8"><form><input type="submit" style="width:80px;height:30px"></form>')
        with pytest.raises(BrowserError, match="não consegui identificar"):
            await b.click(ref(await b.elements(), "input[submit]"))
        return True

    assert run(scenario)


def test_product_page_mentioning_prime_is_not_an_offer_page():
    from agente.browser import is_subscription_offer

    product = "Controle DualSense R$ 376,20 Entrega GRÁTIS Prime Adicionar ao carrinho Experimente o Prime"
    assert not is_subscription_offer(product)


def test_button_context_never_borrows_a_neighbor_button_name(loja, run):
    listing = run(lambda b: go_to_offer(b, loja))
    subscribe = next(l for l in listing.splitlines() if "Assine o Amazon Prime" in l)
    assert "Não, obrigado" not in subscribe
