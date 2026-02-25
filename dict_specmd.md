# 分类体系初版 + 关键词词典

下面把 **1）分类体系+词典** 和 **2）热度公式+默认参数** 再“工程可落地”一版：直接给你两份可用的 **YAML 配置**+ **计算伪代码**（你们落到 Python/Go 都很快）。

---

## 1）分类体系初版 + 关键词词典（可配置化）

### 1.1 taxonomy.yaml（两级标签 + 规则权重）

```yaml
version: 0.1
labels:
  - id: AI.LLM
    name: "AI / LLM & Reasoning"
    parent: "AI"
    keywords_strong: ["mmlu", "gsm8k", "reasoning", "chain-of-thought", "rlhf", "alignment"]
    keywords_medium: ["prompt", "eval", "benchmark", "hallucination", "safety"]
    keywords_weak: ["llm", "model", "transformer"]

  - id: AI.AGENT
    name: "AI / Agent & Tool Use"
    parent: "AI"
    keywords_strong: ["mcp", "model context protocol", "tool calling", "function calling", "langgraph"]
    keywords_medium: ["workflow", "orchestration", "planner", "executor", "reflection", "reliability"]
    keywords_weak: ["agent", "agents", "automation"]

  - id: AI.RAG
    name: "AI / RAG & Search"
    parent: "AI"
    keywords_strong: ["rag", "retrieval augmented generation", "reranker", "hybrid search"]
    keywords_medium: ["vector database", "embedding", "retriever", "chunking"]
    keywords_weak: ["search", "retrieval"]

  - id: AI.SERVING
    name: "AI / Serving & Inference"
    parent: "AI"
    keywords_strong: ["vllm", "sglang", "tensorrt-llm", "triton", "llama.cpp", "gguf"]
    keywords_medium: ["kv cache", "paged attention", "speculative decoding", "quantization", "flashattention"]
    keywords_weak: ["inference", "serving", "deploy", "latency", "throughput"]

  - id: SYS.K8S
    name: "System / Cloud & K8s"
    parent: "System"
    keywords_strong: ["kubernetes", "k8s", "helm", "istio", "envoy"]
    keywords_medium: ["ingress", "service mesh", "containerd", "cni", "sidecar"]
    keywords_weak: ["container", "cloud", "cluster"]

  - id: DATA.DB
    name: "Data / Database"
    parent: "Data"
    keywords_strong: ["postgresql", "postgres", "mysql", "clickhouse", "duckdb", "redis"]
    keywords_medium: ["olap", "index", "query planner", "mvcc", "replication"]
    keywords_weak: ["database", "sql", "storage"]

  - id: SEC.CVE
    name: "Security / Vulnerability & CVE"
    parent: "Security"
    keywords_strong: ["cve-", "zero-day", "rce", "sandbox escape"]
    keywords_medium: ["xss", "sqli", "csrf", "exploit", "poc"]
    keywords_weak: ["security", "vulnerability"]

  - id: PROG.RUST
    name: "Programming / Rust"
    parent: "Programming"
    keywords_strong: ["borrow checker", "cargo", "tokio", "wasm"]
    keywords_medium: ["lifetime", "trait", "async", "serde"]
    keywords_weak: ["rust"]

scoring:
  # 规则命中对标签打分的增益（加到模型logit或直接加权）
  boost:
    strong: 1.2
    medium: 0.6
    weak: 0.3
  # 最终多标签输出阈值
  thresholds:
    primary_label_min: 0.55
    secondary_label_min: 0.40

```

### 1.2 entities.yaml（产品/技术/项目 词典 + 同义词归一）

> 这是你后面做“多个博主讨论同一个产品技术”的关键：先把实体归一做扎实。
> 

