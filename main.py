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

try:
    from botlive_sync import (
        handle_botlive_admin_command,
        sync_member_to_botlive,
        botlive_health_text,
    )
except Exception as e:
    handle_botlive_admin_command = None
    sync_member_to_botlive = None
    botlive_health_text = None
    print(f"[startup] BotLive sync disabled: {e}")


# ============================================================
# Fumap LINE Webhook V3 Mobile Safe
# - LINE RichMenu a/b/c giữ logic cũ, không post lên Web BotLive.
# - Member basic/vip/free sync thêm sang BotLive members nếu botlive_sync.py tồn tại.
# - Admin inbox/report/reply/done/cancel đọc/ghi BotLive Sheet mới.
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
    if len(v) >= 2 and v[0] == v[-1] and v[0] in {'"', "'"}:
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
BOTLIVE_DASHBOARD_URL = env_clean("BOTLIVE_DASHBOARD_URL", f"{BOTLIVE_BASE_URL}/battle").replace("\\n", "").replace("\n", "").strip()
BOTLIVE_LEADERBOARD_URL = env_clean("BOTLIVE_LEADERBOARD_URL", f"{BOTLIVE_BASE_URL}/battle").replace("\\n", "").replace("\n", "").strip()
BOTLIVE_WEBHOOK_URL = env_clean("BOTLIVE_WEBHOOK_URL", f"{BOTLIVE_BASE_URL}/webhook/tradingview").replace("\\n", "").replace("\n", "").strip()

OPENAI_API_KEY = env_clean("OPENAI_API_KEY")
OPENAI_MODEL = env_clean("OPENAI_MODEL", "gpt-5-mini")
OPENAI_MAX_OUTPUT_TOKENS = env_int("OPENAI_MAX_OUTPUT_TOKENS", 1200)
OPENAI_WEB_SEARCH = env_bool("OPENAI_WEB_SEARCH", False)
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
    ["A_LATEST_URL", "今日易經加密分析", "", "RichMenu A｜ảnh Kinh Dịch", ""],
    ["B_LATEST_URL", "最新技術指標分析", "", "RichMenu B｜ảnh TradingView", ""],
    ["C_LATEST_URL", "今日加密市場報告", "", "RichMenu C｜ảnh báo cáo phiên", ""],
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

PLAN_LIMIT = {"FREE": 0, "BASIC": 1, "VIP": 5, "VIPFULL": 5, "ADMIN": 999}
PLAN_ZH = {"FREE": "免費用戶", "BASIC": "BASIC 會員", "VIP": "VIPFULL 會員", "VIPFULL": "VIPFULL 會員", "ADMIN": "管理員"}

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


def normalize_coin(v: str) -> str:
    coin = s(v).upper().replace("/", "").replace("-", "").replace(" ", "")
    if coin.endswith("USDT"):
        coin = coin[:-4]
    return coin or "BTC"


def normalize_request_type(v: str) -> str:
    raw = s(v).lower()
    if raw in {"tokenomic", "tokenomics", "token", "tokennomic"}:
        return "TOKENOMIC"
    if raw in {"session", "senssion", "bao", "report", "market"}:
        return "SESSION_REPORT"
    return "TRADINGVIEW"


def repair_private_key_newlines(raw: str) -> str:
    pattern = r'("private_key"\s*:\s*")(.*?)("\s*,\s*"client_email")'
    m = re.search(pattern, raw, flags=re.DOTALL)
    if not m:
        return raw
    key_value = m.group(2)
    key_value = key_value.replace("\r\n", "\\n").replace("\n", "\\n")
    return raw[:m.start(2)] + key_value + raw[m.end(2):]


def parse_service_account_json() -> Dict[str, Any]:
    if GOOGLE_SERVICE_ACCOUNT_JSON_BASE64:
        b = GOOGLE_SERVICE_ACCOUNT_JSON_BASE64.strip()
        b += "=" * (-len(b) % 4)
        return json.loads(base64.b64decode(b).decode("utf-8"))

    raw = GOOGLE_SERVICE_ACCOUNT_JSON.strip()
    if not raw:
        raise RuntimeError("Missing GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_JSON_BASE64")

    candidates: List[str] = [raw]
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        candidates.append(raw[1:-1])

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
        try:
            unescaped = c.encode("utf-8").decode("unicode_escape")
            obj = json.loads(repair_private_key_newlines(unescaped))
            if isinstance(obj, dict):
                return obj
        except Exception as e:
            last_error = e
        try:
            obj = json.loads(repair_private_key_newlines(c))
            if isinstance(obj, dict):
                return obj
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


