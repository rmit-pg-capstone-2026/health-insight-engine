"""JSON schema for the insight extraction step.

OpenRouter's strict mode follows the OpenAI convention: every property must
appear in `required`, and `additionalProperties` must be false. There is no
way to make a field genuinely optional, so fields that may not apply are
declared nullable and carry null instead of being absent.

Two fields in the saved output never reach the model:

  insight_id            assigned by the script, in returned order
  source.retrieval_date the run time, which the model cannot know

Only `evidence` can be verified mechanically against the source text. The
finding, reasoning and caveat are written by the model - that is the trade
made when moving from transcription to judgement.
"""

MAX_INSIGHTS = 20

INSIGHT_TYPES = ["clinical", "pharmaceutical", "medical_technology"]

SOURCE = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "publisher": {"type": ["string", "null"]},
        "title": {"type": ["string", "null"]},
        "url": {"type": ["string", "null"]},
        "publication_date": {"type": ["string", "null"]},
        "period_covered": {"type": ["string", "null"]},
    },
    "required": [
        "publisher", "title", "url", "publication_date", "period_covered",
    ],
}

INSIGHT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "insight_type": {"type": "string", "enum": INSIGHT_TYPES},
        "finding": {"type": "string"},
        "evidence": {"type": "string"},
        "evidence_location": {"type": ["string", "null"]},
        "target_population": {"type": ["string", "null"]},
        "caveat": {"type": ["string", "null"]},
        "reasoning": {"type": "string"},
    },
    "required": [
        "insight_type", "finding", "evidence", "evidence_location",
        "target_population", "caveat", "reasoning",
    ],
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        # First in the schema on purpose: the model generates keys in order,
        # so it commits to the in-scope decision before it starts writing
        # insights, rather than justifying them afterwards.
        "document_scope": {
            "type": "string",
            "enum": ["in_scope", "out_of_scope"],
        },
        "source": SOURCE,
        "summary": {"type": "string"},
        "insights": {
            "type": "array",
            "items": INSIGHT,
            "maxItems": MAX_INSIGHTS,
        },
        "no_insights_reason": {"type": ["string", "null"]},
    },
    "required": [
        "document_scope", "source", "summary", "insights",
        "no_insights_reason",
    ],
}

# Strict mode does not support maxItems (nor minimum, pattern, format).
# Sending it can fail the call outright, so the cap is enforced in the prompt
# and checked locally instead - the schema that goes over the wire omits it.
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
