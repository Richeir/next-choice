# 桌面应用（Tauri）说明

本文是桌面端相关说明的**单一维护点**：架构、开发模式、sidecar 生命周期、数据库选择、打包与发布、已知限制均以本文为准；根目录 `README.md` 与 `CLAUDE.md` 只保留摘要并指向本文，不重复展开细节。

桌面端定位是**查看器**：把现有 React 前端封装为 Tauri 2 桌面应用（macOS / Windows），Nest.js 后端以 sidecar 单文件随应用启动，用户通过文件选择指定 SQLite 数据库。桌面端**不新增采集功能、不修改 Python 脚本行为、不影响浏览器端（`npm run dev` + Vite proxy）既有用法**。

## 1. 概述与定位

- **壳**：Tauri 2（Rust），位于 `desktop/`，用系统 WebView 承载前端产物。
- **前端**：`frontend/` 沿用 React 18 + Vite 5，构建产物 `frontend/dist` 被嵌入应用。桌面环境使用 **HashRouter**（WebView 内无服务端路由回退）。
- **后端**：`backend/` 的 Nest.js 应用被 `@yao-pkg/pkg` 打包为单文件二进制 `desktop/binaries/backend-<target-triple>`，作为 Tauri `externalBin` sidecar，由 Rust 在应用启动时拉起并注入环境变量。
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
│   Nest.js @ :3100                                            │
│   env: PORT=3100  DB_PATH=<db_path>  CORS_ORIGIN=<白名单>     │
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
| sidecar 环境变量 | `PORT=3100`、`DB_PATH=<解析结果>`、`CORS_ORIGIN=<来源白名单>` |
| CORS 白名单 | release 仅 Tauri WebView 来源；debug 构建另放行 `http://localhost:5173`（见 §3.3） |
| 配置目录 | `app_config_dir`（macOS：`~/Library/Application Support/com.mstock.desktop/`） |
| 数据库路径持久化 | 配置目录下 `db_path.txt`（一行文本） |

关键文件：

| 路径 | 说明 |
|------|------|
| `desktop/src/lib.rs` | Rust 壳：spawn / kill sidecar、`resolve_db_path`、`get_db_path` / `set_db_path` 命令、CORS 白名单注入 |
| `desktop/tauri.conf.json` | bundle 配置，`externalBin: ["binaries/backend"]` |
| `desktop/binaries/` | sidecar 产物目录（gitignored，见根 `.gitignore`） |
| `backend/build-sidecar.mjs` | sidecar 构建脚本：`nest build` → `pkg` → 重命名为 `backend-<triple>`，含 `.env` 内嵌告警守卫 |
| `backend/package.json` | `pkg` 配置（`assets` 含 better-sqlite3 `.node` 与 `database/schema.sql`） |
| `backend/src/database/database.service.ts` | pkg 快照内原生模块引导（复制 `.node` 到真实磁盘） |
| `frontend/src/config.ts` | `IS_TAURI` / `API_BASE_URL` 按环境切换 |
| `frontend/src/components/DbPicker.tsx` | 「数据源」选择入口 |
| `.github/workflows/desktop-release.yml` | 跨平台构建 / 发布 CI |

## 3. 开发模式

### 3.1 前置条件

- Node.js ≥ 22（`@yao-pkg/pkg` 的 target 为 `node22-*`）
- Rust toolchain（Tauri 2 前置：macOS 需 Xcode Command Line Tools；Windows 需 MSVC）
- 首次需先安装前端 / 后端依赖（`cd frontend && npm install`、`cd backend && npm install`）

### 3.2 桌面开发

```bash
cd backend && npm run build:sidecar   # 首次 / 后端改动后：生成 sidecar 二进制
npx --prefix frontend tauri dev       # 在仓库根执行；CLI 会自动发现 desktop/tauri.conf.json
```

说明：

