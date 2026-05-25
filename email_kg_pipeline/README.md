# 邮件知识图谱 (Email Knowledge Graph)

基于 NetworkX 构建的轻量级知识图谱，用于表示邮件事件中的实体关系，补充向量 RAG 在关联查询上的不足。

## 架构定位

```
                    用户查询
                       │
                       ▼
            ┌─────────────────────┐
            │   意图路由器         │
            └─────────────────────┘
              │              │              │
    术语查询   │    时间线查询 │    关联查询   │
              │              │              │
              ▼              ▼              ▼
    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
    │   术语 RAG      │  │   邮件事件 RAG   │  │   知识图谱      │
    │ (ChromaDB)      │  │ (ChromaDB)      │  │ (NetworkX)      │
    │   21,686 条     │  │   7,893 条事件   │  │  10,610 节点    │
    │  语义检索        │  │  向量语义检索    │  │  实体关系查询   │
    └─────────────────┘  └─────────────────┘  └─────────────────┘
              │              │              │
              └──────────────┴──────────────┘
                             │
                             ▼
                      ┌─────────────┐
                      │  LLM 生成器  │
                      └─────────────┘
```

## 目录结构

```
email_kg_pipeline/
├── configs/
│   └── schema.json              # 图谱 Schema 定义
├── data/
│   ├── factory_mapping.csv      # 款号→工厂映射（用户提供）
│   └── organization.json        # 组织架构（用户提供）
├── output/
│   ├── kg_graph_with_customers.pkl   # 序列化图谱文件（含 Customer 节点）
│   └── kg_stats.json            # 图谱统计信息
├── scripts/
│   ├── run_build.sh             # 一键构建脚本
│   ├── test_queries.sh          # 查询测试脚本（V2 - 含 Customer）
│   └── test_queries.py          # Python 查询测试脚本（V2 - 含 Customer）
└── src/
    ├── kg_builder.py            # 图谱构建器（支持 Customer 节点）
    ├── kg_query.py              # 查询引擎（支持 Customer 查询）
    └── kg_updater.py            # 增量更新器
```

## 快速开始

### 1. 安装依赖

```bash
pip install networkx
```

### 2. 准备数据

需要四个数据源：

**A. 事件数据**（已有）
- 路径: `email_rag_pipeline/output/new/events_passed.json`
- 说明: 从邮件中提取的结构化事件（7,893 条）

**B. 工厂映射**（用户提供）
- 路径: `email_kg_pipeline/data/factory_mapping.csv`
- 格式:
  ```csv
  style_id,order_id,factory_name,factory_code,factory_location,contact_person,status,start_date
  CCSS230021,ORDER-2023-001,东台鸿丰服饰有限公司,HF001,江苏省东台市,黄厂长,合作中,2023-01-15
  ```

**C. 组织架构**（用户提供）
- 路径: `email_kg_pipeline/data/organization.json`
- 格式:
  ```json
  {
    "departments": [{"id": "dept_001", "name": "业务部", "manager": "u001"}],
    "users": [{"id": "u001", "name": "Paula Cheng", "department": "dept_001", "role": "高级跟单员", "reports_to": "u000"}],
    "style_assignments": [{"style_id": "CCSS230021", "primary_owner": "u001", "secondary_owners": ["u002"], "watchers": ["u005"]}]
  }
  ```

**D. 邮件摘要**（用于客户数据）
- 路径: `data/data-summary/email_summary.json`
- 说明: 从邮件摘要的 `company_people` 字段提取客户信息

### 3. 构建图谱

