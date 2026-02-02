# agent/agent_core.py
"""
Agent核心类 - 从main.py迁移过来
"""

import asyncio
import logging
import sys
from typing import Optional

from eye.eye_core import EyeCore
from brain.brain_core import BrainCore
from hand.hand_core import HandCore
from config.settings import ServerConfig


class AICameraAgent:
    """
    AI Camera Agent 主类
    负责初始化和管理眼睛、大脑、手三个核心模块
    """

    def __init__(self):
        self.eye: Optional[EyeCore] = None
        self.brain: Optional[BrainCore] = None
        self.hand: Optional[HandCore] = None

        # 运行状态
        self._running = False
        self._tasks = []

        # 配置日志
        self._setup_logging()

    def _setup_logging(self):
        """配置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('ai_camera_agent.log')
            ]
        )
        logging.info("🤖 AI Camera Agent 启动中...")

    async def initialize(self) -> bool:
        """
        两阶段初始化以防止竞态条件
        
        阶段1: 创建模块而不依赖
        阶段2: 使用依赖关系初始化模块
        阶段3: 在所有组件就绪后注册技能
        """
        try:
            logging.info("=" * 60)
            logging.info("阶段1: 创建模块...")
            logging.info("=" * 60)
            
            # 创建模块而不依赖
            self.eye = EyeCore()
            self.hand = HandCore()  # 不传递eye参数!
            self.brain = BrainCore()  # 不传递参数!
            
            logging.info("✅ 模块创建成功")
            
            logging.info("=" * 60)
            logging.info("阶段2: 使用依赖关系初始化...")
            logging.info("=" * 60)
            
            # 按依赖顺序初始化: Eye → Hand → Brain
            await self.eye.initialize()
            logging.info("✅ 眼睛初始化完成")
            
            await self.hand.initialize(self.eye)
            logging.info("✅ 手初始化完成并引用眼睛")
            
            await self.brain.initialize(self.eye, self.hand)
            logging.info("✅ 大脑初始化完成并引用眼睛和手")
            
            logging.info("=" * 60)
            logging.info("阶段3: 注册技能...")
            logging.info("=" * 60)
            
            # 在所有组件就绪后注册技能
            await self.hand.register_skills()
            logging.info(f"✅ 注册了 {len(self.hand.skills)} 个技能")
            
            logging.info("=" * 60)
            logging.info("✅ 初始化完成!")
            logging.info("=" * 60)
            
            return True
            
        except Exception as e:
            logging.error(f"❌ 初始化失败: {e}", exc_info=True)
            return False

    async def start(self):
        """启动Agent"""
        if self._running:
            logging.warning("Agent 已经在运行中")
            return

        success = await self.initialize()
        if not success:
            logging.error("初始化失败，无法启动")
            return

        self._running = True
        logging.info("🚀 AI Camera Agent 启动成功")

        try:
            # 启动眼睛模块（视频采集和分析）
            eye_task = asyncio.create_task(self._start_eye())
            self._tasks.append(eye_task)

            # 启动API服务器（如果有）
            api_task = asyncio.create_task(self._start_api_server())
            self._tasks.append(api_task)

            # 等待所有任务
            await asyncio.gather(*self._tasks)

        except KeyboardInterrupt:
            logging.info("接收到中断信号，正在关闭...")
        except Exception as e:
            logging.error(f"运行异常: {e}")
        finally:
            await self.stop()

    async def _start_eye(self):
        """启动眼睛模块"""
        if self.eye:
            try:
                await self.eye.start()
            except Exception as e:
                logging.error(f"眼睛模块启动失败: {e}")

    async def _start_api_server(self):
        """
        启动FastAPI服务器（已修复 - 实际启动服务器！）
        """
        import uvicorn
        from api.app import create_app
        
        # 创建FastAPI应用并注入agent引用
        app = create_app(agent_instance=self)
        
        # 配置uvicorn服务器
        config = uvicorn.Config(
            app=app,
            host=ServerConfig.HOST,
            port=ServerConfig.PORT,
            loop="asyncio",  # 使用当前事件循环
            log_level="info",
            access_log=True
        )
        
        server = uvicorn.Server(config)
        
        logging.info(f"🌐 启动API服务器 {ServerConfig.HOST}:{ServerConfig.PORT}")
        
        # 运行服务器（这将阻塞直到关闭）
        await server.serve()

    async def process_user_input(self, user_input: str) -> str:
        """处理用户输入（测试用）"""
        if not self.brain:
            return "❌ 大脑模块未初始化"

        try:
            response = await self.brain.process(user_input)
            return response
        except Exception as e:
            return f"❌ 处理失败: {str(e)}"

    async def stop(self, timeout: float = 10.0):
        """优雅关闭"""
        if not self._running:
            return

        self._running = False
        logging.info("🛑 启动优雅关闭...")
        
        # 阶段1: 停止接收新工作
        shutdown_start = asyncio.get_event_loop().time()
        
        # 阶段2: 按依赖顺序停止模块
        try:
            # 大脑首先停止（无新命令）
            if self.brain:
                await asyncio.wait_for(self.brain.shutdown(), timeout=3.0)
            
            # 眼睛接下来停止（无新感知）
            if self.eye:
                await asyncio.wait_for(self.eye.stop(), timeout=5.0)
            
            # 手最后停止（完成待处理执行）
            if self.hand:
                await asyncio.wait_for(self.hand.shutdown(), timeout=3.0)
        
        except asyncio.TimeoutError:
            logging.warning("优雅关闭超时 - 强制终止")
        
        # 阶段3: 取消剩余任务
        remaining_time = timeout - (asyncio.get_event_loop().time() - shutdown_start)
        
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=max(1.0, remaining_time)
                )
            except asyncio.TimeoutError:
                logging.error("强制关闭 - 一些任务未终止")
        
        # 阶段4: 清理资源
        await self._cleanup_resources()
        
        logging.info("👋 关闭完成")
    
    async def _cleanup_resources(self):
        """显式清理资源"""
        tasks = []
        
        # 关闭数据库连接
        from infrastructure.database.async_db_manager import async_db_manager
        tasks.append(async_db_manager.close_all())
        
        # 关闭HTTP客户端
        if self.brain and hasattr(self.brain, 'client'):
            tasks.append(self.brain.client.aclose())
        
        # 关闭VLM客户端
        if self.eye and hasattr(self.eye, 'scene_analyzer'):
            tasks.append(self.eye.scene_analyzer.close())
        
        await asyncio.gather(*tasks, return_exceptions=True)

    async def get_status(self) -> dict:
        """获取系统状态"""
        return {
            "running": self._running,
            "eye_initialized": self.eye is not None,
            "brain_initialized": self.brain is not None,
            "hand_initialized": self.hand is not None,
            "active_tasks": len(self._tasks)
        }


async def test_agent():
    """测试Agent功能"""
    print("开始测试AI Camera Agent...")

    # 创建Agent实例
    agent = AICameraAgent()

    # 初始化但不启动后台任务
    success = await agent.initialize()
    if not success:
        print("❌ 初始化失败")
        return

    print("✅ 初始化成功")
    print("🧠 大脑模块就绪")
    print("👁️ 眼睛模块就绪")
    print("🖐️ 手模块就绪")

    # 测试用例
    test_cases = [
        "你好",
        "看看现在画面里有什么",
        "只检测人和车",
        "我出门了",
        "系统状态怎么样",
        "没事了，误报"
    ]

    print("\n📋 开始测试对话:")
    for user_input in test_cases:
        print(f"\n👤 用户: {user_input}")
        response = await agent.process_user_input(user_input)
        print(f"🤖 Agent: {response}")
        await asyncio.sleep(1)  # 避免太快

    print("\n✅ 测试完成")
    await agent.stop()


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="AI Camera Agent")
    parser.add_argument("--test", action="store_true", help="运行测试模式")
    parser.add_argument("--start", action="store_true", help="启动完整服务")

    args = parser.parse_args()

    if args.test:
        await test_agent()
    elif args.start:
        agent = AICameraAgent()
        await agent.start()
    else:
        print("请指定运行模式:")
        print("  python main.py --test    # 测试模式")
        print("  python main.py --start   # 启动完整服务")
        print("\n类Agent架构:")
        print("  👁️  眼睛: 视频流采集、目标检测、场景分析")
        print("  🧠  大脑: 意图理解、任务规划、LLM交互")
        print("  🖐️  手: 技能执行、结果处理、警报分发")


if __name__ == "__main__":
    asyncio.run(main())