// ============================================================
//  Slit-Scan Panorama — Web Application
//  Runs entirely in the browser using OpenCV.js
// ============================================================

// ── Global state ──
const state = {
  video: null,           // HTMLVideoElement
  fps: 30,
  totalFrames: 0,
  currentFrameIdx: 0,
  startFrame: -1,
  endFrame: -1,

  bgRoi: null,           // {x, y, w, h} — background ROI in image coords
  tramRoi: null,         // {x, y, w, h} — vehicle ROI in image coords
  tramFrameIdx: 0,
  slitX: null,           // null = ROI center, number = user override

  stabilizedFrames: [],  // array of {data: Uint8Array, w: number, h: number} — stored in JS heap, not WASM
  frameW: 0,
  frameH: 0,
  cancelled: false,
};

// ── DOM refs (populated on init) ──
let dom = {};

// ── OpenCV ready flag ──
let cvReady = false;

// ============================================================
//  OpenCV bootstrap
// ============================================================

function onOpenCvLoaded() {
  if (typeof cv !== 'undefined') {
    if (cv.getBuildInformation) {
      onCvReady();
    } else {
      cv['onRuntimeInitialized'] = onCvReady;
    }
  }
}

function onCvReady() {
  cvReady = true;
  const el = document.getElementById('opencv-loading');
  el.classList.add('fade-out');
  setTimeout(() => el.classList.add('hidden'), 500);
  console.log('OpenCV.js ready:', cv.getBuildInformation().split('\n')[0]);
}

// ============================================================
//  Initialization
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  dom = {
    dropZone:      document.getElementById('drop-zone'),
    fileInput:     document.getElementById('file-input'),
    btnLoad:       document.getElementById('btn-load'),
    workspace:     document.getElementById('workspace'),
    panels:        document.getElementById('panels'),
    status:        document.getElementById('status'),

    canvasOrig:    document.getElementById('canvas-original'),
    canvasStab:    document.getElementById('canvas-stabilized'),
    sliderFrame:   document.getElementById('slider-frame'),
    sliderStab:    document.getElementById('slider-stab'),
    frameLabel:    document.getElementById('frame-label'),
    stabFrameLabel:document.getElementById('stab-frame-label'),

    btnStart:      document.getElementById('btn-start'),
    btnEnd:        document.getElementById('btn-end'),
    lblStart:      document.getElementById('lbl-start'),
    lblEnd:        document.getElementById('lbl-end'),
    lblBgRoi:      document.getElementById('lbl-bg-roi'),
    btnStabilize:  document.getElementById('btn-stabilize'),

    lblTramRoi:    document.getElementById('lbl-tram-roi'),
    lblSlitPos:    document.getElementById('lbl-slit-pos'),
    btnPanorama:   document.getElementById('btn-panorama'),

    roiHintOrig:   document.getElementById('roi-hint-original'),
    roiHintStab:   document.getElementById('roi-hint-stab'),

    chkSideBySide: document.getElementById('chk-side-by-side'),

    progressOverlay: document.getElementById('progress-overlay'),
    progressTitle:   document.getElementById('progress-title'),
    progressFill:    document.getElementById('progress-fill'),
    progressDetail:  document.getElementById('progress-detail'),
    btnCancel:       document.getElementById('btn-cancel'),

    panoramaModal:   document.getElementById('panorama-modal'),
    canvasPanorama:  document.getElementById('canvas-panorama'),
    panoramaStats:   document.getElementById('panorama-stats'),
    btnSavePanorama: document.getElementById('btn-save-panorama'),
    btnClosePanorama:document.getElementById('btn-close-panorama'),
    btnCloseModal:   document.getElementById('btn-close-modal'),
  };

  state.video = document.getElementById('video-element');

  // ── Wire up events ──
  dom.btnLoad.addEventListener('click', () => dom.fileInput.click());
  dom.fileInput.addEventListener('change', e => {
    if (e.target.files.length) loadVideo(e.target.files[0]);
  });

  // Drag-and-drop
  dom.dropZone.addEventListener('dragover', e => {
    e.preventDefault();
    dom.dropZone.classList.add('drag-over');
  });
  dom.dropZone.addEventListener('dragleave', () => {
    dom.dropZone.classList.remove('drag-over');
  });
  dom.dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dom.dropZone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('video/')) loadVideo(file);
  });

  // Frame navigation
  dom.sliderFrame.addEventListener('input', e => showFrame(parseInt(e.target.value)));
  dom.sliderStab.addEventListener('input', e => showStabilizedFrame(parseInt(e.target.value)));

  // Keyboard navigation
  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT' && e.target.type !== 'range') return;
    const slider = document.activeElement === dom.sliderStab ? dom.sliderStab : dom.sliderFrame;
    if (e.key === 'ArrowLeft')  { slider.value = Math.max(0, parseInt(slider.value) - 1); slider.dispatchEvent(new Event('input')); e.preventDefault(); }
    if (e.key === 'ArrowRight') { slider.value = Math.min(parseInt(slider.max), parseInt(slider.value) + 1); slider.dispatchEvent(new Event('input')); e.preventDefault(); }
  });

  // Frame range
  dom.btnStart.addEventListener('click', setStartFrame);
  dom.btnEnd.addEventListener('click', setEndFrame);

  // Processing
  dom.btnStabilize.addEventListener('click', stabilizeFrames);
  dom.btnPanorama.addEventListener('click', generatePanorama);
  dom.btnCancel.addEventListener('click', () => { state.cancelled = true; });

  // Layout toggle
  dom.chkSideBySide.addEventListener('change', e => {
    dom.panels.className = e.target.checked ? 'panels-horizontal' : 'panels-vertical';
  });

  // Panorama modal
  dom.btnClosePanorama.addEventListener('click', closePanoramaModal);
  dom.btnCloseModal.addEventListener('click', closePanoramaModal);
  dom.btnSavePanorama.addEventListener('click', savePanorama);

  // ROI drawing on canvases
  setupROIDrawing(dom.canvasOrig, roi => {
    state.bgRoi = roi;
    dom.lblBgRoi.textContent = `BG ROI: [${roi.x}, ${roi.y}, ${roi.w}×${roi.h}]`;
    updateUI();
    redrawOriginal();
  }, null);

  setupROIDrawing(dom.canvasStab, roi => {
    state.tramRoi = roi;
    state.tramFrameIdx = parseInt(dom.sliderStab.value);
    state.slitX = null;
    dom.lblTramRoi.textContent = `Vehicle ROI: [${roi.x}, ${roi.y}, ${roi.w}×${roi.h}] @ frame ${state.tramFrameIdx}`;
    dom.lblSlitPos.textContent = 'Slit: center (right-click to override)';
    updateUI();
    redrawStabilized();
  }, point => {
    state.slitX = point.x;
    dom.lblSlitPos.textContent = `Slit: x=${point.x} (right-click to change)`;
    redrawStabilized();
  });
});

