"""JSON schema for the insight extraction step.

OpenRouter's strict mode follows the OpenAI convention: every property must
appear in `required`, and `additionalProperties` must be false. Fields that
may be absent are declared nullable rather than optional.

The findings here are written by the model, not copied, so only `evidence` can
be verified mechanically against the source text. That is the trade made when
moving from transcription to judgement.
"""

MAX_INSIGHTS = 10

DOMAINS = ["clinical", "pharmaceutical", "medical_technology"]

INSIGHT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "finding": {"type": "string"},
        "evidence": {"type": "string"},
        "reasoning": {"type": "string"},
        "domain": {"type": "string", "enum": DOMAINS},
    },
    "required": ["finding", "evidence", "reasoning", "domain"],
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": ["string", "null"]},
        "publisher": {"type": ["string", "null"]},
        "source_url": {"type": ["string", "null"]},
        "publication_date": {"type": ["string", "null"]},
        "period_covered": {"type": ["string", "null"]},
        "insights": {
            "type": "array",
            "items": INSIGHT,
            "maxItems": MAX_INSIGHTS,
        },
        "summary": {"type": "string"},
        "no_insights_reason": {"type": ["string", "null"]},
    },
    "required": [
        "title", "publisher", "source_url", "publication_date",
        "period_covered", "insights", "summary", "no_insights_reason",
    ],
}

# Strict mode does not support maxItems (nor minimum, pattern, format). Sending
# it can fail the call outright, so the cap is enforced in the prompt and
# checked locally instead - the schema that goes over the wire omits it.
import copy as _copy

_API_SCHEMA = _copy.deepcopy(EXTRACTION_SCHEMA)
_API_SCHEMA["properties"]["insights"].pop("maxItems", None)

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "health_insight_extraction",
        "strict": True,
        "schema": _API_SCHEMA,
    },
}
