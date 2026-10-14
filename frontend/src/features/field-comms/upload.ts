import { api, parseResponse, sessionHeaders } from "../../api";
import type { FieldMedia, MediaUpload, MediaUploadInput, MediaUploadResult } from "../../types";

export async function sha256Hex(blob: Blob) {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
// Exponential backoff with jitter for weak field networks.
const backoff = (attempt: number) => Math.min(30000, 1000 * 2 ** attempt) * (0.5 + Math.random() / 2);

async function raw<T>(path: string, method: string, body: Blob, contentType = "application/octet-stream") {
  const response = await fetch("/api/v1" + path, {
    method,
    headers: { "Content-Type": contentType, ...sessionHeaders() },
    body,
  });
  return parseResponse<T>(response);
}

export type UploadProgress = (received: number, total: number) => void;

/**
 * Resumable upload: the server-side received_bytes is authoritative, so a retry or
 * a restarted page continues from GET status instead of resending the whole file.
 * The same client_id makes repeating start idempotent.
 */
export async function uploadMedia(
  blob: Blob,
  meta: Omit<MediaUploadInput, "sha256" | "size" | "content_type">,
  onProgress?: UploadProgress,
): Promise<MediaUploadResult> {
  const contentType = blob.type.split(";")[0];
  const sha256 = await sha256Hex(blob);
  let upload = await api<MediaUpload>("/media/uploads", "POST", { ...meta, sha256, size: blob.size, content_type: contentType });
  let attempt = 0;
  while (upload.received_bytes < upload.size) {
    const end = Math.min(upload.size, upload.received_bytes + upload.chunk_bytes);
    try {
      upload = await raw<MediaUpload>(
        `/media/uploads/${upload.id}?offset=${upload.received_bytes}`,
        "PUT",
        blob.slice(upload.received_bytes, end),
      );
      attempt = 0;
      onProgress?.(upload.received_bytes, upload.size);
    } catch (error) {
      const status = (error as { status?: number }).status;
      if (status && status >= 400 && status < 500 && status !== 409) throw error;
      if (attempt >= 6) throw error;
      await wait(backoff(attempt++));
      upload = await api<MediaUpload>(`/media/uploads/${upload.id}`);
    }
  }
  return api<MediaUploadResult>(`/media/uploads/${upload.id}/complete`, "POST");
}

export async function fetchMediaBlob(media: FieldMedia) {
  const response = await fetch(`/api/v1/media/${media.id}/content`, { headers: sessionHeaders(), cache: "no-store" });
  if (!response.ok) await parseResponse(response);
  return response.blob();
}

export function rawPut(path: string, blob: Blob) {
  return raw<FieldMedia>(path, "PUT", blob, blob.type.split(";")[0]);
}
