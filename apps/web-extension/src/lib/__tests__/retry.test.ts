import { describe, it, expect, vi } from "vitest";
import { withRetry, ApiError } from "../retry";

describe("withRetry", () => {
  it("returns on first success", async () => {
    const fn = vi.fn().mockResolvedValue("ok");
    const result = await withRetry(fn);
    expect(result).toBe("ok");
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("retries on 500 errors", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(500, "Internal", null))
      .mockResolvedValue("ok");

    const result = await withRetry(fn, { baseDelayMs: 1 });
    expect(result).toBe("ok");
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("retries on network errors (TypeError)", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValue("ok");

    const result = await withRetry(fn, { baseDelayMs: 1 });
    expect(result).toBe("ok");
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("does NOT retry on 4xx errors", async () => {
    const fn = vi
      .fn()
      .mockRejectedValue(new ApiError(400, "Bad Request", null));

    await expect(withRetry(fn, { baseDelayMs: 1 })).rejects.toThrow(
      "Bad Request"
    );
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("throws after maxAttempts", async () => {
    const fn = vi
      .fn()
      .mockRejectedValue(new ApiError(503, "Unavailable", null));

    await expect(
      withRetry(fn, { maxAttempts: 3, baseDelayMs: 1 })
    ).rejects.toThrow("Unavailable");
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it("applies exponential backoff", async () => {
    const delays: number[] = [];
    const originalSetTimeout = globalThis.setTimeout;
    vi.spyOn(globalThis, "setTimeout").mockImplementation(
      (fn: TimerHandler, ms?: number) => {
        if (ms !== undefined) delays.push(ms);
        if (typeof fn === "function") fn();
        return 0 as unknown as ReturnType<typeof originalSetTimeout>;
      }
    );

    const apiFn = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(500, "fail", null))
      .mockRejectedValueOnce(new ApiError(500, "fail", null))
      .mockResolvedValue("ok");

    await withRetry(apiFn, { maxAttempts: 3, baseDelayMs: 100 });
    expect(delays).toEqual([100, 200]);

    vi.restoreAllMocks();
  });
});
