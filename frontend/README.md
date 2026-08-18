# M·STOCK 前端

React 18 + Vite 5 + TypeScript + React Router 6 + Axios + ECharts。

页面设计见 [doc/frontend/pages.md](../doc/frontend/pages.md)，API 约定见 [doc/api-design.md](../doc/api-design.md)。

## 开发

```bash
# 1. 启动后端（默认 http://localhost:3100）
cd ../backend && npm run start:prod

# 2. 启动前端（http://localhost:5173，/api 自动代理到后端）
npm install
npm run dev
```

## 测试 / 构建

```bash
npm test        # vitest 页面级测试（mock API）
npm run build   # tsc + vite 生产构建（产物在 dist/）
```

## 页面

| 路由 | 页面 |
|------|------|
| `/` | 首页统计卡片 |
| `/stocks` | 股票列表（筛选 / 排序 / 分页） |
| `/etfs` | ETF 列表 |
| `/stocks/:code` | 股票详情（分析卡片 + 关键指标 + K 线） |
| `/etfs/:code` | ETF 详情 |

## 已知限制（MVP）

- “已分析 / 待分析”状态筛选：后端暂不支持按分析状态过滤，前端按当前页客户端过滤。
- 首页 ETF 卡片的“已分析”数：stats 接口仅提供股票+ETF 合计 `analyzedCnt`，ETF 卡片按同一数值计算并封顶 100%。
- 行业 / 管理人下拉选项从已加载数据累积（后端无字典接口）。
- 涨跌配色以设计图为准（绿涨红跌），与 pages.md §6 文字描述（涨红跌绿）不一致，以图为准。
