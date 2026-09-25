// Единый набор иконок интерфейса (lucide, ISC). Вместо эмодзи: эмодзи на
// Windows, Mac, Android и iPhone рисуются по-разному и выглядят грязно,
// а у SVG-иконок одна толщина линии и цвет берётся из CSS (currentColor).
import {
  AlertCircle,
  ArrowLeft,
  BarChart3,
  Bot,
  Download,
  Eye,
  EyeOff,
  FileText,
  Image,
  Info,
  KeyRound,
  LogOut,
  MessageSquare,
  MessagesSquare,
  Mic,
  MousePointerClick,
  Music,
  Paperclip,
  Phone,
  ShieldCheck,
  Search,
  SendHorizontal,
  Sticker,
  Trash2,
  UserRound,
  UserRoundCheck,
  Video,
  X,
} from "lucide-react";

const DEFAULTS = { size: 20, strokeWidth: 1.75, "aria-hidden": true };

function wrap(Icon) {
  return function IconWithDefaults(props) {
    return <Icon {...DEFAULTS} {...props} />;
  };
}

export const IconAlert = wrap(AlertCircle);
export const IconArrowLeft = wrap(ArrowLeft);
export const IconEye = wrap(Eye);
export const IconEyeOff = wrap(EyeOff);
export const IconInfo = wrap(Info);
export const IconKey = wrap(KeyRound);
export const IconPhone = wrap(Phone);
export const IconShield = wrap(ShieldCheck);
export const IconImage = wrap(Image);
export const IconStats = wrap(BarChart3);
export const IconBot = wrap(Bot);
export const IconDownload = wrap(Download);
export const IconFile = wrap(FileText);
export const IconLogOut = wrap(LogOut);
export const IconChats = wrap(MessageSquare);
export const IconConsole = wrap(MessagesSquare);
export const IconMic = wrap(Mic);
export const IconPaperclip = wrap(Paperclip);
export const IconSearch = wrap(Search);
export const IconSend = wrap(SendHorizontal);
export const IconTrash = wrap(Trash2);
export const IconUser = wrap(UserRound);
export const IconTakeover = wrap(UserRoundCheck);
export const IconX = wrap(X);

const TYPE_ICONS = {
  image: Image,
  document: FileText,
  video: Video,
  audio: Music,
  voice: Mic,
  sticker: Sticker,
  button: MousePointerClick,
  system: Info,
};

// Иконка типа вложения/сообщения; null для обычного текста.
export function TypeIcon({ type, ...props }) {
  const Icon = TYPE_ICONS[type];
  return Icon ? <Icon {...DEFAULTS} size={16} {...props} /> : null;
}
