import { useState } from "react";

export function Composer({ onSend, disabled }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function send() {
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    try {
      await onSend(value);
      setText("");
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(e) {
    // Enter отправляет, Shift+Enter переносит строку.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="composer">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Напишите сообщение…  (Enter — отправить, Shift+Enter — новая строка)"
        rows={1}
        maxLength={4000}
        disabled={disabled || busy}
      />
      <button
        type="button"
        className="btn-primary btn-send"
        onClick={send}
        disabled={disabled || busy || !text.trim()}
      >
        {busy ? "…" : "Отправить"}
      </button>
    </div>
  );
}
