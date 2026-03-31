from __future__ import annotations

import re
from typing import Any, Dict, List

from app.agents.base_agent import BaseAgent
from app.models.pipeline_models import IncidentStageOutput, StructuredDocumentOutput
from app.repositories.pipeline_repository import PipelineRepository


class IncidentAgent(BaseAgent):
    """Classify incidents, assign priority, and persist enriched records."""

    def __init__(self, name: str, repository: PipelineRepository) -> None:
        super().__init__(name)
        self.repository = repository

    async def run(self, input_data: StructuredDocumentOutput) -> IncidentStageOutput:
        enriched: List[Dict[str, Any]] = []
        for event in input_data.events:
            incident = dict(event)
            severity = self._classify_severity(event)
            tags = self._extract_tags(event)
            incident["severity"] = severity
            incident["tags"] = tags
            incident["escalate"] = severity in {"critical", "high"}
            incident["incident_type"] = event.get("event_type", "unknown")
            enriched.append(incident)

        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        queue = sorted(
            enriched,
            key=lambda item: (
                priority_order.get(item.get("severity", "low"), 4),
                -(item.get("impact", {}).get("customers_affected") or 0),
                -(item.get("impact", {}).get("mw_lost") or 0),
            ),
        )
        output = IncidentStageOutput(
            document_id=input_data.document_id,
            incidents=enriched,
            priority_queue=queue,
        )
        await self.repository.save_incidents(input_data.document_id, output.incidents)
        return output

    def _classify_severity(self, event: Dict[str, Any]) -> str:
        impact = event.get("impact", {})
        customers = impact.get("customers_affected") or 0
        mw_lost = impact.get("mw_lost") or 0
        text_blob = " ".join([event.get("title") or ""] + event.get("actions_taken", []))
        lower_blob = text_blob.lower()

        if customers >= 50000:
            return "critical"
        if self._mentions_critical_infrastructure(lower_blob):
            return "critical"
        if re.search(r"perte de supervision|perte de t[ée]l[ée]conduite|d[ée]fauts r[ée]p[ée]t[ée]s", lower_blob):
            return "critical"

        if customers >= 10000:
            return "high"
        if mw_lost >= 30:
            return "high"
        if re.search(r"intrusion|occupation|malveillant|service public|industrie", lower_blob):
            return "high"

        if customers > 0 or mw_lost >= 5:
            return "medium"
        if event.get("event_type") in {"equipment_fault", "telecom"}:
            return "medium"
        return "low"

    def _mentions_critical_infrastructure(self, text: str) -> bool:
        return bool(re.search(r"h[ôo]pital|sncf|eau potable|station de pompage|a[ée]roport", text))

    def _extract_tags(self, event: Dict[str, Any]) -> List[str]:
        tags: List[str] = []
        impact = event.get("impact", {})
        text = " ".join(
            [
                event.get("title") or "",
                event.get("cause", {}).get("description") or "",
                " ".join(event.get("actions_taken", [])),
            ]
        ).lower()

        if (impact.get("customers_affected") or 0) > 0:
            tags.append("customer_outage")
        if re.search(r"industrie|industriel|usine", text):
            tags.append("industrial_impact")
        if re.search(r"telecom|t[ée]l[ée]conduite", text):
            tags.append("telecom_loss")
        if re.search(r"supervision|observabilit[ée]|visibilit[ée]", text):
            tags.append("observability_loss")
        if re.search(r"interconnexion|couplage|ajustement", text):
            tags.append("interconnection_action")
        if re.search(r"groupe|production", text):
            tags.append("production_constraint")
        if re.search(r"erreur humaine|manoeuvre", text):
            tags.append("human_error")
        if re.search(r"tiers|travaux tiers|agression", text):
            tags.append("third_party_damage")
        if re.search(r"incendie|feu", text):
            tags.append("fire")
        if re.search(r"malveillant|intrusion", text):
            tags.append("malicious_act")
        if re.search(r"s[ée]curit[ée]|sant[ée]|s[ûu]ret[ée]", text):
            tags.append("safety_event")
        if event.get("media_relevance") in {"potential", "confirmed"}:
            tags.append("media_sensitive")
        return sorted(set(tags))

