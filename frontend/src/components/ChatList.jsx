import { formatTime, initials } from "../format.js";

function ChatListItem({ chat, active, onSelect }) {
  return (
    <button
      type="button"
      className={`chat-item${active ? " is-active" : ""}`}
      onClick={() => onSelect(chat.id)}
    >
      <div className="avatar" aria-hidden="true">
        {initials(chat.display_name || chat.phone || "?")}
      </div>

      <div className="chat-item-body">
        <div className="chat-item-top">
          <span className="chat-item-name">{chat.display_name || chat.phone || chat.external_id}</span>
          <span className="chat-item-time">{formatTime(chat.last_message_at)}</span>
        </div>
        <div className="chat-item-bottom">
          <span className="chat-item-preview">{chat.last_message_preview || "Нет сообщений"}</span>
          {chat.unread_count > 0 && <span className="badge-unread">{chat.unread_count}</span>}
        </div>
        {chat.is_taken_over && (
          <div className="chat-item-taken" title="Диалог ведёт менеджер">
            👤 {chat.taken_over_by?.name || "Менеджер"}
          </div>
        )}
      </div>
    </button>
  );
}

export function ChatList({ chats, activeId, onSelect, query, onQueryChange, filter, onFilterChange, error }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-search">
        <input
          type="search"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Поиск по имени или номеру"
        />
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
