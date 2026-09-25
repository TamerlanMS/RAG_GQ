import { useEffect, useRef } from "react";
import { dayKey, formatClock, formatDateSeparator } from "../format.js";
import { IconBot, IconDownload, IconFile, TypeIcon } from "./icons.jsx";

const TYPE_LABEL = {
  image: "Фото",
  document: "Документ",
  video: "Видео",
  audio: "Аудио",
  voice: "Голосовое",
  sticker: "Стикер",
};

function formatSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

function fileExt(name) {
  const m = /\.([a-z0-9]{1,5})$/i.exec(name || "");
  return m ? m[1].toUpperCase() : "";
}

// Вложение, скачанное на сервер. media_url — подписанная ссылка на
// /api/v1/console/media/{id}, её можно ставить прямо в src.
function Attachment({ msg }) {
  const label = TYPE_LABEL[msg.msg_type] || "Файл";
  const url = msg.media_url;

  if (!url) {
    // Файл ещё докачивается, не скачался, или сообщение старше этой функции.
    return (
      <div className="bubble-attachment">
        <TypeIcon type={msg.msg_type} />
        <span>
          {label}
          {msg.file_name ? ` — ${msg.file_name}` : ""}
          {!msg.pending && <span className="attachment-missing"> · файл недоступен</span>}
        </span>
      </div>
    );
  }

  const mime = msg.media_mime || "";
  const isImage = ["image", "sticker"].includes(msg.msg_type) && mime.startsWith("image/");

  if (isImage) {
    return (
      <a href={url} target="_blank" rel="noreferrer" className="attachment-image-link">
        <img
          src={url}
          alt={label}
          loading="lazy"
          className={msg.msg_type === "sticker" ? "attachment-sticker" : "attachment-image"}
        />
      </a>
    );
  }
  if (msg.msg_type === "video" && mime.startsWith("video/")) {
    return <video src={url} controls preload="metadata" className="attachment-video" />;
  }
  if (["audio", "voice"].includes(msg.msg_type) && mime.startsWith("audio/")) {
    return (
      <div className="attachment-audio-row">
        <span className={`attachment-audio-icon${msg.msg_type === "voice" ? " is-voice" : ""}`}>
          <TypeIcon type={msg.msg_type} size={18} />
        </span>
        <audio src={url} controls preload="metadata" className="attachment-audio" />
      </div>
    );
  }

  // Документ либо медиа в формате, который браузер не покажет, — карточкой.
  const name = msg.file_name || label;
  const ext = fileExt(msg.file_name);
  return (
    <a href={url} target="_blank" rel="noreferrer" download={msg.file_name || undefined} className="attachment-file">
      <span className="attachment-file-icon">
        <IconFile size={26} strokeWidth={1.5} />
      </span>
      <span className="attachment-file-meta">
        <span className="attachment-file-name">{name}</span>
        <span className="attachment-file-size">
          {[ext, formatSize(msg.media_size)].filter(Boolean).join(" · ")}
        </span>
      </span>
      <span className="attachment-file-download">
        <IconDownload size={18} />
      </span>
    </a>
  );
}

function MessageBubble({ msg, first }) {
  if (msg.author === "system") {
    return <div className="system-note">{msg.text}</div>;
  }

  const side = msg.direction === "in" ? "left" : "right";
  const kind = msg.author; // client | bot | manager
  const hasAttachment = msg.msg_type in TYPE_LABEL;
  // Время поверх картинки — только у фото и стикеров: у видео оно
  // перекрыло бы панель управления плеера.
  const mediaOnly = hasAttachment && !msg.text && ["image", "sticker"].includes(msg.msg_type);

  return (
    <div className={`bubble-row is-${side}${first ? " is-first" : ""}`}>
      <div className={`bubble is-${kind}${first ? " has-tail" : ""}${mediaOnly ? " is-media" : ""}`}>
        {first && kind === "manager" && msg.author_manager_name && (
          <div className="bubble-author">{msg.author_manager_name}</div>
        )}
        {first && kind === "bot" && (
          <div className="bubble-author is-bot">
            <IconBot size={13} />
            Бот
          </div>
        )}
        {hasAttachment && <Attachment msg={msg} />}
        {msg.text && <span className="bubble-text">{msg.text}</span>}
        <span className="bubble-time">
          {msg.pending ? "отправляется…" : formatClock(msg.created_at)}
        </span>
      </div>
    </div>
  );
}

export function MessageThread({ messages, loading }) {
  const endRef = useRef(null);
  const containerRef = useRef(null);
  const stickToBottomRef = useRef(true);

  // Автопрокрутка вниз — но только если менеджер уже внизу.
  // Иначе поллинг дёргал бы его вверх во время чтения истории.
  function onScroll() {
    const el = containerRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  }

  useEffect(() => {
    if (stickToBottomRef.current) {
      endRef.current?.scrollIntoView({ block: "end" });
    }
  }, [messages]);

  // Фото и видео догружаются уже после прокрутки вниз и сдвигают ленту —
  // чат открывался бы не на последнем сообщении. Пока менеджер внизу,
  // после каждой догрузки снова прижимаемся к концу. load/loadedmetadata
  // не всплывают, поэтому слушаем на фазе перехвата.
  useEffect(() => {
    // Открыт другой чат — он всегда начинается с последнего сообщения,
    // даже если в предыдущем менеджер листал вверх.
    if (loading) stickToBottomRef.current = true;
    const el = containerRef.current;
    if (!el) return undefined;
    const pin = () => {
      if (stickToBottomRef.current) el.scrollTop = el.scrollHeight;
    };
    el.addEventListener("load", pin, true);
    el.addEventListener("loadedmetadata", pin, true);
    return () => {
      el.removeEventListener("load", pin, true);
      el.removeEventListener("loadedmetadata", pin, true);
    };
  }, [loading]);

  if (loading) {
    return (
      <div className="thread">
        <div className="empty-hint">Загрузка…</div>
      </div>
    );
  }

  let lastDay = null;
  let prev = null;

  return (
    <div className="thread" ref={containerRef} onScroll={onScroll}>
      <div className="thread-inner">
        {messages.length === 0 && <div className="empty-hint">В этом диалоге пока нет сообщений</div>}
        {messages.map((m) => {
          const key = dayKey(m.created_at);
          const separator = key && key !== lastDay ? formatDateSeparator(m.created_at) : null;
          lastDay = key || lastDay;
          // «Хвостик» и подпись автора — только у первого сообщения серии
          // подряд от одного автора, как в WhatsApp.
          const first =
            Boolean(separator) ||
            !prev ||
            prev.author === "system" ||
            prev.author !== m.author ||
            prev.direction !== m.direction ||
            (m.author === "manager" && prev.author_manager_name !== m.author_manager_name);
          prev = m;
          return (
            <div key={m.id}>
              {separator && (
                <div className="date-separator">
                  <span>{separator}</span>
                </div>
              )}
              <MessageBubble msg={m} first={first} />
            </div>
          );
        })}
        <div ref={endRef} />
      </div>
    </div>
  );
}
