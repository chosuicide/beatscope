/**
 * Bridge to the eight frozen v0.11 WebMCP tools (plan §7.1: they "remain
 * available and keep their frozen semantics"). The legacy register module is
 * reused verbatim — the new shell only adapts its state through the typed
 * services. Outside a WebMCP-capable host this degrades to 'unsupported'.
 */
import type { BeatScopeServices } from './types';
import type { AppState } from '../app/store';
import { demoLegacyProject } from '../demo/rhythm';

interface WebmcpDeps {
  getState: () => unknown;
  hasAudio: () => boolean;
  seek: (time: number) => void;
  play: () => Promise<boolean>;
  pause: () => void;
  readAudioTime: () => number;
  setFollowPlayback: (enabled: boolean) => void;
  scrollPlayerIntoView: () => void;
  sceneAt: (time: number) => unknown;
  onStatus: (status: string) => void;
}

type InstallWebMCP = (deps: WebmcpDeps) => { status: string; dispose: () => void };

export async function installLegacyWebMCP(services: BeatScopeServices, state: () => AppState): Promise<string> {
  try {
    // Frozen legacy modules are reused, not copied; Vite bundles them from
    // their repository location (beatscope/web stays until the Round 5 map).
    // @ts-expect-error - untyped legacy JS module
    const register = (await import('../../../beatscope/web/webmcp/register.js')) as unknown as {
      installWebMCP: InstallWebMCP;
    };
    const session = register.installWebMCP({
      getState: () => legacyStateShape(state()),
      hasAudio: () => services.hasAudio(),
      seek: () => {}, // wired to the transport in Round 4's proposal round-trip
      play: async () => false,
      pause: () => {},
      readAudioTime: () => state().transport.time,
      setFollowPlayback: () => {},
      scrollPlayerIntoView: () => {},
      sceneAt: (time) => {
        const doc = state().doc;
        return doc.scenes.find((s) => time >= s.start_time && time < s.end_time) ?? null;
      },
      onStatus: () => {},
    });
    return session.status;
  } catch {
    return 'unsupported';
  }
}

/**
 * The frozen tools read the v0.11 state shape; the project field maps from
 * the demo rhythm facts without rewriting the tools themselves.
 */
function legacyStateShape(state: AppState): Record<string, unknown> {
  return {
    project: state.legacyProject ?? demoLegacyProject(),
    playbackTime: state.transport.time,
    isPlaying: state.transport.playing,
    loop: state.transport.loopStart !== null,
    loopSelection:
      state.transport.loopStart !== null && state.transport.loopEnd !== null
        ? { start: state.transport.loopStart, end: state.transport.loopEnd }
        : null,
    subdivision: 16,
    adjustments: null,
  };
}
