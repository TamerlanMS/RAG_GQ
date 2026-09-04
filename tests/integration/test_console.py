# -*- coding: utf-8 -*-
"""
Сквозной тест менеджерской веб-консоли.
Запускается ВНУТРИ контейнера api: docker compose exec -T api python - < test_console.py
"""
from __future__ import annotations

import json
import sys
import time
import uuid

import httpx
from sqlalchemy import text as sqltext

BASE = "http://localhost:8000"
API = BASE + "/api/v1/console"

PASSWORDS = {}  # code -> password, заполняется сидированием

_results = []


def check(name, cond, detail=""):
    _results.append((name, bool(cond), detail))
    mark = "PASS" if cond else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f"  — {detail}"
    print(line)
    return bool(cond)


def section(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def db():
    from src.db.chat_database import ChatSessionLocal
    return ChatSessionLocal()


def q1(sql, **params):
    s = db()
    try:
        return s.execute(sqltext(sql), params).scalar()
    finally:
        s.close()


def qall(sql, **params):
    s = db()
    try:
        return s.execute(sqltext(sql), params).all()
    finally:
        s.close()


def webhook(phone, body, wamid=None, name="Тест Клиент", mtype="text", extra_msg=None):
    """Отправляет входящее сообщение в формате Meta Cloud API v3."""
    msg = {"from": phone, "id": wamid or ("wamid." + uuid.uuid4().hex[:12]), "type": mtype}
    if mtype == "text":
        msg["text"] = {"body": body}
    if extra_msg:
        msg.update(extra_msg)
    payload = {"entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"profile": {"name": name}, "wa_id": phone}],
        "messages": [msg]}}]}]}
    r = httpx.post(BASE + "/api/v1/whatsapp/webhook", json=payload, timeout=20)
    return r.status_code, msg["id"]


def login(phone, password):
    return httpx.post(API + "/login", json={"phone": phone, "password": password}, timeout=20)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────
section("0. ПОДГОТОВКА: чистое состояние")

s = db()
try:
    s.execute(sqltext("DELETE FROM chat_messages"))
    s.execute(sqltext("DELETE FROM chats"))
    s.commit()
finally:
    s.close()
check("таблицы переписки очищены", q1("SELECT count(*) FROM chats") == 0)
check("менеджеры на месте", q1("SELECT count(*) FROM managers") == 5,
      f"{q1('SELECT count(*) FROM managers')} шт.")


# ─────────────────────────────────────────────────────────────
section("1. НОРМАЛИЗАЦИЯ ТЕЛЕФОНОВ")

from src.common.phone import normalize_phone  # noqa: E402
from src.settings.config import MANAGERS  # noqa: E402

cases = [
    ("+77710010254", "+77710010254"),
    ("87750866676", "+77750866676"),
    ("8 (771) 166-82-84", "+77711668284"),
    ("+7 775 086-66-76", "+77750866676"),
    ("77789392009", "+77789392009"),   # сырой формат Gupshup
    ("7086110592", "+77086110592"),    # 10 цифр без префикса
    ("+87711668284", "+77711668284"),  # домашний 8 с плюсом
    ("", None),
    ("12345", None),
    ("abc", None),
    ("+1 415 555 0123", None),         # не казахстанский формат
]
for raw, expected in cases:
    got = normalize_phone(raw)
    check(f"normalize_phone({raw!r})", got == expected, f"получено {got!r}, ожидалось {expected!r}")

canonical = all(normalize_phone(m["phone"]) == m["phone"] for m in MANAGERS)
check("все номера в config.MANAGERS уже канонические", canonical)

from src.common.tools.ReAct_agent import check_phone_number  # noqa: E402
check("инструмент агента делегирует в normalize_phone",
      check_phone_number.invoke({"phone_number": "87007718216"}) == "+77007718216")


# ─────────────────────────────────────────────────────────────
section("2. ИЗОЛЯЦИЯ БАЗ")

# Модели нужно импортировать явно — так же, как это делает src/main.py,
# иначе ChatBase.metadata окажется пустым в этом процессе.
from src.db.Models import chat_models as _cm  # noqa: E402,F401
from src.db.Models import manager_models as _mm  # noqa: E402,F401
from src.db.chat_database import chat_engine  # noqa: E402
from src.db.database import Base, engine  # noqa: E402
from src.db.chat_database import ChatBase  # noqa: E402

chat_tables = set(ChatBase.metadata.tables)
main_tables = set(Base.metadata.tables)
check("модели переписки не попали в главный Base", not (chat_tables & main_tables),
      f"пересечение: {chat_tables & main_tables or 'нет'}")
check("ChatBase содержит ровно 3 таблицы", chat_tables == {"managers", "chats", "chat_messages"},
      str(sorted(chat_tables)))
check("engine'ы указывают на разные базы",
      str(chat_engine.url.database) != str(engine.url.database),
      f"{chat_engine.url.database} vs {engine.url.database}")

