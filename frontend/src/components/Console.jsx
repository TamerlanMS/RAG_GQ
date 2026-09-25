import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api.js";
import { clearAuth } from "../auth.js";
import { usePolling } from "../hooks/usePolling.js";
import { useNewMessageNotifier } from "../hooks/useNewMessageNotifier.js";
import { loadNotifySettings, saveNotifySettings } from "../notify/settings.js";
import { unlockAudio } from "../notify/sound.js";
import { NotifyPrompt, NotifySettings } from "./NotifySettings.jsx";
import { Avatar, ChatList } from "./ChatList.jsx";
import { Composer } from "./Composer.jsx";
import { MessageThread } from "./MessageThread.jsx";
import { Stats } from "./Stats.jsx";
import {
  IconArrowLeft,
  IconBot,
  IconConsole,
  IconLogOut,
  IconStats,
  IconTakeover,
} from "./icons.jsx";

const CHATS_INTERVAL_MS = 5000;
const MESSAGES_INTERVAL_MS = 3000;

// Входящее с вложением появляется сразу, а файл сервер докачивает у Gupshup
// чуть позже и дописывает к уже отданному сообщению. Такие сообщения
// перечитываем при опросе, пока у них не появится media_url, — но не дольше
// этого окна (если файл так и не скачался, дальше ждать бессмысленно).
const MEDIA_TYPES = new Set(["image", "document", "video", "audio", "voice", "sticker"]);
const MEDIA_WAIT_MS = 3 * 60 * 1000;

