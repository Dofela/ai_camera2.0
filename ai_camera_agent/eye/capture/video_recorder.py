# eye/capture/video_recorder.py
"""
视频录制器 - 基于old_app的视频保存逻辑重构

功能:
1. 异常事件视频录制
2. 视频文件管理
3. 帧缓冲和编码
"""
import os
import cv2
import time
import logging
import numpy as np
from typing import List, Optional, Tuple
from datetime import datetime
from pathlib import Path

from config.settings import VideoConfig


class VideoRecorder:
    """
    视频录制器
    
    基于 old_app 的 _save_alert_video_sync 逻辑重构，
    适配新的类Agent架构。
    """
    
    def __init__(self, output_dir: str = "video_warning"):
        """
        初始化视频录制器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 视频参数
        self.fps = VideoConfig.TARGET_FPS
        self.jpeg_quality = VideoConfig.JPEG_QUALITY
        
        # 当前录制状态
        self.is_recording = False
        self.current_writer = None
        self.current_filename = None
        self.frame_buffer: List[np.ndarray] = []
        self.max_buffer_size = 100  # 最大缓冲帧数
        
        logging.info(f"🎥 [VideoRecorder] 初始化完成 | 输出目录: {self.output_dir}")
    
    def start_recording(self, event_id: int, frames: List[np.ndarray]) -> Optional[str]:
        """
        开始录制视频
        
        Args:
            event_id: 事件ID
            frames: 初始帧列表
            
        Returns:
            视频文件路径（如果成功）
        """
        if self.is_recording:
            logging.warning("🎥 [VideoRecorder] 已经在录制中")
            return self.current_filename
        
        try:
            # 生成文件名
            timestamp = int(time.time())
            filename = self.output_dir / f"event_{event_id}_{timestamp}.mp4"
            
            # 获取视频参数
            if not frames:
                logging.error("🎥 [VideoRecorder] 没有帧数据")
                return None
            
            height, width = frames[0].shape[:2]
            
            # 创建视频写入器
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(
                str(filename),
                fourcc,
                float(self.fps),
                (width, height)
            )
            
            if not writer.isOpened():
                logging.error(f"🎥 [VideoRecorder] 无法创建视频文件: {filename}")
                return None
            
            # 写入初始帧
            for frame in frames:
                if frame is not None:
                    writer.write(frame.astype(np.uint8))
            
            # 更新状态
            self.is_recording = True
            self.current_writer = writer
            self.current_filename = str(filename)
            self.frame_buffer = frames.copy()
            
            logging.info(f"🎥 [VideoRecorder] 开始录制: {filename}")
            return str(filename)
            
        except Exception as e:
            logging.error(f"❌ [VideoRecorder] 开始录制失败: {e}")
            return None
    
    def add_frame(self, frame: np.ndarray):
        """
        添加帧到视频
        
        Args:
            frame: 视频帧
        """
        if not self.is_recording or self.current_writer is None:
            return
        
        try:
            # 写入帧
            self.current_writer.write(frame.astype(np.uint8))
            
            # 缓冲帧（用于可能的重新编码）
            self.frame_buffer.append(frame.copy())
            if len(self.frame_buffer) > self.max_buffer_size:
                self.frame_buffer.pop(0)
                
        except Exception as e:
            logging.error(f"❌ [VideoRecorder] 添加帧失败: {e}")
    
    def stop_recording(self) -> Optional[str]:
        """
        停止录制
        
        Returns:
            视频文件路径
        """
        if not self.is_recording or self.current_writer is None:
            return None
        
        try:
            # 释放写入器
            self.current_writer.release()
            filename = self.current_filename
            
            # 重置状态
            self.is_recording = False
            self.current_writer = None
            self.current_filename = None
            self.frame_buffer.clear()
            
            # 检查文件大小
            if os.path.exists(filename):
                file_size = os.path.getsize(filename) / (1024 * 1024)  # MB
                logging.info(f"🎥 [VideoRecorder] 录制完成: {filename} ({file_size:.2f} MB)")
            else:
                logging.warning(f"🎥 [VideoRecorder] 视频文件未创建: {filename}")
                return None
            
            return filename
            
        except Exception as e:
            logging.error(f"❌ [VideoRecorder] 停止录制失败: {e}")
            return None
    
    def save_alert_video(self, frames: List[np.ndarray], event_id: int, 
                        fps: Optional[int] = None) -> Optional[str]:
        """
        保存报警视频（同步版本，兼容old_app接口）
        
        Args:
            frames: 帧列表
            event_id: 事件ID
            fps: 帧率（可选）
            
        Returns:
            视频文件路径
        """
        if not frames:
            return None
        
        try:
            # 生成文件名
            timestamp = int(time.time())
            filename = self.output_dir / f"alert_{event_id}_{timestamp}.mp4"
            
            # 获取视频参数
            height, width = frames[0].shape[:2]
            actual_fps = fps or self.fps
            
            # 创建视频写入器
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(
                str(filename),
                fourcc,
                float(actual_fps),
                (width, height)
            )
            
            if not writer.isOpened():
                logging.error(f"🎥 [VideoRecorder] 无法创建报警视频: {filename}")
                return None
            
            # 写入所有帧
            for frame in frames:
                if frame is not None:
                    writer.write(frame.astype(np.uint8))
            
            writer.release()
            
            # 检查文件
            if os.path.exists(str(filename)):
                file_size = os.path.getsize(str(filename)) / (1024 * 1024)
                logging.info(f"🎥 [VideoRecorder] 报警视频保存: {filename} ({file_size:.2f} MB)")
                return str(filename)
            else:
                return None
                
        except Exception as e:
            logging.error(f"❌ [VideoRecorder] 保存报警视频失败: {e}")
            return None
    
    def save_snapshot(self, frame: np.ndarray, event_id: int) -> Optional[str]:
        """
        保存快照
        
        Args:
            frame: 帧
            event_id: 事件ID
            
        Returns:
            快照文件路径
        """
        try:
            # 创建快照目录
            snapshot_dir = self.output_dir / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = snapshot_dir / f"snapshot_{event_id}_{timestamp}.jpg"
            
            # 保存图像
            success = cv2.imwrite(str(filename), frame, 
                                 [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
            
            if success:
                logging.info(f"📸 [VideoRecorder] 快照保存: {filename}")
                return str(filename)
            else:
                logging.error(f"❌ [VideoRecorder] 快照保存失败: {filename}")
                return None
                
        except Exception as e:
            logging.error(f"❌ [VideoRecorder] 保存快照失败: {e}")
            return None
    
    def cleanup_old_videos(self, max_age_days: int = 7):
        """
        清理旧视频文件
        
        Args:
            max_age_days: 最大保留天数
        """
        try:
            current_time = time.time()
            cutoff_time = current_time - (max_age_days * 24 * 60 * 60)
            
            deleted_count = 0
            for file_path in self.output_dir.rglob("*.mp4"):
                if file_path.is_file():
                    file_time = file_path.stat().st_mtime
                    if file_time < cutoff_time:
                        file_path.unlink()
                        deleted_count += 1
            
            # 清理快照
            snapshot_dir = self.output_dir / "snapshots"
            if snapshot_dir.exists():
                for file_path in snapshot_dir.rglob("*.jpg"):
                    if file_path.is_file():
                        file_time = file_path.stat().st_mtime
                        if file_time < cutoff_time:
                            file_path.unlink()
                            deleted_count += 1
            
            if deleted_count > 0:
                logging.info(f"🧹 [VideoRecorder] 清理了{deleted_count}个旧文件")
                
        except Exception as e:
            logging.error(f"❌ [VideoRecorder] 清理文件失败: {e}")
    
    def get_status(self) -> dict:
        """获取录制器状态"""
        return {
            "is_recording": self.is_recording,
            "current_filename": self.current_filename,
            "frame_buffer_size": len(self.frame_buffer),
            "output_dir": str(self.output_dir),
            "fps": self.fps
        }
    
    def __del__(self):
        """析构函数"""
        if self.is_recording and self.current_writer is not None:
            try:
                self.current_writer.release()
                logging.warning("🎥 [VideoRecorder] 录制器被销毁时正在录制，已强制停止")
            except:
                pass