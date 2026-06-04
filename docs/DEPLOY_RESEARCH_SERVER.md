# Deploy Research Server on VPS

This deploys only the research server.

No live trading. No exchange keys. No 3Commas. No order execution.

## 1. Install system packages

```bash
sudo apt update
sudo apt install -y git python3 python3-venv curl
```

## 2. Create service user

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin smoke || true
```

## 3. Clone repository

```bash
sudo mkdir -p /opt/smoke-strategy
sudo chown -R $USER:$USER /opt/smoke-strategy
git clone https://github.com/SanChi117/Smoke-strategy.git /opt/smoke-strategy
cd /opt/smoke-strategy
```

## 4. Create Python environment

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .
```

## 5. Create `.env`

```bash
cp .env.example .env
```

Default safe config:

```bash
SMOKE_RESEARCH_MODE=research
SMOKE_RESEARCH_HOST=127.0.0.1
SMOKE_RESEARCH_PORT=8080
SMOKE_RESEARCH_BASE_DIR=/opt/smoke-strategy
RESEARCH_SERVER_TOKEN=
```

Keep `127.0.0.1` unless nginx/reverse proxy and firewall are configured.

For VPS use, set a token before exposing any endpoint:

```bash
nano .env
```

Example:

```bash
RESEARCH_SERVER_TOKEN=change-this-long-random-token
```

When `RESEARCH_SERVER_TOKEN` is set, all non-`/health` endpoints require:

```text
X-Research-Token: change-this-long-random-token
```

## 6. Run smoke tests before service install

```bash
.venv/bin/python -m strategy_lab.smoke_test
.venv/bin/python -m strategy_lab.pipeline_smoke_test
.venv/bin/python -m strategy_lab.candle_pipeline_smoke_test
.venv/bin/python -m strategy_lab.end_to_end_smoke_test
.venv/bin/python -m strategy_lab.research_server_smoke_test
```

All tests should end with `OK`.

## 7. Install systemd service

```bash
sudo cp deploy/systemd/smoke-research.service /etc/systemd/system/smoke-research.service
sudo chown -R smoke:smoke /opt/smoke-strategy
sudo systemctl daemon-reload
sudo systemctl enable smoke-research
sudo systemctl start smoke-research
```

## 8. Check status

```bash
sudo systemctl status smoke-research --no-pager
```

Health-check:

```bash
/opt/smoke-strategy/.venv/bin/python /opt/smoke-strategy/scripts/health_check.py --host 127.0.0.1 --port 8080
```

Or with curl:

```bash
curl http://127.0.0.1:8080/health
```

Expected:

```json
{
  "status": "ok",
  "mode": "research",
  "auth_enabled": true
}
```

If `RESEARCH_SERVER_TOKEN` is empty, `auth_enabled` will be `false`.

## 9. Run pipeline through server

### Run existing trade CSV pipeline

```bash
curl -X POST http://127.0.0.1:8080/run/pipeline \
  -H 'Content-Type: application/json' \
  -H 'X-Research-Token: change-this-long-random-token' \
  -d '{"input_csv":"data/sample_runner_trades.csv","out_dir":"results","profile":"growth_100_20x"}'
```

### Run candle end-to-end pipeline

Requires `data/candles.csv`.

```bash
curl -X POST http://127.0.0.1:8080/run/end-to-end \
  -H 'Content-Type: application/json' \
  -H 'X-Research-Token: change-this-long-random-token' \
  -d '{"candles_csv":"data/candles.csv","out_dir":"results","profile":"growth_100_20x","min_confidence":50}'
```

Each server run now creates a separate folder:

```text
results/runs/<run_id>/
```

Inside it:

```text
run_metadata.json
end_to_end_summary.csv
report_sanity_summary.csv
report_sanity_issues.csv
candle_research_report.csv
pipeline_summary.csv
...
```

### List recent runs

```bash
curl "http://127.0.0.1:8080/runs/list?runs_dir=results/runs&limit=20" \
  -H 'X-Research-Token: change-this-long-random-token'
```

The response includes:

```text
run_id
type
started_at
completed_at
profile
sanity_status
generated_trades
executed_trades
ret_pct
max_dd_pct
out_dir
```

### Read latest run metadata

```bash
curl http://127.0.0.1:8080/runs/latest?runs_dir=results/runs \
  -H 'X-Research-Token: change-this-long-random-token'
```

### Read latest reports

```bash
curl http://127.0.0.1:8080/reports/latest?out_dir=results \
  -H 'X-Research-Token: change-this-long-random-token'
```

### Read a specific run

```bash
curl "http://127.0.0.1:8080/reports/latest?out_dir=results&run_id=<run_id>" \
  -H 'X-Research-Token: change-this-long-random-token'
```

## 10. Logs

```bash
sudo journalctl -u smoke-research -n 100 --no-pager
```

Follow logs:

```bash
sudo journalctl -u smoke-research -f
```

## Important safety notes

This service must stay research-only.

Do not add exchange API keys.
Do not add order execution.
Do not expose port 8080 publicly without `RESEARCH_SERVER_TOKEN`, firewall and reverse proxy rules.
