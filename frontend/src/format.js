// Форматирование для интерфейса.

export function initials(name) {
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

/** Время для списка чатов: сегодня — часы, иначе дата. */
export function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  return sameDay
    ? d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

/** Точное время под пузырём сообщения. */
export function formatClock(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

/** Разделитель дат в треде. */
export function formatDateSeparator(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const sameDate = (a, b) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  if (sameDate(d, today)) return "Сегодня";
  if (sameDate(d, yesterday)) return "Вчера";
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "long", year: "numeric" });
}

export function dayKey(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toDateString();
}

// Спокойная палитра для аватаров: у каждого клиента свой постоянный цвет —
// по нему быстрее находишь нужный чат в списке.
const AVATAR_COLORS = ["#4f9d8f", "#5b8def", "#c47ad0", "#e0875a", "#4aa3c7", "#9c8cd9", "#d46a7e", "#6fae5c"];

export function avatarColor(seed) {
  const s = String(seed || "?");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

// Превью последнего сообщения приходит с сервера с эмодзи-подписью типа
// (src/common/chat_store.py, _TYPE_LABELS: «📷 Фото», «📎 Документ», …).
// Распознаём её и отдаём тип отдельно — вместо эмодзи рисуется SVG-иконка.
const PREVIEW_PREFIXES = [
  ["📷", "image"],
  ["📎", "document"],
  ["🎥", "video"],
  ["🎵", "audio"],
  ["🎤", "voice"],
  ["🏷", "sticker"],
  ["🔘", "button"],
  ["ℹ️", "system"],
  ["ℹ", "system"],
];

export function splitPreview(preview) {
  const text = String(preview || "").trim();
  for (const [emoji, type] of PREVIEW_PREFIXES) {
    if (text.startsWith(emoji)) {
      return { type, text: text.slice(emoji.length).replace(/^️/, "").trim() };
    }
  }
  return { type: null, text };
}
