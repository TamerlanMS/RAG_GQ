// Хранение сессии менеджера.
//
// localStorage — осознанный компромисс: токен доступен из JS, значит XSS = кража
// токена. Альтернатива (httpOnly-cookie) требует CSRF-защиты и credentials-режима
// CORS. Для внутренней консоли без сторонних скриптов и с TTL токена 12 ч это
// приемлемо.

const TOKEN_KEY = "gq_console_token";
const MANAGER_KEY = "gq_console_manager";

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getManager() {
  try {
    const raw = localStorage.getItem(MANAGER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setAuth(token, manager) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(MANAGER_KEY, JSON.stringify(manager));
  } catch {
    /* приватный режим браузера — сессия проживёт до перезагрузки страницы */
  }
}

export function clearAuth() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(MANAGER_KEY);
  } catch {
    /* ничего не делаем */
  }
}

// Последний номер, с которым входили, — чтобы не набирать его каждый раз.
// Только номер (10 цифр без +7); пароль не сохраняется никогда.
const LAST_PHONE_KEY = "gq_console_last_phone";

export function getLastPhone() {
  try {
    return localStorage.getItem(LAST_PHONE_KEY) || "";
  } catch {
    return "";
  }
}

export function setLastPhone(national) {
  try {
    localStorage.setItem(LAST_PHONE_KEY, national);
  } catch {
    /* приватный режим — просто не запомним */
  }
}
