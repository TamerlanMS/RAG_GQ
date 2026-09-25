import { useEffect, useRef } from "react";
import { api } from "../api.js";
import { splitPreview } from "../format.js";
import { notificationPermission } from "../notify/settings.js";
import { playMessageSound } from "../notify/sound.js";
import { faviconDataUrl, setTabUnread } from "../notify/tabBadge.js";

const INTERVAL_MS = 5000;

const TYPE_TEXT = {
  image: "Фото",
  document: "Документ",
  video: "Видео",
  audio: "Аудио",
  voice: "Голосовое сообщение",
  sticker: "Стикер",
  button: "Нажата кнопка",
};

// Таймер в выделенном Web Worker: Chrome в свёрнутой вкладке через 5 минут
// «усыпляет» обычные setTimeout до одного раза в минуту, а таймеры воркера —
// нет. Иначе уведомление приходило бы с опозданием до минуты.
function startTicker(ms, onTick) {
  try {
    const src = `setInterval(() => postMessage(0), ${ms});`;
    const url = URL.createObjectURL(new Blob([src], { type: "text/javascript" }));
    const worker = new Worker(url);
    worker.onmessage = onTick;
    return () => {
      worker.terminate();
      URL.revokeObjectURL(url);
    };
  } catch {
    const id = setInterval(onTick, ms);
    return () => clearInterval(id);
  }
}

/**
 * Следит за новыми сообщениями клиентов во ВСЕХ диалогах (без фильтров
 * и поиска из списка слева) и сообщает о них: всплывающее уведомление,
 * звук, счётчик на вкладке. Работает и когда вкладка свёрнута.
 *
 * Новое сообщение = у диалога вырос unread_count. Его увеличивает только
 * входящее от клиента (ответы бота и менеджеров — нет).
 */
export function useNewMessageNotifier({ settings, activeIdRef, onOpenChat }) {
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const openRef = useRef(onOpenChat);
  openRef.current = onOpenChat;

  useEffect(() => {
    let prev = null; // chatId -> unread_count; null до первого опроса
    let busy = false;
    let stopped = false;
    const icon = faviconDataUrl();

    function notify(chat) {
      const s = settingsRef.current;
      const name = chat.display_name || chat.phone || chat.external_id;
      // Смотрите прямо на этот диалог — он и так перед глазами.
      const lookingAtIt = chat.id === activeIdRef.current && document.visibilityState === "visible";
      if (lookingAtIt) return;

      if (s.sound) playMessageSound();
      if (!s.desktop || notificationPermission() !== "granted") return;

      let body = "Новое сообщение";
      if (s.preview) {
        // Текст — из последнего сообщения КЛИЕНТА: в общем превью к этому
        // моменту уже может стоять ответ бота.
        let text = (chat.last_in_text || "").trim();
        let type = chat.last_in_type;
        if (!type && !text) ({ text, type } = splitPreview(chat.last_message_preview));
        const label = type && type !== "text" ? TYPE_TEXT[type] : null;
        body = label && text ? `${label}: ${text}` : text || label || body;
        if (body.length > 180) body = `${body.slice(0, 177)}…`;
      }
      try {
        const n = new Notification(s.preview ? name : "GQ Group — консоль", {
          body,
          tag: `gq-chat-${chat.id}`, // новое от того же клиента заменяет старое
          renotify: true,
          icon,
          silent: true, // звук играем сами — по настройке «Звук»
        });
        n.onclick = () => {
          window.focus();
          openRef.current?.(chat.id);
          n.close();
        };
      } catch {
        /* браузер отказал (например, iOS Safari без установки на экран) */
      }
    }

    async function poll() {
      if (busy || stopped) return;
      busy = true;
      try {
        const data = await api.chats();
        if (stopped) return;
        const items = data.items || [];
        setTabUnread(data.unread_total ?? items.reduce((sum, c) => sum + (c.unread_count || 0), 0));

        const next = new Map(items.map((c) => [c.id, c.unread_count || 0]));
        if (prev) {
          // Сначала самые свежие — при пачке уведомлений новое сверху.
          for (const chat of items) {
            const before = prev.has(chat.id) ? prev.get(chat.id) : 0;
            if ((chat.unread_count || 0) > before) notify(chat);
          }
        }
        prev = next;
      } catch {
        /* нет сети или 401 (api.js сам вернёт на экран входа) — попробуем в следующий раз */
      } finally {
        busy = false;
      }
    }

    poll();
    const stop = startTicker(INTERVAL_MS, poll);
    return () => {
      stopped = true;
      stop();
      setTabUnread(0);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
