/**
 * Magnetic response strip (plan §5.3): a compact chain builder shown when a
 * layer is selected. Dragging a driver onto a motion (or the reverse) creates
 * a valid chain assigned to this layer; dragging an existing chain onto the
 * layer row reassigns it. Only compatible ports attach — an invalid drop
 * returns to origin and explains the constraint inline. Every chain edit is
 * exactly one undo transaction through the command layer.
 *
 * Pointer drag and keyboard/click arming share the same `complete()` path, so
 * every control is reachable without a pointer (§10.3).
 *
 * The board itself never shows a node graph: this strip edits structured
 * data, the canvas keeps rendering the final composition.
 */
import { useState } from 'react';
import { useStore } from '../app/store';
import {
  addResponseCommand,
  assignResponseLayerCommand,
  removeResponseCommand,
} from '../direction/commands';
import { translate } from '../app/i18n';
import { driverFor, operatorFor } from '../motion/evaluate';
import type {
  DirectionLayer,
  DirectionScene,
  DriverSpec,
  MotionSpec,
  ResponseChain,
} from '../direction/types';

export const DRIVER_DEFAULTS: Record<string, DriverSpec> = {
  ranked_onsets: { kind: 'ranked_onsets', band: 'low', tier: 'primary', max_events_per_bar: 4, refractory_beats: 0.5 },
  beat_phase: { kind: 'beat_phase', subdivision: 2 },
  downbeat_impulse: { kind: 'downbeat_impulse' },
  energy_envelope: { kind: 'energy_envelope', band: 'mid' },
  structure_boundary: { kind: 'structure_boundary' },
  scene_phase: { kind: 'scene_phase' },
  transition_phase: { kind: 'transition_phase' },
};

export const MOTION_DEFAULTS: Record<string, MotionSpec> = {
  scale_pulse: { kind: 'scale_pulse', amount: 0.05, attack_seconds: 0.02, release_seconds: 0.2 },
  radial_expand: { kind: 'radial_expand', amount: 0.04, attack_seconds: 0.02, release_seconds: 0.2 },
  translate_recoil: { kind: 'translate_recoil', axis: [1, 0], amount: 0.045, attack_seconds: 0.025, release_seconds: 0.22 },
  translate_drift: { kind: 'translate_drift', axis: [0, 1], amount: 0.02, attack_seconds: 0.06, release_seconds: 0.35 },
  rotate_recoil: { kind: 'rotate_recoil', amount: 1.5, attack_seconds: 0.02, release_seconds: 0.25 },
  crop_reveal: { kind: 'crop_reveal', amount: 0.06, attack_seconds: 0.03, release_seconds: 0.3 },
  strip_offset: { kind: 'strip_offset', amount: 0.03, attack_seconds: 0.02, release_seconds: 0.2 },
  opacity_lift: { kind: 'opacity_lift', amount: 0.15, attack_seconds: 0.03, release_seconds: 0.3 },
  opacity_fade: { kind: 'opacity_fade', amount: 0.2, attack_seconds: 0.04, release_seconds: 0.4 },
  blur_focus: { kind: 'blur_focus', amount: 2, attack_seconds: 0.05, release_seconds: 0.35 },
  invert_palette: { kind: 'invert_palette', amount: 1, attack_seconds: 0.01, release_seconds: 0.12 },
};

/** Deterministic id: next free `response-NN`, never wall-clock derived. */
export function nextResponseId(scene: DirectionScene): string {
  const used = new Set(scene.responses.map((r) => r.id));
  for (let index = scene.responses.length + 1; index < scene.responses.length + 1000; index++) {
    const candidate = `response-${String(index).padStart(2, '0')}`;
    if (!used.has(candidate)) return candidate;
  }
  return `response-${scene.responses.length + 1}`;
}

type PortType = 'driver' | 'motion' | 'chain';
type TargetType = PortType | 'layer';

interface Port {
  type: PortType;
  kind?: string;
  id?: string;
}

