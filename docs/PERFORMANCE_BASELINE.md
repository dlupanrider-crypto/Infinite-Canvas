# Infinite Canvas 性能基线记录

> 基于 main.py（共 16,914 行）的静态分析，记录已识别的性能热点、复杂度、并发特征及优化方向。
> 本文档仅做记录，不实施任何优化。

---

## 1. 性能热点清单

### 🔴 高严重度

#### HP-1：WebSocket 串行广播
- **行号**：L110-L153（`broadcast_count`、`broadcast_new_image`、`broadcast_canvas_updated`、`broadcast_asset_library_updated`）
- **问题描述**：四个广播方法均采用 `for ... await connection.send_text()` 串行发送，连接数 N 时延迟为 O(N)。当某个连接网络缓慢时，整个广播链路被阻塞。
- **复杂度**：O(N)，N = 活跃 WebSocket 连接数
- **影响范围**：所有实时通知（在线人数、新图片、画布更新、资产库更新）
- **潜在优化方向**：
  - 使用 `asyncio.gather()` 并行发送
  - 引入广播队列（pub/sub 模式）解耦发送与业务逻辑
  - 对失败连接批量清理而非逐个 remove

#### HP-2：`save_to_history` 全量读写 JSON
- **行号**：L3038-L3050
- **问题描述**：每次保存历史记录时，完整读取 `history.json`（最大 5000 条）、在头部插入新记录、再全量写回。文件越大，序列化/反序列化开销越高。
- **复杂度**：O(M)，M = 历史记录条数（上限 5000）
- **影响范围**：每次图片生成/处理完成后均会调用
- **潜在优化方向**：
  - 改用 SQLite 或 append-only 日志格式
  - 使用双缓冲/增量写入
  - 引入写入批处理（batch write）

#### HP-3：`iter_canvas_records` 全量解析所有画布文件
- **行号**：L3290-L3305（被 `list_canvases` L3307-L3315、`list_deleted_canvases` L3317-L3319 调用）
- **问题描述**：每次列出画布时，遍历 `data/canvases/` 目录下所有 JSON 文件并逐一解析。画布数量增加后，磁盘 IO 和 JSON 解析开销线性增长。
- **复杂度**：O(K)，K = 画布文件数量
- **影响范围**：画布列表页、画布搜索、画布统计
- **潜在优化方向**：
  - 维护索引文件（仅存储元数据），按需加载完整数据
  - 引入内存缓存（LRU）
  - 迁移至 SQLite

#### HP-4：`check_update` 同步阻塞路由
- **行号**：L1845-L1880
- **问题描述**：路由函数为 `def`（同步），内部使用 `Thread` + `join(timeout=5.5)` 等待两个外部 HTTP 请求。在 FastAPI 中，同步路由函数由线程池执行，默认线程池大小有限（40），高并发时会耗尽线程。
- **复杂度**：O(1)（固定两次外部请求），但阻塞时间最长 5.5s
- **影响范围**：前端首屏加载时调用，阻塞工作线程
- **潜在优化方向**：
  - 改为 `async def` + `httpx.AsyncClient`
  - 增加缓存（如 10 分钟内不重复检测）
  - 首屏不阻塞，改为后台定时检测

### 🟡 中严重度

#### HP-5：httpx.AsyncClient 每次请求新建实例
- **行号**：15 处 `async with httpx.AsyncClient(...)` 调用（详见第 5 节）
- **问题描述**：每次 API 调用都新建 `AsyncClient`，无法复用 TCP 连接池。每次新建涉及 SSL 握手、DNS 解析等开销。
- **复杂度**：O(1) 每次，但常数项较大（尤其 HTTPS 场景）
- **影响范围**：所有外部 API 调用（AI 生图、资产上传、版本检测等）
- **潜在优化方向**：
  - 使用应用级全局 `httpx.AsyncClient` 单例
  - 利用 `app.state` 或 lifespan 管理客户端生命周期