function awaitingMediaId(messages) {
  const now = Date.now();
  const waiting = messages.filter(
    (m) =>
      !m.pending &&
      MEDIA_TYPES.has(m.msg_type) &&
      !m.media_url &&
      now - new Date(m.created_at).getTime() < MEDIA_WAIT_MS,
  );
  return waiting.length ? Math.min(...waiting.map((m) => m.id)) : null;
}

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
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const [threadLoading, setThreadLoading] = useState(false);
  const [threadError, setThreadError] = useState("");

  // Курсор поллинга: максимальный уже полученный id. Ref, а не state —
  // его читает функция опроса, и лишние перерисовки тут не нужны.
  const lastIdRef = useRef(0);
  const activeIdRef = useRef(null);
  activeIdRef.current = activeId;

  const activeChat = chats.find((c) => c.id === activeId) || null;

  // На телефоне открытый чат занимает весь экран (как в WhatsApp), поэтому
  // «назад» — системная кнопка/жест Android или браузера — должен закрывать
  // чат, а не уводить со страницы. Открытие чата кладёт запись в историю,
  // переключение между чатами её заменяет (иначе «назад» листал бы чаты).
  function openChat(id) {
    const state = { gqChat: id };
    if (window.history.state?.gqChat) window.history.replaceState(state, "");
    else window.history.pushState(state, "");
    setActiveId(id);
  }

  function closeChat() {
    if (window.history.state?.gqChat) window.history.back(); // popstate ниже сбросит activeId
    else setActiveId(null);
  }

  useEffect(() => {
    function onPop(e) {
      setActiveId(e.state?.gqChat ?? null);
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // ── Уведомления о новых сообщениях ───────────────────────
  const [notifySettings, setNotifySettings] = useState(loadNotifySettings);
  function updateNotifySettings(next) {
    setNotifySettings(next);
    saveNotifySettings(next);
  }
  useNewMessageNotifier({ settings: notifySettings, activeIdRef, onOpenChat: openChat });

  // Звук браузер разрешает только после первого действия на странице.
  useEffect(() => {
    const unlock = () => unlockAudio();
    document.addEventListener("pointerdown", unlock, { once: true });
    document.addEventListener("keydown", unlock, { once: true });
    return () => {
      document.removeEventListener("pointerdown", unlock);
      document.removeEventListener("keydown", unlock);
    };
  }, []);

  // Вернулись на вкладку — открытый диалог теперь действительно прочитан.
  useEffect(() => {
    function onVisible() {
      const id = activeIdRef.current;
      if (document.visibilityState !== "visible" || id === null) return;
      api.markRead(id).catch(() => {});
      setChats((prev) => prev.map((c) => (c.id === id ? { ...c, unread_count: 0 } : c)));
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

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
        if (document.visibilityState !== "visible") return undefined;
        return api.markRead(activeId).catch(() => {});
      })
      .then(() => {
        if (!cancelled && document.visibilityState === "visible") {
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
  // Если есть сообщение, ждущее файл, курсор временно откатывается к нему —
  // тогда оно придёт повторно и заменит старую версию по id.
  const pollMessages = useCallback(async () => {
    const chatId = activeIdRef.current;
    if (chatId === null) return;
    const waitingId = awaitingMediaId(messagesRef.current);
    const afterId = waitingId !== null ? Math.min(lastIdRef.current ?? waitingId, waitingId - 1) : lastIdRef.current;
    const data = await api.messages(chatId, { afterId });
    if (!data.items.length) return;
    if (activeIdRef.current !== chatId) return; // менеджер успел переключить чат
    const known = new Set(messagesRef.current.filter((m) => !m.pending).map((m) => m.id));
    const hasFresh = data.items.some((m) => !known.has(m.id));
    const byId = new Map(data.items.map((m) => [m.id, m]));
    setMessages((prev) => {
      const settled = prev.filter((m) => !m.pending);
      const updated = settled.map((m) => byId.get(m.id) || m);
      const seen = new Set(settled.map((m) => m.id));
      const fresh = data.items.filter((m) => !seen.has(m.id));
      // Пришли новые — серверная версия заменяет оптимистичные (как и раньше).
      if (fresh.length) return [...updated, ...fresh];
      if (updated.every((m, i) => m === settled[i])) return prev;
      return [...updated, ...prev.filter((m) => m.pending)];
    });
    const lastItemId = data.items[data.items.length - 1].id;
    lastIdRef.current = Math.max(lastIdRef.current ?? 0, lastItemId);
    // Вкладка скрыта — сообщение не прочитано: иначе счётчик обнулился бы,
    // и уведомление о нём не пришло бы.
    if (hasFresh && document.visibilityState === "visible") api.markRead(chatId).catch(() => {});
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

  async function handleSendFile(file, caption) {
    const chatId = activeId;
    const optimistic = {
      id: `pending-${Date.now()}`,
      direction: "out",
      author: "manager",
      author_manager_name: manager.name,
      text: caption || null,
      msg_type: "document",
      file_name: file.name,
      created_at: new Date().toISOString(),
      pending: true,
    };
    setMessages((prev) => [...prev, optimistic]);
    try {
      const res = await api.replyFile(chatId, file, caption, true);
      setChats((prev) => prev.map((c) => (c.id === chatId ? res.chat : c)));
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
      await pollMessages();
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
      setThreadError(err.message);
      throw err; // Composer оставит файл выбранным — можно повторить
    }
  }

  async function handleSendVoice(blob) {
    const chatId = activeId;
    const ext = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
    const file = new File([blob], `voice.${ext}`, { type: blob.type || "audio/webm" });
    const optimistic = {
      id: `pending-${Date.now()}`,
      direction: "out",
      author: "manager",
      author_manager_name: manager.name,
      text: null,
      msg_type: "voice",
      created_at: new Date().toISOString(),
      pending: true,
    };
    setMessages((prev) => [...prev, optimistic]);
    try {
      const res = await api.replyFile(chatId, file, "", true, true);
      setChats((prev) => prev.map((c) => (c.id === chatId ? res.chat : c)));
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
      await pollMessages();
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
      setThreadError(err.message);
      throw err;
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

  const clientName = activeChat ? activeChat.display_name || activeChat.phone || activeChat.external_id : "";

  const sidebarHeader = (
    <>
    <header className="panel-header sidebar-header">
      <div className="me" title={`${manager.name} — ${manager.role || "менеджер"}`}>
        <Avatar name={manager.name} size="sm" />
        <span className="me-brand">GQ Group</span>
      </div>
      <div className="header-actions">
        <NotifySettings settings={notifySettings} onChange={updateNotifySettings} />
        {isDirector && (
          <button type="button" className="icon-btn" onClick={() => setView("stats")} title="Статистика">
            <IconStats />
          </button>
        )}
        <button type="button" className="icon-btn" onClick={logout} title="Выйти">
          <IconLogOut />
        </button>
      </div>
    </header>
    <NotifyPrompt settings={notifySettings} onChange={updateNotifySettings} />
    </>
  );

  if (view === "stats" && isDirector) {
    return (
      <div className="console">
        <Stats onBack={() => setView("chats")} />
      </div>
    );
  }

  return (
    <div className={`console${activeChat ? " is-chat-open" : ""}`}>
      <div className="layout">
        <ChatList
          header={sidebarHeader}
          chats={chats}
          activeId={activeId}
          onSelect={openChat}
          query={query}
          onQueryChange={setQuery}
          filter={filter}
          onFilterChange={setFilter}
          error={chatsError}
        />

        <main className="pane">
          {!activeChat ? (
            <div className="empty-state">
              <div className="empty-state-icon">
                <IconConsole size={56} strokeWidth={1.25} />
              </div>
              <h2>GQ Group — консоль менеджера</h2>
              <p>
                Выберите диалог слева, чтобы читать переписку клиента с ботом,
                <br />
                перехватить диалог и ответить самому.
              </p>
            </div>
          ) : (
            <>
              <header className="panel-header pane-header">
                <button type="button" className="icon-btn btn-back" onClick={closeChat} aria-label="К списку диалогов">
                  <IconArrowLeft />
                </button>
                <Avatar name={clientName} size="sm" />
                <div className="pane-header-titles">
                  <div className="pane-title">{clientName}</div>
                  <div className="pane-subtitle">{activeChat.phone || activeChat.external_id} · WhatsApp</div>
                </div>

                <div className="takeover-bar">
                  {activeChat.is_taken_over ? (
                    <>
                      <span className="takeover-label" title="Бот молчит, отвечает менеджер">
                        <IconTakeover size={16} />
                        <span className="takeover-text">Ведёт {activeChat.taken_over_by?.name || "менеджер"}</span>
                      </span>
                      <button type="button" className="btn-outline" onClick={handleRelease}>
                        <IconBot size={16} />
                        <span>Вернуть боту</span>
                      </button>
                    </>
                  ) : (
                    <>
                      <span className="takeover-label is-bot">
                        <IconBot size={16} />
                        <span className="takeover-text">Отвечает бот</span>
                      </span>
                      <button type="button" className="btn-primary btn-sm" onClick={() => handleTakeover(false)}>
                        <IconTakeover size={16} />
                        <span>Перехватить</span>
                      </button>
                    </>
                  )}
                </div>
              </header>

              {threadError && <div className="pane-error">{threadError}</div>}

              <MessageThread messages={messages} loading={threadLoading} />
              <Composer onSend={handleSend} onSendFile={handleSendFile} onSendVoice={handleSendVoice} disabled={false} />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
