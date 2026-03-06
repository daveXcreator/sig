from app.utils import log


def generate_signals(sentiment_data: list, rsi_data: list) -> list:
    signals = []

    rsi_map = {r["pair"]: r for r in rsi_data}

    for sentiment_item in sentiment_data:
        pair = sentiment_item["pair"]
        sentiment = sentiment_item["sentiment"]
        confidence = sentiment_item["confidence"]
        rsi_entry = rsi_map.get(pair)

        if not rsi_entry:
            continue

        # Keep pairs where sentiment and RSI direction agree and confidence is strong.
        if sentiment == rsi_entry["signal"] and confidence >= 0.7:
            message = (
                f"*{pair}* -> _{sentiment.upper()}_\n"
                f"- Sentiment Confidence: `{confidence:.2f}`\n"
                f"- RSI: `{rsi_entry['rsi']:.2f}` confirms {sentiment}\n"
            )
            signals.append(
                {
                    "pair": pair,
                    "signal": sentiment,
                    "confidence": confidence,
                    "rsi": rsi_entry["rsi"],
                    "message": message,
                }
            )

    log(f"Generated {len(signals)} signals")
    return signals
