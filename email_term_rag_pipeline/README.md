# 邮件术语 RAG 流水线 (Email Term RAG Pipeline)

基于《汉英英汉服装分类词汇》构建的专业术语检索增强生成（RAG）流水线。

> 本模块是双轨 RAG 架构中的「术语 RAG」轨道，与 `email_rag_pipeline`（邮件事件 RAG）并列。命名遵循 `email_*_pipeline` 统一规范。

---

## 📁 目录结构

```
email_term_rag_pipeline/
├── README.md                         # 本文件
├── requirements.txt                  # 依赖列表
├── configs/                          # 配置文件
│   ├── extraction_config.json        # PDF 提取配置
│   └── kb_config.json                # 向量库构建配置
├── src/                              # 核心源码
│   ├── extract_pdf_terms.py          # PDF 术语提取（491页全量+断点恢复+分类识别）
│   ├── build_term_kb.py              # ChromaDB 术语建库
│   └── rag_qa.py                     # 术语检索与问答服务
├── scripts/
│   ├── run_term_pipeline.sh          # 术语RAG一键构建脚本
│   └── quick_test.py                 # 快速测试
└── output/                           # 流水线输出
    ├── extracted_terms.json
    ├── filtered_terms.json
    ├── extract_stats.json
    └── term_kb_stats.json
```

> **向量数据库位置**：术语向量库写入项目根目录的 `vector_db/`（ChromaDB 共享存储），collection 名为 `clothing_terms`。

---

## 🚀 快速开始

### 方式1：一键脚本（最简单）

```bash
./email_term_rag_pipeline/scripts/run_term_pipeline.sh
```

脚本会自动：
1. 从 `data/pdf/汉英英汉服装分类词汇.pdf` 提取全部 491 页术语
2. 质量过滤、去重、保留分类信息
3. 构建/覆盖 `clothing_terms` ChromaDB collection
4. 输出统计报告到 `email_term_rag_pipeline/output/`

> **耗时提示**：491 页 PDF 提取约需 **8-12 分钟**，支持断点恢复。首次建库需下载 BGE 模型（约 1-2GB）。

### 方式2：分步执行

```bash
# Step 1: 提取 PDF（支持 --resume 断点恢复）
python email_term_rag_pipeline/src/extract_pdf_terms.py

# 如果中断，恢复运行：
python email_term_rag_pipeline/src/extract_pdf_terms.py --resume

# Step 2: 构建向量库
python email_term_rag_pipeline/src/build_term_kb.py
```

### 方式3：基于旧数据快速建库

如果你不想重新提取 PDF，可以直接用旧数据建库（但**没有分类信息**）：

```bash
python email_term_rag_pipeline/src/build_term_kb.py \
    --input email_term_rag_pipeline/output/filtered_terms.json
```

---

## 🏗️ 流水线设计

```
data/pdf/汉英英汉服装分类词汇.pdf
    │
    ▼
[src/extract_pdf_terms.py] 增强提取
    ├── 全角字符转半角
    ├── 页眉分类检测（如：衣前身 / 拉链 / 外套）
    ├── 中英文跨行合并
    ├── 跳过前言/目录/附录页
    └── 每 50 页自动保存断点
    │
    ▼
email_term_rag_pipeline/output/extracted_terms.json
    │
    ▼
[内置过滤] 质量过滤
    ├── 黑名单过滤（去除前言垃圾词条）
    ├── 长度过滤（中文>=2字，英文>=2字符）
    └── 去重（基于 chinese+english）
    
> **注意**：`build_term_kb.py` 在建库时会再做一次英文长度过滤（>=3字符），因此入库数量（21,686）略少于 `filtered_terms.json` 中的数量（21,705）。
    │
    ▼
email_term_rag_pipeline/output/filtered_terms.json
    │
    ▼
[src/build_term_kb.py] ChromaDB 建库
    ├── 统一使用 BAAI/bge-large-zh-v1.5
    ├── 延迟导入 SentenceTransformer（兼容 PyTorch 2.2.2）
    ├── collection: clothing_terms（覆盖重建，非追加）
    └── 输出 term_kb_stats.json
    │
    ▼
vector_db/  (共享向量数据库)
    └── clothing_terms  ← 21,686 条术语向量
```

---

## 🎯 功能特性

### 1. 术语检索
- **语义检索**: 使用BGE嵌入模型，支持语义相似度匹配
- **中英双语**: 支持中英文互查
- **分类过滤**: 可按服装部位分类检索

### 2. RAG问答
- **翻译问答**: "拉链的英文是什么？"
- **解释问答**: "什么是暗门襟？"
- **模糊匹配**: 支持相似术语联想

### 3. 批量处理
```python
from email_term_rag_pipeline.src.rag_qa import ClothingRAG

rag = ClothingRAG()
terms = ["拉链", "纽扣", "袖口"]
results = rag.batch_translate(terms, direction="zh2en")
```

