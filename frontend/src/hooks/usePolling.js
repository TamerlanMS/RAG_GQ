import { useEffect, useRef } from "react";

/**
 * Периодический опрос сервера.
 *
 * Рекурсивный setTimeout, а НЕ setInterval: при медленной сети интервал
 * накладывал бы запросы друг на друга. Следующий запуск планируется только
 * после завершения предыдущего.
 *
 * Дополнительно:
 *  - пауза, когда вкладка скрыта (document.visibilityState), и немедленный
 *    запрос при возврате;
 *  - экспоненциальный backoff ×2 до 30 с при ошибках, сброс при первом успехе.
 */
export function usePolling(fn, intervalMs, { enabled = true, deps = [] } = {}) {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const timerRef = useRef(null);
  const stoppedRef = useRef(false);
  const backoffRef = useRef(1);

  useEffect(() => {
    if (!enabled) return undefined;

    stoppedRef.current = false;
    backoffRef.current = 1;

    const clear = () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const schedule = (delay) => {
      clear();
      if (stoppedRef.current) return;
      timerRef.current = setTimeout(tick, delay);
    };

    async function tick() {
      if (stoppedRef.current) return;
      if (document.visibilityState === "hidden") {
        schedule(intervalMs);
        return;
      }
      try {
        await fnRef.current();
        backoffRef.current = 1;
      } catch {
        // Ошибки обрабатывает вызывающий код; здесь только замедляемся.
        backoffRef.current = Math.min(backoffRef.current * 2, Math.ceil(30000 / intervalMs));
      }
      schedule(intervalMs * backoffRef.current);
    }

    const onVisible = () => {
      if (document.visibilityState === "visible") {
        backoffRef.current = 1;
        schedule(0);
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    tick();

    return () => {
      stoppedRef.current = true;
      clear();
      document.removeEventListener("visibilitychange", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, ...deps]);
}
