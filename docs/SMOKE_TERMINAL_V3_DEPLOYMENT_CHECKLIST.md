# Deployment checklist

- pull the terminal branch;
- install package in the existing virtualenv;
- copy/update the systemd unit;
- daemon-reload and restart;
- verify `/health`, `/api/terminal-capabilities`, `/api/market-overview`, `/api/chart`;
- verify browser zoom/pan/crosshair and Entry/SL/TP selection;
- keep `/legacy` available during acceptance.