def ensure_headers(ws_obj, headers: List[str]) -> None:
    existing = ws_obj.row_values(1)
    if not existing:
        ws_obj.append_row(headers)
        return
    missing = [h for h in headers if h not in existing]
    if missing:
        ws_obj.update("1:1", [existing + missing])


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
# Member / content / inbox legacy sheet
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
            try:
                if sync_member_to_botlive:
                    sync_member_to_botlive(
                        line_user_id=line_user_id,
                        display_name=data.get("display_name", ""),
                        plan="VIPFULL" if data.get("plan") == "VIP" else data.get("plan", plan),
                        days=days,
                        member_token=data.get("member_token", ""),
                        note="synced from LINEhook admin command",
                    )
            except Exception as e:
                print(f"[botlive_sync] sync member failed: {e}")
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
    try:
        if sync_member_to_botlive:
            sync_member_to_botlive(
                line_user_id=line_user_id,
                display_name=data.get("display_name", ""),
                plan="VIPFULL" if data.get("plan") == "VIP" else data.get("plan", plan),
                days=days,
                member_token=data.get("member_token", ""),
                note="synced from LINEhook admin command",
            )
    except Exception as e:
        print(f"[botlive_sync] sync member failed: {e}")
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
        return "📊 技術指標分析\n\n" + "\n\n".join([
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
        buy = [
            fmt_link(links.get("PLAN_BASIC_URL", {}).get("title_zh", "BASIC 會員購買連結"), links.get("PLAN_BASIC_URL", {}).get("url", "")),
            fmt_link(links.get("PLAN_VIP_URL", {}).get("title_zh", "VIPFULL 會員購買連結"), links.get("PLAN_VIP_URL", {}).get("url", "")),
            fmt_link(links.get("SUPPORT_URL", {}).get("title_zh", "聯繫客服"), links.get("SUPPORT_URL", {}).get("url", "")),
        ]
        return "💎 會員方案 / 課程連結\n\n" + "\n\n".join(learn + buy)
    if code == "E":
        return (
            "📘 使用教學\n\n"
            "1. 輸入 id：查看你的會員狀態與 BotLive 連結\n"
            "2. 輸入 chatbot：開啟 AI 對話模式\n"
            "3. 輸入 stop / exit：關閉 AI 對話模式\n"
            "4. Web BotLive 會員中心可建立 Demo Bot、送出分析申請、查看通知。\n\n"
            + fmt_link("BotLive Demo Bot 教學", links.get("BOTLIVE_GUIDE_URL", {}).get("url", ""))
        )
    return "請點選 RichMenu，或輸入 id 查看會員狀態。"


def member_status_text(line_user_id: str, display_name: str = "") -> str:
    m = get_member(line_user_id)
    if not m:
        return (
            "🪪 會員狀態\n\n"
            f"LINE ID:\n{line_user_id}\n\n"
            "目前尚未開通 BASIC / VIPFULL。\n請把上面的 LINE ID 傳給管理員開通。"
        )

    token = s(m.get("member_token")) or make_token()
    plan = normalize_plan(m.get("plan"))
    text = (
        "🪪 會員中心\n\n"
        f"名稱：{s(m.get('display_name')) or display_name or '-'}\n"
        f"方案：{PLAN_ZH.get(plan, plan)}\n"
        f"狀態：{s(m.get('status')) or '-'}\n"
        f"到期：{s(m.get('expired_at')) or '-'}\n"
        f"Bot 上限：{s(m.get('bot_limit')) or bot_limit_for(plan)}\n\n"
        f"BotLive Member Center:\n{botlive_url(token)}"
    )
    return text


def ai_system_prompt(member: Optional[Dict[str, Any]]) -> str:
    plan = normalize_plan(member.get("plan") if member else "FREE")
    return (
        "你是 Fumap BotLive 的加密市場助理。"
        "使用繁體中文回答，必要時補充越南語。"
        "回答要務實，重視風險控管，不承諾穩賺。"
        f"會員方案：{plan}。"
    )


def call_openai_chat(line_user_id: str, user_text: str, member: Optional[Dict[str, Any]]) -> str:
    if not OpenAI or not OPENAI_API_KEY:
        return "AI 尚未啟用，請稍後再試。"

    st = state_get(line_user_id)
    today = today_tw()
    daily = int(float(st.get("daily_ai_count") or 0)) if s(st.get("ai_count_date")) == today else 0
    active = is_active_member(member)
    limit = AI_DAILY_LIMIT_ACTIVE if active else AI_DAILY_LIMIT_FREE

    if not active and not AI_CHAT_ALLOW_FREE:
        return member_denied()
    if daily >= limit:
        return f"今日 AI 使用次數已達上限：{limit} 次。"

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": ai_system_prompt(member)},
                {"role": "user", "content": user_text[:3500]},
            ],
            max_tokens=OPENAI_MAX_OUTPUT_TOKENS,
        )
        answer = resp.choices[0].message.content or "AI 無回覆。"
        state_update(line_user_id, {"daily_ai_count": daily + 1, "ai_count_date": today, "last_ai_at": now_tw()})
        return answer[:4900]
    except Exception as e:
        print(f"[openai] error: {e}")
        return f"AI 回覆失敗：{e}"


