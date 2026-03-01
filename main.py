import sys
import os
import cv2
import numpy as np
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QSlider,
    QFileDialog,
    QGroupBox,
    QMessageBox,
    QProgressDialog,
    QCheckBox,
    QSplitter,
    QDialog,
    QScrollArea,
)
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal, pyqtSlot, QSize
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QPalette


def enhance_frame(frame):
    """Enhance contrast and saturation for washed-out phone footage."""
    # Convert to LAB color space for perceptual contrast enhancement
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    # CLAHE on lightness channel — adaptive contrast without blowing highlights
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)

    lab = cv2.merge([l, a, b])
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    # Boost saturation slightly in HSV
    hsv = cv2.cvtColor(enhanced, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.3, 0, 255)
    hsv = hsv.astype(np.uint8)
    enhanced = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    return enhanced


class ROISelector(QLabel):
    roiSelected = pyqtSignal(QRect)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.selection_start = QPoint()
        self.selection_end = QPoint()
        self.is_selecting = False
        self.roi = QRect()
        self.pixmap_item = None

    def setPixmap(self, pixmap):
        self.pixmap_item = pixmap
        # We don't call super().setPixmap(pixmap) because we do custom rendering
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.pixmap_item is not None:
            self.selection_start = event.pos()
            self.selection_end = self.selection_start
            self.is_selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_selecting and self.pixmap_item is not None:
            self.selection_end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.LeftButton
            and self.is_selecting
            and self.pixmap_item is not None
        ):
            self.selection_end = event.pos()
            self.is_selecting = False
            self.update()

            img_rect = self._get_image_rect()
            if img_rect.width() == 0 or img_rect.height() == 0:
                return

            mapped_start = self._map_to_image(self.selection_start, img_rect)
            mapped_end = self._map_to_image(self.selection_end, img_rect)

            x1 = min(mapped_start.x(), mapped_end.x())
            y1 = min(mapped_start.y(), mapped_end.y())
            x2 = max(mapped_start.x(), mapped_end.x())
            y2 = max(mapped_start.y(), mapped_end.y())

            img_w = self.pixmap_item.width()
            img_h = self.pixmap_item.height()

            x1 = max(0, min(x1, img_w - 1))
            y1 = max(0, min(y1, img_h - 1))
            x2 = max(0, min(x2, img_w - 1))
            y2 = max(0, min(y2, img_h - 1))

            self.roi = QRect(QPoint(x1, y1), QPoint(x2, y2))

            if self.roi.width() > 5 and self.roi.height() > 5:
                self.roiSelected.emit(self.roi)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.pixmap_item is None:
            return

        painter = QPainter(self)

        # Draw background and pixmap
        img_rect = self._get_image_rect()
        scaled_pixmap = self.pixmap_item.scaled(
            img_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        painter.drawPixmap(img_rect.topLeft(), scaled_pixmap)

        # Draw selection
        pen = QPen(QColor(255, 0, 0, 255), 2, Qt.SolidLine)
        painter.setPen(pen)

        if self.is_selecting:
            rect = QRect(self.selection_start, self.selection_end).normalized()
            painter.drawRect(rect)
        elif not self.roi.isNull():
            px1 = (
                self.roi.left() * img_rect.width() / self.pixmap_item.width()
                + img_rect.left()
            )
            py1 = (
                self.roi.top() * img_rect.height() / self.pixmap_item.height()
                + img_rect.top()
            )
            pw = self.roi.width() * img_rect.width() / self.pixmap_item.width()
            ph = self.roi.height() * img_rect.height() / self.pixmap_item.height()
            painter.drawRect(QRect(int(px1), int(py1), int(pw), int(ph)))

    def _get_image_rect(self):
        # Calculate the actual displayed rect of the image depending on scale/aspect ratio
        if self.pixmap_item is None:
            return QRect()

        lbl_w = self.width()
        lbl_h = self.height()
        pm_w = self.pixmap_item.width()
        pm_h = self.pixmap_item.height()

        if pm_w == 0 or pm_h == 0:
            return QRect()

        ratio_lbl = lbl_w / lbl_h
        ratio_pm = pm_w / pm_h

        if ratio_lbl > ratio_pm:
            # Label is wider than pixmap, fit height
            h = lbl_h
            w = int(h * ratio_pm)
            x = (lbl_w - w) // 2
            y = 0
        else:
            # Label is taller than pixmap, fit width
            w = lbl_w
            h = int(w / ratio_pm)
            x = 0
            y = (lbl_h - h) // 2

        return QRect(x, y, w, h)

    def _map_to_image(self, p: QPoint, img_rect: QRect) -> QPoint:
        x_rel = p.x() - img_rect.left()
        y_rel = p.y() - img_rect.top()

        # Map to image space
        x_img = (
            int((x_rel / img_rect.width()) * self.pixmap_item.width())
            if img_rect.width() > 0
            else 0
        )
        y_img = (
            int((y_rel / img_rect.height()) * self.pixmap_item.height())
            if img_rect.height() > 0
            else 0
        )
        return QPoint(x_img, y_img)


class PanoramaViewer(QDialog):
    def __init__(self, image: np.ndarray, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Slit-Scan Panorama Result")
        self.resize(1024, 600)
        self.image = image

        layout = QVBoxLayout(self)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)

        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignCenter)

        enhanced = enhance_frame(self.image)
        rgb_image = cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)
        self.img_label.setPixmap(pixmap)

        self.scroll.setWidget(self.img_label)
        layout.addWidget(self.scroll)

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Save Image")
        self.btn_save.clicked.connect(self.save_image)
        btn_layout.addWidget(self.btn_save)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout)

    def save_image(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Panorama", "panorama.jpg", "Images (*.jpg *.png)"
        )
        if file_path:
            cv2.imwrite(file_path, enhance_frame(self.image))
            QMessageBox.information(self, "Success", f"Saved to {file_path}")


class SlitScanApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Slit-Scan Vehicle UI")
        self.resize(1024, 800)

        # State Variables
        self.cap = None
        self.total_frames = 0
        self.current_frame_idx = 0
        self.start_frame = -1
        self.end_frame = -1
        self.bg_roi = None
        self.tram_roi = None
        self.tram_frame_idx = 0
        self.stabilized_frames = []
        self.side_by_side = False

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)

        # 1. Top Controls (Load video & layout toggle)
        top_layout = QHBoxLayout()
        self.btn_load = QPushButton("Load Video")
        self.btn_load.clicked.connect(self.load_video)
        top_layout.addWidget(self.btn_load)

        self.lbl_status = QLabel("Ready")
        top_layout.addWidget(self.lbl_status)

        self.chk_side_by_side = QCheckBox("Side-by-Side View")
        self.chk_side_by_side.stateChanged.connect(self.toggle_layout)
        top_layout.addWidget(self.chk_side_by_side)

        top_layout.addStretch()
        self.main_layout.addLayout(top_layout)

        # Content Splitter (replaces the hardcoded layout for views)
        self.splitter = QSplitter(Qt.Vertical)
        self.main_layout.addWidget(self.splitter, 1)

        # 2. Main View Widget
        self.main_view_widget = QWidget()
        self.main_view_layout = QVBoxLayout(self.main_view_widget)
        self.main_view_layout.setContentsMargins(0, 0, 0, 0)

        self.video_viewer = ROISelector()
        self.video_viewer.setMinimumSize(320, 240)
        self.video_viewer.setStyleSheet("background-color: black;")
        self.video_viewer.roiSelected.connect(self.on_roi_selected)
        self.main_view_layout.addWidget(self.video_viewer, 1)

        self.splitter.addWidget(self.main_view_widget)

        # 3. Timeline / Selection Controls
        timeline_layout = QVBoxLayout()
        nav_group = QGroupBox("Video Navigation")
        nav_layout = QVBoxLayout(nav_group)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self.on_slider_changed)
        nav_layout.addWidget(self.slider)

        btn_box = QHBoxLayout()
        self.btn_start = QPushButton("Set Start Frame")
        self.btn_start.clicked.connect(self.set_start_frame)
        self.lbl_start = QLabel("Start: Not Set")

        self.btn_end = QPushButton("Set End Frame")
        self.btn_end.clicked.connect(self.set_end_frame)
        self.lbl_end = QLabel("End: Not Set")

        btn_box.addWidget(self.btn_start)
        btn_box.addWidget(self.lbl_start)
        btn_box.addStretch()
        btn_box.addWidget(self.btn_end)
        btn_box.addWidget(self.lbl_end)

        nav_layout.addLayout(btn_box)
        timeline_layout.addWidget(nav_group)
        self.main_view_layout.addWidget(nav_group)

        # 4. Stabilization Controls
        stab_group = QGroupBox("Stabilization")
        stab_layout = QHBoxLayout(stab_group)

        self.lbl_roi = QLabel("Background ROI: Not Selected (Draw on video to select)")
        stab_layout.addWidget(self.lbl_roi)

        self.btn_stabilize = QPushButton("Stabilize Frames")
        self.btn_stabilize.setEnabled(False)
        self.btn_stabilize.clicked.connect(self.stabilize_video)
        stab_layout.addWidget(self.btn_stabilize)

        self.main_layout.addWidget(stab_group)

        # 5. Stabilized Frame View
        self.stab_view_widget = QWidget()
        sv_layout = QVBoxLayout(self.stab_view_widget)
        sv_layout.setContentsMargins(0, 0, 0, 0)

        stab_view_group = QGroupBox("Stabilized Output View")
        stab_view_inner_layout = QVBoxLayout(stab_view_group)

        self.stab_viewer = ROISelector()
        self.stab_viewer.setAlignment(Qt.AlignCenter)
        self.stab_viewer.setStyleSheet("background-color: #222;")
        self.stab_viewer.setMinimumSize(320, 240)
        self.stab_viewer.roiSelected.connect(self.on_tram_roi_selected)
        stab_view_inner_layout.addWidget(self.stab_viewer, 1)

        self.slider_stab = QSlider(Qt.Horizontal)
        self.slider_stab.setEnabled(False)
        self.slider_stab.valueChanged.connect(self.on_stab_slider_changed)
        stab_view_inner_layout.addWidget(self.slider_stab)

        self.lbl_tram_roi = QLabel(
            "Tram ROI: Not Selected (Draw over tram in stabilized view)"
        )
        stab_view_inner_layout.addWidget(self.lbl_tram_roi)

        self.btn_panorama = QPushButton("Generate Slit-Scan Panorama")
        self.btn_panorama.setEnabled(False)
        self.btn_panorama.clicked.connect(self.generate_panorama)
        stab_view_inner_layout.addWidget(self.btn_panorama)

        sv_layout.addWidget(stab_view_group)
        self.splitter.addWidget(self.stab_view_widget)

        self.update_ui_state()

    def toggle_layout(self, state):
        self.side_by_side = state == Qt.Checked
        if self.side_by_side:
            self.splitter.setOrientation(Qt.Horizontal)
        else:
            self.splitter.setOrientation(Qt.Vertical)

    def update_ui_state(self):
        has_video = self.cap is not None
        self.slider.setEnabled(has_video)
        self.btn_start.setEnabled(has_video)
        self.btn_end.setEnabled(has_video)

        can_stabilize = (
            has_video
            and self.start_frame != -1
            and self.end_frame != -1
            and self.start_frame <= self.end_frame
            and self.bg_roi is not None
        )
        self.btn_stabilize.setEnabled(can_stabilize)

        has_stabilized = len(self.stabilized_frames) > 0
        self.slider_stab.setEnabled(has_stabilized)

        can_pano = has_stabilized and self.tram_roi is not None
        if hasattr(self, "btn_panorama"):
            self.btn_panorama.setEnabled(can_pano)

    def load_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "", "Video Files (*.mp4 *.avi *.mov *.mkv)"
        )
        if file_path:
            if self.cap is not None:
                self.cap.release()
            self.cap = cv2.VideoCapture(file_path)
            if not self.cap.isOpened():
                QMessageBox.critical(self, "Error", "Could not open video file.")
                self.cap = None
                return

            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.slider.setRange(0, max(0, self.total_frames - 1))
            self.slider.setValue(0)
            self.start_frame = -1
            self.end_frame = -1
            self.bg_roi = None
            self.tram_roi = None
            self.tram_frame_idx = 0
            self.stabilized_frames = []
            self.video_viewer.roi = QRect()
            if hasattr(self, "stab_viewer"):
                self.stab_viewer.roi = QRect()

            self.lbl_status.setText(f"Loaded: {file_path}")
            self.lbl_start.setText("Start: Not Set")
            self.lbl_end.setText("End: Not Set")
            self.lbl_roi.setText(
                "Background ROI: Not Selected (Draw on video to select)"
            )
            if hasattr(self, "lbl_tram_roi"):
                self.lbl_tram_roi.setText(
                    "Tram ROI: Not Selected (Draw over tram in stabilized view)"
                )

            self.show_frame(0)
            self.update_ui_state()

    def set_start_frame(self):
        self.start_frame = self.current_frame_idx
        self.lbl_start.setText(f"Start: {self.start_frame}")
        self.update_ui_state()

    def set_end_frame(self):
        self.end_frame = self.current_frame_idx
        self.lbl_end.setText(f"End: {self.end_frame}")
        self.update_ui_state()

    def on_roi_selected(self, roi: QRect):
        self.bg_roi = roi
        self.lbl_roi.setText(
            f"Background ROI: [x={roi.x()}, y={roi.y()}, w={roi.width()}, h={roi.height()}]"
        )
        self.update_ui_state()

    def on_tram_roi_selected(self, roi: QRect):
        self.tram_roi = roi
        self.tram_frame_idx = self.slider_stab.value()
        self.lbl_tram_roi.setText(
            f"Tram ROI: [x={roi.x()}, y={roi.y()}, w={roi.width()}, h={roi.height()}] @ frame {self.tram_frame_idx}"
        )
        self.update_ui_state()

    def on_slider_changed(self, value):
        self.show_frame(value)

    def show_frame(self, frame_idx):
        if self.cap is None:
            return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        if ret:
            self.current_frame_idx = frame_idx
            frame = enhance_frame(frame)
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)
            self.video_viewer.setPixmap(pixmap)
            self.video_viewer.update()

    def on_stab_slider_changed(self, value):
        if 0 <= value < len(self.stabilized_frames):
            frame = self.stabilized_frames[value]
            frame = enhance_frame(frame)
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)

            # CRITICAL FIX: Do NOT pre-scale the pixmap before passing it to ROISelector!
            # The ROISelector maps mouse coordinates based on the pixel dimensions of the pixmap
            # it receives vs its screen rect. Passing a scaled pixmap ruins the coordinate math
            # and returns tiny y-values (the sky) instead of the bottom (the tram).
            self.stab_viewer.setPixmap(pixmap)
            self.stab_viewer.update()

    def stabilize_video(self):
        if (
            self.start_frame < 0
            or self.end_frame < self.start_frame
            or self.bg_roi is None
        ):
            return

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.start_frame)
        ret, ref_frame = self.cap.read()
        if not ret:
            QMessageBox.critical(self, "Error", "Could not read reference start frame.")
            return

        # Prepare SIFT
        sift = cv2.SIFT_create()
        ref_gray = cv2.cvtColor(ref_frame, cv2.COLOR_BGR2GRAY)

        # Create mask
        mask = np.zeros_like(ref_gray)
        rx, ry, rw, rh = (
            self.bg_roi.x(),
            self.bg_roi.y(),
            self.bg_roi.width(),
            self.bg_roi.height(),
        )
        mask[ry : ry + rh, rx : rx + rw] = 255

        kp_ref, des_ref = sift.detectAndCompute(ref_gray, mask)

        if des_ref is None or len(kp_ref) < 4:
            QMessageBox.warning(
                self,
                "Warning",
                "Not enough features found in ROI. Please select a larger or more textured background area.",
            )
            return

        bf = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
        self.stabilized_frames = []

        total_to_process = self.end_frame - self.start_frame + 1
        progress = QProgressDialog(
            "Stabilizing frames...", "Cancel", 0, total_to_process, self
        )
        progress.setWindowModality(Qt.WindowModal)

        for i in range(total_to_process):
            if progress.wasCanceled():
                break

            frame_idx = self.start_frame + i
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, curr_frame = self.cap.read()
            if not ret:
                break

            curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
            kp_curr, des_curr = sift.detectAndCompute(curr_gray, None)

            if des_curr is not None:
                matches = bf.knnMatch(des_curr, des_ref, k=2)
                good = []
                for match_res in matches:
                    if len(match_res) == 2:
                        m, n = match_res
                        if m.distance < 0.7 * n.distance:
                            good.append(m)
                    elif len(match_res) == 1:
                        good.append(match_res[0])
            else:
                good = []

            if len(good) >= 4:
                src_pts = np.float32([kp_curr[m.queryIdx].pt for m in good]).reshape(
                    -1, 1, 2
                )
                dst_pts = np.float32([kp_ref[m.trainIdx].pt for m in good]).reshape(
                    -1, 1, 2
                )

                M, inliers = cv2.estimateAffinePartial2D(
                    src_pts, dst_pts, method=cv2.RANSAC
                )
            else:
                M = None

            if M is None:
                # Fallback to no movement if matching fails
                M = np.eye(2, 3, dtype=np.float32)

            h_frm, w_frm = curr_frame.shape[:2]
            stab_frame = cv2.warpAffine(curr_frame, M, (w_frm, h_frm))
            self.stabilized_frames.append(stab_frame)

            progress.setValue(i + 1)

        progress.setValue(total_to_process)

        if len(self.stabilized_frames) > 0:
            self.slider_stab.setRange(0, len(self.stabilized_frames) - 1)
            self.slider_stab.setValue(0)
            self.on_stab_slider_changed(0)

            # Save stabilized frames for offline debugging
            stab_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stabilized_frames.npz")
            try:
                np.savez_compressed(stab_path, *self.stabilized_frames)
                print(f"Saved {len(self.stabilized_frames)} stabilized frames to {stab_path}")
            except Exception as e:
                print(f"Could not save stabilized frames: {e}")

        self.update_ui_state()

    def generate_panorama(self):
        if not self.stabilized_frames or self.tram_roi is None:
            return

        n_frames = len(self.stabilized_frames)
        h_frame, w_frame = self.stabilized_frames[0].shape[:2]

        rx, ry, rw, rh = (
            self.tram_roi.x(),
            self.tram_roi.y(),
            self.tram_roi.width(),
            self.tram_roi.height(),
        )
        roi_cx = rx + rw // 2
        roi_cy = ry + rh // 2

        debug_log = []
        debug_log.append(f"TRAM ROI x:{rx} y:{ry} w:{rw} h:{rh}")
        debug_log.append(f"ROI center: ({roi_cx}, {roi_cy})")
        debug_log.append(f"Tram frame idx: {self.tram_frame_idx}")
        debug_log.append(f"Total frames: {n_frames}")

        # ── Phase 1: Direction estimation ──
        # Use phase correlation on ~10 frame pairs near tram_frame_idx
        progress = QProgressDialog(
            "Phase 1: Estimating tram direction...",
            "Cancel",
            0,
            5,
            self,
        )
        progress.setWindowModality(Qt.WindowModal)

        sample_dx_list = []
        sample_dy_list = []
        half_window = 5
        center = max(half_window, min(self.tram_frame_idx, n_frames - 1 - half_window))
        sample_pairs = []
        for k in range(center - half_window, center + half_window):
            if 0 <= k < n_frames - 1:
                sample_pairs.append((k, k + 1))

        debug_log.append(f"Direction sample pairs: {len(sample_pairs)}")

        for idx, (a, b) in enumerate(sample_pairs):
            if progress.wasCanceled():
                return
            fa = self.stabilized_frames[a]
            fb = self.stabilized_frames[b]
            # Extract ROI region for phase correlation
            y1 = max(0, ry)
            y2 = min(h_frame, ry + rh)
            x1 = max(0, rx)
            x2 = min(w_frame, rx + rw)
            crop_a = cv2.cvtColor(fa[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY).astype(np.float64)
            crop_b = cv2.cvtColor(fb[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY).astype(np.float64)
            if crop_a.size == 0 or crop_b.size == 0:
                continue
            hann = cv2.createHanningWindow((crop_a.shape[1], crop_a.shape[0]), cv2.CV_64F)
            (sdx, sdy), resp = cv2.phaseCorrelate(crop_a, crop_b, hann)
            debug_log.append(f"  dir sample {a}->{b}: dx={sdx:.3f} dy={sdy:.3f} conf={resp:.4f}")
            if resp > 0.05:
                sample_dx_list.append(sdx)
                sample_dy_list.append(sdy)

        progress.setValue(1)

        if len(sample_dx_list) < 2:
            QMessageBox.warning(
                self,
                "Direction Estimation Failed",
                "Could not estimate tram direction from phase correlation.\n"
                "Try selecting a frame where the tram is clearly visible and moving.",
            )
            return

        # Filter out background-dominated samples (dx≈0) — the tram only occupies
        # the ROI in frames near tram_frame_idx; other pairs see static background.
        # Keep only samples where |dx| > 10 (clearly a moving object).
        moving_dx = []
        moving_dy = []
        for sdx, sdy in zip(sample_dx_list, sample_dy_list):
            if abs(sdx) > 10 or abs(sdy) > 10:
                moving_dx.append(sdx)
                moving_dy.append(sdy)

        debug_log.append(f"Direction samples: {len(sample_dx_list)} total, {len(moving_dx)} with significant motion")

        if len(moving_dx) < 2:
            # Fall back to all samples if filtering removed everything
            moving_dx = sample_dx_list
            moving_dy = sample_dy_list
            debug_log.append("  Warning: falling back to all samples (no significant motion detected)")

        med_dx = float(np.median(moving_dx))
        med_dy = float(np.median(moving_dy))
        angle_rad = np.arctan2(med_dy, med_dx)
        angle_deg = np.degrees(angle_rad)

        debug_log.append(f"Median direction: dx={med_dx:.3f} dy={med_dy:.3f}")
        debug_log.append(f"Angle: {angle_deg:.2f} deg")

        progress.setValue(2)

        # ── Phase 2: Angle validation ──
        # Near-horizontal means angle near 0 or near +/-180
        normalized_angle = angle_deg % 360  # 0..360
        if normalized_angle > 180:
            normalized_angle -= 360  # -180..180
        # Check if close to 0 or +/-180
        if abs(normalized_angle) > 20 and abs(abs(normalized_angle) - 180) > 20:
            QMessageBox.warning(
                self,
                "Unexpected Tram Angle",
                f"Estimated tram movement angle is {angle_deg:.1f} degrees.\n"
                f"Expected near-horizontal movement (close to 0 or 180 degrees).\n"
                f"Check that the tram ROI is correct and the tram is moving horizontally.",
            )
            return

        progress.setValue(3)

        # ── Phase 3: Rotate all frames ──
        progress.setLabelText("Phase 3: Rotating all frames...")
        progress.setMaximum(n_frames)
        progress.setValue(0)

        rot_center = (roi_cx, roi_cy)
        rot_mat = cv2.getRotationMatrix2D(rot_center, angle_deg, 1.0)
        rotated_frames = []

        for i in range(n_frames):
            if progress.wasCanceled():
                return
            rotated = cv2.warpAffine(
                self.stabilized_frames[i],
                rot_mat,
                (w_frame, h_frame),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REPLICATE,
            )
            rotated_frames.append(rotated)
            progress.setValue(i + 1)

        debug_log.append(f"Rotated {len(rotated_frames)} frames by {angle_deg:.2f} deg around ({roi_cx}, {roi_cy})")

        # After rotation, the per-frame horizontal velocity should be close to
        # the magnitude of the Phase 1 vector (rotation removed the dy component).
        # cos(angle_rad) projects the original velocity onto the new horizontal axis.
        rot_med_dx = med_dx * np.cos(angle_rad) + med_dy * np.sin(angle_rad)
        debug_log.append(f"Expected per-frame dx after rotation: {rot_med_dx:.3f}")

        # ── Phase 3b: Save debug crops ──
        # Save a few ROI crops so we can visually verify the ROI lands on the tram
        debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_crops")
        os.makedirs(debug_dir, exist_ok=True)
        debug_frames_to_save = [0, self.tram_frame_idx, n_frames - 1]
        for di in debug_frames_to_save:
            if 0 <= di < n_frames:
                # Predicted tram x in this frame
                pred_x = roi_cx + (di - self.tram_frame_idx) * rot_med_dx
                pred_x_int = int(round(pred_x))
                # Save the rotated frame with the predicted ROI drawn on it
                debug_frame = rotated_frames[di].copy()
                # Draw predicted ROI
                dbx1 = max(0, pred_x_int - rw // 2)
                dbx2 = min(w_frame, pred_x_int + rw // 2)
                dby1 = max(0, ry)
                dby2 = min(h_frame, ry + rh)
                cv2.rectangle(debug_frame, (dbx1, dby1), (dbx2, dby2), (0, 255, 0), 3)
                # Also draw original ROI position for reference
                cv2.rectangle(debug_frame, (rx, ry), (rx + rw, ry + rh), (0, 0, 255), 2)
                cv2.putText(debug_frame, f"frame={di} pred_x={pred_x_int}", (10, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
                cv2.imwrite(os.path.join(debug_dir, f"rotated_frame_{di:04d}.jpg"), debug_frame)
                debug_log.append(f"Saved debug crop for frame {di} (pred_x={pred_x_int})")

        # ── Phase 4: Per-frame displacement via phase correlation ──
        # Use the SAME band position for both frames (like Phase 1).
        # Phase correlation directly measures the tram's displacement.
        # The band is centered at the predicted tram position in frame i.
        progress.setLabelText("Phase 4: Measuring per-frame displacement...")
        progress.setMaximum(n_frames)
        progress.setValue(0)

        dx_history = []
        confidence_history = []
        fallback_count = 0

        # Band: use the ROI height, and a width that covers the tram plus one
        # frame of displacement as margin for phase correlation to work
        band_margin = int(abs(rot_med_dx)) + 20
        by1 = max(0, ry)
        by2 = min(h_frame, ry + rh)

        for i in range(n_frames - 1):
            if progress.wasCanceled():
                return

            # Predict where the tram center is in frame i
            predicted_cx = roi_cx + (i - self.tram_frame_idx) * rot_med_dx

            # Same band position for both frames, centered on the predicted tram
            bx1 = max(0, int(predicted_cx - rw // 2 - band_margin))
            bx2 = min(w_frame, int(predicted_cx + rw // 2 + band_margin))

            used_fallback = False
            dx = rot_med_dx
            conf = 0.0

            if bx2 - bx1 < 10 or by2 - by1 < 10:
                # Tram predicted off-screen, use Phase 1 estimate
                used_fallback = True
                fallback_count += 1
            else:
                crop_a = cv2.cvtColor(rotated_frames[i][by1:by2, bx1:bx2], cv2.COLOR_BGR2GRAY).astype(np.float64)
                crop_b = cv2.cvtColor(rotated_frames[i + 1][by1:by2, bx1:bx2], cv2.COLOR_BGR2GRAY).astype(np.float64)

                if crop_a.size > 0 and crop_a.shape[0] > 1 and crop_a.shape[1] > 1:
                    hann = cv2.createHanningWindow((crop_a.shape[1], crop_a.shape[0]), cv2.CV_64F)
                    (pdx, _pdy), conf = cv2.phaseCorrelate(crop_a, crop_b, hann)
                    dx = pdx  # Direct measurement — same band, so pdx IS the displacement

                # Fallback if confidence too low or dx is wildly off
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
                f"Frame {i}->{i + 1}: dx={dx:.3f} conf={conf:.4f} pred_cx={predicted_cx:.1f} band={bx1}..{bx2}{' [fallback]' if used_fallback else ''}"
            )

            progress.setValue(i + 1)

        progress.setValue(n_frames)

        if len(dx_history) == 0:
            QMessageBox.warning(self, "Error", "No displacement data computed.")
            return

        # ── Phase 5: Slice extraction ──
        # For each frame, extract a full-height vertical strip at the predicted tram center
        progress.setLabelText("Phase 5: Extracting slices...")
        progress.setMaximum(n_frames)
        progress.setValue(0)

        slices = []
        # Compute tram x-position for each frame using refined dx values
        # Start from tram_frame_idx where we know the tram is at roi_cx
        tram_x_positions = [0.0] * n_frames
        tram_x_positions[self.tram_frame_idx] = float(roi_cx)
        for i in range(self.tram_frame_idx, n_frames - 1):
            tram_x_positions[i + 1] = tram_x_positions[i] + dx_history[i]
        for i in range(self.tram_frame_idx, 0, -1):
            tram_x_positions[i - 1] = tram_x_positions[i] - dx_history[i - 1]

        debug_log.append(f"Phase 5: h_frame={h_frame} w_frame={w_frame}")
        debug_log.append(f"  Fixed slit at roi_cx={roi_cx}")

        # Slit-scan: fixed slit at roi_cx, every frame contributes a slice.
        # Background frames show static scenery; tram frames show the tram
        # unrolling as it passes through the slit.
        for i in range(n_frames):
            if progress.wasCanceled():
                return

            frame = rotated_frames[i]

            # Slice width from the dx of this frame
            if i < len(dx_history):
                dx = dx_history[i]
            else:
                dx = dx_history[-1] if dx_history else rot_med_dx

            slice_width = max(1, round(abs(dx)))

            # Full-height vertical strip at FIXED slit position roi_cx
            x_start = max(0, roi_cx - slice_width // 2)
            x_end = min(w_frame, x_start + slice_width)
            if x_end <= x_start:
                x_start = max(0, roi_cx)
                x_end = x_start + 1

            img_slice = frame[0:h_frame, x_start:x_end]

            if img_slice.size > 0:
                slices.append(img_slice)

            progress.setValue(i + 1)

        debug_log.append(f"Phase 5: {len(slices)} slices from {n_frames} frames")
        if slices:
            debug_log.append(f"  First slice shape: {slices[0].shape}, Last slice shape: {slices[-1].shape}")
        progress.setValue(n_frames)

        # Write debug log
        try:
            with open("flow_debug_log.txt", "w") as f:
                f.write("\n".join(debug_log))
        except Exception as e:
            print(f"Could not write log: {e}")

        if len(dx_history) > 0:
            avg_dx = float(np.mean(dx_history))
            med_dx_final = float(np.median(dx_history))
            max_dx = float(np.max(dx_history))
            min_dx = float(np.min(dx_history))
            avg_conf = float(np.mean(confidence_history)) if confidence_history else 0.0

            # Reverse slices if tram moved right (positive dx) so nose appears on the left
            if med_dx_final > 0:
                slices.reverse()

            QMessageBox.information(
                self,
                "Panorama Generation Stats",
                f"Frames processed: {n_frames}\n"
                f"Rotation angle: {angle_deg:.2f} deg\n"
                f"Median DX per frame: {med_dx_final:.2f}px\n"
                f"Average DX per frame: {avg_dx:.2f}px\n"
                f"Min/Max DX: {min_dx:.2f}px / {max_dx:.2f}px\n"
                f"Average confidence: {avg_conf:.4f}\n"
                f"Fallback frames: {fallback_count}/{n_frames - 1}\n\n"
                f"Slices generated: {len(slices)}\n\n"
                f"(Logs written to 'flow_debug_log.txt')",
            )

        if slices:
            panorama = cv2.hconcat(slices)
            viewer = PanoramaViewer(panorama, self)
            viewer.exec_()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SlitScanApp()
    window.show()
    sys.exit(app.exec_())
