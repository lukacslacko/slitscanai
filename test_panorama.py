"""
Offline panorama generation test script.
Loads stabilized frames from stabilized_frames.npz and runs the panorama algorithm
without needing the GUI.

Usage:
    python test_panorama.py [--roi X,Y,W,H] [--frame-idx N]

If no ROI is specified, uses the last known values from flow_debug_log.txt.
"""

import sys
import os
import cv2
import numpy as np
import argparse


def load_stabilized_frames(path="stabilized_frames.npz"):
    data = np.load(path)
    frames = [data[k] for k in sorted(data.files, key=lambda x: int(x.split("_")[1]))]
    print(f"Loaded {len(frames)} frames, shape={frames[0].shape}")
    return frames


def generate_panorama(frames, rx, ry, rw, rh, tram_frame_idx):
    n_frames = len(frames)
    h_frame, w_frame = frames[0].shape[:2]
    roi_cx = rx + rw // 2
    roi_cy = ry + rh // 2

    debug_log = []
    debug_log.append(f"TRAM ROI x:{rx} y:{ry} w:{rw} h:{rh}")
    debug_log.append(f"ROI center: ({roi_cx}, {roi_cy})")
    debug_log.append(f"Tram frame idx: {tram_frame_idx}")
    debug_log.append(f"Total frames: {n_frames}, frame shape: {h_frame}x{w_frame}")

    # ── Phase 1: Direction estimation ──
    print("Phase 1: Estimating tram direction...")
    sample_dx_list = []
    sample_dy_list = []
    half_window = 5
    center = max(half_window, min(tram_frame_idx, n_frames - 1 - half_window))

    for k in range(center - half_window, center + half_window):
        if 0 <= k < n_frames - 1:
            y1, y2 = max(0, ry), min(h_frame, ry + rh)
            x1, x2 = max(0, rx), min(w_frame, rx + rw)
            crop_a = cv2.cvtColor(frames[k][y1:y2, x1:x2], cv2.COLOR_BGR2GRAY).astype(np.float64)
            crop_b = cv2.cvtColor(frames[k + 1][y1:y2, x1:x2], cv2.COLOR_BGR2GRAY).astype(np.float64)
            if crop_a.size == 0 or crop_b.size == 0:
                continue
            hann = cv2.createHanningWindow((crop_a.shape[1], crop_a.shape[0]), cv2.CV_64F)
            (sdx, sdy), resp = cv2.phaseCorrelate(crop_a, crop_b, hann)
            debug_log.append(f"  dir sample {k}->{k+1}: dx={sdx:.3f} dy={sdy:.3f} conf={resp:.4f}")
            if resp > 0.05:
                sample_dx_list.append(sdx)
                sample_dy_list.append(sdy)

    # Filter out background-dominated samples
    moving_dx = [d for d, _ in zip(sample_dx_list, sample_dy_list) if abs(d) > 10 or abs(_) > 10]
    moving_dy = [d for _, d in zip(sample_dx_list, sample_dy_list) if abs(_) > 10 or abs(d) > 10]
    # Redo filtering properly
    moving_dx, moving_dy = [], []
    for sdx, sdy in zip(sample_dx_list, sample_dy_list):
        if abs(sdx) > 10 or abs(sdy) > 10:
            moving_dx.append(sdx)
            moving_dy.append(sdy)

    debug_log.append(f"Direction samples: {len(sample_dx_list)} total, {len(moving_dx)} with significant motion")

    if len(moving_dx) < 2:
        moving_dx = sample_dx_list
        moving_dy = sample_dy_list

    if len(moving_dx) < 1:
        print("ERROR: No direction samples!")
        return None

    med_dx = float(np.median(moving_dx))
    med_dy = float(np.median(moving_dy))
    angle_rad = np.arctan2(med_dy, med_dx)
    angle_deg = np.degrees(angle_rad)
    print(f"  Median direction: dx={med_dx:.3f} dy={med_dy:.3f}, angle={angle_deg:.2f} deg")
    debug_log.append(f"Median direction: dx={med_dx:.3f} dy={med_dy:.3f}")
    debug_log.append(f"Angle: {angle_deg:.2f} deg")

    # ── Phase 3: Rotate all frames ──
    print("Phase 3: Rotating all frames...")
    rot_center = (roi_cx, roi_cy)
    rot_mat = cv2.getRotationMatrix2D(rot_center, angle_deg, 1.0)
    rotated_frames = []
    for i, f in enumerate(frames):
        rotated = cv2.warpAffine(f, rot_mat, (w_frame, h_frame),
                                  flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        rotated_frames.append(rotated)

    rot_med_dx = med_dx * np.cos(angle_rad) + med_dy * np.sin(angle_rad)
    debug_log.append(f"Expected per-frame dx after rotation: {rot_med_dx:.3f}")
    print(f"  Expected per-frame dx after rotation: {rot_med_dx:.3f}")

    # ── Phase 4: Per-frame displacement ──
    # Same band position for both frames — phase correlation directly measures displacement.
    print("Phase 4: Measuring per-frame displacement...")
    dx_history = []
    confidence_history = []
    fallback_count = 0

    band_margin = int(abs(rot_med_dx)) + 20
    by1 = max(0, ry)
    by2 = min(h_frame, ry + rh)

    for i in range(n_frames - 1):
        predicted_cx = roi_cx + (i - tram_frame_idx) * rot_med_dx

        bx1 = max(0, int(predicted_cx - rw // 2 - band_margin))
        bx2 = min(w_frame, int(predicted_cx + rw // 2 + band_margin))

        used_fallback = False
        dx = rot_med_dx
        conf = 0.0

        if bx2 - bx1 < 10 or by2 - by1 < 10:
            used_fallback = True
            fallback_count += 1
        else:
            crop_a = cv2.cvtColor(rotated_frames[i][by1:by2, bx1:bx2], cv2.COLOR_BGR2GRAY).astype(np.float64)
            crop_b = cv2.cvtColor(rotated_frames[i + 1][by1:by2, bx1:bx2], cv2.COLOR_BGR2GRAY).astype(np.float64)

            if crop_a.size > 0 and crop_a.shape[0] > 1 and crop_a.shape[1] > 1:
                hann = cv2.createHanningWindow((crop_a.shape[1], crop_a.shape[0]), cv2.CV_64F)
                (pdx, _pdy), conf = cv2.phaseCorrelate(crop_a, crop_b, hann)
                dx = pdx

            if conf < 0.05 or abs(dx - rot_med_dx) > abs(rot_med_dx) * 0.5:
                used_fallback = True
                fallback_count += 1
                if len(dx_history) > 3:
                    dx = float(np.median(dx_history[-5:]))
                else:
                    dx = rot_med_dx

        dx_history.append(dx)
        confidence_history.append(conf)
        debug_log.append(
            f"Frame {i}->{i+1}: dx={dx:.3f} conf={conf:.4f} pred_cx={predicted_cx:.1f} band={bx1}..{bx2}{' [fallback]' if used_fallback else ''}"
        )

    print(f"  Fallbacks: {fallback_count}/{n_frames-1}")

    # ── Phase 5: Slice extraction ──
    print("Phase 5: Extracting slices...")
    tram_x_positions = [0.0] * n_frames
    tram_x_positions[tram_frame_idx] = float(roi_cx)
    for i in range(tram_frame_idx, n_frames - 1):
        tram_x_positions[i + 1] = tram_x_positions[i] + dx_history[i]
    for i in range(tram_frame_idx, 0, -1):
        tram_x_positions[i - 1] = tram_x_positions[i] - dx_history[i - 1]

    slices = []
    debug_log.append(f"Phase 5: fixed slit at roi_cx={roi_cx}, all frames")

    for i in range(n_frames):
        frame = rotated_frames[i]

        if i < len(dx_history):
            dx = dx_history[i]
        else:
            dx = dx_history[-1] if dx_history else rot_med_dx

        slice_width = max(1, round(abs(dx)))

        x_start = max(0, roi_cx - slice_width // 2)
        x_end = min(w_frame, x_start + slice_width)
        if x_end <= x_start:
            x_start = max(0, roi_cx)
            x_end = x_start + 1

        img_slice = frame[0:h_frame, x_start:x_end]
        if img_slice.size > 0:
            slices.append(img_slice)

    debug_log.append(f"Phase 5: {len(slices)} slices from {n_frames} frames")
    print(f"  {len(slices)} slices from {n_frames} frames")

    # Write debug log
    with open("flow_debug_log.txt", "w") as f:
        f.write("\n".join(debug_log))

    if not slices:
        print("ERROR: No slices generated!")
        return None

    med_dx_final = float(np.median(dx_history))
    if med_dx_final > 0:
        slices.reverse()

    panorama = cv2.hconcat(slices)
    print(f"  Panorama shape: {panorama.shape}")

    avg_dx = float(np.mean(dx_history))
    avg_conf = float(np.mean(confidence_history))
    print(f"  Stats: med_dx={med_dx_final:.2f} avg_dx={avg_dx:.2f} avg_conf={avg_conf:.4f}")

    return panorama


def main():
    parser = argparse.ArgumentParser(description="Offline panorama generation")
    parser.add_argument("--roi", type=str, help="ROI as X,Y,W,H")
    parser.add_argument("--frame-idx", type=int, default=18, help="Tram frame index")
    parser.add_argument("--input", type=str, default="stabilized_frames.npz", help="Input file")
    parser.add_argument("--output", type=str, default="panorama.jpg", help="Output file")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: {args.input} not found. Run the GUI first to stabilize frames.")
        sys.exit(1)

    frames = load_stabilized_frames(args.input)

    if args.roi:
        rx, ry, rw, rh = [int(x) for x in args.roi.split(",")]
    else:
        # Default ROI - adjust as needed
        rx, ry, rw, rh = 342, 930, 628, 57
        print(f"Using default ROI: x={rx} y={ry} w={rw} h={rh}")

    panorama = generate_panorama(frames, rx, ry, rw, rh, args.frame_idx)

    if panorama is not None:
        cv2.imwrite(args.output, panorama)
        print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