- `tauri dev` 会执行 `beforeDevCommand`（`npm run dev`）拉起 Vite 开发服务器（`:5173`），Rust 在 `setup()` 中 spawn sidecar，WebView 通过 `http://localhost:3100/api` 直连后端。
- **`tauri dev` / `tauri build` 会污染 `desktop/Cargo.toml`**：Tauri CLI 在 run/build 时会向依赖追加 `features = []`（功能等价，无行为差异）。提交前请 `git diff desktop/Cargo.toml` 检查并还原。

### 3.3 CORS 行为

后端以环境变量 `CORS_ORIGIN` 控制跨域白名单（逗号分隔多个 origin，见 `backend/src/main.ts`）；**未设置该变量时缺省放行全部 origin**。各场景取值：

| 场景 | CORS_ORIGIN | 效果 |
|------|-------------|------|
| 浏览器 dev / 独立部署后端 | 未设置 | 放行全部 origin（Vite proxy 同源转发本不触发跨域；前端产物脱离代理独立部署时依赖此缺省） |
| 桌面 release（`tauri build` 产物） | `tauri://localhost,http://tauri.localhost` | 仅放行 Tauri WebView 来源（macOS WKWebView 用 `tauri://localhost`，Windows/Linux WebView2 用 `http://tauri.localhost`） |
| 桌面 debug（`tauri dev`） | 上值追加 `,http://localhost:5173` | debug 下 WebView 页面来源是 devUrl（Vite `:5173`），需额外放行 |

设计动机：sidecar 是常驻本机 `:3100` 的服务，若保持「放行全部」，任意网页可直接读写它（含 `POST /api/analyze` 触发 LLM 配额消耗）。因此由 Rust 在 spawn 时按构建类型（`cfg!(debug_assertions)`）注入收紧后的白名单（`desktop/src/lib.rs`）。

## 4. Sidecar 生命周期

```
应用启动
  └─ setup(): resolve_db_path() 决定 DB_PATH
        └─ shell().sidecar("backend")
              .env(PORT=3100).env(DB_PATH=...).env(CORS_ORIGIN=...)
              .spawn()
              └─ stdout/stderr 转发为 [backend] 日志
              └─ 后端监听 http://localhost:3100/api，提供全部 /api 接口
应用正常退出（关窗 / App Quit）
  └─ RunEvent::ExitRequested | Exit → child.kill() → 后端随应用一并关闭，:3100 释放
```

要点：

