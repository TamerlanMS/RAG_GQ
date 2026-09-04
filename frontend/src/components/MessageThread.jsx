import { useEffect, useRef } from "react";
import { dayKey, formatClock, formatDateSeparator } from "../format.js";

const TYPE_LABEL = {
  image: "📷 Фото",
  document: "📎 Документ",
  video: "🎥 Видео",
  audio: "🎵 Аудио",
  voice: "🎤 Голосовое",
};

function MessageBubble({ msg }) {
  if (msg.author === "system") {
    return <div className="system-note">{msg.text}</div>;
  }

  const side = msg.direction === "in" ? "left" : "right";
  const kind = msg.author; // client | bot | manager
  const attachment = msg.msg_type !== "text" && msg.msg_type !== "button" ? TYPE_LABEL[msg.msg_type] : null;

  return (
    <div className={`bubble-row is-${side}`}>
      <div className={`bubble is-${kind}`}>
        {kind === "manager" && msg.author_manager_name && (
          <div className="bubble-author">{msg.author_manager_name}</div>
        )}
        {kind === "bot" && <div className="bubble-author">Бот</div>}
        {attachment && (
          <div className="bubble-attachment">
            {attachment}
            {msg.file_name ? ` — ${msg.file_name}` : ""}
          </div>
        )}
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