#### HP-6：同步 `requests.get/post` 在异步上下文中使用
- **行号**：13 处调用（详见第 5 节），关键位置：L1489、L1739、L1812、L1897、L2809、L6120、L10447、L10481、L10525、L10635、L16088、L16102、L16112
- **问题描述**：在 FastAPI 异步应用中直接使用同步 `requests` 库，会阻塞事件循环（如果在 async 函数中调用）或占用线程池线程。
- **复杂度**：O(1)，但阻塞时间取决于网络延迟
- **影响范围**：版本检测、ComfyUI 通信、文件下载等
- **潜在优化方向**：
  - 统一迁移至 `httpx.AsyncClient`
  - 对必须保留的同步调用，使用 `asyncio.to_thread()` 包装

#### HP-7：`load_asset_library` 每次调用全量加载
- **行号**：L6273-L6283（读取）、L6632-L6640（保存）
- **问题描述**：每次访问资产库相关接口时，从磁盘完整读取 `asset_library.json` 并反序列化。当资产数量增长后，单次读取开销显著增加。
- **复杂度**：O(A)，A = 资产库中的条目总数
- **影响范围**：资产库列表、分类管理、素材上传等
- **潜在优化方向**：
  - 引入内存缓存 + 脏标记机制
  - 按类别分文件存储
  - 迁移至数据库

### 🟢 低严重度

#### HP-8：全局 Lock 粒度过粗
- **行号**：L250-L258（锁定义）
- **问题描述**：8 个全局 `threading.Lock`，部分锁保护范围过大（如 `CANVAS_LOCK` 保护所有画布的读写），导致不相关的画布操作互相等待。
- **复杂度**：N/A（并发控制）
- **影响范围**：多用户并发操作时可能出现锁等待
- **潜在优化方向**：
  - 按资源 ID 使用分段锁（striped lock）
  - 读写分离（ReadWriteLock）
  - 评估是否可改为 asyncio.Lock

#### HP-9：`online_count` 每次遍历所有连接
- **行号**：L103-L108
- **问题描述**：统计在线人数时遍历 `connection_clients` 字典的所有值，过滤 `canvas_` 前缀。
- **复杂度**：O(N)，N = 连接数
- **影响范围**：每次广播时都会调用（包含在广播循环中）
- **潜在优化方向**：
  - 维护独立的计数器，连接/断开时增减

#### HP-10：Responses API 轮询模式
- **行号**：L4035-L4063
- **问题描述**：对 OpenAI Responses API 采用轮询模式，间隔 5s，最长 1500s（25 分钟）。每次轮询发送一次 HTTP 请求。
- **复杂度**：O(T/5)，T = 任务耗时秒数
- **影响范围**：Responses API 类型的 AI 请求
- **潜在优化方向**：
  - 使用 SSE/WebSocket 推送替代轮询（如果 API 支持）
  - 指数退避（exponential backoff）减少轮询频率

---

## 2. O(n) 操作清单

| 操作名称 | 行号 | 触发频率 | 数据规模上限 | 复杂度 |
|---------|------|---------|------------|--------|
| WebSocket 广播（4 种） | L110-L153 | 每次状态变更 | 连接数（预计 <100） | O(N) |
| `online_count` 统计 | L103-L108 | 每次广播 | 连接数 | O(N) |
| `save_to_history` 全量读写 | L3038-L3050 | 每次图片生成 | 5,000 条记录 | O(M) |
| `iter_canvas_records` 全量解析 | L3290-L3305 | 每次画布列表请求 | 画布数（预计 <500） | O(K) |
| `list_canvases` 排序 | L3307-L3315 | 每次画布列表请求 | 同上 | O(K log K) |
| `load_asset_library` 全量加载 | L6273-L6283 | 每次资产库操作 | 资产数（预计 <5000） | O(A) |
| `save_asset_library` 全量保存 | L6632-L6640 | 每次资产库变更 | 同上 | O(A) |
| `cleanup_expired_canvas_trash` | L3275-L3288 | 每次 `iter_canvas_records` | 画布数 | O(K) |
| Responses API 轮询 | L4035-L4063 | 每次 Responses 请求 | 300 次轮询/任务 | O(T/interval) |
| `check_update` 版本检测 | L1845-L1880 | 前端首屏/手动 | 固定 2 次 HTTP | O(1) 但阻塞 5.5s |
| `sync_static_html_versions` | L184 | 每次启动 | HTML 文件数 | O(F) |