- sidecar 由 Rust 在 `setup()` 中 spawn，注入 `PORT=3100`、`DB_PATH` 与 `CORS_ORIGIN`；后端所有接口经 `http://localhost:3100/api` 提供。
- 退出钩子挂在 `RunEvent::ExitRequested | Exit` 双分支（`take()` 保证不重复 kill）。
- **强杀（SIGTERM / 任务管理器强杀）不会触发上述钩子**，sidecar 会变成孤儿进程继续占用 `:3100`。此时需手动清理，见[已知限制](#7-已知限制)。

## 5. 数据库选择流程

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
- 若用户从未选择数据库，应用会在配置目录创建空库（fresh DB 自动建表，schema 经 pkg assets 打包，见[sidecar 打包](#61-sidecar-打包)）。

## 6. 打包与发布

### 6.1 sidecar 打包

`npm run build:sidecar`（即 `backend/build-sidecar.mjs`）依次：

1. `nest build` 产出 `backend/dist`；
2. `npx @yao-pkg/pkg dist/main.js --target <node22-*>` 打包为单文件（pkg target 按 host 平台/架构选择，**原生模块无法交叉编译**）；
3. 重命名为 Tauri externalBin 约定的 `desktop/binaries/backend-<target-triple>`（Windows 带 `.exe`）。

pkg 打包两个必要条件：

- **better-sqlite3 原生模块**：`.node` 必须放进 `pkg.assets`（`node_modules/better-sqlite3/prebuilds/*.node`）；快照内 VFS 路径无法被 `dlopen`，`database.service.ts` 顶部引导逻辑会在 `process.pkg` 下把 `.node` 复制到真实磁盘并接管 `require.resolve`。
- **schema.sql 必须随包**：`pkg.assets` 还包含 `database/schema.sql`，否则 fresh DB 无法自动建表（后端启动但 11 张表全缺）。

### 6.2 应用打包

```bash
npx --prefix frontend tauri build
```

`tauri build` 构建前端、嵌入 WebView 资产与 sidecar，产物位于 `desktop/target/release/bundle/`（macOS 为 `.app` / `.dmg`，Windows 为 `.msi` / `.exe`）。

- **macOS DMG 打包在无 GUI 环境会失败**：DMG 步骤会调用 create-dmg 的 Finder AppleScript 美化流程，在 headless / CI 类环境可能报 `AppleEvent timed out`（-1712）。解决：`CI=true npx --prefix frontend tauri build`（tauri CLI 会把 `CI` 传给 `bundle_dmg.sh` 跳过该步骤）。注意 tauri CLI 会误解析 `CI=1`，需用 **`CI=true`**；GitHub Actions 默认就是 `CI=true`，因此 CI 不受影响。

### 6.3 分发安全：本地构建内嵌 `.env`

pkg 打包会把仓库根 `.env`（含 LLM 密钥）快照进二进制，`build-sidecar.mjs` 对此有告警守卫。因此**本地构建的 DMG/`.app` 内嵌本机 `.env`**，仅适合本地自测，请勿对外分发；对外分发请走 CI（全新 checkout，无 `.env`）。若修改了 `.env` 或相关环境变量，需重新 `npm run build:sidecar` 才会生效。

### 6.4 签名与公证

- macOS 对外分发需**签名 + 公证**，否则他机打开会被 Gatekeeper 拦截；Windows 建议代码签名。
- 当前 `.github/workflows/desktop-release.yml` 仅配置 `GITHUB_TOKEN`，**未配置签名/公证密钥**（如 `APPLE_CERTIFICATE` / `APPLE_SIGNING_IDENTITY` 等），CI 产物为未签名安装包，仅供自测/内部使用。
- 对外正式分发请按 Tauri 官方 "Signing & Notarizing" 文档补充签名配置。

### 6.5 CI 发布

`.github/workflows/desktop-release.yml` 在 **`release` 分支 push** 或 **手动 `workflow_dispatch`** 时触发，产出 macOS arm64 / x64 + Windows 三套 draft release 安装包：

- runner 矩阵：arm64 用默认 `macos-latest`（arm64 runner）；x86_64 必须用 Intel runner `macos-13`（arm64 runner 无法编译 x64 原生模块）；Windows 用 `windows-latest`。
- 各平台 runner 上先 `npm ci` 安装前后端依赖，再 `npm run build:sidecar` 构建 sidecar，最后调用 `tauri-apps/tauri-action` 打包并创建 draft release。

## 7. 已知限制

1. **强杀会导致 sidecar 孤儿**：对 Tauri 进程 `SIGTERM` / 强杀不会触发 Rust 的 kill-on-exit（`RunEvent::ExitRequested | Exit`），sidecar 会孤儿化并继续占用 `:3100`。请通过正常关窗 / App Quit 退出；若出现孤儿，手动清理：
   ```bash
   lsof -nP -i :3100      # 查看占用 :3100 的 PID
   kill <pid>             # 清理孤儿 sidecar
   ```
2. **原生文件对话框与「重启生效」提示需人工**：「数据源」选择（dialog）和保存后的提示（`@tauri-apps/plugin-dialog` 的 `message()`）需要人类交互；WebView 页面渲染本身也无法脚本化验证。
3. **`alert()` 在 WKWebView 中是空操作**：应用改用 dialog 插件的 `message()` 展示「重启生效」提示，请勿改回 `alert()`。
4. **未选择数据库时会新建空库**：若从未通过「数据源」选择 DB，应用会在配置目录创建 fresh 空库（schema 自动应用）。此时页面数据为空属预期。
5. **ETF K 线图显示「暂无 K 线数据」（预存在 bug，非桌面迁移引入）**：前端 `getKline` 默认 `adjust=qfq`（`frontend/src/api/index.ts`），而数据库仅存 ETF 不复权数据（adjustflag=3，见 CLAUDE.md「新浪 ETF 源仅不复权」）。**桌面端与浏览器端同样受影响**，除非显式传 `adjust=raw`。
