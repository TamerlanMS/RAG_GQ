# -*- coding: utf-8 -*-
"""Часть 3: API чатов, перехват, ответ, гейт бота."""
from __future__ import annotations

import os
import time
import uuid

import httpx
from sqlalchemy import text as sqltext

BASE = "http://localhost:8000"
API = BASE + "/api/v1/console"
WEBHOOK_TOKEN = os.getenv("GUPSHUP_VERIFY_TOKEN", "gqgroup_verify")
_results = []

PW = {"director": "TestPass_director_123", "sabieva": "TestPass_sabieva_123",
      "zhenibek": "TestPass_zhenibek_123", "kalbaeva": "NewPass_kalbaeva_456"}


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


def webhook(phone, body="", wamid=None, name="Клиент"):
    mid = wamid or ("wamid." + uuid.uuid4().hex[:12])
    payload = {"entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"profile": {"name": name}, "wa_id": phone}],
        "messages": [{"from": phone, "id": mid, "type": "text", "text": {"body": body}}]}}]}]}
    httpx.post(BASE + "/api/v1/whatsapp/webhook", params={"token": WEBHOOK_TOKEN},
              json=payload, timeout=25)
    return mid


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def tok(code, phone):
    r = httpx.post(API + "/login", json={"phone": phone, "password": PW[code]}, timeout=25)
    return r.json()["access_token"]


def wait_for(fn, timeout=25, interval=0.5):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(interval)
    return False


T_KAL = tok("kalbaeva", "87750866676")
T_SAB = tok("sabieva", "87711668284")

# ─────────────────────────────────────────────────────────────
section("5. GET /chats — список, поиск, фильтры, пагинация")

# Набор самодостаточный: сносим оба чата и создаём заново, иначе абсолютные
# проверки (счётчики системных сообщений, пагинация) ломаются на повторном прогоне.
P1 = "77011110001"
P2 = "77022220002"
_s = db()
try:
    _s.execute(sqltext("DELETE FROM chat_messages WHERE chat_id IN "
                       "(SELECT id FROM chats WHERE external_id IN (:a, :b))"), {"a": P1, "b": P2})
    _s.execute(sqltext("DELETE FROM chats WHERE external_id IN (:a, :b)"), {"a": P1, "b": P2})
    _s.commit()
finally:
    _s.close()

# P1 — три входящих, чтобы хватило сообщений на проверки пагинации
for _t in ("Здравствуйте, нужен кабель ВВГ 3х2.5",
           "И ещё лоток 200х50",
           "Сколько будет стоить доставка?"):
    webhook(P1, _t, name="Алия Нурлан")
    time.sleep(9)
webhook(P2, "Добрый день, интересует лоток перфорированный", name="Бахыт Ораз")
wait_for(lambda: q1("SELECT count(*) FROM chats WHERE external_id=:p", p=P2) == 1)
time.sleep(9)

r = httpx.get(API + "/chats", headers=auth(T_KAL), timeout=25)
check("GET /chats -> 200", r.status_code == 200, f"HTTP {r.status_code}")
data = r.json()
check("есть поле total", "total" in data and data["total"] >= 2, str(data.get("total")))
ids = [c["id"] for c in data["items"]]
check("свежий чат сверху (сортировка по last_message_at DESC)",
      data["items"][0]["external_id"] == P2, data["items"][0]["external_id"])
check("в выдаче есть unread_count и is_taken_over",
      all(k in data["items"][0] for k in ("unread_count", "is_taken_over", "taken_over_by")))

check("GET /chats без токена -> 401",
      httpx.get(API + "/chats", timeout=25).status_code == 401)

# Поиск
r = httpx.get(API + "/chats", params={"query": "Бахыт"}, headers=auth(T_KAL), timeout=25).json()
check("поиск по имени", len(r["items"]) == 1 and r["items"][0]["external_id"] == P2,
      f"{len(r['items'])} результатов")
