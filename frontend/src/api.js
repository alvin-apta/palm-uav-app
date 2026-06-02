const API_BASE_URL = resolvePublicUrl(import.meta.env.VITE_API_BASE_URL || "http://localhost:8080", "8090");
const TITILER_PROXY_PREFIX = "/titiler";

function resolvePublicUrl(configuredUrl, publicPort) {
  if (typeof window === "undefined") return configuredUrl;
  const currentHost = window.location.hostname;
  if (currentHost === "localhost" || currentHost === "127.0.0.1") return configuredUrl;

  try {
    const url = new URL(configuredUrl);
    if (url.hostname === "localhost" || url.hostname === "127.0.0.1") {
      return "/api";
    }
  } catch {
    return configuredUrl;
  }

  return configuredUrl;
}

export function apiBaseUrl() {
  return API_BASE_URL;
}

export function publicAssetUrl(url) {
  if (!url || typeof url !== "string" || typeof window === "undefined") return url;
  if (!url.startsWith(TITILER_PROXY_PREFIX)) return url;
  if (window.location.port !== "5173") return url;

  const path = url.slice(TITILER_PROXY_PREFIX.length) || "/";
  return `${window.location.protocol}//${window.location.hostname}:8082${path}`;
}

export async function login(email, password) {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  return parseResponse(response);
}

export async function apiFetch(path, token, options = {}) {
  const headers = new Headers(options.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  return parseResponse(response);
}

export async function apiBlob(path, token, options = {}) {
  const headers = new Headers(options.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail || "Export failed");
  }
  return response.blob();
}

export function apiUpload(path, token, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}${path}`);
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      onProgress?.(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      const payload = safeJson(xhr.responseText);
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(formatApiError(payload) || `Upload failed: ${xhr.status}`));
        return;
      }
      resolve(payload);
    };
    xhr.onerror = () => reject(new Error("Upload failed: network error"));
    xhr.onabort = () => reject(new Error("Upload cancelled"));
    xhr.send(formData);
  });
}

async function parseResponse(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(formatApiError(payload) || `Request failed: ${response.status}`);
  }
  return payload;
}

function formatApiError(payload) {
  if (!payload) return "";
  if (typeof payload.detail === "string") return payload.detail;
  if (Array.isArray(payload.detail)) {
    return payload.detail
      .map((item) => {
        const location = Array.isArray(item.loc) ? item.loc.join(".") : "";
        return `${location ? `${location}: ` : ""}${item.msg || JSON.stringify(item)}`;
      })
      .join("; ");
  }
  if (payload.message) return payload.message;
  return "";
}

function safeJson(text) {
  try {
    return JSON.parse(text || "{}");
  } catch {
    return {};
  }
}
