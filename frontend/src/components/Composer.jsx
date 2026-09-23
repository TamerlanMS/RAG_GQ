import { useRef, useState } from "react";

// Лимит WhatsApp на документ; для фото (5 МБ) и видео/аудио (16 МБ) точную
// проверку делает сервер — он знает, каким типом уйдёт файл.
const MAX_FILE_BYTES = 100 * 1024 * 1024;

function formatSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

export function Composer({ onSend, onSendFile, disabled }) {
  const [text, setText] = useState("");
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  async function send() {
    const value = text.trim();
    if (busy || (!value && !file)) return;
    setBusy(true);
    try {
      if (file) {
        // Текст уходит подписью к файлу.
        await onSendFile(file, value);
        setFile(null);
      } else {
        await onSend(value);
      }
      setText("");
    } catch {
      // Ошибку показывает Console; файл и подпись оставляем, чтобы повторить.
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

  function pickFile(e) {
    const picked = e.target.files?.[0];
    e.target.value = ""; // чтобы тот же файл можно было выбрать повторно
    if (!picked) return;
    if (picked.size > MAX_FILE_BYTES) {
      setFileError(`Файл больше 100 МБ — WhatsApp такой не примет`);
      return;
    }
    setFileError("");
    setFile(picked);
  }

  const canSend = !disabled && !busy && (file || text.trim());

  return (
    <div className="composer-wrap">
      {(file || fileError) && (
        <div className="composer-file">
          {file ? (
            <>
              <span className="composer-file-name">📎 {file.name}</span>
              <span className="composer-file-size">{formatSize(file.size)}</span>
              <button
                type="button"
                className="composer-file-remove"
                onClick={() => setFile(null)}
                disabled={busy}
                title="Убрать файл"
              >
                ×
              </button>
            </>
          ) : (
            <span className="composer-file-error">{fileError}</span>
          )}
        </div>
      )}
      <div className="composer">
        <input ref={inputRef} type="file" hidden onChange={pickFile} />
        <button
          type="button"
          className="btn-attach"
          onClick={() => inputRef.current?.click()}
          disabled={disabled || busy}
          title="Прикрепить файл: фото, видео, аудио или документ"
        >
          📎
        </button>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={
            file
              ? "Подпись к файлу (необязательно)…"
              : "Напишите сообщение…  (Enter — отправить, Shift+Enter — новая строка)"
          }
          rows={1}
          maxLength={file ? 1024 : 4000}
          disabled={disabled || busy}
        />
        <button type="button" className="btn-primary btn-send" onClick={send} disabled={!canSend}>
          {busy ? "…" : "Отправить"}
        </button>
      </div>
    </div>
  );
}
