from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from app.agents.base_agent import BaseAgent
from app.models.pipeline_models import AnalysisStageOutput, IncidentStageOutput
from app.rag.retrieval import Retriever
from app.repositories.pipeline_repository import PipelineRepository
from app.services.llm_service import LLMService


class LLMEnrichmentError(RuntimeError):
    """Raised when strict LLM analysis fails."""

    def __init__(self, message: str, trace: Dict[str, Any]) -> None:
        super().__init__(message)
        self.trace = trace


class AnalysisAgent(BaseAgent):
    """Produce machine-readable and human-readable document-level analysis."""
    PROMPT_VERSION = "analysis-v3"

    def __init__(
        self,
        name: str,
        repository: PipelineRepository,
        llm_service: Optional[LLMService] = None,
        retriever: Optional[Retriever] = None,
    ) -> None:
        super().__init__(name)
        self.repository = repository
        self.llm_service = llm_service or LLMService()
        self.retriever = retriever or Retriever()

    async def run(self, input_data: IncidentStageOutput) -> AnalysisStageOutput:
        incidents = input_data.incidents
        by_severity = Counter(incident.get("severity", "low") for incident in incidents)
        by_cause = Counter(incident.get("cause", {}).get("category", "unknown") for incident in incidents)
        by_region = Counter(incident.get("region") or "unknown" for incident in incidents)
        by_asset = Counter(
            asset.get("asset_type", "unknown")
            for incident in incidents
            for asset in incident.get("assets", [])
        )

        total_mw = sum(float(incident.get("impact", {}).get("mw_lost") or 0) for incident in incidents)
        total_customers = sum(int(incident.get("impact", {}).get("customers_affected") or 0) for incident in incidents)
        critical_incidents = [i for i in incidents if i.get("severity") == "critical"][:5]

        repeated_assets = self._find_repeated_assets(incidents)
        patterns = self._detect_patterns(incidents)
        caveats = self._build_caveats(incidents)
        top_causes = [
            cause
            for cause, _count in by_cause.most_common(3)
            if cause and cause != "unknown"
        ]
        top_regions = [
            region
            for region, _count in by_region.most_common(3)
            if region and region != "unknown"
        ]
        deterministic_context = {
            "stats": {
                "incident_count": len(incidents),
                "by_severity": dict(by_severity),
                "total_mw_impacted": total_mw,
                "total_customers_impacted": total_customers,
                "by_cause": dict(by_cause),
                "by_asset_type": dict(by_asset),
                "by_region": dict(by_region),
            },
            "top_causes": top_causes,
            "top_regions": top_regions,
            "patterns": patterns + repeated_assets,
            "recommended_actions": self._recommend_actions(patterns, incidents),
            "caveats": caveats,
            "critical_incidents": critical_incidents,
        }

        rag_context = await self._retrieve_context(incidents)
        rag_summary = [
            {
                "source": item.get("source"),
                "page": item.get("page"),
                "score": item.get("score"),
            }
            for item in rag_context
        ]

        llm_enrichment, llm_trace = await self._generate_llm_enrichment(
            deterministic_context=deterministic_context,
            incidents=incidents,
            rag_context=rag_context,
        )
        executive_summary = llm_enrichment.get("executive_summary")
        if not isinstance(executive_summary, str) or not executive_summary.strip():
            raise RuntimeError("LLM response is missing 'executive_summary'.")
        executive_summary = self._quality_gate_executive_summary(
            candidate=executive_summary.strip(),
            stats=deterministic_context["stats"],
        )

        cross_incident_insights = self._normalize_string_list(
            llm_enrichment.get("cross_incident_insights"),
            max_items=8,
        )
        cross_incident_insights = self._ensure_cross_incident_insights(
            llm_items=cross_incident_insights,
            deterministic_context=deterministic_context,
        )
        recommended_actions = self._normalize_string_list(
            llm_enrichment.get("recommended_actions"),
            max_items=8,
        )
        recommended_actions = self._ensure_recommended_actions(
            llm_items=recommended_actions,
            deterministic_items=list(deterministic_context["recommended_actions"]),
        )

        reasoning_summary = self._normalize_string_list(
            llm_enrichment.get("reasoning_summary"),
            max_items=8,
        )
        reasoning_summary = self._ensure_reasoning_summary(
            llm_items=reasoning_summary,
            deterministic_context=deterministic_context,
        )

        # Always render a canonical markdown report so UI output is predictable across models.
        human_summary = self._build_human_summary_markdown(
            executive_summary=executive_summary,
            stats=deterministic_context["stats"],
            patterns=deterministic_context["patterns"],
            cross_incident_insights=cross_incident_insights,
            recommended_actions=recommended_actions,
            reasoning_summary=reasoning_summary,
            caveats=caveats,
        )

        analysis_payload = {
            "executive_summary": executive_summary,
            "critical_incidents": critical_incidents,
            "stats": deterministic_context["stats"],
            "patterns": deterministic_context["patterns"],
            "recommended_actions": recommended_actions,
            "caveats": caveats,
            "llm_enhanced": True,
            "llm_model": llm_trace.get("model"),
            "llm_provider": llm_trace.get("provider"),
            "cross_incident_insights": cross_incident_insights,
            "reasoning_summary": reasoning_summary,
            "rag_context": rag_summary,
            "llm_trace": llm_trace,
            "prompt_version": self.PROMPT_VERSION,
        }

        output = AnalysisStageOutput(
            document_id=input_data.document_id,
            analysis=analysis_payload,
            human_summary=human_summary,
        )
        await self.repository.save_analysis(output.model_dump(mode="json"))
        return output

    async def _retrieve_context(self, incidents: List[Dict[str, Any]]) -> List[dict]:
        if not incidents:
            return []
        query_parts = []
        for incident in incidents[:5]:
            title = incident.get("title") or "incident"
            cause = incident.get("cause", {}).get("category") or "unknown"
            severity = incident.get("severity") or "unknown"
            query_parts.append(f"{severity} {cause} {title}")
        query = " ".join(query_parts)
        return await self.retriever.retrieve(query, top_k=4)

    async def _generate_llm_enrichment(
        self,
        deterministic_context: Dict[str, Any],
        incidents: List[Dict[str, Any]],
        rag_context: List[dict],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:

        compact_incidents = [
            {
                "title": item.get("title"),
                "severity": item.get("severity"),
                "event_type": item.get("event_type"),
                "cause": item.get("cause", {}).get("category"),
                "customers_affected": item.get("impact", {}).get("customers_affected"),
                "mw_lost": item.get("impact", {}).get("mw_lost"),
                "duration_minutes": item.get("impact", {}).get("duration_minutes"),
                "status": item.get("status"),
                "region": item.get("region"),
                "control_center": item.get("control_center"),
                "assets": [
                    asset.get("name") or asset.get("asset_type")
                    for asset in (item.get("assets") or [])[:3]
                    if isinstance(asset, dict)
                ],
                "tags": item.get("tags") or [],
                "confidence": item.get("confidence"),
            }
            for item in incidents[:12]
        ]
        context_chunks = [
            {
                "source": item.get("source"),
                "page": item.get("page"),
                "snippet": (item.get("text") or "")[:450],
            }
            for item in rag_context[:3]
        ]

        schema = {
            "executive_summary": "string",
            "cross_incident_insights": ["string"],
            "recommended_actions": ["string"],
            "reasoning_summary": ["string"],
            "human_summary_markdown": "string",
        }
        prompt = (
            "Task: Produce a high-signal incident analysis for the French transmission grid.\n"
            f"Output schema: {json.dumps(schema, ensure_ascii=False)}\n"
            "Quality constraints:\n"
            "- Ground all claims in INCIDENTS / DETERMINISTIC_CONTEXT / OPTIONAL_CONTEXT only.\n"
            "- Do not invent values (MW, customers, causes, assets, regions, counts).\n"
            "- If evidence is missing, explicitly state insufficient evidence.\n"
            "- executive_summary must be 2-3 sentences and include incident_count, critical/high counts, total MW, total customers.\n"
            "- cross_incident_insights must contain 3-6 concrete evidence-based strings.\n"
            "- recommended_actions must contain 3-6 operator actions linked to observed patterns.\n"
            "- reasoning_summary must contain 3-6 short evidence bullets and no hidden chain-of-thought.\n"
            "- human_summary_markdown must include these sections exactly:\n"
            "  # Incident Analysis\n"
            "  ## Executive Summary\n"
            "  ## Key Statistics\n"
            "  ## Patterns\n"
            "  ## Cross-Incident Insights\n"
            "  ## Recommended Actions\n"
            "  ## Caveats\n"
            "- Return valid JSON only, no markdown fences.\n\n"
            f"INCIDENTS={json.dumps(compact_incidents, ensure_ascii=False)}\n"
            f"DETERMINISTIC_CONTEXT={json.dumps(deterministic_context, ensure_ascii=False)}\n"
            f"OPTIONAL_CONTEXT={json.dumps(context_chunks, ensure_ascii=False)}"
        )
        llm_result = await self.llm_service.generate_with_diagnostics(
            prompt,
            temperature=0.0,
            max_tokens=1400,
            system_prompt=self._build_analysis_system_prompt(),
        )
        raw = llm_result.get("output") or ""
        trace = {
            "provider": llm_result.get("provider"),
            "model": llm_result.get("model"),
            "latency_ms": llm_result.get("latency_ms"),
            "response_chars": llm_result.get("response_chars"),
            "request_error": llm_result.get("error"),
            "raw_output_preview": raw[:1800] if raw else None,
            "prompt_incident_count": len(compact_incidents),
            "prompt_rag_sources": [item.get("source") for item in context_chunks if item.get("source")],
            "prompt_version": self.PROMPT_VERSION,
            "parse_ok": False,
        }
        if not raw:
            raise LLMEnrichmentError(
                f"LLM response is empty ({trace['provider']}/{trace['model']}): {trace['request_error'] or 'unknown error'}",
                trace,
            )

        parsed = self._safe_load_json(raw)
        if not parsed:
            raise LLMEnrichmentError("LLM response is not valid JSON.", trace)
        trace["parse_ok"] = True
        return parsed, trace

    def _safe_load_json(self, raw_text: str) -> Optional[Dict[str, Any]]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        cleaned = cleaned.replace("\u201c", '"').replace("\u201d", '"')

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        candidate = re.sub(r",\s*([}\]])", r"\1", match.group(0))
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    def _build_analysis_system_prompt(self) -> str:
        return (
            "You are a senior incident analyst for the French electricity transmission grid.\n"
            "Return exactly one valid JSON object and nothing else.\n"
            "Use only INCIDENTS, DETERMINISTIC_CONTEXT, OPTIONAL_CONTEXT as evidence.\n"
            "Do not invent incidents, values, dates, assets, causes, or locations.\n"
            "If evidence is insufficient, explicitly say 'insufficient evidence'.\n"
            "Ensure recommendations are operational, concrete, and directly tied to observed patterns.\n"
        )

    def _quality_gate_executive_summary(self, *, candidate: str, stats: Dict[str, Any]) -> str:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        if not normalized:
            normalized = self._build_executive_summary(
                int(stats.get("incident_count", 0)),
                Counter(stats.get("by_severity", {})),
                float(stats.get("total_mw_impacted", 0)),
                int(stats.get("total_customers_impacted", 0)),
            )
        has_number = bool(re.search(r"\d", normalized))
        too_short = len(normalized.split()) < 12
        generic_markers = (
            "several incidents",
            "multiple incidents",
            "various incidents",
            "experienced incidents",
        )
        looks_generic = any(marker in normalized.lower() for marker in generic_markers)
        if (not has_number) or too_short or looks_generic:
            normalized = self._build_executive_summary(
                int(stats.get("incident_count", 0)),
                Counter(stats.get("by_severity", {})),
                float(stats.get("total_mw_impacted", 0)),
                int(stats.get("total_customers_impacted", 0)),
            )
            top_cause_pairs = sorted(
                (stats.get("by_cause", {}) or {}).items(),
                key=lambda item: item[1],
                reverse=True,
            )
            top_cause_pairs = [(cause, count) for cause, count in top_cause_pairs if cause != "unknown"][:2]
            if top_cause_pairs:
                cause_phrase = ", ".join(f"{cause} ({count})" for cause, count in top_cause_pairs)
                normalized = f"{normalized} Dominant causes: {cause_phrase}."
        return normalized

    def _ensure_cross_incident_insights(
        self,
        *,
        llm_items: List[str],
        deterministic_context: Dict[str, Any],
    ) -> List[str]:
        baseline = self._build_default_cross_incident_insights(deterministic_context)
        merged = self._dedupe_strings(llm_items + baseline)
        return merged[:8]

    def _ensure_recommended_actions(
        self,
        *,
        llm_items: List[str],
        deterministic_items: List[str],
    ) -> List[str]:
        merged = self._dedupe_strings(llm_items + deterministic_items)
        if not merged:
            return ["No urgent systemic action identified; continue standard monitoring."]
        return merged[:8]

    def _ensure_reasoning_summary(
        self,
        *,
        llm_items: List[str],
        deterministic_context: Dict[str, Any],
    ) -> List[str]:
        baseline = self._build_default_reasoning_summary(deterministic_context)
        merged = self._dedupe_strings(llm_items + baseline)
        return merged[:8]

    def _build_default_cross_incident_insights(self, deterministic_context: Dict[str, Any]) -> List[str]:
        stats = deterministic_context.get("stats", {})
        insights: List[str] = []

        top_causes = deterministic_context.get("top_causes") or []
        if top_causes:
            by_cause = stats.get("by_cause", {})
            cause_bits = [f"{cause} ({by_cause.get(cause, 0)})" for cause in top_causes[:2]]
            insights.append(f"Cause concentration observed: {', '.join(cause_bits)}.")

        top_regions = deterministic_context.get("top_regions") or []
        if top_regions:
            by_region = stats.get("by_region", {})
            region_bits = [f"{region} ({by_region.get(region, 0)})" for region in top_regions[:2]]
            insights.append(f"Regional concentration observed: {', '.join(region_bits)}.")

        repeated_assets = [
            pattern.replace("repeated_asset:", "")
            for pattern in (deterministic_context.get("patterns") or [])
            if isinstance(pattern, str) and pattern.startswith("repeated_asset:")
        ]
        if repeated_assets:
            insights.append(
                f"Repeated asset exposure detected: {', '.join(repeated_assets[:2])} appeared in multiple incidents."
            )

        critical = int((stats.get("by_severity", {}) or {}).get("critical", 0))
        high = int((stats.get("by_severity", {}) or {}).get("high", 0))
        if critical or high:
            insights.append(
                f"Severity mix shows elevated operational risk ({critical} critical, {high} high incidents)."
            )

        total_mw = float(stats.get("total_mw_impacted", 0))
        if total_mw > 0:
            insights.append(f"Aggregate generation/load impact reached {total_mw:.1f} MW across the report period.")

        return insights

    def _build_default_reasoning_summary(self, deterministic_context: Dict[str, Any]) -> List[str]:
        stats = deterministic_context.get("stats", {})
        incident_count = int(stats.get("incident_count", 0))
        by_severity = stats.get("by_severity", {}) or {}
        critical = int(by_severity.get("critical", 0))
        high = int(by_severity.get("high", 0))
        total_mw = float(stats.get("total_mw_impacted", 0))
        total_customers = int(stats.get("total_customers_impacted", 0))

        points = [
            f"{incident_count} incidents were analyzed ({critical} critical, {high} high).",
            f"Computed total impact is {total_mw:.1f} MW and {total_customers} affected customers.",
        ]

        top_causes = deterministic_context.get("top_causes") or []
        if top_causes:
            by_cause = stats.get("by_cause", {})
            points.append(
                "Most frequent causes were "
                + ", ".join(f"{cause} ({by_cause.get(cause, 0)})" for cause in top_causes[:2])
                + "."
            )

        patterns = deterministic_context.get("patterns") or []
        if patterns:
            points.append(f"Detected recurring patterns: {', '.join(patterns[:3])}.")

        if deterministic_context.get("caveats"):
            points.append("Interpretation includes caveats due to confidence/status gaps in extracted events.")
        return points

    def _dedupe_strings(self, values: List[str]) -> List[str]:
        seen: set[str] = set()
        output: List[str] = []
        for item in values:
            cleaned = re.sub(r"\s+", " ", (item or "")).strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            output.append(cleaned)
        return output

    def _normalize_string_list(self, value: Any, max_items: int) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()

        def append_item(candidate: str) -> None:
            clean = re.sub(r"\s+", " ", candidate).strip()
            if not clean or clean in seen:
                return
            seen.add(clean)
            normalized.append(clean)

        if isinstance(value, str):
            for item in self._split_bullet_like_text(value):
                append_item(item)
                if len(normalized) >= max_items:
                    return normalized
            return normalized

        if not isinstance(value, list):
            return []

        for item in value:
            if isinstance(item, str):
                for part in self._split_bullet_like_text(item):
                    append_item(part)
                    if len(normalized) >= max_items:
                        return normalized
                continue

            if isinstance(item, dict):
                label_raw = item.get("type") or item.get("title") or item.get("name")
                label = label_raw.strip() if isinstance(label_raw, str) else ""
                details_raw = item.get("details") or item.get("items") or item.get("evidence")
                details: List[str] = []
                if isinstance(details_raw, str):
                    details = self._split_bullet_like_text(details_raw)
                elif isinstance(details_raw, list):
                    for detail in details_raw:
                        if isinstance(detail, str):
                            details.extend(self._split_bullet_like_text(detail))
                        elif isinstance(detail, dict):
                            text = detail.get("text") or detail.get("detail") or detail.get("description")
                            if isinstance(text, str):
                                details.extend(self._split_bullet_like_text(text))

                if label and details:
                    append_item(f"{label}: {'; '.join(details[:2])}")
                elif label:
                    append_item(label)
                else:
                    for detail in details:
                        append_item(detail)

            if len(normalized) >= max_items:
                break
        return normalized

    def _split_bullet_like_text(self, value: str) -> List[str]:
        parts: List[str] = []
        for raw_line in value.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^[\-\*\u2022]\s*", "", line).strip()
            if line:
                parts.append(line)
        return parts if parts else [value.strip()]

    def _is_thin_markdown(self, markdown: str) -> bool:
        non_empty_lines = [line for line in markdown.splitlines() if line.strip()]
        if len(non_empty_lines) <= 2:
            return True
        normalized = re.sub(r"[#`\-\*\s]", "", markdown)
        return len(normalized) < 90

    def _build_human_summary_markdown(
        self,
        *,
        executive_summary: str,
        stats: Dict[str, Any],
        patterns: List[str],
        cross_incident_insights: List[str],
        recommended_actions: List[str],
        reasoning_summary: List[str],
        caveats: List[str],
    ) -> str:
        lines = [
            "# Incident Analysis",
            "",
            "## Executive Summary",
            executive_summary,
            "",
            "## Key Statistics",
            f"- Incident count: {stats.get('incident_count', 0)}",
            f"- By severity: {stats.get('by_severity', {})}",
            f"- Total MW impacted: {stats.get('total_mw_impacted', 0)}",
            f"- Total customers impacted: {stats.get('total_customers_impacted', 0)}",
        ]
        lines.extend(["", "## Patterns"])
        if patterns:
            lines.extend([f"- {item}" for item in patterns])
        else:
            lines.append("- No recurrent pattern detected in this batch.")

        lines.extend(["", "## Cross-Incident Insights"])
        if cross_incident_insights:
            lines.extend([f"- {item}" for item in cross_incident_insights])
        else:
            lines.append("- Insufficient evidence for additional cross-incident insights.")

        lines.extend(["", "## Recommended Actions"])
        if recommended_actions:
            lines.extend([f"- {item}" for item in recommended_actions])
        else:
            lines.append("- Continue standard monitoring.")

        if reasoning_summary:
            lines.extend(["", "## Reasoning Summary"])
            lines.extend([f"- {item}" for item in reasoning_summary])

        lines.extend(["", "## Caveats"])
        if caveats:
            lines.extend([f"- {item}" for item in caveats])
        else:
            lines.append("- No caveat reported.")
        return "\n".join(lines).strip()

    def _build_executive_summary(
        self,
        incident_count: int,
        by_severity: Counter[str],
        total_mw: float,
        total_customers: int,
    ) -> str:
        return (
            f"{incident_count} incidents identified. "
            f"Critical: {by_severity.get('critical', 0)}, high: {by_severity.get('high', 0)}. "
            f"Total estimated impact: {total_mw:.1f} MW and {total_customers} customers."
        )

    def _find_repeated_assets(self, incidents: List[Dict[str, Any]]) -> List[str]:
        counts = defaultdict(int)
        for incident in incidents:
            for asset in incident.get("assets", []):
                name = asset.get("name")
                if name:
                    counts[name.lower()] += 1
        repeated = [asset for asset, count in counts.items() if count >= 2]
        return [f"repeated_asset:{asset}" for asset in repeated]

    def _detect_patterns(self, incidents: List[Dict[str, Any]]) -> List[str]:
        patterns: List[str] = []
        all_tags = [tag for incident in incidents for tag in incident.get("tags", [])]
        tag_counts = Counter(all_tags)
        tag_to_pattern = {
            "observability_loss": "observability_issues",
            "third_party_damage": "third_party_cable_aggression",
            "human_error": "human_error_pattern",
            "malicious_act": "security_intrusion_pattern",
            "telecom_loss": "telecom_stability_pattern",
        }
        for tag, pattern in tag_to_pattern.items():
            if tag_counts.get(tag, 0) >= 2:
                patterns.append(pattern)
        weather_hits = sum(
            1 for incident in incidents if incident.get("cause", {}).get("category") == "weather"
        )
        if weather_hits >= 2:
            patterns.append("weather_related_incidents")
        return patterns

    def _recommend_actions(self, patterns: List[str], incidents: List[Dict[str, Any]]) -> List[str]:
        actions = {
            "observability_issues": "Audit telemetry and telecontrol redundancy on impacted control centers.",
            "third_party_cable_aggression": "Coordinate preventive patrols with civil works stakeholders in exposed corridors.",
            "human_error_pattern": "Reinforce operating procedures and targeted operator training.",
            "security_intrusion_pattern": "Increase site security controls and incident response readiness.",
            "telecom_stability_pattern": "Review telecom failover mechanisms and supervision alarms.",
            "weather_related_incidents": "Trigger weather hardening checks for vulnerable assets.",
        }
        recommendations = [actions[p] for p in patterns if p in actions]
        if any(incident.get("severity") == "critical" for incident in incidents):
            recommendations.append("Run post-incident review for all critical events within 48 hours.")
        return recommendations or ["No urgent systemic action identified; continue standard monitoring."]

    def _build_caveats(self, incidents: List[Dict[str, Any]]) -> List[str]:
        caveats: List[str] = []
        low_confidence = [incident for incident in incidents if (incident.get("confidence") or 0) < 0.5]
        if low_confidence:
            caveats.append("Some incidents have low extraction confidence and require operator validation.")
        if any(incident.get("status") == "unknown" for incident in incidents):
            caveats.append("At least one incident has unknown closure status.")
        caveats.append("OCR/LLM extraction may require operator validation on degraded pages.")
        return caveats
