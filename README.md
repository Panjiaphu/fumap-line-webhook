# GuiLua FX Webapp

Django + PostgreSQL foundation for a commercial exchange-rate webapp.

## Current scope
- Homepage with today's TWD/VND and USDT rate panels.
- Exchange-rate engine with separate Binance raw data, MaiCoin raw data, internal calculation, official display rate and manual fallback.
- Django admin controls for API/manual pricing mode and source status.
- Registration, login, email activation and password reset pages.
- Member and admin dashboard placeholders.
- Vietnamese default language and Traditional Chinese translation structure.
- Render-ready environment examples and smoke-test script.

## Local setup
```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Rate formula assumption
The current implementation uses this transparent assumption:

```text
official TWD/VND = average Binance P2P USDT/VND SELL / MaiCoin USDT/TWD BUY - 20
```

The owner still needs to confirm rounding, spread policy and whether MaiCoin "buy" should be interpreted from the business or exchange perspective.

## Localization status
- Homepage: Vietnamese default and Traditional Chinese translation keys are prepared.
- Auth pages: translation keys are prepared.
- Member/admin dashboards: translation keys are prepared.
- Trade/event/shop: currently functional placeholders; business copy still needs full Traditional Chinese review after feature details are finalized.

## Secret safety
Use `.env.example` and `deploy/render.env.example` only as templates. Do not commit real passwords, API keys, SSH keys, tokens or Render secrets.

