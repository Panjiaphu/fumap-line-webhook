import base64
import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, jsonify, request

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception as e:
    gspread = None
    Credentials = None
    print(f"[startup] Google Sheets disabled: {e}")

try:
    from openai import OpenAI
except Exception as e:
    OpenAI = None
    print(f"[startup] OpenAI disabled: {e}")

# ============================================================
# Fumap LINE Webhook V2 Clean
# - User/member messages: Traditional Chinese
# - Admin messages: Vietnamese
# - BotLive bridge: Google Sheet tab BotLiveMembers + member_token
# ============================================================

app = Flask(__name__)
TW_TZ = timezone(timedelta(hours=8))

# -------------------------
# ENV
# -------------------------

def env_raw(name: str, default: str = "") -> str:
    return os.getenv(name, default) or ""


def env_clean(name: str, default: str = "") -> str:
    v = env_raw(name, default).strip()
    # Do NOT replace all \\n here. For JSON, replacing early can break private_key.
    if len(v) >= 2 and v[0] == v[-1] and v[0] in {'"', "'"}:
        # remove wrapper quotes only. JSON parsing function handles escapes later.
        v = v[1:-1]
    return v.strip()


def env_bool(name: str, default: bool = False) -> bool:
    return env_clean(name, str(default)).lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(env_clean(name, str(default)))
    except Exception:
        return default