// ============================================================
//  Video loading
// ============================================================

function loadVideo(file) {
  if (!cvReady) { alert('OpenCV.js is still loading. Please wait.'); return; }

  // Clean up previous state
  freeStabilizedFrames();
  state.startFrame = -1;
  state.endFrame = -1;
  state.bgRoi = null;
  state.tramRoi = null;
  state.slitX = null;

  const url = URL.createObjectURL(file);
  const video = state.video;
  video.src = url;

  video.onloadedmetadata = () => {
    state.fps = video.mozFrameRate || video.webkitFrameRate || 30;
    // Try to get accurate fps from video metadata
    if (video.duration && video.duration > 0) {
      // Use a heuristic: seek to end to count frames
      // For now, assume 30fps if not available, or use the duration-based estimate
    }
    state.totalFrames = Math.round(video.duration * state.fps);

    dom.sliderFrame.max = Math.max(0, state.totalFrames - 1);
    dom.sliderFrame.value = 0;
    dom.sliderFrame.disabled = false;

    dom.status.textContent = `${file.name} (${video.videoWidth}×${video.videoHeight}, ~${state.totalFrames} frames)`;
    dom.lblStart.textContent = 'Start: ---';
    dom.lblEnd.textContent = 'End: ---';
    dom.lblBgRoi.textContent = 'Background ROI: Not selected';
    dom.lblTramRoi.textContent = 'Vehicle ROI: Not selected';
    dom.lblSlitPos.textContent = 'Slit: center (right-click to override)';

    // Resize canvases to match video dimensions
    dom.canvasOrig.width = video.videoWidth;
    dom.canvasOrig.height = video.videoHeight;

    // Auto side-by-side for portrait videos
    if (video.videoHeight > video.videoWidth) {
      dom.chkSideBySide.checked = true;
      dom.panels.className = 'panels-horizontal';
    }

    dom.dropZone.classList.add('hidden');
    dom.workspace.classList.remove('hidden');
    dom.roiHintOrig.classList.remove('hidden');

    showFrame(0);
    updateUI();
  };

  video.onerror = () => {
    alert('Could not load video. Make sure the format is supported by your browser (MP4 recommended).');
  };
}

// ============================================================
//  Frame display
// ============================================================

async function seekToTime(video, time) {
  return new Promise((resolve) => {
    if (Math.abs(video.currentTime - time) < 0.001) {
      resolve();
      return;
    }
    video.onseeked = () => resolve();
    video.currentTime = time;
  });
}

async function showFrame(frameIdx) {
  const video = state.video;
  if (!video || !video.duration) return;

  state.currentFrameIdx = frameIdx;
  const time = frameIdx / state.fps;
  await seekToTime(video, time);

  const ctx = dom.canvasOrig.getContext('2d');
  ctx.drawImage(video, 0, 0);
  dom.frameLabel.textContent = `Frame ${frameIdx} / ${state.totalFrames - 1}`;

  // Redraw ROI overlay
  drawROIOverlay(dom.canvasOrig, state.bgRoi, null);
}

function showStabilizedFrame(frameIdx) {
  if (frameIdx < 0 || frameIdx >= state.stabilizedFrames.length) return;

  const mat = jsFrameToMat(state.stabilizedFrames[frameIdx]);
  const enhanced = enhanceFrame(mat);
  mat.delete();

  dom.canvasStab.width = enhanced.cols;
  dom.canvasStab.height = enhanced.rows;

  cv.imshow(dom.canvasStab, enhanced);
  enhanced.delete();

  dom.stabFrameLabel.textContent = `Frame ${frameIdx} / ${state.stabilizedFrames.length - 1}`;

  // Redraw ROI & slit overlays
  drawROIOverlay(dom.canvasStab, state.tramRoi, state.slitX);
}

function redrawOriginal() {
  // Re-draw current frame + ROI overlay without re-seeking
  const ctx = dom.canvasOrig.getContext('2d');
  ctx.drawImage(state.video, 0, 0);
  drawROIOverlay(dom.canvasOrig, state.bgRoi, null);
}

function redrawStabilized() {
  const idx = parseInt(dom.sliderStab.value);
  if (idx >= 0 && idx < state.stabilizedFrames.length) {
    showStabilizedFrame(idx);
  }
}

