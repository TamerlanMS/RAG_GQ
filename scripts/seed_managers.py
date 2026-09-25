"""
Создание менеджеров веб-консоли из списка config.MANAGERS.

Использование:
    # создать всех отсутствующих со случайными паролями и вывести их один раз
    docker compose exec api python scripts/seed_managers.py

    # задать/сбросить пароль конкретному менеджеру
    docker compose exec api python scripts/seed_managers.py --code kalbaeva --password 'НовыйПароль123'

    # посмотреть, что будет сделано, ничего не меняя
    docker compose exec api python scripts/seed_managers.py --dry-run

    # отключить в базе тех, кого убрали из config.MANAGERS (уволились)
    docker compose exec api python scripts/seed_managers.py --deactivate-missing

Скрипт идемпотентен: повторный запуск не сбрасывает уже заданные пароли.

Менеджеров НЕ удаляем, а отключаем (is_active=false): войти он больше не
сможет, но его ответы в переписке и строки статистики за прошлые периоды
остаются привязаны к нему. Вернули в config.MANAGERS — включится снова.

Пароли печатаются через print, а НЕ через logger — иначе они попадут
в logs/app.log (в src/common/logger.py включён файловый обработчик).
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common.auth import hash_password  # noqa: E402
from src.common.phone import normalize_phone  # noqa: E402
from src.db.chat_database import ChatBase, ChatSessionLocal, chat_engine, ensure_chat_database  # noqa: E402
from src.db.Models.manager_models import Manager  # noqa: E402
from src.settings.config import MANAGER_CHAT_IDS, MANAGERS  # noqa: E402


def _generate_password() -> str:
    return secrets.token_urlsafe(9)


def main() -> int:
    parser = argparse.ArgumentParser(description="Сидирование менеджеров веб-консоли")
    parser.add_argument("--code", help="Обработать только этого менеджера (director/kalbaeva/...)")
    parser.add_argument("--password", help="Задать конкретный пароль (иначе генерируется случайный)")
    parser.add_argument("--dry-run", action="store_true", help="Ничего не менять, только показать")
    parser.add_argument(
        "--deactivate-missing",
        action="store_true",
        help="Отключить в базе менеджеров, которых нет в config.MANAGERS (вход для них закроется)",
    )
    args = parser.parse_args()

    if args.password and not args.code:
        print("ОШИБКА: --password можно использовать только вместе с --code", file=sys.stderr)
        return 2

    targets = [m for m in MANAGERS if not args.code or m["id"] == args.code]
    if not targets:
        known = ", ".join(m["id"] for m in MANAGERS)
        print(f"ОШИБКА: менеджер '{args.code}' не найден. Известные: {known}", file=sys.stderr)
        return 2

    # Проверяем ВСЕ номера до записи: лучше упасть до изменений, чем на середине.
    normalized: dict = {}
    for m in targets:
        phone = normalize_phone(m["phone"])
        if not phone:
            print(
                f"ОШИБКА: не удалось разобрать номер менеджера '{m['id']}': {m['phone']!r}. "
                "Поправьте src/settings/config.py",
                file=sys.stderr,
            )
            return 1
        normalized[m["id"]] = phone

    ensure_chat_database()
    ChatBase.metadata.create_all(bind=chat_engine)

    db = ChatSessionLocal()
    created: list = []
    updated: list = []
    skipped: list = []
    try:
        for m in targets:
            code = m["id"]
            phone = normalized[code]
            existing = db.query(Manager).filter(Manager.code == code).one_or_none()

            if existing is None:
                raw = args.password or _generate_password()
                if args.dry_run:
                    print(f"[dry-run] СОЗДАЛ БЫ: {code} ({m['name']}) — {phone}")
                    continue
                db.add(
                    Manager(
                        code=code,
                        name=m["name"],
                        role=m["role"],
                        phone=phone,
                        password_hash=hash_password(raw),
                        tg_chat_id=(MANAGER_CHAT_IDS.get(code) or None),
                    )
                )
                created.append((m["name"], phone, raw))
                continue

            # Менеджер уже есть: освежаем справочные поля, пароль не трогаем...
            changes = []
            if existing.name != m["name"]:
                changes.append("name")
                existing.name = m["name"]
            if existing.role != m["role"]:
                changes.append("role")
                existing.role = m["role"]
            if existing.phone != phone:
                changes.append("phone")
                existing.phone = phone
            if not existing.is_active:
                changes.append("снова включён")
                existing.is_active = True

            # ...кроме случая, когда пароль задан явно.
            if args.password:
                changes.append("password")
                existing.password_hash = hash_password(args.password)

            if args.dry_run:
                print(f"[dry-run] ОБНОВИЛ БЫ: {code} — {', '.join(changes) or 'без изменений'}")
                continue

            if changes:
                updated.append((m["name"], phone, args.password if args.password else None))
            else:
                skipped.append(m["name"])

        deactivated: list = []
        if args.deactivate_missing:
            known = {m["id"] for m in MANAGERS}
            for extra in db.query(Manager).filter(Manager.is_active.is_(True)).all():
                if extra.code not in known:
                    if args.dry_run:
                        print(f"[dry-run] ОТКЛЮЧИЛ БЫ: {extra.code} ({extra.name})")
                        continue
                    extra.is_active = False
                    deactivated.append(extra.name)

        if args.dry_run:
            db.rollback()
            return 0

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if created:
        print("\n=== СОЗДАНЫ. Пароли показываются ОДИН раз — сохраните их сейчас ===")
        for name, phone, raw in created:
            print(f"  {name}\n    логин:  {phone}\n    пароль: {raw}\n")
    if updated:
        print("=== ОБНОВЛЕНЫ ===")
        for name, phone, raw in updated:
            suffix = f"  новый пароль: {raw}" if raw else ""
            print(f"  {name} — {phone}{suffix}")
    if skipped:
        print(f"=== БЕЗ ИЗМЕНЕНИЙ: {', '.join(skipped)} ===")
    if deactivated:
        print(f"=== ОТКЛЮЧЕНЫ (нет в config.MANAGERS): {', '.join(deactivated)} ===")
    if not (created or updated or skipped or deactivated):
        print("Нечего делать.")

    print("\nСменить пароль можно через POST /api/v1/console/me/password.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
