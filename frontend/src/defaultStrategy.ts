export const defaultStrategy = `def run(ctx):
    # ctx.candles es un DataFrame de pandas con las velas cargadas:
    # timestamp, open, high, low, close, volume, symbol, timeframe, source.
    candles = ctx.candles

    # Usamos el cierre de cada vela para calcular las senales.
    close = candles["close"]

    # Media movil rapida y lenta. En 5Min, 10 velas = 50 minutos
    # y 25 velas = 125 minutos. En 1Day, son 10 y 25 dias.
    fast = close.rolling(10).mean()
    slow = close.rolling(25).mean()

    # Compra cuando la media rapida cruza hacia arriba la media lenta.
    # El shift(1) compara contra la vela anterior para detectar el cruce,
    # no solo que fast este arriba de slow.
    entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))

    # Vende cuando la media rapida cruza hacia abajo la media lenta.
    # El motor tambien puede cerrar por Stop % o Take % desde la UI.
    exits = (fast < slow) & (fast.shift(1) >= slow.shift(1))

    # markers permite dibujar anotaciones extra en la grafica.
    # Las compras/ventas principales las genera el motor desde entries/exits.
    markers = []

    # Ejemplo: si hay noticias con sentimiento negativo fuerte, dibuja
    # una marca informativa al final de la serie.
    if len(getattr(ctx, "sentiment", [])) > 0:
        recent_negative = ctx.sentiment[
            (ctx.sentiment["label"] == "negative") & (ctx.sentiment["score"] > 0.55)
        ]
        if len(recent_negative) > 0:
            markers.append({
                "timestamp": candles["timestamp"].iloc[-1],
                "type": "news",
                "label": "Riesgo por noticias",
                "color": "#d64545",
            })

    # El backtester espera entries/exits como booleanos alineados a candles.
    # markers es opcional.
    return {
        "entries": entries,
        "exits": exits,
        "markers": markers,
    }
`;