```yaml
version: 0.1
entities:
  - id: ent.vllm
    canonical: "vLLM"
    type: "Product"
    aliases: ["vllm", "vLLM", "paged attention", "PagedAttention"]
    trigger_keywords: ["vllm", "paged attention"]

  - id: ent.mcp
    canonical: "Model Context Protocol"
    type: "Protocol"
    aliases: ["mcp", "model context protocol"]
    trigger_keywords: ["mcp", "model context protocol"]

  - id: ent.sglang
    canonical: "SGLang"
    type: "Product"
    aliases: ["sglang", "sg-lang", "sg lang"]
    trigger_keywords: ["sglang"]

  - id: ent.postgres
    canonical: "PostgreSQL"
    type: "Database"
    aliases: ["postgres", "postgresql", "pg"]
    trigger_keywords: ["postgres", "postgresql"]

  - id: ent.tensorrt_llm
    canonical: "TensorRT-LLM"
    type: "Product"
    aliases: ["tensorrt-llm", "tensorrt llm"]
    trigger_keywords: ["tensorrt-llm"]

```

### 1.3 分类与实体抽取落地规则（最小可行）

- **先跑规则**（taxonomy.yaml、entities.yaml 命中）
- 再跑 **embedding/LLM**（可选）补足召回
- 最终输出：
    - `labels[] = [{id, score}]`
    - `entities[] = [{entity_id, confidence, mentions[]}]`
- **置信度融合**（建议）：
    - `score_final = sigmoid(logit(score_model) + sum(rule_boost))`
    - 没有模型时：`score_rule = min(1, sum(rule_boost)/2.0)`（简单可用）

---

## 2）热度评分公式 + 默认参数（“跨博主同题共振”优先）

### 2.1 hot_config.yaml（参数一键可调）

```yaml
version: 0.1
windows:
  - name: "24h"
    hours: 24
  - name: "7d"
    hours: 168
  - name: "30d"
    hours: 720

hot_score:
  weights:
    D_diversity: 0.35   # 博主覆盖度（最重要）
    Q_volume:    0.25   # 文章数量
    V_velocity:  0.25   # 增长速度
    R_recency:   0.15   # 新鲜度

  caps:
    M_blogs: 8          # 覆盖8个博主基本封顶
    M_posts: 15         # 15篇封顶

  velocity:
    max_ratio: 2.0      # 增长200%封顶
    epsilon: 1

  recency:
    tau_hours: 36       # 新鲜度衰减时间常数

cross_blogger_hot:
  rules:
    - window: "24h"
      min_blogs: 2
      min_posts: 3
    - window: "7d"
      min_blogs: 4
      min_posts: 8

```

### 2.2 计算逻辑（伪代码，工程直接抄）

```
for each topic T in window W:
  N_posts = count(posts in T within W)
  N_blogs = count(distinct blog_id in T within W)

  # Diversity (D)
  D = min(1, log(1+N_blogs) / log(1+M_blogs))

  # Volume (Q)
  Q = min(1, log(1+N_posts) / log(1+M_posts))

  # Velocity (V): compare current window vs previous window (same length)
  N_prev = count(posts in T within previous W)
  growth_ratio = (N_posts - N_prev) / max(epsilon, N_prev)
  V = clip(growth_ratio, 0, max_ratio) / max_ratio

  # Recency (R): based on the latest post time in current window
  delta_hours = hours_since(latest_post_time_in_T_within_W)
  R = exp(- delta_hours / tau_hours)

  Hot = wD*D + wQ*Q + wV*V + wR*R

```

### 2.3 “同题共振”标注（你要的那条）

```
CrossBloggerHot(T, W) = (N_blogs >= min_blogs) AND (N_posts >= min_posts)  # 按配置表
Resonance = N_blogs / sqrt(N_posts)  # 越高越像“多博主共同关注”

```

### 2.4 榜单建议（输出三榜就很有用）

- **Hot Topics 24h**：按 `Hot(24h)` 排
- **Rising Topics 24h**：按 `V(24h)` 排（突然爆起来）
- **Cross-Blogger 7d**：按 `D(7d)` 或 `Resonance(7d)` 排（形成共识/扩散）

---

如果你下一步要继续推进（我不追问你细节也能直接给方案）：我可以把 **topic 构建规则**写成同样可配置的 `topic_builder.yaml`（实体驱动+语义聚类补漏+合并/拆分策略），并给一份“最小实现”的目录结构（crawler / parser / annotator / scorer / api）。