# -------------------------
# Admin commands
# -------------------------

def admin_help_legacy() -> str:
    if handle_botlive_admin_command:
        try:
            handled, text = handle_botlive_admin_command("help", "", push_text)
            if handled:
                return text
        except Exception:
            pass

    return (
        "🛠 Fumap Admin Help V3\n\n"
        "basic Uxxxx 30 → mở BASIC 30 ngày\n"
        "vip Uxxxx 30 → mở VIPFULL 30 ngày\n"
        "free Uxxxx → chuyển FREE\n"
        "inbox → xem request BotLive\n"
        "report Q00001 https://link → gửi link báo cáo\n"
        "reply Q00001 nội dung → trả lời member\n"
        "done Q00001 → hoàn thành\n"
        "cancel Q00001 → hủy\n"
        "a/b/c https://link → cập nhật LINE RichMenu, không post Web BotLive\n"
        "learn1..learn5 https://link\nbasiclink/viplink/support https://link\n"
        "send Uxxxx nội dung\ncheck\ninit"
    )


def handle_admin_command(line_user_id: str, reply_token: str, text: str) -> bool:
    raw = s(text)
    if not raw:
        return False

    # 1) BotLive commands first: help, inbox, report, reply, done, cancel, botlivecheck
    if handle_botlive_admin_command:
        try:
            handled, admin_reply = handle_botlive_admin_command(raw, line_user_id, push_text)
            if handled:
                reply_text(reply_token, admin_reply)
                return True
        except Exception as e:
            reply_text(reply_token, f"❌ BotLive command error: {e}")
            return True

    parts = raw.split()
    cmd = parts[0].lower()

    if cmd in {"help", "admin", "指令", "lenh", "lệnh"}:
        reply_text(reply_token, admin_help_legacy())
        return True

    if cmd == "init":
        try:
            result = init_sheets()
            reply_text(reply_token, "✅ Init OK\n" + json.dumps(result, ensure_ascii=False))
        except Exception as e:
            reply_text(reply_token, f"❌ Init lỗi: {e}")
        return True

    if cmd == "check":
        lines = [
            "✅ Fumap LINEhook Check",
            f"GOOGLE_SHEET_ID: {'OK' if GOOGLE_SHEET_ID else 'MISSING'}",
            f"LINE token: {'OK' if LINE_CHANNEL_ACCESS_TOKEN else 'MISSING'}",
            f"Admin IDs: {len(ADMIN_LINE_USER_IDS)}",
            f"BOTLIVE_BASE_URL: {BOTLIVE_BASE_URL}",
            f"BOTLIVE_MEMBER_URL: {BOTLIVE_MEMBER_URL}",
        ]
        if botlive_health_text:
            try:
                lines.append("")
                lines.append(botlive_health_text())
            except Exception as e:
                lines.append(f"BotLive Sync Error: {e}")
        reply_text(reply_token, "\n".join(lines))
        return True

    if cmd in SHORT_LINK_KEYS and len(parts) >= 2:
        # Important: a/b/c/learn/basiclink/viplink/support only update LINEhook ContentLinks.
        try:
            url = clean_url(parts[1])
            result = set_link(cmd, url)
            note = ""
            if cmd in {"a", "b", "c"}:
                note = "\n\n⚠️ Lưu ý: lệnh a/b/c chỉ cập nhật LINE RichMenu, KHÔNG post lên Web BotLive."
            reply_text(reply_token, f"✅ Đã cập nhật {cmd} → {result.get('key')}\n{url}{note}")
        except Exception as e:
            reply_text(reply_token, f"❌ Cập nhật link lỗi: {e}")
        return True

    if cmd in {"basic", "vip", "vipfull"} and len(parts) >= 2:
        uid = parts[1]
        if not looks_line_user_id(uid):
            reply_text(reply_token, "❌ Sai LINE user id. Ví dụ: basic Uxxxx 30")
            return True
        days = parse_days(parts[2], 30) if len(parts) >= 3 else 30
        profile = line_profile(uid)
        name = profile.get("displayName", "")
        plan = "VIP" if cmd in {"vip", "vipfull"} else "BASIC"
        try:
            data = upsert_member(uid, name, plan, days, note=f"admin {line_user_id}")
            token = s(data.get("member_token"))
            push_text(uid, (
                f"✅ 會員方案已開通\n\n"
                f"方案：{PLAN_ZH.get(normalize_plan(plan), plan)}\n"
                f"期限：{days} 天\n"
                f"到期：{s(data.get('expired_at'))}\n\n"
                f"BotLive Member Center:\n{botlive_url(token)}"
            ))
            reply_text(reply_token, (
                f"✅ Đã mở {plan} {days} ngày\n"
                f"User: {uid}\n"
                f"Name: {name or '-'}\n"
                f"BotLive: {botlive_url(token)}\n"
                f"Đã sync BotLive members nếu botlive_sync hoạt động."
            ))
        except Exception as e:
            reply_text(reply_token, f"❌ Mở member lỗi: {e}")
        return True

    if cmd == "free" and len(parts) >= 2:
        uid = parts[1]
        if not looks_line_user_id(uid):
            reply_text(reply_token, "❌ Sai LINE user id. Ví dụ: free Uxxxx")
            return True
        try:
            profile = line_profile(uid)
            name = profile.get("displayName", "")
            data = upsert_member(uid, name, "FREE", 1, note=f"admin {line_user_id}")
            push_text(uid, "ℹ️ 你的會員方案已調整為 FREE。")
            reply_text(reply_token, f"✅ Đã chuyển FREE\nUser: {uid}\nĐã sync BotLive members nếu botlive_sync hoạt động.")
        except Exception as e:
            reply_text(reply_token, f"❌ Free lỗi: {e}")
        return True

    if cmd == "send" and len(parts) >= 3:
        uid = parts[1]
        msg = raw.split(None, 2)[2]
        if not looks_line_user_id(uid):
            reply_text(reply_token, "❌ Sai LINE user id. Ví dụ: send Uxxxx nội dung")
            return True
        ok = push_text(uid, msg)
        reply_text(reply_token, f"✅ Sent: {ok}")
        return True

    # Legacy AdminInbox commands, keep for old request flow.
    if cmd == "oldinbox":
        try:
            rows = inbox_list(10)
            if not rows:
                reply_text(reply_token, "📭 Old AdminInbox hiện trống.")
            else:
                lines = ["📥 Old AdminInbox"]
                for r in rows:
                    lines.append(f"{s(r.get('id'))}｜{s(r.get('plan'))}｜{s(r.get('request_type'))}｜{s(r.get('coin'))}｜{s(r.get('status'))}")
                reply_text(reply_token, "\n".join(lines))
        except Exception as e:
            reply_text(reply_token, f"❌ Old inbox lỗi: {e}")
        return True

    return False


