import { avatarColor, formatTime, initials, splitPreview } from "../format.js";
import { IconSearch, IconUser, TypeIcon } from "./icons.jsx";

export function Avatar({ name, size = "md" }) {
  return (
    <div className={`avatar avatar-${size}`} style={{ background: avatarColor(name) }} aria-hidden="true">
      {initials(name || "?")}
    </div>
  );
}

function ChatListItem({ chat, active, onSelect }) {
  const name = chat.display_name || chat.phone || chat.external_id;
  const preview = splitPreview(chat.last_message_preview);
  const unread = chat.unread_count > 0;

  return (
    <button
      type="button"
      className={`chat-item${active ? " is-active" : ""}${unread ? " is-unread" : ""}`}
      onClick={() => onSelect(chat.id)}
    >
      <Avatar name={name} />

      <div className="chat-item-body">
        <div className="chat-item-top">
          <span className="chat-item-name">{name}</span>
          <span className="chat-item-time">{formatTime(chat.last_message_at)}</span>
        </div>
        <div className="chat-item-bottom">
          <span className="chat-item-preview">
            {preview.type && <TypeIcon type={preview.type} className="preview-icon" />}
            <span className="chat-item-preview-text">{preview.text || "Нет сообщений"}</span>
          </span>
          {unread && <span className="badge-unread">{chat.unread_count}</span>}
        </div>
        {chat.is_taken_over && (
          <div className="chat-item-taken" title="Диалог ведёт менеджер">
            <IconUser size={13} />
            <span>{chat.taken_over_by?.name || "Менеджер"}</span>
          </div>
        )}
      </div>
    </button>
  );
}

export function ChatList({ header, chats, activeId, onSelect, query, onQueryChange, filter, onFilterChange, error }) {
  return (
    <aside className="sidebar">
      {header}

      <div className="sidebar-search">
        <label className="search-box">
          <IconSearch size={18} className="search-icon" />
          <input
            type="search"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Поиск по имени или номеру"
          />
        </label>
      </div>

      <div className="sidebar-filters">
        {[
          ["all", "Все"],
          ["mine", "Мои"],
          ["bot", "У бота"],
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`chip${filter === key ? " is-active" : ""}`}
            onClick={() => onFilterChange(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {error && <div className="sidebar-error">{error}</div>}

      <div className="chat-list">
        {chats.length === 0 && !error && <div className="empty-hint">Диалогов пока нет</div>}
        {chats.map((c) => (
          <ChatListItem key={c.id} chat={c} active={c.id === activeId} onSelect={onSelect} />
        ))}
      </div>
    </aside>
  );
}
