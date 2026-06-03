const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export function toAssetUrl(path) {
  if (!path) {
    return null;
  }
  if (/^https?:\/\//.test(path)) {
    return path;
  }
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

async function handleResponse(response) {
  if (!response.ok) {
    let message = "请求失败";
    try {
      const data = await response.json();
      message = data.detail || data.message || message;
    } catch (error) {
      message = response.statusText || message;
    }
    throw new Error(message);
  }
  return response.json();
}

export async function fetchDocuments() {
  const response = await fetch(`${API_BASE}/api/documents`);
  return handleResponse(response);
}

export async function fetchApiKeyStatus() {
  const response = await fetch(`${API_BASE}/api/config/key`);
  return handleResponse(response);
}

export async function fetchMcpConfigStatus() {
  const response = await fetch(`${API_BASE}/api/config/mcp`);
  return handleResponse(response);
}

export async function saveApiKey(dashscopeApiKey) {
  const response = await fetch(`${API_BASE}/api/config/key`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ dashscope_api_key: dashscopeApiKey }),
  });
  return handleResponse(response);
}

export async function saveMcpConfig(dingtalkMcpUrl) {
  const response = await fetch(`${API_BASE}/api/config/mcp`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ dingtalk_mcp_url: dingtalkMcpUrl }),
  });
  return handleResponse(response);
}

export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${API_BASE}/api/documents/upload`, {
    method: "POST",
    body: formData,
  });
  return handleResponse(response);
}

export async function uploadDocumentUrl({ url, title }) {
  const response = await fetch(`${API_BASE}/api/documents/upload-url`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ url, title: title || null }),
  });
  return handleResponse(response);
}

export async function reindexDocument(documentId) {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/reindex`, {
    method: "POST",
  });
  return handleResponse(response);
}

export async function refreshLinkDocument(documentId) {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/refresh-link`, {
    method: "POST",
  });
  return handleResponse(response);
}

export async function fetchDocumentChunks(documentId) {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/chunks`);
  return handleResponse(response);
}

export async function deleteDocument(documentId) {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    return handleResponse(response);
  }
  return null;
}

export async function askQuestion({ question, topK }) {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question, top_k: topK }),
  });
  return handleResponse(response);
}

export async function generatePrd({ sessionId, requirement, useRag, topK }) {
  const response = await fetch(`${API_BASE}/api/prd/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      session_id: sessionId,
      requirement,
      use_rag: useRag,
      top_k: topK,
      mode: "full_prd",
    }),
  });
  return handleResponse(response);
}

export async function clearPrdMemory(sessionId) {
  const response = await fetch(`${API_BASE}/api/prd/sessions/${encodeURIComponent(sessionId)}/memory`, {
    method: "DELETE",
  });
  return handleResponse(response);
}

export async function fetchChunk(chunkId) {
  const response = await fetch(`${API_BASE}/api/chunks/${chunkId}`);
  return handleResponse(response);
}

export function streamQuestion({ question, topK, onToken, onMeta, onError, onDone }) {
  const url = new URL(`${API_BASE}/api/chat/stream`);
  url.searchParams.set("question", question);
  if (typeof topK === "number") {
    url.searchParams.set("top_k", String(topK));
  }
  const source = new EventSource(url);
  let closedByApp = false;

  source.addEventListener("token", (event) => {
    const payload = JSON.parse(event.data);
    onToken?.(payload);
  });

  source.addEventListener("meta", (event) => {
    const payload = JSON.parse(event.data);
    onMeta?.(payload);
  });

  source.addEventListener("app-error", (event) => {
    if (event.data) {
      const payload = JSON.parse(event.data);
      onError?.(payload.message);
    } else {
      onError?.("流式请求中断");
    }
    closedByApp = true;
    source.close();
  });

  source.addEventListener("done", () => {
    closedByApp = true;
    onDone?.();
    source.close();
  });

  source.onerror = () => {
    if (closedByApp) {
      return;
    }
    onError?.("无法连接到流式问答接口");
    source.close();
  };

  return source;
}

export function streamPrd({ sessionId, requirement, useRag, topK, onToken, onMeta, onError, onDone }) {
  const url = new URL(`${API_BASE}/api/prd/stream`);
  url.searchParams.set("session_id", sessionId);
  url.searchParams.set("requirement", requirement);
  url.searchParams.set("use_rag", String(Boolean(useRag)));
  url.searchParams.set("mode", "full_prd");
  if (typeof topK === "number") {
    url.searchParams.set("top_k", String(topK));
  }
  const source = new EventSource(url);
  let closedByApp = false;

  source.addEventListener("token", (event) => {
    const payload = JSON.parse(event.data);
    onToken?.(payload);
  });

  source.addEventListener("meta", (event) => {
    const payload = JSON.parse(event.data);
    onMeta?.(payload);
  });

  source.addEventListener("app-error", (event) => {
    if (event.data) {
      const payload = JSON.parse(event.data);
      onError?.(payload.message);
    } else {
      onError?.("PRD stream interrupted");
    }
    closedByApp = true;
    source.close();
  });

  source.addEventListener("done", () => {
    closedByApp = true;
    onDone?.();
    source.close();
  });

  source.onerror = () => {
    if (closedByApp) {
      return;
    }
    onError?.("Unable to connect to PRD stream API");
    source.close();
  };

  return source;
}
