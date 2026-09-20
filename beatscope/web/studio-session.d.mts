export declare const HIGH_PRECISION_BACKEND: 'enhanced';
export declare function analyzeUrl(options?: { backend?: string; subdivision?: number }): string;
export interface SessionFilmView {
  videoUrl?: string;
  videoJobId?: string;
}

export declare function applyJobToSession<F extends SessionFilmView, J extends { id: string; state: string; video_url?: string }>(
  session: F,
  job: J,
): F & { videoUrl?: string; videoJobId?: string; job: J };

export declare function lastFilmUrl(session: SessionFilmView | null): string | null;
export declare function shouldKeepTracking(error: unknown): boolean;
export declare function pollRetryDelayMs(failures: number): number;
export declare function trackJob<J>(options: {
  read: () => Promise<J>;
  accept: (job: J) => boolean | Promise<boolean>;
  isCurrent: () => boolean;
  sleep?: (ms: number) => Promise<unknown>;
}): Promise<void>;
