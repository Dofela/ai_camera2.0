# skills/data/report.py
"""
报告技能 - 生成事件报告
"""

from pydantic import Field
from skills.base_skill import BaseSkill
from infrastructure.database.async_db_manager import async_db_manager
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional


class ReportSkill(BaseSkill):
    name = "generate_report"
    description = "生成安防事件报告。用于'生成报告'、'查看事件统计'、'导出数据'等需求。"

    class Parameters(BaseSkill.Parameters):
        time_range: str = Field(
            default="24h", 
            description="时间范围: '24h'(最近24小时), '7d'(最近7天), '30d'(最近30天)"
        )
        event_types: List[str] = Field(
            default_factory=list,
            description="事件类型过滤: 'all'(所有), 'visual'(视觉异常), 'behavior'(行为异常)"
        )

    async def execute(self, params: dict) -> str:
        p = self.Parameters(**params)
        
        try:
            # 解析时间范围
            start_time, end_time = self._parse_time_range(p.time_range)
            
            # 查询数据库
            events = await self._query_events(start_time, end_time, p.event_types)
            
            if not events:
                return "📊 报告: 指定时间段内未检测到事件"
            
            # 生成详细报告
            report = self._generate_report(events, p.time_range)
            
            # 保存报告到文件
            report_path = self._save_report(report, start_time, end_time)
            
            return f"📊 报告已生成: {report_path}\n\n{report[:500]}..."
            
        except Exception as e:
            return f"❌ 生成报告失败: {str(e)}"
    
    def _parse_time_range(self, time_range: str) -> tuple:
        """解析时间范围"""
        end_time = datetime.now()
        
        if time_range == "24h":
            start_time = end_time - timedelta(hours=24)
        elif time_range == "7d":
            start_time = end_time - timedelta(days=7)
        elif time_range == "30d":
            start_time = end_time - timedelta(days=30)
        else:
            start_time = end_time - timedelta(hours=24)
        
        return start_time, end_time
    
    async def _query_events(self, start_time: datetime, end_time: datetime, event_types: List[str]) -> List[Dict]:
        """查询事件数据"""
        try:
            # 构建SQL查询
            sql = """
            SELECT id, start_time, end_time, target_data, sys_summary, ai_analysis, 
                   is_abnormal, alert_tags, video_path
            FROM security_events 
            WHERE start_time >= ? AND start_time <= ? AND status = 'closed'
            """
            params = [start_time.strftime('%Y-%m-%d %H:%M:%S'), end_time.strftime('%Y-%m-%d %H:%M:%S')]
            
            # 添加事件类型过滤
            if event_types and "all" not in event_types:
                if "visual" in event_types:
                    sql += " AND is_abnormal = 1"
                if "behavior" in event_types:
                    sql += " AND alert_tags LIKE '%behavior%'"
            
            sql += " ORDER BY start_time DESC"
            
            # 执行查询
            async with async_db_manager._get_connection() as conn:
                cursor = await conn.execute(sql, params)
                rows = await cursor.fetchall()
                await cursor.close()
            
            # 转换为字典列表
            columns = [description[0] for description in cursor.description]
            events = [dict(zip(columns, row)) for row in rows]
            
            return events
            
        except Exception as e:
            raise Exception(f"查询事件数据失败: {e}")
    
    def _generate_report(self, events: List[Dict], time_range: str) -> str:
        """生成报告内容"""
        total_events = len(events)
        
        # 统计各类事件
        visual_abnormal = sum(1 for e in events if e.get('is_abnormal', 0) == 1)
        behavior_abnormal = sum(1 for e in events if 'behavior' in (e.get('alert_tags', '') or ''))
        
        # 目标统计
        target_stats = {}
        for event in events:
            try:
                target_data = json.loads(event.get('target_data', '{}'))
                for target, count in target_data.items():
                    target_stats[target] = target_stats.get(target, 0) + count
            except:
                pass
        
        # 生成报告文本
        report = f"""
# AI Camera 安防报告
## 时间范围: {time_range}

### 概览
- 总事件数: {total_events}
- 视觉异常事件: {visual_abnormal}
- 行为异常事件: {behavior_abnormal}

### 目标统计
"""
        for target, count in sorted(target_stats.items(), key=lambda x: x[1], reverse=True):
            report += f"- {target}: {count}\n"
        
        report += "\n### 事件详情\n"
        for event in events[:20]:  # 限制显示前20个事件
            report += f"- [{event['start_time']}] {event['sys_summary']}\n"
            if event.get('ai_analysis'):
                report += f"  AI分析: {event['ai_analysis']}\n"
        
        if len(events) > 20:
            report += f"\n... 还有 {len(events) - 20} 个事件\n"
        
        return report
    
    def _save_report(self, report: str, start_time: datetime, end_time: datetime) -> str:
        """保存报告到文件"""
        import os
        from pathlib import Path
        
        # 创建报告目录
        report_dir = Path("reports")
        report_dir.mkdir(exist_ok=True)
        
        # 生成文件名
        filename = f"report_{start_time.strftime('%Y%m%d')}_{end_time.strftime('%Y%m%d')}.txt"
        filepath = report_dir / filename
        
        # 保存文件
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(report)
        
        return str(filepath)