---

## 3. 并发与锁分析

### 3.1 全局 Lock 清单（L250-L258）

| Lock 名称 | 用途 | 粒度评估 |
|-----------|------|---------|
| `QUEUE_LOCK` | 保护任务队列操作 | 中等（所有任务共享） |
| `HISTORY_LOCK` | 保护 `history.json` 读写 | 粗（所有历史记录操作互斥） |
| `GLOBAL_CONFIG_LOCK` | 保护全局配置读写 | 合理 |
| `CONVERSATION_LOCK` | 保护会话数据操作 | 合理 |
| `CANVAS_LOCK` | 保护所有画布文件读写 | **过粗**（不同画布 ID 也互斥） |
| `LOAD_LOCK` | 保护模型/工作流加载 | 合理 |
| `RUNNINGHUB_WORKFLOW_LOCK` | 保护 RunningHub 工作流操作 | 合理 |
| `UPDATE_LOCK` | 保护版本更新检测 | 合理 |

### 3.2 同步阻塞调用位置

以下同步调用如果在 async 路由中直接执行，会阻塞事件循环：

| 位置 | 调用 | 阻塞时长 |
|------|------|---------|
| L1489 | `requests.get`（版本检测） | 最长 5s |
| L1739 | `requests.get`（版本检测） | 最长 5s |
| L1812 | `requests.get`（更新日志） | 最长 3s |
| L1846 | `check_update` 整个函数为 `def`（同步路由） | 最长 5.5s |
| L1897 | `github_get` → `requests.get` | 最长 30s |
| L2809 | `requests.get`（ComfyUI 探活） | 0.5s |
| L6120 | `requests.get`（模型下载） | 无上限 |
| L10447 | `requests.get`（ComfyUI 文件） | 1s |
| L10481 | `requests.get`（ComfyUI 代理） | 60s |
| L10525 | `requests.post`（ComfyUI 上传） | 5s |
| L10635 | `requests.post`（ComfyUI 批量上传） | 10s |
| L16088 | `requests.get`（画布同步检查） | 0.5s |
| L16102 | `requests.get`（画布同步拉取） | 5s |
| L16112 | `requests.post`（画布同步上传） | 10s |

### 3.3 无锁保护的共享状态

- `JIMENG_LOGIN_SESSION`（L259-L264）：字典形式的会话状态，无显式锁保护
- `NEXT_TASK_ID`（L257）：全局自增 ID，无原子操作保护
- `manager.active_connections`（L81）：WebSocket 连接列表，在广播循环中修改（删除失败连接）
- `GLOBAL_LOOP`（L164）：全局事件循环引用，启动时赋值一次，风险较低

---

## 4. WebSocket 性能特征

### 4.1 当前广播机制

- **模式**：**串行广播**
- 所有广播方法（L110-L153）均使用 `for connection in self.active_connections[:]` 逐个 `await send_text()`
- 发送顺序取决于连接在列表中的位置
- 任一连接发送失败时，该连接从列表中移除，不影响后续连接

### 4.2 连接管理

- **连接存储**：`active_connections`（列表，O(N) 查找）、`user_connections`（字典，O(1) 查找）、`connection_clients`（字典）
- **连接数限制**：无显式上限，受系统文件描述符和内存限制
- **断开检测**：仅在发送失败时被动清理（无主动心跳超时检测）

### 4.3 心跳机制

- **客户端主动**：客户端发送 `"ping"` 字符串（L207），服务端回复 `{"type": "pong"}`（L208）
- **无服务端主动心跳**：服务端不主动检测死连接
- **无超时断开**：如果客户端不发送 ping 且网络中断，连接将一直保留在列表中

### 4.4 WebSocket 端点

- 路径：`/ws/stats`（L201）
- 支持 `client_id` 查询参数标识客户端
- 异常处理：`WebSocketDisconnect` 和通用 `Exception` 均触发 `disconnect`

---

## 5. HTTP 客户端使用模式

### 5.1 httpx.AsyncClient 创建/销毁位置