LINE_CHANNEL_SECRET = env_clean("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = env_clean("LINE_CHANNEL_ACCESS_TOKEN")
ADMIN_TOKEN = env_clean("ADMIN_TOKEN", "fumap_admin_123")
ADMIN_LINE_USER_IDS = [
    x.strip()
    for x in (env_clean("ADMIN_LINE_USER_IDS") or env_clean("ADMIN_USER_IDS")).replace(";", ",").split(",")
    if x.strip()
]

GOOGLE_SHEET_ID = env_clean("GOOGLE_SHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = env_raw("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SERVICE_ACCOUNT_JSON_BASE64 = env_clean("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64", "")
BOTLIVE_SHEET_NAME = env_clean("BOTLIVE_SHEET_NAME", "BotLiveMembers")
MARKET_CONTEXT_SHEET_NAME = env_clean("MARKET_CONTEXT_SHEET_NAME", "MarketContext")

BOTLIVE_BASE_URL = env_clean("BOTLIVE_BASE_URL", "https://fumap-bot-life.onrender.com").replace("\\n", "").replace("\n", "").strip().rstrip("/")
BOTLIVE_MEMBER_URL = env_clean("BOTLIVE_MEMBER_URL", f"{BOTLIVE_BASE_URL}/member").replace("\\n", "").replace("\n", "").strip()
BOTLIVE_DASHBOARD_URL = env_clean("BOTLIVE_DASHBOARD_URL", f"{BOTLIVE_BASE_URL}/dashboard").replace("\\n", "").replace("\n", "").strip()
BOTLIVE_LEADERBOARD_URL = env_clean("BOTLIVE_LEADERBOARD_URL", f"{BOTLIVE_BASE_URL}/leaderboard").replace("\\n", "").replace("\n", "").strip()
BOTLIVE_WEBHOOK_URL = env_clean("BOTLIVE_WEBHOOK_URL", f"{BOTLIVE_BASE_URL}/webhook/tradingview").replace("\\n", "").replace("\n", "").strip()

OPENAI_API_KEY = env_clean("OPENAI_API_KEY")
OPENAI_MODEL = env_clean("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_OUTPUT_TOKENS = env_int("OPENAI_MAX_OUTPUT_TOKENS", 1200)
AI_CHAT_ALLOW_FREE = env_bool("AI_CHAT_ALLOW_FREE", False)
AI_DAILY_LIMIT_ACTIVE = env_int("AI_DAILY_LIMIT_ACTIVE", 10)
AI_DAILY_LIMIT_FREE = env_int("AI_DAILY_LIMIT_FREE", 0)
AI_CHAT_COOLDOWN_SECONDS = env_int("AI_CHAT_COOLDOWN_SECONDS", 30)

TRADINGVIEW_WEBHOOK_SECRET = env_clean("TRADINGVIEW_WEBHOOK_SECRET") or env_clean("WEBHOOK_SECRET")
MAX_LEVERAGE = env_int("MAX_LEVERAGE", 10)
DEV_ALLOW_ALL = env_bool("DEV_ALLOW_ALL", False)

# -------------------------
# Sheet schema
# -------------------------

MEMBER_HEADERS = [
    "line_user_id", "display_name", "plan", "bot_limit", "active_bot_count", "status",
    "started_at", "expired_at", "member_token", "note", "created_at", "updated_at",
]
CONTENT_HEADERS = ["key", "title_zh", "url", "note_vi", "updated_at"]
STATE_HEADERS = ["line_user_id", "chat_mode", "daily_ai_count", "ai_count_date", "last_ai_at", "updated_at"]
INBOX_HEADERS = ["id", "line_user_id", "display_name", "plan", "request_type", "coin", "raw_text", "status", "created_at", "updated_at"]
REPORT_HEADERS = ["id", "request_id", "line_user_id", "report_type", "coin", "report_text", "report_url", "sent_at"]
TV_HEADERS = ["id", "source", "symbol", "timeframe", "signal", "price", "bias", "raw_payload", "forwarded_to_botlive", "created_at", "active"]
MARKET_HEADERS = ["id", "session", "bias", "risk_level", "raw_text", "summary", "created_by", "created_at", "active"]

SHEETS = {
    BOTLIVE_SHEET_NAME: MEMBER_HEADERS,
    "ContentLinks": CONTENT_HEADERS,
    "UserState": STATE_HEADERS,
    "AdminInbox": INBOX_HEADERS,
    "MemberReports": REPORT_HEADERS,
    "TradingViewAlerts": TV_HEADERS,
    MARKET_CONTEXT_SHEET_NAME: MARKET_HEADERS,
}

DEFAULT_LINKS = [
    ["A_LATEST_URL", "今日易經加密分析", "", "RichMenu A 最新文章", ""],
    ["B_LATEST_URL", "最新技術指標分析", "", "RichMenu B 最新文章", ""],
    ["C_LATEST_URL", "今日加密市場報告", "", "RichMenu C 最新文章", ""],
    ["A_GUIDE_URL", "易經加密分析教學", "", "A hướng dẫn", ""],
    ["B_GUIDE_URL", "技術指標分析教學", "", "B hướng dẫn", ""],
    ["C_GUIDE_URL", "加密市場報告教學", "", "C hướng dẫn", ""],
    ["PLAN_BASIC_URL", "BASIC 會員購買連結", "", "Link mua BASIC", ""],
    ["PLAN_VIP_URL", "VIPFULL 會員購買連結", "", "Link mua VIPFULL", ""],
    ["LEARN_1_URL", "學習 1｜Fumap AI 報告入門", "", "5 link học tập 1", ""],
    ["LEARN_2_URL", "學習 2｜技術指標與趨勢判讀", "", "5 link học tập 2", ""],
    ["LEARN_3_URL", "學習 3｜Tokenomics 代幣經濟", "", "5 link học tập 3", ""],
    ["LEARN_4_URL", "學習 4｜交易時段與市場節奏", "", "5 link học tập 4", ""],
    ["LEARN_5_URL", "學習 5｜BotLive Demo Bot 教學", "", "5 link học tập 5", ""],
    ["BOTLIVE_GUIDE_URL", "BotLive Demo Bot 教學", "", "BotLive hướng dẫn", ""],
    ["SUPPORT_URL", "聯繫客服 / 開通會員", "", "CSKH", ""],
]

PLAN_LIMIT = {"FREE": 0, "BASIC": 1, "VIP": 5, "ADMIN": 999}
PLAN_ZH = {"FREE": "免費用戶", "BASIC": "BASIC 會員", "VIP": "VIPFULL 會員", "ADMIN": "管理員"}

SHORT_LINK_KEYS = {
    "a": "A_LATEST_URL", "b": "B_LATEST_URL", "c": "C_LATEST_URL",
    "aguide": "A_GUIDE_URL", "bguide": "B_GUIDE_URL", "cguide": "C_GUIDE_URL",
    "basiclink": "PLAN_BASIC_URL", "viplink": "PLAN_VIP_URL",
    "learn1": "LEARN_1_URL", "learn2": "LEARN_2_URL", "learn3": "LEARN_3_URL", "learn4": "LEARN_4_URL", "learn5": "LEARN_5_URL",
    "botguide": "BOTLIVE_GUIDE_URL", "support": "SUPPORT_URL",
}

# -------------------------
# Helpers
# -------------------------

def now_tw() -> str:
    return datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")


def today_tw() -> str:
    return datetime.now(TW_TZ).strftime("%Y-%m-%d")


def s(v: Any) -> str:
    return str(v or "").strip()


def normalize_plan(plan: Any) -> str:
    raw = s(plan).upper().replace(" ", "").replace("-", "_")
    if raw in {"B", "BASIC", "BASE", "會員", "会员", "基礎", "基础"}:
        return "BASIC"
    if raw in {"V", "VIP", "VIPFULL", "VIP_FULL", "FULL", "PRO", "進階", "进阶"}:
        return "VIP"
    if raw in {"ADMIN", "A", "MANAGER"}:
        return "ADMIN"
    return "FREE"


def bot_limit_for(plan: str) -> int:
    return PLAN_LIMIT.get(normalize_plan(plan), 0)


def is_admin(line_user_id: str) -> bool:
    return DEV_ALLOW_ALL or (line_user_id in ADMIN_LINE_USER_IDS)


def make_token() -> str:
    return "fm_" + uuid.uuid4().hex[:24]


def make_row_id(prefix: str, count: int) -> str:
    return f"{prefix}{count + 1:05d}"


def clean_url(url: Any) -> str:
    return s(url).replace("\\n", "").replace("\n", "").replace('"', "").strip()


def parse_days(text: str, default: int = 30) -> int:
    try:
        return max(1, int(text))
    except Exception:
        return default


def looks_line_user_id(v: str) -> bool:
    return bool(re.fullmatch(r"U[a-fA-F0-9]{20,40}", s(v)))


def repair_private_key_newlines(raw: str) -> str:
    # If JSON was decoded once and private_key contains literal newlines, json.loads will fail.
    # This repairs only literal newlines inside the private_key string.
    pattern = r'("private_key"\s*:\s*")(.*?)("\s*,\s*"client_email")'
    m = re.search(pattern, raw, flags=re.DOTALL)
    if not m:
        return raw
    key_value = m.group(2)
    key_value = key_value.replace("\r\n", "\\n").replace("\n", "\\n")
    return raw[:m.start(2)] + key_value + raw[m.end(2):]


def parse_service_account_json() -> Dict[str, Any]:
    # Preferred: GOOGLE_SERVICE_ACCOUNT_JSON_BASE64, but raw JSON is also supported.
    if GOOGLE_SERVICE_ACCOUNT_JSON_BASE64:
        b = GOOGLE_SERVICE_ACCOUNT_JSON_BASE64.strip()
        b += "=" * (-len(b) % 4)
        return json.loads(base64.b64decode(b).decode("utf-8"))

    raw = GOOGLE_SERVICE_ACCOUNT_JSON.strip()
    if not raw:
        raise RuntimeError("Missing GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_JSON_BASE64")

    candidates: List[str] = [raw]

    # If user pasted with wrapper quotes into Render.
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        candidates.append(raw[1:-1])

    # If it is a JSON string that contains JSON text.
    try:
        first = json.loads(raw)
        if isinstance(first, dict):
            return first
        if isinstance(first, str):
            candidates.insert(0, first)
    except Exception:
        pass

    last_error: Optional[Exception] = None
    for c in candidates:
        c = c.strip()
        # Try raw as-is.
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
            if isinstance(obj, str):
                obj2 = json.loads(repair_private_key_newlines(obj))
                if isinstance(obj2, dict):
                    return obj2
        except Exception as e:
            last_error = e
        # Try unicode unescape only for strings with visible \n/\" sequences.
        try:
            unescaped = c.encode("utf-8").decode("unicode_escape")
            obj = json.loads(repair_private_key_newlines(unescaped))
            if isinstance(obj, dict):
                return obj
        except Exception as e:
            last_error = e
        # Try repairing private key literal newline.
        try:
            obj = json.loads(repair_private_key_newlines(c))
            if isinstance(obj, dict):
                return obj
        except Exception as e:
            last_error = e

    # Last chance: maybe user accidentally pasted base64 into GOOGLE_SERVICE_ACCOUNT_JSON.
    try:
        b = raw.strip()
        b += "=" * (-len(b) % 4)
        return json.loads(base64.b64decode(b).decode("utf-8"))
    except Exception as e:
        last_error = e

    raise RuntimeError(f"Cannot parse Google service account JSON: {last_error}")

# -------------------------
# Google Sheets
# -------------------------

_gc = None
_ss = None


def sheets_client():
    global _gc
    if _gc:
        return _gc
    if not gspread or not Credentials:
        raise RuntimeError("gspread/google-auth not installed")
    if not GOOGLE_SHEET_ID:
        raise RuntimeError("Missing GOOGLE_SHEET_ID")
    info = parse_service_account_json()
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    _gc = gspread.authorize(creds)
    return _gc


def spreadsheet():
    global _ss
    if _ss:
        return _ss
    _ss = sheets_client().open_by_key(GOOGLE_SHEET_ID)
    return _ss


def ensure_headers(ws, headers: List[str]) -> None:
    existing = ws.row_values(1)
    if not existing:
        ws.append_row(headers)
        return
    missing = [h for h in headers if h not in existing]
    if missing:
        ws.update("1:1", [existing + missing])


def ws(name: str, headers: List[str]):
    ss = spreadsheet()
    try:
        sh = ss.worksheet(name)
    except Exception:
        sh = ss.add_worksheet(title=name, rows=1000, cols=max(20, len(headers) + 2))
        sh.append_row(headers)
        return sh
    ensure_headers(sh, headers)
    return sh


def records(sh) -> List[Dict[str, Any]]:
    out = []
    for i, row in enumerate(sh.get_all_records(), start=2):
        row["_row"] = i
        out.append(row)
    return out


def update_row(sh, row_num: int, data: Dict[str, Any]) -> None:
    headers = sh.row_values(1)
    for k, v in data.items():
        if k in headers:
            sh.update_cell(row_num, headers.index(k) + 1, v)


def append_dict(sh, data: Dict[str, Any]) -> None:
    headers = sh.row_values(1)
    sh.append_row([data.get(h, "") for h in headers], value_input_option="USER_ENTERED")


def init_sheets() -> Dict[str, Any]:
    made = []
    for name, headers in SHEETS.items():
        sh = ws(name, headers)
        made.append(name)
    link_ws = ws("ContentLinks", CONTENT_HEADERS)
    existing = {s(r.get("key")) for r in records(link_ws)}
    for row in DEFAULT_LINKS:
        if row[0] not in existing:
            row[-1] = now_tw()
            link_ws.append_row(row, value_input_option="USER_ENTERED")
    return {"ok": True, "sheets": made, "content_seeded": True}

# -------------------------
# Member / content / inbox
# -------------------------

def member_ws():
    return ws(BOTLIVE_SHEET_NAME, MEMBER_HEADERS)


def get_member(line_user_id: str) -> Optional[Dict[str, Any]]:
    try:
        sh = member_ws()
        rows = [r for r in records(sh) if s(r.get("line_user_id")) == line_user_id]
        if not rows:
            return None
        row = rows[-1]
        row["plan"] = normalize_plan(row.get("plan"))
        if not s(row.get("member_token")):
            token = make_token()
            update_row(sh, int(row["_row"]), {"member_token": token, "updated_at": now_tw()})
            row["member_token"] = token
        return row
    except Exception as e:
        print(f"[member] get failed: {e}")
        return None


def is_active_member(m: Optional[Dict[str, Any]]) -> bool:
    if not m:
        return False
    plan = normalize_plan(m.get("plan"))
    status = s(m.get("status")).upper()
    if status in {"BAN", "BANNED", "BLOCKED", "DELETED", "停用", "封鎖", "封锁"}:
        return False
    if plan in {"BASIC", "VIP", "ADMIN"}:
        exp = s(m.get("expired_at"))
        # Keep permissive: if date missing, active rows still work.
        return status in {"", "ACTIVE", "ADMIN"}
    return False


def upsert_member(line_user_id: str, display_name: str, plan: str, days: int, note: str = "") -> Dict[str, Any]:
    plan = normalize_plan(plan)
    start = today_tw()
    end = (datetime.now(TW_TZ) + timedelta(days=max(1, days))).strftime("%Y-%m-%d") if plan != "FREE" else ""
    now = now_tw()
    sh = member_ws()
    rows = records(sh)
    for r in reversed(rows):
        if s(r.get("line_user_id")) == line_user_id:
            token = s(r.get("member_token")) or make_token()
            data = {
                "display_name": display_name or s(r.get("display_name")),
                "plan": plan,
                "bot_limit": bot_limit_for(plan),
                "status": "ACTIVE" if plan != "FREE" else "FREE",
                "started_at": start,
                "expired_at": end,
                "member_token": token,
                "note": note,
                "updated_at": now,
            }
            update_row(sh, int(r["_row"]), data)
            data["line_user_id"] = line_user_id
            return data
    data = {
        "line_user_id": line_user_id,
        "display_name": display_name,
        "plan": plan,
        "bot_limit": bot_limit_for(plan),
        "active_bot_count": 0,
        "status": "ACTIVE" if plan != "FREE" else "FREE",
        "started_at": start,
        "expired_at": end,
        "member_token": make_token(),
        "note": note,
        "created_at": now,
        "updated_at": now,
    }
    append_dict(sh, data)
    return data


def get_links() -> Dict[str, Dict[str, str]]:
    sh = ws("ContentLinks", CONTENT_HEADERS)
    out: Dict[str, Dict[str, str]] = {}
    for r in records(sh):
        key = s(r.get("key"))
        if key:
            out[key] = {"title_zh": s(r.get("title_zh")), "url": clean_url(r.get("url")), "note_vi": s(r.get("note_vi"))}
    if not out:
        for key, title, url, note, _ in DEFAULT_LINKS:
            out[key] = {"title_zh": title, "url": url, "note_vi": note}
    return out


def set_link(key: str, url: str) -> Dict[str, Any]:
    key = key.strip().upper()
    if key.lower() in SHORT_LINK_KEYS:
        key = SHORT_LINK_KEYS[key.lower()]
    url = clean_url(url)
    sh = ws("ContentLinks", CONTENT_HEADERS)
    for r in records(sh):
        if s(r.get("key")).upper() == key:
            update_row(sh, int(r["_row"]), {"url": url, "updated_at": now_tw()})
            return {"key": key, "url": url, "updated": True}
    title = next((x[1] for x in DEFAULT_LINKS if x[0] == key), key)
    append_dict(sh, {"key": key, "title_zh": title, "url": url, "note_vi": "Admin added", "updated_at": now_tw()})
    return {"key": key, "url": url, "created": True}


def state_get(line_user_id: str) -> Dict[str, Any]:
    sh = ws("UserState", STATE_HEADERS)
    for r in reversed(records(sh)):
        if s(r.get("line_user_id")) == line_user_id:
            return r
    data = {"line_user_id": line_user_id, "chat_mode": "OFF", "daily_ai_count": 0, "ai_count_date": today_tw(), "last_ai_at": "", "updated_at": now_tw()}
    append_dict(sh, data)
    return data


def state_update(line_user_id: str, data: Dict[str, Any]) -> None:
    sh = ws("UserState", STATE_HEADERS)
    data = {**data, "updated_at": now_tw()}
    for r in reversed(records(sh)):
        if s(r.get("line_user_id")) == line_user_id:
            update_row(sh, int(r["_row"]), data)
            return
    base = {"line_user_id": line_user_id, "chat_mode": "OFF", "daily_ai_count": 0, "ai_count_date": today_tw(), "last_ai_at": "", "updated_at": now_tw()}
    base.update(data)
    append_dict(sh, base)


def chat_mode(line_user_id: str, on: bool) -> None:
    try:
        state_update(line_user_id, {"chat_mode": "ON" if on else "OFF"})
    except Exception as e:
        print(f"[state] update failed: {e}")


def create_inbox(line_user_id: str, display_name: str, plan: str, request_type: str, coin: str, raw: str) -> Dict[str, Any]:
    sh = ws("AdminInbox", INBOX_HEADERS)
    rows = records(sh)
    qid = make_row_id("Q", len(rows))
    data = {
        "id": qid,
        "line_user_id": line_user_id,
        "display_name": display_name,
        "plan": normalize_plan(plan),
        "request_type": request_type,
        "coin": coin.upper(),
        "raw_text": raw,
        "status": "NEW",
        "created_at": now_tw(),
        "updated_at": now_tw(),
    }
    append_dict(sh, data)
    return data


def inbox_list(limit: int = 10) -> List[Dict[str, Any]]:
    sh = ws("AdminInbox", INBOX_HEADERS)
    rows = [r for r in records(sh) if s(r.get("status")).upper() in {"", "NEW", "PROCESSING"}]
    return rows[-limit:]


def inbox_get(qid: str) -> Optional[Dict[str, Any]]:
    sh = ws("AdminInbox", INBOX_HEADERS)
    for r in records(sh):
        if s(r.get("id")).upper() == qid.upper():
            return r
    return None


def inbox_update(qid: str, data: Dict[str, Any]) -> bool:
    sh = ws("AdminInbox", INBOX_HEADERS)
    for r in records(sh):
        if s(r.get("id")).upper() == qid.upper():
            update_row(sh, int(r["_row"]), {**data, "updated_at": now_tw()})
            return True
    return False


def save_report(req: Dict[str, Any], text: str = "", url: str = "") -> Dict[str, Any]:
    sh = ws("MemberReports", REPORT_HEADERS)
    rid = make_row_id("R", len(records(sh)))
    data = {
        "id": rid,
        "request_id": s(req.get("id")),
        "line_user_id": s(req.get("line_user_id")),
        "report_type": s(req.get("request_type")),
        "coin": s(req.get("coin")).upper(),
        "report_text": text,
        "report_url": clean_url(url),
        "sent_at": now_tw(),
    }
    append_dict(sh, data)
    return data

# -------------------------
# LINE API
# -------------------------

def line_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}", "Content-Type": "application/json"}


def verify_signature(body: bytes, signature: str) -> bool:
    if DEV_ALLOW_ALL:
        return True
    if not LINE_CHANNEL_SECRET:
        return False
    digest = hmac.new(LINE_CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature or "")


def reply_text(reply_token: str, text: str) -> None:
    if not reply_token or reply_token == "00000000000000000000000000000000":
        return
    try:
        r = requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers=line_headers(),
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": text[:4900]}]},
            timeout=10,
        )
        if r.status_code >= 300:
            print(f"[line] reply failed {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[line] reply exception: {e}")


def push_text(user_id: str, text: str) -> bool:
    if not user_id or not LINE_CHANNEL_ACCESS_TOKEN:
        return False
    try:
        r = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers=line_headers(),
            json={"to": user_id, "messages": [{"type": "text", "text": text[:4900]}]},
            timeout=10,
        )
        if r.status_code >= 300:
            print(f"[line] push failed {r.status_code}: {r.text}")
            return False
        return True
    except Exception as e:
        print(f"[line] push exception: {e}")
        return False


