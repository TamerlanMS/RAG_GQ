import { useEffect, useRef, useState } from "react";
import { notificationPermission, notificationsSupported } from "../notify/settings.js";
import { playMessageSound, unlockAudio } from "../notify/sound.js";
import { faviconDataUrl } from "../notify/tabBadge.js";
import { IconBell, IconBellOff, IconX } from "./icons.jsx";

function Toggle({ checked, onChange, label, hint, disabled }) {
  return (
    <label className={`toggle-row${disabled ? " is-disabled" : ""}`}>
      <span className="toggle-text">
        <span className="toggle-label">{label}</span>
        {hint && <span className="toggle-hint">{hint}</span>}
      </span>
      <input
        type="checkbox"
        className="toggle"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
    </label>
  );
}

async function askPermission() {
  if (!notificationsSupported()) return "unsupported";
  try {
    return await Notification.requestPermission();
  } catch {
    return Notification.permission;
  }
}

export function NotifySettings({ settings, onChange }) {
  const [open, setOpen] = useState(false);
  const [permission, setPermission] = useState(notificationPermission);
  const panelRef = useRef(null);

  // Закрыть панель по клику вне неё и по Esc.
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const set = (patch) => onChange({ ...settings, ...patch });
  const muted = !settings.sound && !(settings.desktop && permission === "granted");

  async function enableDesktop(value) {
    if (value && permission === "default") setPermission(await askPermission());
    set({ desktop: value });
  }

  function test() {
    unlockAudio();
    if (settings.sound) playMessageSound();
    if (settings.desktop && notificationPermission() === "granted") {
      new Notification(settings.preview ? "Тестовый клиент" : "GQ Group — консоль", {
        body: settings.preview ? "Так будет выглядеть уведомление о новом сообщении" : "Новое сообщение",
        icon: faviconDataUrl(),
        tag: "gq-test",
        silent: true,
      });
    }
  }

  return (
    <div className="notify-wrap" ref={panelRef}>
      <button
        type="button"
        className="icon-btn"
        onClick={() => setOpen((v) => !v)}
        title="Уведомления"
        aria-expanded={open}
      >
        {muted ? <IconBellOff /> : <IconBell />}
      </button>

      {open && (
        <div className="notify-panel" role="dialog" aria-label="Настройки уведомлений">
          <div className="notify-panel-head">
            <span>Уведомления</span>
            <button type="button" className="icon-btn icon-btn-sm" onClick={() => setOpen(false)} title="Закрыть">
              <IconX size={16} />
            </button>
          </div>

          <Toggle
            label="Всплывающие уведомления"
            hint={
              permission === "unsupported"
                ? "Недоступно на этом адресе — откройте https://bot.gqe-online.kz/console/"
                : permission === "denied"
                  ? "Запрещены в браузере — разрешите в настройках сайта (значок слева от адреса)"
                  : "Имя клиента и сообщение в углу экрана, даже когда вкладка свёрнута"
            }
            checked={settings.desktop && permission === "granted"}
            disabled={permission === "unsupported" || permission === "denied"}
            onChange={enableDesktop}
          />
          <Toggle
            label="Звуковой сигнал"
            hint="Короткий сигнал при новом сообщении клиента"
            checked={settings.sound}
            onChange={(v) => {
              unlockAudio();
              set({ sound: v });
            }}
          />
          <Toggle
            label="Показывать текст сообщения"
            hint="Выключите, если экран видят посторонние: будет только «Новое сообщение»"
            checked={settings.preview}
            onChange={(v) => set({ preview: v })}
          />
          <Toggle
            label="Счётчик на вкладке"
            hint="Число непрочитанных в названии вкладки и на её значке — всегда включён"
            checked
            disabled
            onChange={() => {}}
          />

          <button type="button" className="btn-outline notify-test" onClick={test}>
            Проверить
          </button>
        </div>
      )}
    </div>
  );
}

// Полоска-приглашение над списком чатов: разрешение браузер даёт только
// по нажатию кнопки, поэтому один раз спрашиваем явно.
export function NotifyPrompt({ settings, onChange }) {
  const [permission, setPermission] = useState(notificationPermission);
  const [hidden, setHidden] = useState(() => {
    try {
      return localStorage.getItem("gq_console_notify_prompt") === "hidden";
    } catch {
      return false;
    }
  });

  if (hidden || permission !== "default" || !settings.desktop) return null;

  function dismiss() {
    setHidden(true);
    try {
      localStorage.setItem("gq_console_notify_prompt", "hidden");
    } catch {
      /* ничего */
    }
  }

  return (
    <div className="notify-prompt">
      <span className="notify-prompt-icon">
        <IconBell size={18} />
      </span>
      <span className="notify-prompt-text">Получать уведомления о новых сообщениях клиентов?</span>
      <button
        type="button"
        className="btn-primary btn-sm"
        onClick={async () => {
          unlockAudio();
          const p = await askPermission();
          setPermission(p);
          onChange({ ...settings, desktop: p === "granted" });
        }}
      >
        Включить
      </button>
      <button type="button" className="icon-btn icon-btn-sm" onClick={dismiss} title="Не сейчас">
        <IconX size={16} />
      </button>
    </div>
  );
}
