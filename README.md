# Fumap LINE Webhook V2 Clean

LINE webhook server for Fumap AI 分析.

## Core features

- LINE Messaging API webhook: `/callback`
- Rich Menu text handler: `A / B / C / D / E / F`
- Member management through Google Sheet
- BASIC / VIPFULL permission control
- BotLive bridge using `BotLiveMembers.member_token`
- Manual report flow:
  - member sends `tokenomic ETH`, `signal BTC`, `session SOL`
  - request is saved into `AdminInbox`
  - admin replies with `reply Q00001 ...` or `report Q00001 https://...`
- AI chatbot mode for BASIC / VIPFULL
- TradingView webhook endpoint: `/webhook/tradingview`

## Render build settings

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
gunicorn main:app
```

## Required Render environment variables

```env
ADMIN_TOKEN=fumap_admin_123
ADMIN_LINE_USER_IDS=YOUR_LINE_USER_ID
BOTLIVE_BASE_URL=https://fumap-bot-life.onrender.com
BOTLIVE_SHEET_NAME=BotLiveMembers
GOOGLE_SHEET_ID=YOUR_GOOGLE_SHEET_ID
GOOGLE_SERVICE_ACCOUNT_JSON=YOUR_SERVICE_ACCOUNT_JSON
LINE_CHANNEL_SECRET=YOUR_LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN=YOUR_LINE_CHANNEL_ACCESS_TOKEN
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
OPENAI_MODEL=gpt-5-mini
TZ=Asia/Taipei
```

Optional:

```env
MARKET_CONTEXT_SHEET_NAME=MarketContext
MAX_LEVERAGE=10
TRADINGVIEW_WEBHOOK_SECRET=fumap_tv_secret_123
WEBHOOK_SECRET=fumap_tv_secret_123
AI_CHAT_ALLOW_FREE=false
AI_DAILY_LIMIT_ACTIVE=10
AI_DAILY_LIMIT_FREE=0
AI_CHAT_COOLDOWN_SECONDS=30
```

## Health check

```text
https://YOUR_RENDER_URL/health
```

Admin env check:

```text
https://YOUR_RENDER_URL/health/env-check?token=fumap_admin_123
```

Initialize Google Sheet tabs:

```text
https://YOUR_RENDER_URL/admin/sheets/init?token=fumap_admin_123
```

## LINE Developers

Webhook URL:

```text
https://YOUR_RENDER_URL/callback
```

Use webhook: ON

Rich Menu text action should send:

```text
A
B
C
D
E
F
```

## Admin commands

Open BASIC:

```text
basic Uxxxxxxxx 30
```

Open VIPFULL:

```text
vip Uxxxxxxxx 30
```

Disable / reset to FREE:

```text
free Uxxxxxxxx
```

View member requests:

```text
inbox
```

Send report text:

```text
reply Q00001 report content here
```

Send report link:

```text
report Q00001 https://...
```

Update Rich Menu links:

```text
a https://...
b https://...
c https://...
learn1 https://...
learn2 https://...
learn3 https://...
learn4 https://...
learn5 https://...
basiclink https://...
viplink https://...
support https://...
botguide https://...
```

Send direct message:

```text
send Uxxxxxxxx message content
```

## Member commands

```text
id
me
botlive
chatbot
off chatbot
tokenomic ETH
signal BTC
session SOL
```

## Google Sheet tabs

The app creates these tabs automatically:

- `BotLiveMembers`
- `ContentLinks`
- `UserState`
- `AdminInbox`
- `MemberReports`
- `TradingViewAlerts`
- `MarketContext`

## BotLive connection

This LINE webhook writes member rows to `BotLiveMembers` using the same schema expected by `fumap-bot-life`:

```text
line_user_id | display_name | plan | bot_limit | active_bot_count | status | started_at | expired_at | member_token | note | created_at | updated_at
```

When a member enters:

```text
botlive
```

The LINE bot returns:

```text
https://fumap-bot-life.onrender.com/member?token=MEMBER_TOKEN
```
