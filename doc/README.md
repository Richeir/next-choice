# doc 文档索引

本目录存放项目的设计文档。MVP0 为前期纯设计阶段，覆盖：系统架构、技术栈、数据库、后端 API、LLM 分析、前端页面。

## 文档列表

| 文件 | 内容 | 状态 |
|------|------|------|
| [architecture.md](architecture.md) | 系统总体架构、前后端数据流 | 新 |
| [tech-stack.md](tech-stack.md) | 技术栈选型与版本 | 新 |
| [api-design.md](api-design.md) | 自研 Nest.js 后端 API 设计 | 新 |
| [db-design.md](db-design.md) | SQLite 数据库设计（11 张表） | 已有 |
| [baostock-api.md](baostock-api.md) | BaoStock 数据源 API 参考 | 已有 |
| [llm-analysis.md](llm-analysis.md) | LLM 分析设计：提示词模板 + 输出 schema | 新 |
| [backend/modules.md](backend/modules.md) | Nest.js 模块划分与数据访问层 | 新 |
| [frontend/pages.md](frontend/pages.md) | React 前端页面设计 | 新 |

## 阅读顺序建议

1. 先读 [architecture.md](architecture.md) 了解整体。
2. 再读 [tech-stack.md](tech-stack.md) 与 [db-design.md](db-design.md) 明确技术底座与数据。
3. 随后读 [api-design.md](api-design.md) 与 [backend/modules.md](backend/modules.md) 理解后端。
4. 最后读 [llm-analysis.md](llm-analysis.md) 与 [frontend/pages.md](frontend/pages.md)。
