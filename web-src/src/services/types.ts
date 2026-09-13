/**
 * Typed capability adapters (plan §3.7). The same React tree runs in two
 * modes; components ask the capability service, never the hostname.
 */
import type { DirectionDocument, WorkspaceDocument } from '../direction/types';
import type { DemoRhythm } from '../demo/rhythm';
import type { AssetClient } from '../media/client';

export interface ProjectSummary {
  project_id: string;
  display_name: string;
}

export interface AnalysisJob {
  job_id: string;
  status: string;
}

export interface BeatScopeServices {
  readonly mode: 'local-studio' | 'static-demo';
  /** Project media capabilities; `available: false` removes the affordance. */
  readonly assets: AssetClient;
  listProjects(): Promise<ProjectSummary[]>;
  loadProject(projectId: string): Promise<{
    doc: DirectionDocument;
    rhythm: DemoRhythm | null;
    workspace: WorkspaceDocument | null;
    recoveredDraft?: boolean;
    /** v0.11 response-relevance sidecar keyed by onset id; null when absent */
    relevance?: Map<string, number> | null;
  }>;
  submitAnalysis(file: File): Promise<AnalysisJob | null>;
  cancelAnalysis(jobId: string): Promise<boolean>;
  audioUrlFor(projectId: string): string | null;
  hasAudio(): boolean;
  /**
   * Persist the direction document (Round 2 Commit 1): local-studio PUTs
   * canonical bytes with If-Match and throws DirectionConflictError on a
   * refused save (412/428); the demo writes a validated local draft.
   */
  saveDirection(doc: DirectionDocument): Promise<void>;
  saveDraft(doc: DirectionDocument): void;
  saveWorkspace(workspace: WorkspaceDocument): Promise<void>;
}
