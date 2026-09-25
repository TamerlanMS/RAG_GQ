import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api.js";
import { getLastPhone, setAuth, setLastPhone } from "../auth.js";
import {
  IconAlert,
  IconBot,
  IconConsole,
  IconEye,
  IconEyeOff,
  IconImage,
  IconInfo,
  IconKey,
  IconPhone,
  IconShield,
  IconTakeover,
} from "./icons.jsx";

// Номер храним как 10 цифр после +7. «+7» стоит неизменяемой приставкой перед
// полем, в поле — «(777) 000-00-00». Ввод и вставка в любом виде:
//   - ведущая 8 — это «8» вместо «+7» (казахстанские номера с 8 не начинаются);
//   - 11-я цифра означает, что первая 7 была кодом страны («+7 777…», «7777…»).
function toNational(inputValue) {
  let d = inputValue.replace(/\D/g, "");
  if (d[0] === "8") d = d.slice(1);
  while (d.length > 10 && d[0] === "7") d = d.slice(1);
  return d.slice(0, 10);
}

function formatNational(n) {
  if (!n) return "";
  // Скобку и дефисы добавляем, только когда за ними уже есть цифры, —
  // иначе Backspace «застревал» бы на форматирующих символах.
  let out = `(${n.slice(0, 3)}`;
  if (n.length > 3) out += `) ${n.slice(3, 6)}`;
  if (n.length > 6) out += `-${n.slice(6, 8)}`;
  if (n.length > 8) out += `-${n.slice(8, 10)}`;
  return out;
}

const FEATURES = [
  [IconBot, "Переписка клиентов с ботом WhatsApp — в реальном времени"],
  [IconTakeover, "Перехват диалога: бот замолкает, отвечаете вы"],
  [IconImage, "Фото, файлы и голосовые — в обе стороны"],
];

export function Login({ onSuccess, notice = "" }) {
  const [national, setNational] = useState(getLastPhone);
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const phoneRef = useRef(null);
  const passwordRef = useRef(null);

  // Номер уже запомнен — сразу в поле пароля.
  useEffect(() => {
    (national.length === 10 ? passwordRef : phoneRef).current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const phoneComplete = national.length === 10;

  async function submit(e) {
    e.preventDefault();
    if (!phoneComplete || !password || busy) return;
    setError("");
    setBusy(true);
    try {
      const data = await api.login(`+7${national}`, password);
      setLastPhone(national);
      setAuth(data.access_token, data.manager);
      onSuccess(data.manager);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось войти");
      setPassword("");
      passwordRef.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  function onPasswordKey(e) {
    if (typeof e.getModifierState === "function") setCapsLock(e.getModifierState("CapsLock"));
  }

  return (
    <div className="login-page">
      <div className="login-band">
        <div className="login-brand">
          <IconConsole size={28} strokeWidth={1.5} />
          <span>GQ Group</span>
        </div>
      </div>

      <div className="login-card">
        <section className="login-intro">
          <h1 className="login-title">Консоль менеджера</h1>
          <p className="login-subtitle">Рабочее место для переписки с клиентами GQ Group в WhatsApp.</p>
          <ul className="login-features">
            {FEATURES.map(([Icon, text]) => (
              <li key={text}>
                <span className="login-feature-icon">
                  <Icon size={18} />
                </span>
                {text}
              </li>
            ))}
          </ul>
          <p className="login-help">
            <IconInfo size={16} />
            Нет доступа или забыли пароль — обратитесь к руководителю.
          </p>
        </section>

        <form className="login-form" onSubmit={submit} noValidate>
          <h2 className="login-form-title">Вход</h2>

          {notice && !error && (
            <div className="login-alert is-info" role="status">
              <IconInfo size={18} />
              <span>{notice}</span>
            </div>
          )}
          {error && (
            <div className="login-alert is-error" role="alert">
              <IconAlert size={18} />
              <span>{error}</span>
            </div>
          )}

          <label className="field">
            <span className="field-label">Телефон</span>
            <span className="input-wrap">
              <IconPhone size={18} className="input-icon" />
              <span className="input-prefix">+7</span>
              <input
                ref={phoneRef}
                className="has-prefix"
                type="tel"
                inputMode="tel"
                value={formatNational(national)}
                onChange={(e) => {
                  setNational(toNational(e.target.value));
                  setError("");
                }}
                placeholder="(777) 000-00-00"
                autoComplete="username"
                aria-invalid={Boolean(error) || undefined}
                required
              />
            </span>
          </label>

          <label className="field">
            <span className="field-label">Пароль</span>
            <span className="input-wrap">
              <IconKey size={18} className="input-icon" />
              <input
                ref={passwordRef}
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setError("");
                }}
                onKeyDown={onPasswordKey}
                onKeyUp={onPasswordKey}
                onBlur={() => setCapsLock(false)}
                autoComplete="current-password"
                aria-invalid={Boolean(error) || undefined}
                required
              />
              <button
                type="button"
                className="input-toggle"
                onClick={() => setShowPassword((v) => !v)}
                title={showPassword ? "Скрыть пароль" : "Показать пароль"}
                aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
              >
                {showPassword ? <IconEyeOff size={18} /> : <IconEye size={18} />}
              </button>
            </span>
            {capsLock && <span className="field-hint is-warning">Включён Caps Lock</span>}
          </label>

          <button className="btn-primary login-submit" type="submit" disabled={busy || !phoneComplete || !password}>
            {busy ? <span className="spinner" /> : "Войти"}
          </button>

          <p className="login-secure">
            <IconShield size={15} />
            Пароль не сохраняется на этом устройстве — только номер телефона.
          </p>
        </form>
      </div>
    </div>
  );
}
