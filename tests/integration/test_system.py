# -*- coding: utf-8 -*-
"""Системные сообщения при перехвате/возврате + регрессия основного API."""
from __future__ import annotations

import time
import uuid

import httpx
from sqlalchemy import text as sqltext

BASE = "http://localhost:8000"
API = BASE + "/api/v1/console"
_res = []


def check(n, c, d=""):
    _res.append((n, bool(c), d))
    print(f"[{'PASS' if c else 'FAIL'}] {n}" + (f"  — {d}" if d else ""))


def section(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def db():
    from src.db.chat_database import ChatSessionLocal
    return ChatSessionLocal()


def q1(sql, **p):
    s = db()
    try:
        return s.execute(sqltext(sql), p).scalar()
    finally:
        s.close()


def qall(sql, **p):
    s = db()
    try:
        return s.execute(sqltext(sql), p).all()
    finally:
        s.close()


def webhook(phone, body, name="Клиент"):
    mid = "wamid." + uuid.uuid4().hex[:12]
    httpx.post(BASE + "/api/v1/whatsapp/webhook", timeout=25, json={"entry": [{"changes": [{
        "field": "messages", "value": {
            "contacts": [{"profile": {"name": name}, "wa_id": phone}],
            "messages": [{"from": phone, "id": mid, "type": "text", "text": {"body": body}}]}}]}]})
    return mid


def wait_for(fn, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.5)
    return False


T_KAL = httpx.post(API + "/login", timeout=25,
                   json={"phone": "87750866676", "password": "NewPass_kalbaeva_456"}
                   ).json()["access_token"]
T_SAB = httpx.post(API + "/login", timeout=25,
                   json={"phone": "87711668284", "password": "TestPass_sabieva_123"}
                   ).json()["access_token"]
HK = {"Authorization": f"Bearer {T_KAL}"}
HS = {"Authorization": f"Bearer {T_SAB}"}

section("11. СИСТЕМНЫЕ СООБЩЕНИЯ (чистый чат)")

P = "77044440004"
s = db()
try:
    s.execute(sqltext("DELETE FROM chat_messages WHERE chat_id IN "
                      "(SELECT id FROM chats WHERE external_id=:p)"), {"p": P})
    s.execute(sqltext("DELETE FROM chats WHERE external_id=:p"), {"p": P})
    s.commit()
finally:
    s.close()

webhook(P, "Здравствуйте", name="Мурат Сыстем")
wait_for(lambda: q1("SELECT count(*) FROM chats WHERE external_id=:p", p=P) == 1)
cid = q1("SELECT id FROM chats WHERE external_id=:p", p=P)
time.sleep(8)


def nsys():
    return q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='system'", c=cid)


check("на чистом чате системных сообщений нет", nsys() == 0, f"{nsys()}")

httpx.post(f"{API}/chats/{cid}/takeover", headers=HK, json={}, timeout=25)
check("takeover -> +1 системное", nsys() == 1, f"{nsys()}")

httpx.post(f"{API}/chats/{cid}/takeover", headers=HK, json={}, timeout=25)
check("повторный takeover тем же менеджером -> без нового", nsys() == 1, f"{nsys()}")

httpx.post(f"{API}/chats/{cid}/takeover", headers=HS, json={"force": True}, timeout=25)
check("перехват другим менеджером (force) -> +1", nsys() == 2, f"{nsys()}")

httpx.post(f"{API}/chats/{cid}/release", headers=HS, timeout=25)
check("release -> +1", nsys() == 3, f"{nsys()}")

httpx.post(f"{API}/chats/{cid}/release", headers=HS, timeout=25)
check("повторный release -> без нового", nsys() == 3, f"{nsys()}")

texts = [r[0] for r in qall(
    "SELECT text FROM chat_messages WHERE chat_id=:c AND author='system' ORDER BY id", c=cid)]
check("тексты системных сообщений осмысленные",
      "подключился" in texts[0] and "вернул" in texts[-1], str(texts))

r = httpx.get(f"{API}/chats/{cid}/messages", headers=HK, timeout=25).json()
sys_out = [m for m in r["items"] if m["author"] == "system"]
check("системные сообщения видны в API", len(sys_out) == 3, f"{len(sys_out)}")
check("у системного msg_type=system", all(m["msg_type"] == "system" for m in sys_out))

section("12. РЕГРЕССИЯ: существующие эндпоинты не сломаны")

r = httpx.get(BASE + "/api/v1/status_DB", timeout=25)
check("GET /status_DB -> 200", r.status_code == 200, f"HTTP {r.status_code}")
check("отвечает версия Postgres", "PostgreSQL" in str(r.json().get("DB_version", "")),
      str(r.json().get("DB_version", ""))[:40])

r = httpx.get(BASE + "/api/v1/products", params={"limit": 3}, timeout=25)
check("GET /products -> 200", r.status_code == 200, f"HTTP {r.status_code}")
check("товары на месте", isinstance(r.json(), list) and len(r.json()) == 3,
      f"{len(r.json()) if isinstance(r.json(), list) else '?'} шт.")
total_products = q1_main = None
from src.db.database import SessionLocal  # noqa: E402
sm = SessionLocal()
try:
    total_products = sm.execute(sqltext("SELECT count(*) FROM products")).scalar()
finally:
    sm.close()
check("в основной базе есть товары", total_products > 4000, f"{total_products} шт.")

pid = r.json()[0]["id"]
r = httpx.get(f"{BASE}/api/v1/products/{pid}", timeout=25)
check("GET /products/{id} -> 200", r.status_code == 200)
check("GET /products/999999999 -> 404",
      httpx.get(BASE + "/api/v1/products/999999999", timeout=25).status_code == 404)

r = httpx.get(BASE + "/api/v1/suppliers", timeout=25)
check("GET /suppliers -> 200", r.status_code == 200, f"HTTP {r.status_code}")
check("парсеры поставщиков зарегистрированы",
      len(r.json().get("suppliers", [])) == 6, str(r.json().get("suppliers")))

r = httpx.get(BASE + "/api/v1/whatsapp/webhook", timeout=25)
check("GET /whatsapp/webhook health-check -> 200", r.status_code == 200)
r = httpx.get(BASE + "/api/v1/whatsapp/webhook", timeout=25,
              params={"hub.mode": "subscribe", "hub.verify_token": "gqgroup_verify",
                      "hub.challenge": "12345"})
check("верификация Meta с верным токеном отдаёт challenge",
      r.status_code == 200 and r.text == "12345", f"HTTP {r.status_code} {r.text[:20]}")
r = httpx.get(BASE + "/api/v1/whatsapp/webhook", timeout=25,
              params={"hub.mode": "subscribe", "hub.verify_token": "wrong",
                      "hub.challenge": "12345"})
check("верификация с неверным токеном -> 403", r.status_code == 403, f"HTTP {r.status_code}")

section("13. КОНСОЛЬ РАЗДАЁТСЯ")

r = httpx.get(BASE + "/console/", timeout=25)
check("GET /console/ -> 200", r.status_code == 200, f"HTTP {r.status_code}")
check("отдаётся HTML", "text/html" in r.headers.get("content-type", ""),
      r.headers.get("content-type", ""))
import re  # noqa: E402
js = re.search(r'src="(/console/assets/[^"]+\.js)"', r.text)
css = re.search(r'href="(/console/assets/[^"]+\.css)"', r.text)
check("в HTML есть ссылка на JS с префиксом /console/", bool(js), js.group(1) if js else "нет")
check("в HTML есть ссылка на CSS с префиксом /console/", bool(css), css.group(1) if css else "нет")
if js:
    rj = httpx.get(BASE + js.group(1), timeout=25)
    check("JS-бандл отдаётся 200", rj.status_code == 200 and len(rj.content) > 10000,
          f"HTTP {rj.status_code}, {len(rj.content)} байт")
if css:
    rc = httpx.get(BASE + css.group(1), timeout=25)
    check("CSS отдаётся 200", rc.status_code == 200 and len(rc.content) > 1000,
          f"HTTP {rc.status_code}, {len(rc.content)} байт")

print("\nИТОГ: pass=%d fail=%d" % (sum(1 for _, o, _ in _res if o),
                                   sum(1 for _, o, _ in _res if not o)))
for n, o, d in _res:
    if not o:
        print("  ПРОВАЛ:", n, "—", d)
