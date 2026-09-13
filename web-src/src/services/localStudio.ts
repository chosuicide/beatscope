/**
 * Local Studio adapter: talks to the existing v0.11 REST endpoints behind
 * typed methods (plan Round 1 Commit 2 — "adapt existing analysis/playback
 * state behind typed services; do not rewrite Python analysis").
 *
 * Round 2 Commit 1 adds direction persistence: the initial document is
 * derived server-side from the Rhythm IR on first GET; saves are PUTs with
 * an If-Match ETag, and a refused save (412/428) raises
 * DirectionConflictError carrying the server's current ETag. After a
 * conflict the adapter adopts the server baseline so the next edit can
 * save — the failed write itself still surfaces as saveState 'conflict'.
 */
import type { BeatScopeServices, ProjectSummary, AnalysisJob } from './types';
import type { DirectionDocument, WorkspaceDocument } from '../direction/types';
import { canonicalDirectionBytes, validateDirection } from '../direction/contract';
import { DirectionConflictError } from './conflict';
import type { DemoRhythm } from '../demo/rhythm';
import { LocalStudioAssetClient, type AssetClient } from '../media/client';

function adaptRhythm(raw: any): DemoRhythm {
  const bpm = Number(raw?.tempo?.global_bpm) || 120;
  const beats = Array.isArray(raw?.beats) ? raw.beats.map((b: any) => ({
    time: Number(b.time), bar: Number(b.bar), beat: Number(b.beat_in_bar ?? b.beat),
  })) : [];
  const bands = ['low', 'mid', 'high'] as const;
  const onsets = Array.isArray(raw?.onsets) ? raw.onsets.map((o: any) => {
    const band = bands.reduce((best, key) => Number(o?.bands?.[key] ?? 0) > Number(o?.bands?.[best] ?? 0) ? key : best, 'low' as typeof bands[number]);
    return { id: String(o.id), time: Number(o.time), band, strength: Number(o.strength ?? o?.bands?.[band] ?? 0) };
  }) : [];
  const downbeats = Array.isArray(raw?.beats)
    ? raw.beats.filter((b: any) => b.downbeat === true || Number(b.beat_in_bar ?? b.beat) === 1).map((b: any) => Number(b.time))
    : [];
  const rawEnergy = raw?.energy;
  const energy =
    rawEnergy && Array.isArray(rawEnergy?.bands?.low) && Array.isArray(rawEnergy?.bands?.mid) && Array.isArray(rawEnergy?.bands?.high)
      ? {
          fps: Number(rawEnergy.fps) || 20,
          start: Number(rawEnergy.start) || 0,
          bands: {
            low: rawEnergy.bands.low.map(Number),
            mid: rawEnergy.bands.mid.map(Number),
            high: rawEnergy.bands.high.map(Number),
          },
        }
      : null;
  const patterns = raw?.patterns ?? {};
  const boundaries = Array.isArray(patterns.boundaries)
    ? patterns.boundaries.filter((b: any) => Number.isFinite(Number(b?.time))).map((b: any) => Number(b.time))
    : [];
  const segments = Array.isArray(patterns.segments)
    ? patterns.segments
        .filter((s: any) => Number.isFinite(Number(s?.start_time)) && Number.isFinite(Number(s?.end_time)))
        .map((s: any) => ({ start_time: Number(s.start_time), end_time: Number(s.end_time) }))
    : [];
  return {
    project_id: String(raw.project_id), duration: Number(raw?.source?.duration ?? 0), bpm,
    bar_seconds: 60 / bpm * Number(raw?.meter?.numerator ?? 4), beats, onsets,
    downbeats, energy, boundaries, segments,
  };
}

export class LocalStudioServices implements BeatScopeServices {
  readonly mode = 'local-studio' as const;
  private audioProjectId: string | null = null;
  private directionProjectId: string | null = null;
  private directionEtag: string | null = null;
  private workspaceEtag: string | null = null;
  private activeDraftKey: string | null = null;
  private assetClient: LocalStudioAssetClient | null = null;

  /** Lazily bound to the first project that loads (plan §6.1). */
  get assets(): AssetClient {
    if (!this.assetClient) {
      this.assetClient = new LocalStudioAssetClient(this.audioProjectId ?? this.directionProjectId ?? '');
    }
    return this.assetClient;
  }

  async listProjects(): Promise<ProjectSummary[]> {
    const res = await fetch('/api/projects');
    if (!res.ok) return [];
    const body = (await res.json()) as { projects?: ProjectSummary[] };
    return body.projects ?? [];
  }

