# 桌面应用（Tauri）说明

本文档说明基于 Tauri 2 的桌面端（macOS / Windows）。桌面端定位是**查看器**：把现有 React 前端封装为桌面应用，Nest.js 后端以 sidecar 单文件随应用启动，用户通过文件选择指定 SQLite 数据库。桌面端**不新增采集功能、不修改 Python 脚本行为、不改变浏览器端（`npm run dev` + Vite proxy）既有用法**。

## 1. 概述

- **壳**：Tauri 2（Rust），位于 `src-tauri/`，用系统 WebView 承载前端产物。
- **前端**：`frontend/` 沿用 React 18 + Vite 5，构建产物 `frontend/dist` 被嵌入应用。桌面环境使用 **HashRouter**（WebView 内无服务端路由回退）。
- **后端**：`backend/` 的 Nest.js 应用被 `@yao-pkg/pkg` 打包为单文件二进制 `src-tauri/binaries/backend-<target-triple>`，作为 Tauri `externalBin` sidecar，由 Rust 在应用启动时拉起并注入环境变量。
- **数据采集**：仍由 Python 脚本（Akshare → SQLite）离线完成，桌面端只读所选 SQLite 数据库。

## 2. 架构

```
┌────────────────────────────────────────────────────────────┐
│                    Tauri 2 桌面应用（WebView）                 │
│   React（HashRouter，#/stocks 等）                           │
│   └── http  ─────────────────────────────┐                  │
└──────────────────────────────────────────│──────────────────┘
                                           │ HTTP (REST / JSON)
┌──────────────────────────────────────────▼──────────────────┐
│            Backend sidecar（pkg 单文件二进制）                 │
│   Nest.js  @ :3100   env: PORT=3100  DB_PATH=<db_path>      │
│   stdout/stderr → 控制台 [backend] 日志                       │
└──────────────────────────────────────────┬──────────────────┘
                                           │ 文件读写
                               ┌───────────▼───────────┐
                               │   SQLite 数据库文件     │
                               │  db_path.txt 指定的库    │
                               └───────────────────────┘
```

关键运行参数：

| 项 | 说明 |
|----|------|
| 前端路由 | HashRouter（URL 形如 `#/stocks`） |
| API 基址（桌面） | `http://localhost:3100/api`（直连 sidecar） |
| API 基址（浏览器） | `/api`（Vite proxy → `:3100`） |
| sidecar 环境变量 | `PORT=3100`、`DB_PATH=<用户选择或默认路径>` |
| 配置目录 | `app_config_dir`（macOS：`~/Library/Application Support/com.mstock.desktop/`） |
| 数据库路径持久化 | 配置目录下 `db_path.txt`（一行文本） |

## 3. 关键文件

| 路径 | 说明 |
|------|------|
| `src-tauri/src/lib.rs` | Rust 壳：spawn / kill sidecar、`resolve_db_path`、`get_db_path` / `set_db_path` 命令 |
| `src-tauri/tauri.conf.json` | bundle 配置，`externalBin: ["binaries/backend"]` |
| `src-tauri/binaries/` | sidecar 产物目录（gitignored） |
| `backend/build-sidecar.mjs` | sidecar 构建脚本：`nest build` → `pkg` → 重命名为 `backend-<triple>` |
| `backend/package.json` | `pkg` 配置（`assets` 含 better-sqlite3 `.node` 与 `database/schema.sql`） |
| `backend/src/database/database.service.ts` | pkg 快照内原生模块引导（复制 `.node` 到真实磁盘） |
| `frontend/src/config.ts` | `IS_TAURI` / `API_BASE_URL` 按环境切换 |
| `frontend/src/components/DbPicker.tsx` | 「数据源」选择入口 |
| `.github/workflows/desktop-release.yml` | 跨平台构建 / 发布 CI |

## 4. 开发与构建命令

### 4.1 前置条件

