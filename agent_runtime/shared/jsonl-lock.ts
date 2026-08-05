import { createRequire } from "node:module";

const properLockfile = createRequire(import.meta.url)("proper-lockfile") as typeof import("proper-lockfile");

const STALE_AFTER_MS = 30_000;

/**
 * Cross-process mutex for one JSONL stream. `proper-lockfile` uses atomic mkdir,
 * a heartbeat and ownership-aware release, avoiding the stale-file CAS race of
 * hand-rolled lock files. `realpath:false` also permits first-write streams.
 */
export async function withJsonlLock<T>(path: string, label: string, action: () => Promise<T>): Promise<T> {
  let release: (() => Promise<void>) | undefined;
  try {
    release = await properLockfile.lock(path, {
      realpath: false,
      stale: STALE_AFTER_MS,
      update: STALE_AFTER_MS / 3,
      retries: { retries: 5, factor: 1, minTimeout: 10, maxTimeout: 10, randomize: true },
    });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ELOCKED") throw new Error(`${label} is locked`);
    throw error;
  }
  try {
    return await action();
  } finally {
    await release();
  }
}