def notify_admins(text: str) -> None:
    for uid in ADMIN_LINE_USER_IDS:
        push_text(uid, text)


def line_profile(user_id: str) -> Dict[str, str]:
    if not user_id or not LINE_CHANNEL_ACCESS_TOKEN:
        return {}
    try:
        r = requests.get(f"https://api.line.me/v2/bot/profile/{user_id}", headers=line_headers(), timeout=8)
        if r.ok:
            return r.json()
    except Exception as e:
        print(f"[line] profile failed: {e}")
    return {}

# -------------------------
# Messages
# -------------------------

def fmt_link(title: str, url: str) -> str:
    return f"・{title}\n{url}" if url else f"・{title}\n準備中，請稍後查看。"


def member_denied() -> str:
    return "🔒 此功能僅限 BASIC / VIPFULL 會員使用。\n請輸入「id」取得會員代碼，並聯繫客服開通。"


def botlive_url(token: str) -> str:
    return f"{BOTLIVE_MEMBER_URL}?token={token}"


def rich_menu_text(code: str) -> str:
    try:
        links = get_links()
    except Exception:
        links = {key: {"title_zh": title, "url": url} for key, title, url, _, _ in DEFAULT_LINKS}
    code = code.upper()
    if code == "A":
        return "🔮 易經加密分析\n\n" + "\n\n".join([
            fmt_link(links.get("A_LATEST_URL", {}).get("title_zh", "今日易經加密分析"), links.get("A_LATEST_URL", {}).get("url", "")),
            fmt_link(links.get("A_GUIDE_URL", {}).get("title_zh", "易經加密分析教學"), links.get("A_GUIDE_URL", {}).get("url", "")),
        ])
    if code == "B":
        return "📊 技術指標分析\n\n這裡提供公開版技術分析與指標教學。會員若需要指定幣種人工分析，請輸入：signal ETH\n\n" + "\n\n".join([
            fmt_link(links.get("B_LATEST_URL", {}).get("title_zh", "最新技術指標分析"), links.get("B_LATEST_URL", {}).get("url", "")),
            fmt_link(links.get("B_GUIDE_URL", {}).get("title_zh", "技術指標分析教學"), links.get("B_GUIDE_URL", {}).get("url", "")),
        ])
    if code == "C":
        return "🧭 加密市場報告\n\n" + "\n\n".join([
            fmt_link(links.get("C_LATEST_URL", {}).get("title_zh", "今日加密市場報告"), links.get("C_LATEST_URL", {}).get("url", "")),
            fmt_link(links.get("C_GUIDE_URL", {}).get("title_zh", "加密市場報告教學"), links.get("C_GUIDE_URL", {}).get("url", "")),
        ])
    if code == "D":
        learn = []
        for i in range(1, 6):
            k = f"LEARN_{i}_URL"
            learn.append(fmt_link(links.get(k, {}).get("title_zh", f"學習 {i}"), links.get(k, {}).get("url", "")))
        return (
            "💎 會員方案\n\n"
            "BASIC 會員\n・可提交 Tokenomics / Signal / Session 人工分析需求\n・可使用 AI Chatbot 解釋報告\n・可建立 1 個 BotLive Demo Bot\n\n"
            "VIPFULL 會員\n・包含 BASIC 全部功能\n・可建立 5 個 BotLive Demo Bot\n・優先處理人工分析需求\n\n"
            "🛒 購買連結\n"
            f"{fmt_link(links.get('PLAN_BASIC_URL', {}).get('title_zh', 'BASIC 會員購買連結'), links.get('PLAN_BASIC_URL', {}).get('url', ''))}\n\n"
            f"{fmt_link(links.get('PLAN_VIP_URL', {}).get('title_zh', 'VIPFULL 會員購買連結'), links.get('PLAN_VIP_URL', {}).get('url', ''))}\n\n"
            "📚 學習資源\n" + "\n\n".join(learn)
        )
    if code == "E":
        return (
            "📘 使用教學\n\n"
            "免費用戶：\n・id：取得會員開通代碼\n・A/B/C/D/E/F：查看主選單內容\n\n"
            "BASIC / VIPFULL 會員：\n・tokenomic ETH：提交代幣經濟分析需求\n・signal BTC：提交技術指標分析需求\n・session SOL：提交交易時段報告需求\n・chatbot：開啟 AI 解釋模式\n・off chatbot：關閉 AI 解釋模式\n・botlive：取得 BotLive 會員中心連結\n\n"
            + fmt_link(links.get("BOTLIVE_GUIDE_URL", {}).get("title_zh", "BotLive Demo Bot 教學"), links.get("BOTLIVE_GUIDE_URL", {}).get("url", ""))
        )
    if code == "F":
        return "☎️ 客服中心\n\n若要開通 BASIC / VIPFULL，請先輸入「id」取得會員代碼，再聯繫客服。\n\n" + fmt_link(links.get("SUPPORT_URL", {}).get("title_zh", "聯繫客服 / 開通會員"), links.get("SUPPORT_URL", {}).get("url", ""))
    return "請選擇 A / B / C / D / E / F。"


