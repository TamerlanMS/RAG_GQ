# -*- coding: utf-8 -*-
"""
Статистика по заявкам (GET /console/stats) — доступ только у директора,
корректность подсчётов сверяется напрямую с БД.
"""
from __future__ import annotations

import subprocess
import sys
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
    httpx.post(BASE + "/api/v1/whatsapp/webhook", params={"token": "gqgroup_verify"},
              timeout=25, json={"entry": [{"changes": [{
        "field": "messages", "value": {
            "contacts": [{"profile": {"name": name}, "wa_id": phone}],
            "messages": [{"from": phone, "id": mid, "type": "text", "text": {"body": body}}]}}]}]})
    return mid


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def wait_for(fn, timeout=25, interval=0.5):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(interval)
    return False


# Набор не должен зависеть от того, что сделали с паролями другие файлы
# батареи, запущенные раньше (test_console.py сбрасывает пароль ВСЕХ
# менеджеров, test_fixes.py отдельно меняет пароль Калбаевой) — сами
# задаём пароли перед входом.
PW = "TestPass_stats_123"
for code in ("director", "kalbaeva"):
    subprocess.run([sys.executable, "scripts/seed_managers.py", "--code", code, "--password", PW],
                   capture_output=True, cwd="/app")

T_DIR = httpx.post(API + "/login", timeout=25,
                   json={"phone": "87710010254", "password": PW}).json()["access_token"]
T_KAL = httpx.post(API + "/login", timeout=25,
                   json={"phone": "87750866676", "password": PW}).json()["access_token"]

section("16. ДОСТУП: только директор")

check("директор -> 200", httpx.get(API + "/stats", headers=auth(T_DIR), timeout=25).status_code == 200)
r = httpx.get(API + "/stats", headers=auth(T_KAL), timeout=25)
check("обычный менеджер -> 403", r.status_code == 403, f"HTTP {r.status_code}")
check("текст объясняет причину", "руководител" in r.json().get("detail", "").lower(), r.json())
check("без токена -> 401", httpx.get(API + "/stats", timeout=25).status_code == 401)

section("17. КОРРЕКТНОСТЬ ПОДСЧЁТОВ")

# Набор самодостаточный: два новых чата с известным раскладом ответов.
P1, P2 = "77099990001", "77099990002"
_s = db()
try:
    for p in (P1, P2):
        _s.execute(sqltext("DELETE FROM chat_messages WHERE chat_id IN "
                           "(SELECT id FROM chats WHERE external_id=:p)"), {"p": p})
        _s.execute(sqltext("DELETE FROM chats WHERE external_id=:p"), {"p": p})
    _s.commit()
finally:
    _s.close()

webhook(P1, "Нужна цена на автомат", name="Стата Один")
wait_for(lambda: q1("SELECT count(*) FROM chats WHERE external_id=:p", p=P1) == 1)
cid1 = q1("SELECT id FROM chats WHERE external_id=:p", p=P1)
time.sleep(9)  # даём боту ответить, иначе P1 попадёт в never_replied как и P2

webhook(P2, "Здравствуйте", name="Стата Два")
wait_for(lambda: q1("SELECT count(*) FROM chats WHERE external_id=:p", p=P2) == 1)
cid2 = q1("SELECT id FROM chats WHERE external_id=:p", p=P2)

# Менеджер (Калбаева) отвечает только в P1 -> P2 остаётся "без ответа менеджера".
httpx.post(f"{API}/chats/{cid1}/reply", headers=auth(T_KAL), timeout=30,
           json={"text": "Автомат IEK есть, уточните количество.", "take_over": True})
httpx.post(f"{API}/chats/{cid1}/release", headers=auth(T_KAL), timeout=25)

before_never = q1(
    "SELECT count(*) FROM chats WHERE id IN (:a,:b) AND NOT EXISTS "
    "(SELECT 1 FROM chat_messages m WHERE m.chat_id=chats.id AND m.author='manager')",
    a=cid1, b=cid2,
)
check("P2 действительно без ответа менеджера (контроль перед сравнением с API)",
      before_never == 1, f"{before_never}")

r = httpx.get(API + "/stats", params={"period": "today"}, headers=auth(T_DIR), timeout=25)
check("period=today -> 200", r.status_code == 200, f"HTTP {r.status_code}")
data = r.json()

db_total_today = q1(
    "SELECT count(*) FROM chats WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'UTC')"
)
check("total_chats совпадает с прямым запросом к БД",
      data["total_chats"] == db_total_today, f"API={data['total_chats']} DB={db_total_today}")

db_never = q1(
    "SELECT count(*) FROM chats c WHERE c.created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') "
    "AND NOT EXISTS (SELECT 1 FROM chat_messages m WHERE m.chat_id=c.id AND m.author='manager')"
)
check("never_replied_chats совпадает с прямым запросом", data["never_replied_chats"] == db_never,
      f"API={data['never_replied_chats']} DB={db_never}")

kal_row = next((m for m in data["by_manager"] if m["manager_name"].startswith("Калбаева")), None)
check("Калбаева попала в by_manager", kal_row is not None)
db_kal_handled = q1(
    "SELECT count(DISTINCT chat_id) FROM chat_messages "
    "WHERE author='manager' AND author_manager_id=2 AND chat_id IN "
    "(SELECT id FROM chats WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'UTC'))"
)
check("chats_handled Калбаевой совпадает с БД", kal_row and kal_row["chats_handled"] == db_kal_handled,
      f"API={kal_row['chats_handled'] if kal_row else '?'} DB={db_kal_handled}")

all_manager_ids = {m["manager_id"] for m in data["by_manager"]}
db_manager_ids = {r[0] for r in qall("SELECT id FROM managers")}
check("в by_manager попали ВСЕ менеджеры, включая с нулём заявок",
      all_manager_ids == db_manager_ids, f"{sorted(all_manager_ids)} vs {sorted(db_manager_ids)}")

section("18. ПЕРИОДЫ И ДИАПАЗОН ДАТ")

for period in ("today", "week", "month", "all"):
    r = httpx.get(API + "/stats", params={"period": period}, headers=auth(T_DIR), timeout=25)
    check(f"period={period} -> 200", r.status_code == 200, f"HTTP {r.status_code}")

r = httpx.get(API + "/stats", params={"date_from": "2020-01-01", "date_to": "2020-12-31"},
              headers=auth(T_DIR), timeout=25)
check("явный диапазон в прошлом -> total_chats=0", r.status_code == 200 and r.json()["total_chats"] == 0,
      str(r.json().get("total_chats")))

r = httpx.get(API + "/stats", params={"date_from": "not-a-date"}, headers=auth(T_DIR), timeout=25)
check("неверный формат даты -> 422", r.status_code == 422, f"HTTP {r.status_code}")

r_all = httpx.get(API + "/stats", params={"period": "all"}, headers=auth(T_DIR), timeout=25).json()
check("period=all покрывает весь тестовый диапазон (>= today)",
      r_all["total_chats"] >= data["total_chats"],
      f"all={r_all['total_chats']} today={data['total_chats']}")

print("\nИТОГ: pass=%d fail=%d" % (sum(1 for _, o, _ in _res if o),
                                   sum(1 for _, o, _ in _res if not o)))
for n, o, d in _res:
    if not o:
        print("  ПРОВАЛ:", n, "—", d)
