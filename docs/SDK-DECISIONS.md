# UI SDK decisions

This demo intentionally combines specialist libraries with clear ownership. Versions are pinned in package.json/package-lock.json for reproducible delivery; this is not a claim that each is the newest release.

| Concern | Library | Implemented use |
|---|---|---|
| UI | React 19 + TypeScript strict | Feature modules, typed contracts, lazy analytics, error boundary |
| GIS | MapLibre GL JS 5 | OSM/OpenFreeMap custom vector style, GeoJSON import/export, WMS/WFS, geographic measurement, polygons, heatmap, clusters, tracks |
| Charting | Apache ECharts 5 | Interactive time trend, tooltips, data zoom, SVG renderer, resize/dispose lifecycle |
| Server state | TanStack Query 5 | Bootstrap query, cancellation signal, cache, 3-second refresh, bounded retry |
| Tables | TanStack Table 8 | Reusable headless data grid with sorting and pagination |
| Icons | Lucide React | Consistent operational iconography |
| Persian typography | Vazirmatn / Fontsource | Bundled font files without runtime CDN calls |
| Contract generation | openapi-typescript | DTOs generated from Python OpenAPI |
| Development / build | Vite + esbuild | HMR in development; typechecked, minified, split production distribution |
| API | FastAPI + Pydantic | Validated requests, response models, local Swagger documentation |

Official documentation consulted:
- https://maplibre.org/maplibre-gl-js/docs/API/classes/GeoJSONSource/
- https://maplibre.org/maplibre-gl-js/docs/API/classes/Map/
- https://tanstack.com/query/latest/docs/framework/react/overview
- https://tanstack.com/table/v8/docs/overview
- https://echarts.apache.org/handbook/en/concepts/chart-size/

MapLibre is appropriate for operational GIS. A separate globe engine or deck.gl would add bundle and lifecycle complexity without a demonstrated need for this 12-entity demo. For millions of points or specialized GPU overlays, add deck.gl at the map adapter boundary. For an executive globe, add Cesium on a separate route; do not initialize two map engines simultaneously without a specific product requirement.

Native HTML dialog is used for keyboard/focus behavior. A large general component kit is not required to preserve a coherent design system. Shared primitives and CSS tokens own visual consistency.

The non-WebGL fallback uses real OSM raster tiles with operational SVG overlays and the same API records and selection callbacks. Advanced GIS tools use MapLibre. Chrome browser checks cover the real vector basemap and the raster fallback; see OMIDIYEH-MAP.fa.md.

No external tiles, real company coordinates, surveillance feeds, or GPU/LLM inference are included.
