# eye/detection/yolo_client.py
"""
YOLO 检测客户端 - 支持本地模型、远程服务器、YOLO-World三种模式

YOLO-World 是开放词汇检测模型，可以通过自然语言提示词检测任意物体。
这是实现"LLM修改检测目标"功能的核心组件。

基于原 app/infrastructure/yolo_client.py 完整重构
"""
import cv2
import json
import logging
import asyncio
import time
import hashlib
from abc import ABC, abstractmethod
from typing import List, Dict, Tuple, Set, Optional
import numpy as np

from config.settings import YoloConfig


class BaseYoloClient(ABC):
    """YOLO 客户端基类"""

    def __init__(self):
        self.last_send_time = 0
        self.interval = 1.0 / max(1, YoloConfig.DETECT_FPS)
        self.nms_threshold = YoloConfig.NMS_THRESHOLD
        self.confidence_threshold = YoloConfig.CONFIDENCE_THRESHOLD
        # 当前检测目标列表（用于开放词汇模型）
        self.current_targets: List[str] = YoloConfig.DEFAULT_TARGETS.copy()

    @abstractmethod
    async def _detect(self, frame: np.ndarray) -> List[Dict]:
        """子类实现具体的检测逻辑"""
        pass

    def update_prompt(self, targets: List[str]) -> bool:
        """
        更新检测目标（开放词汇检测的核心接口）

        Args:
            targets: 要检测的目标列表，如 ["person", "fire", "knife", "package"]

        Returns:
            是否更新成功
        """
        self.current_targets = targets
        logging.info(f"🎯 [YOLO] 检测目标更新: {targets}")
        return True

    async def detect_async(
            self,
            frame: np.ndarray,
            alert_targets: Set[str] = None
    ) -> Tuple[List[Dict], np.ndarray]:
        """
        异步检测接口

        Args:
            frame: 输入图像
            alert_targets: 需要标红的高危目标名称集合

        Returns:
            (检测结果列表, 绘制后的图像)
        """
        if alert_targets is None:
            alert_targets = set()

        # 频率控制
        now = time.time()
        if now - self.last_send_time < self.interval:
            return [], frame
        self.last_send_time = now

        try:
            # 执行检测
            raw_detections = await self._detect(frame)

            # 后处理：NMS + 绘制
            final_detections = self._apply_nms(raw_detections)
            plotted_frame = self._draw_boxes(frame, final_detections, alert_targets)

            return final_detections, plotted_frame

        except Exception as e:
            logging.error(f"❌ [YOLO] 检测错误: {e}")
            return [], frame

    def _apply_nms(self, detections: List[Dict]) -> List[Dict]:
        """非极大值抑制"""
        if not detections:
            return []

        # 按类别分组
        grouped = {}
        for det in detections:
            cls = det['class']
            if cls not in grouped:
                grouped[cls] = []
            grouped[cls].append(det)

        # 对每个类别单独做 NMS
        results = []
        for cls, dets in grouped.items():
            dets.sort(key=lambda x: x['confidence'], reverse=True)
            keep = []
            while dets:
                best = dets.pop(0)
                keep.append(best)
                dets = [d for d in dets if self._calculate_iou(best['box'], d['box']) < self.nms_threshold]
            results.extend(keep)

        return results

    def _calculate_iou(self, boxA: List[int], boxB: List[int]) -> float:
        """计算 IoU"""
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])

        interArea = max(0, xB - xA) * max(0, yB - yA)
        if interArea == 0:
            return 0

        boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])

        return interArea / float(boxAArea + boxBArea - interArea)

    def _draw_boxes(
            self,
            frame: np.ndarray,
            detections: List[Dict],
            alert_targets: Set[str]
    ) -> np.ndarray:
        """在图像上绘制检测框"""
        plotted = frame.copy()

        for det in detections:
            x1, y1, x2, y2 = det['box']
            name = det['class']
            conf = det['confidence']

            # 高危目标用红色，普通目标用随机色
            if name in alert_targets:
                color = (0, 0, 255)  # 红色
                label_prefix = "⚠️ "
            else:
                color = self._get_color_by_name(name)
                label_prefix = ""

            # 绘制框
            cv2.rectangle(plotted, (x1, y1), (x2, y2), color, 2)

            # 绘制标签背景
            label = f"{label_prefix}{name} {conf:.2f}"
            (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            cv2.rectangle(plotted, (x1, y1 - 20), (x1 + w, y1), color, -1)

            # 绘制文字
            cv2.putText(plotted, label, (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        return plotted

    @staticmethod
    def _get_color_by_name(name: str) -> Tuple[int, int, int]:
        """根据名字生成固定颜色"""
        hash_obj = hashlib.md5(name.encode())
        hex_dig = hash_obj.hexdigest()
        r = int(hex_dig[0:2], 16)
        g = int(hex_dig[2:4], 16)
        b = int(hex_dig[4:6], 16)
        return (b, g, r)  # BGR 格式


class LocalYoloClient(BaseYoloClient):
    """
    本地 YOLO 客户端 - 使用 ultralytics 库

    支持的模型：
    - yolov8n.pt (标准 COCO 80类)
    - yolov8s.pt (标准 COCO 80类)
    - yolov8n-world.pt (YOLO-World 开放词汇)
    - yolov8s-world.pt (YOLO-World 开放词汇)
    """

    def __init__(self, model_path: str = None):
        super().__init__()
        self.model = None
        self.model_path = model_path or YoloConfig.LOCAL_MODEL_PATH
        self.is_world_model = "world" in self.model_path.lower()
        
        # 为CPU密集型YOLO推理创建专用执行器
        import concurrent.futures
        self._executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=2  # 不要过度并行化推理
        )
        
        self._load_model()

    def _load_model(self):
        """加载 YOLO 模型"""
        try:
            from ultralytics import YOLO

            logging.info(f"📦 [YOLO] 正在加载本地模型: {self.model_path}")
            self.model = YOLO(self.model_path)

            # 如果是 YOLO-World 模型，设置初始检测类别
            if self.is_world_model:
                logging.info("🌍 [YOLO-World] 开放词汇模型已加载")
                self.model.set_classes(self.current_targets)

            # 预热模型（第一次推理会比较慢）
            dummy = np.zeros((640, 640, 3), dtype=np.uint8)
            self.model(dummy, verbose=False)

            logging.info(f"✅ [YOLO] 本地模型加载完成 (World={self.is_world_model})")

        except ImportError:
            logging.error("❌ [YOLO] 请安装 ultralytics: pip install ultralytics")
            raise
        except Exception as e:
            logging.error(f"❌ [YOLO] 模型加载失败: {e}")
            raise

    def update_prompt(self, targets: List[str]) -> bool:
        """
        更新检测目标

        对于 YOLO-World 模型，这会真正改变检测的类别
        对于标准 YOLO 模型，只记录目标（用于过滤）
        """
        self.current_targets = targets

        if self.is_world_model and self.model:
            try:
                # YOLO-World 核心功能：动态设置检测类别
                self.model.set_classes(targets)
                logging.info(f"🎯 [YOLO-World] 检测目标已更新: {targets}")
                return True
            except Exception as e:
                logging.error(f"❌ [YOLO-World] 更新检测目标失败: {e}")
                return False
        else:
            # 标准 YOLO 模型只记录目标用于后续过滤
            logging.info(f"📝 [YOLO] 检测目标记录（标准模型不支持动态更新）: {targets}")
            return True

    async def _detect(self, frame: np.ndarray) -> List[Dict]:
        """执行本地检测"""
        if self.model is None:
            return []

        loop = asyncio.get_running_loop()
        
        try:
            # 使用ProcessPoolExecutor实现真正的并行处理
            # 添加超时以防止无限期阻塞
            detections = await asyncio.wait_for(
                loop.run_in_executor(self._executor, self._inference, frame),
                timeout=2.0  # 快速失败
            )
            return detections
        except asyncio.TimeoutError:
            logging.error("YOLO推理超时 - 跳过帧")
            return []
    
    def _inference(self, frame: np.ndarray) -> List[Dict]:
        """用于ProcessPoolExecutor中的推理方法"""
        results = self.model(frame, verbose=False, conf=self.confidence_threshold)
        detections = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            for i in range(len(boxes)):
                box = boxes.xyxy[i].cpu().numpy()
                conf = float(boxes.conf[i].cpu().numpy())
                cls_id = int(boxes.cls[i].cpu().numpy())
                cls_name = result.names[cls_id]

                # 对于非 World 模型，过滤非目标类别
                if not self.is_world_model and self.current_targets:
                    if cls_name.lower() not in [t.lower() for t in self.current_targets]:
                        continue

                detections.append({
                    "class": cls_name,
                    "confidence": conf,
                    "box": [int(box[0]), int(box[1]), int(box[2]), int(box[3])]
                })

        return detections


class YoloWorldClient(BaseYoloClient):
    """
    YOLO-World 专用客户端

    支持开放词汇检测，可以通过自然语言描述检测任意物体
    这是实现"AI对话调整检测需求"的核心组件
    """

    def __init__(self, model_path: str = None):
        super().__init__()
        self.model = None
        self.model_path = model_path or "yolov8s-world.pt"
        self._load_model()

    def _load_model(self):
        """加载 YOLO-World 模型"""
        try:
            from ultralytics import YOLO

            logging.info(f"🌍 [YOLO-World] 正在加载开放词汇模型: {self.model_path}")
            self.model = YOLO(self.model_path)

            # 设置初始检测类别
            self.model.set_classes(self.current_targets)

            # 预热
            dummy = np.zeros((640, 640, 3), dtype=np.uint8)
            self.model(dummy, verbose=False)

            logging.info("✅ [YOLO-World] 开放词汇模型加载完成")

        except Exception as e:
            logging.error(f"❌ [YOLO-World] 模型加载失败: {e}")
            logging.info("💡 提示: 请确保安装了 ultralytics>=8.1.0")
            raise

    def update_prompt(self, targets: List[str]) -> bool:
        """
        更新检测目标（核心功能）

        Args:
            targets: 要检测的目标列表
                    支持自然语言描述，如 ["穿红衣服的人", "包裹", "火焰"]
        """
        if not self.model:
            return False

        try:
            self.current_targets = targets
            self.model.set_classes(targets)
            logging.info(f"🎯 [YOLO-World] 检测目标更新成功: {targets}")
            return True
        except Exception as e:
            logging.error(f"❌ [YOLO-World] 检测目标更新失败: {e}")
            return False

    async def _detect(self, frame: np.ndarray) -> List[Dict]:
        """执行开放词汇检测"""
        if self.model is None:
            return []

        loop = asyncio.get_running_loop()

        def _inference():
            results = self.model(frame, verbose=False, conf=self.confidence_threshold)
            detections = []

            for result in results:
                boxes = result.boxes
                if boxes is None:
                    continue

                for i in range(len(boxes)):
                    box = boxes.xyxy[i].cpu().numpy()
                    conf = float(boxes.conf[i].cpu().numpy())
                    cls_id = int(boxes.cls[i].cpu().numpy())
                    cls_name = result.names[cls_id]

                    detections.append({
                        "class": cls_name,
                        "confidence": conf,
                        "box": [int(box[0]), int(box[1]), int(box[2]), int(box[3])]
                    })

            return detections

        return await loop.run_in_executor(None, _inference)


class RemoteYoloClient(BaseYoloClient):
    """
    远程 YOLO 客户端 - 通过 WebSocket 连接 GPU 服务器
    支持远程 YOLO-World 服务
    """

    def __init__(self):
        super().__init__()
        self.ws = None

    async def _connect(self) -> bool:
        """连接到远程服务器"""
        try:
            import websockets
            self.ws = await websockets.connect(YoloConfig.WS_URL, ping_interval=None)
            logging.info("✅ [YOLO] 已连接到远程 GPU 服务器")
            return True
        except Exception as e:
            logging.error(f"❌ [YOLO] 远程连接失败: {e}")
            self.ws = None
            return False

    async def _detect(self, frame: np.ndarray) -> List[Dict]:
        """远程检测"""
        if self.ws is None:
            if not await self._connect():
                return []

        try:
            # 预处理：缩放 + 编码
            loop = asyncio.get_running_loop()
            buffer_bytes, scale = await loop.run_in_executor(None, self._preprocess, frame)

            if buffer_bytes is None:
                return []

            # 发送并等待响应
            await self.ws.send(buffer_bytes)
            response = await asyncio.wait_for(self.ws.recv(), timeout=2.0)
            raw_detections = json.loads(response)

            # 还原坐标
            detections = []
            for det in raw_detections:
                if det.get('confidence', 0) < self.confidence_threshold:
                    continue

                box = det.get('box', {})
                detections.append({
                    "class": det.get('name', 'obj'),
                    "confidence": det.get('confidence', 0),
                    "box": [
                        int(box.get('x1', 0) / scale),
                        int(box.get('y1', 0) / scale),
                        int(box.get('x2', 0) / scale),
                        int(box.get('y2', 0) / scale)
                    ]
                })

            return detections

        except Exception as e:
            import websockets
            if isinstance(e, (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError, ConnectionRefusedError)):
                self.ws = None
            else:
                logging.error(f"❌ [YOLO] 远程检测错误: {e}")
            return []

    @staticmethod
    def _preprocess(frame: np.ndarray) -> Tuple[Optional[bytes], float]:
        """预处理图像"""
        try:
            h, w = frame.shape[:2]
            scale = 640 / w
            new_h = int(h * scale)
            frame_resized = cv2.resize(frame, (640, new_h))
            _, buffer = cv2.imencode('.jpg', frame_resized, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            return buffer.tobytes(), scale
        except Exception:
            return None, 1.0

    def update_prompt(self, targets: List[str]) -> bool:
        """更新远程服务器的检测目标"""
        self.current_targets = targets
        try:
            import httpx
            resp = httpx.post(YoloConfig.API_URL, json=targets, timeout=5)
            success = resp.status_code == 200
            if success:
                logging.info(f"🎯 [YOLO] 远程检测目标更新成功: {targets}")
            return success
        except Exception as e:
            logging.error(f"❌ [YOLO] 远程目标更新失败: {e}")
            return False

    async def close(self):
        """关闭连接"""
        if self.ws:
            await self.ws.close()
            self.ws = None
            logging.info("🔌 [YOLO] 远程连接已关闭")


def create_yolo_client() -> BaseYoloClient:
    """
    工厂函数：根据配置创建 YOLO 客户端

    优先级：
    1. USE_LOCAL_MODEL=true + 模型包含 "world" → YoloWorldClient
    2. USE_LOCAL_MODEL=true → LocalYoloClient
    3. USE_LOCAL_MODEL=false → RemoteYoloClient
    """
    if YoloConfig.USE_LOCAL_MODEL:
        model_path = YoloConfig.LOCAL_MODEL_PATH

        # 检查是否是 YOLO-World 模型
        if "world" in model_path.lower():
            logging.info("🌍 [YOLO] 使用 YOLO-World 开放词汇模式")
            return YoloWorldClient(model_path)
        else:
            logging.info("🏠 [YOLO] 使用本地标准模型模式")
            return LocalYoloClient(model_path)
    else:
        logging.info("☁️ [YOLO] 使用远程服务器模式")
        return RemoteYoloClient()