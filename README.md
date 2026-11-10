# HomeScope AI

基于 FastAPI、HelloAgents、MCP、高德地图和 Vue 3 的多 Agent 搬家选址与通勤决策学习项目。

## 功能与架构

- 需求分析 Agent 提取选址偏好。
- 代码驱动地图采集模块通过高德 MCP 获取坐标、通勤和周边设施证据。
- 通勤、设施 Agent 并行分析，确定性评分算法排序，决策 Agent 生成综合说明。
- 地图增强结果 TTL 缓存、阶段计时、阶段间时间预算检查与异常分类。
- SQLite 保存分析历史、会话与需求版本，使用版本校验防止过期需求覆盖。
- Vue 3 + TypeScript 展示需求表单、分析结果、地图和历史记录。

后端采用代码编排工作流。默认地图采集通过确定性代码调用工具，不依赖模型自由规划。候选区域与租金仍为演示数据，真实地图数据用于增强；本项目不提供实时房源信息。会话版本管理尚不等于自然语言多轮对话或长期记忆。

## 项目结构

```text
backend/app/agents/        # 分析 Agent 与工作流编排
backend/app/api/routes/    # FastAPI 接口
backend/app/services/      # LLM、地图、缓存和会话服务
backend/app/decision/      # 评分排序
backend/app/repositories/  # SQLite 数据访问
backend/app/models/        # Pydantic 数据模型
backend/tests/             # 后端测试
frontend/src/              # Vue 页面与组件
docs/                      # 项目复盘文档
```

## 本地运行（Windows PowerShell）

建议使用 Python 3.11，并安装适合当前 Vite 版本的 Node.js。

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

按需填写 `backend/.env` 中的模型服务和高德 Web 服务配置，再启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

接口文档：<http://127.0.0.1:8000/docs>。服务启动成功不表示外部模型与地图配置已验证。

在另一个终端启动前端：

```powershell
cd frontend
npm.cmd ci
Copy-Item .env.example .env.local
npm.cmd run dev
```

地图展示需在 `frontend/.env.local` 配置高德 JS API Key 与安全码；后端使用单独的 Web 服务 Key。前端开发代理将 `/api` 请求转发至 `127.0.0.1:8000`。

## 验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

```powershell
cd frontend
npm.cmd run build
```

单元测试主要使用替身和临时数据库，不能替代真实模型与地图联调。

## 配置与使用边界

真实 `.env`、本地数据库、依赖目录和构建产物不纳入版本管理。只提交不含真实密钥的环境变量示例。浏览器地图配置会出现在客户端，请按高德平台规则限制使用范围。

当前为学习原型，尚未实现用户鉴权与会话归属隔离。部署到公共网络前需补充访问控制，不应保存或公开真实个人选址需求。
