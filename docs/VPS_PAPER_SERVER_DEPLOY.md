# VPS Paper Server Deploy

Final deployment target for the current research baseline:

- Baseline: `TAGGED_MTF_NO_DIRECTION_BLOCK_V1`
- Mode: paper-review only
- Live orders: disabled / not implemented
- Exchange API keys: not used
- Data source: public Binance candles

## What this server does

The server can run on a VPS 24/7 and:

1. scan public 15m candles;
2. generate virtual paper trades only for the final HYBRID v2 baseline;
3. monitor paper TP/SL using candles;
4. save all trades to SQLite;
5. expose status and CSV export endpoints;
6. accept external paper webhooks if needed.

It does not send real orders.

## Files

- `scripts/smoke_paper_server.py` — paper-review server and optional scanner.
- `deployment/smoke-paper.env.example` — environment settings.
- `deployment/smoke-paper.service.example` — systemd unit template.
- `deployment/install_smoke_paper_server.sh` — install/start helper.

## VPS install

Recommended directory:

```bash
/opt/smoke-strategy
```

Copy or clone the repository into that directory, then run:

```bash
cd /opt/smoke-strategy
chmod +x deployment/install_smoke_paper_server.sh
sudo deployment/install_smoke_paper_server.sh
```

The install script creates `.env.paper`, generates a local secret, installs the systemd service and starts it.

## Check server

```bash
curl http://127.0.0.1:8095/health
curl http://127.0.0.1:8095/status
curl http://127.0.0.1:8095/trades?limit=20
```

Export journal:

```bash
curl http://127.0.0.1:8095/export/trades.csv -o paper_trades.csv
```

Logs:

```bash
journalctl -u smoke-paper -f
```

Restart:

```bash
systemctl restart smoke-paper
```

Stop:

```bash
systemctl stop smoke-paper
```

## Config

Edit:

```bash
nano /opt/smoke-strategy/.env.paper
```

Important settings:

```text
SMOKE_AUTO_SCAN=true
SMOKE_SCAN_INTERVAL_SEC=900
SMOKE_CANDLE_LIMIT=1200
SMOKE_MAX_OPEN_PER_SYMBOL=1
SMOKE_DAILY_DD_STOP_PCT=2.0
SMOKE_WEEKLY_DD_STOP_PCT=5.0
SMOKE_MAX_STOP_STREAK=3
```

If `SMOKE_SYMBOLS_FILE` exists, the server uses that symbol list. Otherwise it uses `SMOKE_SYMBOLS`.

## Endpoints

```text
GET  /health
GET  /status
GET  /trades?limit=200
GET  /export/trades.csv
POST /paper-webhook
POST /scan-once
```

External paper webhook example:

```bash
curl -X POST http://127.0.0.1:8095/paper-webhook \
  -H 'Content-Type: application/json' \
  -H 'X-Smoke-Secret: YOUR_SECRET' \
  -d '{
    "action":"entry",
    "symbol":"INJUSDT",
    "side":"short",
    "entry_price":10.0,
    "stop_price":10.2,
    "target_price":9.65,
    "setup_type":"pullback",
    "direction_context":"down",
    "source":"manual_test"
  }'
```

## Paper-review rule

Run until both are true:

- at least 30 calendar days;
- at least 100 closed paper trades.

If one condition is reached earlier, continue until the other is reached too.

## Safety

This repository version is not a live trading bot. Keep paper-review isolated from old 3Commas/TradingView live webhooks. Do not reuse `/webhook`; use `/paper-webhook` only.
