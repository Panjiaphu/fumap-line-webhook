"""
Fumap LINEHook Runtime Patch - BotLive Member Request Notify

Add this file at the root of fumap-line-webhook.

It adds an internal endpoint without editing main.py:

GET  /internal/botlive/member-request
POST /internal/botlive/member-request

BotLive calls this endpoint when a member sends:
- TOKENOMIC
- TRADINGVIEW
- SESSION_REPORT

LINEHook then pushes a LINE message to ADMIN_LINE_USER_IDS.

Required Render ENV on fumap-line-webhook:
- LINE_CHANNEL_ACCESS_TOKEN
- ADMIN_LINE_USER_IDS
- BOTLIVE_NOTIFY_SECRET

Required Render ENV on fumap-bot-life:
- LINEHOOK_NOTIFY_URL=https://YOUR-LINEHOOK.onrender.com/internal/botlive/member-request
- BOTLIVE_NOTIFY_SECRET=same value
- BOTLIVE_NOTIFY_ENABLED=true
"""

from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone

try:
    import flask
    from flask import request, jsonify
except Exception:
    flask = None
    request = None
    jsonify = None


TW_TZ = timezone(timedelta(hours=8))


def _env(name: str, default: str = "") -> str:
    try:
        v = str(os.getenv(name, default) or "").strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in {"'", '"'}:
            v = v[1:-1]
        return v.strip()
    except Exception:
        return default


def _env_list(name: str) -> list[str]:
    raw = _env(name, "")
    if not raw and name == "ADMIN_LINE_USER_IDS":
        raw = _env("ADMIN_USER_IDS", "")
    return [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]


def _now_tw() -> str:
    return datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _notify_secret() -> str:
    return _env("BOTLIVE_NOTIFY_SECRET") or _env("LINEHOOK_NOTIFY_SECRET") or _env("ADMIN_TOKEN", "fumap_admin_123")


def _provided_secret() -> str:
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}
    return (
        str(request.headers.get("X-BOTLIVE-NOTIFY-SECRET") or "").strip()
        or str(request.headers.get("X-LINEHOOK-NOTIFY-SECRET") or "").strip()
        or str(data.get("secret") or "").strip()
    )


def _secret_ok() -> bool:
    expected = _notify_secret()
    got = _provided_secret()
    return bool(expected and got and hmac.compare_digest(got, expected))


def _line_headers() -> dict:
    return {
        "Authorization": f"Bearer {_env('LINE_CHANNEL_ACCESS_TOKEN')}",
        "Content-Type": "application/json",
    }


def _line_push(user_id: str, text: str) -> bool:
    token = _env("LINE_CHANNEL_ACCESS_TOKEN")
    if not user_id or not token:
        return False
    try:
        import requests
        r = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers=_line_headers(),
            json={"to": user_id, "messages": [{"type": "text", "text": text[:4900]}]},
            timeout=8,
        )
        if r.status_code >= 300:
            print(f"[linehook_notify] LINE push failed {r.status_code}: {r.text[:300]}")
            return False
        return True
    except Exception as e:
        print(f"[linehook_notify] LINE push exception: {e}")
        return False


def _request_type_label(rt: str) -> str:
    x = str(rt or "").upper()
    if x == "TOKENOMIC":
        return "Tokenomic 代幣經濟"
    if x == "SESSION_REPORT":
        return "Session 報告"
    if x == "TRADINGVIEW":
        return "TradingView 技術分析"
    return x or "Member Request"


def _admin_requests_url() -> str:
    explicit = _env("BOTLIVE_ADMIN_REQUESTS_URL")
    if explicit:
        return explicit
    base = _env("BOTLIVE_BASE_URL", "https://fumap-bot-life.onrender.com").rstrip("/")
    token = _env("BOTLIVE_ADMIN_TOKEN") or _env("ADMIN_TOKEN", "fumap_admin_123")
    # Keep this convenient for admin LINE. User can change ADMIN_TOKEN later.
    return f"{base}/admin/requests?token={token}&lang=zh"


def _build_message(data: dict) -> str:
    request_id = data.get("request_id", "")
    member = data.get("member_name", "") or data.get("display_name", "") or "-"
    plan = data.get("plan", "-")
    rt = _request_type_label(data.get("request_type", ""))
    symbol = data.get("symbol", "-")
    status = data.get("status", "PENDING")
    created = data.get("created_at", "") or _now_tw()
    msg = data.get("message", "")

    return (
        "🔔 BotLive 會員申請通知\n"
        "━━━━━━━━━━━━━━\n"
        f"申請 ID：{request_id}\n"
        f"會員：{member}\n"
        f"方案：{plan}\n"
        f"類型：{rt}\n"
        f"幣種：{symbol}\n"
        f"狀態：{status}\n"
        f"時間：{created}\n"
        f"內容：{msg}\n"
        "\n"
        "請至 Admin Requests 處理：\n"
        f"{_admin_requests_url()}"
    )


def _handle_botlive_member_request_notify():
    if request.method == "GET":
        return jsonify({
            "ok": True,
            "service": "LINEHook BotLive member request notify",
            "url": "/internal/botlive/member-request",
            "admin_count": len(_env_list("ADMIN_LINE_USER_IDS")),
            "secret_required": True,
        })

    if not _secret_ok():
        return jsonify({"ok": False, "error": "invalid secret"}), 401

    data = request.get_json(silent=True) or {}
    admins = _env_list("ADMIN_LINE_USER_IDS")
    if not admins:
        return jsonify({"ok": False, "error": "missing ADMIN_LINE_USER_IDS"}), 500

    text = _build_message(data)
    sent = []
    failed = []
    for uid in admins:
        if _line_push(uid, text):
            sent.append(uid)
        else:
            failed.append(uid)

    return jsonify({
        "ok": bool(sent),
        "sent_count": len(sent),
        "failed_count": len(failed),
        "failed": failed,
        "request_id": data.get("request_id", ""),
    }), 200 if sent else 500


def _install_linehook_internal_notify_route():
    if flask is None:
        return

    original_preprocess_request = flask.Flask.preprocess_request
    if getattr(flask.Flask, "_fumap_notify_route_installed", False):
        return
    flask.Flask._fumap_notify_route_installed = True

    def _patched_preprocess_request(self):
        try:
            path = request.path or ""
            if path.rstrip("/") == "/internal/botlive/member-request":
                return _handle_botlive_member_request_notify()
        except Exception as e:
            try:
                print(f"[linehook_notify] route error: {e}")
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(e)}), 500
        return original_preprocess_request(self)

    flask.Flask.preprocess_request = _patched_preprocess_request
    print("[linehook_notify] internal BotLive notify route installed")


_install_linehook_internal_notify_route()