// Draw ROI rectangle and optional slit line on a canvas
function drawROIOverlay(canvas, roi, slitX) {
  const ctx = canvas.getContext('2d');
  // Need to re-draw the frame content first for original canvas
  // For stabilized canvas, cv.imshow already drew the image
  // So we just draw overlays on top

  if (roi) {
    ctx.strokeStyle = 'rgba(255, 0, 0, 0.9)';
    ctx.lineWidth = 2;
    ctx.strokeRect(roi.x, roi.y, roi.w, roi.h);
  }

  if (slitX !== null && slitX !== undefined) {
    ctx.strokeStyle = 'rgba(0, 255, 255, 0.8)';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(slitX, 0);
    ctx.lineTo(slitX, canvas.height);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

// ============================================================
//  ROI drawing on canvas
// ============================================================

function setupROIDrawing(canvas, onRoiSelected, onPointSelected) {
  let drawing = false;
  let startX = 0, startY = 0;
  let savedImageData = null; // snapshot of canvas before drag starts

  function canvasToImage(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: Math.round((e.clientX - rect.left) * scaleX),
      y: Math.round((e.clientY - rect.top) * scaleY),
    };
  }

  canvas.addEventListener('mousedown', e => {
    if (e.button === 0 && canvas.width > 0 && canvas.height > 0) {
      const pos = canvasToImage(e);
      startX = pos.x;
      startY = pos.y;
      drawing = true;
      // Snapshot the canvas so we can restore it cheaply during drag
      const ctx = canvas.getContext('2d');
      savedImageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      e.preventDefault();
    }
  });

  canvas.addEventListener('mousemove', e => {
    if (!drawing || !savedImageData) return;
    const pos = canvasToImage(e);

    // Restore the snapshot (no OpenCV calls!)
    const ctx = canvas.getContext('2d');
    ctx.putImageData(savedImageData, 0, 0);

    // Draw selection rectangle
    ctx.strokeStyle = 'rgba(255, 255, 0, 0.9)';
    ctx.lineWidth = 2;
    ctx.strokeRect(startX, startY, pos.x - startX, pos.y - startY);
  });

  canvas.addEventListener('mouseup', e => {
    if (e.button === 0 && drawing) {
      drawing = false;
      const pos = canvasToImage(e);
      const x1 = Math.max(0, Math.min(startX, pos.x));
      const y1 = Math.max(0, Math.min(startY, pos.y));
      const x2 = Math.min(canvas.width, Math.max(startX, pos.x));
      const y2 = Math.min(canvas.height, Math.max(startY, pos.y));
      const w = x2 - x1;
      const h = y2 - y1;

      if (w > 5 && h > 5) {
        onRoiSelected({ x: x1, y: y1, w, h });
      }
    }
  });

  // Right-click for slit position
  canvas.addEventListener('contextmenu', e => {
    e.preventDefault();
    if (onPointSelected) {
      const pos = canvasToImage(e);
      onPointSelected(pos);
    }
  });
}

// ============================================================
//  Image enhancement (CLAHE + saturation boost)
// ============================================================

function enhanceFrame(src) {
  // src: cv.Mat in RGBA — returns a new RGBA mat (caller must delete)
  // Applies CLAHE contrast enhancement + saturation boost.
  // Kept lightweight to avoid WASM heap pressure.
  try {
    let bgr = new cv.Mat();
    cv.cvtColor(src, bgr, cv.COLOR_RGBA2BGR);

    // CLAHE on L channel
    let lab = new cv.Mat();
    cv.cvtColor(bgr, lab, cv.COLOR_BGR2Lab);
    let labPlanes = new cv.MatVector();
    cv.split(lab, labPlanes);

    let lChannel = labPlanes.get(0);
    let clahe = new cv.CLAHE(2.0, new cv.Size(8, 8));
    let lEnhanced = new cv.Mat();
    clahe.apply(lChannel, lEnhanced);

    // Rebuild LAB with enhanced L
    let newLabPlanes = new cv.MatVector();
    newLabPlanes.push_back(lEnhanced);
    newLabPlanes.push_back(labPlanes.get(1));
    newLabPlanes.push_back(labPlanes.get(2));
    cv.merge(newLabPlanes, lab);
    cv.cvtColor(lab, bgr, cv.COLOR_Lab2BGR);

    // Saturation boost: work directly on the data array to avoid extra Mat allocations
    let hsv = new cv.Mat();
    cv.cvtColor(bgr, hsv, cv.COLOR_BGR2HSV);
    let hsvData = hsv.data;
    for (let p = 1; p < hsvData.length; p += 3) {
      hsvData[p] = Math.min(255, Math.round(hsvData[p] * 1.3));
    }
    cv.cvtColor(hsv, bgr, cv.COLOR_HSV2BGR);

    let rgba = new cv.Mat();
    cv.cvtColor(bgr, rgba, cv.COLOR_BGR2RGBA);

    // Cleanup
    bgr.delete(); lab.delete(); labPlanes.delete(); newLabPlanes.delete();
    clahe.delete(); lEnhanced.delete(); hsv.delete();

    return rgba;
  } catch (e) {
    // If enhancement fails, return a plain RGBA copy
    console.warn('Enhancement failed, returning original:', cvErr(e));
    let rgba = src.clone();
    return rgba;
  }
}

// ============================================================
//  Frame range
// ============================================================

function setStartFrame() {
  state.startFrame = state.currentFrameIdx;
  dom.lblStart.textContent = `Start: ${state.startFrame}`;
  updateUI();
}

function setEndFrame() {
  state.endFrame = state.currentFrameIdx;
  dom.lblEnd.textContent = `End: ${state.endFrame}`;
  updateUI();
}

// ============================================================
//  UI state management
// ============================================================

function updateUI() {
  const hasVideo = state.video && state.video.duration > 0;
  dom.btnStart.disabled = !hasVideo;
  dom.btnEnd.disabled = !hasVideo;

  const canStabilize = hasVideo &&
    state.startFrame >= 0 && state.endFrame >= 0 &&
    state.startFrame <= state.endFrame && state.bgRoi !== null;
  dom.btnStabilize.disabled = !canStabilize;

  const hasStab = state.stabilizedFrames.length > 0;
  dom.sliderStab.disabled = !hasStab;

  const canPano = hasStab && state.tramRoi !== null;
  dom.btnPanorama.disabled = !canPano;

  if (hasStab) {
    dom.roiHintStab.classList.remove('hidden');
    dom.roiHintStab.textContent = 'Draw a rectangle over the vehicle · Right-click to set slit position';
  }
}

// ============================================================
//  Progress helpers
// ============================================================

function showProgress(title) {
  state.cancelled = false;
  dom.progressTitle.textContent = title;
  dom.progressDetail.textContent = '';
  dom.progressFill.style.width = '0%';
  dom.progressOverlay.classList.remove('hidden');
}

function updateProgress(fraction, detail) {
  dom.progressFill.style.width = `${Math.round(fraction * 100)}%`;
  if (detail !== undefined) dom.progressDetail.textContent = detail;
}

function hideProgress() {
  dom.progressOverlay.classList.add('hidden');
}

async function yieldToUI() {
  return new Promise(r => setTimeout(r, 0));
}

// ============================================================
//  Frame extraction helper
// ============================================================

async function extractFrameAsMat(frameIdx) {
  const video = state.video;
  const time = frameIdx / state.fps;
  await seekToTime(video, time);

  const w = video.videoWidth;
  const h = video.videoHeight;
  const tmpCanvas = document.createElement('canvas');
  tmpCanvas.width = w;
  tmpCanvas.height = h;
  const ctx = tmpCanvas.getContext('2d');
  ctx.drawImage(video, 0, 0, w, h);

  const imageData = ctx.getImageData(0, 0, w, h);
  const mat = cv.matFromImageData(imageData);
  return mat; // CV_8UC4 (RGBA)
}

// ============================================================
//  Frame storage (JS heap, not WASM heap)
// ============================================================

// Store a cv.Mat as a plain JS object and delete the Mat to free WASM memory.
function matToJsFrame(mat) {
  // mat is CV_8UC4 (RGBA)
  let frame = { data: new Uint8Array(mat.data), w: mat.cols, h: mat.rows };
  return frame;
}

// Temporarily convert a JS frame back to a cv.Mat. Caller MUST delete the returned Mat.
function jsFrameToMat(frame) {
  let mat = new cv.Mat(frame.h, frame.w, cv.CV_8UC4);
  mat.data.set(frame.data);
  return mat;
}

// ============================================================
//  Similarity transform estimator (replaces estimateAffinePartial2D)
// ============================================================

// Estimate a similarity transform (rotation + scale + translation) from
// matched point pairs using RANSAC.  Returns a 2×3 cv.Mat or null.
//
// srcPts/dstPts: flat arrays [x0, y0, x1, y1, ...] with N point pairs.
function estimateSimilarityRANSAC(srcPts, dstPts, threshold, maxIters) {
  threshold = threshold || 5.0;
  maxIters = maxIters || 200;
  const n = srcPts.length / 2;
  if (n < 2) return null;

  // Solve similarity from exactly 2 point pairs:
  //   a*x - b*y + tx = u
  //   b*x + a*y + ty = v
  function solveFromTwo(i, j) {
    let x1 = srcPts[i * 2], y1 = srcPts[i * 2 + 1];
    let x2 = srcPts[j * 2], y2 = srcPts[j * 2 + 1];
    let u1 = dstPts[i * 2], v1 = dstPts[i * 2 + 1];
    let u2 = dstPts[j * 2], v2 = dstPts[j * 2 + 1];

    let dx = x2 - x1, dy = y2 - y1;
    let du = u2 - u1, dv = v2 - v1;
    let denom = dx * dx + dy * dy;
    if (denom < 1e-10) return null;

    let a = (dx * du + dy * dv) / denom;
    let b = (dx * dv - dy * du) / denom;
    let tx = u1 - a * x1 + b * y1;
    let ty = v1 - b * x1 - a * y1;
    return { a, b, tx, ty };
  }

  function countInliers(params) {
    let count = 0;
    let { a, b, tx, ty } = params;
    for (let i = 0; i < n; i++) {
      let x = srcPts[i * 2], y = srcPts[i * 2 + 1];
      let eu = a * x - b * y + tx - dstPts[i * 2];
      let ev = b * x + a * y + ty - dstPts[i * 2 + 1];
      if (eu * eu + ev * ev < threshold * threshold) count++;
    }
    return count;
  }

  let bestParams = null;
  let bestCount = 0;

  for (let iter = 0; iter < maxIters; iter++) {
    let i = Math.floor(Math.random() * n);
    let j = Math.floor(Math.random() * (n - 1));
    if (j >= i) j++;
    let params = solveFromTwo(i, j);
    if (!params) continue;
    let count = countInliers(params);
    if (count > bestCount) {
      bestCount = count;
      bestParams = params;
      if (count > n * 0.9) break; // good enough
    }
  }

  if (!bestParams || bestCount < 4) return null;

  // Refine on all inliers using least-squares
  let { a, b, tx, ty } = bestParams;
  let sumXX = 0, sumXY = 0, sumX = 0, sumY = 0;
  let sumUX = 0, sumUY = 0, sumVX = 0, sumVY = 0;
  let sumU = 0, sumV = 0, cnt = 0;

  for (let i = 0; i < n; i++) {
    let x = srcPts[i * 2], y = srcPts[i * 2 + 1];
    let eu = a * x - b * y + tx - dstPts[i * 2];
    let ev = b * x + a * y + ty - dstPts[i * 2 + 1];
    if (eu * eu + ev * ev >= threshold * threshold) continue;

    let u = dstPts[i * 2], v = dstPts[i * 2 + 1];
    sumXX += x * x + y * y;
    sumXY += 0; // symmetric
    sumX += x; sumY += y;
    sumUX += u * x + v * y;
    sumVX += v * x - u * y;
    sumU += u; sumV += v;
    cnt++;
  }

  if (cnt < 2) return null;

  // Normal equations for [a, b, tx, ty]:
  //   [sumXX,  0,    sumX, -sumY] [a ]   [sumUX]
  //   [0,      sumXX, sumY,  sumX] [b ] = [sumVX]
  //   [sumX,   sumY,  cnt,   0   ] [tx]   [sumU ]
  //   [-sumY,  sumX,  0,     cnt ] [ty]   [sumV ]
  // This is a 4×4 system. Solve it the simple way.
  let det = sumXX * cnt - sumX * sumX - sumY * sumY; // Simplified for this structure
  // Actually, let me solve it properly but simply — use the 2-point approach on all inlier centroids
  let cxS = sumX / cnt, cyS = sumY / cnt;
  let cxD = sumU / cnt, cyD = sumV / cnt;

  let num_a = 0, num_b = 0, denom2 = 0;
  for (let i = 0; i < n; i++) {
    let x = srcPts[i * 2], y = srcPts[i * 2 + 1];
    let eu2 = a * x - b * y + tx - dstPts[i * 2];
    let ev2 = b * x + a * y + ty - dstPts[i * 2 + 1];
    if (eu2 * eu2 + ev2 * ev2 >= threshold * threshold) continue;

    let u = dstPts[i * 2], v = dstPts[i * 2 + 1];
    let dxs = x - cxS, dys = y - cyS;
    let dxd = u - cxD, dyd = v - cyD;
    num_a += dxs * dxd + dys * dyd;
    num_b += dxs * dyd - dys * dxd;
    denom2 += dxs * dxs + dys * dys;
  }

  if (denom2 < 1e-10) return null;
  a = num_a / denom2;
  b = num_b / denom2;
  tx = cxD - a * cxS + b * cyS;
  ty = cyD - b * cxS - a * cyS;

  // Build 2×3 cv.Mat
  let M = new cv.Mat(2, 3, cv.CV_64F);
  M.data64F[0] = a;  M.data64F[1] = -b; M.data64F[2] = tx;
  M.data64F[3] = b;  M.data64F[4] =  a; M.data64F[5] = ty;
  return M;
}

// ============================================================
//  Stabilization
// ============================================================

// OpenCV.js throws WASM heap pointers as exceptions, not Error objects.
function cvErr(e) {
  if (typeof e === 'number') {
    try { return cv.exceptionFromPtr(e).msg; } catch (_) {}
  }
  return e.message || String(e);
}

async function stabilizeFrames() {
  if (!cvReady) return;
  const { startFrame, endFrame, bgRoi } = state;
  if (startFrame < 0 || endFrame < startFrame || !bgRoi) return;

  freeStabilizedFrames();
  showProgress('Extracting & stabilizing frames...');

  try {
    // Extract reference frame
    const refMat = await extractFrameAsMat(startFrame);
    let refGray = new cv.Mat();
    cv.cvtColor(refMat, refGray, cv.COLOR_RGBA2GRAY);

    // Create mask for background ROI — fill the ROI region with 255
    let mask = cv.Mat.zeros(refGray.rows, refGray.cols, cv.CV_8U);
    {
      let roiRect = new cv.Rect(bgRoi.x, bgRoi.y, bgRoi.w, bgRoi.h);
      let roiView = mask.roi(roiRect);
      roiView.setTo(new cv.Scalar(255, 0, 0, 0));
      // roiView is a header/view into mask — do NOT delete it
    }

    // Detect features on reference frame
    let orb = new cv.ORB();
    let kpRef = new cv.KeyPointVector();
    let desRef = new cv.Mat();
    orb.detectAndCompute(refGray, mask, kpRef, desRef);

    if (desRef.empty() || kpRef.size() < 4) {
      hideProgress();
      alert('Not enough features found in the background ROI. Please select a larger or more textured area.');
      refMat.delete(); refGray.delete(); mask.delete();
      orb.delete(); kpRef.delete(); desRef.delete();
      return;
    }

    let bf = new cv.BFMatcher(cv.NORM_HAMMING);
    const totalFrames = endFrame - startFrame + 1;

    for (let i = 0; i < totalFrames; i++) {
      if (state.cancelled) break;

      const frameIdx = startFrame + i;
      const currMat = await extractFrameAsMat(frameIdx);

      let currGray = new cv.Mat();
      cv.cvtColor(currMat, currGray, cv.COLOR_RGBA2GRAY);

      let kpCurr = new cv.KeyPointVector();
      let desCurr = new cv.Mat();
      let noMask = new cv.Mat();  // empty Mat = no mask
      orb.detectAndCompute(currGray, noMask, kpCurr, desCurr);

      let M = null;

      if (!desCurr.empty() && kpCurr.size() >= 4) {
        let matches = new cv.DMatchVectorVector();
        bf.knnMatch(desCurr, desRef, matches, 2);

        // Lowe's ratio test
        let srcPts = [];
        let dstPts = [];
        for (let j = 0; j < matches.size(); j++) {
          let mv = matches.get(j);
          if (mv.size() >= 2) {
            let m0 = mv.get(0);
            let m1 = mv.get(1);
            if (m0.distance < 0.7 * m1.distance) {
              let srcKp = kpCurr.get(m0.queryIdx);
              let dstKp = kpRef.get(m0.trainIdx);
              srcPts.push(srcKp.pt.x, srcKp.pt.y);
              dstPts.push(dstKp.pt.x, dstKp.pt.y);
            }
          }
        }
        matches.delete();

        if (srcPts.length >= 8) { // at least 4 point pairs
          // Try OpenCV's estimateAffinePartial2D first (not in all builds)
          if (typeof cv.estimateAffinePartial2D === 'function') {
            try {
              let srcMat = cv.matFromArray(srcPts.length / 2, 1, cv.CV_32FC2, srcPts);
              let dstMat = cv.matFromArray(dstPts.length / 2, 1, cv.CV_32FC2, dstPts);
              let inliers = new cv.Mat();
              M = cv.estimateAffinePartial2D(srcMat, dstMat, inliers, cv.RANSAC);
              inliers.delete(); srcMat.delete(); dstMat.delete();
            } catch (e) {
              M = null;
            }
          }
          // Fallback: our own RANSAC similarity estimator (works on flat arrays directly)
          if (!M) {
            M = estimateSimilarityRANSAC(srcPts, dstPts, 5.0, 300);
          }
        }
      }

      // Apply transform (or identity)
      let stabFrame = new cv.Mat();
      if (M && !M.empty()) {
        // Decompose and clamp rotation/scale
        let cos_a = M.data64F[0];
        let sin_a = M.data64F[3];
        let angle = Math.atan2(sin_a, cos_a) * 180 / Math.PI;
        let scale = Math.sqrt(cos_a * cos_a + sin_a * sin_a);
        let tx = M.data64F[2];
        let ty = M.data64F[5];

        angle = Math.max(-5, Math.min(5, angle));
        scale = Math.max(0.95, Math.min(1.05, scale));

        let rad = angle * Math.PI / 180;
        M.data64F[0] = scale * Math.cos(rad);
        M.data64F[1] = -scale * Math.sin(rad);
        M.data64F[3] = scale * Math.sin(rad);
        M.data64F[4] = scale * Math.cos(rad);
        M.data64F[2] = tx;
        M.data64F[5] = ty;

        cv.warpAffine(currMat, stabFrame, M, new cv.Size(currMat.cols, currMat.rows),
          cv.INTER_LINEAR, cv.BORDER_REPLICATE, new cv.Scalar(0, 0, 0, 255));
        M.delete();
      } else {
        currMat.copyTo(stabFrame);
      }

      // Store as plain JS array to avoid filling the WASM heap
      state.stabilizedFrames.push(matToJsFrame(stabFrame));
      stabFrame.delete();

      currGray.delete(); kpCurr.delete(); desCurr.delete(); noMask.delete();
      currMat.delete();

      updateProgress((i + 1) / totalFrames, `Frame ${i + 1} / ${totalFrames}`);
      if (i % 3 === 0) await yieldToUI();
    }

    refMat.delete(); refGray.delete(); mask.delete();
    orb.delete(); kpRef.delete(); desRef.delete(); bf.delete();

    // Setup stabilized view
    if (state.stabilizedFrames.length > 0) {
      dom.sliderStab.max = state.stabilizedFrames.length - 1;
      dom.sliderStab.value = 0;
      state.frameW = state.stabilizedFrames[0].w;
      state.frameH = state.stabilizedFrames[0].h;
      dom.canvasStab.width = state.frameW;
      dom.canvasStab.height = state.frameH;
      showStabilizedFrame(0);
    }

    updateUI();
  } catch (err) {
    console.error('Stabilization error:', cvErr(err));
    alert('Stabilization failed: ' + cvErr(err));
  } finally {
    hideProgress();
  }
}

function freeStabilizedFrames() {
  // JS frames are plain objects — just release the array for GC
  state.stabilizedFrames = [];
  state.frameW = 0;
  state.frameH = 0;
  state.tramRoi = null;
  state.slitX = null;
}

// ============================================================
//  Phase correlation (pure implementation)
// ============================================================

function phaseCorrelate(gray1, gray2) {
  // gray1, gray2: CV_32F single-channel mats of equal size
  let h = gray1.rows, w = gray1.cols;

  // Clone and apply Hanning window
  let win1 = gray1.clone();
  let win2 = gray2.clone();
  applyHanningWindow(win1);
  applyHanningWindow(win2);

  // DFT (complex output)
  let F1 = new cv.Mat();
  let F2 = new cv.Mat();
  cv.dft(win1, F1, cv.DFT_COMPLEX_OUTPUT);
  cv.dft(win2, F2, cv.DFT_COMPLEX_OUTPUT);

  // F1, F2 are CV_32FC2 — interleaved [re, im, re, im, ...]
  let d1 = F1.data32F;
  let d2 = F2.data32F;
  let n = h * w;

  // Cross-power spectrum in-place in F1
  for (let i = 0; i < n; i++) {
    let re1 = d1[2 * i],     im1 = d1[2 * i + 1];
    let re2 = d2[2 * i],     im2 = d2[2 * i + 1];
    // conj(F1) * F2  (matches OpenCV cv2.phaseCorrelate sign convention)
    let cRe = re1 * re2 + im1 * im2;
    let cIm = re1 * im2 - im1 * re2;
    let mag = Math.sqrt(cRe * cRe + cIm * cIm) + 1e-10;
    d1[2 * i]     = cRe / mag;
    d1[2 * i + 1] = cIm / mag;
  }

  // Inverse DFT (cv.idft is not in all OpenCV.js builds; use cv.dft with DFT_INVERSE)
  let result = new cv.Mat();
  cv.dft(F1, result, cv.DFT_INVERSE | cv.DFT_SCALE | cv.DFT_REAL_OUTPUT);

  // Find peak
  let minMax = cv.minMaxLoc(result);
  let peak = minMax.maxLoc;
  let confidence = minMax.maxVal;

  let dx = peak.x;
  let dy = peak.y;
  if (dx > w / 2) dx -= w;
  if (dy > h / 2) dy -= h;

  win1.delete(); win2.delete();
  F1.delete(); F2.delete();
  result.delete();

  return { dx, dy, confidence };
}

function applyHanningWindow(mat) {
  let h = mat.rows, w = mat.cols;
  let data = mat.data32F;
  for (let y = 0; y < h; y++) {
    let wy = 0.5 * (1 - Math.cos(2 * Math.PI * y / h));
    for (let x = 0; x < w; x++) {
      let wx = 0.5 * (1 - Math.cos(2 * Math.PI * x / w));
      data[y * w + x] *= wy * wx;
    }
  }
}

// ============================================================
//  Panorama generation
// ============================================================

async function generatePanorama() {
  if (!state.stabilizedFrames.length || !state.tramRoi) return;

  const nFrames = state.stabilizedFrames.length;
  const hFrame = state.frameH;
  const wFrame = state.frameW;
  const { x: rx, y: ry, w: rw, h: rh } = state.tramRoi;
  const roiCx = state.slitX !== null ? state.slitX : rx + Math.floor(rw / 2);
  const roiCy = ry + Math.floor(rh / 2);

  showProgress('Phase 1: Estimating direction...');

  try {
    // ── Phase 1: Direction estimation via phase correlation ──
    let sampleDxList = [];
    let sampleDyList = [];
    const halfWindow = 5;
    const center = Math.max(halfWindow, Math.min(state.tramFrameIdx, nFrames - 1 - halfWindow));

    for (let k = center - halfWindow; k < center + halfWindow; k++) {
      if (state.cancelled) { hideProgress(); return; }
      if (k < 0 || k >= nFrames - 1) continue;

      let y1 = Math.max(0, ry);
      let y2 = Math.min(hFrame, ry + rh);
      let x1 = Math.max(0, rx);
      let x2 = Math.min(wFrame, rx + rw);

      // Crop directly from JS frames — no full-frame Mat allocation
      let cropA = cropJsFrameToFloat(state.stabilizedFrames[k], x1, y1, x2 - x1, y2 - y1);
      let cropB = cropJsFrameToFloat(state.stabilizedFrames[k + 1], x1, y1, x2 - x1, y2 - y1);

      if (cropA.rows > 1 && cropA.cols > 1) {
        let result = phaseCorrelate(cropA, cropB);
        if (result.confidence > 0.05) {
          sampleDxList.push(result.dx);
          sampleDyList.push(result.dy);
        }
      }
      cropA.delete(); cropB.delete();
    }

    if (sampleDxList.length < 2) {
      hideProgress();
      alert('Could not estimate vehicle direction. Try selecting a frame where the vehicle is clearly visible and moving.');
      return;
    }

    // Filter for significant motion
    let movingDx = [], movingDy = [];
    for (let i = 0; i < sampleDxList.length; i++) {
      if (Math.abs(sampleDxList[i]) > 10 || Math.abs(sampleDyList[i]) > 10) {
        movingDx.push(sampleDxList[i]);
        movingDy.push(sampleDyList[i]);
      }
    }
    if (movingDx.length < 2) {
      movingDx = sampleDxList;
      movingDy = sampleDyList;
    }

    let medDx = median(movingDx);
    let medDy = median(movingDy);
    let angleRad = Math.atan2(medDy, medDx);
    let angleDeg = angleRad * 180 / Math.PI;

    // ── Phase 2: Angle validation ──
    let normalizedAngle = ((angleDeg % 360) + 360) % 360;
    if (normalizedAngle > 180) normalizedAngle -= 360;
    if (Math.abs(normalizedAngle) > 20 && Math.abs(Math.abs(normalizedAngle) - 180) > 20) {
      hideProgress();
      alert(`Estimated vehicle angle is ${angleDeg.toFixed(1)}°. Expected near-horizontal movement.\nCheck that the vehicle ROI is correct.`);
      return;
    }

    updateProgress(0.1, `Direction: ${angleDeg.toFixed(1)}° (dx=${medDx.toFixed(1)}, dy=${medDy.toFixed(1)})`);

    // ── Phase 3: Rotate all frames & store in JS heap ──
    showProgress('Phase 3: Rotating frames...');
    let rotCenter = new cv.Point(roiCx, roiCy);
    let rotMat = cv.getRotationMatrix2D(rotCenter, angleDeg, 1.0);
    let rotatedFrames = []; // JS heap storage: {data, w, h}

    for (let i = 0; i < nFrames; i++) {
      if (state.cancelled) { rotMat.delete(); hideProgress(); return; }

      let src = jsFrameToMat(state.stabilizedFrames[i]);
      let rotated = new cv.Mat();
      cv.warpAffine(src, rotated, rotMat,
        new cv.Size(wFrame, hFrame), cv.INTER_LINEAR, cv.BORDER_REPLICATE,
        new cv.Scalar(0, 0, 0, 255));
      src.delete();

      rotatedFrames.push(matToJsFrame(rotated));
      rotated.delete();

      updateProgress((i + 1) / nFrames, `Rotating frame ${i + 1} / ${nFrames}`);
      if (i % 5 === 0) await yieldToUI();
    }
    rotMat.delete();

    // Expected per-frame dx after rotation
    let rotMedDx = medDx * Math.cos(angleRad) + medDy * Math.sin(angleRad);

    // ── Phase 4: Per-frame displacement via phase correlation ──
    showProgress('Phase 4: Measuring displacement...');
    let dxHistory = [];
    let confidenceHistory = [];
    let fallbackCount = 0;
    let bandMargin = Math.round(Math.abs(rotMedDx)) + 20;
    let by1 = Math.max(0, ry);
    let by2 = Math.min(hFrame, ry + rh);

    for (let i = 0; i < nFrames - 1; i++) {
      if (state.cancelled) { hideProgress(); return; }

      let predictedCx = roiCx + (i - state.tramFrameIdx) * rotMedDx;
      let bx1 = Math.max(0, Math.round(predictedCx - rw / 2 - bandMargin));
      let bx2 = Math.min(wFrame, Math.round(predictedCx + rw / 2 + bandMargin));

      let usedFallback = false;
      let dx = rotMedDx;
      let conf = 0;

      if (bx2 - bx1 < 10 || by2 - by1 < 10) {
        usedFallback = true;
        fallbackCount++;
      } else {
        // Crop directly from JS frames — no full-frame Mat allocation
        let cropA = cropJsFrameToFloat(rotatedFrames[i], bx1, by1, bx2 - bx1, by2 - by1);
        let cropB = cropJsFrameToFloat(rotatedFrames[i + 1], bx1, by1, bx2 - bx1, by2 - by1);

        if (cropA.rows > 1 && cropA.cols > 1) {
          let result = phaseCorrelate(cropA, cropB);
          dx = result.dx;
          conf = result.confidence;
        }
        cropA.delete(); cropB.delete();

        if (conf < 0.05 || Math.abs(dx - rotMedDx) > Math.abs(rotMedDx) * 0.5) {
          usedFallback = true;
          fallbackCount++;
          if (dxHistory.length > 3) {
            dx = median(dxHistory.slice(-5));
          } else {
            dx = rotMedDx;
          }
        }
      }

      dxHistory.push(dx);
      confidenceHistory.push(conf);

      updateProgress((i + 1) / (nFrames - 1), `Displacement ${i + 1} / ${nFrames - 1}`);
      if (i % 5 === 0) await yieldToUI();
    }

    if (dxHistory.length === 0) {
      hideProgress();
      alert('No displacement data computed.');
      return;
    }

    // ── Phase 5: Slice extraction + panorama assembly ──
    // Done entirely with raw pixel data & canvas — no cv.Mat allocations.
    showProgress('Phase 5: Extracting slices...');

    // Compute tram x-position per frame
    let tramXPositions = new Array(nFrames).fill(0);
    tramXPositions[state.tramFrameIdx] = roiCx;
    for (let i = state.tramFrameIdx; i < nFrames - 1; i++) {
      tramXPositions[i + 1] = tramXPositions[i] + dxHistory[i];
    }
    for (let i = state.tramFrameIdx; i > 0; i--) {
      tramXPositions[i - 1] = tramXPositions[i] - dxHistory[i - 1];
    }

    // First pass: compute slice widths and total panorama width
    let sliceInfos = []; // {xStart, sliceWidth}
    let totalPanoWidth = 0;
    for (let i = 0; i < nFrames; i++) {
      let dx = (i < dxHistory.length) ? dxHistory[i] : (dxHistory.length > 0 ? dxHistory[dxHistory.length - 1] : rotMedDx);
      let sliceWidth = Math.max(1, Math.round(Math.abs(dx)));
      let xStart = Math.max(0, roiCx - Math.floor(sliceWidth / 2));
      let xEnd = Math.min(wFrame, xStart + sliceWidth);
      if (xEnd <= xStart) { xStart = Math.max(0, roiCx); xEnd = xStart + 1; }
      sliceWidth = xEnd - xStart;
      sliceInfos.push({ xStart, sliceWidth });
      totalPanoWidth += sliceWidth;
    }

    let medDxFinal = median(dxHistory);
    let avgDx = dxHistory.reduce((a, b) => a + b, 0) / dxHistory.length;
    let avgConf = confidenceHistory.length > 0 ?
      confidenceHistory.reduce((a, b) => a + b, 0) / confidenceHistory.length : 0;

    // Determine frame order (reverse if vehicle moved right)
    let frameOrder = [];
    for (let i = 0; i < nFrames; i++) frameOrder.push(i);
    if (medDxFinal > 0) frameOrder.reverse();

    // Assemble panorama on a canvas using raw pixel data
    let panoCanvas = document.createElement('canvas');
    panoCanvas.width = totalPanoWidth;
    panoCanvas.height = hFrame;
    let panoCtx = panoCanvas.getContext('2d');
    let outX = 0;

    for (let fi = 0; fi < frameOrder.length; fi++) {
      if (state.cancelled) break;
      let i = frameOrder[fi];
      let { xStart, sliceWidth } = sliceInfos[i];
      let frame = rotatedFrames[i]; // JS frame: {data, w, h}

      // Copy vertical strip directly from raw RGBA data to an ImageData
      let stripData = new ImageData(sliceWidth, hFrame);
      let src = frame.data;
      let dst = stripData.data;
      for (let y = 0; y < hFrame; y++) {
        let srcOffset = (y * wFrame + xStart) * 4;
        let dstOffset = y * sliceWidth * 4;
        // Copy one row of the strip
        for (let x = 0; x < sliceWidth * 4; x++) {
          dst[dstOffset + x] = src[srcOffset + x];
        }
      }

      panoCtx.putImageData(stripData, outX, 0);
      outX += sliceWidth;

      updateProgress((fi + 1) / nFrames, `Slicing frame ${fi + 1} / ${nFrames}`);
      if (fi % 10 === 0) await yieldToUI();
    }

    // Free rotated frames (JS heap — just drop references)
    rotatedFrames = null;

    // Rotate 180 if vehicle went right-to-left
    if (Math.abs(angleDeg) > 90) {
      let tmpCanvas = document.createElement('canvas');
      tmpCanvas.width = panoCanvas.width;
      tmpCanvas.height = panoCanvas.height;
      let tmpCtx = tmpCanvas.getContext('2d');
      tmpCtx.translate(tmpCanvas.width, tmpCanvas.height);
      tmpCtx.rotate(Math.PI);
      tmpCtx.drawImage(panoCanvas, 0, 0);
      panoCanvas = tmpCanvas;
      panoCtx = tmpCtx;
    }

    // Try to enhance with CLAHE; if WASM OOMs, show raw panorama
    let finalCanvas = panoCanvas;
    try {
      let panoImageData = panoCtx.getImageData(0, 0, panoCanvas.width, panoCanvas.height);
      let panoMat = cv.matFromImageData(panoImageData);
      let enhanced = enhanceFrame(panoMat);
      panoMat.delete();

      finalCanvas = document.createElement('canvas');
      finalCanvas.width = enhanced.cols;
      finalCanvas.height = enhanced.rows;
      cv.imshow(finalCanvas, enhanced);
      enhanced.delete();
    } catch (enhErr) {
      console.warn('Panorama enhancement failed (using raw):', cvErr(enhErr));
      // finalCanvas stays as panoCanvas — unenhanced but still valid
    }

    showPanoramaModalFromCanvas(finalCanvas, {
      frames: nFrames,
      angle: angleDeg,
      medDx: medDxFinal,
      avgDx: avgDx,
      avgConf: avgConf,
      fallbacks: fallbackCount,
      sliceCount: nFrames,
    });

  } catch (err) {
    console.error('Panorama error:', cvErr(err));
    alert('Panorama generation failed: ' + cvErr(err));
  } finally {
    hideProgress();
  }
}

// ============================================================
//  Panorama modal
// ============================================================

function showPanoramaModalFromCanvas(srcCanvas, stats) {
  dom.canvasPanorama.width = srcCanvas.width;
  dom.canvasPanorama.height = srcCanvas.height;
  let ctx = dom.canvasPanorama.getContext('2d');
  ctx.drawImage(srcCanvas, 0, 0);

  dom.panoramaStats.textContent =
    `Frames: ${stats.frames} · Rotation: ${stats.angle.toFixed(1)}°\n` +
    `Median DX: ${stats.medDx.toFixed(2)}px · Avg DX: ${stats.avgDx.toFixed(2)}px\n` +
    `Avg confidence: ${stats.avgConf.toFixed(4)} · Fallbacks: ${stats.fallbacks}/${stats.frames - 1}\n` +
    `Slices: ${stats.sliceCount}`;

  dom.panoramaModal.classList.remove('hidden');
}

function closePanoramaModal() {
  dom.panoramaModal.classList.add('hidden');
}

function savePanorama() {
  const canvas = dom.canvasPanorama;
  const link = document.createElement('a');
  link.download = 'panorama.png';
  link.href = canvas.toDataURL('image/png');
  link.click();
}

// ============================================================
//  Utility functions
// ============================================================

// Crop a region from a JS frame {data, w, h} directly into a CV_32F grayscale Mat.
// Only the small crop enters WASM — no full-frame Mat allocation.
function cropJsFrameToFloat(frame, x, y, cw, ch) {
  x = Math.max(0, Math.min(x, frame.w - 1));
  y = Math.max(0, Math.min(y, frame.h - 1));
  cw = Math.min(cw, frame.w - x);
  ch = Math.min(ch, frame.h - y);
  if (cw < 1 || ch < 1) {
    return cv.Mat.zeros(1, 1, cv.CV_32F);
  }

  // Extract grayscale float directly from RGBA bytes
  let floatMat = new cv.Mat(ch, cw, cv.CV_32F);
  let dst = floatMat.data32F;
  let src = frame.data;
  let srcW = frame.w;
  for (let row = 0; row < ch; row++) {
    let srcRowOff = ((y + row) * srcW + x) * 4;
    let dstRowOff = row * cw;
    for (let col = 0; col < cw; col++) {
      let off = srcRowOff + col * 4;
      // ITU-R BT.601 luma: 0.299R + 0.587G + 0.114B
      dst[dstRowOff + col] = src[off] * 0.299 + src[off + 1] * 0.587 + src[off + 2] * 0.114;
    }
  }
  return floatMat;
}

// Crop from a cv.Mat (RGBA) — used when we already have a Mat in hand.
function cropAndConvertToFloat(mat, x, y, w, h) {
  x = Math.max(0, Math.min(x, mat.cols - 1));
  y = Math.max(0, Math.min(y, mat.rows - 1));
  w = Math.min(w, mat.cols - x);
  h = Math.min(h, mat.rows - y);
  if (w < 1 || h < 1) {
    return cv.Mat.zeros(1, 1, cv.CV_32F);
  }

  let cropped = mat.roi(new cv.Rect(x, y, w, h));
  let gray = new cv.Mat();
  cv.cvtColor(cropped, gray, cv.COLOR_RGBA2GRAY);
  let floatMat = new cv.Mat();
  gray.convertTo(floatMat, cv.CV_32F);
  gray.delete();
  return floatMat;
}

function median(arr) {
  if (arr.length === 0) return 0;
  let sorted = [...arr].sort((a, b) => a - b);
  let mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}
