import { useEffect, useRef, useState } from "react";
import { IconEmojiFlags, IconEmojiGesture, IconEmojiHeart, IconEmojiRecent, IconEmojiSmile, IconEmojiWork } from "./icons.jsx";

// Подобранный набор вместо библиотеки на сотни килобайт: частые смайлики
// плюс раздел «Работа» — то, что реально пишут клиентам. Рисует их шрифт
// системы (как и сам WhatsApp у клиента).
const CATEGORIES = [
  {
    key: "smile",
    title: "Смайлы",
    Icon: IconEmojiSmile,
    emojis:
      "😀 😃 😄 😁 😆 😅 😂 🤣 😊 🙂 😉 😌 😍 🥰 😘 😋 😎 🤩 🥳 🤗 🤔 🤨 😐 😑 😶 🙄 😏 😬 😮 😯 😲 😳 🥺 😢 😭 😤 😡 🤯 😱 😴 🤒 🤧 😇 🤝 🙈 🙊",
  },
  {
    key: "gesture",
    title: "Жесты",
    Icon: IconEmojiGesture,
    emojis: "👍 👎 👌 ✌️ 🤞 🤟 👋 🤚 ✋ 🖐️ 👏 🙌 🙏 💪 👉 👈 👆 👇 ☝️ ✍️ 🤙 🫡 🤷 🤷‍♂️ 🤷‍♀️ 🙋 🙋‍♂️ 🙋‍♀️ 💁 💁‍♀️",
  },
  {
    key: "heart",
    title: "Символы",
    Icon: IconEmojiHeart,
    emojis: "❤️ 🧡 💛 💚 💙 💜 🤍 💯 🔥 ✨ ⭐ 🌟 🎉 🎊 🎁 ✅ ☑️ ✔️ ❌ ❗ ❓ ⚠️ ⛔ 🆗 🆕 🔝 ➡️ ⬅️ ⬆️ ⬇️ 🔴 🟢 🟡 🔵",
  },
  {
    key: "work",
    title: "Работа",
    Icon: IconEmojiWork,
    emojis:
      "📦 🚚 🚛 🏭 🏢 🏗️ ⚡ 🔌 💡 🔋 🔧 🔨 🛠️ ⚙️ 🧰 📏 📐 🧾 📄 📃 📑 📋 📎 📌 📍 🗂️ 📁 💰 💵 💳 🏦 📈 📉 📊 ⏳ ⌛ ⏰ 📅 🗓️ 📞 ☎️ 📱 💻 🖨️ ✉️ 📧 📬 🔍 🔒 🔑",
  },
  {
    key: "flags",
    title: "Флаги",
    Icon: IconEmojiFlags,
    emojis: "🇰🇿 🇷🇺 🇺🇿 🇰🇬 🇨🇳 🇹🇷 🇩🇪 🇮🇹 🇺🇸 🇬🇧 🇪🇺 🏁 🚩",
  },
].map((c) => ({ ...c, list: c.emojis.split(" ").filter(Boolean) }));

const RECENT_KEY = "gq_console_recent_emoji";
const RECENT_MAX = 24;

function loadRecent() {
  try {
    const v = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(v) ? v.slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

function saveRecent(list) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  } catch {
    /* приватный режим */
  }
}

/**
 * Панель смайликов над полем ввода. Остаётся открытой после выбора —
 * можно набрать несколько подряд; закрывается по Esc, клику мимо или кнопке.
 */
export function EmojiPicker({ onPick, onClose, anchorRef }) {
  const [recent, setRecent] = useState(loadRecent);
  const [tab, setTab] = useState(() => (loadRecent().length ? "recent" : "smile"));
  const panelRef = useRef(null);

  useEffect(() => {
    const onDown = (e) => {
      if (panelRef.current?.contains(e.target) || anchorRef?.current?.contains(e.target)) return;
      onClose();
    };
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose, anchorRef]);

  function pick(emoji) {
    const next = [emoji, ...recent.filter((e) => e !== emoji)].slice(0, RECENT_MAX);
    setRecent(next);
    saveRecent(next);
    onPick(emoji);
  }

  const tabs = [
    ...(recent.length ? [{ key: "recent", title: "Недавние", Icon: IconEmojiRecent, list: recent }] : []),
    ...CATEGORIES,
  ];
  const current = tabs.find((t) => t.key === tab) || tabs[0];

  return (
    <div className="emoji-panel" ref={panelRef} role="dialog" aria-label="Смайлики">
      <div className="emoji-tabs" role="tablist">
        {tabs.map(({ key, title, Icon }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={current.key === key}
            className={`emoji-tab${current.key === key ? " is-active" : ""}`}
            onClick={() => setTab(key)}
            title={title}
          >
            <Icon size={18} />
          </button>
        ))}
      </div>
      <div className="emoji-title">{current.title}</div>
      <div className="emoji-grid">
        {current.list.map((e) => (
          <button
            key={e}
            type="button"
            className="emoji-cell"
            // mousedown, а не click: иначе поле ввода теряет фокус и позицию курсора.
            onMouseDown={(ev) => ev.preventDefault()}
            onClick={() => pick(e)}
          >
            {e}
          </button>
        ))}
      </div>
    </div>
  );
}
