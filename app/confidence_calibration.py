from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from app.config import CALIBRATION_MODEL_PATH, ENABLE_CONFIDENCE_CALIBRATION

EPS = 1e-6
DEFAULT_MAX_ITER = 500
DEFAULT_LR = 0.05
DEFAULT_L2 = 1e-3


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _logit(probability: float) -> float:
    p = max(EPS, min(1.0 - EPS, float(probability)))
    return math.log(p / (1.0 - p))


def _brier_score(predictions: list[float], labels: list[int]) -> float:
    if not predictions or len(predictions) != len(labels):
        return 0.0
    total = 0.0
    for prediction, label in zip(predictions, labels):
        delta = float(prediction) - float(label)
        total += delta * delta
    return total / len(predictions)


def _extract_confidence(row: dict[str, Any]) -> float | None:
    for key in ("confidence_raw", "confidence_calibrated", "confidence"):
        if key not in row:
            continue
        try:
            return _clamp01(float(row[key]))
        except (TypeError, ValueError):
            return None
    return None


def _extract_label(row: dict[str, Any]) -> int | None:
    for key in ("directional_success", "success", "outcome"):
        if key not in row:
            continue
        value = row[key]
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return 1 if float(value) > 0 else 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"win", "profit", "success", "true", "1"}:
                return 1
            if lowered in {"loss", "fail", "false", "0"}:
                return 0
        return None
    return None


def _parse_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows = payload.get("outcomes")
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return []


def load_outcome_points(path: str | Path) -> list[tuple[float, int]]:
    source = Path(path)
    if not source.exists():
        return []

    text = source.read_text(encoding="utf-8").strip()
    if not text:
        return []

    rows: list[dict[str, Any]] = []
    try:
        rows = _parse_rows(json.loads(text))
    except json.JSONDecodeError:
        for line in text.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)

    points: list[tuple[float, int]] = []
    for row in rows:
        confidence = _extract_confidence(row)
        label = _extract_label(row)
        if confidence is None or label is None:
            continue
        points.append((confidence, label))
    return points


def build_mock_outcome_points(count: int = 200) -> list[tuple[float, int]]:
    points: list[tuple[float, int]] = []
    for idx in range(max(20, int(count))):
        confidence = 0.25 + (idx % 75) * (0.70 / 74.0)
        confidence = _clamp01(confidence)
        expected_prob = _clamp01(0.10 + 0.85 * confidence)
        marker = (idx * 17) % 100
        label = 1 if marker < int(expected_prob * 100) else 0
        points.append((confidence, label))
    return points


def fit_platt_scaler(
    points: list[tuple[float, int]],
    *,
    max_iter: int = DEFAULT_MAX_ITER,
    learning_rate: float = DEFAULT_LR,
    l2_penalty: float = DEFAULT_L2,
) -> tuple[float, float]:
    if not points:
        return 1.0, 0.0

    features = [_logit(confidence) for confidence, _ in points]
    labels = [int(label) for _, label in points]

    slope = 1.0
    intercept = 0.0

    for _ in range(max_iter):
        grad_slope = 0.0
        grad_intercept = 0.0
        for feature, label in zip(features, labels):
            prediction = _sigmoid(slope * feature + intercept)
            error = prediction - label
            grad_slope += error * feature
            grad_intercept += error

        n = float(len(features))
        grad_slope = grad_slope / n + l2_penalty * slope
        grad_intercept = grad_intercept / n

        slope -= learning_rate * grad_slope
        intercept -= learning_rate * grad_intercept

    return float(slope), float(intercept)


def apply_platt_calibration(confidence_raw: float, slope: float, intercept: float) -> float:
    feature = _logit(_clamp01(confidence_raw))
    return _clamp01(_sigmoid(float(slope) * feature + float(intercept)))