# -------------------------
# User commands
# -------------------------

def handle_member_request(line_user_id: str, display_name: str, text: str) -> Optional[str]:
    raw = s(text)
    parts = raw.split()
    if len(parts) < 2:
        return None

    cmd = parts[0].lower()
    if cmd not in {"tokenomic", "tokenomics", "tokennomic", "tradingview", "traddingview", "signal", "session", "senssion", "report"}:
        return None

    member = get_member(line_user_id)
    if not is_active_member(member):
        return member_denied()

    coin = normalize_coin(parts[1])
    rtype = normalize_request_type(cmd)
    plan = normalize_plan(member.get("plan") if member else "FREE")
    req = create_inbox(line_user_id, display_name, plan, rtype, coin, raw)

    notify_admins(
        "📩 Yêu cầu phân tích mới từ LINE\n"
        f"{req.get('id')}｜{plan}｜{rtype}｜{coin}\n"
        f"User: {display_name}\n"
        f"LINE ID: {line_user_id}"
    )

    return (
        "✅ 已收到你的分析申請\n"
        "✅ Đã nhận yêu cầu phân tích của bạn\n\n"
        f"編號：{req.get('id')}\n"
        f"類型：{rtype}\n"
        f"幣種：{coin}\n\n"
        "管理員完成後會透過 LINE 傳送報告。"
    )


