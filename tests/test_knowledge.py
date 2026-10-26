"""Base de conhecimento: salvar por área, buscar, bloquear segredos e reindexar."""

import pytest

from agente.knowledge import AREAS, KnowledgeBase, find_secret, slugify


@pytest.fixture
def kb(tmp_path) -> KnowledgeBase:
    return KnowledgeBase(tmp_path / "conhecimento")


def titles(hits):
    return [h.title for h in hits]


def test_creates_one_folder_per_area(kb):
    assert all((kb.root / area).is_dir() for area in AREAS)


def test_save_writes_markdown_with_header(kb):
    path = kb.save("financas", "Gastos fixos", "Aluguel 1500.", tags="mensal", source="extrato")
    text = path.read_text(encoding="utf-8")
    assert path.parent == kb.root / "financas"
    assert text.startswith("---\ntitulo: Gastos fixos\n")
    assert "area: financas" in text and "tags: mensal" in text and "fonte: extrato" in text
    assert text.rstrip().endswith("Aluguel 1500.")


def test_studies_go_to_niche_folder(kb):
    path = kb.save("estudos", "Decorators", "Função que embrulha outra.", nicho="Python Avançado")
    assert path.parent == kb.root / "estudos" / "python-avancado"
    no_niche = kb.save("estudos", "Algo", "Sem nicho.")
    assert no_niche.parent.name == "outros"


def test_same_title_same_day_does_not_overwrite(kb):
    first = kb.save("geral", "Nota", "um")
    second = kb.save("geral", "Nota", "dois")
    assert first != second and first.exists() and second.exists()


def test_invalid_area_is_refused(kb):
    with pytest.raises(ValueError, match="área inválida"):
        kb.save("trabalho", "x", "y")


@pytest.mark.parametrize("text", ["meu cpf 123.456.789-09", "cartão 4111 1111 1111 1111", "senha: abc123", "api_key=sk-123"])
def test_secrets_are_refused(kb, text):
    with pytest.raises(ValueError, match="não salvei"):
        kb.save("geral", "x", text)


def test_numbers_that_are_not_cards_pass():
    assert find_secret("ligar 11 98765-4321, pedido 20261026") is None
    assert find_secret("4111 1111 1111 1112") is None  # falha no dígito verificador


def test_search_ranks_and_ignores_stopwords(kb):
    kb.save("financas", "Gastos fixos de outubro", "Aluguel 1500, internet 120.")
    kb.save("saude", "Exame de sangue", "Colesterol LDL 130, o médico pediu repetir.")
    assert titles(kb.search("quanto gasto de aluguel?")) == ["Gastos fixos de outubro"]
    assert titles(kb.search("colesterol")) == ["Exame de sangue"]
    assert kb.search("de que o") == []


def test_search_ignores_accents_and_filters_area(kb):
    kb.save("saude", "Consulta", "O médico pediu exames.")
    kb.save("lazer", "Viagem", "Médico recomendou descanso na praia.")
    assert len(kb.search("medico")) == 2
    assert titles(kb.search("medico", area="lazer")) == ["Viagem"]


def test_reindex_picks_up_manual_edits(kb):
    (kb.root / "lazer" / "manual.md").write_text("Viagem para Gramado em julho", encoding="utf-8")
    assert kb.search("gramado") == []
    kb.reindex()
    assert titles(kb.search("gramado")) == ["manual"]


def test_summary_lists_counts_niches_and_recent(kb):
    kb.save("estudos", "Present perfect", "Gramática.", nicho="ingles")
    kb.save("financas", "Gastos", "Aluguel.")
    summary = kb.summary()
    assert "- financas: 1 nota(s); recentes: Gastos" in summary
    assert "nichos: ingles" in summary
    assert "- lazer: 0 nota(s)" in summary


def test_slugify():
    assert slugify("Ação & Reação!") == "acao-reacao"
    assert slugify("???") == "nota"


def test_stats_and_recent(kb):
    kb.save("financas", "Aluguel", "1500")
    kb.save("estudos", "Decorators", "...", nicho="python")
    assert kb.stats()["financas"] == 1 and kb.stats()["lazer"] == 0
    assert {n["title"] for n in kb.recent()} == {"Aluguel", "Decorators"}
    assert next(n for n in kb.recent() if n["title"] == "Decorators")["nicho"] == "python"
