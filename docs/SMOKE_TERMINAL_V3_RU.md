# SMOKE Terminal V3

## Назначение

Terminal V3 заменяет минимальную табличную панель на интерактивный торговый интерфейс в стиле Binance/TradingView. Это только визуализация и управление paper-сервисом. Он не меняет торговую семантику, не отправляет ордера и не снимает запрет live.

## Возможности

- свечной график на TradingView Lightweight Charts;
- мышь/тач: масштабирование, прокрутка, перетаскивание и кроссхейр;
- 15m, 1h, 4h и 1d из единого закрытого 15m потока;
- объём и EMA20/EMA50/EMA200 с независимым включением;
- список активной universe с последней ценой, изменением за 24 часа, количеством READY и открытых paper-сделок;
- маркеры READY-сетапов и paper-сделок;
- выбор сетапа из таблицы с Entry, SL, TP и Exit на ценовой шкале;
- инспектор сценария и состояния scanner/kill-switch;
- измерение изменения цены и числа баров между двумя точками;
- fit, fullscreen, клавиши F/R/M;
- сохранение выбранной монеты, timeframe и индикаторов в браузере;
- обновление графика без сброса пользовательского масштаба;
- старая панель остаётся доступна по `/legacy`.

## Техническая изоляция

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

Systemd example уже переключён на:

```text
scripts/smoke_control_server_v3.py
```

После обновления файлов на VPS:

```bash
sudo systemctl daemon-reload
sudo systemctl restart smoke-control
sudo systemctl status smoke-control --no-pager
```

Открыть основной URL панели. `/legacy` показывает прежний интерфейс.

## Ограничения текущей версии

- 1m/5m не предлагаются, потому что серверный canonical stream сейчас 15m. Нельзя рисовать выдуманные младшие свечи.
- стакан и лента сделок не показываются, потому что paper-сервис не хранит order-book/trade stream. Их можно добавить отдельным market-data transport позднее.
- зоны POI/liquidity появятся после подключения production SMOKE CORE event export к панели.
- библиотека графика загружается из pinned CDN `lightweight-charts@4.2.2`; для полностью автономной установки её следует vendor-ить в репозиторий.