- Node.js ≥ 22（`@yao-pkg/pkg` 的 target 为 `node22-*`）
- Rust toolchain（Tauri 2 前置：macOS 需 Xcode Command Line Tools；Windows 需 MSVC）
- 首次需先安装前端 / 后端依赖（`cd frontend && npm install`、`cd backend && npm install`）

### 4.2 桌面开发模式

```bash
cd backend && npm run build:sidecar   # 首次 / 后端改动后：生成 sidecar 二进制
npx --prefix frontend tauri dev       # 桌面开发（自动拉起 Vite + sidecar）
```

说明：`tauri dev` 会执行 `beforeDevCommand`（`npm run dev`）拉起 Vite 开发服务器，Rust 在 `setup()` 中 spawn sidecar，WebView 通过 `http://localhost:3100/api` 直连后端。

### 4.3 打包分发

```bash
cd backend && npm run build:sidecar
npx --prefix frontend tauri build
```

产物位于 `src-tauri/target/release/bundle/`（macOS 为 `.app` / `.dmg`，Windows 为 `.msi` / `.exe`）。

### 4.4 CI 发布

`.github/workflows/desktop-release.yml` 会在 **`release` 分支 push** 或 **手动 `workflow_dispatch`** 时构建 macOS arm64 / x64 + Windows 三套产物（draft release）。CI 在各自平台 runner 上先 `npm run build:sidecar` 再调用 `tauri-action`。

## 5. Sidecar 生命周期

```
应用启动
  └─ setup(): resolve_db_path() 决定 DB_PATH
        └─ shell().sidecar("backend").env(PORT=3100).env(DB_PATH=...).spawn()
              └─ stdout/stderr 转发为 [backend] 日志
              └─ 后端监听 http://localhost:3100/api，提供全部 /api 接口
应用正常退出（关窗 / App Quit）
  └─ RunEvent::ExitRequested | Exit → child.kill() → 后端随应用一并关闭，:3100 释放
```

要点：

