import json
import re

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.utils import log

PAIR_PATTERN = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")
CLIENT = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

PROMPT_TEMPLATE = """
You are an AI Forex expert. Based on the news headline and description, identify which currency pairs are affected.

Respond ONLY with a JSON array of standard Forex pairs like ["USD/JPY", "EUR/USD"]. If none, return an empty array.

Title: {title}
Description: {description}
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


def normalize_pairs(values: list) -> list[str]:
    normalized_pairs: list[str] = []
    seen: set[str] = set()

    for value in values:
        if not isinstance(value, str):
            continue
        pair = value.strip().upper()
        if PAIR_PATTERN.fullmatch(pair) and pair not in seen:
            seen.add(pair)
            normalized_pairs.append(pair)

    return normalized_pairs


def detect_currency_pairs(
    title: str,
    description: str,
    allowed_pairs: list[str] | None = None,
) -> list[str]:
    if CLIENT is None:
        log("OPENAI_API_KEY is missing; skipping pair detection.")
        return []

    prompt = PROMPT_TEMPLATE.format(title=title, description=description)

    try:
        response = CLIENT.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You extract currency pairs from news."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=100,
        )

        content = response.choices[0].message.content or ""
        pairs = normalize_pairs(extract_json_array(content))
        if allowed_pairs is not None:
            allowed = {pair.strip().upper() for pair in allowed_pairs if isinstance(pair, str)}
            pairs = [pair for pair in pairs if pair in allowed]
        if pairs:
            log(f"Detected pairs: {pairs}")
        return pairs

    except Exception:
        log("OpenAI pair detection error.")
        return []
