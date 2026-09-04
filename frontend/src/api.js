// Единственная точка обращения к бэкенду.
import { clearAuth, getToken } from "./auth.js";

const BASE = "/api/v1/console";

// Колбэк, который App выставляет один раз: при 401 переводит приложение на экран входа.
let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// handle401=false нужен для /login: там 401 означает «неверный телефон или пароль»,
// а не истёкшую сессию, и подменять текст сервера нельзя.
async function request(path, options = {}, { handle401 = true } = {}) {
  const token = getToken();
  let res;
  try {
    res = await fetch(BASE + path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
  } catch {
    throw new ApiError(0, "Нет связи с сервером");
  }

  if (res.status === 401 && handle401) {
    clearAuth();
    onUnauthorized();
    throw new ApiError(401, "Сессия истекла, войдите заново");
  }

  if (!res.ok) {
    let detail = "Ошибка сервера";
    try {
      const body = await res.json();
      // FastAPI отдаёт detail строкой; при ошибке валидации — списком.
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail[0]?.msg || detail;
    } catch {
      /* тело не JSON — оставляем общее сообщение */
    }
    throw new ApiError(res.status, detail);
  }

  return res.status === 204 ? null : res.json();
}

export const api = {
  login: (phone, password) =>
    request(
      "/login",
      { method: "POST", body: JSON.stringify({ phone, password }) },
      { handle401: false },
    ),

  me: () => request("/me"),

  chats: ({ query = "", takenOver = null, mine = false } = {}) => {
    const p = new URLSearchParams();
    if (query) p.set("query", query);
    if (takenOver !== null) p.set("taken_over", String(takenOver));
    if (mine) p.set("mine", "true");
    const qs = p.toString();
    return request(`/chats${qs ? `?${qs}` : ""}`);
  },

  messages: (chatId, { afterId = null, beforeId = null, limit = 50 } = {}) => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (afterId !== null) p.set("after_id", String(afterId));
    if (beforeId !== null) p.set("before_id", String(beforeId));
    return request(`/chats/${chatId}/messages?${p}`);
  },

  reply: (chatId, text, takeOver = true) =>
    request(`/chats/${chatId}/reply`, {
      method: "POST",
      body: JSON.stringify({ text, take_over: takeOver }),
    }),

  takeover: (chatId, force = false) =>
    request(`/chats/${chatId}/takeover`, {
      method: "POST",
      body: JSON.stringify({ force, notify_client: false }),
    }),

  release: (chatId) => request(`/chats/${chatId}/release`, { method: "POST" }),

  markRead: (chatId) => request(`/chats/${chatId}/read`, { method: "POST" }),
};
