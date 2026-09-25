import { useEffect, useState } from "react";
import { api, setUnauthorizedHandler } from "./api.js";
import { getManager, getToken } from "./auth.js";
import { Console } from "./components/Console.jsx";
import { Login } from "./components/Login.jsx";

export default function App() {
  const [manager, setManager] = useState(getManager);
  const [checking, setChecking] = useState(Boolean(getToken()));
  // Почему показан экран входа: истёкшая сессия — не то же самое, что «Выйти».
  const [notice, setNotice] = useState("");

  // Одна точка на всё приложение: любой 401 из api.js возвращает на экран входа.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setManager(null);
      setNotice("Сессия истекла — войдите снова.");
    });
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
      .catch(() => {
        setManager(null);
        setNotice("Сессия истекла — войдите снова.");
      })
      .finally(() => setChecking(false));
  }, []);

  if (checking) {
    return <div className="boot-screen">Загрузка…</div>;
  }

  if (!manager) {
    return (
      <Login
        notice={notice}
        onSuccess={(m) => {
          setNotice("");
          setManager(m);
        }}
      />
    );
  }

  return (
    <Console
      manager={manager}
      onLogout={() => {
        setNotice("");
        setManager(null);
      }}
    />
  );
}