共 **15 处** `async with httpx.AsyncClient(...)` 调用，全部为"即用即建"模式：

| 行号 | 用途 | 超时配置 |
|------|------|---------|
| L4633 | 下载远程图片/文件 | connect=20s, read=300s |
| L5683 | 下载远程图片/文件 | connect=20s, read=300s |
| L7486 | 下载预览图 | connect=20s, read=120s |
| L7835 | RunningHub 上传 | connect=20s, read=动态 |
| L8055 | RunningHub 注册资源 | 120s |
| L8075 | RunningHub 任务查询 | 60s |
| L8198 | 火山引擎素材注册 | 120s |
| L8214 | 火山引擎素材查询 | 60s |
| L8264 | 上传到 Jimeng | connect=20s, read=600s |
| L8284 | 上传到 Jimeng（备用） | connect=20s, read=600s |
| L8340 | 下载远程资源 | connect=20s, read=300s |
| L8407 | 下载视频 | 动态超时 |
| L8743 | ModelScope 生图 | AI_REQUEST_TIMEOUT (1800s) |
| L8823 | AI API 调用（文本/图片） | connect=20s, read=1800s |
| L8851 | AI API 调用（带图片） | connect=20s, read=1800s |

### 5.2 同步 requests 调用位置

共 **13 处** 直接调用 `requests.get` / `requests.post`（详见第 3.2 节表格）。

### 5.3 连接池复用情况

- **httpx.AsyncClient**：❌ 无复用，每次 `async with` 新建连接
- **requests**：❌ 无复用，未使用 `requests.Session()`
- **影响**：高频调用场景（如 ComfyUI 通信）下，TCP/TLS 握手开销显著

---

## 6. 前端文件大小统计

### JavaScript 文件

| 文件名 | 大小 | 备注 |
|--------|------|------|
| `smart-canvas.js` | **846.2 KB** | ⚠️ 超过 100KB |
| `canvas.js` | **703.4 KB** | ⚠️ 超过 100KB |
| `asset-manager.js` | **242.2 KB** | ⚠️ 超过 100KB |
| `api-settings.js` | **194.5 KB** | ⚠️ 超过 100KB |
| `ltx-director-timeline.js` | **150.5 KB** | ⚠️ 超过 100KB |
| `comfyui-settings.js` | 68.0 KB | |
| `canvas-list.js` | 47.5 KB | |
| `theme.js` | 11.2 KB | |
| `history-bulk-manager.js` | 10.2 KB | |
| `touch-mouse.js` | 6.1 KB | |
| `image-preview.js` | 5.2 KB | |
| `i18n-core.js` | 2.4 KB | |
| `i18n.js` | 1.0 KB | |

### JavaScript i18n 文件

| 文件名 | 大小 | 备注 |
|--------|------|------|
| `i18n/canvas.js` | 29.2 KB | |
| `i18n/smart-canvas.js` | 25.6 KB | |
| `i18n/api-settings.js` | 18.0 KB | |
| `i18n/studio.js` | 8.7 KB | |
| `i18n/comfyui-settings.js` | 6.1 KB | |
| `i18n/validate-i18n.js` | 3.0 KB | |
| `i18n/common.js` | 2.8 KB | |

### CSS 文件

| 文件名 | 大小 | 备注 |
|--------|------|------|
| `api-settings.css` | **198.3 KB** | ⚠️ 超过 100KB |
| `smart-canvas.css` | **171.0 KB** | ⚠️ 超过 100KB |
| `canvas.css` | **141.8 KB** | ⚠️ 超过 100KB |
| `theme.css` | 54.9 KB | |
| `asset-manager.css` | 41.4 KB | |
| `canvas-list.css` | 26.5 KB | |
| `comfyui-settings.css` | 25.8 KB | |

### 前端总计

| 类型 | 文件数 | 总大小 |
|------|--------|--------|
| JS（主文件） | 13 | ~2,288 KB |
| JS（i18n） | 7 | ~93 KB |
| CSS | 7 | ~660 KB |
| **合计** | **27** | **~3,041 KB** |

