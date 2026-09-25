import { useEffect, useRef, useState } from "react";
import { useVoiceRecorder } from "../hooks/useVoiceRecorder.js";
import { IconMic, IconPaperclip, IconSend, IconTrash, IconX } from "./icons.jsx";

// Лимит WhatsApp на документ; для фото (5 МБ) и видео/аудио (16 МБ) точную
// проверку делает сервер — он знает, каким типом уйдёт файл.
const MAX_FILE_BYTES = 100 * 1024 * 1024;

function formatSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

// Сенсорный экран: у экранной клавиатуры нет Shift, поэтому Enter переносит
// строку, а отправка — кнопкой (как в самом WhatsApp).
const IS_TOUCH = typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches;

function formatTimer(sec) {
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

export function Composer({ onSend, onSendFile, onSendVoice, disabled }) {
  const [text, setText] = useState("");
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);
  const textRef = useRef(null);
  const voice = useVoiceRecorder();

  // Поле растёт вместе с текстом (до max-height в CSS), как в WhatsApp.
  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text, voice.recording]);

  async function sendVoice() {
    const blob = await voice.stop();
    if (!blob || !blob.size) return;
    setBusy(true);
    try {
      await onSendVoice(blob);
    } catch {
      // Ошибку показывает Console.
    } finally {
      setBusy(false);
    }
  }

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
    // Enter отправляет, Shift+Enter переносит строку (на телефоне Enter — перенос).
    if (e.key === "Enter" && !e.shiftKey && !IS_TOUCH) {
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

  const hasContent = Boolean(file || text.trim());
  const canSend = !disabled && !busy && hasContent;

  if (voice.recording) {
    return (
      <div className="composer-wrap">
        <div className="composer composer-recording">
          <button type="button" className="icon-btn" onClick={voice.cancel} title="Удалить запись">
            <IconTrash />
          </button>
          <span className="rec-indicator">
            <span className="rec-dot" />
            <span className="rec-timer">{formatTimer(voice.seconds)}</span>
            <span className="rec-hint">Идёт запись…</span>
          </span>
          <button type="button" className="send-btn" onClick={sendVoice} title="Отправить голосовое">
            <IconSend />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="composer-wrap">
      {voice.error && (
        <div className="composer-note is-error">
          <span>{voice.error}</span>
          <button type="button" className="icon-btn icon-btn-sm" onClick={() => voice.setError("")} title="Скрыть">
            <IconX size={16} />
          </button>
        </div>
      )}
      {(file || fileError) && (
        <div className={`composer-note${file ? "" : " is-error"}`}>
          {file ? (
            <>
              <span className="composer-file-icon">
                <IconPaperclip size={16} />
              </span>
              <span className="composer-file-name">{file.name}</span>
              <span className="composer-file-size">{formatSize(file.size)}</span>
              <button
                type="button"
                className="icon-btn icon-btn-sm"
                onClick={() => setFile(null)}
                disabled={busy}
                title="Убрать файл"
              >
                <IconX size={16} />
              </button>
            </>
          ) : (
            <span>{fileError}</span>
          )}
        </div>
      )}
      <div className="composer">
        <input ref={inputRef} type="file" hidden onChange={pickFile} />
        <button
          type="button"
          className="icon-btn"
          onClick={() => inputRef.current?.click()}
          disabled={disabled || busy}
          title="Прикрепить файл: фото, видео, аудио или документ"
        >
          <IconPaperclip />
        </button>
        <textarea
          ref={textRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={file ? "Подпись к файлу (необязательно)" : "Введите сообщение"}
          title={IS_TOUCH ? undefined : "Enter — отправить, Shift+Enter — новая строка"}
          rows={1}
          maxLength={file ? 1024 : 4000}
          disabled={disabled || busy}
        />
        {/* Как в WhatsApp: пустое поле — микрофон, есть текст или файл — отправка. */}
        {hasContent || busy ? (
          <button type="button" className="send-btn" onClick={send} disabled={!canSend} title="Отправить">
            {busy ? <span className="spinner" /> : <IconSend />}
          </button>
        ) : (
          <button
            type="button"
            className="icon-btn"
            onClick={voice.start}
            disabled={disabled}
            title="Записать голосовое"
          >
            <IconMic />
          </button>
        )}
      </div>
    </div>
  );
}