- sidecar 由 Rust 在 `setup()` 中 spawn，注入 `PORT=3100` 与 `DB_PATH`；后端所有接口经 `http://localhost:3100/api` 提供。
- 退出钩子挂在 `RunEvent::ExitRequested | Exit` 双分支（`take()` 保证不重复 kill）。
- **强杀（SIGTERM / 任务管理器强杀）不会触发上述钩子**，sidecar 会变成孤儿进程继续占用 `:3100`。此时需手动清理，见[已知限制](#9-已知限制)。

## 6. 数据库选择流程

启动时 Rust 按以下优先级解析 `DB_PATH`（`resolve_db_path`）：

1. 配置目录下 `db_path.txt` 中保存的用户选择；
2. 开发期仓库根 `data/market.db`（与后端非 pkg 时的默认路径一致）；
3. 均不满足时，在配置目录下新建空库 `market.db`（schema 自动建表）。

用户切换数据库流程：

```
点击「数据源」→ 原生文件对话框选择 .db 文件
  → invoke set_db_path 写入 app_config_dir/db_path.txt
  → 提示「已保存数据库路径，请重启应用生效。」
重启应用 → resolve_db_path() 读取 db_path.txt → DB_PATH 注入 sidecar → 数据来自所选库
```

要点：

- **更换数据库后必须重启应用**：`DB_PATH` 在启动时读取并注入 sidecar，运行中切换不生效。
- 若用户从未选择数据库，应用会在配置目录创建空库（fresh DB 自动建表，见[打包注意事项](#8-打包注意事项)）。

## 7. 打包 / 分发 / 签名

### 7.1 sidecar 打包

`npm run build:sidecar`（即 `backend/build-sidecar.mjs`）依次：

1. `nest build` 产出 `backend/dist`；
2. `npx @yao-pkg/pkg dist/main.js` 打包为单文件（pkg target 按 host 平台/架构选择，**原生模块无法交叉编译**）；
3. 重命名为 Tauri externalBin 约定的 `src-tauri/binaries/backend-<target-triple>`（Windows 带 `.exe`）。

### 7.2 应用打包

`tauri build` 构建前端、嵌入 WebView 资产与 sidecar，产出安装包。

### 7.3 签名与公证

- macOS 对外分发需**签名 + 公证**，否则他机打开会被 Gatekeeper 拦截；Windows 建议代码签名。
- 当前 `.github/workflows/desktop-release.yml` 仅配置 `GITHUB_TOKEN`，**未配置签名/公证密钥**（如 `APPLE_CERTIFICATE` / `APPLE_SIGNING_IDENTITY` 等），CI 产物为未签名安装包，仅供自测/内部使用。
- 对外正式分发请按 Tauri 官方 "Signing & Notarizing" 文档补充签名配置。

## 8. 打包注意事项

1. **macOS DMG 打包在无 GUI 环境会失败**：`tauri build` 的 DMG 步骤会调用 create-dmg 的 Finder AppleScript 美化流程，在 headless / CI 类环境可能报 `AppleEvent timed out`（-1712）。解决：`CI=true npx --prefix frontend tauri build`（tauri CLI 会把 `CI` 传给 `bundle_dmg.sh` 跳过该步骤）。注意 tauri CLI 会误解析 `CI=1`，需用 **`CI=true`**；GitHub Actions 默认就是 `CI=true`，因此 CI 不受影响。
2. **`.env` 会被打进 sidecar**：pkg 打包会把仓库根 `.env`（含 LLM 密钥）快照进二进制。因此**本地构建的 DMG/`.app` 内嵌本机 `.env`**，仅适合本地自测，请勿对外分发；对外分发请走 CI（全新 checkout，无 `.env`）。若修改了 `.env` 或相关环境变量，需重新 `npm run build:sidecar` 才会生效。
3. **`tauri dev` / `tauri build` 会污染 `src-tauri/Cargo.toml`**：Tauri CLI 在 run/build 时会向依赖追加 `features = []`（功能等价，无行为差异）。提交前请 `git diff src-tauri/Cargo.toml` 检查并还原。
4. **better-sqlite3 原生模块**：pkg 打包必须把 `.node` 放进 `pkg.assets`（`node_modules/better-sqlite3/prebuilds/*.node`）；快照内 VFS 路径无法被 `dlopen`，`database.service.ts` 顶部引导逻辑会在 `process.pkg` 下把 `.node` 复制到真实磁盘并接管 `require.resolve`。`pkg.assets` 还必须包含 `database/schema.sql`，否则 fresh DB 无法自动建表（后端启动但 11 张表全缺）。

## 9. 已知限制

1. **强杀会导致 sidecar 孤儿**：对 Tauri 进程 `SIGTERM` / 强杀不会触发 Rust 的 kill-on-exit（`RunEvent::ExitRequested | Exit`），sidecar 会孤儿化并继续占用 `:3100`。请通过正常关窗 / App Quit 退出；若出现孤儿，手动清理：
   ```bash
   lsof -nP -i :3100      # 查看占用 :3100 的 PID
   kill <pid>             # 清理孤儿 sidecar
   ```
2. **原生文件对话框与「重启生效」提示需人工**：「数据源」选择（dialog）和保存后的提示（`@tauri-apps/plugin-dialog` 的 `message()`）需要人类交互；WebView 页面渲染本身也无法脚本化验证。
3. **`alert()` 在 WKWebView 中是空操作**：应用改用 dialog 插件的 `message()` 展示「重启生效」提示，请勿改回 `alert()`。
4. **未选择数据库时会新建空库**：若从未通过「数据源」选择 DB，应用会在配置目录创建 fresh 空库（schema 自动应用）。此时页面数据为空属预期。
5. **ETF K 线图显示「暂无 K 线数据」（预存在，非本次迁移引入）**：前端 `getKline` 默认 `adjust=qfq`，而数据库仅存 ETF 不复权数据（adjustflag=3，见 CLAUDE.md「新浪 ETF 源仅不复权」）。**桌面端与浏览器端同样受影响**，除非显式传 `adjust=raw`。
