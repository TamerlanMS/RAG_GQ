import { useEffect, useRef } from "react";
import { dayKey, formatClock, formatDateSeparator } from "../format.js";

const TYPE_LABEL = {
  image: "📷 Фото",
  document: "📎 Документ",
  video: "🎥 Видео",
  audio: "🎵 Аудио",
  voice: "🎤 Голосовое",
  sticker: "🏷 Стикер",
};

function formatSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

// Вложение, скачанное на сервер. media_url — подписанная ссылка на
// /api/v1/console/media/{id}, её можно ставить прямо в src.
function Attachment({ msg }) {
  const label = TYPE_LABEL[msg.msg_type] || "📎 Файл";
  const url = msg.media_url;

  if (!url) {
    // Файл не скачался (или сообщение пришло до появления этой функции).
    return (
      <div className="bubble-attachment">
        {label}
        {msg.file_name ? ` — ${msg.file_name}` : ""}
        <span className="attachment-missing"> · файл недоступен</span>
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
    return <audio src={url} controls preload="metadata" className="attachment-audio" />;
  }

  // Документ либо медиа в формате, который браузер не покажет, — ссылкой.
  const name = msg.file_name || label;
  return (
    <a href={url} target="_blank" rel="noreferrer" download={msg.file_name || undefined} className="attachment-file">
      <span className="attachment-file-icon">📎</span>
      <span className="attachment-file-meta">
        <span className="attachment-file-name">{name}</span>
        <span className="attachment-file-size">{formatSize(msg.media_size)}</span>
      </span>
    </a>
  );
}

function MessageBubble({ msg }) {
  if (msg.author === "system") {
    return <div className="system-note">{msg.text}</div>;
  }

  const side = msg.direction === "in" ? "left" : "right";
  const kind = msg.author; // client | bot | manager
  const hasAttachment = msg.msg_type in TYPE_LABEL;

  return (
    <div className={`bubble-row is-${side}`}>
      <div className={`bubble is-${kind}`}>
        {kind === "manager" && msg.author_manager_name && (
          <div className="bubble-author">{msg.author_manager_name}</div>
        )}
        {kind === "bot" && <div className="bubble-author">Бот</div>}
        {hasAttachment && <Attachment msg={msg} />}
        {msg.text && <div className="bubble-text">{msg.text}</div>}
        <div className="bubble-time">
          {formatClock(msg.created_at)}
          {msg.pending && " · отправляется…"}
        </div>
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

  if (loading) {
    return <div className="thread"><div className="empty-hint">Загрузка…</div></div>;
  }

  let lastDay = null;

  return (
    <div className="thread" ref={containerRef} onScroll={onScroll}>
      {messages.length === 0 && <div className="empty-hint">В этом диалоге пока нет сообщений</div>}
      {messages.map((m) => {
        const key = dayKey(m.created_at);
        const separator = key && key !== lastDay ? formatDateSeparator(m.created_at) : null;
        lastDay = key || lastDay;
        return (
          <div key={m.id}>
            {separator && <div className="date-separator">{separator}</div>}
            <MessageBubble msg={m} />
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}
