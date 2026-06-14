# Render Deployment Guide

## Target
- Repository: `Panjiaphu/fumap-line-webhook`
- Service ID: `srv-d7p1sr67r5hc73dp04l0`
- Runtime: Python Django with PostgreSQL

## Build command
```bash
pip install -r requirements.txt && python manage.py compilemessages && python manage.py collectstatic --noinput && python manage.py migrate
```

## Start command
```bash
gunicorn config.wsgi:application
```

## Required environment variables
Use `.env.example` and `deploy/render.env.example` as the safe templates. Put real values only in Render environment settings.

## Smoke test
After the service is live:
```bash
APP_BASE_URL=https://your-render-domain.onrender.com scripts/render_smoke_test.sh
```

## Notes
- API prices are attempted first when `api_enabled` is on.
- Admin manual fallback is controlled through Django admin model `SiteRateSettings`.
- The TWD/VND formula currently assumes: average Binance USDT/VND sell divided by MaiCoin USDT/TWD buy, then subtract 20.

