# Slit-Scan Panorama — Web App

A browser-based tool for creating panoramic images of moving vehicles (trams, trains, buses) from handheld video footage using the **slit-scan** technique. All processing runs **locally in your browser** — your video never leaves your machine.

![workflow](https://img.shields.io/badge/no_server-100%25_client--side-brightgreen)
![opencv](https://img.shields.io/badge/powered_by-OpenCV.js-blue)

## How It Works

Slit-scan photography captures a thin vertical strip from each video frame and stitches them side-by-side. When a vehicle passes through the frame, each strip captures a different section of the vehicle, building up a complete panoramic image — even from a shaky handheld phone video.

The pipeline:

1. **Video stabilization** — Aligns all frames to a reference using ORB feature matching on a user-selected static background region.
2. **Direction estimation** — Uses phase correlation to determine the vehicle's direction of travel.
3. **Frame rotation** — Rotates all frames so the vehicle moves perfectly horizontally.
4. **Per-frame displacement** — Measures exact pixel displacement between consecutive frames using phase correlation.
5. **Slice extraction** — Extracts a vertical strip from each frame at a fixed slit position, with width proportional to displacement.
6. **Assembly** — Concatenates all slices into the final panorama, with contrast/saturation enhancement.

## Quick Start

### Option 1: Just open it

Open `index.html` directly in a modern browser (Chrome, Firefox, Edge). The app loads OpenCV.js from a CDN, so you need an internet connection on first load.

### Option 2: Local server (recommended)

A local HTTP server avoids any potential cross-origin issues:

```bash
# Python 3
cd web/
python -m http.server 8000

# Node.js
npx serve .
```

Then open [http://localhost:8000](http://localhost:8000).

## Step-by-Step Usage

### 1. Load a Video

- **Drag and drop** a video file onto the landing page, or click **Choose File**.
- MP4 (H.264) is recommended for best browser compatibility. WebM and MOV also work in most browsers.
- Short clips (5–15 seconds) of a vehicle passing by work best.

### 2. Set the Frame Range

- Use the **slider** or **arrow keys** to navigate through the video.
- Click **Set Start** on a frame just before the vehicle enters.
- Click **Set End** on a frame just after the vehicle exits.

### 3. Select Background ROI

- **Left-click and drag** on the video to draw a rectangle over a **static background area** (buildings, ground, sky — anything that doesn't move).
- This region is used for feature-based stabilization. Choose an area with good texture (avoid blank sky or uniform walls).

### 4. Stabilize

- Click **Stabilize Frames**. This extracts each frame and aligns them using ORB feature matching against the first frame.
- A progress indicator shows the current status. Processing time depends on the number of frames and video resolution.

### 5. Select Vehicle ROI

- In the **Stabilized View**, navigate to a frame where the vehicle is clearly visible.
- **Left-click and drag** to draw a rectangle over the vehicle.
- The ROI should cover the vehicle's full height and approximate width.

### 6. (Optional) Set Slit Position

- By default, the slit is placed at the center of the vehicle ROI.
- **Right-click** anywhere on the stabilized view to override the slit position (shown as a cyan dashed line).

### 7. Generate Panorama

- Click **Generate Panorama**. The app will:
  1. Estimate the vehicle's direction of travel
  2. Rotate all frames to make motion horizontal
  3. Measure per-frame displacement via phase correlation
  4. Extract and assemble vertical slices
- The result opens in a modal with statistics.

### 8. Save

- Click **Save Image** to download the panorama as a PNG file.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `←` / `→` | Step one frame backward/forward on the focused slider |

## Tips for Best Results

- **Steady-ish footage**: The stabilizer can handle moderate handheld shake, but a tripod or resting the phone on a surface helps.
- **Vehicle fills the frame vertically**: The more of the frame height the vehicle occupies, the better the panorama.
- **Consistent speed**: Vehicles moving at a constant speed produce the most uniform panoramas.
- **Good lighting**: Better lighting = better feature matching = better stabilization.
- **Short clips**: 200–500 frames is the sweet spot. Very long clips may use a lot of memory.

## Technical Notes

### Browser Compatibility

| Browser | Status |
|---------|--------|
| Chrome 90+ | Fully supported |
| Firefox 90+ | Fully supported |
| Edge 90+ | Fully supported |
| Safari 15+ | Should work (less tested) |

### Memory Usage

All stabilized frames are held in memory as uncompressed RGBA bitmaps. For a 1080p video:
- ~8 MB per frame
- 300 frames ≈ 2.4 GB

For long or high-resolution clips, consider:
- Selecting a shorter frame range
- Using a lower-resolution video

### Differences from the Python Version

| Feature | Python (main.py) | Web (this) |
|---------|-------------------|------------|
| Feature detector | SIFT | ORB (available in standard OpenCV.js) |
| Feature matcher | BFMatcher (L2) | BFMatcher (Hamming) |
| Video decoding | OpenCV VideoCapture | HTML5 `<video>` + Canvas |
| Frame seeking | Frame-accurate | Time-based (minor imprecision possible) |
| UI framework | PyQt5 | Vanilla HTML/CSS/JS |
| Phase correlation | `cv2.phaseCorrelate` | Custom implementation using DFT |
| Processing | Native (fast) | WebAssembly (slower, but no install needed) |

### Offline Use

To use without an internet connection, download `opencv.js` from the [OpenCV releases](https://docs.opencv.org/4.9.0/opencv.js), place it in this directory, and update the `<script>` tag in `index.html` to point to the local file:

```html
<script async src="opencv.js" onload="onOpenCvLoaded()" type="text/javascript"></script>
```

## Architecture

```
web/
├── index.html    — Page structure and layout
├── style.css     — Dark theme styling
├── app.js        — All application logic (~600 lines)
│   ├── OpenCV bootstrap & initialization
│   ├── Video loading & frame extraction
│   ├── Canvas display & ROI selection
│   ├── Image enhancement (CLAHE + saturation)
│   ├── Stabilization (ORB + affine transform)
│   ├── Phase correlation (custom DFT-based)
│   ├── Panorama generation pipeline
│   └── UI state management
└── README.md     — This file
```

## Credits

- **OpenCV.js** — Computer vision in the browser via WebAssembly
- **Created by [Claude](https://claude.ai/)** (Anthropic) — AI-assisted development

---

*This is the web companion to the Python desktop app (`main.py` in the parent directory). Both implement the same slit-scan algorithm; the Python version uses SIFT features and native OpenCV for faster processing, while this web version trades some speed for zero-install convenience.*
