import json
import re
from typing import Any

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.utils import log

ALLOWED_SENTIMENTS = {"bullish", "bearish", "neutral"}
CLIENT = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

PROMPT_TEMPLATE = """
You are a professional Forex analyst.

Given this news, analyze the sentiment (bullish, bearish, neutral) **for each currency pair mentioned**.

Return a JSON array with objects in this format:
[
  {{ "pair": "USD/JPY", "sentiment": "bullish", "confidence": 0.85 }},
  ...
]

News Title: {title}

Description: {description}

Pairs to analyze: {pairs}
"""

def extract_json_array(content: str) -> list:
    text = (content or "").strip()
    if not text:
        return []

    candidates = [text]
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        candidates.insert(0, match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed

    return []


def normalize_sentiment(items: list[Any], pairs: list[str]) -> list[dict[str, Any]]:
    allowed_pairs = {pair.upper() for pair in pairs}
    normalized_by_pair: dict[str, dict[str, Any]] = {}

    for item in items:
        if not isinstance(item, dict):
            continue

        pair = str(item.get("pair", "")).strip().upper()
        sentiment = str(item.get("sentiment", "")).strip().lower()
        confidence = item.get("confidence", 0)

        if pair not in allowed_pairs or sentiment not in ALLOWED_SENTIMENTS:
            continue

        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0

        normalized = {
            "pair": pair,
            "sentiment": sentiment,
            "confidence": max(0.0, min(confidence, 1.0)),
        }
        existing = normalized_by_pair.get(pair)
        if existing is None or normalized["confidence"] > existing["confidence"]:
            normalized_by_pair[pair] = normalized

    return list(normalized_by_pair.values())


def analyze_sentiment(title: str, description: str, pairs: list[str]) -> list[dict[str, Any]]:
    if not pairs:
        return []
    if CLIENT is None:
        log("OPENAI_API_KEY is missing; skipping sentiment analysis.")
        return []

    prompt = PROMPT_TEMPLATE.format(
        title=title,
        description=description,
        pairs=", ".join(pairs),
    )

    try:
        response = CLIENT.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You analyze Forex news sentiment."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=300,
        )

        content = response.choices[0].message.content or ""
        result = normalize_sentiment(extract_json_array(content), pairs)
        if result:
            log(f"Sentiment analysis: {result}")
        return result

    except Exception:
        log("OpenAI sentiment analysis error.")
        return []
