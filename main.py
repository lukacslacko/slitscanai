import sys
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
)
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal, pyqtSlot, QSize
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QPalette


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

        self.stab_viewer = QLabel()
        self.stab_viewer.setAlignment(Qt.AlignCenter)
        self.stab_viewer.setStyleSheet("background-color: #222;")
        self.stab_viewer.setMinimumSize(320, 240)
        stab_view_inner_layout.addWidget(self.stab_viewer, 1)

        self.slider_stab = QSlider(Qt.Horizontal)
        self.slider_stab.setEnabled(False)
        self.slider_stab.valueChanged.connect(self.on_stab_slider_changed)
        stab_view_inner_layout.addWidget(self.slider_stab)

        sv_layout.addWidget(stab_view_group)
        self.splitter.addWidget(self.stab_view_widget)

        self.update_ui_state()

    def toggle_layout(self, state):
        self.side_by_side = (state == Qt.Checked)
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
            self.stabilized_frames = []
            self.video_viewer.roi = QRect()

            self.lbl_status.setText(f"Loaded: {file_path}")
            self.lbl_start.setText("Start: Not Set")
            self.lbl_end.setText("End: Not Set")
            self.lbl_roi.setText(
                "Background ROI: Not Selected (Draw on video to select)"
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

    def on_slider_changed(self, value):
        self.show_frame(value)

    def show_frame(self, frame_idx):
        if self.cap is None:
            return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        if ret:
            self.current_frame_idx = frame_idx
            # Convert to QPixmap
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
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)
            # Scale down for viewing if needed, keep Aspect Ratio
            self.stab_viewer.setPixmap(
                pixmap.scaled(
                    self.stab_viewer.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )

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

        self.update_ui_state()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SlitScanApp()
    window.show()
    sys.exit(app.exec_())
