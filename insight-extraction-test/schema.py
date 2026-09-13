MEASURE = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value_text": {"type": "string"},
        "value_number": {"type": ["number", "null"]},
        "unit": {"type": ["string", "null"]},
        "population": {"type": ["string", "null"]},
        "period": {"type": ["string", "null"]},
        "comparison": {"type": ["string", "null"]},
        "direction": {
            "type": "string",
            "enum": ["increase", "decrease", "no_change", "not_stated"],
        },
    },
    "required": [
        "value_text", "value_number", "unit",
        "population", "period", "comparison", "direction",
    ],
}

DOMAINS = ["clinical", "pharmaceutical", "medical_technology"]

FINDING = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "finding": {"type": "string"},
        "quote": {"type": "string"},
        "connection_quote": {"type": "string"},
        "topic": {"type": "string"},
        "domain": {"type": "string", "enum": DOMAINS},
        "also_relevant_to": {
            "type": "array",
            "items": {"type": "string", "enum": DOMAINS},
        },
        "measures": {"type": "array", "items": MEASURE},
        "evidence_type": {
            "type": "string",
            "enum": [
                "official_statistic",
                "report_finding",
                "listing_change",
                "commentary",
            ],
        },
        "relevance_reason": {"type": "string"},
    },
    "required": [
        "finding", "quote", "connection_quote", "topic", "domain",
        "also_relevant_to", "measures", "evidence_type", "relevance_reason",
    ],
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": ["string", "null"]},
        "publisher": {"type": ["string", "null"]},
        "publication_date": {"type": ["string", "null"]},
        "source_url": {"type": ["string", "null"]},
        "findings": {"type": "array", "items": FINDING},
        "no_findings_reason": {"type": ["string", "null"]},
    },
    "required": [
        "title", "publisher", "publication_date",
        "source_url", "findings", "no_findings_reason",
    ],
}

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "health_article_extraction",
        "strict": True,
        "schema": EXTRACTION_SCHEMA,
    },
}
