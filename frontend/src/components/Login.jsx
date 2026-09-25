import { useState } from "react";
import { api, ApiError } from "../api.js";
import { setAuth } from "../auth.js";
import { IconConsole } from "./icons.jsx";

export function Login({ onSuccess }) {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const data = await api.login(phone.trim(), password);
      setAuth(data.access_token, data.manager);
      onSuccess(data.manager);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось войти");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-band">
        <div className="login-brand">
          <IconConsole size={30} strokeWidth={1.5} />
          <span>GQ Group</span>
        </div>
      </div>
      <form className="login-card" onSubmit={submit}>
        <h1 className="login-title">Консоль менеджера</h1>
        <p className="login-subtitle">Переписка клиентов с ботом WhatsApp. Войдите по номеру телефона и паролю.</p>

        <label className="field">
          <span>Телефон</span>
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+7 777 000 00 00"
            autoComplete="username"
            autoFocus
            required
          />
        </label>

        <label className="field">
          <span>Пароль</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {error && <div className="form-error">{error}</div>}

        <button className="btn-primary" type="submit" disabled={busy || !phone || !password}>
          {busy ? "Вход…" : "Войти"}
        </button>
      </form>
    </div>
  );
}