  async loadProject(projectId: string): Promise<{
    doc: DirectionDocument;
    rhythm: DemoRhythm | null;
    workspace: WorkspaceDocument | null;
    recoveredDraft?: boolean;
    relevance?: Map<string, number> | null;
  }> {
    const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}`);
    if (!res.ok) throw new Error(`project ${projectId} not found`);
    const rawRhythm = await res.json(); // Rhythm IR is validated on the Python side
    this.audioProjectId = projectId;
    this.assetClient = new LocalStudioAssetClient(projectId);
    let doc = await this.fetchDirection(projectId);
    const draft = this.readDraft();
    if (draft) doc = draft;
    const workspace = await this.fetchWorkspace(projectId);
    const relevance = await this.fetchRelevance(projectId);
    return { doc, rhythm: adaptRhythm(rawRhythm), workspace, recoveredDraft: draft !== null, relevance };
  }

  /**
   * v0.11 response relevance (plan §4.4/§4.7): read-only evidence used to
   * rank the budget. The model is never retrained and no timestamp changes;
   * a missing sidecar falls back to measured strength inside the evaluator.
   */
  private async fetchRelevance(projectId: string): Promise<Map<string, number> | null> {
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/response-relevance`);
      if (!res.ok) return null;
      const body = (await res.json()) as { events?: Array<{ onset_id?: unknown; response_relevance?: unknown }> };
      if (!Array.isArray(body.events)) return null;
      const map = new Map<string, number>();
      for (const row of body.events) {
        const id = Number(row?.onset_id);
        const value = Number(row?.response_relevance);
        if (Number.isFinite(id) && Number.isFinite(value)) map.set(String(id), value);
      }
      return map.size > 0 ? map : null;
    } catch {
      return null;
    }
  }

  private async fetchDirection(projectId: string): Promise<DirectionDocument> {
    const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/direction`);
    const etag = res.headers.get('ETag');
    if (res.status === 422) {
      // stored sidecar failed validation (§10.2 reconciliation failure)
      throw new DirectionConflictError(
        'The stored direction failed contract validation — reset the project sidecar to re-derive it.',
        etag,
      );
    }
    if (!res.ok) throw new Error(`direction unavailable for ${projectId} (${res.status})`);
    const parsed = (await res.json()) as DirectionDocument;
    const { errors } = validateDirection(parsed);
    if (errors.length > 0) {
      throw new DirectionConflictError(`Direction rejected by contract: ${errors[0]}`, etag);
    }
    this.directionProjectId = projectId;
    this.directionEtag = etag;
    this.activeDraftKey = etag ? this.draftKey(parsed, etag) : null;
    return parsed;
  }

  private draftKey(doc: DirectionDocument, etag: string): string {
    return `beathi-direction-draft:${doc.project_id}:${doc.source_rhythm_sha256}:${etag}`;
  }

  private readDraft(): DirectionDocument | null {
    if (!this.activeDraftKey) return null;
    const raw = localStorage.getItem(this.activeDraftKey);
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as DirectionDocument;
      return validateDirection(parsed).errors.length === 0 ? parsed : null;
    } catch {
      return null;
    }
  }

  saveDraft(doc: DirectionDocument): void {
    if (!this.directionEtag) return;
    this.activeDraftKey = this.draftKey(doc, this.directionEtag);
    localStorage.setItem(this.activeDraftKey, new TextDecoder().decode(canonicalDirectionBytes(doc)));
  }

  private async fetchWorkspace(projectId: string): Promise<WorkspaceDocument | null> {
    const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/workspace`);
    if (!res.ok) return null;
    this.workspaceEtag = res.headers.get('ETag');
    return (await res.json()) as WorkspaceDocument;
  }

  async submitAnalysis(file: File): Promise<AnalysisJob | null> {
    const body = await file.arrayBuffer();
    const res = await fetch('/api/jobs/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) },
      body,
    });
    if (!res.ok) return null;
    return (await res.json()) as AnalysisJob;
  }

  async cancelAnalysis(jobId: string): Promise<boolean> {
    const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' });
    return res.ok;
  }

  audioUrlFor(projectId: string): string | null {
    return this.audioProjectId === projectId || projectId ? `/api/projects/${encodeURIComponent(projectId)}/audio` : null;
  }

  hasAudio(): boolean {
    return this.audioProjectId !== null;
  }

  async saveDirection(doc: DirectionDocument): Promise<void> {
    const projectId = this.directionProjectId;
    if (!projectId) throw new Error('no project loaded; cannot save direction');
    let etag = this.directionEtag;
    if (!etag) {
      await this.fetchDirection(projectId);
      etag = this.directionEtag;
    }
    if (!etag) throw new Error('direction baseline unavailable; cannot save');

    const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/direction`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'If-Match': etag },
      body: new Blob([canonicalDirectionBytes(doc)]),
    });
    if (res.status === 409 || res.status === 428) {
      const payload = (await res.json().catch(() => ({}))) as { current_etag?: unknown };
      const currentEtag = typeof payload.current_etag === 'string' ? payload.current_etag : null;
      throw new DirectionConflictError(
        'The direction changed on the server. Review the server version before applying this local draft.',
        currentEtag,
      );
    }
    if (!res.ok) throw new Error(`direction save failed (${res.status})`);
    const payload = (await res.json().catch(() => ({}))) as { etag?: unknown };
    if (typeof payload.etag === 'string') {
      if (this.activeDraftKey) localStorage.removeItem(this.activeDraftKey);
      this.directionEtag = payload.etag;
      this.activeDraftKey = this.draftKey(doc, payload.etag);
    }
  }

  async saveWorkspace(workspace: WorkspaceDocument): Promise<void> {
    if (!this.workspaceEtag || !this.directionProjectId) return;
    const res = await fetch(`/api/projects/${encodeURIComponent(this.directionProjectId)}/workspace`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'If-Match': this.workspaceEtag },
      body: JSON.stringify(workspace),
    });
    if (res.status === 409) return; // workspace is local preference; never overwrite a newer editor
    if (!res.ok) throw new Error(`workspace save failed (${res.status})`);
    const payload = (await res.json()) as { etag?: string };
    if (payload.etag) this.workspaceEtag = payload.etag;
  }
}
