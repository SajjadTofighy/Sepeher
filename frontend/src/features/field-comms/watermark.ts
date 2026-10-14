import type { FieldMedia } from "../../types";

// The stored original stays untouched; the viewer's watermark is drawn at display/export time.
export const watermarkLines = (media: FieldMedia, classification: string) => {
  const w = media.watermark;
  if (!w) return [classification];
  return [
    classification,
    `ثبت ${w.captured_at_jalali} · نگهبان ${w.guard_code} · ایستگاه ${w.station_code}`,
    `بیننده ${w.viewer} · ${w.viewed_at_jalali}`,
  ];
};

export async function watermarkedImage(blob: Blob, lines: string[]) {
  const bitmap = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const context = canvas.getContext("2d")!;
  context.drawImage(bitmap, 0, 0);
  const size = Math.max(14, Math.round(bitmap.width / 40));
  context.font = `600 ${size}px Vazirmatn, Tahoma, sans-serif`;
  context.textAlign = "center";
  context.fillStyle = "rgba(255,255,255,0.32)";
  context.save();
  context.translate(bitmap.width / 2, bitmap.height / 2);
  context.rotate(-Math.PI / 7);
  const step = size * 7;
  for (let y = -bitmap.height; y < bitmap.height; y += step)
    lines.forEach((line, i) => context.fillText(line, 0, y + i * size * 1.4));
  context.restore();
  context.textAlign = "right";
  context.fillStyle = "rgba(0,0,0,0.6)";
  context.fillRect(0, bitmap.height - size * 1.6 * lines.length - size, bitmap.width, size * 1.6 * lines.length + size);
  context.fillStyle = "#fff";
  lines.forEach((line, i) => context.fillText(line, bitmap.width - size, bitmap.height - size * 1.6 * (lines.length - i - 0.6)));
  bitmap.close();
  return new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((out) => (out ? resolve(out) : reject(new Error("ساخت تصویر نشان‌دار ممکن نشد"))), "image/png"),
  );
}