def admin_help() -> str:
    return (
        "🛠 Lệnh admin Fumap V2 Clean\n"
        "basic Uxxxx 30  → mở BASIC 30 ngày\n"
        "vip Uxxxx 30    → mở VIPFULL 30 ngày\n"
        "free Uxxxx      → chuyển về FREE\n"
        "inbox           → xem yêu cầu mới\n"
        "reply Q00001 nội dung báo cáo\n"
        "report Q00001 https://link-bao-cao\n"
        "done Q00001     → đánh dấu xong\n"
        "cancel Q00001   → hủy yêu cầu\n"
        "a/b/c https://link → cập nhật link RichMenu A/B/C\n"
        "learn1..learn5 https://link → cập nhật 5 link học tập\n"
        "basiclink https://link → link mua BASIC\n"
        "viplink https://link → link mua VIP\n"
        "support https://link → link CSKH\n"
        "send Uxxxx nội dung → gửi riêng user\n"
        "check           → kiểm tra sheet/env\n"
        "init            → tạo sheet/header\n"
    )

# -------------------------
# Command handling
# -------------------------

def get_request_type_and_coin(text: str) -> Optional[Tuple[str, str]]:
    m = re.match(r"^\s*(tokenomic|tokenomics|signal|session|代幣經濟|技術分析|指標分析|盤勢|交易時段)\s+([A-Za-z0-9._-]{2,20})", text, re.I)
    if not m:
        return None
    raw = m.group(1).lower()
    coin = m.group(2).upper()
    if raw in {"tokenomic", "tokenomics", "代幣經濟"}:
        return "tokenomic", coin
    if raw in {"signal", "技術分析", "指標分析"}:
        return "signal", coin
    return "session", coin


