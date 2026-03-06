from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.parse import quote

import requests

from app.config import PEXELS_API_KEY
from app.schemas import NormalizedArticle, PairImpact, SignalCandidate
from app.signal_setup import SignalExecutionPlan

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"

PERSON_IMAGE_LOOKUP = {
    "donald trump": (
        "Donald Trump",
        "https://upload.wikimedia.org/wikipedia/commons/5/56/Donald_Trump_official_portrait.jpg",
    ),
    "trump": (
        "Donald Trump",
        "https://upload.wikimedia.org/wikipedia/commons/5/56/Donald_Trump_official_portrait.jpg",
    ),
    "jerome powell": (
        "Jerome Powell",
        "https://upload.wikimedia.org/wikipedia/commons/2/20/Jerome_Powell_official_portrait.jpg",
    ),
    "powell": (
        "Jerome Powell",
        "https://upload.wikimedia.org/wikipedia/commons/2/20/Jerome_Powell_official_portrait.jpg",
    ),
    "christine lagarde": (
        "Christine Lagarde",
        "https://upload.wikimedia.org/wikipedia/commons/5/5f/Christine_Lagarde_2011.jpg",
    ),
    "lagarde": (
        "Christine Lagarde",
        "https://upload.wikimedia.org/wikipedia/commons/5/5f/Christine_Lagarde_2011.jpg",
    ),
}

THEME_IMAGE_LOOKUP = {
    "geopolitical": (
        "geopolitical tension",
        "https://images.pexels.com/photos/1583582/pexels-photo-1583582.jpeg",
    ),
    "war": (
        "geopolitical tension",
        "https://images.pexels.com/photos/1583582/pexels-photo-1583582.jpeg",
    ),
    "inflation": (
        "inflation and consumer prices",
        "https://images.pexels.com/photos/4386431/pexels-photo-4386431.jpeg",
    ),
    "employment": (
        "labor market and jobs",
        "https://images.pexels.com/photos/3184465/pexels-photo-3184465.jpeg",
    ),
    "rate_decision": (
        "central bank policy",
        "https://images.pexels.com/photos/730547/pexels-photo-730547.jpeg",
    ),
    "risk_sentiment": (
        "market risk sentiment",
        "https://images.pexels.com/photos/210607/pexels-photo-210607.jpeg",
    ),
    "fx": (
        "forex market",
        "https://images.pexels.com/photos/6802042/pexels-photo-6802042.jpeg",
    ),
}

KEYWORD_THEME_MAP = {
    "war": "war",
    "bomb": "war",
    "missile": "war",
    "attack": "war",
    "conflict": "war",
    "sanction": "geopolitical",
    "inflation": "inflation",
    "cpi": "inflation",
    "jobs": "employment",
    "employment": "employment",
    "payroll": "employment",
    "nfp": "employment",
    "fomc": "rate_decision",
    "ecb": "rate_decision",
    "boe": "rate_decision",
    "boj": "rate_decision",
    "rate": "rate_decision",
}


@dataclass(slots=True)
class VisualAttachment:
    image_url: str
    source: str
    kind: str
    hint: str


def _normalize_mode(image_mode: str | None) -> str:
    if not image_mode:
        return "auto"
    mode = str(image_mode).strip().lower()
    if mode in {"off", "none", "disabled"}:
        return "off"
    if mode in {"context", "chart", "auto"}:
        return mode
    return "auto"


def _text_blob(article: NormalizedArticle, signal: SignalCandidate) -> str:
    return " ".join(
        (
            str(article.title or ""),
            str(article.summary or ""),
            str(signal.thesis or ""),
            str(signal.pair or ""),
        )
    ).lower()


def _find_person(text: str) -> tuple[str, str] | None:
    aliases = sorted(PERSON_IMAGE_LOOKUP.keys(), key=len, reverse=True)
    for alias in aliases:
        if alias in text:
            return PERSON_IMAGE_LOOKUP[alias]
    return None


def _guess_theme(text: str, event_type: str) -> str:
    if event_type in THEME_IMAGE_LOOKUP:
        return event_type
    for keyword, theme in KEYWORD_THEME_MAP.items():
        if keyword in text:
            return theme
    return "fx"


