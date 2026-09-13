/**
 * Static demo adapter (plan §3.7): no server, no upload, no pretend saving.
 * The bundled "Beyond the Fog" document loads synchronously; edits persist
 * only in this browser via localStorage (IndexedDB migration is Round 5).
 *
 * Round 2 Commit 1: drafts are stored as canonical `beatscope-direction-1`
 * bytes and re-validated on recovery — a draft that no longer satisfies the
 * contract is discarded (never half-applied) and the shipped document
 * loads instead.
 */
import type { BeatScopeServices, ProjectSummary } from './types';
import type { DirectionDocument, WorkspaceDocument } from '../direction/types';
import { canonicalDirectionString, validateDirection } from '../direction/contract';
import { demoDocument } from '../demo/document';
import { demoRhythm, type DemoRhythm } from '../demo/rhythm';

const draftKey = (doc: DirectionDocument) => `beathi-direction-draft:${doc.project_id}:${doc.source_rhythm_sha256}:static`;
const WORKSPACE_KEY = 'beathi-workspace:beyond-the-fog-01';

export class StaticDemoServices implements BeatScopeServices {
  readonly mode = 'static-demo' as const;

  private isShot(): boolean {
    return new URLSearchParams(window.location.search).has('shot');
  }

  async listProjects(): Promise<ProjectSummary[]> {
    return [{ project_id: demoDocument.project_id, display_name: demoDocument.project_title }];
  }

  async loadProject(_projectId: string): Promise<{ doc: DirectionDocument; rhythm: DemoRhythm | null; workspace: WorkspaceDocument | null }> {
    if (this.isShot()) return { doc: demoDocument, rhythm: demoRhythm(), workspace: null };
    const key = draftKey(demoDocument);
    const raw = localStorage.getItem(key);
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as DirectionDocument;
        const { errors } = validateDirection(parsed);
        if (errors.length === 0) return { doc: parsed, rhythm: demoRhythm(), workspace: this.readWorkspace() };
        // a draft outside the contract is stale or corrupted; drop it whole
      } catch {
        /* fall through to discard */
      }
      localStorage.removeItem(key);
    }
    return { doc: demoDocument, rhythm: demoRhythm(), workspace: this.readWorkspace() };
  }

  async submitAnalysis(): Promise<null> {
    return null; // unsupported actions are removed, not dead buttons (§3.7)
  }

  async cancelAnalysis(): Promise<boolean> {
    return false;
  }

  audioUrlFor(): string | null {
    return null; // the demo carries no third-party audio
  }

  hasAudio(): boolean {
    return false;
  }

  async saveDirection(doc: DirectionDocument): Promise<void> {
    const { errors } = validateDirection(doc);
    if (errors.length > 0) throw new Error(`refusing to save an invalid direction draft: ${errors[0]}`);
    this.saveDraft(doc);
  }

  saveDraft(doc: DirectionDocument): void {
    if (this.isShot()) return;
    localStorage.setItem(draftKey(doc), canonicalDirectionString(doc));
  }

  private readWorkspace(): WorkspaceDocument | null {
    try { return JSON.parse(localStorage.getItem(WORKSPACE_KEY) ?? 'null') as WorkspaceDocument | null; }
    catch { return null; }
  }

  async saveWorkspace(workspace: WorkspaceDocument): Promise<void> {
    if (this.isShot()) return;
    localStorage.setItem(WORKSPACE_KEY, JSON.stringify(workspace));
  }

  resetDemo(): void {
    localStorage.removeItem(draftKey(demoDocument));
  }
}
