# Private Knowledge RAG MVP

基于 `FastAPI + Qdrant + DashScope + React + Vite` 的单机私有知识库 RAG 系统，支持文档上传、异步索引、流式问答和引用溯源。

## 功能
- 支持 `PDF / DOCX / Markdown / TXT` 文档上传
- 自动解析、清洗、语义边界切片
- 使用 `text-embedding-v4` 写入 `Qdrant`
- 使用 `qwen3.5-35b-a3b` 生成回答
- 相似度阈值拒答，降低幻觉
- SSE 流式问答
- 引用片段回溯

## 启动 Qdrant
在项目根目录执行：

```powershell
docker compose up -d qdrant
```

默认地址：
- REST: `http://localhost:6333`
- gRPC: `localhost:6334`

## 后端启动
推荐使用 `Python 3.11`。

```powershell
cd D:\桌面\ss
py -3.11 -m venv .venv311
.\.venv311\Scripts\Activate.ps1
python -m pip install -U pip setuptools wheel -i https://pypi.tuna.tsinghua.edu.cn/simple
cd backend
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m uvicorn app.main:app --reload --app-dir .
```

默认地址：`http://localhost:8000`

## 前端启动
```powershell
cd D:\桌面\ss\frontend
npm install
npm run dev
```

默认地址：`http://localhost:5173`

## API 概览
- `POST /api/documents/upload`
- `GET /api/documents`
- `GET /api/documents/{id}`
- `POST /api/documents/{id}/reindex`
- `POST /api/chat`
- `GET /api/chat/stream`
- `GET /api/chunks/{chunk_id}`

## 当前限制
- 首版不做 OCR、复杂表格抽取、多用户权限
- 单机部署，索引任务使用进程内线程池
- 向量库依赖单独的 `Qdrant` Docker 服务