function readPort(event: React.DragEvent): Port | null {
  try {
    const raw = event.dataTransfer.getData('application/x-beathi-chain');
    if (!raw) return null;
    return JSON.parse(raw) as Port;
  } catch {
    return null;
  }
}

function writePort(event: React.DragEvent, port: Port): void {
  event.dataTransfer.setData('application/x-beathi-chain', JSON.stringify(port));
  event.dataTransfer.effectAllowed = 'copyMove';
}

const samePort = (a: Port | null, b: Port): boolean =>
  !!a && a.type === b.type && a.kind === b.kind && a.id === b.id;

export function ResponseStrip({ scene, layer }: { scene: DirectionScene; layer: DirectionLayer }) {
  const { state, dispatch } = useStore();
  const t = (key: string, params?: Record<string, string | number>) =>
    translate(state.language, key, params);
  const [notice, setNotice] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  // keyboard/click fallback: arm a port, then activate a compatible target
  const [armed, setArmed] = useState<Port | null>(null);
  const chains = scene.responses.filter((r) => r.target_layer_id === layer.id);

  const reject = (message: string) => {
    setNotice(message);
    setDropTarget(null);
    setArmed(null);
  };

  const createChain = (driverKind: string, motionKind: string) => {
    const driver = DRIVER_DEFAULTS[driverKind];
    const motion = MOTION_DEFAULTS[motionKind];
    if (!driver || !motion) return reject(t('chain.invalid.unknown'));
    const definition = driverFor(driverKind);
    const availability = definition
      ? definition.availability(state.rhythm)
      : { available: false, reason: 'unknown driver' };
    const chain: ResponseChain = {
      id: nextResponseId(scene),
      target_layer_id: layer.id,
      label: `${driverFor(driverKind)?.label ?? driverKind} → ${operatorFor(motionKind)?.label ?? motionKind}`,
      driver: { ...driver } as DriverSpec,
      motion: { ...motion } as MotionSpec,
      ...(availability.available ? {} : { unavailable_reason: availability.reason ?? 'driver unavailable' }),
    };
    dispatch({ type: 'command', command: addResponseCommand(state.doc, scene.id, chain) });
    setNotice(availability.available ? null : t('chain.notice.unavailable', { reason: availability.reason ?? '' }));
    setArmed(null);
  };

  /** One completion path for drag drops and keyboard activation. */
  const complete = (port: Port, targetKind: string, targetType: TargetType) => {
    if (targetType === 'layer') {
      if (port.type === 'chain' && port.id) {
        const chain = scene.responses.find((r) => r.id === port.id);
        if (!chain) return reject(t('chain.invalid.unknown'));
        if (chain.target_layer_id === layer.id) return reject(t('chain.invalid.alreadyHere'));
        dispatch({
          type: 'command',
          command: assignResponseLayerCommand(state.doc, scene.id, chain.id, layer.id),
        });
        setNotice(null);
        setArmed(null);
        return;
      }
      return reject(t('chain.invalid.driverNeedsMotion'));
    }
    if (port.type === 'driver' && targetType === 'motion') return createChain(port.kind!, targetKind);
    if (port.type === 'motion' && targetType === 'driver') return createChain(targetKind, port.kind!);
    if (port.type === 'driver') return reject(t('chain.invalid.driverOnDriver'));
    if (port.type === 'motion') return reject(t('chain.invalid.motionOnMotion'));
    return reject(targetType === 'motion' ? t('chain.invalid.chainOnMotion') : t('chain.invalid.chainOnDriver'));
  };

  /** Activate a port: arm it, or complete against the armed port. */
  const activate = (port: Port, targetKind: string, targetType: TargetType) => {
    if (!armed) {
      setArmed(port);
      setNotice(null);
      return;
    }
    if (samePort(armed, port)) {
      setArmed(null);
      return;
    }
    complete(armed, targetKind, targetType);
  };

  const keyProps = (port: Port, targetKind: string, targetType: TargetType) => ({
    tabIndex: 0,
    role: 'button' as const,
    'aria-pressed': samePort(armed, port),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        activate(port, targetKind, targetType);
      } else if (e.key === 'Escape') {
        setArmed(null);
      }
    },
    onClick: () => activate(port, targetKind, targetType),
  });

  const dragProps = (port: Port) => ({
    draggable: true,
    onDragStart: (e: React.DragEvent) => writePort(e, port),
  });

  const dropProps = (targetKind: string, targetType: TargetType, key: string) => ({
    onDragOver: (e: React.DragEvent) => {
      e.preventDefault();
      setDropTarget(key);
    },
    onDragLeave: () => setDropTarget((v) => (v === key ? null : v)),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      const port = readPort(e);
      if (!port) return reject(t('chain.invalid.empty'));
      complete(port, targetKind, targetType);
    },
  });

  return (
    <div className="isec">
      <h3>{t('inspector.section.chain')}</h3>
      <div className="irow">
        <span className="ilab">{t('chain.label.drivers')}</span>
        <div className="stack">
          {Object.keys(DRIVER_DEFAULTS).map((kind) => {
            const definition = driverFor(kind);
            const availability = definition
              ? definition.availability(state.rhythm)
              : { available: false, reason: 'unknown' };
            const port: Port = { type: 'driver', kind };
            return (
              <span
                key={kind}
                className={`chip drag${availability.available ? '' : ' off'}${dropTarget === `d:${kind}` ? ' hot' : ''}${samePort(armed, port) ? ' armed' : ''}`}
                title={availability.available ? undefined : availability.reason}
                {...dragProps(port)}
                {...keyProps(port, kind, 'driver')}
                {...dropProps(kind, 'driver', `d:${kind}`)}
              >
                {definition?.label ?? kind}
              </span>
            );
          })}
        </div>
      </div>
      <div className="irow">
        <span className="ilab">{t('chain.label.motions')}</span>
        <div className="stack">
          {Object.keys(MOTION_DEFAULTS).map((kind) => {
            const port: Port = { type: 'motion', kind };
            return (
              <span
                key={kind}
                className={`chip drag${dropTarget === `m:${kind}` ? ' hot' : ''}${samePort(armed, port) ? ' armed' : ''}`}
                {...dragProps(port)}
                {...keyProps(port, kind, 'motion')}
                {...dropProps(kind, 'motion', `m:${kind}`)}
              >
                {operatorFor(kind)?.label ?? kind}
              </span>
            );
          })}
        </div>
      </div>
      <div
        className={`chain-target${dropTarget === 'layer' ? ' hot' : ''}`}
        {...dropProps('', 'layer', 'layer')}
        tabIndex={0}
        role="button"
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            if (armed) complete(armed, '', 'layer');
          } else if (e.key === 'Escape') {
            setArmed(null);
          }
        }}
        onClick={() => {
          if (armed) complete(armed, '', 'layer');
        }}
      >
        <span className="tm">{layer.label}</span>
        <span className="note">{t('chain.hint.assemble')}</span>
      </div>
      {chains.length > 0 && (
        <div className="stack" style={{ marginTop: 8 }}>
          {chains.map((chain) => {
            const port: Port = { type: 'chain', id: chain.id };
            return (
              <span
                key={chain.id}
                className={`chip drag${samePort(armed, port) ? ' armed' : ''}`}
                title={chain.unavailable_reason ?? undefined}
                {...dragProps(port)}
                {...keyProps(port, '', 'chain')}
              >
                {chain.label}
                <button
                  className="chain-remove"
                  aria-label={t('chain.action.remove')}
                  onClick={(e) => {
                    e.stopPropagation();
                    dispatch({
                      type: 'command',
                      command: removeResponseCommand(state.doc, scene.id, chain.id),
                    });
                  }}
                >
                  ×
                </button>
              </span>
            );
          })}
        </div>
      )}
      {notice && (
        <p className="note chain-notice" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
