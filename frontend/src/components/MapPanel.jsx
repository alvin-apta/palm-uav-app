import * as React from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const { useEffect, useRef, useState } = React;
const HEALTH_COLORS = {
  healthy: "#16a34a",
  small_young: "#eab308",
  yellow_stressed: "#f97316",
  dead: "#dc2626",
};

export default function MapPanel({
  trees,
  detections = { type: "FeatureCollection", features: [] },
  showDetectionBoxes = true,
  showTreePoints = false,
  cogSource,
  cogBounds,
  cogLayers = [],
  cogBoundsList = [],
  zoomRequest = 0,
  locateRequest = 0,
  onLocateError,
}) {
  const mapRef = useRef(null);
  const containerRef = useRef(null);
  const locationMarkerRef = useRef(null);
  const hoverPopupRef = useRef(null);
  const cogLayerIdsRef = useRef([]);
  const [mapReady, setMapReady] = useState(false);

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
            "healthy",
            HEALTH_COLORS.healthy,
            "small_young",
            HEALTH_COLORS.small_young,
            "yellow_stressed",
            HEALTH_COLORS.yellow_stressed,
            "dead",
            HEALTH_COLORS.dead,
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
      "healthy",
      HEALTH_COLORS.healthy,
      "small_young",
      HEALTH_COLORS.small_young,
      "yellow_stressed",
      HEALTH_COLORS.yellow_stressed,
      "dead",
      HEALTH_COLORS.dead,
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
