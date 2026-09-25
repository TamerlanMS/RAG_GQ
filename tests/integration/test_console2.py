# -*- coding: utf-8 -*-
"""Часть 2: изоляция (правильно), персистентность, API, перехват."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid

import httpx
from sqlalchemy import text as sqltext

BASE = "http://localhost:8000"
API = BASE + "/api/v1/console"
WEBHOOK_TOKEN = os.getenv("GUPSHUP_VERIFY_TOKEN", "gqgroup_verify")
_results = []

PASSWORDS = {c: "TestPass_" + c + "_123" for c in
             ("director", "ivanova", "zhenibek", "mukhanov")}
PASSWORDS["kalbaeva"] = "NewPass_kalbaeva_456"


def check(name, cond, detail=""):
    _results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return bool(cond)


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


def webhook(phone, body="", wamid=None, name="Клиент", mtype="text", extra=None):
    msg = {"from": phone, "id": wamid or ("wamid." + uuid.uuid4().hex[:12]), "type": mtype}
    if mtype == "text":
        msg["text"] = {"body": body}
    if extra:
        msg.update(extra)
    payload = {"entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"profile": {"name": name}, "wa_id": phone}],
        "messages": [msg]}}]}]}
    r = httpx.post(BASE + "/api/v1/whatsapp/webhook", params={"token": WEBHOOK_TOKEN},
                   json=payload, timeout=25)
    return r.status_code, msg["id"]


def login(phone, pw):
    return httpx.post(API + "/login", json={"phone": phone, "password": pw}, timeout=25)


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def wait_for(fn, timeout=25, interval=0.5):
    """Ждём асинхронную обработку вебхука (BackgroundTasks + задержки бота)."""
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(interval)
    return False


# ─────────────────────────────────────────────────────────────
section("2b. ИЗОЛЯЦИЯ БАЗ (с корректным импортом моделей)")

# Так же, как это делает src/main.py
from src.db.Models import chat_models as _cm  # noqa: E402,F401
from src.db.Models import manager_models as _mm  # noqa: E402,F401
from src.db.Models import product_models as _pm  # noqa: E402,F401
from src.db.chat_database import ChatBase, chat_engine  # noqa: E402
from src.db.database import Base, engine  # noqa: E402

chat_t = set(ChatBase.metadata.tables)
main_t = set(Base.metadata.tables)
check("ChatBase содержит ровно 3 таблицы", chat_t == {"managers", "chats", "chat_messages"},
      str(sorted(chat_t)))
check("модели переписки НЕ в главном Base", not (chat_t & main_t),
      f"пересечение: {sorted(chat_t & main_t) or 'нет'}")
check("products остался в главном Base", "products" in main_t)

import src.db.Models as models_pkg  # noqa: E402
exported = [n for n in ("Chat", "ChatMessage", "Manager") if hasattr(models_pkg, n)]
check("Models/__init__ не реэкспортирует модели переписки", not exported, str(exported))

# ensure_chat_database идемпотентна
from src.db.chat_database import ensure_chat_database  # noqa: E402
try:
    ensure_chat_database()
    ensure_chat_database()
    check("ensure_chat_database идемпотентна (2 вызова подряд)", True)
except Exception as e:
    check("ensure_chat_database идемпотентна (2 вызова подряд)", False, repr(e))


# ─────────────────────────────────────────────────────────────
section("3b. ОГРАНИЧЕНИЕ ПЕРЕБОРА ПАРОЛЯ")

# mukhanov используется только здесь — после теста его номер заблокирован на 15 мин.
codes = []
for i in range(6):
    codes.append(login("87715259591", "wrong" + str(i)).status_code)
check("первые 5 неудачных попыток -> 401", codes[:5] == [401] * 5, str(codes[:5]))
check("6-я попытка -> 429 (сработал лимит)", codes[5] == 429, f"получено {codes[5]}")
r_locked = login("87715259591", PASSWORDS["mukhanov"])
check("верный пароль при блокировке тоже -> 429", r_locked.status_code == 429,
      f"HTTP {r_locked.status_code}")
check("блокировка не задевает других менеджеров",
      login("87710225844", PASSWORDS["ivanova"]).status_code == 200)


# ─────────────────────────────────────────────────────────────
section("4. ПЕРСИСТЕНТНОСТЬ ВХОДЯЩИХ И ИСХОДЯЩИХ")

P1 = "77011110001"
# Тест должен быть идемпотентен: сносим чат от прошлых прогонов,
# иначе проверки «первое сообщение» и display_name гонятся с фоновой задачей.
_s = db()
try:
    _s.execute(sqltext("DELETE FROM chat_messages WHERE chat_id IN "
                       "(SELECT id FROM chats WHERE external_id=:p)"), {"p": P1})
    _s.execute(sqltext("DELETE FROM chats WHERE external_id=:p"), {"p": P1})
    _s.commit()
finally:
    _s.close()

st, wid1 = webhook(P1, "Здравствуйте, нужен кабель ВВГ 3х2.5", name="Алия Нурлан")
check("вебхук возвращает 200 сразу", st == 200, f"HTTP {st}")

ok = wait_for(lambda: q1("SELECT count(*) FROM chats WHERE external_id=:p", p=P1) == 1)
check("чат создан", ok)
# Ждём, пока фоновая задача допишет входящее — только потом проверяем поля чата.
wait_for(lambda: q1("SELECT count(*) FROM chat_messages WHERE external_id=:w", w=wid1) == 1)
chat = qall("SELECT id, display_name, phone, channel, unread_count FROM chats WHERE external_id=:p", p=P1)[0]
check("display_name из вебхука сохранён", chat[1] == "Алия Нурлан", repr(chat[1]))
check("phone нормализован в +7", chat[2] == "+7" + P1[1:], repr(chat[2]))
check("external_id остался сырым (нужен для отправки в Gupshup)",
      q1("SELECT external_id FROM chats WHERE id=:i", i=chat[0]) == P1)
check("channel = whatsapp", chat[3] == "whatsapp")

ok = wait_for(lambda: q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c", c=chat[0]) >= 2)
check("записаны входящее и исходящее", ok,
      f"{q1('SELECT count(*) FROM chat_messages WHERE chat_id=:c', c=chat[0])} сообщений")

rows = qall("SELECT direction, author, msg_type, external_id FROM chat_messages "
            "WHERE chat_id=:c ORDER BY id", c=chat[0])
check("первое — входящее от клиента", rows[0][:3] == ("in", "client", "text"), str(rows[0]))
check("wamid сохранён у входящего", rows[0][3] == wid1, repr(rows[0][3]))
check("второе — исходящее от бота (приветственные кнопки)",
      rows[1][0] == "out" and rows[1][1] == "bot", str(rows[1]))
check("у исходящего external_id пуст", rows[1][3] is None, repr(rows[1][3]))
check("unread_count = 1 (считается только входящее)",
      q1("SELECT unread_count FROM chats WHERE id=:i", i=chat[0]) == 1,
      str(q1("SELECT unread_count FROM chats WHERE id=:i", i=chat[0])))
check("last_message_preview заполнен",
      bool(q1("SELECT last_message_preview FROM chats WHERE id=:i", i=chat[0])))

# Идемпотентность
n_before = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c", c=chat[0])
webhook(P1, "Здравствуйте, нужен кабель ВВГ 3х2.5", wamid=wid1, name="Алия Нурлан")
time.sleep(8)
dupes = q1("SELECT count(*) FROM chat_messages WHERE external_id=:w", w=wid1)
check("повторный вебхук с тем же wamid не создаёт дубликат", dupes == 1, f"{dupes} записей")

# Типы сообщений
st, wid_img = webhook(P1, mtype="image", extra={
    "image": {"id": "media-1", "caption": "Вот такой автомат", "url": ""}})
ok = wait_for(lambda: q1("SELECT count(*) FROM chat_messages WHERE external_id=:w", w=wid_img) == 1)
check("фото записано", ok)
if ok:
    row = qall("SELECT msg_type, text FROM chat_messages WHERE external_id=:w", w=wid_img)[0]
    check("msg_type=image, подпись сохранена как текст",
          row[0] == "image" and row[1] == "Вот такой автомат", str(row))

st, wid_doc = webhook(P1, mtype="document", extra={
    "document": {"id": "media-2", "filename": "Спецификация.xlsx", "caption": "", "url": ""}})
ok = wait_for(lambda: q1("SELECT count(*) FROM chat_messages WHERE external_id=:w", w=wid_doc) == 1)
check("документ записан", ok)
if ok:
    row = qall("SELECT msg_type, file_name FROM chat_messages WHERE external_id=:w", w=wid_doc)[0]
    check("msg_type=document, имя файла сохранено",
          row[0] == "document" and row[1] == "Спецификация.xlsx", str(row))

# Нажатие кнопки
st, wid_btn = webhook(P1, mtype="interactive", extra={
    "interactive": {"type": "button_reply",
                    "button_reply": {"id": "kp_electro", "title": "⚡ КП по электрике"}}})
ok = wait_for(lambda: q1("SELECT count(*) FROM chat_messages WHERE external_id=:w", w=wid_btn) == 1)
check("нажатие кнопки записано", ok)
if ok:
    row = qall("SELECT msg_type, text, extra FROM chat_messages WHERE external_id=:w", w=wid_btn)[0]
    check("msg_type=button и button_id в extra",
          row[0] == "button" and (row[2] or {}).get("button_id") == "kp_electro", str(row[:2]))

with open("/tmp/_p2.txt", "w") as f:
    f.write(f"{sum(1 for _, o, _ in _results if o)} {sum(1 for _, o, _ in _results if not o)}")
print("\nИТОГ ЧАСТИ 2: pass=%d fail=%d" % (sum(1 for _, o, _ in _results if o),
                                           sum(1 for _, o, _ in _results if not o)))
for n, o, d in _results:
    if not o:
        print("  ПРОВАЛ:", n, "—", d)
