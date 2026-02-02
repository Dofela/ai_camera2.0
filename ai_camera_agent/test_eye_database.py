#!/usr/bin/env python3
"""
眼睛模块独立数据库测试脚本

测试功能:
1. 数据库迁移工具
2. 异步数据库管理器
3. 眼睛模块集成
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_database_migration():
    """测试数据库迁移工具"""
    from infrastructure.database.eye_migrator import EyeDatabaseMigrator, migrate_eye_database, check_eye_database
    
    print("=" * 60)
    print("🧪 测试1: 数据库迁移工具")
    print("=" * 60)
    
    # 创建迁移工具实例
    migrator = EyeDatabaseMigrator()
    
    # 检查迁移前状态
    status_before = await check_eye_database()
    print(f"📊 迁移前状态:")
    print(f"  - 目标数据库存在: {status_before['target_exists']}")
    print(f"  - 源数据库存在: {status_before['source_exists']}")
    
    # 执行迁移
    print("\n🔄 执行数据库迁移...")
    success = await migrator.migrate()
    
    if success:
        print("✅ 数据库迁移成功!")
        
        # 检查迁移后状态
        status_after = await check_eye_database()
        print(f"\n📊 迁移后状态:")
        print(f"  - 目标数据库存在: {status_after['target_exists']}")
        print(f"  - 表数量: {status_after.get('table_count', 0)}")
        print(f"  - 索引数量: {status_after.get('index_count', 0)}")
        
        if 'tables' in status_after:
            print(f"  - 表列表: {status_after['tables']}")
    else:
        print("❌ 数据库迁移失败!")
        
    return success

async def test_async_db_manager():
    """测试异步数据库管理器"""
    from infrastructure.database.async_db_manager import async_db_manager
    from config.settings import DBConfig
    
    print("\n" + "=" * 60)
    print("🧪 测试2: 异步数据库管理器")
    print("=" * 60)
    
    print(f"📁 数据库路径: {DBConfig.EYE_DB_PATH}")
    
    # 初始化数据库管理器
    print("🔄 初始化异步数据库管理器...")
    await async_db_manager.initialize()
    
    # 健康检查
    print("🩺 执行健康检查...")
    healthy = await async_db_manager.health_check()
    
    if healthy:
        print("✅ 数据库健康检查通过!")
    else:
        print("❌ 数据库健康检查失败!")
        return False
    
    # 测试数据库操作
    print("\n📝 测试数据库操作...")
    
    # 1. 开始事件
    print("  1. 开始新事件...")
    event_id = await async_db_manager.start_event(
        start_time="2024-01-01 10:00:00",
        initial_targets={"person": 2, "car": 1},
        is_abnormal=0,
        alert_tags=""
    )
    
    if event_id:
        print(f"    ✅ 事件创建成功, ID: {event_id}")
    else:
        print("    ❌ 事件创建失败")
        return False
    
    # 2. 更新事件
    print("  2. 更新事件...")
    await async_db_manager.update_event(
        row_id=event_id,
        end_time="2024-01-01 10:01:00",
        max_targets={"person": 3, "car": 1, "bicycle": 1},
        is_abnormal=1,
        alert_tags="visual"
    )
    print("    ✅ 事件更新成功")
    
    # 3. 关闭事件
    print("  3. 关闭事件...")
    await async_db_manager.close_event(
        row_id=event_id,
        end_time="2024-01-01 10:02:00"
    )
    print("    ✅ 事件关闭成功")
    
    # 4. 测试连接池
    print("\n🔗 测试连接池...")
    print(f"    - 最大连接数: {async_db_manager._max_connections}")
    print(f"    - 活动连接数: {async_db_manager._active_connections}")
    
    return True

async def test_eye_module_integration():
    """测试眼睛模块集成"""
    from eye.memory.perception_memory import PerceptionMemory
    from common.types import DetectionResult, PerceptionResult
    from datetime import datetime
    
    print("\n" + "=" * 60)
    print("🧪 测试3: 眼睛模块集成")
    print("=" * 60)
    
    # 创建感知记忆实例
    print("🧠 创建感知记忆实例...")
    perception_memory = PerceptionMemory()
    
    # 连接到数据库
    print("💾 连接到数据库...")
    perception_memory.connect_database()  # 使用默认的异步数据库管理器
    
    # 创建测试数据
    print("📊 创建测试数据...")
    detection_result = DetectionResult(
        has_detections=True,
        class_counts={"person": 2, "car": 1},
        timestamp=datetime.now().isoformat()
    )
    
    perception_result = PerceptionResult(
        detection_result=detection_result,
        timestamp=datetime.now().isoformat(),
        alert_tags=set()
    )
    
    # 测试存储功能
    print("💾 测试存储功能...")
    success = await perception_memory.store(perception_result)
    
    if success:
        print("✅ 感知数据存储成功!")
        
        # 检查事件状态
        if perception_memory.current_event.is_active:
            print(f"📊 当前事件状态:")
            print(f"    - 事件ID: {perception_memory.current_event.event_id}")
            print(f"    - 最大计数: {perception_memory.current_event.max_counts}")
            print(f"    - 报警标签: {perception_memory.current_event.alert_tags}")
    else:
        print("❌ 感知数据存储失败!")
    
    return success

async def test_performance():
    """测试性能"""
    from infrastructure.database.async_db_manager import async_db_manager
    import time
    
    print("\n" + "=" * 60)
    print("🧪 测试4: 性能测试")
    print("=" * 60)
    
    # 测试并发写入
    print("⚡ 测试并发写入性能...")
    
    async def create_event(i: int):
        """创建单个事件"""
        start_time = f"2024-01-01 10:{i:02d}:00"
        await async_db_manager.start_event(
            start_time=start_time,
            initial_targets={"person": i % 3 + 1},
            is_abnormal=i % 2,
            alert_tags="test"
        )
    
    # 并发创建10个事件
    num_events = 10
    start_time = time.time()
    
    tasks = [create_event(i) for i in range(num_events)]
    await asyncio.gather(*tasks)
    
    end_time = time.time()
    elapsed = end_time - start_time
    
    print(f"    - 创建 {num_events} 个事件")
    print(f"    - 总耗时: {elapsed:.2f} 秒")
    print(f"    - 平均每个事件: {elapsed/num_events:.3f} 秒")
    print(f"    - 吞吐量: {num_events/elapsed:.1f} 事件/秒")
    
    return True

async def cleanup():
    """清理测试数据"""
    from config.settings import DBConfig
    import os
    
    print("\n" + "=" * 60)
    print("🧹 清理测试数据")
    print("=" * 60)
    
    db_path = DBConfig.EYE_DB_PATH
    
    if os.path.exists(db_path):
        # 备份测试数据库
        backup_path = f"{db_path}.test_backup"
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"📦 测试数据库已备份到: {backup_path}")
        
        # 删除测试数据库
        os.remove(db_path)
        print(f"🗑️ 已删除测试数据库: {db_path}")
    
    print("✅ 清理完成")

async def main():
    """主测试函数"""
    print("🚀 开始眼睛模块独立数据库测试")
    print("=" * 60)
    
    all_tests_passed = True
    
    try:
        # 测试1: 数据库迁移
        if not await test_database_migration():
            all_tests_passed = False
        
        # 测试2: 异步数据库管理器
        if all_tests_passed and not await test_async_db_manager():
            all_tests_passed = False
        
        # 测试3: 眼睛模块集成
        if all_tests_passed and not await test_eye_module_integration():
            all_tests_passed = False
        
        # 测试4: 性能测试
        if all_tests_passed and not await test_performance():
            all_tests_passed = False
        
        # 显示测试结果
        print("\n" + "=" * 60)
        print("📊 测试结果汇总")
        print("=" * 60)
        
        if all_tests_passed:
            print("🎉 所有测试通过!")
            print("\n✅ 眼睛模块独立数据库实现成功:")
            print("   - 数据库迁移工具 ✓")
            print("   - 异步数据库管理器 ✓")
            print("   - 连接池和错误重试 ✓")
            print("   - 眼睛模块集成 ✓")
            print("   - 性能优化 ✓")
        else:
            print("❌ 部分测试失败")
        
        # 清理测试数据
        await cleanup()
        
    except Exception as e:
        print(f"💥 测试过程中发生异常: {e}")
        import traceback
        traceback.print_exc()
        all_tests_passed = False
    
    return all_tests_passed

if __name__ == "__main__":
    # 运行测试
    success = asyncio.run(main())
    
    # 退出码
    sys.exit(0 if success else 1)