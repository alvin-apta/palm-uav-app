import * as React from "react";
import { createRoot } from "react-dom/client";
import { apiBlob, apiFetch, apiUpload, login, publicAssetUrl } from "./api";
import MapPanel from "./components/MapPanel";
import "./styles.css";

const { useEffect, useMemo, useState } = React;
const NAV = ["Home", "Missions", "Upload Imagery", "Stitching", "Map", "Prescriptions", "Reports", "Admin"];
const HEALTH_OPTIONS = ["healthy", "small_young", "yellow_stressed", "dead"];
const ACTIVE_STITCH_STATUSES = new Set(["queued", "running"]);
const PHOTO_FILE_EXTENSIONS = new Set([".jpg", ".jpeg", ".png", ".tif", ".tiff"]);
const QUICK_STITCH_DEFAULTS = {
  mode: "quick",
  resize_max_px: 1800,
  max_concurrency: 2,
  feature_quality: "medium",
  orthophoto_resolution: 16,
  split_batch_size: 0,
  split_overlap: 0,
  fast_orthophoto: true,
  skip_3dmodel: true,
  minimal_outputs: true,
};
const FINAL_STITCH_DEFAULTS = {
  ...QUICK_STITCH_DEFAULTS,
  mode: "final",
  resize_max_px: 3072,
  feature_quality: "high",
  orthophoto_resolution: 10,
  fast_orthophoto: false,
};

function photoFilePath(file) {
  return file.webkitRelativePath || file.relativePath || file.name;
}

function isSupportedPhotoFile(file) {
  const name = photoFilePath(file).toLowerCase();
  const dotIndex = name.lastIndexOf(".");
  return dotIndex >= 0 && PHOTO_FILE_EXTENSIONS.has(name.slice(dotIndex));
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value >= 1024 * 1024 * 1024) return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  if (value >= 1024) return `${Math.round(value / 1024)} KB`;
  return `${value} B`;
}

function mergePhotoFiles(existing, incoming) {
  const merged = [...existing];
  const keys = new Set(existing.map((file) => `${photoFilePath(file)}:${file.size}:${file.lastModified}`));
  for (const file of incoming) {
    if (!isSupportedPhotoFile(file)) continue;
    const key = `${photoFilePath(file)}:${file.size}:${file.lastModified}`;
    if (keys.has(key)) continue;
    keys.add(key);
    merged.push(file);
  }
  return merged;
}