idx = q1("SELECT indexdef FROM pg_indexes WHERE indexname='uq_chat_messages_external'")
check("partial-индекс дедупликации создан с предикатом",
      idx and "WHERE (external_id IS NOT NULL)" in idx)


# ─────────────────────────────────────────────────────────────
section("3. АУТЕНТИФИКАЦИЯ")

# Пароли задаём принудительно, чтобы тест не зависел от прошлых прогонов.
import subprocess  # noqa: E402
for code in ("director", "kalbaeva", "sabieva", "zhenibek", "dolakov"):
    pw = "TestPass_" + code + "_123"
    PASSWORDS[code] = pw
    subprocess.run(
        [sys.executable, "scripts/seed_managers.py", "--code", code, "--password", pw],
        capture_output=True, cwd="/app",
    )

r = login("87711668284", PASSWORDS["sabieva"])
check("вход под sabieva (бывший +8 номер)", r.status_code == 200, f"HTTP {r.status_code}")
tok_sab = r.json().get("access_token") if r.status_code == 200 else None

for fmt in ["+77750866676", "87750866676", "+7 775 086-66-76", "7750866676"]:
    rr = login(fmt, PASSWORDS["kalbaeva"])
    check(f"вход в формате {fmt!r}", rr.status_code == 200, f"HTTP {rr.status_code}")

tok = login("87750866676", PASSWORDS["kalbaeva"]).json()["access_token"]
me = httpx.get(API + "/me", headers=auth(tok), timeout=20)
check("/me отдаёт профиль", me.status_code == 200 and me.json()["code"] == "kalbaeva",
      me.text[:80])

check("/me без токена -> 401", httpx.get(API + "/me", timeout=20).status_code == 401)
check("/me с мусорным токеном -> 401",
      httpx.get(API + "/me", headers=auth("garbage"), timeout=20).status_code == 401)

# Подделанная подпись
import jwt as pyjwt  # noqa: E402
forged = pyjwt.encode({"sub": "1", "exp": int(time.time()) + 3600}, "wrong-secret", algorithm="HS256")
check("токен с чужой подписью -> 401",
      httpx.get(API + "/me", headers=auth(forged), timeout=20).status_code == 401)

# Истёкший токен, подписанный правильным секретом
import os  # noqa: E402
expired = pyjwt.encode({"sub": "1", "exp": int(time.time()) - 10}, os.getenv("API_TOKEN", ""),
                       algorithm="HS256")
re_exp = httpx.get(API + "/me", headers=auth(expired), timeout=20)
check("истёкший токен -> 401 с понятным текстом",
      re_exp.status_code == 401 and "истек" in re_exp.json().get("detail", "").lower(),
      re_exp.json().get("detail", ""))

r_bad = login("87750866676", "wrong-password")
check("неверный пароль -> 401", r_bad.status_code == 401)
r_unk = login("87019999999", "whatever")
check("неизвестный номер -> 401", r_unk.status_code == 401)
check("сообщение об ошибке одинаковое (не раскрывает существование номера)",
      r_bad.json()["detail"] == r_unk.json()["detail"], r_bad.json()["detail"])
r_junk = login("не-телефон", "whatever")
check("нераспознанный номер -> 401, а не 422", r_junk.status_code == 401,
      f"HTTP {r_junk.status_code}")

# Смена пароля
new_pw = "NewPass_kalbaeva_456"
rc = httpx.post(API + "/me/password", headers=auth(tok), timeout=20,
                json={"old_password": PASSWORDS["kalbaeva"], "new_password": new_pw})
check("смена пароля -> 204", rc.status_code == 204, f"HTTP {rc.status_code}")
check("вход по новому паролю работает", login("87750866676", new_pw).status_code == 200)
check("вход по старому паролю больше не работает",
      login("87750866676", PASSWORDS["kalbaeva"]).status_code == 401)
PASSWORDS["kalbaeva"] = new_pw
rc2 = httpx.post(API + "/me/password", headers=auth(tok), timeout=20,
                 json={"old_password": "не тот", "new_password": "Whatever_789"})
check("смена пароля с неверным текущим -> 400", rc2.status_code == 400, f"HTTP {rc2.status_code}")
rc3 = httpx.post(API + "/me/password", headers=auth(tok), timeout=20,
                 json={"old_password": new_pw, "new_password": "коротк"})
check("слишком короткий новый пароль -> 422", rc3.status_code == 422, f"HTTP {rc3.status_code}")

print("\n".join([]))
print(json.dumps({"passed_so_far": sum(1 for _, ok, _ in _results if ok),
                  "failed_so_far": sum(1 for _, ok, _ in _results if not ok)}))

# Итог первой половины сохраняем — вторая часть в отдельном файле
import pickle  # noqa: E402
with open("/tmp/_res1.pkl", "wb") as f:
    pickle.dump((_results, PASSWORDS), f)
