import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { StyleSpecification } from "maplibre-gl";
import nightStyleJSON from "./omidiyeh-night.json";
const nightStyle = nightStyleJSON as unknown as StyleSpecification;
export type BasemapMode = "night" | "street";
// OSM relation 16776135 (Omidiyeh, Khuzestan), verified using Nominatim.
export const OMIDIYEH_CENTER: [number, number] = [49.7017752, 30.7568821];
export const OMIDIYEH_BOUNDS: [[number, number], [number, number]] = [
  [49.6726002, 30.7339043],
  [49.7299453, 30.7817512],
];
export const baseLayerIds = nightStyle.layers.map((layer) => layer.id);
export const labelLayerIds = nightStyle.layers
  .filter((layer) => layer.type === "symbol")
  .map((layer) => layer.id);
export const buildingLayerIds = nightStyle.layers
  .filter((layer) => layer.id.startsWith("building"))
  .map((layer) => layer.id);
// Synthetic operational area around Aghajari fields; the command map opens on all of it.
export function operationalBounds(
  zones: { points: number[][] }[],
  assets: { lon: number; lat: number }[],
): [[number, number], [number, number]] {
  const points = [
    ...zones.flatMap((z) => z.points),
    ...assets.map((a) => [a.lon, a.lat]),
  ];
  if (!points.length) return OMIDIYEH_BOUNDS;
  const lons = points.map((p) => p[0]);
  const lats = points.map((p) => p[1]);
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ];
}
export const feature = (
  geometry: Geometry,
  properties: Record<string, unknown> = {},
): Feature => ({ type: "Feature", geometry, properties });
export const collection = (features: Feature[]): FeatureCollection => ({
  type: "FeatureCollection",
  features,
});
export const empty = collection([]);
export const mapStyle: StyleSpecification = {
  version: 8,
  glyphs: nightStyle.glyphs,
  sources: {
    ...nightStyle.sources,
    "osm-street": {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors',
    },
    zones: { type: "geojson", data: empty },
    assets: {
      type: "geojson",
      data: empty,
      cluster: true,
      clusterMaxZoom: 9,
      clusterRadius: 45,
    },
    incidents: { type: "geojson", data: empty },
    tracks: { type: "geojson", data: empty },
    command: { type: "geojson", data: empty },
    coverage: { type: "geojson", data: empty },
  },
  layers: [
    ...nightStyle.layers,
    {
      id: "osm-street",
      type: "raster",
      source: "osm-street",
      layout: { visibility: "none" },
      paint: { "raster-fade-duration": 200 },
    },
    {
      id: "zone-fill",
      type: "fill",
      source: "zones",
      paint: {
        "fill-color": ["get", "color"],
        "fill-opacity": ["case", ["get", "alert"], 0.22, 0.07],
      },
    },
    {
      id: "zone-glow",
      type: "line",
      source: "zones",
      paint: {
        "line-color": ["get", "color"],
        "line-width": ["case", ["get", "alert"], 10, 6],
        "line-blur": 8,
        "line-opacity": ["case", ["get", "alert"], 0.6, 0.22],
      },
    },
    {
      id: "zone-line",
      type: "line",
      source: "zones",
      paint: {
        "line-color": ["get", "color"],
        "line-width": ["case", ["get", "alert"], 2.6, 1.4],
        "line-dasharray": [4, 4],
        "line-opacity": ["case", ["get", "alert"], 1, 0.75],
      },
    },
    {
      id: "coverage-fill",
      type: "fill",
      source: "coverage",
      layout: { visibility: "none" },
      paint: { "fill-color": "#9b7bc4", "fill-opacity": 0.21 },
    },
    {
      id: "coverage-line",
      type: "line",
      source: "coverage",
      layout: { visibility: "none" },
      paint: {
        "line-color": "#a98ccd",
        "line-width": 1,
        "line-dasharray": [4, 4],
      },
    },
    {
      id: "heat",
      type: "heatmap",
      source: "incidents",
      layout: { visibility: "none" },
      paint: {
        "heatmap-radius": 70,
        "heatmap-opacity": 0.65,
        "heatmap-color": [
          "interpolate",
          ["linear"],
          ["heatmap-density"],
          0,
          "rgba(60,150,140,0)",
          0.3,
          "#69b8a1",
          0.6,
          "#e4bd62",
          1,
          "#ee755d",
        ],
      },
    },
    {
      id: "track-casing",
      type: "line",
      source: "tracks",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": "#081520",
        "line-width": ["case", ["get", "selected"], 8, 6],
        "line-opacity": 0.85,
      },
    },
    {
      id: "track-glow",
      type: "line",
      source: "tracks",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": ["get", "color"],
        "line-width": ["case", ["get", "selected"], 13, 9],
        "line-blur": 7,
        "line-opacity": ["case", ["get", "selected"], 0.5, 0.22],
      },
    },
    {
      id: "track",
      type: "line",
      source: "tracks",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": ["get", "color"],
        "line-width": ["case", ["get", "selected"], 5, 3.2],
        "line-opacity": 0.95,
      },
    },
    {
      id: "command-line",
      type: "line",
      source: "command",
      layout: { "line-cap": "round" },
      paint: {
        "line-color": ["case", ["get", "dispatched"], "#74e3c3", "#f3c477"],
        "line-width": ["case", ["get", "dispatched"], 4, 2],
        "line-dasharray": [2, 2],
        "line-opacity": 0.9,
      },
    },
    {
      id: "clusters",
      type: "circle",
      source: "assets",
      filter: ["has", "point_count"],
      paint: {
        "circle-radius": 22,
        "circle-color": "#275e59",
        "circle-stroke-color": "#73c5b4",
        "circle-stroke-width": 2,
      },
    },
    {
      id: "cluster-core",
      type: "circle",
      source: "assets",
      filter: ["has", "point_count"],
      paint: { "circle-radius": 5, "circle-color": "#9ad8c8" },
    },
  ],
};
// Production never touches public tile services: without an approved internal style the map is
// schematic (operational layers on a plain background) and makes no basemap request at all.
const publicSources = new Set(["openmaptiles", "osm-street"]);
export const schematicStyle: StyleSpecification = {
  version: 8,
  sources: Object.fromEntries(
    Object.entries(mapStyle.sources).filter(([id]) => !publicSources.has(id)),
  ),
  layers: mapStyle.layers.filter(
    (layer) => layer.id === "background" || (!baseLayerIds.includes(layer.id) && layer.id !== "osm-street"),
  ),
};
