/**
 * Movie transport: the Beathi floating-transport contract (same classes as the
 * canvas transport, `.transport` / `.tp-*`) with a movie clock — play/pause,
 * a draggable timeline, the timecode and a secondary label. Presentational
 * only: the caller owns the clock, so the canvas editor's own transport stays
 * untouched.
 *
 * The timeline is a custom track, so it carries its own drag: pointer capture
 * keeps the gesture alive after the pointer leaves the 3px rail (the grab area
 * is widened in CSS), and while dragging the track renders from its own value
 * so the running clock cannot tug the knob back mid-gesture.
 */
import { useRef, useState } from 'react';
import type { KeyboardEvent, PointerEvent, ReactNode } from 'react';
import { useCopy } from './copy';

function timeLabel(t: number): string {
  const safe = Number.isFinite(t) && t > 0 ? t : 0;
  const m = Math.floor(safe / 60);
  const s = Math.floor(safe % 60);
  const tenth = Math.floor((safe * 10) % 10);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${tenth}`;
}

interface MovieTransportProps {
  time: number;
  duration: number;
  playing: boolean;
  disabled?: boolean;
  label: string;
  onToggle: () => void;
  onSeek: (time: number) => void;
  children?: ReactNode;
}

export function MovieTransport({ time, duration, playing, disabled, label, onToggle, onSeek, children }: MovieTransportProps) {
  const copy = useCopy();
  const track = useRef<HTMLDivElement>(null);
  const [dragTime, setDragTime] = useState<number | null>(null);
  const shown = dragTime ?? time;
  const progress = duration > 0 ? Math.min(1, Math.max(0, shown / duration)) : 0;

  const timeAt = (clientX: number): number => {
    const el = track.current;
    if (!el || duration <= 0) return 0;
    const rect = el.getBoundingClientRect();
    const fraction = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return fraction * duration;
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || duration <= 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const next = timeAt(event.clientX);
    setDragTime(next);
    onSeek(next);
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (dragTime === null) return;
    const next = timeAt(event.clientX);
    setDragTime(next);
    onSeek(next);
  };

  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setDragTime(null);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled || duration <= 0) return;
    const step = event.shiftKey ? 10 : 1;
    let next: number | null = null;
    if (event.key === 'ArrowLeft') next = Math.max(0, shown - step);
    else if (event.key === 'ArrowRight') next = Math.min(duration, shown + step);
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = duration;
    if (next === null) return;
    event.preventDefault();
    onSeek(next);
  };

  return (
    <div className="transport mv-transport">
      <div className="tp-in">
        <button
          className="tp-play"
          aria-label={playing ? copy.pause : copy.play}
          disabled={disabled}
          onClick={onToggle}
        >
          {playing ? (
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
              <rect x="1.5" y="1" width="3" height="10" rx="0.6" fill="currentColor" />
              <rect x="7.5" y="1" width="3" height="10" rx="0.6" fill="currentColor" />
            </svg>
          ) : (
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
              <path d="M2.6 1.4 10.4 6 2.6 10.6Z" fill="currentColor" />
            </svg>
          )}
        </button>
        <div
          ref={track}
          className="tp-tl"
          role="slider"
          tabIndex={disabled ? -1 : 0}
          aria-label={copy.timeline}
          aria-valuenow={Math.round(progress * 100)}
          aria-valuetext={timeLabel(shown)}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onKeyDown={onKeyDown}
        >
          <span className="tp-fill" style={{ width: `${progress * 100}%` }} />
          <span className="tp-knob" style={{ left: `${progress * 100}%` }} />
        </div>
        <span className="tp-time">{timeLabel(shown)}</span>
        <span className="tp-div" />
        <span className="tp-n">{label}</span>
        {children}
      </div>
    </div>
  );
}
