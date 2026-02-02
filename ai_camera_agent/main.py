# main.py
"""
AI Camera Agent - 主入口文件
"""

from agent.agent_core import AICameraAgent, main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())