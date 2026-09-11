import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api.js";

const PERIODS = [
  ["today", "Сегодня"],
  ["week", "7 дней"],
  ["month", "30 дней"],
  ["all", "Всё время"],
];

function formatDate(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("ru-RU");
}

export function Stats({ onBack }) {
  const [period, setPeriod] = useState("week");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const usingCustomRange = Boolean(dateFrom || dateTo);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.stats({ period, dateFrom: dateFrom || null, dateTo: dateTo || null });
      setData(res);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [period, dateFrom, dateTo]);

  useEffect(() => {
    load();
  }, [load]);

  function pickPeriod(key) {
    setPeriod(key);
    setDateFrom("");
    setDateTo("");
  }

  return (
    <div className="stats-page">
      <div className="stats-header">
        <button type="button" className="btn-ghost" onClick={onBack}>
          ← К диалогам
        </button>
        <h2 className="stats-title">Статистика по заявкам</h2>
      </div>

      <div className="stats-controls">
        <div className="stats-periods">
          {PERIODS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`chip${!usingCustomRange && period === key ? " is-active" : ""}`}
              onClick={() => pickPeriod(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="stats-range">
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            aria-label="С даты"
          />
          <span>—</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            aria-label="По дату"
          />
        </div>
      </div>

      {error && <div className="pane-error">{error}</div>}
      {loading && <div className="empty-hint">Загрузка…</div>}

      {data && !loading && (
        <>
          <div className="stats-range-label">
            за период {formatDate(data.period_from)} — {formatDate(data.period_to)}
          </div>

          <div className="stats-cards">
            <div className="stats-card">
              <div className="stats-card-value">{data.total_chats}</div>
              <div className="stats-card-label">Заявок за период</div>
            </div>
            <div className="stats-card">
              <div className="stats-card-value">{data.unread_chats}</div>
              <div className="stats-card-label">Непрочитанных</div>
            </div>
            <div className="stats-card">
              <div className="stats-card-value">{data.never_replied_chats}</div>
              <div className="stats-card-label">Без единого ответа менеджера</div>
            </div>
          </div>

          <div className="stats-table-wrap">
            <table className="stats-table">
              <thead>
                <tr>
                  <th>Менеджер</th>
                  <th>Обработано заявок</th>
                </tr>
              </thead>
              <tbody>
                {data.by_manager.map((m) => (
                  <tr key={m.manager_id}>
                    <td>{m.manager_name}</td>
                    <td>{m.chats_handled}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
