import { vi } from "vitest";

const storageMock: Record<string, unknown> = {};

globalThis.chrome = {
  storage: {
    local: {
      get: vi.fn().mockImplementation((keys: string | string[]) => {
        if (typeof keys === "string") {
          return Promise.resolve({ [keys]: storageMock[keys] });
        }
        const result: Record<string, unknown> = {};
        for (const k of keys) {
          result[k] = storageMock[k];
        }
        return Promise.resolve(result);
      }),
      set: vi.fn().mockImplementation((items: Record<string, unknown>) => {
        Object.assign(storageMock, items);
        return Promise.resolve();
      }),
    },
  },
  tabs: {
    query: vi.fn().mockImplementation(
      (_query: unknown, cb: (tabs: { url: string }[]) => void) =>
        cb([{ url: "https://example.com/article" }])
    ),
  },
  action: {
    setBadgeText: vi.fn(),
    setBadgeBackgroundColor: vi.fn(),
  },
  runtime: {
    onMessage: { addListener: vi.fn() },
    sendMessage: vi.fn(),
  },
} as unknown as typeof chrome;

/** Reset mock storage between tests. */
export function resetStorage(): void {
  for (const key of Object.keys(storageMock)) {
    delete storageMock[key];
  }
  vi.mocked(chrome.storage.local.get).mockClear();
  vi.mocked(chrome.storage.local.set).mockClear();
}
