# -*- coding: utf-8 -*-
"""Проверка двух исправлений, найденных при тестировании интерфейса."""
from __future__ import annotations

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


def qall(sql, **p):
    s = db()
    try:
        return s.execute(sqltext(sql), p).all()
    finally:
        s.close()


T_SAB = httpx.post(API + "/login", timeout=25,
                   json={"phone": "87710225844", "password": "TestPass_ivanova_123"}
                   ).json()["access_token"]
T_KAL = httpx.post(API + "/login", timeout=25,
                   json={"phone": "87770791494", "password": "NewPass_kalbaeva_456"}
                   ).json()["access_token"]
HS = {"Authorization": f"Bearer {T_SAB}"}
HK = {"Authorization": f"Bearer {T_KAL}"}

section("ИСПРАВЛЕНИЕ 1: сервер отдаёт корректный текст ошибки логина")

r = httpx.post(API + "/login", json={"phone": "87710225844", "password": "nope"}, timeout=25)
check("неверный пароль -> 401", r.status_code == 401, f"HTTP {r.status_code}")
check("detail = «Неверный телефон или пароль», а не про сессию",
      r.json()["detail"] == "Неверный телефон или пароль", r.json()["detail"])
check("текст НЕ содержит «сесси»", "сесси" not in r.json()["detail"].lower())

r = httpx.get(API + "/me", headers={"Authorization": "Bearer garbage-token"}, timeout=25)
check("а вот на защищённом роуте 401 остаётся про авторизацию",
      r.status_code == 401 and "авториз" in r.json()["detail"].lower(), r.json()["detail"])

section("ИСПРАВЛЕНИЕ 2: фильтр mine — по конкретному менеджеру")

# Набор не должен зависеть от порядка запуска: сами создаём расклад —
# один диалог у Ивановой, один у Айтейбаевой, остальные у бота.
_ids = [r[0] for r in qall("SELECT id FROM chats ORDER BY id")]
assert len(_ids) >= 2, "нужно минимум 2 чата"
for _i in _ids:
    httpx.post(f"{API}/chats/{_i}/release", headers=HS, timeout=25)
    httpx.post(f"{API}/chats/{_i}/release", headers=HK, timeout=25)
httpx.post(f"{API}/chats/{_ids[0]}/takeover", headers=HS, json={"force": True}, timeout=25)
httpx.post(f"{API}/chats/{_ids[1]}/takeover", headers=HK, json={"force": True}, timeout=25)

holders = {r[0]: r[1] for r in qall(
    "SELECT c.id, m.name FROM chats c LEFT JOIN managers m ON m.id=c.taken_over_by_id")}
taken_total = sum(1 for v in holders.values() if v)

a = httpx.get(API + "/chats", params={"mine": "true"}, headers=HS, timeout=25).json()
b = httpx.get(API + "/chats", params={"mine": "true"}, headers=HK, timeout=25).json()
allt = httpx.get(API + "/chats", params={"taken_over": "true"}, headers=HS, timeout=25).json()
bot = httpx.get(API + "/chats", params={"taken_over": "false"}, headers=HS, timeout=25).json()

check("mine для Ивановой -> только её диалоги",
      all((c["taken_over_by"] or {}).get("name", "").startswith("Иванова") for c in a["items"])
      and a["total"] > 0, f"{a['total']} шт.")
check("mine для Айтейбаевой -> только её диалоги",
      all((c["taken_over_by"] or {}).get("name", "").startswith("Айтейбаева") for c in b["items"])
      and b["total"] > 0, f"{b['total']} шт.")
check("выборки двух менеджеров не пересекаются",
      not ({c["id"] for c in a["items"]} & {c["id"] for c in b["items"]}))
check("mine(Иванова) + mine(Айтейбаева) == taken_over=true",
      a["total"] + b["total"] == allt["total"] == taken_total,
      f"{a['total']}+{b['total']} vs {allt['total']} (в БД {taken_total})")
check("taken_over=false -> ни у одного нет держателя",
      all(c["taken_over_by"] is None and c["is_taken_over"] is False for c in bot["items"]),
      f"{bot['total']} шт.")
check("mine и taken_over комбинируются без ошибки",
      httpx.get(API + "/chats", params={"mine": "true", "taken_over": "true"},
                headers=HS, timeout=25).status_code == 200)
check("mine=false ведёт себя как отсутствие фильтра",
      httpx.get(API + "/chats", params={"mine": "false"}, headers=HS, timeout=25).json()["total"]
      == httpx.get(API + "/chats", headers=HS, timeout=25).json()["total"])
check("mine требует авторизации",
      httpx.get(API + "/chats", params={"mine": "true"}, timeout=25).status_code == 401)

section("ИСПРАВЛЕНИЕ 3: заголовки кеширования")

r = httpx.get(BASE + "/console/", timeout=25)
check("index.html -> no-cache", "no-cache" in r.headers.get("cache-control", ""),
      r.headers.get("cache-control", "(нет)"))
import re  # noqa: E402
m = re.search(r'src="(/console/assets/[^"]+\.js)"', r.text)
if m:
    ra = httpx.get(BASE + m.group(1), timeout=25)
    check("ассет -> immutable, длинный max-age",
          "immutable" in ra.headers.get("cache-control", ""),
          ra.headers.get("cache-control", "(нет)"))

print("\nИТОГ: pass=%d fail=%d" % (sum(1 for _, o, _ in _res if o),
                                   sum(1 for _, o, _ in _res if not o)))
for n, o, d in _res:
    if not o:
        print("  ПРОВАЛ:", n, "—", d)
