# 每日定时抓取 OPML/RSS 博主文章 → 主题分类 → 热门讨论与同题聚合”的程序规格书（PRD + 技术规格合体版）

下面是一份“每日定时抓取 OPML/RSS 博主文章 → 主题分类 → 热门讨论与同题聚合”的**程序规格书（PRD + 技术规格合体版）**，按你说的“多个博主讨论同一个产品/技术要标注出来”。

---

## 1. 背景与目标

### 1.1 背景

你已有一份 OPML（包含大量博主的 RSS/Atom 链接）。希望系统每日自动拉取新文章，做主题分类、聚合，并识别“跨博主共同讨论”的热点（同一产品/技术）。

### 1.2 目标

- **每日定时**抓取所有博主的新文章（增量）。

      [https://gist.github.com/emschwartz/e6d2bf860ccc367fe37ff953ba6de66b](https://gist.github.com/emschwartz/e6d2bf860ccc367fe37ff953ba6de66b)

- 对文章进行**结构化抽取**：标题/摘要/正文/作者/发布时间/链接/标签等。
- 对文章做**主题分类**（可多标签）。
- 生成**热点讨论主题**榜单：按热度/增长/跨博主覆盖度排序。
- 支持“**同一产品/技术**”跨博主的聚合页（Topic Page），可追踪时间线和参与博主。

### 1.3 非目标（第一期不做）

- 全站全文爬虫（仅 RSS/Atom + 可选正文抓取）。
- 评论区抓取（除非后续接入 HN/Reddit/X 等外部讨论源）。
- 个性化推荐（先做全局榜单）。

---

## 2. 用户与使用场景

### 2.1 目标用户

- 研究员/产品经理/开发者：希望每日获得“深度技术圈”的趋势与文章汇总。
- 内容团队：需要快速发现“热点技术/产品”以做选题/报道/二次解读。
- 生态运营：关注某技术栈在不同博主间的扩散与共识形成。

### 2.2 关键场景

- 早晨 9:00 自动生成“昨日/近24h”热点清单。
- 点击某个 Topic（例如 *vLLM / SGLang / MCP / CUDA / Rust*）进入聚合页：看到多博主观点与时间线。
- 搜索某产品/公司/项目名，查看最近讨论热度曲线与关联文章。

---

## 3. 输入与输出

### 3.1 输入

- OPML 文件（包含 feed 列表）
- 可选：手动添加 feed URL
- 可选：外部信号源（后续）：HN、Reddit、GitHub Trending、X 热门等

### 3.2 输出

- 文章库（结构化）
- 分类结果（文章级多标签）
- Topic 聚合（同一产品/技术）
- 热点榜单（按时间窗口）
- API / Web 管理后台 / 可导出 CSV/JSON

---

## 4. 功能规格

## 4.1 Feed 管理

- 导入 OPML：
    - 解析 outline 节点，获取 title、xmlUrl（RSS/Atom）、htmlUrl
    - 去重：按 feed URL 规范化（去参数、http/https 统一、末尾斜杠等）
- Feed 状态：
    - ACTIVE / PAUSED / ERROR（连续失败阈值）
    - 记录最近一次抓取时间、ETag、Last-Modified、失败次数、平均响应耗时
- Feed 分组（可选）：
    - 按 OPML 目录层级、或按主题（安全/AI/工程/创业等）

## 4.2 定时抓取与增量更新

- 每日定时任务（默认 08:30 Asia/Singapore）：
    - 按 feed 逐个拉取（支持并发，限制 QPS）
    - 使用 HTTP 缓存：If-None-Match/If-Modified-Since
    - 只保存新条目（GUID/Link/Title+Date 指纹）
- 抓取策略：
    - 失败重试：指数退避（如 1m/5m/30m）
    - 限流与礼貌：单域名并发上限、User-Agent、超时控制
    - 解析异常隔离：单 feed 失败不影响整体批处理

## 4.3 文章解析与正文抽取

- RSS/Atom 提供字段：
    - title, link, guid, published, updated, author, summary/content, categories
- 正文抽取（可配置）：
    - 若 RSS 仅摘要：使用 Readability/Boilerpipe 类抽取正文
    - 若正文不可用：保留摘要并标记 content_level=SUMMARY
- 语言检测：
    - 自动识别中/英/其他，为分类与实体识别选择对应模型

## 4.4 主题分类（文章级）

- 多标签分类体系（可版本化）：
    - 一级：AI/系统/安全/编程语言/数据/产品与创业/硬件/开源生态…
    - 二级：LLM Agent、推理加速、数据库、分布式、Rust、K8s、编译器…
- 分类方法（推荐混合）：
    1. 规则与词典（高精度：例如 CVE、Kubernetes、Rust、CUDA）
    2. 向量语义分类（embedding + 近邻/层次分类）
    3. LLM 归类（对长文做摘要后归类；可离线批处理）
- 输出：
    - labels[]（含置信度）、primary_label、摘要（100~200字）
    - 关键短语（keyphrases）

## 4.5 实体识别（产品/技术/项目/公司/人名）

- 目标实体类型：
    - Product/Project（如 vLLM、SGLang、LangChain、Postgres）
    - Company/Org（OpenAI、NVIDIA）
    - Standard/Protocol（MCP、OAuth）
    - Programming Language/Framework（Rust、PyTorch）
- 方法：
    - 词典 + NER 模型 + 链接归一（Entity Canonicalization）
    - 同义词：如 “PostgreSQL / Postgres”
- 输出：
    - entities[]（name, type, canonical_id, confidence）
    - entity_mentions（用于 topic 聚合证据）

## 4.6 Topic 聚合（跨博主讨论同一产品/技术）

- Topic 定义：
    - 以 canonical entity 为核心（如 “vLLM”）
    - 或以聚类主题为核心（如 “LLM serving optimization”）
- 聚合规则：
    - **实体驱动**：同 canonical_id 的文章自动归入同 Topic
    - **语义聚类**：对无明确实体但语义相近的文章做聚类补充
- Topic 页面产物：
    - 相关文章列表（按时间）
    - 参与博主列表与覆盖度
    - 共识点/分歧点（可选：用 LLM 对多文摘要对比生成）
    - 热度曲线（近7/30天）

## 4.7 热点识别与“热门讨论主题”榜单

- 热点评分（可配置权重）：
    - recency：越新越高
    - volume：文章数
    - diversity：涉及博主数（**你要的关键指标**）
    - velocity：增长速度（近24h vs 前24h）
    - external_signal（后续）：HN/Reddit/GitHub star 增量等
- 输出榜单：
    - Top Topics（24h/7d/30d）
    - Top Entities（产品/技术）
    - “跨博主共振”榜单（diversity 权重更高）

## 4.8 搜索、订阅与导出

- 搜索：
    - 按关键词/实体/标签/博主/时间范围
- 订阅：
    - 订阅某 Topic：每天推送新增文章摘要
- 导出：
    - CSV/JSON（文章、Topic、实体、榜单）

## 4.9 管理后台（MVP）

- Feed 列表与健康状态
- 抓取任务状态、失败原因、重试
- 分类体系版本管理（label map、词典）
- Topic 合并/拆分（人工纠偏工具）

---

## 5. 数据模型（核心表）

### 5.1 feeds

- id, title, feed_url, site_url, status, etag, last_modified, last_fetch_at, error_count, created_at

### 5.2 posts

- id, feed_id, guid_hash, title, url, author, published_at, fetched_at
- raw_summary, raw_content, content_level(SUMMARY/FULL)
- language, text_hash(去重), canonical_url

### 5.3 post_annotations

- post_id
- summary_generated, keyphrases[]
- labels[] (label_id, confidence)
- entities[] (entity_id, confidence)
- embedding_vector_id

### 5.4 entities

- entity_id, canonical_name, type, aliases[], wiki_url(optional)

### 5.5 topics

- topic_id, topic_type(ENTITY/CLUSTER), title, description, created_at
- primary_entity_id(optional)

### 5.6 topic_posts

- topic_id, post_id, score, evidence(mentions/cluster_distance)

### 5.7 hot_rankings

- window(24h/7d/30d), computed_at
- items: topic_id/entity_id, hot_score, breakdown_json

---

## 6. 处理流程（Pipeline）

1. **OPML 导入** → feeds
2. **Scheduler** 触发抓取批处理
3. **Fetcher**：HTTP conditional GET → 原始 XML
4. **Parser**：解析 RSS/Atom → posts（基础字段）
5. **Content Extractor**（可选）→ full text
6. **Normalize/Dedupe**：URL 规范化、重复文章合并
7. **Annotate**：
    - language detect
    - summarize
    - classify labels
    - extract entities
    - embeddings
8. **Topic Builder**：
    - entity-based grouping
    - semantic clustering补充
9. **Hot Scoring**：按窗口计算榜单
10. **Serve**：API/前端/导出

---

## 7. 系统架构建议

### 7.1 组件

- Scheduler（cron/worker beat）
- Fetcher Worker（并发抓取）
- Parser/Extractor Worker
- NLP/LLM Worker（分类、摘要、实体、聚类）
- API Server（查询、榜单、导出）
- Admin Console（管理）

### 7.2 技术选型（参考）

- 语言：Python（生态成熟）或 Go（抓取性能强）+ Python NLP
- 存储：
    - PostgreSQL（主存储）
    - Redis（队列/缓存）
    - 对象存储（原始 XML/正文快照）
    - 向量库：pgvector / Milvus / Weaviate（按规模选）
- 任务队列：Celery/RQ（Python）或 Temporal（复杂流程）
- 内容抽取：readability-lxml / trafilatura
- 监控：Prometheus + Grafana + Sentry

---

## 8. 关键算法与规则

### 8.1 去重策略（强制）

- guid 优先；无 guid 则 canonical_url；
- 再无则 title+published_at 的 hash；
- 内容指纹：simhash/minhash（防“同文多发/转载”）

### 8.2 实体归一（同一产品技术）

- alias 字典（手工 + 自动扩展）
- embedding 近邻合并候选（人工确认）
- 规则：大小写、连字符、版本号清洗（“vLLM 0.4.2” → vLLM）

### 8.3 热点定义（满足你的诉求）

“热门讨论主题”必须同时满足：

- 近窗口内文章数 ≥ N（如 3）
- 覆盖博主数 ≥ M（如 2）—— **跨博主共振**
- 增长速度或热度分 ≥ threshold

---

## 9. API 规格（示例）

- `GET /api/topics?window=24h&sort=hot`
- `GET /api/topics/{id}`（含相关文章、参与博主、热度曲线）
- `GET /api/posts?label=LLM&after=...`
- `GET /api/entities?q=vllm`
- `POST /api/feeds/import-opml`
- `GET /api/export/posts.csv?window=7d`

---

## 10. 质量、可靠性与安全

### 10.1 SLA/稳定性

- 每日批处理在 X 分钟内完成（随 feed 数量扩展）
- 单 feed 失败不影响整体；错误可追踪可重跑

### 10.2 可观测性

- 指标：抓取成功率、平均耗时、解析失败率、NLP 队列积压
- 日志：按 feed_id/post_id 关联
- 告警：连续失败、热度计算异常、队列积压

### 10.3 合规

- 尊重 robots 与站点条款（RSS 通常许可更清晰）
- 正文抓取可开关；默认只存摘要+引用链接

---

## 11. 里程碑（建议）

- **MVP（1-2周）**：OPML 导入 + RSS 增量抓取 + 文章库 + 基础榜单（按数量/博主覆盖）
- **V1（2-4周）**：正文抽取 + 分类/实体识别 + Topic 聚合页
- **V2（4-8周）**：语义聚类增强 + 热度曲线 + 人工纠偏后台
- **V3（可选）**：接入外部讨论信号（HN/Reddit/GitHub）强化“热门讨论”准确度

---

**分类体系初版（label taxonomy + 关键词词典）**

1. **热度评分公式与默认参数**（N/M/阈值、权重表）
2. **数据库建表 SQL + 任务队列的模块划分**（按你团队习惯：Python/Celery 或 Go+Python 混合）