def handle_admin(text: str, user_id: str, display_name: str) -> Optional[str]:
    raw = text.strip()
    if not raw:
        return None
    parts = raw.split()
    low = [p.lower() for p in parts]
    if low and low[0] == "admin":
        parts = parts[1:]
        low = low[1:]
    if not parts:
        return admin_help()

    cmd = low[0]

    if cmd in {"help", "adminhelp", "?"}:
        return admin_help()

    if cmd == "check":
        try:
            info = parse_service_account_json()
            init_ok = bool(spreadsheet())
            return (
                "✅ Check OK\n"
                f"Google JSON: OK\n"
                f"client_email: {info.get('client_email', '')}\n"
                f"GOOGLE_SHEET_ID: {GOOGLE_SHEET_ID}\n"
                f"BOTLIVE_SHEET_NAME: {BOTLIVE_SHEET_NAME}\n"
                f"BotLive: {BOTLIVE_BASE_URL}"
            )
        except Exception as e:
            return f"❌ Check lỗi: {e}"

    if cmd == "init":
        try:
            res = init_sheets()
            return "✅ Đã tạo Google Sheet tabs/header:\n" + ", ".join(res.get("sheets", []))
        except Exception as e:
            return f"❌ Init sheet lỗi: {e}"

    # basic Uxxx 30 / vip Uxxx 30 / free Uxxx
    # add basic Uxxx 30 / set vip Uxxx 30
    plan_cmds = {"basic": "BASIC", "vip": "VIP", "vipfull": "VIP", "free": "FREE"}
    if cmd in {"add", "set", "member"} and len(low) >= 3 and low[1] in plan_cmds:
        plan = plan_cmds[low[1]]
        target = parts[2]
        days = parse_days(parts[3], 30) if len(parts) >= 4 else 30
    elif cmd in plan_cmds and len(parts) >= 2:
        plan = plan_cmds[cmd]
        target = parts[1]
        days = parse_days(parts[2], 30) if len(parts) >= 3 else 30
    else:
        plan = ""
        target = ""
        days = 30

    if plan:
        if not looks_line_user_id(target):
            return "❌ User ID không đúng. Ví dụ: vip Uxxxxxxxx 30"
        try:
            # If target profile cannot be fetched, keep empty name. BotLive still works by line_user_id/token.
            prof = line_profile(target)
            name = prof.get("displayName", "") or target[-8:]
            m = upsert_member(target, name, plan, days, note=f"set by {display_name or user_id}")
            zh = (
                "✅ 會員權限已開通\n"
                f"方案：{PLAN_ZH.get(normalize_plan(plan), plan)}\n"
                f"期限：{s(m.get('expired_at')) or '未設定'}\n"
                f"BotLive：{botlive_url(s(m.get('member_token')))}"
            ) if plan != "FREE" else "您的會員狀態已調整為免費用戶。"
            pushed = push_text(target, zh)
            return (
                "✅ Đã cập nhật member\n"
                f"User: {target}\n"
                f"Name: {name}\n"
                f"Plan: {normalize_plan(plan)}\n"
                f"Bot limit: {bot_limit_for(plan)}\n"
                f"Expired: {s(m.get('expired_at'))}\n"
                f"Token: {s(m.get('member_token'))}\n"
                f"Push khách: {'OK' if pushed else 'FAIL'}"
            )
        except Exception as e:
            return f"❌ Mở quyền lỗi: {e}"

    if cmd in {"inbox", "requests", "q"}:
        try:
            rows = inbox_list(10)
            if not rows:
                return "📭 Chưa có yêu cầu mới."
            lines = ["📩 Yêu cầu mới:"]
            for r in rows:
                lines.append(f"{s(r.get('id'))} | {s(r.get('plan'))} | {s(r.get('request_type'))} {s(r.get('coin'))} | {s(r.get('display_name'))}\nUser: {s(r.get('line_user_id'))}")
            return "\n\n".join(lines)
        except Exception as e:
            return f"❌ Inbox lỗi: {e}"

    if cmd in {"reply", "report"} and len(parts) >= 3:
        qid = parts[1].upper()
        body = raw.split(parts[1], 1)[1].strip()
        if not body:
            return "❌ Thiếu nội dung/link báo cáo."
        try:
            req = inbox_get(qid)
            if not req:
                return f"❌ Không tìm thấy {qid}."
            if cmd == "report":
                url = body
                msg = f"📄 您的 {s(req.get('coin'))} {s(req.get('request_type'))} 報告已完成：\n{url}"
                save_report(req, text="", url=url)
                inbox_update(qid, {"status": "DONE"})
            else:
                msg = f"📄 您的 {s(req.get('coin'))} {s(req.get('request_type'))} 報告已完成：\n\n{body}"
                save_report(req, text=body, url="")
                inbox_update(qid, {"status": "DONE"})
            pushed = push_text(s(req.get("line_user_id")), msg)
            return f"✅ Đã gửi báo cáo {qid}. Push khách: {'OK' if pushed else 'FAIL'}"
        except Exception as e:
            return f"❌ Gửi báo cáo lỗi: {e}"

    if cmd in {"done", "cancel"} and len(parts) >= 2:
        qid = parts[1].upper()
        try:
            ok = inbox_update(qid, {"status": "DONE" if cmd == "done" else "CANCELLED"})
            return f"✅ Đã cập nhật {qid}: {'DONE' if cmd == 'done' else 'CANCELLED'}" if ok else f"❌ Không tìm thấy {qid}."
        except Exception as e:
            return f"❌ Cập nhật yêu cầu lỗi: {e}"

    # a https://... / learn1 https://... / link KEY https://...
    if cmd in {"link"} and len(parts) >= 3:
        key = parts[1]
        url = raw.split(parts[1], 1)[1].strip()
        try:
            res = set_link(key, url)
            return f"✅ Đã cập nhật link\n{res['key']}\n{res['url']}"
        except Exception as e:
            return f"❌ Cập nhật link lỗi: {e}"

    if cmd in SHORT_LINK_KEYS and len(parts) >= 2:
        url = raw.split(parts[0], 1)[1].strip()
        try:
            res = set_link(cmd, url)
            return f"✅ Đã cập nhật link\n{res['key']}\n{res['url']}"
        except Exception as e:
            return f"❌ Cập nhật link lỗi: {e}"

    if cmd == "send" and len(parts) >= 3:
        target = parts[1]
        body = raw.split(parts[1], 1)[1].strip()
        if not looks_line_user_id(target):
            return "❌ User ID không đúng."
        ok = push_text(target, body)
        return f"✅ Send {'OK' if ok else 'FAIL'}"

    return None


