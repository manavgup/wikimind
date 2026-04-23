import { describe, it, expect, vi, beforeEach } from "vitest";
import { clipUrl, getSource, listRecentSources } from "../api";
import { resetStorage } from "../../test-setup";

const fetchMock = vi.fn();
globalThis.fetch = fetchMock;

beforeEach(() => {
  fetchMock.mockReset();
  resetStorage();
});

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(data),
  } as Response;
}

describe("clipUrl", () => {
  it("POSTs to /ingest/url with correct body", async () => {
    const source = { id: "abc", status: "pending", title: "Test" };
    fetchMock.mockResolvedValue(jsonResponse(source));

    const result = await clipUrl("https://example.com");
    expect(result).toEqual(source);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:7842/ingest/url",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          url: "https://example.com",
          auto_compile: true,
        }),
      })
    );
  });

  it("uses custom gateway URL from storage", async () => {
    await chrome.storage.local.set({
      gatewayUrl: "http://myhost:9000",
    });
    fetchMock.mockResolvedValue(
      jsonResponse({ id: "x", status: "pending" })
    );

    await clipUrl("https://example.com");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://myhost:9000/ingest/url",
      expect.anything()
    );
  });

  it("parses error response in WikiMind format", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { error: { code: "bad_url", message: "Invalid URL" } },
        400
      )
    );

    await expect(clipUrl("bad")).rejects.toThrow("Invalid URL");
  });
});

describe("getSource", () => {
  it("GETs /ingest/sources/:id", async () => {
    const source = { id: "abc", status: "compiled" };
    fetchMock.mockResolvedValue(jsonResponse(source));

    const result = await getSource("abc");
    expect(result).toEqual(source);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:7842/ingest/sources/abc",
      expect.anything()
    );
  });
});

describe("listRecentSources", () => {
  it("GETs /ingest/sources with limit", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));

    await listRecentSources(3);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:7842/ingest/sources?limit=3",
      expect.anything()
    );
  });
});