function fileFromEntry(entry) {
  return new Promise((resolve, reject) => {
    entry.file(
      (file) => {
        try {
          Object.defineProperty(file, "relativePath", { value: entry.fullPath.replace(/^\//, ""), configurable: true });
        } catch {
          file.relativePath = entry.fullPath.replace(/^\//, "");
        }
        resolve(file);
      },
      reject,
    );
  });
}

function readDirectoryEntries(reader) {
  return new Promise((resolve, reject) => {
    const entries = [];
    function readBatch() {
      reader.readEntries(
        (batch) => {
          if (!batch.length) {
            resolve(entries);
            return;
          }
          entries.push(...batch);
          readBatch();
        },
        reject,
      );
    }
    readBatch();
  });
}

async function filesFromEntry(entry) {
  if (entry.isFile) return [await fileFromEntry(entry)];
  if (!entry.isDirectory) return [];
  const entries = await readDirectoryEntries(entry.createReader());
  const nested = await Promise.all(entries.map(filesFromEntry));
  return nested.flat();
}

async function filesFromDrop(dataTransfer) {
  const itemEntries = [...(dataTransfer.items || [])]
    .map((item) => item.webkitGetAsEntry?.())
    .filter(Boolean);
  if (itemEntries.length) {
    const nested = await Promise.all(itemEntries.map(filesFromEntry));
    return nested.flat();
  }
  return [...(dataTransfer.files || [])];
}

function humanize(value) {
  return String(value || "-").replaceAll("_", " ");
}

function normalizeRasterSource(source) {
  if (!source?.tiles) return source;
  return { ...source, tiles: source.tiles.map(publicAssetUrl) };
}

function stitchJobProgress(job) {
  if (!job) return 0;
  if (job.status === "complete") return 100;
  if (job.status === "failed") return Number(job.summary_json?.nodeodm_progress ?? 100);
  if (job.status === "running") return Number(job.summary_json?.nodeodm_progress ?? 10);
  return Number(job.summary_json?.nodeodm_progress ?? 0);
}

function stitchJobStage(job) {
  if (!job) return "Idle";
  if (job.status === "complete") return "Complete";
  if (job.status === "failed") return humanize(job.error_code || job.summary_json?.nodeodm_stage || "failed");
  if (job.status === "queued") return "Queued";
  return humanize(job.summary_json?.nodeodm_stage || "starting");
}

function stitchJobDetail(job) {
  if (!job) return "No stitch job started";
  if (job.status === "running") {
    const taskId = job.summary_json?.nodeodm_task_uuid?.slice(0, 8);
    const elapsed = formatDuration(elapsedJobSeconds(job));
    return taskId ? `NodeODM task ${taskId} | elapsed ${elapsed}` : `Waiting for NodeODM task | elapsed ${elapsed}`;
  }
  if (job.status === "failed") return job.summary_json?.friendly_error || job.error_message || job.error_code || "Processing failed";
  if (job.status === "complete") return `Preview is available | elapsed ${formatDuration(elapsedJobSeconds(job))}`;
  return `${job.asset_ids_json?.length || 0} photos waiting`;
}

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds || 0));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = Math.floor(value % 60);
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

function elapsedJobSeconds(job, now = Date.now()) {
  if (!job) return 0;
  const startTime = Date.parse(job.started_at || job.created_at || "");
  const endTime = job.completed_at ? Date.parse(job.completed_at) : now;
  if (Number.isNaN(startTime) || Number.isNaN(endTime)) return job.summary_json?.elapsed_seconds || 0;
  return Math.max(0, Math.round((endTime - startTime) / 1000));
}

function stitchJobBatchLabel(job) {
  const batchTotal = Number(job?.summary_json?.batch_total || job?.options_json?.batch_total || 0);
  if (batchTotal <= 1) return "";
  const batchIndex = Number(job?.summary_json?.batch_index || job?.options_json?.batch_index || 1);
  return `Batch ${batchIndex} of ${batchTotal}`;
}

function stitchJobEstimate(job) {
  const seconds = Number(job?.summary_json?.estimated_seconds || 0);
  return seconds ? formatDuration(seconds) : "-";
}

function queuedJobSeconds(job) {
  const created = Date.parse(job?.created_at || "");
  const started = Date.parse(job?.started_at || "");
  if (Number.isNaN(created) || Number.isNaN(started)) return 0;
  return Math.max(0, Math.round((started - created) / 1000));
}

function totalJobSeconds(job, now = Date.now()) {
  const created = Date.parse(job?.created_at || "");
  const ended = job?.completed_at ? Date.parse(job.completed_at) : now;
  if (Number.isNaN(created) || Number.isNaN(ended)) return elapsedJobSeconds(job, now);
  return Math.max(0, Math.round((ended - created) / 1000));
}

function formatMetric(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "-";
  return `${value}${suffix}`;
}

function cogLabel(asset) {
  if (asset?.batch_total > 1) return `Batch ${asset.batch_index}/${asset.batch_total}`;
  return asset?.original_filename || "Orthomosaic";
}

function inferenceJobProgress(job) {
  if (!job) return 0;
  if (job.status === "complete" || job.status === "failed") return 100;
  if (job.status === "running") return Number(job.summary_json?.progress ?? 10);
  return Number(job.summary_json?.progress ?? 0);
}

function inferenceJobDetail(job) {
  if (!job) return "Run after at least one stitched orthomosaic is complete.";
  if (job.status === "failed") return job.summary_json?.friendly_error || job.error_message || job.error_code || "AI inference failed.";
  if (job.status === "complete") return `${job.summary_json?.unique_trees ?? 0} palms mapped from ${job.summary_json?.assets ?? job.summary_json?.cog_assets ?? 0} stitched layer(s).`;
  if (job.status === "running") {
    const processed = job.summary_json?.processed_assets ?? 0;
    const total = job.summary_json?.total_assets ?? job.summary_json?.cog_assets ?? 0;
    const tile = job.summary_json?.current_tile;
    const tiles = job.summary_json?.total_tiles;
    return tile && tiles ? `Processing map ${processed + 1}/${total}, tile ${tile}/${tiles}` : `Processing ${processed}/${total} stitched layer(s)`;
  }
  return `${job.summary_json?.cog_assets ?? job.summary_json?.assets ?? 0} stitched layer(s) queued`;
}

function CollapseCard({ title, meta, open, onToggle, children, className = "" }) {
  return (
    <section className={`collapsible-card ${className} ${open ? "" : "is-collapsed"}`}>
      <button className="collapse-head" type="button" onClick={onToggle} aria-expanded={open}>
        <span>{title}</span>
        {meta !== undefined && meta !== null && meta !== "" && <strong>{meta}</strong>}
        <i>{open ? "Hide" : "Show"}</i>
      </button>
      {open && <div className="collapse-body">{children}</div>}
    </section>
  );
}

function App() {
  const [token, setToken] = useState(localStorage.getItem("palmops-token") || "");
  const [user, setUser] = useState(null);
  const [active, setActive] = useState("Home");
  const [message, setMessage] = useState("");
  const [blocks, setBlocks] = useState([]);
  const [missions, setMissions] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [orthomosaicJobs, setOrthomosaicJobs] = useState([]);
  const [trees, setTrees] = useState({ type: "FeatureCollection", features: [] });
  const [detections, setDetections] = useState({ type: "FeatureCollection", features: [] });
  const [cogs, setCogs] = useState([]);
  const [cogSource, setCogSource] = useState(null);
  const [cogBounds, setCogBounds] = useState(null);
  const [cogLayers, setCogLayers] = useState([]);
  const [cogBoundsList, setCogBoundsList] = useState([]);
  const [selectedCogIds, setSelectedCogIds] = useState(["all"]);
  const [showDetectionBoxes, setShowDetectionBoxes] = useState(true);
  const [selectedDetectionClasses, setSelectedDetectionClasses] = useState(HEALTH_OPTIONS);
  const [mapZoomRequest, setMapZoomRequest] = useState(0);
  const [locateRequest, setLocateRequest] = useState(0);
  const [selectedBlock, setSelectedBlock] = useState("");
  const [summary, setSummary] = useState(null);
  const [stitchQuality, setStitchQuality] = useState(null);
  const [stitchPreview, setStitchPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [stitchPreviewCollapsed, setStitchPreviewCollapsed] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [selectedPhotoFiles, setSelectedPhotoFiles] = useState([]);
  const [photoDropActive, setPhotoDropActive] = useState(false);
  const [stitchSubmitting, setStitchSubmitting] = useState(false);
  const [stitchRefreshing, setStitchRefreshing] = useState(false);
  const [qualityRefreshing, setQualityRefreshing] = useState(false);
  const [cogRegistering, setCogRegistering] = useState(false);
  const [inferenceSubmitting, setInferenceSubmitting] = useState(false);
  const [modelStatus, setModelStatus] = useState(null);
  const [mapLoading, setMapLoading] = useState(false);
  const [mapSections, setMapSections] = useState({
    overlays: false,
    detections: false,
    actions: false,
    inference: false,
    analytics: false,
  });
  const [nowTick, setNowTick] = useState(Date.now());
  const [stitchSettings, setStitchSettings] = useState(QUICK_STITCH_DEFAULTS);
  const [loginForm, setLoginForm] = useState({ email: "owner@example.com", password: "palmops123" });

  const currentBlockId = selectedBlock || blocks[0]?.id || "";
  const treeCount = trees.features?.length || 0;
  const unhealthyCount = trees.features?.filter((feature) => ["yellow_stressed", "dead"].includes(feature.properties?.health_class)).length || 0;
  const blockOrthomosaicJobs = orthomosaicJobs.filter((job) => job.block_id === currentBlockId);
  const latestBlockStitchJob = blockOrthomosaicJobs[0] || null;
  const hasActiveStitchJob = blockOrthomosaicJobs.some((job) => ACTIVE_STITCH_STATUSES.has(job.status));
  const latestStitchedMap =
    orthomosaicJobs.find((job) => job.block_id === currentBlockId && job.status === "complete" && job.output_asset_id) ||
    orthomosaicJobs.find((job) => job.status === "complete" && job.output_asset_id);
  const currentBlockInferenceJobs = jobs.filter((job) => job.block_id === currentBlockId);
  const latestInferenceJob = currentBlockInferenceJobs[0] || null;
  const selectedPhotoTotalBytes = selectedPhotoFiles.reduce((total, file) => total + file.size, 0);
  const selectedCogAssetIds = useMemo(() => {
    if (!cogs.length) return [];
    if (selectedCogIds.includes("all")) return cogs.map((asset) => asset.id);
    return selectedCogIds.filter((id) => cogs.some((asset) => asset.id === id));
  }, [cogs, selectedCogIds]);
  const overlayFilteredDetections = useMemo(
    () => ({
      ...detections,
      features: (detections.features || []).filter((feature) => selectedCogAssetIds.includes(feature.properties?.asset_id)),
    }),
    [detections, selectedCogAssetIds]
  );
  const detectionClassTotals = useMemo(
    () =>
      HEALTH_OPTIONS.reduce((totals, className) => {
        totals[className] = (overlayFilteredDetections.features || []).filter(
          (feature) => feature.properties?.health_class === className
        ).length;
        return totals;
      }, {}),
    [overlayFilteredDetections]
  );
  const filteredDetections = useMemo(
    () => ({
      ...overlayFilteredDetections,
      features: (overlayFilteredDetections.features || []).filter((feature) =>
        selectedDetectionClasses.includes(feature.properties?.health_class)
      ),
    }),
    [overlayFilteredDetections, selectedDetectionClasses]
  );
  const detectionCount = filteredDetections.features?.length || 0;
  const inferenceButtonLabel = inferenceSubmitting ? "Starting..." : latestInferenceJob ? "Run Again" : "Run Inference";

  async function refreshAll(nextToken = token) {
    if (!nextToken) return;
    const [me, blockRows, missionRows, jobRows, stitchRows, model] = await Promise.all([
      apiFetch("/auth/me", nextToken),
      apiFetch("/blocks", nextToken),
      apiFetch("/missions", nextToken),
      apiFetch("/inference/jobs", nextToken),
      apiFetch("/orthomosaics/jobs", nextToken),
      apiFetch("/inference/jobs/model/status", nextToken),
    ]);
    setUser(me);
    setBlocks(blockRows);
    setMissions(missionRows);
    setJobs(jobRows);
    setOrthomosaicJobs(stitchRows);
    setModelStatus(model);
    if (!selectedBlock && blockRows[0]) setSelectedBlock(blockRows[0].id);
  }

  async function loadMapData(blockId = currentBlockId) {
    if (!blockId || !token) return;
    const query = new URLSearchParams({ block_id: blockId });
    if (latestInferenceJob?.block_id === blockId) query.set("job_id", latestInferenceJob.id);
    const [treeGeojson, detectionGeojson, cogRows] = await Promise.all([
      apiFetch(`/map/trees.geojson?${query}`, token),
      apiFetch(`/map/detections.geojson?${query}`, token),
      apiFetch(`/map/cogs?block_id=${blockId}`, token),
    ]);
    setTrees(treeGeojson);
    setDetections(detectionGeojson);
    setCogs(cogRows);
    if (cogRows.length) {
      const validIds = selectedCogIds.filter((id) => id === "all" || cogRows.some((asset) => asset.id === id));
      const nextIds = selectedCogIds.length === 0 ? [cogRows[0].id] : validIds.length ? validIds : [cogRows[0].id];
      await loadCogSelection(nextIds, cogRows);
    } else {
      setSelectedCogIds([]);
      setCogSource(null);
      setCogBounds(null);
      setCogLayers([]);
      setCogBoundsList([]);
    }
    return { treeGeojson, cogRows };
  }

  async function loadSummary(blockId = currentBlockId) {
    if (!blockId || !token) return;
    setSummary(await apiFetch(`/analytics/block/${blockId}/summary`, token));
  }

  async function loadStitchQuality(blockId = currentBlockId) {
    if (!blockId || !token) return;
    setStitchQuality(await apiFetch(`/orthomosaics/quality?block_id=${blockId}`, token));
  }

  useEffect(() => {
    refreshAll().catch((error) => setMessage(error.message));
  }, []);

  useEffect(() => {
    if (currentBlockId && token) {
      loadMapData(currentBlockId).catch((error) => setMessage(error.message));
      loadSummary(currentBlockId).catch(() => setSummary(null));
      loadStitchQuality(currentBlockId).catch(() => setStitchQuality(null));
    }
  }, [currentBlockId, token, latestInferenceJob?.id]);

  useEffect(() => {
    if (active !== "Map" || !latestStitchedMap || currentBlockId === latestStitchedMap.block_id) return;
    if (treeCount || cogs.length) return;
    openStitchJobOnMap(latestStitchedMap).catch((error) => setMessage(error.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, latestStitchedMap?.id, currentBlockId, treeCount, cogs.length]);

  useEffect(() => {
    if (stitchPreview && stitchPreview.block_id !== currentBlockId) {
      setStitchPreview(null);
      setStitchPreviewCollapsed(false);
    }
  }, [currentBlockId, stitchPreview]);

  useEffect(() => {
    if (!token || active !== "Stitching" || !hasActiveStitchJob) return undefined;
    const timer = setInterval(() => {
      refreshAll().catch((error) => setMessage(error.message));
    }, 3000);
    return () => clearInterval(timer);
  }, [active, hasActiveStitchJob, token]);

  useEffect(() => {
    if (!token || active !== "Map" || !latestInferenceJob || !ACTIVE_STITCH_STATUSES.has(latestInferenceJob.status)) return undefined;
    const timer = setInterval(() => {
      refreshAll().catch((error) => setMessage(error.message));
      loadMapData(currentBlockId).catch(() => {});
      loadSummary().catch(() => setSummary(null));
    }, 3000);
    return () => clearInterval(timer);
  }, [active, latestInferenceJob?.id, latestInferenceJob?.status, token, currentBlockId]);

  useEffect(() => {
    if (active !== "Stitching") return undefined;
    const timer = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);

  async function handleLogin(event) {
    event.preventDefault();
    try {
      const payload = await login(loginForm.email, loginForm.password);
      localStorage.setItem("palmops-token", payload.access_token);
      setToken(payload.access_token);
      setMessage("Signed in");
      await refreshAll(payload.access_token);
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function createBlock(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      estate_name: form.get("estate_name"),
      name: form.get("name"),
      planting_year: Number(form.get("planting_year") || 0) || null,
      palm_spacing_m: Number(form.get("palm_spacing_m") || 0) || null,
      target_palms_ha: Number(form.get("target_palms_ha") || 0) || null,
    };
    const block = await apiFetch("/blocks", token, { method: "POST", body: JSON.stringify(payload) });
    setSelectedBlock(block.id);
    await refreshAll();
    setMessage("Block created");
  }

  async function createMission(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(form.entries());
    payload.block_id = currentBlockId;
    await apiFetch("/missions", token, { method: "POST", body: JSON.stringify(payload) });
    await refreshAll();
    setMessage("Mission saved");
  }

  function addPhotoFiles(files) {
    const supported = [...files].filter(isSupportedPhotoFile);
    setSelectedPhotoFiles((current) => mergePhotoFiles(current, supported));
    if (!supported.length) {
      setMessage("Choose JPG, PNG, TIFF, or GeoTIFF photos");
      return;
    }
    setMessage(`${supported.length} image file${supported.length === 1 ? "" : "s"} ready to upload`);
  }

  function handlePhotoInputChange(event) {
    addPhotoFiles(event.target.files || []);
    event.target.value = "";
  }

  async function handlePhotoDrop(event) {
    event.preventDefault();
    setPhotoDropActive(false);
    try {
      const files = await filesFromDrop(event.dataTransfer);
      addPhotoFiles(files);
    } catch (error) {
      setMessage(`Could not read dropped files: ${error.message}`);
    }
  }

  async function uploadPhotos(event) {
    event.preventDefault();
    const formElement = event.currentTarget;
    if (!currentBlockId) {
      setMessage("Create a block before uploading imagery");
      return;
    }
    const form = new FormData(formElement);
    if (!selectedPhotoFiles.length) {
      setMessage("Choose one or more image files before uploading");
      return;
    }
    form.delete("files");
    selectedPhotoFiles.forEach((file) => {
      form.append("files", file, photoFilePath(file));
    });
    if (!form.get("sensor_width_mm")) form.delete("sensor_width_mm");
    if (!form.get("focal_length_mm")) form.delete("focal_length_mm");
    form.set("block_id", currentBlockId);
    setIsUploading(true);
    setUploadProgress(0);
    setMessage("Uploading photos...");
    try {
      const result = await apiUpload("/imagery/upload/photos", token, form, (progress) => {
        setUploadProgress(progress);
        if (progress >= 100) setMessage("Upload complete. Reading EXIF metadata...");
      });
      setMessage(`${result.length} photos uploaded`);
      formElement.reset();
      setSelectedPhotoFiles([]);
      await loadStitchQuality();
      await loadMapData();
      setMessage(`${result.length} photos uploaded. Create a stitch job first; AI inference runs on the stitched orthomosaic.`);
    } catch (error) {
      setMessage(`Upload failed: ${error.message}`);
    } finally {
      setIsUploading(false);
    }
  }

  async function registerCog(event) {
    event.preventDefault();
    const formElement = event.currentTarget;
    if (!currentBlockId) {
      setMessage("Create a block before registering a COG");
      return;
    }
    const form = new FormData(formElement);
    form.set("block_id", currentBlockId);
    setCogRegistering(true);
    setMessage("Registering map raster...");
    try {
      const result = await apiFetch("/imagery/upload/cog", token, { method: "POST", body: form });
      setMessage(`COG registered: ${result.original_filename}`);
      formElement.reset();
      await loadMapData();
    } catch (error) {
      setMessage(`COG registration failed: ${error.message}`);
    } finally {
      setCogRegistering(false);
    }
  }

  async function createJob({ automatic = false } = {}) {
    if (modelStatus && !modelStatus.configured) {
      setMessage(modelStatus.message || "Palm tree detection model is not configured.");
      return null;
    }
    const selectedCogs = selectedCogIds.includes("all") ? cogs : cogs.filter((asset) => selectedCogIds.includes(asset.id));
    const assetIds = selectedCogs.map((asset) => asset.id);
    if (!assetIds.length && latestStitchedMap?.output_asset_id && latestStitchedMap.block_id === currentBlockId) {
      assetIds.push(latestStitchedMap.output_asset_id);
    }
    if (!assetIds.length) {
      setMessage("No stitched orthomosaic is ready for this block. Create a stitch job first, then run inference.");
      return null;
    }
    setInferenceSubmitting(true);
    setMessage(automatic ? "Starting AI palm inference on stitched map..." : "Creating inference job from selected stitched map layer(s)...");
    try {
      const job = await apiFetch("/inference/jobs", token, {
        method: "POST",
        body: JSON.stringify({ block_id: currentBlockId, asset_ids: assetIds }),
      });
      await refreshAll();
      setMessage(`Inference job ${job.status}: ${assetIds.length} stitched layer(s) queued`);
      return job;
    } catch (error) {
      setMessage(`Inference job failed: ${error.message}`);
      throw error;
    } finally {
      setInferenceSubmitting(false);
    }
  }

  function updateStitchSetting(key, value) {
    setStitchSettings((settings) => ({ ...settings, [key]: value }));
  }

  function updateStitchMode(mode) {
    setStitchSettings((settings) => {
      if (mode === "quick") {
        return {
          ...settings,
          ...QUICK_STITCH_DEFAULTS,
        };
      }
      if (mode === "final") {
        return {
          ...settings,
          ...FINAL_STITCH_DEFAULTS,
        };
      }
      if (mode === "partial") {
        return {
          ...settings,
          mode,
          resize_max_px: 2400,
          max_concurrency: 1,
          feature_quality: "medium",
          orthophoto_resolution: 12,
          split_batch_size: 60,
          split_overlap: 20,
          fast_orthophoto: false,
          skip_3dmodel: true,
          minimal_outputs: true,
        };
      }
      if (mode === "ultra_low") {
        return {
          ...settings,
          mode,
          resize_max_px: 1600,
          max_concurrency: 1,
          feature_quality: "low",
          orthophoto_resolution: 16,
          split_batch_size: 15,
          split_overlap: 4,
          fast_orthophoto: true,
          skip_3dmodel: true,
          minimal_outputs: true,
        };
      }
      return { ...settings, mode };
    });
  }

  function buildStitchOptions() {
    const options = {
      output: "orthomosaic_geotiff",
      low_memory_preset: stitchSettings.mode !== "final",
      cog: true,
      "max-concurrency": Number(stitchSettings.max_concurrency || 2),
      "feature-quality": stitchSettings.feature_quality,
      "orthophoto-resolution": Number(stitchSettings.orthophoto_resolution || 12),
      "fast-orthophoto": Boolean(stitchSettings.fast_orthophoto),
      "skip-3dmodel": Boolean(stitchSettings.skip_3dmodel),
      "skip-report": true,
    };
    if (Number(stitchSettings.resize_max_px || 0) > 0) {
      options.resize_max_px = Number(stitchSettings.resize_max_px);
    }
    if (stitchSettings.minimal_outputs) {
      options.gltf = false;
      options["pc-ept"] = false;
      options["3d-tiles"] = false;
      options.dsm = false;
      options.dtm = false;
    }
    if (Number(stitchSettings.split_batch_size || 0) > 0) {
      options.split_batch_size = Number(stitchSettings.split_batch_size);
      options.split_overlap = Number(stitchSettings.split_overlap || 0);
    }
    return options;
  }

  async function createOrthomosaicJob() {
    if (!currentBlockId) {
      setMessage("Create a block before stitching imagery");
      return;
    }
    setStitchSubmitting(true);
    setMessage("Creating stitch job...");
    try {
      const options = buildStitchOptions();
      const job = await apiFetch("/orthomosaics/jobs", token, {
        method: "POST",
        body: JSON.stringify({ block_id: currentBlockId, engine: "nodeodm", options }),
      });
      await refreshAll();
      await loadStitchQuality();
      const batchTotal = job.summary_json?.batch_total || 1;
      setMessage(batchTotal > 1 ? `Created ${batchTotal} partial stitch jobs` : `Stitch job ${job.status}: ${job.id}`);
    } catch (error) {
      setMessage(`Stitch job failed: ${error.message}`);
    } finally {
      setStitchSubmitting(false);
    }
  }

  async function refreshStitchQuality() {
    setQualityRefreshing(true);
    setMessage("Refreshing metadata check...");
    try {
      await loadStitchQuality();
      setMessage("Metadata check refreshed");
    } catch (error) {
      setMessage(`Metadata check failed: ${error.message}`);
    } finally {
      setQualityRefreshing(false);
    }
  }

  async function refreshStitchJobs() {
    setStitchRefreshing(true);
    setMessage("Refreshing stitch jobs...");
    try {
      await refreshAll();
      setMessage("Stitch jobs refreshed");
    } catch (error) {
      setMessage(`Refresh failed: ${error.message}`);
    } finally {
      setStitchRefreshing(false);
    }
  }

  async function cancelStitchJob(job) {
    const wholeRun = Number(job.summary_json?.batch_total || job.options_json?.batch_total || 0) > 1;
    setMessage(wholeRun ? "Stopping stitch run..." : "Stopping stitch job...");
    try {
      const query = wholeRun ? "?batch=true" : "";
      const result = await apiFetch(`/orthomosaics/jobs/${job.id}/cancel${query}`, token, { method: "POST" });
      await refreshAll();
      setMessage(result.cancelled ? `Stopped ${result.cancelled} stitch job${result.cancelled === 1 ? "" : "s"}` : "No running stitch jobs to stop");
    } catch (error) {
      setMessage(`Stop failed: ${error.message}`);
    }
  }

  async function removeStitchJob(job) {
    const wholeRun = Number(job.summary_json?.batch_total || job.options_json?.batch_total || 0) > 1;
    const label = wholeRun ? "remove this whole stitch run" : "remove this stitch job";
    if (!window.confirm(`Are you sure you want to ${label}? Completed map layers are kept.`)) return;
    setMessage(wholeRun ? "Removing stitch run..." : "Removing stitch job...");
    try {
      const query = wholeRun ? "?batch=true" : "";
      const result = await apiFetch(`/orthomosaics/jobs/${job.id}${query}`, token, { method: "DELETE" });
      await refreshAll();
      setMessage(`Removed ${result.deleted} stitch job${result.deleted === 1 ? "" : "s"}`);
    } catch (error) {
      setMessage(`Remove failed: ${error.message}`);
    }
  }

  async function toggleCog(assetId, checked) {
    let nextIds = selectedCogIds;
    if (assetId === "all") {
      nextIds = checked ? ["all"] : [];
    } else {
      const withoutAll = selectedCogIds.filter((id) => id !== "all");
      nextIds = checked ? [...new Set([...withoutAll, assetId])] : withoutAll.filter((id) => id !== assetId);
    }
    await loadCogSelection(nextIds);
  }

  function toggleDetectionClass(className, checked) {
    setSelectedDetectionClasses((classes) => {
      if (checked) return [...new Set([...classes, className])];
      return classes.filter((item) => item !== className);
    });
  }

  function toggleMapSection(section) {
    setMapSections((sections) => ({ ...sections, [section]: !sections[section] }));
  }

  function setAllMapSections(open) {
    setMapSections((sections) =>
      Object.keys(sections).reduce((nextSections, section) => {
        nextSections[section] = open;
        return nextSections;
      }, {})
    );
  }

  async function loadCogSelection(selection, availableCogs = cogs) {
    const selectionIds = Array.isArray(selection) ? selection : selection ? [selection] : [];
    setSelectedCogIds(selectionIds);
    if (!selectionIds.length) {
      setCogSource(null);
      setCogBounds(null);
      setCogLayers([]);
      setCogBoundsList([]);
      return;
    }
    const targetCogs = selectionIds.includes("all") ? availableCogs : availableCogs.filter((asset) => selectionIds.includes(asset.id));
    const payloads = await Promise.all(
      targetCogs.map(async (asset) => {
        const payload = await apiFetch(`/map/cogs/${asset.id}/tilejson`, token);
        return { ...asset, ...payload };
      })
    );
    const layers = payloads
      .filter((payload) => payload.source)
      .map((payload) => ({
        id: payload.asset_id || payload.id,
        label: cogLabel(payload),
        source: normalizeRasterSource(payload.source),
        bounds: payload.bounds || null,
      }));
    setCogLayers(layers);
    setCogBoundsList(layers.map((layer) => layer.bounds).filter(Boolean));
    setCogSource(layers[0]?.source || null);
    setCogBounds(layers[0]?.bounds || null);
  }

  async function openStitchJobOnMap(job) {
    setMapLoading(true);
    setMessage("Loading stitched raster on the map...");
    try {
      setSelectedBlock(job.block_id);
      setActive("Map");
      const mapData = await loadMapData(job.block_id);
      if (job.output_asset_id) await loadCogSelection([job.output_asset_id], mapData?.cogRows || []);
      setMapZoomRequest((value) => value + 1);
      setMessage("Map layer loaded");
    } finally {
      setMapLoading(false);
    }
  }

  async function refreshMapData() {
    setMapLoading(true);
    setMessage("Refreshing map layers...");
    try {
      await loadMapData();
      setMessage("Map layers refreshed");
    } catch (error) {
      setMessage(`Map refresh failed: ${error.message}`);
    } finally {
      setMapLoading(false);
    }
  }

  async function zoomToSelectedArea() {
    setMessage("Zooming to selected area...");
    if (cogBounds) {
      setMapZoomRequest((value) => value + 1);
      return;
    }
    const nextCogIds = selectedCogIds.length ? selectedCogIds : ["all"];
    if (nextCogIds.length) {
      await loadCogSelection(nextCogIds);
      setMapZoomRequest((value) => value + 1);
      return;
    }
    if (latestStitchedMap) {
      await openStitchJobOnMap(latestStitchedMap);
      return;
    }
    setMessage("No stitched orthomosaic found yet. Create a stitch job first, then open it on the map.");
  }

  function locateUser() {
    setMessage("Requesting browser location permission...");
    setLocateRequest((value) => value + 1);
  }

  async function loadStitchPreview(job) {
    setPreviewLoading(true);
    setStitchPreview(null);
    setStitchPreviewCollapsed(false);
    setMessage("Loading stitch preview...");
    try {
      if (job.block_id !== currentBlockId) setSelectedBlock(job.block_id);
      const preview = await apiFetch(`/orthomosaics/jobs/${job.id}/preview`, token);
      setStitchPreview(preview);
      setMessage(`Preview loaded: distortion risk ${preview.diagnostics?.risk_level || "unknown"}`);
    } catch (error) {
      setMessage(`Preview failed: ${error.message}`);
    } finally {
      setPreviewLoading(false);
    }
  }

  async function downloadPrescription() {
    const blob = await apiBlob(`/exports/prescription?block_id=${currentBlockId}`, token, { method: "POST" });
    downloadBlob(blob, `prescription-${currentBlockId}.zip`);
  }

  async function downloadMissionKmz(missionId) {
    const blob = await apiBlob(`/exports/kmz/mission?mission_id=${missionId}`, token, { method: "POST" });
    downloadBlob(blob, `mission-${missionId}.kmz`);
  }

  const dashboardCards = useMemo(
    () => [
      ["Blocks", blocks.length],
      ["Trees on map", treeCount],
      ["Unhealthy", unhealthyCount],
      ["Jobs", jobs.length + orthomosaicJobs.length],
    ],
    [blocks.length, treeCount, unhealthyCount, jobs.length, orthomosaicJobs.length]
  );
  const mapAnalyticsCards = useMemo(
    () => [
      ["Palms", summary?.population_count ?? treeCount],
      ["Unhealthy", summary?.unhealthy_count ?? unhealthyCount],
      ["Dead", summary?.dead_count ?? 0],
      ["Young", summary?.young_count ?? 0],
      ["GPS", formatMetric(summary?.imagery?.gps_coverage_pct, "%")],
      ["Layers", summary?.imagery?.map_layers ?? cogs.length],
      ["Boxes", detectionCount],
      ["Stitch", `${summary?.stitching?.latest_run_complete ?? 0}/${summary?.stitching?.latest_run_total ?? 0}`],
      ["Run time", summary?.stitching?.latest_run_elapsed_seconds ? formatDuration(summary.stitching.latest_run_elapsed_seconds) : "-"],
      ["AI", humanize(summary?.inference?.latest_status || "not_started")],
      ["FFB kg", formatMetric(summary?.estimated_total_ffb_kg)],
    ],
    [summary, treeCount, unhealthyCount, cogs.length, detectionCount]
  );

  if (!token || !user) {
    return (
      <main className="login-screen">
        <form className="login-card" onSubmit={handleLogin}>
          <img className="login-logo" src="/palmops-icon.png" alt="" />
          <span className="eyebrow">PalmOps Web-GIS</span>
          <h1>Sign in to monitor plantation health.</h1>
          <label>Email<input value={loginForm.email} onChange={(event) => setLoginForm({ ...loginForm, email: event.target.value })} /></label>
          <label>Password<input type="password" value={loginForm.password} onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })} /></label>
          <button type="submit">Sign In</button>
          {message && <p className="message">{message}</p>}
        </form>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><img className="brand-icon" src="/palmops-icon.png" alt="" /><div><strong>PalmOps</strong><small>Web-GIS</small></div></div>
        <nav>{NAV.map((item) => <button key={item} className={active === item ? "active" : ""} onClick={() => setActive(item)}>{item}</button>)}</nav>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div>
            <h1>{active}</h1>
            <p>{user.email} | {user.role}</p>
          </div>
          <select value={currentBlockId} onChange={(event) => setSelectedBlock(event.target.value)}>
            {blocks.map((block) => <option value={block.id} key={block.id}>{block.name}</option>)}
          </select>
        </header>
        {message && <div className="notice">{message}</div>}

        {active === "Home" && (
          <section className="home-grid">
            <div className="hero">
              <span className="eyebrow">Drone to field action</span>
              <h2>Count palms, classify health, stream maps, and export prescription files.</h2>
              <p>Follow the workflow from mission setup to imagery upload, queued AI inference, map review, analytics, and VRT-ready exports.</p>
              <div className="button-row"><button onClick={() => setActive("Missions")}>Start Mission</button><button onClick={() => setActive("Upload Imagery")}>Upload Photos</button></div>
              <img className="hero-logo" src="/palmops-home-logo.png" alt="" />
            </div>
            <div className="metric-grid">{dashboardCards.map(([label, value]) => <article className="metric-card" key={label}><span>{label}</span><strong>{value}</strong></article>)}</div>
          </section>
        )}

        {active === "Missions" && (
          <section className="two-col">
            <form className="panel form-grid" onSubmit={createBlock}>
              <h2>Create Block</h2>
              <label>Estate<input name="estate_name" defaultValue="Demo Estate" /></label>
              <label>Block<input name="name" defaultValue="Block A" /></label>
              <label>Planting year<input name="planting_year" type="number" defaultValue="2018" /></label>
              <label>Palm spacing m<input name="palm_spacing_m" type="number" step="0.1" defaultValue="9" /></label>
              <label>Target palms/ha<input name="target_palms_ha" type="number" defaultValue="136" /></label>
              <button>Create Block</button>
            </form>
            <form className="panel form-grid" onSubmit={createMission}>
              <h2>Plan Mission</h2>
              <label>Mission type<select name="mission_type"><option value="inventory">Inventory</option><option value="inspection">Inspection</option><option value="repeat">Repeat monitoring</option></select></label>
              <label>Pilot<input name="pilot" defaultValue="Pilot" /></label>
              <label>Drone<input name="drone_name" defaultValue="DJI Mini 5 Pro" /></label>
              <label className="wide">Route notes<textarea name="route_notes" defaultValue="50MP nadir photos, 80/70 overlap, repeatable waypoint route." /></label>
              <button>Save Mission</button>
            </form>
          </section>
        )}

        {active === "Upload Imagery" && (
          <section className="two-col">
            <form className="panel form-grid" onSubmit={uploadPhotos}>
              <h2>Upload Photos</h2>
              <label>Sensor width mm optional<input name="sensor_width_mm" type="number" step="0.01" placeholder="Optional for GSD" /></label>
              <label>Focal length mm optional<input name="focal_length_mm" type="number" step="0.01" placeholder="Read from EXIF when available" /></label>
              <div
                className={`wide upload-dropzone ${photoDropActive ? "is-active" : ""}`}
                onDragEnter={(event) => {
                  event.preventDefault();
                  setPhotoDropActive(true);
                }}
                onDragOver={(event) => {
                  event.preventDefault();
                  setPhotoDropActive(true);
                }}
                onDragLeave={(event) => {
                  if (!event.currentTarget.contains(event.relatedTarget)) setPhotoDropActive(false);
                }}
                onDrop={handlePhotoDrop}
              >
                <strong>Drop photos or folders here</strong>
                <span>JPG, PNG, TIFF, and GeoTIFF files are accepted.</span>
                <div className="upload-picker-row">
                  <label className="file-input">Choose files<input type="file" multiple accept=".jpg,.jpeg,.png,.tif,.tiff" onChange={handlePhotoInputChange} /></label>
                  <label className="file-input">Choose folder<input type="file" multiple webkitdirectory="" directory="" onChange={handlePhotoInputChange} /></label>
                </div>
              </div>
              {!!selectedPhotoFiles.length && (
                <div className="wide selected-files">
                  <div className="selected-files-head">
                    <strong>{selectedPhotoFiles.length} files selected</strong>
                    <span>{formatBytes(selectedPhotoTotalBytes)}</span>
                    <button type="button" className="secondary-action" onClick={() => setSelectedPhotoFiles([])}>Clear</button>
                  </div>
                  <div className="selected-files-list">
                    {selectedPhotoFiles.slice(0, 8).map((file) => (
                      <span key={`${photoFilePath(file)}:${file.size}:${file.lastModified}`}>{photoFilePath(file)}</span>
                    ))}
                    {selectedPhotoFiles.length > 8 && <span>{selectedPhotoFiles.length - 8} more files</span>}
                  </div>
                </div>
              )}
              <button disabled={isUploading}>{isUploading ? `Uploading ${uploadProgress}%` : "Upload Photos"}</button>
              {isUploading && (
                <div className="wide upload-progress">
                  <div className="progress-track"><span style={{ width: `${uploadProgress}%` }} /></div>
                  <small>{uploadProgress >= 100 ? "Upload complete. Server is reading EXIF metadata." : "Uploading photos to the API."}</small>
                </div>
              )}
            </form>
            <form className="panel form-grid" onSubmit={registerCog}>
              <h2>Register COG</h2>
              <label className="wide">COG URL<input name="url" placeholder="https://.../orthomosaic.tif" /></label>
              <label className="wide file-input">Or upload GeoTIFF<input name="file" type="file" accept=".tif,.tiff" /></label>
              <button disabled={cogRegistering}>{cogRegistering ? "Registering..." : "Register COG"}</button>
            </form>
          </section>
        )}

        {active === "Stitching" && (
          <section className="stitching-layout">
            <div className="two-col">
              <div className="panel stitch-panel">
                <div className="panel-head">
                  <h2>Orthomosaic Stitching</h2>
                  <button disabled={stitchSubmitting} onClick={createOrthomosaicJob}>
                    {stitchSubmitting ? "Creating..." : "Create Stitch Job"}
                  </button>
                </div>
                <p>Use original DJI photos from the SD card. WhatsApp or edited images may stitch visually, but usually lose GPS and scale metadata.</p>
                <div className="stitch-options">
                  <label>Memory mode
                    <select value={stitchSettings.mode} onChange={(event) => updateStitchMode(event.target.value)}>
                      <option value="quick">Quick unified</option>
                      <option value="final">High quality unified</option>
                      <option value="partial">Low memory batch</option>
                      <option value="ultra_low">Emergency batch</option>
                    </select>
                  </label>
                  <label>Resize long edge px
                    <input
                      type="number"
                      min="800"
                      max="6000"
                      step="100"
                      placeholder="Original"
                      value={stitchSettings.resize_max_px}
                      onChange={(event) => updateStitchSetting("resize_max_px", event.target.value)}
                    />
                  </label>
                  <label>Max concurrency
                    <input
                      type="number"
                      min="1"
                      max="8"
                      value={stitchSettings.max_concurrency}
                      onChange={(event) => updateStitchSetting("max_concurrency", event.target.value)}
                    />
                  </label>
                  <label>Orthophoto cm/px
                    <input
                      type="number"
                      min="2"
                      max="30"
                      value={stitchSettings.orthophoto_resolution}
                      onChange={(event) => updateStitchSetting("orthophoto_resolution", event.target.value)}
                    />
                  </label>
                  <label>Partial batch size
                    <input
                      type="number"
                      min="0"
                      max="200"
                      placeholder="Off"
                      value={stitchSettings.split_batch_size}
                      onChange={(event) => updateStitchSetting("split_batch_size", event.target.value)}
                    />
                  </label>
                  <label>Batch overlap
                    <input
                      type="number"
                      min="0"
                      max="50"
                      value={stitchSettings.split_overlap}
                      onChange={(event) => updateStitchSetting("split_overlap", event.target.value)}
                    />
                  </label>
                  <label>Feature quality
                    <select value={stitchSettings.feature_quality} onChange={(event) => updateStitchSetting("feature_quality", event.target.value)}>
                      <option value="low">Low</option>
                      <option value="medium">Medium</option>
                      <option value="high">High</option>
                    </select>
                  </label>
                  <label className="inline-check">
                    <input type="checkbox" checked={stitchSettings.fast_orthophoto} onChange={(event) => updateStitchSetting("fast_orthophoto", event.target.checked)} />
                    <span>Fast orthophoto</span>
                  </label>
                  <label className="inline-check">
                    <input type="checkbox" checked={stitchSettings.skip_3dmodel} onChange={(event) => updateStitchSetting("skip_3dmodel", event.target.checked)} />
                    <span>Skip 3D model</span>
                  </label>
                  <label className="inline-check">
                    <input type="checkbox" checked={stitchSettings.minimal_outputs} onChange={(event) => updateStitchSetting("minimal_outputs", event.target.checked)} />
                    <span>Minimal outputs</span>
                  </label>
                </div>
                <div className="setup-note setup-note-blue">
                  <strong>Quick review plan</strong>
                  <span>Quick unified creates one downsampled mosaic for cleaner color and no batch stacking. Use High quality unified for final export, or batch modes only when memory prevents a unified run.</span>
                </div>
                <div className="quality-grid">
                  <article><span>Photos</span><strong>{stitchQuality?.image_count ?? 0}</strong></article>
                  <article><span>GPS coverage</span><strong>{stitchQuality?.gps_coverage_pct ?? 0}%</strong></article>
                  <article><span>Metadata check</span><strong>{humanize(stitchQuality?.readiness || "no_photos")}</strong><small>Overlap is checked during processing</small></article>
                  <article><span>Mean altitude</span><strong>{stitchQuality?.altitude_mean_m ? `${stitchQuality.altitude_mean_m} m` : "-"}</strong></article>
                  <article className={`processing-card status-${latestBlockStitchJob?.status || "idle"}`}>
                    <span>Processing</span>
                    <strong>{latestBlockStitchJob ? humanize(latestBlockStitchJob.status) : "Idle"}</strong>
                    <small>{latestBlockStitchJob ? `${stitchJobProgress(latestBlockStitchJob)}% ${stitchJobStage(latestBlockStitchJob)}` : "No active stitch job"}</small>
                  </article>
                  <article>
                    <span>Latest elapsed</span>
                    <strong>{latestBlockStitchJob ? formatDuration(elapsedJobSeconds(latestBlockStitchJob, nowTick)) : "-"}</strong>
                    <small>Estimate {latestBlockStitchJob ? stitchJobEstimate(latestBlockStitchJob) : "-"}</small>
                  </article>
                </div>
                {!!stitchQuality?.warnings?.length && (
                  <div className="warning-list">
                    {stitchQuality.warnings.map((warning) => <span key={warning}>{warning}</span>)}
                  </div>
                )}
                <button className="secondary-action" disabled={qualityRefreshing} onClick={refreshStitchQuality}>
                  {qualityRefreshing ? "Refreshing..." : "Refresh Metadata Check"}
                </button>
              </div>
              <div className="panel">
                <div className="panel-head"><h2>Stitch Jobs</h2><button disabled={stitchRefreshing} onClick={refreshStitchJobs}>{stitchRefreshing ? "Refreshing..." : "Refresh"}</button></div>
                <div className="table-list">
                  {blockOrthomosaicJobs.map((job) => (
                    <div key={job.id} className="table-row stitch-row">
                      <strong className={`status-pill status-${job.status}`}>{humanize(job.status)}</strong>
                      <div className="job-progress">
                        <div className="job-progress-head">
                          <span>{stitchJobStage(job)}</span>
                          <strong>{stitchJobProgress(job)}%</strong>
                        </div>
                        <div className={`progress-track status-${job.status}`}>
                          <span style={{ width: `${stitchJobProgress(job)}%` }} />
                        </div>
                        <small>{stitchJobDetail(job)}</small>
                        <div className="job-meta">
                          <span>Queue {formatDuration(queuedJobSeconds(job))}</span>
                          <span>Process {formatDuration(elapsedJobSeconds(job, nowTick))}</span>
                          <span>Total {formatDuration(totalJobSeconds(job, nowTick))}</span>
                          <span>Estimate {stitchJobEstimate(job)}</span>
                          {stitchJobBatchLabel(job) && <span>{stitchJobBatchLabel(job)}</span>}
                          {job.summary_json?.preprocessing?.enabled && <span>Resized to {job.summary_json.preprocessing.resize_max_px}px</span>}
                        </div>
                        {job.status === "failed" && job.summary_json?.recommended_action && (
                          <p className="job-error-note">{job.summary_json.recommended_action}</p>
                        )}
                      </div>
                      <div className="job-actions">
                        {job.output_asset_id && <button disabled={previewLoading} onClick={() => loadStitchPreview(job)}>{previewLoading ? "Loading..." : "Preview"}</button>}
                        {ACTIVE_STITCH_STATUSES.has(job.status) && <button className="danger-action" onClick={() => cancelStitchJob(job)}>Stop</button>}
                        {!ACTIVE_STITCH_STATUSES.has(job.status) && <button className="secondary-action" onClick={() => removeStitchJob(job)}>Remove</button>}
                        {!job.output_asset_id && !ACTIVE_STITCH_STATUSES.has(job.status) && <span>{job.asset_ids_json?.length || 0} photos</span>}
                      </div>
                    </div>
                  ))}
                  {!blockOrthomosaicJobs.length && <p>No stitch jobs for this selected block yet.</p>}
                </div>
                <div className="setup-note">
                  <strong>ODM engine</strong>
                  <span>Stitching uses the NodeODM service. Small or GPS-less image sets may still fail if ODM cannot solve camera alignment.</span>
                </div>
              </div>
            </div>
            <div className="panel stitch-preview-panel">
              <div className="panel-head">
                <div>
                  <h2>Stitched Preview</h2>
                  {stitchPreview && <p>{stitchPreview.asset_name}</p>}
                </div>
                <div className="panel-actions">
                  {stitchPreview && <button className="secondary-action" onClick={() => setStitchPreviewCollapsed((value) => !value)}>{stitchPreviewCollapsed ? "Expand Preview" : "Collapse Preview"}</button>}
                  {stitchPreview && <button disabled={mapLoading} onClick={() => openStitchJobOnMap({ block_id: stitchPreview.block_id, output_asset_id: stitchPreview.asset_id })}>{mapLoading ? "Opening..." : "Open On Map"}</button>}
                </div>
              </div>
              {!stitchPreview && <p>{previewLoading ? "Loading preview..." : "Choose Preview on a completed stitch job before opening it on the map."}</p>}
              {stitchPreview && stitchPreviewCollapsed && (
                <div className="preview-collapsed">
                  <strong>{stitchPreview.diagnostics?.risk_level || "unknown"} distortion risk</strong>
                  <span>{stitchPreview.diagnostics?.verdict}</span>
                </div>
              )}
              {stitchPreview && !stitchPreviewCollapsed && (
                <div className="stitch-preview-grid">
                  <figure className="preview-frame">
                    <img src={publicAssetUrl(stitchPreview.preview_url)} alt="Stitched orthomosaic preview" />
                  </figure>
                  <div className="diagnostic-list">
                    <div className={`risk-card risk-${stitchPreview.diagnostics?.risk_level || "unknown"}`}>
                      <span>Distortion risk</span>
                      <strong>{stitchPreview.diagnostics?.risk_level || "unknown"}</strong>
                      <p>{stitchPreview.diagnostics?.verdict}</p>
                    </div>
                    <div className="metadata-card">
                      <span>Raster</span>
                      <strong>{stitchPreview.raster_info?.width || "-"} x {stitchPreview.raster_info?.height || "-"}</strong>
                      <p>{stitchPreview.raster_info?.crs || "No CRS detected"}</p>
                    </div>
                    {!!stitchPreview.diagnostics?.issues?.length && (
                      <div className="diagnostic-issues">
                        {stitchPreview.diagnostics.issues.map((issue) => <span key={issue}>{issue}</span>)}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        {active === "Jobs" && (
          <section className="panel">
            <div className="panel-head"><h2>Inference Jobs</h2><button disabled={inferenceSubmitting} onClick={createJob}>{inferenceSubmitting ? "Creating..." : "Run Inference"}</button></div>
            <div className="table-list">{jobs.map((job) => <div key={job.id} className="table-row"><strong>{job.status}</strong><span>{job.id}</span><span>{job.error_code || job.summary_json?.unique_trees || "queued"}</span></div>)}</div>
          </section>
        )}

        {active === "Map" && (
          <section className="map-layout">
            <aside className="panel map-tools">
              <div className="map-tools-head">
                <h2>Map Review</h2>
                <div>
                  <button className="secondary-action" onClick={() => setAllMapSections(true)}>Show all</button>
                  <button className="secondary-action" onClick={() => setAllMapSections(false)}>Hide all</button>
                </div>
              </div>
              <CollapseCard title="Map overlays" meta={`${selectedCogAssetIds.length}/${cogs.length}`} open={mapSections.overlays} onToggle={() => toggleMapSection("overlays")}>
                <div className="overlay-list">
                  <label className="overlay-check">
                    <input type="checkbox" checked={selectedCogIds.includes("all")} onChange={(event) => toggleCog("all", event.target.checked)} />
                    <span>All overlays for comparison</span>
                  </label>
                  {cogs.map((asset) => (
                    <label className="overlay-check" key={asset.id}>
                      <input
                        type="checkbox"
                        disabled={selectedCogIds.includes("all")}
                        checked={selectedCogIds.includes("all") || selectedCogIds.includes(asset.id)}
                        onChange={(event) => toggleCog(asset.id, event.target.checked)}
                      />
                      <span>{cogLabel(asset)}</span>
                    </label>
                  ))}
                  {!cogs.length && <p>No orthomosaic overlays yet.</p>}
                </div>
              </CollapseCard>
              <CollapseCard title="Detection boxes" meta={detectionCount} open={mapSections.detections} onToggle={() => toggleMapSection("detections")}>
                <div className="overlay-list">
                  <label className="overlay-check">
                    <input type="checkbox" checked={showDetectionBoxes} onChange={(event) => setShowDetectionBoxes(event.target.checked)} />
                    <span>Show bounding boxes</span>
                  </label>
                  <div className="class-filter-grid">
                    {HEALTH_OPTIONS.map((item) => (
                      <label className="overlay-check class-check" key={item}>
                        <input
                          type="checkbox"
                          checked={selectedDetectionClasses.includes(item)}
                          onChange={(event) => toggleDetectionClass(item, event.target.checked)}
                        />
                        <span><i className={`class-dot status-${item}`} />{humanize(item)} <b>{detectionClassTotals[item] || 0}</b></span>
                      </label>
                    ))}
                  </div>
                  <div className="class-total-grid">
                    {HEALTH_OPTIONS.map((item) => (
                      <article key={item}>
                        <span>{humanize(item)}</span>
                        <strong>{selectedDetectionClasses.includes(item) ? detectionClassTotals[item] || 0 : 0}</strong>
                      </article>
                    ))}
                  </div>
                  <p>{detectionCount} visible boxes from {selectedCogAssetIds.length} selected overlay{selectedCogAssetIds.length === 1 ? "" : "s"}.</p>
                </div>
              </CollapseCard>
              <CollapseCard title="Map actions" meta={`${cogLayers.length} visible`} open={mapSections.actions} onToggle={() => toggleMapSection("actions")}>
                <div className="map-layer-note">
                  <strong>{cogLayers.length}</strong>
                  <span>{cogLayers.length === 1 ? "overlay visible" : "overlays visible"}</span>
                </div>
                <div className="map-action-grid">
                  <button disabled={mapLoading} onClick={zoomToSelectedArea}>{mapLoading ? "Loading..." : "Zoom To Selected Area"}</button>
                  <button className="secondary-action" onClick={locateUser}>Use My Location</button>
                  <button disabled={mapLoading} onClick={refreshMapData}>{mapLoading ? "Refreshing..." : "Refresh Map"}</button>
                </div>
              </CollapseCard>
              <CollapseCard title="AI Inference" meta={latestInferenceJob ? humanize(latestInferenceJob.status) : "Not started"} open={mapSections.inference} onToggle={() => toggleMapSection("inference")}>
                <div className="panel-head compact-head">
                  <h3>AI Inference</h3>
                  <button disabled={inferenceSubmitting || (modelStatus && !modelStatus.configured)} onClick={() => createJob()}>{inferenceButtonLabel}</button>
                </div>
                <div className="job-progress">
                  <div className="job-progress-head">
                    <span>{latestInferenceJob ? humanize(latestInferenceJob.status) : "Not started"}</span>
                    <strong>{inferenceJobProgress(latestInferenceJob)}%</strong>
                  </div>
                  <div className={`progress-track status-${latestInferenceJob?.status || "queued"}`}>
                    <span style={{ width: `${inferenceJobProgress(latestInferenceJob)}%` }} />
                  </div>
                  <small>{inferenceJobDetail(latestInferenceJob)}</small>
                </div>
                {modelStatus && !modelStatus.configured && (
                  <p className="job-error-note">{modelStatus.message}</p>
                )}
                {latestInferenceJob?.summary_json?.recommended_action && (
                  <p className="job-error-note">{latestInferenceJob.summary_json.recommended_action}</p>
                )}
              </CollapseCard>
              <CollapseCard title="Analytics" meta={`${mapAnalyticsCards.length} stats`} open={mapSections.analytics} onToggle={() => toggleMapSection("analytics")}>
                <div className="mini-metric-grid">
                  {mapAnalyticsCards.map(([label, value]) => (
                    <article key={label}>
                      <span>{label}</span>
                      <strong>{String(value ?? "-")}</strong>
                    </article>
                  ))}
                </div>
                {!!summary?.insights?.length && (
                  <div className="insight-list">
                    {summary.insights.map((insight) => <span key={insight}>{insight}</span>)}
                  </div>
                )}
              </CollapseCard>
              {!cogs.length && !treeCount && <p>No map layers for this block yet. Select the block with a completed stitch job or run inference.</p>}
              {!cogs.length && !treeCount && latestStitchedMap && <button className="secondary-action" disabled={mapLoading} onClick={() => openStitchJobOnMap(latestStitchedMap)}>{mapLoading ? "Opening..." : "Open Latest Orthomosaic"}</button>}
            </aside>
            <MapPanel
              trees={trees}
              detections={filteredDetections}
              showDetectionBoxes={showDetectionBoxes}
              showTreePoints={false}
              cogSource={cogSource}
              cogBounds={cogBounds}
              cogLayers={cogLayers}
              cogBoundsList={cogBoundsList}
              zoomRequest={mapZoomRequest}
              locateRequest={locateRequest}
              onLocateError={(error) => setMessage(`Location failed: ${error}`)}
            />
          </section>
        )}

        {active === "Analytics" && (
          <section className="metric-grid">
            {summary ? Object.entries(summary).filter(([, value]) => typeof value !== "object").map(([key, value]) => <article className="metric-card" key={key}><span>{key.replaceAll("_", " ")}</span><strong>{String(value ?? "-")}</strong></article>) : <div className="panel">No analytics yet.</div>}
          </section>
        )}

        {active === "Prescriptions" && (
          <section className="panel">
            <h2>VRT Prescription Export</h2>
            <p>Exports spot-treatment points as GeoJSON, CSV, KML, and KMZ in one bundle. Dose rates remain manager-configured.</p>
            <button onClick={downloadPrescription}>Download Prescription Bundle</button>
          </section>
        )}

        {active === "Reports" && (
          <section className="panel">
            <h2>Mission KMZ</h2>
            <div className="table-list">{missions.map((mission) => <div className="table-row" key={mission.id}><strong>{mission.mission_type}</strong><span>{mission.drone_name}</span><button onClick={() => downloadMissionKmz(mission.id)}>KMZ</button></div>)}</div>
          </section>
        )}

        {active === "Admin" && (
          <section className="panel">
            <h2>System</h2>
            <p>Model path defaults to <code>/models/palm_health.pt</code>. Missing weights intentionally fail inference with <code>model_not_configured</code>.</p>
            <button onClick={() => { localStorage.removeItem("palmops-token"); location.reload(); }}>Sign Out</button>
          </section>
        )}
      </main>
    </div>
  );
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

createRoot(document.getElementById("root")).render(<App />);
