// Счётчик непрочитанных на вкладке браузера: число в заголовке «(3) GQ …»
// и красный кружок на значке вкладки — видно, даже когда вкладка не активна.

const BASE_TITLE = "GQ Group — консоль менеджера";
let lastCount = -1;

function drawFavicon(count) {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const g = canvas.getContext("2d");
  if (!g) return null;

  // Зелёный круг с «GQ».
  g.fillStyle = "#00a884";
  g.beginPath();
  g.arc(32, 32, 30, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = "#ffffff";
  g.font = "bold 26px 'Segoe UI', Arial, sans-serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText("GQ", 32, 34);

  if (count > 0) {
    const label = count > 99 ? "99+" : String(count);
    const r = label.length > 2 ? 20 : 17;
    g.fillStyle = "#e53935";
    g.beginPath();
    g.arc(size - r + 2, r - 2, r, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = "#ffffff";
    g.font = `bold ${label.length > 2 ? 17 : 22}px 'Segoe UI', Arial, sans-serif`;
    g.fillText(label, size - r + 2, r);
  }
  return canvas.toDataURL("image/png");
}

export function setTabUnread(count) {
  const n = Math.max(0, Number(count) || 0);
  if (n === lastCount) return;
  lastCount = n;
  document.title = n > 0 ? `(${n > 99 ? "99+" : n}) ${BASE_TITLE}` : BASE_TITLE;

  const href = drawFavicon(n);
  if (!href) return;
  let link = document.querySelector('link[rel="icon"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  link.type = "image/png";
  link.href = href;
}

export function faviconDataUrl() {
  return drawFavicon(0);
}
