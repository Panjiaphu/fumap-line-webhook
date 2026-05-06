import base64
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception as e:
    gspread = None
    Credentials = None
    print(f"[botlive_sync] Google Sheets disabled: {e}")


TW_TZ = timezone(timedelta(hours=8))


def env_raw(name: str, default: str = "") -> str:
    return os.getenv(name, default) or ""


def env_clean(name: str, default: str = "") -> str:
    v = env_raw(name, default).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in {'"', "'"}:
        v = v[1:-1]
    return v.strip()


BOTLIVE_DB_MODE = env_clean("BOTLIVE_DB_MODE", "").lower()
BOTLIVE_SHEET_ID = (
    env_clean("BOTLIVE_DB_SHEET_ID")
    or env_clean("BOTLIVE_SHEET_ID")
    or env_clean("BOTLIVE_CONTENT_SHEET_ID")
)
BOTLIVE_BASE_URL = env_clean("BOTLIVE_BASE_URL", "https://fumap-bot-life.onrender.com").rstrip("/")
BOTLIVE_MEMBER_URL = env_clean("BOTLIVE_MEMBER_URL", f"{BOTLIVE_BASE_URL}/member")
GOOGLE_SERVICE_ACCOUNT_JSON = env_raw("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SERVICE_ACCOUNT_JSON_BASE64 = env_clean("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64", "")

MEMBERS_HEADERS = [
    "member_id", "line_user_id", "display_name", "plan", "plan_label", "status",
    "member_code", "member_token", "bot_limit", "bot_count", "expired_at",
    "created_at", "updated_at", "note",
]
REQUEST_HEADERS = [
    "request_id", "created_at", "line_user_id", "member_id", "member_token",
    "member_name", "plan", "request_type", "symbol", "message", "status",
    "report_url", "admin_reply", "seen_by_member", "updated_at",
]
ADMIN_LOG_HEADERS = ["log_id", "created_at", "admin", "action", "target_type", "target_id", "note"]

PLAN_LIMITS = {"FREE": 0, "BASIC": 1, "VIPFULL": 5, "VIP": 5, "ADMIN": 999}
PLAN_LABELS = {
    "FREE": "FREE｜免費查看",
    "BASIC": "BASIC｜會員基礎方案",
    "VIPFULL": "VIPFULL｜VIP Full 全功能方案",
    "VIP": "VIPFULL｜VIP Full 全功能方案",
    "ADMIN": "ADMIN｜管理員",
}


def now_tw() -> str:
    return datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")


def s(v: Any) -> str:
    return str(v or "").strip()


def clean_url(v: Any) -> str:
    return s(v).replace("\\n", "").replace("\n", "").replace('"', "").strip()


def normalize_plan(plan: Any) -> str:
    raw = s(plan).upper().replace(" ", "").replace("-", "_")
    if raw in {"B", "BASIC", "BASE", "會員", "会员", "基礎", "基础"}:
        return "BASIC"
    if raw in {"V", "VIP", "VIPFULL", "VIP_FULL", "FULL", "PRO", "進階", "进阶"}:
        return "VIPFULL"
    if raw in {"ADMIN", "A", "MANAGER"}:
        return "ADMIN"
    return "FREE"


def bot_limit_for(plan: Any) -> int:
    return PLAN_LIMITS.get(normalize_plan(plan), 0)


def plan_label_for(plan: Any) -> str:
    return PLAN_LABELS.get(normalize_plan(plan), PLAN_LABELS["FREE"])


def make_token() -> str:
    return "fm_" + uuid.uuid4().hex[:24]


def make_member_code() -> str:
    return "FUMA-" + uuid.uuid4().hex[:6].upper()


def botlive_member_url(token: str) -> str:
    return f"{BOTLIVE_MEMBER_URL}?token={token}"


def repair_private_key_newlines(raw: str) -> str:
    pattern = r'("private_key"\s*:\s*")(.*?)("\s*,\s*"client_email")'
    m = re.search(pattern, raw, flags=re.DOTALL)
    if not m:
        return raw
    key_value = m.group(2).replace("\r\n", "\\n").replace("\n", "\\n")
    return raw[:m.start(2)] + key_value + raw[m.end(2):]


def parse_service_account_json() -> Dict[str, Any]:
    if GOOGLE_SERVICE_ACCOUNT_JSON_BASE64:
        b = GOOGLE_SERVICE_ACCOUNT_JSON_BASE64.strip()
        b += "=" * (-len(b) % 4)
        return json.loads(base64.b64decode(b).decode("utf-8"))

    raw = GOOGLE_SERVICE_ACCOUNT_JSON.strip()
    if not raw:
        raise RuntimeError("Missing GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_JSON_BASE64")

    candidates = [raw]
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

    last_error = None
    for c in candidates:
        try:
            obj = json.loads(c)
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
        try:
            obj = json.loads(repair_private_key_newlines(c.encode("utf-8").decode("unicode_escape")))
            if isinstance(obj, dict):
                return obj
        except Exception as e:
            last_error = e

    raise RuntimeError(f"Cannot parse Google service account JSON: {last_error}")


_gc = None
_ss = None


def enabled() -> bool:
    return BOTLIVE_DB_MODE == "google_sheet" and bool(BOTLIVE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON and gspread and Credentials)


def client():
    global _gc
    if _gc:
        return _gc
    if not enabled():
        raise RuntimeError("BotLive Google Sheet sync is not enabled. Need BOTLIVE_DB_MODE=google_sheet and BOTLIVE_SHEET_ID.")
    info = parse_service_account_json()
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    _gc = gspread.authorize(creds)
    return _gc


def spreadsheet():
    global _ss
    if _ss:
        return _ss
    _ss = client().open_by_key(BOTLIVE_SHEET_ID)
    return _ss


def ensure_headers(ws, headers: List[str]) -> None:
    current = ws.row_values(1)
    if not current:
        ws.append_row(headers)
        return
    missing = [h for h in headers if h not in current]
    if missing:
        ws.update("1:1", [current + missing])


def worksheet(name: str, headers: List[str]):
    ss = spreadsheet()
    try:
        sh = ss.worksheet(name)
    except Exception:
        sh = ss.add_worksheet(title=name, rows=1000, cols=max(26, len(headers)))
        sh.append_row(headers)
        return sh
    ensure_headers(sh, headers)
    return sh


def records(sh) -> List[Dict[str, Any]]:
    out = []
    for idx, r in enumerate(sh.get_all_records(), start=2):
        r["_row"] = idx
        out.append(r)
    return out


def update_row(sh, row: int, data: Dict[str, Any]) -> None:
    headers = sh.row_values(1)
    for k, v in data.items():
        if k in headers:
            sh.update_cell(row, headers.index(k) + 1, v)


def append_dict(sh, data: Dict[str, Any]) -> None:
    headers = sh.row_values(1)
    sh.append_row([data.get(h, "") for h in headers], value_input_option="USER_ENTERED")


def next_id(tab: str, key: str, prefix: str) -> str:
    sh = worksheet(tab, ADMIN_LOG_HEADERS if tab == "admin_logs" else REQUEST_HEADERS)
    max_n = 0
    for r in records(sh):
        val = s(r.get(key)).upper()
        if val.startswith(prefix.upper()):
            try:
                max_n = max(max_n, int(val[len(prefix):]))
            except Exception:
                pass
    return f"{prefix.upper()}{max_n + 1:05d}"


def log_admin(action: str, target_type: str = "", target_id: str = "", note: str = "") -> None:
    try:
        sh = worksheet("admin_logs", ADMIN_LOG_HEADERS)
        append_dict(sh, {
            "log_id": next_id("admin_logs", "log_id", "L"),
            "created_at": now_tw(),
            "admin": "line_admin",
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "note": note,
        })
    except Exception as e:
        print(f"[botlive_sync] log_admin failed: {e}")


def find_member(line_user_id: str) -> Optional[Dict[str, Any]]:
    sh = worksheet("members", MEMBERS_HEADERS)
    rows = [r for r in records(sh) if s(r.get("line_user_id")) == s(line_user_id)]
    return rows[-1] if rows else None


def sync_member_to_botlive(
    line_user_id: str,
    display_name: str = "",
    plan: str = "FREE",
    days: int = 30,
    member_token: str = "",
    member_code: str = "",
    note: str = "synced from LINEhook",
) -> Dict[str, Any]:
    """Upsert a member row in BotLive Database V1 members tab."""
    sh = worksheet("members", MEMBERS_HEADERS)
    normalized = normalize_plan(plan)
    now = now_tw()
    expired_at = ""
    if normalized != "FREE":
        expired_at = (datetime.now(TW_TZ) + timedelta(days=max(1, int(days or 30)))).strftime("%Y-%m-%d")

    existing = find_member(line_user_id)
    if existing:
        token = member_token or s(existing.get("member_token")) or make_token()
        code = member_code or s(existing.get("member_code")) or make_member_code()
        member_id = s(existing.get("member_id")) or ("M" + uuid.uuid4().hex[:10].upper())
        data = {
            "member_id": member_id,
            "line_user_id": line_user_id,
            "display_name": display_name or s(existing.get("display_name")),
            "plan": normalized,
            "plan_label": plan_label_for(normalized),
            "status": "ACTIVE" if normalized != "FREE" else "FREE",
            "member_code": code,
            "member_token": token,
            "bot_limit": bot_limit_for(normalized),
            "expired_at": expired_at,
            "updated_at": now,
            "note": note,
        }
        update_row(sh, int(existing["_row"]), data)
        data["_row"] = existing["_row"]
        log_admin("sync_member", "member", line_user_id, f"{normalized} {expired_at}")
        return data

    token = member_token or make_token()
    code = member_code or make_member_code()
    data = {
        "member_id": "M" + uuid.uuid4().hex[:10].upper(),
        "line_user_id": line_user_id,
        "display_name": display_name,
        "plan": normalized,
        "plan_label": plan_label_for(normalized),
        "status": "ACTIVE" if normalized != "FREE" else "FREE",
        "member_code": code,
        "member_token": token,
        "bot_limit": bot_limit_for(normalized),
        "bot_count": 0,
        "expired_at": expired_at,
        "created_at": now,
        "updated_at": now,
        "note": note,
    }
    append_dict(sh, data)
    log_admin("create_member", "member", line_user_id, f"{normalized} {expired_at}")
    return data


def request_rows(status: str = "PENDING", limit: int = 10) -> List[Dict[str, Any]]:
    sh = worksheet("member_requests", REQUEST_HEADERS)
    rows = records(sh)
    if status:
        rows = [r for r in rows if s(r.get("status")).upper() == status.upper()]
    rows.sort(key=lambda r: s(r.get("created_at")), reverse=True)
    return rows[:limit]


def get_request(qid: str) -> Optional[Dict[str, Any]]:
    sh = worksheet("member_requests", REQUEST_HEADERS)
    for r in records(sh):
        if s(r.get("request_id")).upper() == s(qid).upper():
            return r
    return None


def update_request(qid: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sh = worksheet("member_requests", REQUEST_HEADERS)
    row = get_request(qid)
    if not row:
        return None
    payload = {**data, "updated_at": now_tw()}
    update_row(sh, int(row["_row"]), payload)
    row.update(payload)
    log_admin("update_request", "member_request", qid, json.dumps(data, ensure_ascii=False))
    return row


def format_inbox(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "📭 Inbox hiện không có yêu cầu PENDING."
    lines = ["📥 BotLive Member Requests"]
    for r in rows:
        lines.append(
            f"{s(r.get('request_id'))}｜{s(r.get('plan'))}｜{s(r.get('request_type'))}｜{s(r.get('symbol'))}｜{s(r.get('status'))}\n"
            f"會員：{s(r.get('member_name')) or s(r.get('line_user_id'))}\n"
            f"需求：{s(r.get('message'))}"
        )
    return "\n\n".join(lines)


def notify_member_text(row: Dict[str, Any], kind: str, value: str) -> str:
    rid = s(row.get("request_id"))
    rtype = s(row.get("request_type"))
    symbol = s(row.get("symbol"))
    if kind == "report":
        return (
            f"✅ 你的分析報告已完成\n"
            f"✅ Báo cáo phân tích của bạn đã hoàn thành\n\n"
            f"{rid}｜{rtype}｜{symbol}\n"
            f"{value}"
        )
    if kind == "reply":
        return (
            f"✅ 你的分析申請已回覆\n"
            f"✅ Yêu cầu phân tích của bạn đã được phản hồi\n\n"
            f"{rid}｜{rtype}｜{symbol}\n"
            f"{value}"
        )
    return f"{rid}｜{rtype}｜{symbol} 已更新。"


def admin_help_v3() -> str:
    return """🛠 Fumap Admin Help V3

【會員管理】
basic Uxxxx 30
→ Mở BASIC 30 ngày + sync BotLive members

vip Uxxxx 30
→ Mở VIPFULL 30 ngày + sync BotLive members

free Uxxxx
→ Chuyển FREE + sync BotLive members

send Uxxxx nội dung
→ Gửi riêng user

【會員申請分析 / BotLive Requests】
inbox
→ Xem yêu cầu phân tích mới từ Web BotLive

reply Q00001 nội dung
→ Trả lời member bằng LINE + lưu DONE

report Q00001 https://link
→ Gửi link ảnh/tài liệu/báo cáo cho member + lưu DONE

done Q00001
→ Đánh dấu hoàn thành

cancel Q00001
→ Hủy yêu cầu

【RichMenu / LINE 快捷連結 - giữ logic cũ】
a https://link
→ RichMenu A：易經圖片 / ảnh Kinh Dịch

b https://link
→ RichMenu B：TradingView 圖片 / ảnh TradingView

c https://link
→ RichMenu C：交易時段報告 / ảnh báo cáo phiên

⚠️ a/b/c chỉ cập nhật LINE RichMenu, KHÔNG post lên Web BotLive.

【學習與購買連結 - giữ logic cũ】
learn1..learn5 https://link
basiclink https://link
viplink https://link
support https://link

【系統】
check
→ Kiểm tra sheet/env

init
→ Tạo sheet/header nếu thiếu"""


def botlive_health_text() -> str:
    try:
        if not enabled():
            return (
                "BotLive Sync: OFF\n"
                "Cần ENV: BOTLIVE_DB_MODE=google_sheet, BOTLIVE_SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON"
            )
        ss = spreadsheet()
        tabs = [w.title for w in ss.worksheets()]
        return f"BotLive Sync: OK\nSheet: {ss.title}\nTabs: {', '.join(tabs[:12])}"
    except Exception as e:
        return f"BotLive Sync: ERROR\n{e}"


def handle_botlive_admin_command(
    text: str,
    admin_user_id: str = "",
    push_func: Optional[Callable[[str, str], bool]] = None,
) -> Tuple[bool, str]:
    """Return (handled, reply_text). Use inside existing LINE admin command handler."""
    raw = s(text)
    if not raw:
        return False, ""

    parts = raw.split()
    cmd = parts[0].lower()

    if cmd in {"help", "admin", "指令", "lenh", "lệnh"}:
        return True, admin_help_v3()

    if cmd == "botlivecheck":
        return True, botlive_health_text()

    if cmd == "inbox":
        try:
            return True, format_inbox(request_rows("PENDING", 10))
        except Exception as e:
            return True, f"❌ Inbox lỗi: {e}"

    if cmd == "report" and len(parts) >= 3:
        qid = parts[1].upper()
        url = clean_url(parts[2])
        row = get_request(qid)
        if not row:
            return True, f"❌ Không tìm thấy request {qid}"
        updated = update_request(qid, {"report_url": url, "status": "DONE", "seen_by_member": "FALSE"})
        msg = notify_member_text(updated or row, "report", url)
        sent = False
        if push_func and s(row.get("line_user_id")):
            sent = bool(push_func(s(row.get("line_user_id")), msg))
        return True, f"✅ Đã gửi report {qid}\nLINE sent: {sent}\n{url}"

    if cmd == "reply" and len(parts) >= 3:
        qid = parts[1].upper()
        content = raw.split(None, 2)[2].strip()
        row = get_request(qid)
        if not row:
            return True, f"❌ Không tìm thấy request {qid}"
        updated = update_request(qid, {"admin_reply": content, "status": "DONE", "seen_by_member": "FALSE"})
        msg = notify_member_text(updated or row, "reply", content)
        sent = False
        if push_func and s(row.get("line_user_id")):
            sent = bool(push_func(s(row.get("line_user_id")), msg))
        return True, f"✅ Đã reply {qid}\nLINE sent: {sent}"

    if cmd == "done" and len(parts) >= 2:
        qid = parts[1].upper()
        row = update_request(qid, {"status": "DONE", "seen_by_member": "FALSE"})
        if not row:
            return True, f"❌ Không tìm thấy request {qid}"
        return True, f"✅ Đã DONE {qid}"

    if cmd == "cancel" and len(parts) >= 2:
        qid = parts[1].upper()
        row = update_request(qid, {"status": "CANCELLED"})
        if not row:
            return True, f"❌ Không tìm thấy request {qid}"
        return True, f"✅ Đã CANCEL {qid}"

    return False, ""
