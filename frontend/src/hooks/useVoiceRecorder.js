import { useEffect, useRef, useState } from "react";

// Запись голосового с микрофона. Формат — какой умеет браузер (WebM/Opus в
// Chrome и Firefox, MP4/AAC в Safari): в OGG/Opus для WhatsApp запись
// перекодирует сервер.
const PREFERRED_TYPES = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
const MAX_SECONDS = 15 * 60;

function pickMimeType() {
  if (typeof MediaRecorder === "undefined") return null;
  return PREFERRED_TYPES.find((t) => MediaRecorder.isTypeSupported(t)) || "";
}

export function voiceSupported() {
  return Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== "undefined";
}

export function useVoiceRecorder() {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);
  const resolveRef = useRef(null);

  function cleanup() {
    clearInterval(timerRef.current);
    timerRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recorderRef.current = null;
    setRecording(false);
    setSeconds(0);
  }

  // Выход из чата / закрытие вкладки во время записи — отпускаем микрофон.
  useEffect(() => cleanup, []);

  async function start() {
    setError("");
    if (!voiceSupported()) {
      setError("Браузер не поддерживает запись. Откройте консоль по https:// в Chrome.");
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Нет доступа к микрофону — разрешите его в настройках браузера");
      return;
    }
    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    chunksRef.current = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size) chunksRef.current.push(e.data);
    };
    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: recorder.mimeType || mimeType || "audio/webm" });
      const resolve = resolveRef.current;
      resolveRef.current = null;
      cleanup();
      resolve?.(blob);
    };
    streamRef.current = stream;
    recorderRef.current = recorder;
    recorder.start(250);
    setRecording(true);
    setSeconds(0);
    // Сверх лимита не останавливаем (запись бы потерялась) — сервер сам
    // обрежет до MAX_SECONDS, а счётчик просто замирает.
    timerRef.current = setInterval(() => setSeconds((s) => Math.min(s + 1, MAX_SECONDS)), 1000);
  }

  // Останавливает запись и отдаёт её (Blob). null — записи не было.
  function stop() {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return Promise.resolve(null);
    return new Promise((resolve) => {
      resolveRef.current = resolve;
      recorder.stop();
    });
  }

  function cancel() {
    const recorder = recorderRef.current;
    resolveRef.current = null;
    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = () => cleanup();
      recorder.stop();
    } else {
      cleanup();
    }
  }

  return { recording, seconds, error, setError, start, stop, cancel };
}