def handle_user_text(line_user_id: str, reply_token: str, text: str, display_name: str = "") -> None:
    raw = s(text)
    lower = raw.lower().strip()

    if lower in {"a", "易經", "易經加密分析"}:
        reply_text(reply_token, rich_menu_text("A"))
        return
    if lower in {"b", "技術", "技術指標", "tradingview"}:
        reply_text(reply_token, rich_menu_text("B"))
        return
    if lower in {"c", "市場", "報告", "session"}:
        reply_text(reply_token, rich_menu_text("C"))
        return
    if lower in {"d", "會員", "方案", "課程"}:
        reply_text(reply_token, rich_menu_text("D"))
        return
    if lower in {"e", "教學", "使用教學", "help"}:
        reply_text(reply_token, rich_menu_text("E"))
        return

    if lower in {"id", "會員中心", "member", "botlive"}:
        reply_text(reply_token, member_status_text(line_user_id, display_name))
        return

    if lower in {"chatbot", "ai", "聊天"}:
        m = get_member(line_user_id)
        if not is_active_member(m) and not AI_CHAT_ALLOW_FREE:
            reply_text(reply_token, member_denied())
            return
        chat_mode(line_user_id, True)
        reply_text(reply_token, "✅ AI 對話模式已開啟。\n輸入 stop / exit 可關閉。")
        return

    if lower in {"stop", "exit", "關閉", "关闭"}:
        chat_mode(line_user_id, False)
        reply_text(reply_token, "✅ AI 對話模式已關閉。")
        return

    req_text = handle_member_request(line_user_id, display_name, raw)
    if req_text:
        reply_text(reply_token, req_text)
        return

    try:
        st = state_get(line_user_id)
        if s(st.get("chat_mode")).upper() == "ON":
            m = get_member(line_user_id)
            reply_text(reply_token, call_openai_chat(line_user_id, raw, m))
            return
    except Exception as e:
        print(f"[state/ai] error: {e}")

    reply_text(reply_token, "請點選下方 RichMenu，或輸入 id 查看會員中心。\nMuốn trò chuyện AI, nhập: chatbot")


# -------------------------
# TradingView bridge
# -------------------------

def save_tv_alert(payload: Dict[str, Any], forwarded: bool) -> None:
    try:
        sh = ws("TradingViewAlerts", TV_HEADERS)
        rows = records(sh)
        data = {
            "id": make_row_id("TV", len(rows)),
            "source": "tradingview",
            "symbol": s(payload.get("symbol") or payload.get("ticker") or payload.get("tickerid") or ""),
            "timeframe": s(payload.get("timeframe") or payload.get("interval") or ""),
            "signal": s(payload.get("signal") or payload.get("action") or payload.get("main_signal") or ""),
            "price": s(payload.get("price") or payload.get("close") or ""),
            "bias": s(payload.get("bias") or payload.get("side") or ""),
            "raw_payload": json.dumps(payload, ensure_ascii=False)[:45000],
            "forwarded_to_botlive": "TRUE" if forwarded else "FALSE",
            "created_at": now_tw(),
            "active": "TRUE",
        }
        append_dict(sh, data)
    except Exception as e:
        print(f"[tv] save alert failed: {e}")