@dataclass(slots=True)
class CalibrationModel:
    method: str
    slope: float
    intercept: float
    fitted_samples: int
    source: str
    brier_before: float
    brier_after: float
    generated_at: str
    min_samples: int

    def apply(self, confidence_raw: float) -> float:
        return apply_platt_calibration(
            confidence_raw=confidence_raw,
            slope=self.slope,
            intercept=self.intercept,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def save_calibration_model(model: CalibrationModel, path: str | Path | None = None) -> Path:
    destination = Path(path or CALIBRATION_MODEL_PATH)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(model.to_dict(), indent=2), encoding="utf-8")
    return destination


def load_calibration_model(path: str | Path | None = None) -> CalibrationModel | None:
    source = Path(path or CALIBRATION_MODEL_PATH)
    if not source.exists():
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    required = {
        "method",
        "slope",
        "intercept",
        "fitted_samples",
        "source",
        "brier_before",
        "brier_after",
        "generated_at",
        "min_samples",
    }
    if not required.issubset(payload.keys()):
        return None
    try:
        return CalibrationModel(
            method=str(payload["method"]),
            slope=float(payload["slope"]),
            intercept=float(payload["intercept"]),
            fitted_samples=int(payload["fitted_samples"]),
            source=str(payload["source"]),
            brier_before=float(payload["brier_before"]),
            brier_after=float(payload["brier_after"]),
            generated_at=str(payload["generated_at"]),
            min_samples=int(payload["min_samples"]),
        )
    except (TypeError, ValueError):
        return None


_MODEL_CACHE: dict[str, Any] = {
    "path": None,
    "mtime": None,
    "model": None,
}


def get_active_calibration_model(path: str | Path | None = None) -> CalibrationModel | None:
    if not ENABLE_CONFIDENCE_CALIBRATION:
        return None

    source = Path(path or CALIBRATION_MODEL_PATH)
    if not source.exists():
        _MODEL_CACHE["path"] = str(source)
        _MODEL_CACHE["mtime"] = None
        _MODEL_CACHE["model"] = None
        return None

    try:
        mtime = source.stat().st_mtime
    except OSError:
        return None

    if (
        _MODEL_CACHE.get("path") == str(source)
        and _MODEL_CACHE.get("mtime") == mtime
    ):
        return _MODEL_CACHE.get("model")

    model = load_calibration_model(source)
    _MODEL_CACHE["path"] = str(source)
    _MODEL_CACHE["mtime"] = mtime
    _MODEL_CACHE["model"] = model
    return model


def run_calibration_job(
    *,
    outcomes_path: str | Path = "artifacts/live/outcomes.jsonl",
    model_path: str | Path | None = None,
    min_samples: int = 100,
    use_mock_if_needed: bool = True,
) -> dict[str, Any]:
    points = load_outcome_points(outcomes_path)
    source = "real_outcomes"

    if len(points) < int(min_samples):
        if not use_mock_if_needed:
            return {
                "status": "failed",
                "reason": "insufficient_outcomes",
                "input_samples": len(points),
                "min_samples": int(min_samples),
            }
        points = build_mock_outcome_points(count=max(200, int(min_samples)))
        source = "mock_outcomes"

    slope, intercept = fit_platt_scaler(points)
    raw_predictions = [confidence for confidence, _ in points]
    labels = [label for _, label in points]
    calibrated_predictions = [
        apply_platt_calibration(confidence, slope, intercept)
        for confidence, _ in points
    ]
    brier_before = _brier_score(raw_predictions, labels)
    brier_after = _brier_score(calibrated_predictions, labels)

    model = CalibrationModel(
        method="platt_logit",
        slope=slope,
        intercept=intercept,
        fitted_samples=len(points),
        source=source,
        brier_before=brier_before,
        brier_after=brier_after,
        generated_at=_utc_now_iso(),
        min_samples=int(min_samples),
    )
    saved_to = save_calibration_model(model=model, path=model_path)

    return {
        "status": "ok",
        "model_path": str(saved_to),
        "source": source,
        "fitted_samples": len(points),
        "brier_before": round(brier_before, 6),
        "brier_after": round(brier_after, 6),
        "improved": brier_after <= brier_before,
    }
