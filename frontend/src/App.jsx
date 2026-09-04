import { useEffect, useState } from "react";
import { api, setUnauthorizedHandler } from "./api.js";
import { getManager, getToken } from "./auth.js";
import { Console } from "./components/Console.jsx";
import { Login } from "./components/Login.jsx";

export default function App() {
  const [manager, setManager] = useState(getManager);
  const [checking, setChecking] = useState(Boolean(getToken()));

  // Одна точка на всё приложение: любой 401 из api.js возвращает на экран входа.
  useEffect(() => {
    setUnauthorizedHandler(() => setManager(null));
  }, []);

  // Сохранённый токен мог истечь — проверяем до отрисовки консоли.
  useEffect(() => {
    if (!getToken()) {
      setChecking(false);
      return;
    }
    api
      .me()
      .then((m) => setManager(m))
      .catch(() => setManager(null))
      .finally(() => setChecking(false));
  }, []);

  if (checking) {
    return <div className="boot-screen">Загрузка…</div>;
  }

  if (!manager) {
    return <Login onSuccess={setManager} />;
  }

  return <Console manager={manager} onLogout={() => setManager(null)} />;
}