```bash
# 方式 1: 使用脚本（推荐，含 Customer 节点）
cd email_kg_pipeline && ./scripts/run_build.sh

# 方式 2: 使用 Python（默认参数，含 Customer 节点）
python3 email_kg_pipeline/src/kg_builder.py

# 方式 3: 显式指定所有路径
python3 email_kg_pipeline/src/kg_builder.py \
    --events email_rag_pipeline/output/new/events_passed.json \
    --factory email_kg_pipeline/data/factory_mapping.csv \
    --org email_kg_pipeline/data/organization.json \
    --email-summary data/data-summary/email_summary.json \
    --output email_kg_pipeline/output/kg_graph_with_customers.pkl

# 方式 4: 仅使用事件数据（跳过工厂、组织架构、客户数据）
python3 email_kg_pipeline/src/kg_builder.py --events-only
```

### 4. 查询测试

```bash
# 一键运行所有测试（含 Customer 查询）
./email_kg_pipeline/scripts/test_queries.sh

# 或单独查询
python3 email_kg_pipeline/scripts/test_queries.py --style CCSS230021
python3 email_kg_pipeline/scripts/test_queries.py --person "Paula Cheng"
python3 email_kg_pipeline/scripts/test_queries.py --customers --min-styles 1
python3 email_kg_pipeline/scripts/test_queries.py --customer heidi@curated-collective.co.uk --customer-detail
```

## 支持的查询

### 原有查询

| 查询 | 命令 | 示例 |
|-----|------|------|
| 款号涉及人员 | `people_by_style` | `kg_query.py --query people_by_style --param CCSS230021` |
| 人员参与款号 | `styles_by_person` | `kg_query.py --query styles_by_person --param "Paula Cheng"` |
| 协作对象 | `collaborators` | `kg_query.py --query collaborators --param "Paula Cheng"` |
| 款号时间线 | `timeline` | `kg_query.py --query timeline --param CCSS230021` |
| 最后更新 | `last_update` | `kg_query.py --query last_update --param CCSS230021` |
| 工厂延期 | `factory_delays` | `kg_query.py --query factory_delays` |
| 工厂款号 | `styles_by_factory` | `kg_query.py --query styles_by_factory --param HF001` |
| 部门款号 | `department_styles` | `kg_query.py --query department_styles --param 业务部` |
| 下属查询 | `subordinates` | `kg_query.py --query subordinates --param "Paula Cheng"` |

### 新增 Customer 查询（V2）

| 查询 | 方法 | 命令行示例 |
|-----|------|-----------|
| 款号关联客户 | `get_customers_by_style` | `test_queries.py --style CCSS230021` |
| 客户关联款号 | `get_styles_by_customer` | `test_queries.py --customer heidi@curated-collective.co.uk` |
| 客户列表 | `get_all_customers` | `test_queries.py --customers --min-styles 1` |
| 客户详情 | `get_customer_details` | `test_queries.py --customer heidi@... --customer-detail` |
| 多条件筛选（含客户） | `find_styles_with_conditions` | 代码调用 |

## 在代码中使用