def forward_to_botlive(payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not BOTLIVE_WEBHOOK_URL:
        return False, "missing BOTLIVE_WEBHOOK_URL"
    try:
        r = requests.post(BOTLIVE_WEBHOOK_URL, json=payload, timeout=12)
        return r.status_code < 300, f"{r.status_code}: {r.text[:500]}"
    except Exception as e:
        return False, str(e)


# -------------------------
# Flask routes
# -------------------------

@app.get("/")
def home():
    return jsonify({"ok": True, "service": "Fumap LINE Webhook V3 Mobile Safe", "time": now_tw()})


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "fumap-line-webhook",
        "mode": "V3_MOBILE_SAFE_BOTLIVE_SYNC",
        "time": now_tw(),
        "google_sheet_id": bool(GOOGLE_SHEET_ID),
        "line_token": bool(LINE_CHANNEL_ACCESS_TOKEN),
        "admin_count": len(ADMIN_LINE_USER_IDS),
        "botlive_base_url": BOTLIVE_BASE_URL,
        "botlive_sync_loaded": bool(handle_botlive_admin_command),
    })


@app.get("/admin/check")
def admin_check_http():
    token = request.args.get("token") or request.headers.get("X-ADMIN-TOKEN")
    if token != ADMIN_TOKEN:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    result = {
        "ok": True,
        "time": now_tw(),
        "google_sheet_id": GOOGLE_SHEET_ID,
        "botlive_base_url": BOTLIVE_BASE_URL,
        "botlive_sync_loaded": bool(handle_botlive_admin_command),
    }
    if botlive_health_text:
        try:
            result["botlive_sync"] = botlive_health_text()
        except Exception as e:
            result["botlive_sync_error"] = str(e)
    return jsonify(result)


@app.post("/webhook/tradingview")
def tradingview_webhook():
    try:
        if TRADINGVIEW_WEBHOOK_SECRET:
            got = request.headers.get("X-Webhook-Secret") or request.args.get("secret") or request.json.get("secret") if request.is_json else ""
            if got != TRADINGVIEW_WEBHOOK_SECRET:
                return jsonify({"ok": False, "error": "bad secret"}), 401

        payload = request.get_json(silent=True) if request.is_json else None
        if not payload:
            raw = request.get_data(as_text=True) or "{}"
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"text": raw}

        ok, detail = forward_to_botlive(payload)
        save_tv_alert(payload, ok)
        return jsonify({"ok": ok, "forwarded_to_botlive": ok, "detail": detail})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/callback")
def callback():
    body = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")
    if not verify_signature(body, signature):
        return jsonify({"ok": False, "error": "invalid signature"}), 403

    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        data = {}

    for event in data.get("events", []):
        try:
            if event.get("type") != "message":
                continue
            msg = event.get("message") or {}
            if msg.get("type") != "text":
                continue

            reply_token = event.get("replyToken", "")
            source = event.get("source") or {}
            line_user_id = source.get("userId", "")
            text = msg.get("text", "")
            profile = line_profile(line_user_id)
            display_name = profile.get("displayName", "")

            if is_admin(line_user_id):
                handled = handle_admin_command(line_user_id, reply_token, text)
                if handled:
                    continue

            handle_user_text(line_user_id, reply_token, text, display_name)

        except Exception as e:
            print(f"[callback] event error: {e}")
            try:
                reply_text(event.get("replyToken", ""), f"系統處理失敗：{e}")
            except Exception:
                pass

    return jsonify({"ok": True})


# LINE console often uses /webhook; keep alias.
@app.post("/webhook")
def webhook_alias():
    return callback()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(env_clean("PORT", "5000")), debug=DEV_ALLOW_ALL)