---

## 📊 数据说明

| 项目 | 数值 |
|------|------|
| 数据来源 | 《汉英英汉服装分类词汇》第4版 |
| 总页数 | 491页 |
| 实际词汇量 | 21,686 条（全量提取+过滤后入库） |
| 原始提取 | 22,091 条 |
| 过滤后 | 21,705 条 |
| 旧数据量 | ~2,890条（仅前100页，无分类，已弃用） |
| 分类数 | 8 个主要分类 |

### 主要分类（按数量排序）

| 分类 | 数量 |
|------|------|
| 设计打样设备和工具 | 11,946 |
| 服装设计制图·人体主要部位 | 2,688 |
| 款式名称 | 2,557 |
| 颜色 | 1,955 |
| 服饰品·帽 | 1,413 |
| 原辅料检验 | 774 |
| 服装成品·一般名称 | 267 |
| 线迹 | 105 |

---

## 🔧 配置选项

### 更换嵌入模型
编辑 `configs/kb_config.json`:
```json
{
  "embedding_model": "BAAI/bge-large-zh-v1.5"
}
```

### 调整检索参数
```python
from email_term_rag_pipeline.src.rag_qa import ClothingRAG
rag = ClothingRAG()
results = rag.retrieve("拉链", top_k=10)
```

---

## 🔄 与邮件系统集成（双轨 RAG）

本模块作为「术语 RAG」，与 `email_rag_pipeline`（邮件事件 RAG）、`email_kg_pipeline`（知识图谱）共同组成多模态检索架构：

```
用户查询
    │
    ▼
[意图路由器]
    │
    ├─ 术语/翻译查询 ──→ 术语 RAG (clothing_terms @ vector_db/)
    └─ 业务流程/时间线查询 ──→ 邮件 RAG (email_events @ vector_db/)
```

> 邮件系统调用术语 RAG 的集成代码已迁移至 `email_rag_pipeline/src/term_rag_integration.py`。

集成示例：
```python
from email_finetuning_pipeline.src.eml_data_processor import extract_text_from_eml
from email_term_rag_pipeline.src.rag_qa import ClothingRAG

rag = ClothingRAG()

def process_email_with_rag(email_path):
    email_data = extract_text_from_eml(email_path)
    content = email_data['content']
    
    technical_terms = extract_terms(content)
    translations = {}
    for term in technical_terms:
        result = rag.answer(f"{term}是什么意思？")
        translations[term] = result['answer']
    
    return {
        'original': content,
        'terms': translations
    }
```

---

## 💡 使用示例

### 示例1: 术语翻译
```
您的问题: 拉链的英文是什么？

回答:
"拉链" 的英文翻译是：
  zipper / slide fastener
  分类：拉链

其他相关术语：
- 隐形拉链 | invisible zipper
- 防水拉链 | waterproof zipper
```

### 示例2: 术语解释
```
您的问题: 什么是暗门襟？

回答:
关于 "暗门襟" (French front):

分类：衣大身
中英对照：暗门襟 | French front; plain front

相关术语：
- 贴门襟 (facing strap)
- 交叉门襟 (crossover placket)
```

### 示例3: 模糊检索
```
您的问题: coat相关词汇

回答:
为您找到以下相关术语：

1. 大衣
   英文: coat
   分类：外套

2. 毛皮大衣
   英文: fur coat
   分类：外套

3. 军大衣
   英文: military coat
   分类：外套
```

---

## 🔍 实现原理

```
PDF提取 (src/extract_pdf_terms.py)
  ↓
术语结构化 (chinese/english/category/page/type)
  ↓
质量过滤 + 去重
  ↓
文本嵌入 (BGE-large-zh-v1.5, 1024维)
  ↓
向量存储 (ChromaDB @ vector_db/, collection=clothing_terms)
  ↓
语义检索 (余弦相似度)
  ↓
结果生成 (答案组装)
```

---

## ⚠️ 注意事项

1. **首次运行**: 需要下载嵌入模型（约1-2GB），请确保网络畅通。国内用户建议设置 `export HF_ENDPOINT=https://hf-mirror.com`
2. **PDF 提取耗时**: 491 页完整提取约需 8-12 分钟，每 50 页自动保存断点
3. **存储空间**: 向量数据库约占用 100-200MB 磁盘空间（位于 `vector_db/`）
4. **macOS OpenMP 报错**: 已内置 `KMP_DUPLICATE_LIB_OK=TRUE` 修复，如仍报错请手动设置环境变量

---

## 📚 参考模型

| 模型 | 维度 | 语言 | 适用场景 |
|------|------|------|----------|
| BAAI/bge-large-zh-v1.5 | 1024 | 中英 | 推荐，效果最佳 |
| BAAI/bge-base-zh-v1.5 | 768 | 中英 | 速度更快 |
| moka-ai/m3e-base | 768 | 中英 | 中文优化 |

---

## 📄 License

MIT License
