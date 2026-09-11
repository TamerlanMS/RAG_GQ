import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api.js";
import { clearAuth } from "../auth.js";
import { usePolling } from "../hooks/usePolling.js";
import { ChatList } from "./ChatList.jsx";
import { Composer } from "./Composer.jsx";
import { MessageThread } from "./MessageThread.jsx";
import { Stats } from "./Stats.jsx";
import { initials } from "../format.js";

const CHATS_INTERVAL_MS = 5000;
const MESSAGES_INTERVAL_MS = 3000;

export function Console({ manager, onLogout }) {
  // Совпадает с проверкой на бэкенде (require_director в src/common/auth.py):
  // code — стабильный идентификатор, а не отображаемая роль.
  const isDirector = manager.code === "director";
  const [view, setView] = useState("chats"); // "chats" | "stats"

  const [chats, setChats] = useState([]);
  const [chatsError, setChatsError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");

  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [threadLoading, setThreadLoading] = useState(false);
  const [threadError, setThreadError] = useState("");

  // Курсор поллинга: максимальный уже полученный id. Ref, а не state —
  // его читает функция опроса, и лишние перерисовки тут не нужны.
  const lastIdRef = useRef(0);
  const activeIdRef = useRef(null);
  activeIdRef.current = activeId;

  const activeChat = chats.find((c) => c.id === activeId) || null;

  const loadChats = useCallback(async () => {
    // "mine" — перехваченные именно этим менеджером (фильтрует сервер по id),
    // "bot" — те, что ведёт бот. Смешивать их в один булев флаг нельзя.
    const takenOver = filter === "bot" ? false : null;
    const mine = filter === "mine";
    try {
      const data = await api.chats({ query, takenOver, mine });
      setChats(data.items);
      setChatsError("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      setChatsError(err.message);
      throw err;
    }
  }, [query, filter]);

  usePolling(loadChats, CHATS_INTERVAL_MS, { deps: [query, filter] });

  // Смена чата: полная загрузка треда и сброс курсора.
  useEffect(() => {
    if (activeId === null) {
      setMessages([]);
      lastIdRef.current = 0;
      return;
    }
    let cancelled = false;
    setThreadLoading(true);
    setThreadError("");
    api
      .messages(activeId, { limit: 50 })
      .then((data) => {
        if (cancelled) return;
        setMessages(data.items);
        lastIdRef.current = data.items.length ? data.items[data.items.length - 1].id : 0;
        return api.markRead(activeId).catch(() => {});
      })
      .then(() => {
        if (!cancelled) {
          setChats((prev) => prev.map((c) => (c.id === activeId ? { ...c, unread_count: 0 } : c)));
        }
      })
      .catch((err) => {
        if (!cancelled && !(err instanceof ApiError && err.status === 401)) setThreadError(err.message);
      })
      .finally(() => {
        if (!cancelled) setThreadLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  // Инкрементальный дозабор: at after_id сервер почти всегда отдаёт пустой список.
  const pollMessages = useCallback(async () => {
    const chatId = activeIdRef.current;
    if (chatId === null) return;
    const data = await api.messages(chatId, { afterId: lastIdRef.current });
    if (!data.items.length) return;
    if (activeIdRef.current !== chatId) return; // менеджер успел переключить чат
    setMessages((prev) => {
      const seen = new Set(prev.filter((m) => !m.pending).map((m) => m.id));
      const fresh = data.items.filter((m) => !seen.has(m.id));
      if (!fresh.length) return prev;
      return [...prev.filter((m) => !m.pending), ...fresh];
    });
    lastIdRef.current = data.items[data.items.length - 1].id;
    api.markRead(chatId).catch(() => {});
  }, []);

  usePolling(pollMessages, MESSAGES_INTERVAL_MS, { enabled: activeId !== null, deps: [activeId] });

  async function handleSend(text) {
    const chatId = activeId;
    // Оптимистичный пузырь — заменится настоящим из ответа сервера.
    const optimistic = {
      id: `pending-${Date.now()}`,
      direction: "out",
      author: "manager",
      author_manager_name: manager.name,
      text,
      msg_type: "text",
      created_at: new Date().toISOString(),
      pending: true,
    };
    setMessages((prev) => [...prev, optimistic]);
    try {
      const res = await api.reply(chatId, text, true);
      setChats((prev) => prev.map((c) => (c.id === chatId ? res.chat : c)));
      // Курсор НЕ двигаем на res.message.id: авто-перехват мог создать системное
      // сообщение с меньшим id, и прыжок через него потерял бы плашку
      // «менеджер подключился к диалогу». Дозабираем всё подряд от текущего курсора.
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
      await pollMessages();
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
      setThreadError(err.message);
    }
  }

  async function handleTakeover(force = false) {
    try {
      const res = await api.takeover(activeId, force);
      setChats((prev) => prev.map((c) => (c.id === activeId ? res.chat : c)));
      setThreadError("");
      pollMessages().catch(() => {});
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        if (window.confirm(`${err.message}\n\nПерехватить всё равно?`)) return handleTakeover(true);
        return;
      }
      setThreadError(err.message);
    }
  }

  async function handleRelease() {
    try {
      const res = await api.release(activeId);
      setChats((prev) => prev.map((c) => (c.id === activeId ? res.chat : c)));
      setThreadError("");
      pollMessages().catch(() => {});
    } catch (err) {
      setThreadError(err.message);
    }
  }

  function logout() {
    clearAuth();
    onLogout();
  }

  return (
    <div className="console">
      <header className="topbar">
        <div className="topbar-brand">GQ Group · консоль менеджера</div>
        <div className="topbar-user">
          {isDirector && (
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setView(view === "stats" ? "chats" : "stats")}
            >
              {view === "stats" ? "Диалоги" : "Статистика"}
            </button>
          )}
          <span className="avatar avatar-sm">{initials(manager.name)}</span>
          <span className="topbar-name">{manager.name}</span>
          <button type="button" className="btn-ghost" onClick={logout}>
            Выйти
          </button>
        </div>
      </header>

      {view === "stats" && isDirector ? (
        <Stats onBack={() => setView("chats")} />
      ) : (
      <div className="layout">
        <ChatList
          chats={chats}
          activeId={activeId}
          onSelect={setActiveId}
          query={query}
          onQueryChange={setQuery}
          filter={filter}
          onFilterChange={setFilter}
          error={chatsError}
        />

        <main className="pane">
          {!activeChat ? (
            <div className="empty-state">Выберите диалог слева</div>
          ) : (
            <>
              <div className="pane-header">
                <div>
                  <div className="pane-title">
                    {activeChat.display_name || activeChat.phone || activeChat.external_id}
                  </div>
                  <div className="pane-subtitle">
                    {activeChat.phone || activeChat.external_id} · WhatsApp
                  </div>
                </div>

                <div className="takeover-bar">
                  {activeChat.is_taken_over ? (
                    <>
                      <span className="takeover-label">
                        Диалог ведёт {activeChat.taken_over_by?.name || "менеджер"}
                      </span>
                      <button type="button" className="btn-ghost" onClick={handleRelease}>
                        Вернуть боту
                      </button>
                    </>
                  ) : (
                    <>
                      <span className="takeover-label takeover-label-bot">Отвечает бот</span>
                      <button type="button" className="btn-secondary" onClick={() => handleTakeover(false)}>
                        Перехватить диалог
                      </button>
                    </>
                  )}
                </div>
              </div>

              {threadError && <div className="pane-error">{threadError}</div>}

              <MessageThread messages={messages} loading={threadLoading} />
              <Composer onSend={handleSend} disabled={false} />
            </>
          )}
        </main>
      </div>
      )}
    </div>
  );
}
