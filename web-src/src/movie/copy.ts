/**
 * Studio copy: English first, Chinese behind the top-bar switch.
 *
 * English is the default; the switch remembers the choice for this browser.
 * `t()` is the non-React accessor (validation errors, document title),
 * `useCopy()` subscribes a component so switching re-renders.
 */
import { useSyncExternalStore } from 'react';

export type Lang = 'en' | 'zh';

const en = {
  docTitle: 'Beathi · Music video studio',
  brand: 'Beathi',
  sections: (n: number | string) => `${n} section${n === 1 ? '' : 's'}`,
  structure: 'Structure',
  barOf: (bar: number | string, bars: number | string) => `Bar ${bar} / ${bars}`,
  changeSong: 'Change song',
  dismissError: 'Dismiss error',
  play: 'Play',
  pause: 'Pause',
  timeline: 'Timeline',
  uploadSong: 'Upload a song',
  uploadHint: 'MP3 · WAV · FLAC · max 10 min',
  posterAlt: 'Built-in template example, not this song',
  livePreviewTitle: 'Live template preview',
  previewFailed: 'The preview failed to load — reload the page.',
  warning: 'Contains flashing and high-contrast cuts. Do not watch if you are photosensitive.',
  transport: { film: 'Film', rendering: 'Rendering · live preview', preview: 'Live preview' },
  status: {
    uploading: 'Uploading',
    analyzing: 'Analyzing',
    rendering: 'Rendering',
    complete: 'Film ready',
    failed: 'Failed',
    preview: 'Ready to preview',
    ready: 'Ready',
    idle: 'Waiting for a song',
  },
  agent: {
    connecting: 'AGENT · CONNECTING',
    tools: (n: number) => `AGENT · ${n} TOOLS`,
    error: 'AGENT · ERROR',
    label: 'In-page agent',
    activity: 'Agent action',
    restore: 'Restore',
    dismiss: 'Dismiss',
  },
  video: 'Video',
  kv: { status: 'Status', progress: 'Progress', elapsed: 'Elapsed', eta: 'Time left', output: 'Output', name: 'Name', version: 'Version' },
  generate: 'Generate video',
  regenerate: 'Regenerate video',
  cancel: 'Cancel',
  retry: 'Retry',
  dataExport: 'Data export',
  dataPackage: 'Package · codex.zip',
  rhythmMidi: 'Rhythm MIDI',
  rhythmCsv: 'Rhythm CSV',
  filmExport: 'Film',
  filmReady: 'MP4',
  filmMissing: 'Generate first',
  template: 'Template',
  errorService: 'Unexpected service response — is this the local Beathi server rather than a static demo?',
  errorRequest: (status: number) => `Request failed (${status})`,
  errorFileType: 'Choose an audio file.',
  errorFileSize: 'Audio must not be empty and must stay under 500 MiB.',
  cue: {
    label: 'Music analysis',
    overview: 'Full-song overview',
    meta: (bpm: string, bars: number, bar: number) => `${bpm} BPM · ${bars} bars · bar ${bar}`,
    collapse: 'Collapse cue map',
    expand: 'Expand cue map',
    overviewLabel: 'Whole-song sections and three bands; click to seek',
    mapLabel: 'Eight-bar cue map; click to seek',
    barsRange: (a: string, b: string, bars: number | string) => `Bars ${a}–${b} / ${bars}`,
    prev: '← Prev 8',
    follow: 'Follow',
    next: 'Next 8 →',
  },
};
export type Copy = typeof en;

const zh: Copy = {
  docTitle: 'Beathi · 音乐视频工作室',
  brand: 'Beathi',
  sections: (n) => `${n} 段`,
  structure: '结构',
  barOf: (bar, bars) => `第 ${bar} 小节 / 共 ${bars} 小节`,
  changeSong: '换一首歌',
  dismissError: '关闭错误提示',
  play: '播放',
  pause: '暂停',
  timeline: '时间轴',
  uploadSong: '上传歌曲',
  uploadHint: 'MP3 · WAV · FLAC · 最长 10 分钟',
  posterAlt: '内置模板示例，不是当前歌曲的画面',
  livePreviewTitle: '实时模板预览',
  previewFailed: '预览加载失败，请刷新页面重试。',
  warning: '包含故障效果与高对比切换，对闪烁敏感时请勿播放。',
  transport: { film: '成片', rendering: '生成中 · 实时预览', preview: '实时预览' },
  status: {
    uploading: '上传中',
    analyzing: '分析中',
    rendering: '生成中',
    complete: '成片就绪',
    failed: '失败',
    preview: '可预览',
    ready: '就绪',
    idle: '等待歌曲',
  },
  agent: {
    connecting: 'AGENT · 连接中',
    tools: (n: number) => `AGENT · ${n} 个工具`,
    error: 'AGENT · 出错',
    label: '页面内 agent',
    activity: 'Agent 动作',
    restore: '恢复',
    dismiss: '关闭',
  },
  video: '视频',
  kv: { status: '状态', progress: '进度', elapsed: '已用', eta: '预计剩余', output: '输出', name: '名称', version: '版本' },
  generate: '生成视频',
  regenerate: '重新生成视频',
  cancel: '取消',
  retry: '重新生成',
  dataExport: '数据导出',
  dataPackage: '数据包 · codex.zip',
  rhythmMidi: '节奏 MIDI',
  rhythmCsv: '节奏 CSV',
  filmExport: '影片导出',
  filmReady: '影片 · MP4',
  filmMissing: '影片 · 需先生成',
  template: '模板',
  errorService: '服务返回异常，请确认这是本地 Beathi 服务，而不是静态演示站。',
  errorRequest: (status) => `请求失败 (${status})`,
  errorFileType: '请选择音频文件。',
  errorFileSize: '音频不能为空，且不能超过 500 MiB。',
  cue: {
    label: '音乐分析',
    overview: '全曲总览',
    meta: (bpm, bars, bar) => `${bpm} BPM · ${bars} 小节 · 第 ${bar}`,
    collapse: '收起节奏图',
    expand: '展开节奏图',
    overviewLabel: '全曲段落与三段能量；点击可跳转',
    mapLabel: '八小节节奏图；点击可跳转',
    barsRange: (a, b, bars) => `小节 ${a}—${b} / ${bars}`,
    prev: '← 前八小节',
    follow: '跟随播放',
    next: '后八小节 →',
  },
};

export const COPY: Record<Lang, Copy> = { en, zh };
export const LANGS: { id: Lang; label: string }[] = [
  { id: 'en', label: 'EN' },
  { id: 'zh', label: '中文' },
];

const KEY = 'beathi.studio.lang';
const listeners = new Set<() => void>();
let current: Lang = read();

function read(): Lang {
  try {
    const stored = localStorage.getItem(KEY);
    if (stored === 'en' || stored === 'zh') return stored;
  } catch {
    /* storage can be unavailable; English is the default either way */
  }
  return 'en';
}

export function setLang(next: Lang): void {
  if (next === current) return;
  current = next;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* remember best-effort */
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const snapshot = (): Lang => current;

export function useLang(): Lang {
  return useSyncExternalStore(subscribe, snapshot);
}

export function useCopy(): Copy {
  return COPY[useLang()];
}

/** Copy for code that runs outside React (validation, document title). */
export function t(): Copy {
  return COPY[current];
}
