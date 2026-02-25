# Topic 构建规则配置 + 最小工程实现结构

很好，我们直接进入下一步：下面是你要的 **Topic 构建规则配置 + 最小工程实现结构**。这部分是整套系统里最关键的“智能中枢”，决定是否能正确识别 **多个博主讨论同一技术/产品**。

---

# 一、Topic 构建规则（topic_builder.yaml）

```yaml
version: 0.1

topic_building:

  priority_order:
    - entity_exact
    - entity_alias
    - semantic_cluster
    - keyword_cluster

  entity_rules:
    create_if_entity_mentioned: true
    min_confidence: 0.55
    merge_if_same_canonical: true

  semantic_cluster:
    enabled: true
    embedding_model: "bge-large"
    similarity_threshold: 0.82
    min_cluster_size: 2

  keyword_cluster:
    enabled: true
    min_keyword_overlap: 3

  topic_split_rules:
    max_time_gap_days: 30
    split_if_semantic_distance: 0.25

  topic_merge_rules:
    merge_if_embedding_similarity: 0.9
    merge_if_same_entity: true

  ranking_priority:
    - entity_topic
    - cluster_topic

  fallback:
    create_single_post_topic: false

```

---

## 规则逻辑解释（工程人员必读）

### Topic 创建优先级

系统按顺序判断文章属于哪个 Topic：

1️⃣ 明确提到实体（如 vLLM） → 直接归入该实体 Topic

2️⃣ 命中实体别名 → 归入实体 Topic

3️⃣ 无实体 → 做 embedding 聚类

4️⃣ 无法聚类 → 关键词聚类

5️⃣ 都失败 → 不建 topic（避免噪声）

👉 这保证：

> 只要多个博主写同一个技术名 → 一定进同一 Topic
> 

---

### Topic 合并策略

两个 Topic 满足任一条件 → 自动合并

- embedding 相似度 ≥ 0.9
- canonical entity 相同

---

### Topic 拆分策略

一个 Topic 满足任一条件 → 自动拆分

- 最后两篇文章时间间隔 > 30 天
- 语义中心偏移 > 0.25

👉 防止一个老技术长期混成一个超大 topic

---

### 单文章 Topic 禁止策略

```
create_single_post_topic = false

```

表示：

> 只有 1 篇文章的主题不会建 topic
> 
> 
> （避免系统被长尾噪声淹没）
> 

---

---

# 二、最小工程实现结构（直接可开发）

推荐微模块结构（单 repo 可跑）

```
rss-intel-system/
│
├── config/
│   ├── taxonomy.yaml
│   ├── entities.yaml
│   ├── hot_config.yaml
│   └── topic_builder.yaml
│
├── crawler/
│   ├── fetcher.py
│   ├── parser.py
│   └── scheduler.py
│
├── processor/
│   ├── cleaner.py
│   ├── deduper.py
│   └── language.py
│
├── nlp/
│   ├── embedder.py
│   ├── classifier.py
│   ├── entity_extractor.py
│   └── summarizer.py
│
├── topic_engine/
│   ├── topic_builder.py
│   ├── clusterer.py
│   ├── merger.py
│   └── splitter.py
│
├── ranking/
│   ├── hot_score.py
│   └── leaderboard.py
│
├── api/
│   ├── routes_topics.py
│   ├── routes_posts.py
│   └── routes_export.py
│
└── db/
    ├── models.py
    └── migrations/

```

---

## 三、核心模块职责（关键设计点）

### crawler

负责：

- RSS 拉取
- 增量检测
- feed 状态管理

绝对不要做 NLP（避免耦合）

---

### processor

负责：

- 去重
- URL 标准化
- HTML 清洗
- 语言识别

---

### nlp

负责：

- embedding
- 分类
- 实体识别
- 摘要

👉 设计原则

**全部可替换模型**

---

### topic_engine（系统灵魂）

负责：

- Topic 生成
- Topic 合并
- Topic 拆分
- Topic 更新

---

### ranking

负责：

- 热度计算
- 榜单生成

---

---

# 三、Topic Builder 核心伪代码（工程可直接写）

```python
def assign_topic(post):

    entities = post.entities

    # 1. entity匹配
    for e in entities:
        topic = find_topic_by_entity(e)
        if topic:
            return topic

    # 2. semantic clustering
    vec = post.embedding
    topic = nearest_topic(vec, threshold=0.82)
    if topic:
        return topic

    # 3. keyword cluster
    topic = keyword_match(post)
    if topic:
        return topic

    # 4. create?
    if config.create_single_post_topic:
        return create_topic(post)

    return None

```

---

---

# 四、上线最小可运行版本（MVP方案）

如果你想一周内上线：

### 必做模块（最小集）

- RSS抓取
- 去重
- 实体识别（规则词典版）
- topic_builder（只做 entity）
- 热榜（只做 N_posts + N_blogs）

### 暂不做

- embedding
- semantic clustering
- LLM分类

👉 仍然能跑出：

> “今天哪些技术被多个博主同时讨论”
> 

---

---

# 五、最终系统能力（上线后效果）

系统每天自动输出：

```
🔥 今日跨博主热点

1️⃣ vLLM
   6篇文章｜4位博主｜增长 +200%

2️⃣ MCP Protocol
   5篇文章｜3位博主｜增长 +150%

3️⃣ Rust async runtime
   4篇文章｜4位博主｜增长 +80%

```

并可点击查看：

- 各博主观点对比
- 时间线
- 讨论趋势图

---

---

# 六、你这个系统的战略价值（重点）

这类系统本质不是 RSS 聚合器，而是：

> 技术舆情雷达 + 研发趋势预测引擎
> 

它能回答：

- 哪个技术刚刚开始爆？
- 哪个技术开始被多方认可？
- 哪个项目正在形成共识？
- 哪个技术只是单人 hype？

这正是你在做生态战略时最需要的数据能力。

---

---