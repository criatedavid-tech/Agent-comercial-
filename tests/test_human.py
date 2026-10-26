"""Ponte humana: avisa a interface, espera a resposta e respeita o tempo limite."""

import asyncio

from agente.human import HumanBridge


def run(coro):
    return asyncio.run(coro)


def test_without_interface_returns_immediately():
    assert "nenhuma pessoa conectada" in run(HumanBridge(1).request("x"))


def test_returns_user_answer():
    async def scenario():
        bridge = HumanBridge(1)
        seen = []

        async def notify(req):
            seen.append(req)
            asyncio.get_running_loop().call_later(0.01, bridge.answer, req.id, " 123456 ")

        bridge.notify = notify
        answer = await bridge.request("código 2FA", "https://site")
        return answer, seen

    answer, seen = run(scenario())
    assert answer == "123456"
    assert seen[0].reason == "código 2FA" and seen[0].link == "https://site"


def test_empty_answer_means_resolved():
    async def scenario():
        bridge = HumanBridge(1)

        async def notify(req):
            asyncio.get_running_loop().call_later(0.01, bridge.answer, req.id, "")

        bridge.notify = notify
        return await bridge.request("captcha")

    assert run(scenario()) == "resolvido"


def test_timeout():
    async def scenario():
        bridge = HumanBridge(0.001)  # 60 ms

        async def notify(req):
            pass

        bridge.notify = notify
        return await bridge.request("x"), bridge._pending

    answer, pending = run(scenario())
    assert answer.startswith("sem resposta")
    assert pending == {}


def test_cancel_all_releases_waiting_requests():
    async def scenario():
        bridge = HumanBridge(1)

        async def notify(req):
            asyncio.get_running_loop().call_later(0.01, bridge.cancel_all)

        bridge.notify = notify
        return await bridge.request("x")

    assert run(scenario()) == "o usuário saiu da conversa"


def test_unknown_id_is_ignored():
    HumanBridge(1).answer("nao-existe", "ok")
