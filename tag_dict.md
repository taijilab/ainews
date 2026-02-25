# 分类体系

下面给你补齐 **(1) 分类体系初版 + 关键词词典**、**(2) 热度评分公式 + 默认参数**（可直接落地到工程里）。

---

## 1) 分类体系初版（Label Taxonomy + 关键词词典）

### 1.1 标签体系（两级）

> 文章允许多标签；输出 primary_label + labels[]（带置信度）。
> 

**L1：AI**

- L2：LLM & Reasoning（推理/对齐/评测）
- L2：Agent & Tool Use（工具调用/工作流/MCP）
- L2：RAG & Search（检索/向量库/知识库）
- L2：Serving & Inference（vLLM/SGLang/TensorRT-LLM/部署）
- L2：Training & Finetune（SFT/DPO/RLHF/LoRA）
- L2：Multimodal（VLM/语音/视频）
- L2：AI Infra & MLOps（特征/训练管线/实验管理）

**L1：System / Infra**

- L2：Distributed Systems（分布式一致性/消息队列）
- L2：Cloud & K8s（Kubernetes/容器/Service Mesh）
- L2：Networking（TCP/QUIC/CDN/负载均衡）
- L2：OS & Kernel（Linux/内核/性能）
- L2：Observability（日志/指标/Tracing）

**L1：Data**

- L2：Database（Postgres/MySQL/OLAP/向量库）
- L2：Data Engineering（ETL/流批/湖仓）
- L2：Analytics / BI（指标体系/实验/数据产品）

**L1：Security**

- L2：Vulnerability & CVE（漏洞/攻防）
- L2：AppSec / Supply Chain（依赖/签名/SBOM）
- L2：Privacy（隐私/合规）

**L1：Programming**

- L2：Languages（Rust/Go/Python/JS/Java…）
- L2：Compiler & Runtime（编译器/VM/JIT）
- L2：Testing & QA（测试/可靠性）
- L2：DevTools（IDE/CLI/Git/CI）

**L1：Hardware**

- L2：GPU/Accelerators（CUDA/ROCm/Ascend/TPU）
- L2：Edge & Devices（端侧/AI PC/嵌入式）
- L2：Performance（profiling/benchmark）

**L1：Product & Biz（可选）**

- L2：Startups / Strategy（创业/商业模式）
- L2：UX / Growth（增长/定价/市场）

---

### 1.2 关键词词典（可直接用于 rule-based boosting）

> 结构：{label: [keywords...]}，匹配命中可增加该标签置信度；同时会把命中的“产品/技术名”记录为候选实体。
> 

**AI > Agent & Tool Use**

- `agent, agents, autonomous agent, workflow, orchestration, tool calling, function calling, tool-use, planner, executor, reflection`
- `MCP, Model Context Protocol, OpenClaw, LangGraph, LangChain, LlamaIndex, Dify, AutoGPT, CrewAI`
- 中文：`智能体, 工具调用, 工作流, 编排, 规划器, 执行器, 反思`

**AI > Serving & Inference**

- `vllm, sglang, tensorRT-LLM, triton, onnxruntime, gguf, llama.cpp, ollama, kserve, ray serve, tgi, text-generation-inference`
- `kv cache, speculative decoding, paged attention, quantization, int8, fp8, bf16, flashattention`
- 中文：`推理加速, 部署, 量化, KV缓存, 投机解码`

**AI > RAG & Search**

- `rag, retrieval, retriever, reranker, vector database, embeddings, hybrid search`
- `faiss, milvus, qdrant, pinecone, weaviate, chroma, pgvector, elasticsearch`
- 中文：`检索增强, 向量库, 召回, 重排`

**AI > Training & Finetune**

- `finetune, sft, dpo, rlhf, ppo, lora, qlora, peft, distillation`
- `deepspeed, megatron, fsdp, accelerate`
- 中文：`微调, 对齐, 蒸馏`

**System > Cloud & K8s**

- `kubernetes, k8s, helm, ingress, istio, linkerd, envoy, service mesh, containerd, docker`
- 中文：`容器, 服务网格, Ingress`

**Data > Database**

- `postgres, postgresql, mysql, sqlite, mongodb, cassandra, redis, clickhouse, duckdb`
- `lakehouse, iceberg, delta lake, hudi`
- 中文：`湖仓, 列存, 向量检索`

**Security > Vulnerability & CVE**