```python
from email_kg_pipeline.src.kg_builder import EmailKnowledgeGraph
from email_kg_pipeline.src.kg_query import KGQueryEngine

# 加载图谱
kg = EmailKnowledgeGraph.load('email_kg_pipeline/output/kg_graph_with_customers.pkl')
engine = KGQueryEngine(kg)

# 查询某款号涉及的人员（含客户信息）
result = engine.get_people_by_style("CCSS230021")
print(result)
# {
#   "style_id": "CCSS230021",
#   "people": [...],
#   "primary_owner": "Paula Cheng",
#   "total_people": 12,
#   "customers": [
#     {"name": "Heidi Knight", "email": "heidi@curated-collective.co.uk"}
#   ],
#   "total_customers": 1
# }

# 直接遍历图谱获取 order_ids（API 暂未暴露）
G = kg.G
order_ids = G.nodes["Style:CCAW240015"].get("order_ids", [])
print(order_ids)  # ['144748739', '202441', '2024410', '310052']

# 直接遍历图谱获取 Event 的 source 字段
event_data = G.nodes["Event:evt_0"]
print(event_data["source_filename"])   # "1577.eml"
print(event_data["source_subject"])    # "转发: EB- CCAW240015 ..."

# 查询客户关联的款号
result = engine.get_styles_by_customer("heidi@curated-collective.co.uk")
print(result)
# {
#   "customer": "heidi@curated-collective.co.uk",
#   "customer_name": "Heidi Knight",
#   "styles": [
#     {"style_id": "CCSS230001", "event_count": 24, "latest_category": "调纸样"},
#     ...
#   ],
#   "total_styles": 12
# }

# 查询客户详情（含关联人员和工厂）
result = engine.get_customer_details("heidi@curated-collective.co.uk")
print(result)
# {
#   "customer": {"name": "Heidi Knight", "email": "...", "style_count": 12},
#   "styles": [...],
#   "related_people": ["Paula Cheng", "Iris Jiang", ...],
#   "related_factories": ["东台鸿丰服饰有限公司", ...]
# }

# 多条件筛选：某客户的延期款号
result = engine.find_styles_with_conditions(
    customer_email="heidi@curated-collective.co.uk",
    min_delay_days=1
)
print(result)

# 查询最后更新时间
result = engine.get_last_update("CCSS230021")
print(result)
# {
#   "style_id": "CCSS230021",
#   "last_update": "2025-08-20",
#   "days_since_update": 243
# }

# 查询工厂延期统计
result = engine.get_factory_delays(top_k=5)
print(result)
# {
#   "factories": [
#     {"name": "东台鸿丰", "total_delay_days": 1858, "avg_delay": 10.9},
#     ...
#   ]
# }
```

## 增量更新

```python
from email_kg_pipeline.src.kg_builder import EmailKnowledgeGraph
from email_kg_pipeline.src.kg_updater import KGUpdater

kg = EmailKnowledgeGraph.load('email_kg_pipeline/output/kg_graph_with_customers.pkl')
updater = KGUpdater(kg)

# 添加新事件（从 LLM 提取）
new_event = {
    "style_id": "CCSS230021",
    "category": "出货",
    "event_type": "确认",
    "date": "2025-08-20",
    "party_from": "工厂",
    "party_to": "客人",
    "description": "款号 CCSS230021 确认出货",
    "source_filename": "new_email.eml"
}

result = updater.add_event(new_event)
# {
#   "success": true,
#   "event_id": "evt_7893",
#   "updated_properties": {
#     "Style:CCSS230021": {"last_update": "2025-08-20", "event_count": 61}
#   }
# }

kg.save()
```

## Schema 设计

### 节点类型

| 类型 | 数量 | 说明 |
|-----|------|------|
| Event | 7,893 | 邮件提取的业务事件 |
| Style | 1,166 | 服装款号（含 `order_ids` 聚合属性） |
| Person | 282 | 参与人员 |
| Category | 23 | 业务阶段 |
| Email | 1,206 | 来源邮件 |
| Factory | 7 | 生产工厂（用户提供） |
| Department | 6 | 部门（用户提供） |
| **Customer** | **27** | **客户（从邮件摘要提取）** |

### 关系类型

| 关系 | 说明 |
|-----|------|
| BELONGS_TO | 事件属于某款号 |
| HAS_CATEGORY | 事件属于某阶段 |
| PARTICIPATED_IN | 人员参与事件 |
| INVOLVED_IN | 人员参与款号 |
| RESPONSIBLE_FOR | 人员负责某款号 |
| COLLABORATED_WITH | 人员协作关系 |
| REPORTS_TO | 汇报关系 |
| BELONGS_TO_DEPT | 人员属于部门 |
| PRODUCED_BY | 款号由工厂生产 |
| FROM_EMAIL | 事件来源邮件 |
| FOLLOWS | 事件时序关系 |
| MANAGES | 人员管理部门 |
| **HAS_STYLE** | **客户拥有款号** |
| **ORDERED_BY** | **款号被客户订购** |

### Style 节点属性（含新增）

