from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from app.config import STRATEGY_CONFIG_PATH


class StrategyConfigError(ValueError):
    pass


REQUIRED_TOP_LEVEL_KEYS = {
    "metadata",
    "event_universe",
    "hard_gate",
    "volatility_buckets",
    "publish_thresholds",
    "trend_alignment",
    "entry_and_risk",
    "validity_window_hours",
    "lifecycle",
}


def _require_dict(payload: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise StrategyConfigError(f"{field_name} must be an object")
    return payload


def _require_list_of_strings(payload: Any, field_name: str) -> list[str]:
    if not isinstance(payload, list) or not all(isinstance(item, str) and item for item in payload):
        raise StrategyConfigError(f"{field_name} must be a list of non-empty strings")
    return payload


def _require_float_between_0_and_1(payload: Any, field_name: str) -> float:
    try:
        value = float(payload)
    except (TypeError, ValueError):
        raise StrategyConfigError(f"{field_name} must be numeric") from None
    if value < 0.0 or value > 1.0:
        raise StrategyConfigError(f"{field_name} must be between 0 and 1")
    return value


def _require_positive_float(payload: Any, field_name: str) -> float:
    try:
        value = float(payload)
    except (TypeError, ValueError):
        raise StrategyConfigError(f"{field_name} must be numeric") from None
    if value <= 0:
        raise StrategyConfigError(f"{field_name} must be > 0")
    return value


def _require_positive_int(payload: Any, field_name: str) -> int:
    try:
        value = int(payload)
    except (TypeError, ValueError):
        raise StrategyConfigError(f"{field_name} must be an integer") from None
    if value <= 0:
        raise StrategyConfigError(f"{field_name} must be > 0")
    return value


@dataclass(slots=True)
class MajorEventStrategyConfig:
    path: str
    raw: dict[str, Any]

    @property
    def metadata(self) -> dict[str, Any]:
        return self.raw["metadata"]

    @property
    def event_universe(self) -> dict[str, Any]:
        return self.raw["event_universe"]

    @property
    def hard_gate(self) -> dict[str, Any]:
        return self.raw["hard_gate"]

    @property
    def publish_thresholds(self) -> dict[str, Any]:
        return self.raw["publish_thresholds"]

    @property
    def pair_multipliers(self) -> dict[str, float]:
        return self.raw["entry_and_risk"]["pair_multipliers"]


def validate_major_event_strategy(payload: dict[str, Any]) -> None:
    missing = REQUIRED_TOP_LEVEL_KEYS - set(payload.keys())
    if missing:
        raise StrategyConfigError(f"Missing strategy config sections: {sorted(missing)}")

    event_universe = _require_dict(payload["event_universe"], "event_universe")
    _require_list_of_strings(event_universe.get("primary"), "event_universe.primary")
    _require_list_of_strings(event_universe.get("secondary"), "event_universe.secondary")
    _require_list_of_strings(event_universe.get("blocked"), "event_universe.blocked")
    secondary_rules = _require_dict(event_universe.get("secondary_rules"), "event_universe.secondary_rules")
    _require_float_between_0_and_1(secondary_rules.get("event_impact_min"), "event_universe.secondary_rules.event_impact_min")
    _require_float_between_0_and_1(secondary_rules.get("pair_relevance_min"), "event_universe.secondary_rules.pair_relevance_min")
    _require_float_between_0_and_1(secondary_rules.get("impact_now_min"), "event_universe.secondary_rules.impact_now_min")

    hard_gate = _require_dict(payload["hard_gate"], "hard_gate")
    _require_float_between_0_and_1(hard_gate.get("event_impact_min"), "hard_gate.event_impact_min")
    _require_float_between_0_and_1(hard_gate.get("pair_relevance_min"), "hard_gate.pair_relevance_min")
    _require_float_between_0_and_1(hard_gate.get("impact_now_min"), "hard_gate.impact_now_min")
    _require_list_of_strings(hard_gate.get("allowed_latency_classes"), "hard_gate.allowed_latency_classes")
    _require_positive_int(hard_gate.get("freshness_max_minutes"), "hard_gate.freshness_max_minutes")
    _require_float_between_0_and_1(hard_gate.get("source_reliability_min"), "hard_gate.source_reliability_min")

    vol = _require_dict(payload["volatility_buckets"], "volatility_buckets")
    low_max = _require_float_between_0_and_1(vol.get("low_max_atr_percentile"), "volatility_buckets.low_max_atr_percentile")
    normal_max = _require_float_between_0_and_1(vol.get("normal_max_atr_percentile"), "volatility_buckets.normal_max_atr_percentile")
    if low_max >= normal_max:
        raise StrategyConfigError("volatility_buckets.low_max_atr_percentile must be less than normal_max_atr_percentile")

    publish_thresholds = _require_dict(payload["publish_thresholds"], "publish_thresholds")
    for bucket in ("low", "normal", "high"):
        row = _require_dict(publish_thresholds.get(bucket), f"publish_thresholds.{bucket}")
        _require_float_between_0_and_1(row.get("confidence_min"), f"publish_thresholds.{bucket}.confidence_min")
        _require_float_between_0_and_1(row.get("technical_alignment_min"), f"publish_thresholds.{bucket}.technical_alignment_min")

    trend = _require_dict(payload["trend_alignment"], "trend_alignment")
    _require_float_between_0_and_1(trend.get("bullish_min_trend_score"), "trend_alignment.bullish_min_trend_score")
    _require_float_between_0_and_1(trend.get("bearish_max_trend_score"), "trend_alignment.bearish_max_trend_score")

    entry_and_risk = _require_dict(payload["entry_and_risk"], "entry_and_risk")
    _require_positive_int(entry_and_risk.get("lookback_bars_1h"), "entry_and_risk.lookback_bars_1h")
    _require_positive_int(entry_and_risk.get("atr_period_1h"), "entry_and_risk.atr_period_1h")
    pair_multipliers = _require_dict(entry_and_risk.get("pair_multipliers"), "entry_and_risk.pair_multipliers")
    if not pair_multipliers:
        raise StrategyConfigError("entry_and_risk.pair_multipliers cannot be empty")
    for pair, multiplier in pair_multipliers.items():
        if not isinstance(pair, str) or "/" not in pair:
            raise StrategyConfigError("entry_and_risk.pair_multipliers keys must be pair strings like AAA/BBB")
        _require_positive_float(multiplier, f"entry_and_risk.pair_multipliers.{pair}")

    buffer_factors = _require_dict(entry_and_risk.get("buffer_factors"), "entry_and_risk.buffer_factors")
    risk_offset_factors = _require_dict(entry_and_risk.get("risk_offset_factors"), "entry_and_risk.risk_offset_factors")
    for bucket in ("low", "normal", "high"):
        _require_positive_float(buffer_factors.get(bucket), f"entry_and_risk.buffer_factors.{bucket}")
        _require_positive_float(risk_offset_factors.get(bucket), f"entry_and_risk.risk_offset_factors.{bucket}")

    validity = _require_dict(payload["validity_window_hours"], "validity_window_hours")
    min_hours = _require_positive_int(validity.get("min"), "validity_window_hours.min")
    max_hours = _require_positive_int(validity.get("max"), "validity_window_hours.max")
    _require_positive_int(validity.get("base"), "validity_window_hours.base")
    if min_hours > max_hours:
        raise StrategyConfigError("validity_window_hours.min cannot be greater than validity_window_hours.max")

    lifecycle = _require_dict(payload["lifecycle"], "lifecycle")
    _require_list_of_strings(lifecycle.get("states"), "lifecycle.states")
    _require_positive_float(lifecycle.get("profit_r_multiple_threshold"), "lifecycle.profit_r_multiple_threshold")
    try:
        loss_threshold = float(lifecycle.get("loss_r_multiple_threshold"))
    except (TypeError, ValueError):
        raise StrategyConfigError("lifecycle.loss_r_multiple_threshold must be numeric") from None
    if loss_threshold >= 0:
        raise StrategyConfigError("lifecycle.loss_r_multiple_threshold must be negative")


def load_major_event_strategy(path: str | None = None) -> MajorEventStrategyConfig:
    config_path = Path(path or STRATEGY_CONFIG_PATH)
    if not config_path.exists():
        raise StrategyConfigError(f"Strategy config file not found: {config_path}")

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise StrategyConfigError(f"Invalid JSON in strategy config: {config_path}") from err

    if not isinstance(payload, dict):
        raise StrategyConfigError("Strategy config root must be an object")

    validate_major_event_strategy(payload)
    return MajorEventStrategyConfig(path=str(config_path), raw=payload)