r = httpx.get(API + "/chats", params={"query": "77022"}, headers=auth(T_KAL), timeout=25).json()
check("поиск по номеру (external_id/phone)", len(r["items"]) == 1, f"{len(r['items'])} результатов")
r = httpx.get(API + "/chats", params={"query": "нетакогоклиента"}, headers=auth(T_KAL), timeout=25).json()
check("поиск без совпадений -> пусто", r["items"] == [] and r["total"] == 0)

# Пагинация
r = httpx.get(API + "/chats", params={"limit": 1}, headers=auth(T_KAL), timeout=25).json()
check("limit=1 отдаёт 1 элемент, total — общее число",
      len(r["items"]) == 1 and r["total"] >= 2, f"items={len(r['items'])} total={r['total']}")
r2 = httpx.get(API + "/chats", params={"limit": 1, "offset": 1}, headers=auth(T_KAL), timeout=25).json()
check("offset сдвигает выборку", r2["items"][0]["id"] != r["items"][0]["id"])
check("limit=0 отклоняется (ge=1)",
      httpx.get(API + "/chats", params={"limit": 0}, headers=auth(T_KAL), timeout=25).status_code == 422)

chat1 = q1("SELECT id FROM chats WHERE external_id=:p", p=P1)
chat2 = q1("SELECT id FROM chats WHERE external_id=:p", p=P2)

# ─────────────────────────────────────────────────────────────
section("6. GET /chats/{id}/messages — курсоры и пагинация")

r = httpx.get(f"{API}/chats/{chat1}/messages", headers=auth(T_KAL), timeout=25)
check("messages -> 200", r.status_code == 200)
msgs = r.json()["items"]
check("сообщения по возрастанию id", [m["id"] for m in msgs] == sorted(m["id"] for m in msgs))
check("extra НЕ отдаётся наружу", all("extra" not in m for m in msgs))
check("есть author_manager_name в схеме", "author_manager_name" in msgs[0])

last = msgs[-1]["id"]
r = httpx.get(f"{API}/chats/{chat1}/messages", params={"after_id": last},
              headers=auth(T_KAL), timeout=25).json()
check("after_id=последний -> пусто (горячий путь поллинга)", r["items"] == [])

r = httpx.get(f"{API}/chats/{chat1}/messages", params={"after_id": msgs[0]["id"]},
              headers=auth(T_KAL), timeout=25).json()
check("after_id=первый -> остальные", len(r["items"]) == len(msgs) - 1,
      f"{len(r['items'])} из {len(msgs) - 1}")

r = httpx.get(f"{API}/chats/{chat1}/messages", params={"limit": 2},
              headers=auth(T_KAL), timeout=25).json()
check("limit=2 -> 2 последних", len(r["items"]) == 2)
check("has_more=true при обрезке", r["has_more"] is True, str(r["has_more"]))
oldest_of_page = r["items"][0]["id"]
r_before = httpx.get(f"{API}/chats/{chat1}/messages",
                     params={"limit": 2, "before_id": oldest_of_page},
                     headers=auth(T_KAL), timeout=25).json()
check("before_id листает вверх",
      all(m["id"] < oldest_of_page for m in r_before["items"]) and r_before["items"],
      str([m["id"] for m in r_before["items"]]))

check("before_id и after_id вместе -> 422",
      httpx.get(f"{API}/chats/{chat1}/messages", params={"after_id": 1, "before_id": 5},
                headers=auth(T_KAL), timeout=25).status_code == 422)
check("несуществующий чат -> 404",
      httpx.get(f"{API}/chats/999999/messages", headers=auth(T_KAL), timeout=25).status_code == 404)

# /read
check("unread до /read > 0", q1("SELECT unread_count FROM chats WHERE id=:i", i=chat1) > 0)
rr = httpx.post(f"{API}/chats/{chat1}/read", headers=auth(T_KAL), timeout=25)
check("/read -> 204", rr.status_code == 204, f"HTTP {rr.status_code}")
check("unread обнулён", q1("SELECT unread_count FROM chats WHERE id=:i", i=chat1) == 0)

