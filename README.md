# trade-

Research only: is there a tradeable edge in Kalshi's XRP 15-minute markets (series `KXXRP15M`)?

- **[REPORT.md](REPORT.md)** — contract summary, fee table, data inventory, model, calibration, edge grid, verdict.
- **[PREREG.md](PREREG.md)** — date split and pass gate, committed before any outcome data was analysed, plus the follow-up test frozen afterwards.
- `src/` — read-only data downloaders, the fair-value model, and the analysis that produces the report.
- `recorder/record_book.py` — 1-second order-book recorder (needs an always-on host; run for at least 14 days).
- `data/*.json`, `data/leadlag.csv` — result summaries. Raw data is not committed.

Nothing in this repository places orders or uses a trading account; every request is an unauthenticated GET for public market data.
