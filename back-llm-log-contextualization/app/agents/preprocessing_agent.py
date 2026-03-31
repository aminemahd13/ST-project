from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.agents.base_agent import BaseAgent
from app.models.pipeline_models import CollectorOutput, StructuredDocumentOutput
from app.repositories.pipeline_repository import PipelineRepository
from app.services.llm_service import LLMService
from app.utils.pdf_parsing import (
    detect_section_headers,
    extract_customer_counts,
    extract_mw_values,
    extract_voltage_levels,
    merge_duplicate_events,
    parse_duration_to_minutes,
    parse_french_datetime,
)


class PreprocessingAgent(BaseAgent):
    """Transform raw PDF pages into structured report and event objects."""

    def __init__(
        self,
        name: str,
        repository: PipelineRepository,
        llm_service: Optional[LLMService] = None,
    ) -> None:
        super().__init__(name)
        self.repository = repository
        self.llm_service = llm_service or LLMService()

    async def run(self, input_data: CollectorOutput) -> StructuredDocumentOutput:
        pages = input_data.raw_pages
        all_text = "\n".join(page.raw_text for page in pages if page.raw_text)
        report = self._parse_report_metadata(all_text, input_data.filename)
        sections = self._extract_sections(pages)
        events = self._extract_events(pages, report_date=report.get("report_date"))
        llm_events = await self._extract_events_with_llm_fallback(pages)
        events.extend(llm_events)
        events = merge_duplicate_events(events)

        structured = StructuredDocumentOutput(
            document_id=input_data.document_id,
            source_file=input_data.filename,
            report=report,
            sections=sections,
            events=events,
        )
        await self.repository.save_structured_document(structured.model_dump(mode="json"))
        return structured

    async def _extract_events_with_llm_fallback(self, pages: List[Any]) -> List[Dict[str, Any]]:
        """Use LLM as fallback for weak/image-heavy pages flagged by collector."""
        extracted: List[Dict[str, Any]] = []
        for page in pages:
            if not getattr(page, "needs_fallback", False):
                continue
            page_events = await self._llm_extract_page_events(
                page_number=page.page_number,
                page_text=page.raw_text,
            )
            extracted.extend(page_events)
        return extracted

    async def _llm_extract_page_events(self, page_number: int, page_text: str) -> List[Dict[str, Any]]:
        """Ask LLM to extract events in strict JSON from a single page."""
        if not page_text.strip():
            return []
        prompt = (
            "Extract incident/event candidates from this French electricity-grid page.\n"
            "Return ONLY valid JSON with this shape:\n"
            '{"events":[{"event_type":"outage|telecom|interconnection|market|safety|security|environment|equipment_fault|unknown",'
            '"title":"...",'
            '"start_time":null,"end_time":null,"status":"open|closed|unknown",'
            '"control_center":null,"region":null,'
            '"location":{"substation":null,"commune":null,"department":null,"country":"France"},'
            '"impact":{"mw_lost":null,"customers_affected":null,"duration_minutes":null},'
            '"cause":{"category":"weather|human_error|equipment_fault|third_party_damage|malicious_act|unknown","description":null},'
            '"actions_taken":[],"media_relevance":"none|potential|confirmed|unknown","confidence":0.0}]}\n'
            "Rules:\n"
            "- Use null for unknown values, do not invent data.\n"
            "- Preserve French wording in textual fields.\n"
            "- Keep confidence in [0,1].\n\n"
            f"PAGE_TEXT:\n{page_text[:10000]}"
        )
        llm_raw = await self.llm_service.generate(prompt, temperature=0.0)
        if not llm_raw:
            return []

        parsed = self._safe_load_json(llm_raw)
        if not parsed:
            return []
        events = parsed.get("events", [])
        normalized: List[Dict[str, Any]] = []
        for index, event in enumerate(events, start=1):
            if not isinstance(event, dict):
                continue
            normalized.append(
                {
                    "event_id": f"evt-llm-{page_number}-{index}",
                    "source_section": detect_section_headers(page_text) or "unknown",
                    "page_numbers": [page_number],
                    "event_type": event.get("event_type", "unknown"),
                    "subcategory": event.get("subcategory"),
                    "title": (event.get("title") or "")[:140] or f"LLM extracted event page {page_number}",
                    "start_time": event.get("start_time"),
                    "end_time": event.get("end_time"),
                    "status": event.get("status", "unknown"),
                    "control_center": event.get("control_center"),
                    "region": event.get("region"),
                    "location": {
                        "substation": (event.get("location") or {}).get("substation"),
                        "commune": (event.get("location") or {}).get("commune"),
                        "department": (event.get("location") or {}).get("department"),
                        "country": "France",
                    },
                    "assets": event.get("assets")
                    or [{"name": None, "asset_type": "unknown", "voltage_kv": None}],
                    "impact": {
                        "mw_lost": (event.get("impact") or {}).get("mw_lost"),
                        "customers_affected": (event.get("impact") or {}).get("customers_affected"),
                        "industrial_clients_affected": [],
                        "critical_sites_affected": [],
                        "duration_minutes": (event.get("impact") or {}).get("duration_minutes"),
                    },
                    "cause": {
                        "category": (event.get("cause") or {}).get("category", "unknown"),
                        "description": (event.get("cause") or {}).get("description"),
                    },
                    "actions_taken": event.get("actions_taken") or [],
                    "direct_consequences": event.get("direct_consequences") or [],
                    "indirect_consequences": event.get("indirect_consequences") or [],
                    "media_relevance": event.get("media_relevance", "unknown"),
                    "raw_evidence": [{"page": page_number, "text": page_text[:600]}],
                    "confidence": float(event.get("confidence", 0.35)),
                }
            )
        return normalized

    def _safe_load_json(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Parse potential JSON response while tolerating fenced blocks."""
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

    def _parse_report_metadata(self, text: str, source_file: str) -> Dict[str, Any]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = lines[0] if lines else source_file
        report_date = parse_french_datetime(text)
        normalized_date: Optional[str] = None
        if report_date:
            normalized_date = datetime.fromisoformat(report_date).date().isoformat()

        lower_text = text.lower()
        scope = "weekend" if "week-end" in lower_text or "weekend" in lower_text else "day"
        if "quotidien" not in lower_text and scope == "day":
            scope = "unknown"

        return {
            "title": title,
            "report_date": normalized_date,
            "report_scope": scope,
            "language": "fr",
            "summary": {
                "highlights": self._extract_bullets(text, marker_patterns=[r"faits marquants", r"r[ée]sum[ée]"]),
                "constraints_current_day": self._extract_bullets(
                    text,
                    marker_patterns=[r"contraintes.*jour", r"contraintes attendues"],
                ),
            },
        }

    def _extract_bullets(self, text: str, marker_patterns: List[str]) -> List[str]:
        lines = text.splitlines()
        bullets: List[str] = []
        capture = False
        for line in lines:
            clean = line.strip()
            if any(re.search(pattern, clean.lower()) for pattern in marker_patterns):
                capture = True
                continue
            if capture and detect_section_headers(clean):
                break
            if capture and re.match(r"^[-•*]\s+", clean):
                bullets.append(re.sub(r"^[-•*]\s+", "", clean))
        return bullets

    def _extract_sections(self, pages: List[Any]) -> List[Dict[str, Any]]:
        sections: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None
        for page in pages:
            section_name = detect_section_headers(page.raw_text)
            if section_name:
                if current:
                    current["page_end"] = page.page_number - 1
                    sections.append(current)
                current = {
                    "name": section_name,
                    "page_start": page.page_number,
                    "page_end": page.page_number,
                    "items": [],
                }
            if current:
                current["items"].append(
                    {
                        "page": page.page_number,
                        "text_preview": page.raw_text[:500],
                    }
                )
        if current:
            current["page_end"] = pages[-1].page_number if pages else current["page_start"]
            sections.append(current)
        return sections

    def _extract_events(self, pages: List[Any], report_date: Optional[str]) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        default_year = int(report_date.split("-")[0]) if report_date else None
        for page in pages:
            page_text = page.raw_text or ""
            if not page_text:
                continue
            event_blocks = re.split(r"\n{2,}", page_text)
            for block in event_blocks:
                if len(block.strip()) < 60:
                    continue
                event_type = self._infer_event_type(block)
                if event_type == "unknown" and "incident" not in block.lower() and "min" not in block.lower():
                    continue
                start_iso, end_iso = self._extract_time_range(block, default_year)
                duration = parse_duration_to_minutes(block)
                mw_values = extract_mw_values(block)
                customer_counts = extract_customer_counts(block)
                voltages = extract_voltage_levels(block)
                event_id = f"evt-{page.page_number}-{len(events) + 1}"
                confidence = self._compute_confidence(block, start_iso, mw_values, customer_counts)
                event = {
                    "event_id": event_id,
                    "source_section": detect_section_headers(block) or "unknown",
                    "page_numbers": [page.page_number],
                    "event_type": event_type,
                    "subcategory": None,
                    "title": block.splitlines()[0][:140],
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "status": self._infer_status(block),
                    "control_center": self._extract_location_value(block, "dispatching|centre de conduite|ccr"),
                    "region": self._extract_location_value(block, "region|r[ée]gion"),
                    "location": {
                        "substation": self._extract_location_value(block, "poste|sous-station|substation"),
                        "commune": self._extract_location_value(block, "commune"),
                        "department": self._extract_location_value(block, "d[ée]partement"),
                        "country": "France",
                    },
                    "assets": self._extract_assets(block, voltages),
                    "impact": {
                        "mw_lost": mw_values[0] if mw_values else None,
                        "customers_affected": customer_counts[0] if customer_counts else None,
                        "industrial_clients_affected": [],
                        "critical_sites_affected": [],
                        "duration_minutes": duration,
                    },
                    "cause": {
                        "category": self._infer_cause_category(block),
                        "description": self._extract_cause_description(block),
                    },
                    "actions_taken": self._extract_actions(block),
                    "direct_consequences": [],
                    "indirect_consequences": [],
                    "media_relevance": self._infer_media_relevance(block),
                    "raw_evidence": [{"page": page.page_number, "text": block[:600]}],
                    "confidence": confidence,
                }
                events.append(event)
        return events

    def _extract_time_range(self, text: str, default_year: Optional[int]) -> tuple[Optional[str], Optional[str]]:
        matches = re.findall(r"\d{1,2}[\/\-\.\s]\d{1,2}(?:[\/\-\.\s]\d{2,4})?(?:\s+\d{1,2}[:h]\d{2})?", text)
        if not matches:
            return None, None
        start = parse_french_datetime(matches[0], default_year=default_year)
        end = parse_french_datetime(matches[1], default_year=default_year) if len(matches) > 1 else None
        return start, end

    def _infer_event_type(self, text: str) -> str:
        lower = text.lower()
        if re.search(r"telecom|teleconduite|supervision", lower):
            return "telecom"
        if re.search(r"interconnexion|couplage|ajustement", lower):
            return "interconnection"
        if re.search(r"s[ée]curit[ée]|intrusion|malveillant", lower):
            return "security"
        if re.search(r"incendie|s[ûu]ret[ée]|sant[ée]|environnement", lower):
            return "safety"
        if re.search(r"d[ée]faut|transformateur|disjoncteur|ligne|poste", lower):
            return "equipment_fault"
        if re.search(r"production|groupe", lower):
            return "market"
        if re.search(r"coupure|d[ée]lestage|perte de charge", lower):
            return "outage"
        return "unknown"

    def _infer_status(self, text: str) -> str:
        lower = text.lower()
        if "retabli" in lower or "rétabli" in lower or "clos" in lower:
            return "closed"
        if "en cours" in lower:
            return "open"
        return "unknown"

    def _extract_location_value(self, text: str, key_pattern: str) -> Optional[str]:
        match = re.search(rf"(?:{key_pattern})\s*[:\-]?\s*([A-Za-zÀ-ÿ0-9\-\s']{{2,60}})", text, re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip(" -")

    def _extract_assets(self, text: str, voltages: List[int]) -> List[Dict[str, Any]]:
        assets: List[Dict[str, Any]] = []
        for pattern, asset_type in [
            (r"ligne\s+([A-Za-z0-9\-/ ]+)", "line"),
            (r"transformateur\s+([A-Za-z0-9\-/ ]+)", "transformer"),
            (r"disjoncteur\s+([A-Za-z0-9\-/ ]+)", "breaker"),
            (r"groupe\s+([A-Za-z0-9\-/ ]+)", "group"),
            (r"poste\s+([A-Za-z0-9\-/ ]+)", "poste"),
            (r"liaison\s+([A-Za-z0-9\-/ ]+)", "liaison"),
        ]:
            for match in re.findall(pattern, text, re.IGNORECASE):
                assets.append(
                    {
                        "name": match.strip()[:80],
                        "asset_type": asset_type,
                        "voltage_kv": voltages[0] if voltages else None,
                    }
                )
        if not assets:
            assets.append({"name": None, "asset_type": "unknown", "voltage_kv": voltages[0] if voltages else None})
        return assets

    def _infer_cause_category(self, text: str) -> str:
        lower = text.lower()
        if re.search(r"m[ée]t[ée]o|orage|vent|chaleur|canicule", lower):
            return "weather"
        if re.search(r"erreur humaine|manoeuvre|mauvaise manipulation", lower):
            return "human_error"
        if re.search(r"d[ée]faillance|panne|d[ée]faut", lower):
            return "equipment_fault"
        if re.search(r"tiers|travaux tiers|agression", lower):
            return "third_party_damage"
        if re.search(r"malveillant|intrusion|occupation", lower):
            return "malicious_act"
        return "unknown"

    def _extract_cause_description(self, text: str) -> Optional[str]:
        match = re.search(r"cause\s*[:\-]\s*(.+)", text, re.IGNORECASE)
        if not match:
            return None
        return match.group(1).splitlines()[0][:200]

    def _extract_actions(self, text: str) -> List[str]:
        actions: List[str] = []
        for line in text.splitlines():
            low = line.lower()
            if re.search(r"sas|mode d[ée]grad[ée]|couplage|consigne|ordre|r[ée]armement", low):
                actions.append(line.strip()[:160])
        return actions[:8]

    def _infer_media_relevance(self, text: str) -> str:
        lower = text.lower()
        if re.search(r"presse|m[ée]dia|journal|communication", lower):
            return "potential"
        return "none"

    def _compute_confidence(
        self,
        block: str,
        start_iso: Optional[str],
        mw_values: List[float],
        customer_counts: List[int],
    ) -> float:
        score = 0.2
        if len(block) > 100:
            score += 0.2
        if start_iso:
            score += 0.2
        if mw_values:
            score += 0.2
        if customer_counts:
            score += 0.2
        return round(min(score, 0.99), 2)