def ai_reply(text: str) -> str:
    if not OPENAI_API_KEY or not OpenAI:
        return "AI 服務目前尚未設定，請稍後再試。"
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        system = (
            "你是 Fumap AI 分析助理。使用繁體中文回答台灣用戶。"
            "只做教育與分析，不提供保證獲利。回答要清楚、實用、簡短。"
        )
        if hasattr(client, "responses"):
            resp = client.responses.create(
                model=OPENAI_MODEL,
                input=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                max_output_tokens=OPENAI_MAX_OUTPUT_TOKENS,
            )
            return getattr(resp, "output_text", "") or "AI 回覆失敗，請稍後再試。"
        comp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
            max_tokens=OPENAI_MAX_OUTPUT_TOKENS,
        )
        return comp.choices[0].message.content or "AI 回覆失敗，請稍後再試。"
    except Exception as e:
        print(f"[openai] failed: {e}")
        return "AI 服務暫時無法回覆，請稍後再試。"


def handle_user_text(text: str, user_id: str, reply_token: str) -> str:
    text_stripped = text.strip()
    low = text_stripped.lower()
    profile = line_profile(user_id)
    display_name = profile.get("displayName", "") or user_id[-8:]

    # Admin command first. It must work even when user has no member row.
    if is_admin(user_id):
        admin_res = handle_admin(text_stripped, user_id, display_name)
        if admin_res:
            return admin_res

    # RichMenu aliases: A-F and Chinese labels. Always turns off chatbot.
    rich_alias = {
        "a": "A", "易經": "A", "易經加密分析": "A",
        "b": "B", "技術指標": "B", "技術指標分析": "B", "指標": "B",
        "c": "C", "市場報告": "C", "加密市場報告": "C",
        "d": "D", "會員方案": "D", "方案": "D",
        "e": "E", "使用教學": "E", "教學": "E",
        "f": "F", "客服": "F", "客服中心": "F",
    }
    if text_stripped in {"A", "B", "C", "D", "E", "F"} or low in rich_alias or text_stripped in rich_alias:
        code = rich_alias.get(low) or rich_alias.get(text_stripped) or text_stripped.upper()
        chat_mode(user_id, False)
        return rich_menu_text(code)

    # ID / me
    if low in {"id", "userid", "user id", "我的id", "會員id"}:
        m = get_member(user_id)
        plan = normalize_plan(m.get("plan")) if m else "FREE"
        admin_note = "\n\n📌 Admin copy:\n" + f"vip {user_id} 30\n" + f"basic {user_id} 30" if is_admin(user_id) else ""
        notify_admins(f"🆔 Khách gửi ID\nTên LINE: {display_name}\nUser ID: {user_id}\nPlan hiện tại: {plan}")
        return f"🆔 您的會員開通代碼\nUser ID：{user_id}\nLINE 名稱：{display_name}\n目前狀態：{PLAN_ZH.get(plan, plan)}\n\n請將此代碼傳給客服，以便開通 BASIC / VIPFULL 會員。{admin_note}"

    if low in {"me", "會員", "member"}:
        m = get_member(user_id)
        plan = normalize_plan(m.get("plan")) if m else "FREE"
        if not m:
            return f"目前狀態：免費用戶\nUser ID：{user_id}\n請聯繫客服開通會員。"
        return f"👤 會員狀態\n方案：{PLAN_ZH.get(plan, plan)}\n到期日：{s(m.get('expired_at')) or '未設定'}\nBot 上限：{s(m.get('bot_limit')) or bot_limit_for(plan)}\nBotLive：{botlive_url(s(m.get('member_token')))}"

    # Member commands
    m = get_member(user_id)
    active = is_active_member(m) or is_admin(user_id)
    plan = normalize_plan(m.get("plan")) if m else ("ADMIN" if is_admin(user_id) else "FREE")

    if low in {"botlive", "bot live", "bot"}:
        if not active:
            return member_denied()
        token = s(m.get("member_token")) if m else make_token()
        return f"🤖 BotLive 會員中心\n{botlive_url(token)}\n\n方案：{PLAN_ZH.get(plan, plan)}\nDemo Bot 上限：{bot_limit_for(plan)}\n排行榜：{BOTLIVE_LEADERBOARD_URL}\n公開 Dashboard：{BOTLIVE_DASHBOARD_URL}"

    if low in {"chatbot", "ai", "開始聊天", "開啟聊天"}:
        if not active and not AI_CHAT_ALLOW_FREE:
            return member_denied()
        chat_mode(user_id, True)
        return "✅ AI Chatbot 已開啟。\n您可以直接貼上報告、文字或問題，我會協助解釋。\n若要關閉，請輸入：off chatbot"

    if low in {"off chatbot", "stop chatbot", "關閉聊天", "停止聊天", "退出聊天"}:
        chat_mode(user_id, False)
        return "✅ AI Chatbot 已關閉。"

    req = get_request_type_and_coin(text_stripped)
    if req:
        if not active:
            return member_denied()
        rtype, coin = req
        try:
            q = create_inbox(user_id, display_name, plan, rtype, coin, text_stripped)
            notify_admins(
                f"📩 Yêu cầu phân tích mới\n"
                f"Mã: {q['id']}\nThành viên: {plan}\nLoại: {rtype}\nCoin: {coin}\nTên: {display_name}\nUser: {user_id}\n\n"
                f"Trả lời:\nreply {q['id']} nội dung báo cáo\nreport {q['id']} https://link"
            )
            title = {"tokenomic": "代幣經濟分析", "signal": "技術指標分析", "session": "交易時段報告"}.get(rtype, rtype)
            return f"✅ 已收到您的 {coin} {title} 需求。\n需求編號：{q['id']}\n管理員將進行人工分析，完成後會直接回覆報告給您。"
        except Exception as e:
            return f"系統暫時無法建立需求，請稍後再試。\n錯誤：{e}"

    # If chat mode is ON, route to AI.
    try:
        st = state_get(user_id)
        if s(st.get("chat_mode")).upper() == "ON":
            if not active and not AI_CHAT_ALLOW_FREE:
                chat_mode(user_id, False)
                return member_denied()
            return ai_reply(text_stripped)
    except Exception as e:
        print(f"[state] get failed: {e}")

    return (
        "您好，歡迎使用 Fumap AI 分析。\n"
        "請點選下方 Rich Menu，或輸入以下指令：\n\n"
        "・id：取得會員開通代碼\n"
        "・會員輸入 chatbot：開啟 AI 解釋模式\n"
        "・會員輸入 tokenomic ETH / signal BTC / session SOL：提交人工分析需求\n"
        "・會員輸入 botlive：取得 BotLive 連結"
    )

