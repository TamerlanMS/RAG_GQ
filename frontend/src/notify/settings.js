// Настройки уведомлений — у каждого браузера свои (localStorage).

const KEY = "gq_console_notify";

export const DEFAULT_NOTIFY_SETTINGS = {
  desktop: true, // всплывающие уведомления (работают, только если браузер разрешил)
  sound: true, // звуковой сигнал
  preview: true, // текст сообщения в уведомлении; выкл. — только «Новое сообщение»
};

export function loadNotifySettings() {
  try {
    return { ...DEFAULT_NOTIFY_SETTINGS, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch {
    return { ...DEFAULT_NOTIFY_SETTINGS };
  }
}

export function saveNotifySettings(settings) {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    /* приватный режим — настройки проживут до перезагрузки */
  }
}

// Уведомления есть не везде: нужен защищённый адрес (https://bot.gqe-online.kz
// или localhost). По http://192.168.2.158 или с ошибкой сертификата браузер
// их не даёт.
export function notificationsSupported() {
  return typeof window !== "undefined" && "Notification" in window && window.isSecureContext;
}

export function notificationPermission() {
  return notificationsSupported() ? Notification.permission : "unsupported";
}