# ─────────────────────────────────────────────────────────────
section("7. ПЕРЕХВАТ")

r = httpx.post(f"{API}/chats/{chat1}/takeover", headers=auth(T_KAL), json={}, timeout=25)
check("takeover -> 200", r.status_code == 200, f"HTTP {r.status_code}")
body = r.json()
check("чат помечен перехваченным", body["chat"]["is_taken_over"] is True)
check("указан держатель", body["chat"]["taken_over_by"]["name"].startswith("Калбаева"),
      str(body["chat"]["taken_over_by"]))
sys_cnt = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='system'", c=chat1)
check("создано системное сообщение", sys_cnt == 1, f"{sys_cnt} шт.")

r = httpx.post(f"{API}/chats/{chat1}/takeover", headers=auth(T_KAL), json={}, timeout=25)
check("повторный takeover тем же менеджером идемпотентен", r.status_code == 200)
check("второе системное сообщение НЕ создано",
      q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='system'", c=chat1) == 1)

r = httpx.post(f"{API}/chats/{chat1}/takeover", headers=auth(T_SAB), json={}, timeout=25)
check("другой менеджер без force -> 409", r.status_code == 409, f"HTTP {r.status_code}")
check("в тексте ошибки указан текущий держатель", "Калбаева" in r.json()["detail"],
      r.json()["detail"])

r = httpx.post(f"{API}/chats/{chat1}/reply", headers=auth(T_SAB),
               json={"text": "Пробую ответить в чужой диалог"}, timeout=25)
check("reply в чужой перехваченный диалог -> 409", r.status_code == 409, f"HTTP {r.status_code}")

r = httpx.post(f"{API}/chats/{chat1}/takeover", headers=auth(T_SAB),
               json={"force": True}, timeout=25)
check("force=true перехватывает", r.status_code == 200 and
      r.json()["chat"]["taken_over_by"]["name"].startswith("Сабиева"),
      str(r.json()["chat"]["taken_over_by"]))

# Возвращаем Калбаевой
httpx.post(f"{API}/chats/{chat1}/release", headers=auth(T_SAB), timeout=25)
httpx.post(f"{API}/chats/{chat1}/takeover", headers=auth(T_KAL), json={}, timeout=25)

# ─────────────────────────────────────────────────────────────
section("8. ГЕЙТ БОТА ПРИ ПЕРЕХВАТЕ")

n_before = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c", c=chat1)
bot_before = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='bot'", c=chat1)
wid = webhook(P1, "Вопрос при перехваченном диалоге")
ok = wait_for(lambda: q1("SELECT count(*) FROM chat_messages WHERE external_id=:w", w=wid) == 1)
check("входящее записано даже при перехвате", ok)
time.sleep(10)
bot_after = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='bot'", c=chat1)
check("бот НЕ ответил при перехвате", bot_after == bot_before,
      f"было {bot_before}, стало {bot_after}")
check("unread вырос (менеджер должен увидеть)",
      q1("SELECT unread_count FROM chats WHERE id=:i", i=chat1) >= 1)

# ─────────────────────────────────────────────────────────────
section("9. ОТВЕТ МЕНЕДЖЕРА")

r = httpx.post(f"{API}/chats/{chat1}/reply", headers=auth(T_KAL),
               json={"text": "Здравствуйте! Кабель есть, 320 тг/м."}, timeout=30)
check("reply -> 200", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
body = r.json()
check("статус sent", body["status"] == "sent", str(body.get("status")))
check("вернулось созданное сообщение", body.get("message") is not None)
if body.get("message"):
    m = body["message"]
    check("author=manager", m["author"] == "manager", m["author"])
    check("указано имя менеджера", (m.get("author_manager_name") or "").startswith("Калбаева"),
          str(m.get("author_manager_name")))
    check("author_manager_id проставлен в БД",
          q1("SELECT author_manager_id FROM chat_messages WHERE id=:i", i=m["id"]) is not None)

# История бота (_wa_history) — dict в памяти процесса uvicorn, из этого процесса
# он не виден. Проверяется отдельно: юнит-тест хелперов + отсутствие warning
# "Не удалось добавить ответ менеджера в историю бота" в логах сервера.

# Автоперехват при ответе
httpx.post(f"{API}/chats/{chat2}/release", headers=auth(T_KAL), timeout=25)
check("chat2 изначально не перехвачен",
      q1("SELECT is_taken_over FROM chats WHERE id=:i", i=chat2) is False)
sys2_before = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='system'", c=chat2)
r = httpx.post(f"{API}/chats/{chat2}/reply", headers=auth(T_KAL),
               json={"text": "Отвечаю без явного перехвата"}, timeout=30)
check("reply на неперехваченный чат -> 200", r.status_code == 200, f"HTTP {r.status_code}")
check("авто-перехват сработал (иначе бот ответил бы следом)",
      q1("SELECT is_taken_over FROM chats WHERE id=:i", i=chat2) is True)
sys2_after = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='system'", c=chat2)
check("авто-перехват добавил ровно одно системное сообщение",
      sys2_after == sys2_before + 1, f"{sys2_before} -> {sys2_after}")
sys_id = q1("SELECT max(id) FROM chat_messages WHERE chat_id=:c AND author='system'", c=chat2)
mgr_id = q1("SELECT max(id) FROM chat_messages WHERE chat_id=:c AND author='manager'", c=chat2)
check("системное сообщение идёт ПЕРЕД сообщением менеджера", sys_id < mgr_id,
      f"system={sys_id} manager={mgr_id}")

r = httpx.post(f"{API}/chats/{chat2}/reply", headers=auth(T_KAL),
               json={"text": ""}, timeout=25)
check("пустой текст -> 422", r.status_code == 422, f"HTTP {r.status_code}")
r = httpx.post(f"{API}/chats/{chat2}/reply", headers=auth(T_KAL),
               json={"text": "x" * 4001}, timeout=25)
check("текст длиннее 4000 -> 422", r.status_code == 422, f"HTTP {r.status_code}")

# ─────────────────────────────────────────────────────────────
section("10. ВОЗВРАТ БОТУ")

sys_before = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='system'", c=chat1)
r = httpx.post(f"{API}/chats/{chat1}/release", headers=auth(T_KAL), timeout=25)
check("release -> 200", r.status_code == 200)
check("флаг снят", r.json()["chat"]["is_taken_over"] is False)
sys_after = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='system'", c=chat1)
check("release добавил ровно одно системное сообщение", sys_after == sys_before + 1,
      f"{sys_before} -> {sys_after}")
r = httpx.post(f"{API}/chats/{chat1}/release", headers=auth(T_KAL), timeout=25)
check("повторный release идемпотентен", r.status_code == 200 and
      r.json()["status"] == "already_released", r.json()["status"])
check("повторный release не добавил системного сообщения",
      q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='system'", c=chat1)
      == sys_after)

bot_before = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='bot'", c=chat1)
btn_before = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND msg_type='button' "
                "AND author='bot'", c=chat1)
webhook(P1, "Вопрос после возврата боту")
ok = wait_for(lambda: q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='bot'",
                         c=chat1) > bot_before, timeout=30)
bot_now = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND author='bot'", c=chat1)
check("бот снова отвечает после release", ok, f"было {bot_before}, стало {bot_now}")
btn_after = q1("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND msg_type='button' "
               "AND author='bot'", c=chat1)
check("приветственное меню НЕ повторилось (защита _greeted)", btn_after == btn_before,
      f"кнопочных сообщений было {btn_before}, стало {btn_after}")

print("\nИТОГ ЧАСТИ 3: pass=%d fail=%d" % (sum(1 for _, o, _ in _results if o),
                                           sum(1 for _, o, _ in _results if not o)))
for n, o, d in _results:
    if not o:
        print("  ПРОВАЛ:", n, "—", d)