# -------------------------
# Routes
# -------------------------

@app.get("/")
def home():
    return jsonify({"ok": True, "app": "Fumap LINE Webhook V2 Clean"})


@app.get("/health")
def health():
    return jsonify({"ok": True, "app": "Fumap LINE Webhook V2 Clean", "time": now_tw()})


@app.get("/health/env-check")
def env_check():
    if request.args.get("token") != ADMIN_TOKEN:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    out = {
        "ok": True,
        "LINE_CHANNEL_SECRET_SET": bool(LINE_CHANNEL_SECRET),
        "LINE_CHANNEL_ACCESS_TOKEN_SET": bool(LINE_CHANNEL_ACCESS_TOKEN),
        "ADMIN_LINE_USER_IDS_COUNT": len(ADMIN_LINE_USER_IDS),
        "GOOGLE_SHEET_ID_SET": bool(GOOGLE_SHEET_ID),
        "GOOGLE_SERVICE_ACCOUNT_JSON_SET": bool(GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_JSON_BASE64),
        "BOTLIVE_SHEET_NAME": BOTLIVE_SHEET_NAME,
        "BOTLIVE_BASE_URL": BOTLIVE_BASE_URL,
        "OPENAI_API_KEY_SET": bool(OPENAI_API_KEY),
        "OPENAI_MODEL": OPENAI_MODEL,
    }
    try:
        info = parse_service_account_json()
        out["GOOGLE_SERVICE_ACCOUNT_JSON_VALID"] = True
        out["GOOGLE_CLIENT_EMAIL"] = info.get("client_email", "")
    except Exception as e:
        out["GOOGLE_SERVICE_ACCOUNT_JSON_VALID"] = False
        out["GOOGLE_SERVICE_ACCOUNT_JSON_ERROR"] = str(e)
    try:
        sh = member_ws()
        out["SHEET_CONNECTED"] = True
        out["MEMBER_SHEET_ROWS"] = len(records(sh))
    except Exception as e:
        out["SHEET_CONNECTED"] = False
        out["SHEET_ERROR"] = str(e)
    return jsonify(out)


