# -*- coding: utf-8 -*-
"""
Автовозврат диалога боту при бездействии менеджера.

Не ждём реальные TAKEOVER_AUTO_RELEASE_MINUTES — вместо этого сдвигаем
taken_over_at в прошлое напрямую в БД и ждём, пока фоновый вотчдог
(main.py: _takeover_watchdog, проверяет каждые 60 с) сам его подхватит.
Значение TAKEOVER_TIMEOUT_MINUTES читаем из самого модуля chat_store —
так тест остаётся верным при любом значении переменной окружения.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text as sqltext

BASE = "http://localhost:8000"
API = BASE + "/api/v1/console"
WEBHOOK_TOKEN = os.getenv("GUPSHUP_VERIFY_TOKEN", "gqgroup_verify")
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


def exec_sql(sql, **p):
    s = db()
    try:
        s.execute(sqltext(sql), p)
        s.commit()
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


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def wait_for(fn, timeout=90, interval=2):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(interval)
    return False


from src.common import chat_store  # noqa: E402

TIMEOUT_MIN = chat_store.TAKEOVER_TIMEOUT_MINUTES
print(f"TAKEOVER_TIMEOUT_MINUTES = {TIMEOUT_MIN} (читаем из живого процесса api)")

T_KAL = httpx.post(API + "/login", timeout=25,
                   json={"phone": "87770791494", "password": "NewPass_kalbaeva_456"}
                   ).json()["access_token"]
HK = auth(T_KAL)

# ─────────────────────────────────────────────────────────────
section("14. АВТОВОЗВРАТ ПРИ БЕЗДЕЙСТВИИ МЕНЕДЖЕРА")

P = "77088880008"
exec_sql("DELETE FROM chat_messages WHERE chat_id IN "
         "(SELECT id FROM chats WHERE external_id=:p)", p=P)
exec_sql("DELETE FROM chats WHERE external_id=:p", p=P)

webhook(P, "Здравствуйте, нужен автомат IEK", name="Тимаут Тест")
wait_for(lambda: q1("SELECT count(*) FROM chats WHERE external_id=:p", p=P) == 1, timeout=20)
cid = q1("SELECT id FROM chats WHERE external_id=:p", p=P)
check("чат создан", cid is not None)

r = httpx.post(f"{API}/chats/{cid}/takeover", headers=HK, json={}, timeout=25)
check("перехват -> 200", r.status_code == 200, f"HTTP {r.status_code}")
check("is_taken_over=true сразу после перехвата",
      q1("SELECT is_taken_over FROM chats WHERE id=:i", i=cid) is True)

# /reply должен освежать taken_over_at, а не только выставлять его при первом перехвате.
before_reply = q1("SELECT taken_over_at FROM chats WHERE id=:i", i=cid)
time.sleep(1.5)
r = httpx.post(f"{API}/chats/{cid}/reply", headers=HK, timeout=30,
               json={"text": "Да, есть в наличии.", "take_over": False})
check("reply при уже перехваченном чате -> 200", r.status_code == 200, f"HTTP {r.status_code}")
after_reply = q1("SELECT taken_over_at FROM chats WHERE id=:i", i=cid)
check("taken_over_at сдвинулся вперёд после /reply (не только на takeover)",
      after_reply > before_reply, f"{before_reply} -> {after_reply}")

# Сдвигаем "последнюю активность" в прошлое дальше порога — без ожидания реальных минут.
stale_at = datetime.now(timezone.utc) - timedelta(minutes=TIMEOUT_MIN + 1)
exec_sql("UPDATE chats SET taken_over_at = :t WHERE id = :i", t=stale_at, i=cid)
check("taken_over_at искусственно состарен", True)

sys_before = q1(
    "SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='system'", c=cid
)

ok = wait_for(lambda: q1("SELECT is_taken_over FROM chats WHERE id=:i", i=cid) is False,
              timeout=90, interval=2)
check("вотчдог освободил диалог в течение ~90 с (интервал проверки 60 с)", ok)
check("taken_over_by_id сброшен", q1("SELECT taken_over_by_id FROM chats WHERE id=:i", i=cid) is None)
check("taken_over_at сброшен", q1("SELECT taken_over_at FROM chats WHERE id=:i", i=cid) is None)

sys_after = q1(
    "SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='system'", c=cid
)
check("добавлено ровно одно системное сообщение", sys_after == sys_before + 1,
      f"{sys_before} -> {sys_after}")

last_sys = q1(
    "SELECT text FROM chat_messages WHERE chat_id=:c AND author='system' ORDER BY id DESC LIMIT 1",
    c=cid,
)
check("текст называет менеджера и упоминает автовозврат",
      "Калбаева" in (last_sys or "") and "автоматически возвращён" in (last_sys or ""),
      repr(last_sys))

# Бот должен снова отвечать после автовозврата (гейт снят) — без повтора приветствия.
btn_before = q1(
    "SELECT count(*) FROM chat_messages WHERE chat_id=:c AND msg_type='button' AND author='bot'",
    c=cid,
)
webhook(P, "Ещё вопрос после автовозврата")
ok = wait_for(lambda: q1(
    "SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='bot' "
    "AND created_at > now() - interval '30 seconds'", c=cid
) > 0, timeout=20)
check("бот отвечает снова после автовозврата", ok)
btn_after = q1(
    "SELECT count(*) FROM chat_messages WHERE chat_id=:c AND msg_type='button' AND author='bot'",
    c=cid,
)
check("приветственное меню не повторилось (_greeted не сброшен)", btn_after == btn_before)

# ─────────────────────────────────────────────────────────────
section("15. СВЕЖИЙ ПЕРЕХВАТ НЕ ТРОГАЕТСЯ")

P2 = "77088880009"
exec_sql("DELETE FROM chat_messages WHERE chat_id IN "
         "(SELECT id FROM chats WHERE external_id=:p)", p=P2)
exec_sql("DELETE FROM chats WHERE external_id=:p", p=P2)
webhook(P2, "Добрый день", name="Свежий Перехват")
wait_for(lambda: q1("SELECT count(*) FROM chats WHERE external_id=:p", p=P2) == 1, timeout=20)
cid2 = q1("SELECT id FROM chats WHERE external_id=:p", p=P2)
httpx.post(f"{API}/chats/{cid2}/takeover", headers=HK, json={}, timeout=25)

# Не старим taken_over_at — он свежий (сейчас). Ждём один цикл вотчдога (60с+запас)
# и убеждаемся, что диалог остался перехваченным.
time.sleep(70)
check("свежий перехват пережил цикл вотчдога и остался у менеджера",
      q1("SELECT is_taken_over FROM chats WHERE id=:i", i=cid2) is True)

httpx.post(f"{API}/chats/{cid2}/release", headers=HK, timeout=25)

print("\nИТОГ: pass=%d fail=%d" % (sum(1 for _, o, _ in _res if o),
                                   sum(1 for _, o, _ in _res if not o)))
for n, o, d in _res:
    if not o:
        print("  ПРОВАЛ:", n, "—", d)