- `cve-, zero-day, exploit, rce, xss, sqli, csrf, sandbox escape`
- `openssl, log4j, supply chain attack`
- 中文：`漏洞, 0day, 供应链攻击`

**Programming > Languages（举例）**

- Rust：`rust, cargo, borrow checker, tokio, wasm`
- Go：`golang, goroutine, go runtime`
- Python：`python, pip, poetry, uv`
- JS：`node, deno, bun, typescript`

**Hardware > GPU/Accelerators**

- `cuda, cuDNN, nvcc, nvidia, amd, rocm, mi300, mi350, tpu, intel gaudi, ascend, cann`
- `blackwell, hopper, gb200, h100, b200`
- 中文：`国产算力, 昇腾, CANN`

---

### 1.3 标签打分规则（落地建议）

- **基础模型**：embedding/LLM 分类输出 `p_model(label)`
- **规则增强**：词典命中加分 `boost(label)`
- 合成：
    
    `p_final = sigmoid( logit(p_model) + sum(boost_hits) )`
    
- 默认 boost：
    - 强关键词（如 “vLLM”、“MCP”、“CVE-”）：+1.2
    - 中关键词（如 “workflow”、“quantization”）：+0.6
    - 弱关键词（如 “agent”、“deploy”）：+0.3

---

## 2) 热度评分公式（Hot Score）+ 默认参数

### 2.1 你要的“同题共振”核心指标

对每个 Topic（通常是 canonical entity，例如 vLLM / MCP / Rust）在时间窗口 W 内统计：

- `N_posts(W)`：相关文章数
- `N_blogs(W)`：参与博主数（去重）
- `V(W)`：增长速度（近窗口 vs 前一窗口）
- `Recency`：新鲜度（越新越高）
- `Quality`（可选）：文章质量代理（字数、外链、是否全文、历史受欢迎度）

> 重点：N_blogs 是主权重，因为你关心“多个博主讨论同一个产品技术”。
> 

---

### 2.2 热度公式（默认版，可直接实现）

对 topic 在窗口 W 的热度分：

[

Hot(W)= 0.35\cdot D + 0.25\cdot Q + 0.25\cdot V + 0.15\cdot R

]

其中：

**(1) 跨博主覆盖度 D（最重要）**

[

D = \min(1, \frac{\log(1+N_{blogs})}{\log(1+M_{blogs})})

]

- 默认 `M_blogs = 8`（达到 8 个博主基本封顶）

**(2) 量级 Q（文章数）**

[

Q = \min(1, \frac{\log(1+N_{posts})}{\log(1+M_{posts})})

]

- 默认 `M_posts = 15`

**(3) 增长速度 V（热度加速）**

[

V = \text{clip}\left(\frac{N_{posts}^{cur}-N_{posts}^{prev}}{\max(1,N_{posts}^{prev})}, 0, 2\right)/2

]

- 解释：同比增长 200% 视为封顶（=1）

**(4) 新鲜度 R**

[

R = e^{-\Delta t / \tau}

]

- `Δt`：topic 最新文章距当前时间的小时数
- 默认 `τ = 36h`（一天半衰减）

> 直觉：“很多博主都在写 + 文章数量不小 + 最近突然变多 + 最新文章很新” 就会冲榜。
> 

---

### 2.3 “同题共振”判定（你要的标注规则）

把 topic 标记为 **Cross-Blogger Hot**（跨博主热点），需满足：

- `N_blogs(W24h) >= 2` 且 `N_posts(W24h) >= 3`
    
    或者
    
- `N_blogs(W7d) >= 4` 且 `N_posts(W7d) >= 8`

并额外输出一个“共振强度”：

[

Resonance = \frac{N_{blogs}}{\sqrt{N_{posts}}}

]

- 越高表示“不是一个博主刷屏，而是多博主共同关注”。

---

### 2.4 热点榜单输出（建议三个榜）

- **Hot Topics 24h**：看“今天大家在聊什么”
- **Rising Topics 24h**：按 `V` 排序，看“突然爆起来的”
- **Cross-Blogger Topics 7d**：按 `D` + `Resonance` 排序，看“形成共识/扩散的技术”

---

如果你接下来要我继续把它“工程化到可直接开干”，我可以再补两块（同样不需要你再解释）：

- **实体归一/同义词合并规则**（例如 Postgres/PostgreSQL、CUDA/cuDNN、MCP/Model Context Protocol）
- **topic 构建策略**（实体驱动 + 语义聚类补漏）的具体实现细节与边界条件（拆分/合并、误报处理）