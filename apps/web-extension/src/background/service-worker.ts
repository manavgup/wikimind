chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "clip:success") {
    chrome.action.setBadgeText({ text: "\u2713" });
    chrome.action.setBadgeBackgroundColor({ color: "#22c55e" });
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 3000);
  }

  if (msg.type === "clip:error") {
    chrome.action.setBadgeText({ text: "!" });
    chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 5000);
  }

  sendResponse({ ok: true });
  return false;
});
