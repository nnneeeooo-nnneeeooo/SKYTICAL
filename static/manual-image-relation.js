(() => {
  "use strict";

  const toggle = document.getElementById("image-direct-relation");
  if (!toggle) return;

  const originalFetch = window.fetch.bind(window);
  const encoder = new TextEncoder();
  const decoder = new TextDecoder();

  function bytesToBase64(bytes) {
    let binary = "";
    for (let start = 0; start < bytes.length; start += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
    }
    return btoa(binary);
  }

  function base64ToBytes(value) {
    const binary = atob(String(value || "").replace(/\s/g, ""));
    return Uint8Array.from(binary, char => char.charCodeAt(0));
  }

  function isManualArticleWrite(input, init) {
    const url = typeof input === "string" ? input : input?.url || "";
    const method = String(
      init?.method || (input instanceof Request ? input.method : "GET"),
    ).toUpperCase();
    return method === "PUT"
      && /\/contents\/data\/articles\/manual-[^/?]+\.json(?:\?|$)/.test(url);
  }

  function applyImageRelation(bodyText) {
    const requestBody = JSON.parse(bodyText);
    if (typeof requestBody.content !== "string") return bodyText;

    const payload = JSON.parse(
      decoder.decode(base64ToBytes(requestBody.content)),
    );
    const article = Array.isArray(payload?.articles)
      ? payload.articles[0] : null;
    const image = article?.image;
    if (!image || image.provider !== "AVWIRE manual upload") return bodyText;

    const directlyRelated = toggle.checked;
    image.manualDirectRelation = directlyRelated;
    image.kind = directlyRelated ? "event_photo" : "file_photo";
    requestBody.content = bytesToBase64(
      encoder.encode(`${JSON.stringify(payload, null, 2)}\n`),
    );
    return JSON.stringify(requestBody);
  }

  window.fetch = (input, init = {}) => {
    if (!isManualArticleWrite(input, init) || typeof init.body !== "string") {
      return originalFetch(input, init);
    }

    try {
      return originalFetch(input, {
        ...init,
        body: applyImageRelation(init.body),
      });
    } catch (error) {
      console.warn("Unable to apply manual image relation metadata", error);
      return originalFetch(input, init);
    }
  };
})();