> ⚠️ 超过 100KB 的文件共 **8 个**，占总量约 80%。最大文件 `smart-canvas.js`（846.2 KB）。

---

## 7. 存储层性能预估

### 7.1 历史记录（`history.json`）

| 记录数 | 预估文件大小 | 读取耗时 | 写入耗时 | 备注 |
|--------|------------|---------|---------|------|
| 10 | ~20 KB | <1ms | <1ms | 无感知 |
| 100 | ~200 KB | ~2ms | ~3ms | 轻微 |
| 1,000 | ~2 MB | ~15ms | ~25ms | 可感知 |
| 5,000（上限） | ~10 MB | ~80ms | ~150ms | 明显延迟 |

> 基于每条记录约 2KB、JSON indent=4 格式估算。

### 7.2 画布文件（`data/canvases/*.json`）

| 画布数 | 列表加载耗时 | 排序耗时 | 备注 |
|--------|------------|---------|------|
| 10 | ~5ms | <1ms | 无感知 |
| 100 | ~50ms | ~2ms | 轻微 |
| 1,000 | ~500ms | ~20ms | 明显延迟 |
| 10,000 | ~5,000ms | ~200ms | 严重阻塞 |

> 基于每个画布文件约 10-50KB 估算。`iter_canvas_records` 需要逐一打开、解析 JSON。

### 7.3 资产库（`asset_library.json`）

| 资产条目数 | 预估文件大小 | 加载耗时 | 保存耗时 | 备注 |
|-----------|------------|---------|---------|------|
| 10 | ~5 KB | <1ms | <1ms | 无感知 |
| 100 | ~50 KB | ~2ms | ~3ms | 轻微 |
| 1,000 | ~500 KB | ~10ms | ~15ms | 可感知 |
| 10,000 | ~5 MB | ~80ms | ~120ms | 明显延迟 |

---

## 8. 推荐优化优先级

按 **收益/成本比** 从高到低排序：

| 优先级 | 优化项 | 收益 | 成本 | 说明 |
|--------|--------|------|------|------|
| P0 | WebSocket 广播改为 `asyncio.gather()` | 🔥🔥🔥 | ⭐ | 改动量小（约 20 行），实时性显著提升 |
| P0 | `check_update` 改为 async + 加缓存 | 🔥🔥🔥 | ⭐ | 消除首屏阻塞，约 30 行改动 |
| P1 | httpx.AsyncClient 改为全局单例 | 🔥🔥 | ⭐ | 复用连接池，减少 TLS 握手，约 50 行改动 |
| P1 | `save_to_history` 改用 append-only 或 SQLite | 🔥🔥🔥 | ⭐⭐ | 消除 O(M) 全量读写，中等改动量 |
| P1 | `iter_canvas_records` 增加索引缓存 | 🔥🔥 | ⭐⭐ | 画布列表加载速度提升 10x+ |
| P2 | 同步 `requests` 迁移至 `httpx` | 🔥🔥 | ⭐⭐⭐ | 13 处调用需逐一改造，工作量大 |
| P2 | `CANVAS_LOCK` 改为分段锁 | 🔥 | ⭐⭐ | 减少锁竞争，但当前并发量下不紧急 |
| P2 | 资产库增加内存缓存 | 🔥🔥 | ⭐⭐ | 减少磁盘 IO，需处理缓存一致性 |
| P3 | WebSocket 死连接检测 | 🔥 | ⭐⭐ | 增加服务端心跳超时，防止连接泄漏 |
| P3 | 前端大文件拆分/压缩 | 🔥 | ⭐⭐⭐ | 5 个 JS 文件超 100KB，需模块化重构 |
| P4 | 存储层迁移至 SQLite | 🔥🔥🔥 | ⭐⭐⭐⭐ | 长期方案，彻底解决文件 IO 瓶颈 |

> 收益标记：🔥 = 低收益，🔥🔥 = 中收益，🔥🔥🔥 = 高收益
> 成本标记：⭐ = 低成本（<2h），⭐⭐ = 中成本（2-8h），⭐⭐⭐ = 高成本（8-24h），⭐⭐⭐⭐ = 很高成本（>24h）
