import { describe, it, expect, beforeEach } from "vitest";
import {
  getSettings,
  setGatewayUrl,
  setAuthToken,
  getRecentClips,
  addRecentClip,
  updateClipStatus,
} from "../storage";
import { resetStorage } from "../../test-setup";
import type { ClipRecord } from "../../types";

beforeEach(() => {
  resetStorage();
});

function makeClip(overrides: Partial<ClipRecord> = {}): ClipRecord {
  return {
    sourceId: `src-${Math.random().toString(36).slice(2, 6)}`,
    url: "https://example.com",
    title: "Test",
    status: "pending",
    clippedAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("getSettings", () => {
  it("returns default gateway URL when empty", async () => {
    const settings = await getSettings();
    expect(settings.gatewayUrl).toBe("https://wikimind.fly.dev");
  });

  it("returns stored gateway URL", async () => {
    await chrome.storage.local.set({ gatewayUrl: "http://custom:9000" });
    const settings = await getSettings();
    expect(settings.gatewayUrl).toBe("http://custom:9000");
  });
});

describe("setGatewayUrl", () => {
  it("persists the URL", async () => {
    await setGatewayUrl("http://new:8080");
    const settings = await getSettings();
    expect(settings.gatewayUrl).toBe("http://new:8080");
  });
});

describe("authToken", () => {
  it("returns empty string when no token stored", async () => {
    const settings = await getSettings();
    expect(settings.authToken).toBe("");
  });

  it("returns stored token", async () => {
    await setAuthToken("eyJhbGciOiJIUzI1NiJ9.test");
    const settings = await getSettings();
    expect(settings.authToken).toBe("eyJhbGciOiJIUzI1NiJ9.test");
  });
});

describe("getRecentClips", () => {
  it("returns empty array when no clips stored", async () => {
    const clips = await getRecentClips();
    expect(clips).toEqual([]);
  });
});

describe("addRecentClip", () => {
  it("prepends new clip", async () => {
    const clip1 = makeClip({ sourceId: "a" });
    const clip2 = makeClip({ sourceId: "b" });

    await addRecentClip(clip1);
    await addRecentClip(clip2);

    const clips = await getRecentClips();
    expect(clips[0].sourceId).toBe("b");
    expect(clips[1].sourceId).toBe("a");
  });

  it("caps at 20 clips", async () => {
    for (let i = 0; i < 25; i++) {
      await addRecentClip(makeClip({ sourceId: `clip-${i}` }));
    }

    const clips = await getRecentClips();
    expect(clips.length).toBe(20);
    expect(clips[0].sourceId).toBe("clip-24");
  });
});

describe("updateClipStatus", () => {
  it("updates status of matching clip", async () => {
    await addRecentClip(makeClip({ sourceId: "abc", status: "pending" }));
    await updateClipStatus("abc", "compiled");

    const clips = await getRecentClips();
    expect(clips[0].status).toBe("compiled");
  });

  it("does nothing for unknown sourceId", async () => {
    await addRecentClip(makeClip({ sourceId: "abc", status: "pending" }));
    await updateClipStatus("unknown", "compiled");

    const clips = await getRecentClips();
    expect(clips[0].status).toBe("pending");
  });
});
