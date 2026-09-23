# -*- coding: utf-8 -*-
"""
Отправка файлов менеджером из консоли клиенту (POST /console/chats/{id}/reply-file).

Сквозная часть идёт через живой API в режиме WHATSAPP_DRY_RUN=true (Gupshup не
вызывается, сообщение пишется в консоль). Формат запроса к самому Gupshup
проверяется отдельно: в этом процессе вызывается wa._send_whatsapp_media с
выключенным dry-run и адресом Gupshup, подменённым на локальный сервер.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

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


def auth(t):
    return {"Authorization": f"Bearer {t}"}


PW = "TestPass_send_123"
for code in ("director", "kalbaeva"):
    subprocess.run([sys.executable, "scripts/seed_managers.py", "--code", code, "--password", PW],
                   capture_output=True, cwd="/app")
T = httpx.post(API + "/login", timeout=25, json={"phone": "87710010254", "password": PW}).json()["access_token"]
T2 = httpx.post(API + "/login", timeout=25, json={"phone": "87750866676", "password": PW}).json()["access_token"]
DIRECTOR_ID = q1("SELECT id FROM managers WHERE code='director'")


def new_chat():
    phone = "7702" + str(uuid.uuid4().int)[:7]
    httpx.post(BASE + "/api/v1/whatsapp/webhook", params={"token": TOKEN}, timeout=25, json={
        "entry": [{"changes": [{"field": "messages", "value": {
            "contacts": [{"profile": {"name": "Отправка файлов"}, "wa_id": phone}],
            "messages": [{"from": phone, "id": "wamid." + uuid.uuid4().hex[:12], "type": "text",
                          "text": {"body": "Пришлите прайс"}}]}}]}]})
    for _ in range(40):
        cid = q1("SELECT id FROM chats WHERE external_id = :p", p=phone)
        if cid:
            return cid, phone
        time.sleep(0.25)
    raise RuntimeError("чат не создан")


def send_file(chat_id, name, data, mime, caption="", token=None):
    return httpx.post(f"{API}/chats/{chat_id}/reply-file", headers=auth(token or T), timeout=60,
                      files={"file": (name, data, mime)}, data={"caption": caption, "take_over": "true"})


PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)

# ═════════════════════════════════════════════════════════════════
section("1. Доступ")
cid, phone = new_chat()
r = httpx.post(f"{API}/chats/{cid}/reply-file", timeout=25, files={"file": ("a.png", PNG, "image/png")})
check("без входа -> 401", r.status_code == 401, str(r.status_code))

section("2. Фото с подписью")
r = send_file(cid, "фото товара.png", PNG, "image/png", caption="Вот так выглядит")
check("200", r.status_code == 200, r.text[:200])
body = r.json() if r.status_code == 200 else {}
m = body.get("message") or {}
check("msg_type = image", m.get("msg_type") == "image", str(m.get("msg_type")))
check("автор — менеджер", m.get("author") == "manager" and m.get("author_manager_name"))
check("подпись сохранена в тексте", m.get("text") == "Вот так выглядит", str(m.get("text")))
check("media_url выдан", bool(m.get("media_url")))
if m.get("media_url"):
    f = httpx.get(BASE + m["media_url"], timeout=25)
    check("файл отдаётся консоли байт-в-байт", f.status_code == 200 and f.content == PNG)
check("диалог перехвачен этим менеджером",
      body.get("chat", {}).get("is_taken_over") and q1("SELECT taken_over_by_id FROM chats WHERE id=:c", c=cid) == DIRECTOR_ID)
check("системное «подключился» записано",
      q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='system' AND text LIKE '%подключился%'", c=cid) == 1)

section("3. Документ: подпись уходит отдельным сообщением")
PDF = b"%PDF-1.4\n" + os.urandom(3000)
r = send_file(cid, "Прайс-лист.pdf", PDF, "application/pdf", caption="Актуальный прайс")
m = r.json().get("message") or {}
check("200 и msg_type = document", r.status_code == 200 and m.get("msg_type") == "document", str(m.get("msg_type")))
check("имя файла сохранено", m.get("file_name") == "Прайс-лист.pdf", str(m.get("file_name")))
check("у самого файла текста нет", not m.get("text"))
last_text = q1("SELECT text FROM chat_messages WHERE chat_id=:c AND author='manager' ORDER BY id DESC LIMIT 1", c=cid)
check("подпись — следующим текстовым сообщением менеджера", last_text == "Актуальный прайс", str(last_text))

section("4. Классификация по типу")
for name, data, mime, expected in [
    ("song.mp3", b"ID3" + os.urandom(500), "audio/mpeg", "audio"),
    ("clip.mp4", b"\x00\x00\x00\x18ftypmp42" + os.urandom(500), "video/mp4", "video"),
    ("договор.docx", b"PK\x03\x04" + os.urandom(500), "application/octet-stream", "document"),
    ("sticker.webp", b"RIFF" + os.urandom(100), "image/webp", "document"),
]:
    r = send_file(cid, name, data, mime)
    got = (r.json().get("message") or {}).get("msg_type") if r.status_code == 200 else r.status_code
    check(f"{name} -> {expected}", got == expected, str(got))

section("5. Отказы")
cid2, _ = new_chat()
big = PNG + b"\x00" * (5 * 1024 * 1024 + 10)
r = send_file(cid2, "big.png", big, "image/png")
check("фото > 5 МБ -> 413", r.status_code == 413, str(r.status_code))
check("  и диалог НЕ перехвачен", not q1("SELECT is_taken_over FROM chats WHERE id=:c", c=cid2))
r = send_file(cid2, "empty.pdf", b"", "application/pdf")
check("пустой файл -> 400", r.status_code == 400, str(r.status_code))
r = send_file(cid, "x.png", PNG, "image/png", token=T2)
check("чат ведёт другой менеджер -> 409", r.status_code == 409, str(r.status_code))
r = send_file(cid2, "../../etc/passwd.pdf", b"%PDF" + os.urandom(100), "application/pdf")
fn = (r.json().get("message") or {}).get("file_name") if r.status_code == 200 else None
check("путь в имени файла отрезан", fn == "passwd.pdf", str(fn))
r = httpx.post(f"{API}/chats/999999999/reply-file", headers=auth(T), timeout=25,
               files={"file": ("a.png", PNG, "image/png")})
check("несуществующий чат -> 404", r.status_code == 404, str(r.status_code))

section("6. Ссылка для Gupshup (/media-out)")
from src.common import media_store
rel = q1("SELECT extra->>'media_path' FROM chat_messages WHERE chat_id=:c AND msg_type='image' "
         "AND author='manager' ORDER BY id LIMIT 1", c=cid)
url = media_store.signed_path_url(rel)
r = httpx.get(BASE + url, timeout=25)
check("подписанная ссылка -> 200 и те же байты", r.status_code == 200 and r.content == PNG, str(r.status_code))
check("Content-Type image/png (WhatsApp проверяет тип)", r.headers.get("content-type") == "image/png",
      r.headers.get("content-type"))
exp = int(time.time()) + 600
check("чужая подпись -> 404",
      httpx.get(f"{API}/media-out", params={"p": rel, "exp": exp, "sig": "0" * 64}, timeout=25).status_code == 404)
evil = "../../../etc/passwd"
check("выход за MEDIA_DIR даже с верной подписью -> 404",
      httpx.get(f"{API}/media-out", params={"p": evil, "exp": exp, "sig": media_store._sign_path(evil, exp)},
                timeout=25).status_code == 404)
past = int(time.time()) - 5
check("просроченная ссылка -> 404",
      httpx.get(f"{API}/media-out", params={"p": rel, "exp": past, "sig": media_store._sign_path(rel, past)},
                timeout=25).status_code == 404)

section("7. Формат запроса к Gupshup (dry-run выключен, Gupshup подменён)")
captured = []
gupshup_status = {"code": 200}


class _Gupshup(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(n).decode())
        captured.append({k: v[0] for k, v in form.items()})
        self.send_response(gupshup_status["code"])
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"submitted","messageId":"x"}')

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 8098), _Gupshup)
threading.Thread(target=srv.serve_forever, daemon=True).start()

from src.whatsapp_bot import whatsapp as wa
wa.WHATSAPP_DRY_RUN = False
wa.GUPSHUP_SEND_URL = "http://127.0.0.1:8098/send"
media = {"media_path": rel, "media_mime": "image/png", "media_size": len(PNG)}
FILE_URL = "https://bot.example.kz/api/v1/console/media-out?p=x&exp=1&sig=y"


def run(kind, **kw):
    captured.clear()
    mid = asyncio.run(wa._send_whatsapp_media(phone, kind, FILE_URL, media=media,
                                              persist_manager_id=DIRECTOR_ID, **kw))
    return mid, [json.loads(c["message"]) for c in captured], captured


mid, msgs, raw = run("image", caption="подпись", file_name="a.png")
check("image: один запрос", len(msgs) == 1, str(len(msgs)))
check("image: type/originalUrl/previewUrl/caption",
      msgs and msgs[0] == {"type": "image", "originalUrl": FILE_URL, "previewUrl": FILE_URL, "caption": "подпись"},
      str(msgs[:1]))
check("image: destination = номер клиента", raw and raw[0].get("destination") == phone)
check("image: записано в консоль", bool(mid))

mid, msgs, _ = run("video", caption="видео")
check("video: type/url/caption", msgs and msgs[0] == {"type": "video", "url": FILE_URL, "caption": "видео"}, str(msgs[:1]))

mid, msgs, _ = run("audio", caption="послушайте")
check("audio: сначала аудио без подписи", msgs and msgs[0] == {"type": "audio", "url": FILE_URL}, str(msgs[:1]))
check("audio: подпись вторым текстовым сообщением",
      len(msgs) == 2 and msgs[1] == {"type": "text", "text": "послушайте"}, str(msgs))

mid, msgs, _ = run("document", caption="", file_name="Прайс.pdf")
check("document: type=file, url, filename",
      msgs and msgs[0] == {"type": "file", "url": FILE_URL, "filename": "Прайс.pdf"}, str(msgs[:1]))
check("document без подписи — ровно один запрос", len(msgs) == 1, str(len(msgs)))

gupshup_status["code"] = 500
before = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c", c=cid)
mid, msgs, _ = run("document", caption="не уйдёт", file_name="x.pdf")
after = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c", c=cid)
check("Gupshup вернул 500 -> None", mid is None)
check("  и в консоль ничего не записано (ни файл, ни подпись)", after == before, f"{before} -> {after}")
srv.shutdown()

total = len(_res)
failed = [r for r in _res if not r[1]]
print(f"\nИТОГО: {total - len(failed)} PASS, {len(failed)} FAIL")
