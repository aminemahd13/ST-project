from app.agents.collector_agent import CollectorAgent
from app.repositories.pipeline_repository import PipelineRepository


def test_select_best_text_prefers_ocr_on_empty_native() -> None:
    agent = CollectorAgent(name="collector", repository=PipelineRepository())
    text, method, needs_fallback = agent._select_best_text(  # noqa: SLF001
        "",
        "Texte OCR assez long pour la page image avec des informations importantes sur les incidents et les valeurs MW.",
    )
    assert text.startswith("Texte OCR")
    assert method == "ocr"
    assert needs_fallback is False


def test_select_best_text_combines_when_both_present() -> None:
    agent = CollectorAgent(name="collector", repository=PipelineRepository())
    text, method, _ = agent._select_best_text(  # noqa: SLF001
        "Texte natif de la page avec contenu suffisant pour être utile.",
        "Complément OCR avec valeurs visuelles.",
    )
    assert "[OCR supplement]" in text
    assert method == "pypdf+ocr"
