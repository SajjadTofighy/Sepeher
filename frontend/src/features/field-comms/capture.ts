export type { CapturePolicy } from "../../types";

// Server-allowed content types; MediaRecorder output must match one of them.
const ALLOWED = {
  audio: ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"],
  video: ["video/webm;codecs=vp8,opus", "video/webm", "video/mp4"],
};

export const pickMimeType = (kind: "audio" | "video") =>
  typeof MediaRecorder === "undefined" ? "" : ALLOWED[kind].find((type) => MediaRecorder.isTypeSupported(type)) || "";

// Captured in memory only: nothing is written to the gallery or downloads.
export function takePhoto(video: HTMLVideoElement) {
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d")!.drawImage(video, 0, 0);
  return new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("گرفتن عکس ممکن نشد"))), "image/jpeg", 0.85),
  );
}

export function recordMedia(
  stream: MediaStream,
  mimeType: string,
  kind: "audio" | "video",
  bitsPerSecond: number,
  maxSeconds: number,
  onDone: (blob: Blob) => void,
) {
  const recorder = new MediaRecorder(stream, kind === "audio" ? { mimeType, audioBitsPerSecond: bitsPerSecond } : { mimeType, videoBitsPerSecond: bitsPerSecond });
  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => event.data.size && chunks.push(event.data);
  recorder.onstop = () => onDone(new Blob(chunks, { type: mimeType.split(";")[0] }));
  recorder.start(1000);
  const timer = setTimeout(() => recorder.state !== "inactive" && recorder.stop(), maxSeconds * 1000);
  return {
    stop: () => {
      clearTimeout(timer);
      if (recorder.state !== "inactive") recorder.stop();
    },
  };
}
