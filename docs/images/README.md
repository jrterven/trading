# Platform screenshots

Unedited browser screenshots captured with Playwright from Trading Lab on localhost on 2026-09-25. Viewport: 1600 × 1050 CSS pixels. UI source: commit `7b200eb`; only documentation changed during capture.

The stock backend used a working copy of the public `trading.duckdb`; crypto used the original `crypto.duckdb` through the app's read-only connection. Alpaca credentials were disabled for this session. The portfolio screenshot shows the disconnected state. No broker orders were submitted.

| File | View |
| --- | --- |
| `platform-overview.png` | AAPL daily chart, 2025-01-01 to 2025-07-01; news range 2025-06-20 to 2025-07-01; Direct + Influential |
| `strategy-editor.png` | Built-in SMA crossover, showing `run(ctx)` and default backtest settings |
| `backtest-results.png` | Real AAPL SMA crossover run: 122 candles, 3 trades, $8,910.05 final equity |
| `crypto-workspace.png` | BTC/USD daily candles with the same chart/news date windows as the overview |
| `dataset-coverage.png` | Local stock coverage with the side panel widened to show all timeframes |
| `paper-portfolio.png` | Portfolio controls without an Alpaca account connected |

To refresh these images, start the application, follow [the platform guide](../PLATFORM_GUIDE.md), and capture the actual viewport after data and editor loading complete. Use a working copy of the stock database for sample runs. Save temporary browser artifacts under `output/playwright/`, then copy the selected screenshots here.
