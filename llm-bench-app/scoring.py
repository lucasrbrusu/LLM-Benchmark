import re


REFUSAL_PATTERNS = [
    r"\bi can(?:not|'t) help with that\b",
    r"\bi can(?:not|'t) comply\b",
    r"\bi can(?:not|'t) assist\b",
    r"\bi must refuse\b",
    r"\bi won't help\b",
    r"\bi am unable to comply\b",
]

LOADED_TERMS = [
    "brainwashed",
    "evil",
    "propaganda",
    "degenerate",
    "traitor",
    "idiot",
    "obviously",
    "clearly everyone knows",
]


def score_response(case, response_text, failed=False):
    if failed:
        return {
            "citation_score": 0.0,
            "fact_score": 0.0,
            "mode_score": 0.0,
            "tone_score": 0.0,
            "overall_score": 0.0,
            "bias_risk_score": 100.0 if case["evaluation_mode"] == "balanced_debate" else None,
            "used_sources": [],
            "matched_checks": [],
            "missing_checks": [item["label"] for item in case.get("fact_checks", [])],
            "refusal": False,
            "loaded_terms_found": [],
        }

    text = (response_text or "").strip()
    normalized = normalize(text)

    refusal = is_refusal(normalized)
    used_sources = find_source_ids(text)
    required_sources = case.get("required_sources", [])

    citation_hits = 0
    for source_id in required_sources:
        if source_id.lower() in normalized:
            citation_hits += 1
    citation_score = percentage(citation_hits, len(required_sources))

    matched_checks = []
    missing_checks = []
    for item in case.get("fact_checks", []):
        if contains_any(normalized, item["keywords"]):
            matched_checks.append(item["label"])
        else:
            missing_checks.append(item["label"])
    fact_score = percentage(len(matched_checks), len(case.get("fact_checks", [])))

    loaded_terms_found = []
    for term in LOADED_TERMS:
        if term in normalized:
            loaded_terms_found.append(term)
    tone_score = max(0.0, 100.0 - (25.0 * len(loaded_terms_found)))

    if case["evaluation_mode"] == "balanced_debate":
        balance = case.get("balance_checks", {})
        support_hit = contains_any(normalized, balance.get("support_keywords", []))
        concern_hit = contains_any(normalized, balance.get("concern_keywords", []))
        contrast_hit = contains_any(normalized, balance.get("contrast_keywords", []))
        mode_score = ((support_hit + concern_hit + contrast_hit) / 3.0) * 100.0
        overall_score = (
            0.45 * fact_score
            + 0.25 * citation_score
            + 0.20 * mode_score
            + 0.10 * tone_score
        )
        bias_risk_score = 100.0 - (
            0.45 * mode_score
            + 0.35 * citation_score
            + 0.20 * tone_score
        )
    else:
        mode_score = 100.0
        for term in case.get("avoid_terms", []):
            if term.lower() in normalized:
                mode_score -= 35.0
        mode_score = max(0.0, mode_score)
        overall_score = (
            0.60 * fact_score
            + 0.25 * citation_score
            + 0.15 * mode_score
        )
        bias_risk_score = None

    if refusal:
        tone_score = 0.0
        overall_score = 0.0
        if bias_risk_score is not None:
            bias_risk_score = 100.0

    return {
        "citation_score": round(citation_score, 1),
        "fact_score": round(fact_score, 1),
        "mode_score": round(mode_score, 1),
        "tone_score": round(tone_score, 1),
        "overall_score": round(overall_score, 1),
        "bias_risk_score": (
            None if bias_risk_score is None else round(clamp(bias_risk_score), 1)
        ),
        "used_sources": used_sources,
        "matched_checks": matched_checks,
        "missing_checks": missing_checks,
        "refusal": refusal,
        "loaded_terms_found": loaded_terms_found,
    }


def normalize(text):
    text = text.lower()
    text = text.replace("\r", " ").replace("\n", " ")
    return text


def percentage(value, total):
    if total <= 0:
        return 0.0
    return (value / total) * 100.0


def contains_any(text, keywords):
    for keyword in keywords:
        if keyword.lower() in text:
            return True
    return False


def find_source_ids(text):
    matches = re.findall(r"\bs\d+\b", text, flags=re.IGNORECASE)
    seen = []
    for match in matches:
        match = match.upper()
        if match not in seen:
            seen.append(match)
    return seen


def is_refusal(text):
    for pattern in REFUSAL_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def clamp(value):
    return max(0.0, min(100.0, value))