| 属性 | 类型 | 说明 |
|-----|------|------|
| `style_id` | string | 款号唯一标识 |
| `first_event_date` | string | 最早事件日期 |
| `last_update` | string | 最后事件更新日期 |
| `event_count` | int | 关联事件总数 |
| `total_delay_days` | int | 累计延期天数 |
| `delay_event_count` | int | 含延期的事件数 |
| `latest_category` | string | 最新事件所属阶段 |
| **`order_ids`** | **list** | **关联的所有订单号列表（从邮件事件聚合，82.6% 覆盖率）** |

### Customer 节点属性

| 属性 | 类型 | 说明 |
|-----|------|------|
| email | string | 客户邮箱 |
| name | string | 客户名称 |
| source | string | 来源字段（如 "Indochine UK"） |
| style_count | int | 关联款号数量 |
| style_list | list | 关联款号列表 |

## 客户数据来源

客户数据从 `data/data-summary/email_summary.json` 的 `company_people` 字段提取：

```python
CUSTOMER_SOURCE_FIELDS = [
    "Indochine UK",                      # UK 客户，indochine.co.uk 域名
    "Curated Collective (客户/合作方)",   # UK 客户，.co.uk 域名
]
```

**活跃客户（有款号关联）：**

| 客户 | 邮箱 | 款号数 | 来源 |
|------|------|--------|------|
| Heidi Knight | heidi@curated-collective.co.uk | 12 | Curated Collective |
| Michelle Evatt | michelle@curated-collective.co.uk | 8 | Curated Collective |
| Emma Townsend | emma@curated-collective.co.uk | 3 | Curated Collective |
| Tarun Goenka | tarun@indochine.co.uk | 2 | Indochine UK |
| Charles Allen | charles@indochine.co.uk | 1 | Indochine UK |

## 与 RAG 的协作

| 问题类型 | 使用系统 | 原因 |
|---------|---------|------|
| "拉链的英文" | RAG | 语义检索 |
| "CCSS230021 最后更新" | 图谱 | O(1) 属性查询 |
| "哪个工厂延期最多" | 图谱 | 全局聚合 |
| "负责人都是谁" | 图谱 | 关系遍历 |
| "出货详情描述" | RAG | 文本语义匹配 |
| "Paula 的下属" | 图谱 | 组织架构遍历 |
| **"Heidi 有哪些款号"** | **图谱** | **客户-款号关系遍历** |
| **"CCSS230011 的客户是谁"** | **图谱** | **款号-客户关系查询** |
| **"CCAW240015 有哪些订单号"** | **图谱** | **Style 节点的 `order_ids` 属性** |
| **"1577.eml 里说了什么"** | **RAG/图谱** | **按 `source_filename` 过滤** |

## 注意事项

1. **数据一致性**: RAG 和图谱各自维护，通过 `style_id` 关联。更新时先写 `events.json`，再同步到两个系统。

2. **工厂数据**: 已提供 966 条工厂映射，覆盖主要款号。

3. **组织架构**: 已提供 42 人 + 6 部门 + 50 款号分配。

4. **客户数据**: 从 `email_summary.json` 自动提取，基于 `top_senders`/`top_recipients` 中的 `style_list` 建立客户-款号关联。

5. **人员名归一化**: 在 `kg_builder.py` 的 `NAME_NORMALIZATION` 中配置大小写变体合并规则。

6. **持久化**: 当前使用 pickle 序列化。数据量增大后可迁移到 Neo4j。

7. **`order_ids` 来源**: 从邮件事件的 `order_id` 字段聚合而来。一个款号可能关联多个订单号（如 `CCAW240015` 有 4 个），一个订单号也可能关联多个款号（如 `310052` 关联 100+ 款号）。

8. **`source_filename`/`source_subject`**: Event 节点直接存储这两个字段（覆盖率 100%），同时通过 `FROM_EMAIL` 关系关联到 Email 节点，支持双向追溯。
