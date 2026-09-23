# -*- coding: utf-8 -*-
"""
Вложения WhatsApp в веб-консоли: фото, видео, аудио, голосовое, документ,
стикер скачиваются на диск и отдаются по подписанной ссылке.

Вместо Gupshup — локальный HTTP-сервер внутри этого же контейнера: в вебхуке
передаётся прямая ссылка `url`, и бот качает файл с него (тот же путь кода,
что и с настоящей ссылкой Gupshup).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from sqlalchemy import text as sqltext

BASE = "http://localhost:8000"
API = BASE + "/api/v1/console"
TOKEN = os.getenv("GUPSHUP_VERIFY_TOKEN", "gqgroup_verify")
_res = []


def check(n, c, d=""):
    _res.append((n, bool(c), d))
    print(f"[{'PASS' if c else 'FAIL'}] {n}" + (f"  — {d}" if d else ""))


def section(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def q1(sql, **p):
    from src.db.chat_database import ChatSessionLocal
    s = ChatSessionLocal()
    try:
        return s.execute(sqltext(sql), p).scalar()
    finally:
        s.close()


def wait_for(fn, timeout=30, interval=0.5):
    end = time.time() + timeout
    while time.time() < end:
        r = fn()
        if r:
            return r
        time.sleep(interval)
    return None


# ─── Поддельный «Gupshup» с файлами ─────────────────────────────
# 1x1 PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
FILES = {
    "/photo.png": (PNG, "image/png"),
    "/clip.mp4": (b"\x00\x00\x00\x18ftypmp42" + os.urandom(4000), "video/mp4"),
    "/song.mp3": (b"ID3" + os.urandom(3000), "audio/mpeg"),
    "/voice.ogg": (b"OggS" + os.urandom(2000), "audio/ogg"),
    "/price.pdf": (b"%PDF-1.4\n" + os.urandom(5000), "application/pdf"),
    "/sticker.webp": (b"RIFF\x00\x00\x00\x00WEBPVP8 " + os.urandom(500), "image/webp"),
    "/evil.html": (b"<script>alert(document.cookie)</script>", "text/html"),
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body, ctype = FILES.get(self.path, (None, None))
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 8099), _Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
SRC = "http://127.0.0.1:8099"


def send_media(phone, msg_type, path, *, mime, filename=None, caption="", voice=False):
    wamid = "wamid.MEDIA-" + uuid.uuid4().hex[:12]
    obj = {"id": "media-" + uuid.uuid4().hex[:8], "url": SRC + path, "mime_type": mime}
    if caption:
        obj["caption"] = caption
    if filename:
        obj["filename"] = filename
    if voice:
        obj["voice"] = True
    r = httpx.post(BASE + "/api/v1/whatsapp/webhook", params={"token": TOKEN}, timeout=25, json={
        "entry": [{"changes": [{"field": "messages", "value": {
            "contacts": [{"profile": {"name": "Медиа тест"}, "wa_id": phone}],
            "messages": [{"from": phone, "id": wamid, "type": msg_type, msg_type: obj}]}}]}]})
    return wamid, r.status_code


def auth(t):
    return {"Authorization": f"Bearer {t}"}


PW = "TestPass_media_123"
subprocess.run([sys.executable, "scripts/seed_managers.py", "--code", "director", "--password", PW],
               capture_output=True, cwd="/app")
T = httpx.post(API + "/login", timeout=25, json={"phone": "87710010254", "password": PW}).json()["access_token"]

PHONE = "7701" + str(uuid.uuid4().int)[:7]


def message_by_wamid(wamid):
    return q1("SELECT id FROM chat_messages WHERE external_id = :w", w=wamid)


def api_message(chat_id, msg_id):
    items = httpx.get(f"{API}/chats/{chat_id}/messages", headers=auth(T), timeout=25,
                      params={"limit": 200}).json()["items"]
    return next((m for m in items if m["id"] == msg_id), None)


# ═════════════════════════════════════════════════════════════════
section("1. Каждый тип вложения скачивается и отдаётся")

CASES = [
    ("image", "/photo.png", "image/png", None, "Фото с подписью", False),
    ("video", "/clip.mp4", "video/mp4", None, "", False),
    ("audio", "/song.mp3", "audio/mpeg", None, "", False),
    ("audio", "/voice.ogg", "audio/ogg", None, "", True),
    ("document", "/price.pdf", "application/pdf", "Прайс 2026.pdf", "", False),
    ("sticker", "/sticker.webp", "image/webp", None, "", False),
]

chat_id = None
urls = {}
for msg_type, path, mime, fname, caption, voice in CASES:
    label = f"{msg_type}{' (голосовое)' if voice else ''}"
    wamid, code = send_media(PHONE, msg_type, path, mime=mime, filename=fname, caption=caption, voice=voice)
    check(f"{label}: вебхук принят", code == 200)
    mid = wait_for(lambda: message_by_wamid(wamid), timeout=15)
    check(f"{label}: сообщение сохранено", bool(mid))
    if not mid:
        continue
    chat_id = chat_id or q1("SELECT chat_id FROM chat_messages WHERE id = :i", i=mid)
    m = wait_for(lambda: (lambda x: x if x and x.get("media_url") else None)(api_message(chat_id, mid)), timeout=30)
    check(f"{label}: в API появилась media_url", bool(m), str(m)[:200] if not m else "")
    if not m:
        continue
    check(f"{label}: media_mime = {mime}", m["media_mime"] == mime, m["media_mime"])
    body, _ = FILES[path]
    check(f"{label}: media_size совпадает", m["media_size"] == len(body), f"{m['media_size']} vs {len(body)}")
    r = httpx.get(BASE + m["media_url"], timeout=25)
    check(f"{label}: файл отдаётся 200", r.status_code == 200, str(r.status_code))
    check(f"{label}: содержимое байт-в-байт", r.content == body)
    check(f"{label}: Content-Type {mime}", r.headers.get("content-type", "").startswith(mime),
          r.headers.get("content-type"))
    check(f"{label}: CSP sandbox", r.headers.get("content-security-policy") == "sandbox")
    if caption:
        check(f"{label}: подпись сохранена текстом", m["text"] == caption, str(m["text"]))
    if fname:
        cd = r.headers.get("content-disposition", "")
        check(f"{label}: имя файла в Content-Disposition", "utf-8''" in cd and "inline" in cd, cd)
    rel = q1("SELECT extra->>'media_path' FROM chat_messages WHERE id = :i", i=mid)
    check(f"{label}: файл лежит на диске", rel and Path("/app/media", rel).is_file(), str(rel))
    urls[label] = (mid, m["media_url"])

section("2. Превью в списке чатов и форма extra")
# Сразу после стикера превью перезапишет ответ бота — проверяем саму функцию.
from src.common import chat_store
check("стикер без текста -> «🏷 Стикер»", chat_store._preview(None, "sticker") == "🏷 Стикер")
kinds = q1("SELECT count(*) FROM chat_messages WHERE chat_id = :c AND extra ? 'media_path' "
           "AND jsonb_typeof(extra) = 'object'", c=chat_id)
check("extra с файлом — объект, а не массив", kinds == len(urls), f"{kinds} из {len(urls)}")
any_msg = q1("SELECT id FROM chat_messages WHERE chat_id = :c ORDER BY id LIMIT 1", c=chat_id)
from src.db.chat_database import ChatSessionLocal
_s = ChatSessionLocal()
_s.execute(sqltext("UPDATE chat_messages SET extra = CAST(:e AS jsonb) WHERE id = :i"),
           {"e": '{"button_id": "manager"}', "i": any_msg})
_s.commit()
_s.close()
chat_store.attach_media_sync(any_msg, {"media_path": "x/y.png"})
merged = q1("SELECT extra::text FROM chat_messages WHERE id = :i", i=any_msg)
check("attach_media не затирает прежний extra", '"button_id"' in merged and '"media_path"' in merged, merged)

section("3. Подпись ссылки")
mid, url = urls.get("image", (None, None))
if url:
    base, qs = url.split("?", 1)
    params = dict(p.split("=") for p in qs.split("&"))
    check("без подписи -> 422/404",
          httpx.get(BASE + base, timeout=25).status_code in (404, 422))
    check("подделанная подпись -> 404",
          httpx.get(BASE + base, params={"exp": params["exp"], "sig": "0" * 64}, timeout=25).status_code == 404)
    check("продлённый exp со старой подписью -> 404",
          httpx.get(BASE + base, params={"exp": int(params["exp"]) + 3600, "sig": params["sig"]},
                    timeout=25).status_code == 404)
    other = urls.get("video", (None, None))[0]
    check("подпись от одного сообщения к другому -> 404",
          other and httpx.get(f"{API}/media/{other}", params=params, timeout=25).status_code == 404)
    from src.common import media_store
    past = int(time.time()) - 10
    check("просроченная (но верно подписанная) ссылка -> 404",
          httpx.get(BASE + base, params={"exp": past, "sig": media_store._sign(mid, past)},
                    timeout=25).status_code == 404)

section("4. Перемотка видео (HTTP Range)")
vid = urls.get("video", (None, None))[1]
if vid:
    r = httpx.get(BASE + vid, headers={"Range": "bytes=0-99"}, timeout=25)
    check("Range -> 206 и ровно 100 байт", r.status_code == 206 and len(r.content) == 100,
          f"{r.status_code}, {len(r.content)}")

section("5. Опасный тип только на скачивание")
wamid, _ = send_media(PHONE, "document", "/evil.html", mime="text/html", filename="счёт.html")
mid = wait_for(lambda: message_by_wamid(wamid), timeout=15)
m = mid and wait_for(lambda: (lambda x: x if x and x.get("media_url") else None)(api_message(chat_id, mid)), timeout=30)
if m:
    r = httpx.get(BASE + m["media_url"], timeout=25)
    check("HTML отдаётся как application/octet-stream",
          r.headers.get("content-type", "").startswith("application/octet-stream"), r.headers.get("content-type"))
    check("HTML — attachment, а не inline", r.headers.get("content-disposition", "").startswith("attachment"),
          r.headers.get("content-disposition"))
else:
    check("HTML-документ сохранён", False)

section("6. Файл сохраняется и в перехваченном диалоге")
httpx.post(f"{API}/chats/{chat_id}/takeover", headers=auth(T), json={"force": True}, timeout=25)
wamid, _ = send_media(PHONE, "image", "/photo.png", mime="image/png")
mid = wait_for(lambda: message_by_wamid(wamid), timeout=15)
m = mid and wait_for(lambda: (lambda x: x if x and x.get("media_url") else None)(api_message(chat_id, mid)), timeout=30)
check("фото в перехваченном чате скачано", bool(m))
httpx.post(f"{API}/chats/{chat_id}/release", headers=auth(T), timeout=25)

section("7. Ссылка Gupshup не отвечает — сообщение всё равно в консоли")
wamid, _ = send_media(PHONE, "image", "/missing.png", mime="image/png", caption="битая ссылка")
mid = wait_for(lambda: message_by_wamid(wamid), timeout=15)
check("сообщение сохранено", bool(mid))
time.sleep(4)
m = mid and api_message(chat_id, mid)
check("media_url = None, текст на месте", bool(m) and m["media_url"] is None and m["text"] == "битая ссылка",
      str(m)[:200])

section("8. Дубликат вебхука не качает файл второй раз")
before = sum(1 for _ in Path("/app/media").rglob("*") if _.is_file())
wamid = "wamid.MEDIA-DUP-" + uuid.uuid4().hex[:8]
payload = {"entry": [{"changes": [{"field": "messages", "value": {
    "contacts": [{"profile": {"name": "Медиа тест"}, "wa_id": PHONE}],
    "messages": [{"from": PHONE, "id": wamid, "type": "image",
                  "image": {"id": "dup", "url": SRC + "/photo.png", "mime_type": "image/png"}}]}}]}]}
for _ in range(2):
    httpx.post(BASE + "/api/v1/whatsapp/webhook", params={"token": TOKEN}, json=payload, timeout=25)
wait_for(lambda: q1("SELECT extra->>'media_path' FROM chat_messages WHERE external_id=:w", w=wamid), timeout=30)
time.sleep(3)
after = sum(1 for _ in Path("/app/media").rglob("*") if _.is_file())
check("одно сообщение в БД", q1("SELECT count(*) FROM chat_messages WHERE external_id=:w", w=wamid) == 1)
check("на диске +1 файл, а не +2", after - before == 1, f"{after - before}")

srv.shutdown()
total = len(_res)
failed = [r for r in _res if not r[1]]
print(f"\nИТОГО: {total - len(failed)} PASS, {len(failed)} FAIL")
