import * as React from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const { useEffect, useRef, useState } = React;
const CANOPY_COLORS = {
  small_canopy: "#eab308",
  medium_canopy: "#16a34a",
  large_canopy: "#2563eb",
};

export default function MapPanel({
  trees,
  detections = { type: "FeatureCollection", features: [] },
  areaPolygons = { type: "FeatureCollection", features: [] },
  showDetectionBoxes = true,
  showTreePoints = false,
  drawingArea = false,
  cogSource,
  cogBounds,
  cogLayers = [],
  cogBoundsList = [],
  zoomRequest = 0,
  locateRequest = 0,
  onDrawPolygon,
  onLocateError,
}) {
  const mapRef = useRef(null);
  const containerRef = useRef(null);
  const locationMarkerRef = useRef(null);
  const hoverPopupRef = useRef(null);
  const cogLayerIdsRef = useRef([]);
  const draftAreaRef = useRef([]);
  const drawingAreaRef = useRef(false);
  const [mapReady, setMapReady] = useState(false);

  useEffect(() => {
    drawingAreaRef.current = drawingArea;
  }, [drawingArea]);

  useEffect(() => {
    if (mapRef.current || !containerRef.current) return;
    mapRef.current = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "OpenStreetMap contributors",
          },
        },
        layers: [{ id: "osm", type: "raster", source: "osm" }],
      },
      center: [101.7, 0.5],
      zoom: 4,
    });
    mapRef.current.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current.addControl(
      new maplibregl.GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: true,
        showUserHeading: true,
        fitBoundsOptions: { maxZoom: 17 },
      }),
      "top-right",
    );
    mapRef.current.on("load", () => {
      mapRef.current?.resize();
      setMapReady(true);
    });
    requestAnimationFrame(() => mapRef.current?.resize());
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const treeVisibility = showTreePoints ? "visible" : "none";
    if (!map.getSource("trees")) {
      map.addSource("trees", { type: "geojson", data: trees });
      map.addLayer({
        id: "tree-points",
        type: "circle",
        source: "trees",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 4, 16, 9],
          "circle-color": [
            "match",
            ["get", "health_class"],
            "small_canopy",
            CANOPY_COLORS.small_canopy,
            "medium_canopy",
            CANOPY_COLORS.medium_canopy,
            "large_canopy",
            CANOPY_COLORS.large_canopy,
            "#2563eb",
          ],
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "#ffffff",
        },
        layout: { visibility: treeVisibility },
      });
      map.on("click", "tree-points", (event) => {
        const feature = event.features?.[0];
        if (!feature) return;
        const props = feature.properties || {};
        const coordinates = feature.geometry.coordinates.slice();
        new maplibregl.Popup()
          .setLngLat(coordinates)
          .setHTML(
            `<strong>${props.health_class}</strong><br/>Confidence: ${Number(props.confidence || 0).toFixed(2)}<br/>Diameter: ${props.equivalent_diameter_m || "-"} m`
          )
          .addTo(map);
      });
    } else {
      map.getSource("trees").setData(trees);
      if (map.getLayer("tree-points")) map.setLayoutProperty("tree-points", "visibility", treeVisibility);
    }
    if (showTreePoints && trees.features?.length) {
      const coordinates = trees.features.map((feature) => feature.geometry.coordinates);
      const bounds = coordinates.reduce(
        (bbox, coordinate) => bbox.extend(coordinate),
        new maplibregl.LngLatBounds(coordinates[0], coordinates[0])
      );
      map.resize();
      map.fitBounds(bounds, { padding: 80, maxZoom: 17, duration: 600 });
    }
  }, [trees, showTreePoints, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const visibility = showDetectionBoxes ? "visible" : "none";
    const paintColor = [
            "match",
            ["get", "health_class"],
      "small_canopy",
      CANOPY_COLORS.small_canopy,
      "medium_canopy",
      CANOPY_COLORS.medium_canopy,
      "large_canopy",
      CANOPY_COLORS.large_canopy,
      "#2563eb",
    ];
    if (!map.getSource("detections")) {
      map.addSource("detections", { type: "geojson", data: detections });
      map.addLayer(
        {
          id: "detection-box-fill",
          type: "fill",
          source: "detections",
          paint: {
            "fill-color": paintColor,
            "fill-opacity": 0.14,
          },
          layout: { visibility },
        },
        map.getLayer("tree-points") ? "tree-points" : undefined,
      );
      map.addLayer(
        {
          id: "detection-box-line",
          type: "line",
          source: "detections",
          paint: {
            "line-color": paintColor,
            "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1.5, 18, 3],
          },
          layout: { visibility },
        },
        map.getLayer("tree-points") ? "tree-points" : undefined,
      );
      const parseMaybeJson = (value) => {
        if (!value || typeof value !== "string") return value || {};
        try {
          return JSON.parse(value);
        } catch {
          return {};
        }
      };
      const formatSize = (props) => {
        const bbox = parseMaybeJson(props.bbox);
        const pixelSize = bbox?.w && bbox?.h ? `${Math.round(Number(bbox.w))} x ${Math.round(Number(bbox.h))} px` : "-";
        const area = Number(props.canopy_area_m2 || 0);
        return area > 0 ? `${area.toFixed(2)} m² (${pixelSize})` : pixelSize;
      };
      const showTooltip = (event) => {
        const feature = event.features?.[0];
        if (!feature) return;
        const props = feature.properties || {};
        if (!hoverPopupRef.current) {
          hoverPopupRef.current = new maplibregl.Popup({
            closeButton: false,
            closeOnClick: false,
            offset: 12,
          });
        }
        hoverPopupRef.current
          .setLngLat(event.lngLat)
          .setHTML(
            `<strong>${String(props.health_class || "").replaceAll("_", " ")}</strong><br/>Size: ${formatSize(props)}<br/>Confidence: ${Number(props.confidence || 0).toFixed(3)}`
          )
          .addTo(map);
      };
      ["detection-box-fill", "detection-box-line"].forEach((layerId) => {
        map.on("mousemove", layerId, showTooltip);
        map.on("mouseenter", layerId, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layerId, () => {
          map.getCanvas().style.cursor = "";
          hoverPopupRef.current?.remove();
        });
      });
    } else {
      map.getSource("detections").setData(detections);
      ["detection-box-fill", "detection-box-line"].forEach((layerId) => {
        if (map.getLayer(layerId)) map.setLayoutProperty(layerId, "visibility", visibility);
      });
    }
  }, [detections, showDetectionBoxes, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const fillColor = [
      "match",
      ["get", "dominant_health_class"],
      "small_canopy",
      "#eab308",
      "medium_canopy",
      "#16a34a",
      "large_canopy",
      "#2563eb",
      "#64748b",
    ];
    if (!map.getSource("area-polygons")) {
      map.addSource("area-polygons", { type: "geojson", data: areaPolygons });
      map.addLayer({
        id: "area-polygon-fill",
        type: "fill",
        source: "area-polygons",
        paint: {
          "fill-color": fillColor,
          "fill-opacity": 0.22,
        },
      });
      map.addLayer({
        id: "area-polygon-line",
        type: "line",
        source: "area-polygons",
        paint: {
          "line-color": fillColor,
          "line-width": 2.5,
        },
      });
      const showAreaPopup = (event) => {
        if (drawingAreaRef.current) return;
        const feature = event.features?.[0];
        if (!feature) return;
        const props = feature.properties || {};
        new maplibregl.Popup()
          .setLngLat(event.lngLat)
          .setHTML(
            `<strong>${props.name || "Area"}</strong><br/>Palms: ${props.tree_count || 0}<br/>Dominant: ${String(props.dominant_health_class || "-").replaceAll("_", " ")}<br/>Area: ${props.area_ha || 0} ha`
          )
          .addTo(map);
      };
      ["area-polygon-fill", "area-polygon-line"].forEach((layerId) => {
        map.on("click", layerId, showAreaPopup);
        map.on("mouseenter", layerId, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layerId, () => {
          map.getCanvas().style.cursor = drawingArea ? "crosshair" : "";
        });
      });
    } else {
      map.getSource("area-polygons").setData(areaPolygons);
    }
  }, [areaPolygons, drawingArea, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    if (!map.getSource("draft-area")) {
      map.addSource("draft-area", { type: "geojson", data: emptyFeatureCollection() });
      map.addLayer({
        id: "draft-area-line",
        type: "line",
        source: "draft-area",
        paint: {
          "line-color": "#dc2626",
          "line-width": 2,
          "line-dasharray": [2, 1],
        },
      });
      map.addLayer({
        id: "draft-area-points",
        type: "circle",
        source: "draft-area",
        paint: {
          "circle-radius": 5,
          "circle-color": "#dc2626",
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
        },
      });
    }
    const updateDraft = () => {
      map.getSource("draft-area")?.setData(draftFeatureCollection(draftAreaRef.current));
    };
    if (!drawingArea) {
      draftAreaRef.current = [];
      updateDraft();
      map.getCanvas().style.cursor = "";
      map.doubleClickZoom.enable();
      return undefined;
    }
    map.getCanvas().style.cursor = "crosshair";
    map.doubleClickZoom.disable();
    const addVertex = (event) => {
      draftAreaRef.current = [...draftAreaRef.current, [event.lngLat.lng, event.lngLat.lat]];
      updateDraft();
    };
    const finishPolygon = (event) => {
      event.preventDefault();
      const coords = draftAreaRef.current;
      if (coords.length < 3) return;
      const ring = [...coords, coords[0]];
      draftAreaRef.current = [];
      updateDraft();
      onDrawPolygon?.({ type: "Polygon", coordinates: [ring] });
    };
    map.on("click", addVertex);
    map.on("dblclick", finishPolygon);
    return () => {
      map.off("click", addVertex);
      map.off("dblclick", finishPolygon);
      map.getCanvas().style.cursor = "";
      map.doubleClickZoom.enable();
    };
  }, [drawingArea, mapReady, onDrawPolygon]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    for (const id of cogLayerIdsRef.current) {
      if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(id)) map.removeSource(id);
    }
    cogLayerIdsRef.current = [];
    const layers = cogLayers.length ? cogLayers : cogSource ? [{ id: "selected", source: cogSource, bounds: cogBounds }] : [];
    if (!layers.length) return;
    const beforeId = map.getLayer("detection-box-fill")
      ? "detection-box-fill"
      : map.getLayer("tree-points")
      ? "tree-points"
      : undefined;
    layers.forEach((layer, index) => {
      const layerId = `cog-raster-${layer.id || index}`;
      map.addSource(layerId, layer.source);
      map.addLayer(
        {
          id: layerId,
          type: "raster",
          source: layerId,
          paint: { "raster-opacity": layers.length > 1 ? 0.64 : 0.78 },
        },
        beforeId,
      );
      cogLayerIdsRef.current.push(layerId);
    });
  }, [cogSource, cogBounds, cogLayers, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const boundsList = cogBoundsList.length ? cogBoundsList : Array.isArray(cogBounds) ? [cogBounds] : [];
    if (!boundsList.length) return;
    const fitCog = () => {
      const validBounds = boundsList
        .map((bounds) => bounds.map(Number))
        .filter((bounds) => bounds.length === 4 && !bounds.some((value) => Number.isNaN(value)));
      if (!validBounds.length) return;
      const [west, south, east, north] = validBounds.reduce(
        (merged, bounds) => [
          Math.min(merged[0], bounds[0]),
          Math.min(merged[1], bounds[1]),
          Math.max(merged[2], bounds[2]),
          Math.max(merged[3], bounds[3]),
        ],
        validBounds[0],
      );
      map.resize();
      map.fitBounds(
        [
          [west, south],
          [east, north],
        ],
        { padding: 80, maxZoom: 20, duration: 800 }
      );
    };
    requestAnimationFrame(fitCog);
    const timer = setTimeout(fitCog, 250);
    return () => clearTimeout(timer);
  }, [cogBounds, cogBoundsList, zoomRequest, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !locateRequest) return;
    if (!navigator.geolocation) {
      onLocateError?.("This browser does not support geolocation.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lngLat = [position.coords.longitude, position.coords.latitude];
        if (!locationMarkerRef.current) {
          locationMarkerRef.current = new maplibregl.Marker({ color: "#2563eb" }).setLngLat(lngLat).addTo(map);
        } else {
          locationMarkerRef.current.setLngLat(lngLat);
        }
        map.resize();
        map.flyTo({ center: lngLat, zoom: 17, duration: 900, essential: true });
      },
      (error) => {
        onLocateError?.(error.message || "Unable to get current location.");
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    );
  }, [locateRequest, onLocateError]);

  return <div ref={containerRef} className="map-canvas" />;
}

function emptyFeatureCollection() {
  return { type: "FeatureCollection", features: [] };
}

function draftFeatureCollection(coordinates) {
  const features = coordinates.map((coordinate, index) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: coordinate },
    properties: { index },
  }));
  if (coordinates.length >= 2) {
    features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates },
      properties: { draft: true },
    });
  }
  return { type: "FeatureCollection", features };
}
