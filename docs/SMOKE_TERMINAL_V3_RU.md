# SMOKE Terminal V3

## Назначение

Terminal V3 заменяет минимальную табличную панель на интерактивный торговый интерфейс в стиле Binance/TradingView. Это визуализация и управление paper-сервисом. Он не меняет торговую семантику, не отправляет ордера и не снимает запрет live.

## Возможности

- свечной график TradingView Lightweight Charts;
- масштабирование, прокрутка, перетаскивание, touch и кроссхейр;
- 15m, 1h, 4h и 1d из единого закрытого 15m потока;
- объём и EMA20/EMA50/EMA200;
- active-universe watchlist: цена, 24h изменение, READY и открытые paper-сделки;
- маркеры READY и paper-сделок;
- выбор сетапа с Entry, SL, TP и Exit на шкале;
- инспектор сценария, scanner и kill-switch;
- измерение изменения цены и количества баров;
- fit, fullscreen, клавиши F/R/M;
- сохранение symbol/timeframe/indicators в браузере;
- автообновление без сброса пользовательского масштаба;
- старая панель по `/legacy`.

## Изоляция

- `scripts/smoke_control_server_v3.py` подключает hardening V2 и добавляет только chart/API transport;
- `strategy_lab/terminal_chart_data.py` агрегирует закрытые свечи и считает causal EMA;
- `web/smoke_terminal_v3.html` содержит интерфейс;
- P1-P8, Decision Engine, risk, portfolio и lifecycle не изменяются.

## API

- `GET /api/chart?symbol=BTCUSDT&timeframe=15m&limit=1800`
- `GET /api/market-overview`
- `GET /api/terminal-capabilities`
- существующие `/api/status`, `/api/candidates`, `/api/trades`, `/api/events` сохранены.

## Запуск

Systemd unit использует `scripts/smoke_control_server_v3.py`. После обновления VPS:

```bash
sudo systemctl daemon-reload
sudo systemctl restart smoke-control
sudo systemctl status smoke-control --no-pager
```

## Ограничения

- 1m/5m не рисуются, потому что canonical server stream сейчас 15m;
- стакан и лента сделок требуют отдельного order-book/trade transport;
- POI/liquidity zones появятся после подключения production SMOKE CORE event export;
- библиотека графика пока загружается из pinned CDN `lightweight-charts@4.2.2`; для полностью автономной установки её позже нужно vendor-ить.
