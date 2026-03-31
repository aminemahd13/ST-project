from app.agents.preprocessing_agent import PreprocessingAgent
from app.repositories.pipeline_repository import PipelineRepository


def test_safe_load_json_parses_fenced_payload() -> None:
    agent = PreprocessingAgent(name="preprocessing", repository=PipelineRepository())
    payload = """```json
{"events":[{"title":"Incident"}]}
```"""
    parsed = agent._safe_load_json(payload)  # noqa: SLF001
    assert parsed is not None
    assert parsed["events"][0]["title"] == "Incident"
