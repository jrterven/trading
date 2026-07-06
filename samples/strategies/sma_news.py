def run(ctx):
    candles = ctx.candles
    close = candles["close"]

    fast = close.rolling(10).mean()
    slow = close.rolling(25).mean()
    entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    exits = (fast < slow) & (fast.shift(1) >= slow.shift(1))

    markers = []
    for score in getattr(ctx, "sentiment", []).to_dict("records"):
        if score.get("label") == "negative" and score.get("score", 0) > 0.55:
            markers.append(
                {
                    "timestamp": candles["timestamp"].iloc[-1],
                    "type": "news",
                    "label": "Noticia negativa",
                    "color": "#d64545",
                }
            )
            break

    return {"entries": entries, "exits": exits, "markers": markers}