def _query_pexels(query: str) -> str | None:
    if not PEXELS_API_KEY:
        return None

    try:
        response = requests.get(
            PEXELS_SEARCH_URL,
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={"Authorization": PEXELS_API_KEY, "User-Agent": "signalyze-ai/1.0"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    photos = payload.get("photos")
    if not isinstance(photos, list) or not photos:
        return None
    first = photos[0] if isinstance(photos[0], dict) else {}
    src = first.get("src") if isinstance(first.get("src"), dict) else {}
    return src.get("large2x") or src.get("large") or src.get("original")


def _build_context_image(
    article: NormalizedArticle,
    pair_impact: PairImpact,
    signal: SignalCandidate,
) -> VisualAttachment | None:
    text = _text_blob(article, signal)
    person = _find_person(text)
    if person:
        person_name, image_url = person
        return VisualAttachment(
            image_url=image_url,
            source="wikimedia",
            kind="person",
            hint=person_name,
        )

    theme_key = _guess_theme(text=text, event_type=pair_impact.event_type)
    query, static_url = THEME_IMAGE_LOOKUP.get(theme_key, THEME_IMAGE_LOOKUP["fx"])
    pexels_url = _query_pexels(query)
    if pexels_url:
        return VisualAttachment(
            image_url=pexels_url,
            source="pexels",
            kind="theme",
            hint=query,
        )

    return VisualAttachment(
        image_url=static_url,
        source="pexels-static",
        kind="theme",
        hint=query,
    )


def _build_chart_image(
    signal: SignalCandidate,
    execution_plan: SignalExecutionPlan | None,
) -> VisualAttachment | None:
    if execution_plan is None:
        return None

    entry = float(execution_plan.entry_trigger_price)
    risk = float(execution_plan.risk_line_price)
    if entry <= 0 or risk <= 0:
        return None

    spread = abs(entry - risk)
    if spread <= 0:
        return None

    points = [0.15, 0.28, 0.42, 0.58, 0.72, 0.86, 1.00]
    scenario_path = [round(risk + (entry - risk) * point, 5) for point in points]
    labels = [f"T-{len(points) - i - 1}" for i in range(len(points))]
    chart_title = f"{signal.pair} 1H setup map"

    chart_config = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "Setup path",
                    "data": scenario_path,
                    "borderColor": "#2A9D8F" if signal.direction == "bullish" else "#E76F51",
                    "backgroundColor": "transparent",
                    "fill": False,
                    "tension": 0.25,
                    "pointRadius": 2,
                },
                {
                    "label": "Entry",
                    "data": [round(entry, 5) for _ in labels],
                    "borderColor": "#1D3557",
                    "borderDash": [6, 4],
                    "fill": False,
                    "pointRadius": 0,
                },
                {
                    "label": "Risk line",
                    "data": [round(risk, 5) for _ in labels],
                    "borderColor": "#6D6875",
                    "borderDash": [3, 3],
                    "fill": False,
                    "pointRadius": 0,
                },
            ],
        },
        "options": {
            "plugins": {
                "title": {"display": True, "text": chart_title},
                "legend": {"display": True, "position": "bottom"},
            },
            "scales": {
                "x": {"grid": {"display": False}},
                "y": {"grid": {"color": "rgba(0,0,0,0.08)"}},
            },
        },
    }

    chart_str = json.dumps(chart_config, separators=(",", ":"))
    chart_url = (
        "https://quickchart.io/chart"
        "?width=1280&height=720&devicePixelRatio=2&format=png&c="
        f"{quote(chart_str, safe='')}"
    )
    return VisualAttachment(
        image_url=chart_url,
        source="quickchart",
        kind="chart",
        hint="entry-risk-setup",
    )


def build_visual_attachment(
    article: NormalizedArticle,
    pair_impact: PairImpact,
    signal: SignalCandidate,
    execution_plan: SignalExecutionPlan | None = None,
    image_mode: str = "auto",
    enable_chart_images: bool = True,
) -> VisualAttachment | None:
    mode = _normalize_mode(image_mode)
    if mode == "off":
        return None

    context_image = _build_context_image(article=article, pair_impact=pair_impact, signal=signal)
    chart_image = (
        _build_chart_image(signal=signal, execution_plan=execution_plan)
        if enable_chart_images
        else None
    )

    if mode == "context":
        return context_image or chart_image
    if mode == "chart":
        return chart_image or context_image

    # auto mode:
    # - prefer person/geopolitical-style image when available
    # - otherwise prefer chart if available
    if context_image and context_image.kind == "person":
        return context_image
    if pair_impact.event_type in {"geopolitical", "risk_sentiment"} and context_image is not None:
        return context_image
    if chart_image is not None:
        return chart_image
    return context_image