@app.get("/admin/sheets/init")
def admin_sheets_init():
    if request.args.get("token") != ADMIN_TOKEN:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        return jsonify(init_sheets())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/callback")
def callback():
    body = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")
    if not verify_signature(body, signature):
        return "bad signature", 403
    payload = request.get_json(silent=True) or {}
    for event in payload.get("events", []):
        try:
            if event.get("type") != "message":
                continue
            msg = event.get("message", {})
            if msg.get("type") != "text":
                reply_text(event.get("replyToken", ""), "目前請先傳送文字訊息。")
                continue
            user_id = event.get("source", {}).get("userId", "")
            if not user_id:
                continue
            text = msg.get("text", "")
            ans = handle_user_text(text, user_id, event.get("replyToken", ""))
            reply_text(event.get("replyToken", ""), ans)
        except Exception as e:
            print(f"[callback] event error: {e}")
            reply_text(event.get("replyToken", ""), f"系統暫時發生錯誤，請稍後再試。\n{str(e)[:300]}")
    return "OK", 200


@app.post("/webhook/tradingview")
def tradingview_webhook():
    payload = request.get_json(silent=True) or {}
    secret = s(payload.get("secret") or request.headers.get("X-Webhook-Secret") or request.args.get("secret"))
    if TRADINGVIEW_WEBHOOK_SECRET and secret != TRADINGVIEW_WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "bad secret"}), 401
    forwarded = False
    if BOTLIVE_WEBHOOK_URL:
        try:
            r = requests.post(BOTLIVE_WEBHOOK_URL, json=payload, timeout=8)
            forwarded = r.status_code < 300
        except Exception as e:
            print(f"[tv] forward failed: {e}")
    try:
        sh = ws("TradingViewAlerts", TV_HEADERS)
        rows = records(sh)
        data = {
            "id": make_row_id("TV", len(rows)),
            "source": "TradingView",
            "symbol": s(payload.get("symbol") or payload.get("ticker") or payload.get("pair")),
            "timeframe": s(payload.get("timeframe") or payload.get("tf") or payload.get("interval")),
            "signal": s(payload.get("signal") or payload.get("side") or payload.get("action")),
            "price": s(payload.get("price") or payload.get("close")),
            "bias": s(payload.get("bias") or payload.get("trend")),
            "raw_payload": json.dumps(payload, ensure_ascii=False),
            "forwarded_to_botlive": "TRUE" if forwarded else "FALSE",
            "created_at": now_tw(),
            "active": "TRUE",
        }
        append_dict(sh, data)
    except Exception as e:
        print(f"[tv] sheet log failed: {e}")
    return jsonify({"ok": True, "forwarded_to_botlive": forwarded})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
