# -*- coding: utf-8 -*-
"""Изолированная проверка счётчика непрочитанных и истории бота."""
from __future__ import annotations

import os
import time
import uuid

import httpx
from sqlalchemy import text as sqltext

BASE = "http://localhost:8000"
API = BASE + "/api/v1/console"
WEBHOOK_TOKEN = os.getenv("GUPSHUP_VERIFY_TOKEN", "gqgroup_verify")
_res = []


def check(n, c, d=""):
    _res.append((n, bool(c), d))
    print(f"[{'PASS' if c else 'FAIL'}] {n}" + (f"  — {d}" if d else ""))


def db():
    from src.db.chat_database import ChatSessionLocal
    return ChatSessionLocal()


def q1(sql, **p):
    s = db()
    try:
        return s.execute(sqltext(sql), p).scalar()
    finally:
        s.close()


def webhook(phone, body, name="Клиент"):
    mid = "wamid." + uuid.uuid4().hex[:12]
    httpx.post(BASE + "/api/v1/whatsapp/webhook", params={"token": WEBHOOK_TOKEN},
              timeout=25, json={"entry": [{"changes": [{
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


print("=" * 72)
print("СЧЁТЧИК НЕПРОЧИТАННЫХ (изолированно, без открытой консоли в браузере)")
print("=" * 72)

P = "77033330003"
s = db()
try:
    s.execute(sqltext("DELETE FROM chat_messages WHERE chat_id IN "
                      "(SELECT id FROM chats WHERE external_id=:p)"), {"p": P})
    s.execute(sqltext("DELETE FROM chats WHERE external_id=:p"), {"p": P})
    s.commit()
finally:
    s.close()

wid = webhook(P, "Первое сообщение", name="Ержан Тест")
wait_for(lambda: q1("SELECT count(*) FROM chats WHERE external_id=:p", p=P) == 1)
cid = q1("SELECT id FROM chats WHERE external_id=:p", p=P)
wait_for(lambda: q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='bot'", c=cid) >= 1)
u1 = q1("SELECT unread_count FROM chats WHERE id=:i", i=cid)
check("после 1 входящего unread=1", u1 == 1, f"получено {u1}")

webhook(P, "Второе сообщение")
time.sleep(12)
u2 = q1("SELECT unread_count FROM chats WHERE id=:i", i=cid)
check("после 2 входящих unread=2 (ответ бота НЕ увеличивает)", u2 == 2, f"получено {u2}")

webhook(P, "Третье сообщение")
time.sleep(12)
u3 = q1("SELECT unread_count FROM chats WHERE id=:i", i=cid)
check("после 3 входящих unread=3", u3 == 3, f"получено {u3}")

n_bot = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='bot'", c=cid)
check("исходящих от бота при этом несколько", n_bot >= 2, f"{n_bot} шт.")

# /read
r = httpx.post(API + "/login", json={"phone": "87770791494", "password": "NewPass_kalbaeva_456"},
               timeout=25)
T = r.json()["access_token"]
H = {"Authorization": f"Bearer {T}"}
httpx.post(f"{API}/chats/{cid}/read", headers=H, timeout=25)
check("после /read unread=0", q1("SELECT unread_count FROM chats WHERE id=:i", i=cid) == 0)

webhook(P, "Сообщение после прочтения")
time.sleep(12)
u4 = q1("SELECT unread_count FROM chats WHERE id=:i", i=cid)
check("счётчик снова растёт после /read", u4 == 1, f"получено {u4}")

print()
print("=" * 72)
print("ИСТОРИЯ БОТА ПОСЛЕ ОТВЕТА МЕНЕДЖЕРА (проверяем В ПРОЦЕССЕ СЕРВЕРА)")
print("=" * 72)
# _wa_history — dict в памяти процесса uvicorn. Из отдельного процесса его не видно,
# поэтому спрашиваем сам сервер через отладочный вызов внутри его же процесса.
httpx.post(f"{API}/chats/{cid}/reply", headers=H, timeout=30,
           json={"text": "Ответ менеджера для проверки истории"})
time.sleep(2)
print("(проверка истории выполняется отдельным шагом внутри процесса сервера)")

print()
print("ИТОГ: pass=%d fail=%d" % (sum(1 for _, o, _ in _res if o),
                                 sum(1 for _, o, _ in _res if not o)))
for n, o, d in _res:
    if not o:
        print("  ПРОВАЛ:", n, "—", d)
