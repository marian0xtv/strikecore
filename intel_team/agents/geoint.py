"""GEOINT specialist — geospatial / image-derived / temporal intelligence.

Domain coverage (CLAUDE.md §5 GEOINT + §2.3 asymmetric tradecraft):

* EXIF GPS extraction from images (exiftool)
* Timezone correlation from post-time clustering (reveals real timezone
  even when the stated location lies)
* Place-of-interest identification (visible landmarks, signage, vegetation,
  road markings, architecture)
* Sun-angle / shadow analysis, weather correlation
* IP geolocation (only when an authoritative source — authenticated APIs,
  not scraping)
* Movement-pattern inference across posts/photos
* Mat2 / metagoofil / metadetective signal aggregation

The specialist operates over **pre-collected tool output** — it does not
run the tools. It applies GEOINT tradecraft to derive defensible findings.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from intel_team.agents.base import AgentConfig, BaseSpecialist
from intel_team.types import Domain, PIR

logger = logging.getLogger("intel_team.agents.geoint")


class GEOINTSpecialist(BaseSpecialist):
    """Geospatial-intelligence specialist."""

    config = AgentConfig(
        name="geoint_specialist",
        domain=Domain.GEOINT,
        system_prompt_file="geoint.md",
        allowed_tool_categories=["geoint"],
        model_tier="specialist",
        max_tokens=6000,
        temperature=0.15,
    )

    _ALLOWED_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "gps_coords",
            "country",
            "region",
            "city",
            "neighbourhood",
            "address",
            "venue",
            "place_of_interest",
            "timezone",
            "movement_pattern",
            "photo_location",
            "visual_landmark",
            "weather_signal",
            "sun_angle_signal",
            "language_signal",
            "device_make",       # EXIF Make/Model
            "device_model",
            "ip_geolocation",
            "other",
        }
    )

    # _FORBIDDEN_TYPES inherited (forbids phone)

    # Override to include the EXIF / image-metadata payload (key GEOINT context)
    def _build_user_message(self, pir: PIR, context: dict[str, Any]) -> str:
        import json

        payload = {
            "pir": {
                "id": pir.id,
                "question": pir.question,
                "target": pir.target,
                "constraints": pir.constraints,
            },
            "investigation_store_summary": context.get("store_summary", ""),
            "recent_tool_outputs": context.get("tool_outputs", {}),
            "exif_dumps": context.get("exif_dumps", {}),         # GEOINT-specific
            "post_timestamps": context.get("post_timestamps", []),  # for timezone correlation
            "claimed_locations": context.get("claimed_locations", []),
            "operator_notes": context.get("operator_notes", ""),
        }
        return (
            "Analyse the material below and produce a GEOINT report per the "
            "JSON schema in your system prompt. Return ONLY the JSON object.\n\n"
            + json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        )
