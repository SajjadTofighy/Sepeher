import type { Asset } from "../../types";

// Timestamp-based playback supports uneven GPS reporting intervals and any track length.
export function visibleTrack(
  track: Asset["track"],
  progress: number,
): Asset["track"] {
  if (track.length < 2 || progress >= 100) return track;
  const first = Date.parse(track[0].time);
  const last = Date.parse(track[track.length - 1].time);
  const cutoff = first + ((last - first) * Math.max(0, progress)) / 100;
  const next = track.findIndex((p) => Date.parse(p.time) > cutoff);
  if (next < 0) return track;
  if (next === 0) return [track[0]];
  // Only recorded positions are displayed; no invented intermediate GPS samples.
  return track.slice(0, next);
}
export function playbackPosition(asset: Asset, progress: number) {
  const points = visibleTrack(asset.track, progress);
  return progress < 100 && points.length ? points[points.length - 1] : asset;
}
export const routeColors = [
  "#74e3c3",
  "#75bcff",
  "#e9b873",
  "#ce9dff",
  "#ff96a8",
  "#99d889",
];
