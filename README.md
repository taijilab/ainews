# AI News Daily

按 `ainews_prd.md`、`tag_dict.md`、`dict_specmd.md`、`topic_rules.md` 实现的最小可运行应用：

- OPML/RSS 抓取与增量入库
- 规则分类（taxonomy）
- 实体识别与归一（entities）
- Topic 聚合（实体优先）
- 热度榜单计算（Hot/Resonance/Cross-Blogger）
- FastAPI 查询接口

## 目录

```text
config/
crawler/
processor/
nlp/
topic_engine/
ranking/
api/
db/
pipeline.py
cli.py
```

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 准备 OPML

默认读取 `feeds.opml`，其中需要包含 `xmlUrl` 字段。

## 运行每日流程

```bash
python cli.py run --opml feeds.opml --db data/ainews.db --config config
```

## 启动 API

```bash
python cli.py serve --db data/ainews.db --host 0.0.0.0 --port 8000
```

启动后直接打开：`http://127.0.0.1:8000/`

- 左侧为按日期时间轴（每天资讯）
- 右侧显示当天统计、话题和文章列表
- 右上角可打开“数据源管理（新窗口）”：`/sources`
- 数据源管理页支持：列表查看、手工添加、删除、Gist 预填
- 文章列表展示：中文标题、中文摘要、Topic/Tag 标签

## API 示例

- `GET /api/topics?window=24h&sort=hot`
- `GET /api/topics/{topic_id}`
- `GET /api/posts?label=AI.SERVING`
- `GET /api/entities?q=vllm`
- `GET /api/dates?limit=120`
- `GET /api/daily?day=2026-02-25`
- `GET /api/sources?days=7`
- `POST /api/sources`
- `DELETE /api/sources/{feed_id}?purge_posts=true`
- `POST /api/sources/import-gist`
- `POST /api/sources/prefill-local-gist`

## 说明

- 当前实现遵循你文档里的 MVP 路径：先用规则词典与实体驱动 Topic。
- `topic_builder.yaml` 中语义聚类参数已预留，后续可接 embedding 模型。
- 热度计算使用 `dict_specmd.md` 的默认公式与阈值。
