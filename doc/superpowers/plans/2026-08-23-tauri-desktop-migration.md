# 前端桌面化（Tauri 2 + Nest.js sidecar）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改采集工作流（查看器型）的前提下，把现有 React 前端封装为兼容 macOS / Windows 的 Tauri 2 桌面应用，Nest.js 后端以 sidecar 单文件随应用启动，用户通过文件选择指定 SQLite 数据库。

**Architecture:** 新增 `src-tauri/`（Rust 壳）与现有 `frontend/`（React 产物）、`backend/`（Nest.js）平级。前端改为 HashRouter、API baseURL 按环境切换；后端用 `@yao-pkg/pkg` 打包成单文件二进制，作为 Tauri `externalBin` sidecar，由 Rust 启动时注入 `PORT`/`DB_PATH` 环境变量；数据库路径由前端通过 dialog 选择并落盘到应用配置目录。桌面端仍然只读数据库，Python 采集脚本与浏览器端部署方式保持不变。

**Tech Stack:** Tauri 2（Rust）、React 18 / Vite 5（沿用）、Nest.js 10 / better-sqlite3（沿用）、@yao-pkg/pkg（Node 22/24 target）、tauri-plugin-shell、tauri-plugin-dialog。

**Spec:** 本计划即规格。设计决策来源于本仓库作者的设计讨论（2026-08-23）：选 Tauri 2 而非 Electron；选「查看器型」即不在桌面内集成 Python 采集；后端以 sidecar 本地服务方式进桌面（方案 A），不做内嵌直连重构。相关既有文档：`doc/architecture.md`、`doc/api-design.md`、`backend/src/database/database.service.ts`（`DB_PATH`）、`backend/src/main.ts`（`PORT`）。

## Global Constraints

- 交互/文档用简体中文；代码、命令、文件名、提交信息用英文（遵循仓库 CLAUDE.md）。
- 提交信息遵循 Conventional Commits：`<type>(<scope>): <subject>`，subject 英文祈使句 ≤50 字符。
- 桌面端只是查看器：不新增采集功能，不修改 Python 脚本行为，不改变浏览器端（`npm run dev` + Vite proxy）既有用法。
- sidecar 环境变量：`PORT=3100`、`DB_PATH=<用户选择或默认>`；后端 `main.ts` 与 `database.service.ts` 已支持这两个变量，不改后端源码除非打包必需。
- `@yao-pkg/pkg` 要求构建机 Node >= 22（target `node22-*`）。构建 sidecar 前需 `node --version` 确认。
- better-sqlite3 是原生模块，pkg 打包是**最高风险点**：assets 必须包含 `.node` 文件，运行时 dlopen 可能需要复制到真实磁盘。Task 3 含专用验证步骤与 fallback。
- 所有 Tauri 命令在项目根运行（`npx --prefix frontend tauri ...`），tauri.conf.json 内路径相对 `src-tauri/`。
- 应用配置目录（`app_config_dir`）用于持久化数据库路径，MVP 存 `db_path.txt` 一行文本。

---

### Task 1: 前端改为桌面兼容（HashRouter + API baseURL 按环境切换）

**Files:**
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/config.ts`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/__tests__/pages.test.tsx`（现有测试应保持绿色）

**Interfaces:**
- Consumes: 现有 `config.ts` 常量、`api/client.ts` 的 `http` axios 实例。
- Produces: `config.ts` 新增导出 `IS_TAURI: boolean`、`API_BASE_URL: string`；`client.ts` 的 `baseURL` 改用 `API_BASE_URL`。

- [ ] **Step 1: 在 config.ts 增加桌面环境检测与 API base**

在 `frontend/src/config.ts` 追加：

```ts
/** 是否运行在 Tauri 桌面环境（WebView 注入 __TAURI_INTERNALS__）。 */
export const IS_TAURI =
  typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

/** API 基址：桌面端直连 sidecar 的本地服务（后端全局前缀 /api），浏览器端走 Vite proxy（/api）。 */
export const API_BASE_URL = IS_TAURI ? 'http://localhost:3100/api' : '/api';
```

- [ ] **Step 2: client.ts 改用 API_BASE_URL**

`frontend/src/api/client.ts` 第 4 行 `baseURL: '/api'` 改为：

```ts
import { API_BASE_URL } from '../config';

export const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
});
```

- [ ] **Step 3: main.tsx 换用 HashRouter**

`frontend/src/main.tsx` 中 `BrowserRouter` 替换为 `HashRouter`（桌面端无服务端路由回退）：

```tsx
import { HashRouter } from 'react-router-dom';
// ...
    <HashRouter>
      <App />
    </HashRouter>
```

- [ ] **Step 4: 运行前端测试确认无回归**

Run: `cd frontend && npm test`
Expected: PASS（现有 `pages.test.tsx` 用 `MemoryRouter` 与 mock API，不受影响；jsdom 无 `__TAURI_INTERNALS__`，`IS_TAURI` 为 false，baseURL 仍为 `/api`）。

- [ ] **Step 5: 构建确认 TypeScript 通过**

Run: `cd frontend && npm run build`
Expected: 构建成功，产出 `frontend/dist/`。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/main.tsx frontend/src/config.ts frontend/src/api/client.ts
git commit -m "feat(frontend): use hash router and env-aware api base"
```

---

### Task 2: 初始化 Tauri 2 壳（src-tauri + 依赖 + 配置）

**Files:**
- Create: `src-tauri/`（`tauri.conf.json`、`Cargo.toml`、`build.rs`、`src/main.rs`、`src/lib.rs`、`capabilities/default.json`、`icons/`）
- Modify: `frontend/package.json`（加 devDependency `@tauri-apps/cli`，dependency `@tauri-apps/api`、`@tauri-apps/plugin-shell`、`@tauri-apps/plugin-dialog`）
- Modify: `.gitignore`（忽略 `src-tauri/target/`）

**Interfaces:**
- Consumes: Task 1 产出 `frontend/dist/`。
- Produces: 可运行的 Tauri 壳骨架；`tauri.conf.json` 配置 `build` 字段指向前端、`bundle.externalBin` 预留 sidecar 名。

- [ ] **Step 1: 安装 Tauri 依赖**

Run: `cd frontend && npm install -D @tauri-apps/cli@^2 && npm install @tauri-apps/api@^2 @tauri-apps/plugin-shell@^2 @tauri-apps/plugin-dialog@^2`
Expected: 安装成功。

- [ ] **Step 2: 生成 Tauri 骨架**

在项目根运行（会创建 `src-tauri/`）：

```bash
npx --prefix frontend tauri init --ci \
  --app-name mstock \
  --window-title "M·STOCK" \
  --frontend-dist ../frontend/dist \
  --dev-url http://localhost:5173 \
  --before-dev-command "npm run dev --prefix frontend" \
  --before-build-command "npm run build --prefix frontend"
```

若该 Tauri CLI 版本不识别 `--ci`，则直接运行 `npx --prefix frontend tauri init` 并按交互提示填入：App name `mstock`、Window title `M·STOCK`、Web assets location `../frontend/dist`、Dev server url `http://localhost:5173`、beforeDevCommand/beforeBuildCommand 同上。

Expected: `src-tauri/` 生成，含 `tauri.conf.json`、`Cargo.toml`、`src/main.rs`、`src/lib.rs`、`icons/`。

- [ ] **Step 3: 配置 tauri.conf.json**

编辑 `src-tauri/tauri.conf.json`，确认/补齐如下（Tauri 2 schema）：

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "MSTOCK",
  "version": "0.1.0",
  "identifier": "com.mstock.desktop",
  "build": {
    "beforeDevCommand": "npm run dev --prefix frontend",
    "devUrl": "http://localhost:5173",
    "beforeBuildCommand": "npm run build --prefix frontend",
    "frontendDist": "../frontend/dist"
  },
  "app": {
    "windows": [
      { "title": "M·STOCK", "width": 1280, "height": 800 }
    ],
    "security": { "csp": null }
  },
  "bundle": {
    "active": true,
    "targets": "all",
    "externalBin": ["binaries/backend"]
  }
}
```

> 说明：`bundle.externalBin` 中 `binaries/backend` 对应 `src-tauri/binaries/backend-<target-triple>`（Task 3 生成）。
>
> **tauri-build 硬约束**：配置 externalBin 后，编译期 `tauri-build` 会无条件 `copy_binaries`，要求目标文件存在，否则 `cargo check` 报 `resource path binaries/backend-<triple> doesn't exist`。因此 Task 2 需先创建一个 **gitignored 空占位文件** `src-tauri/binaries/backend-<host-triple>`（`touch` 即可），让编译通过；Task 3 用真实 pkg 产物覆盖它。

- [ ] **Step 4: 配置 capabilities 权限**

创建 `src-tauri/capabilities/default.json`（Tauri 2 权限模型，sidecar 执行与 dialog 都需显式授权）：

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Default capability for the main window",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "dialog:default",
    {
      "identifier": "shell:allow-execute",
      "allow": [{ "name": "binaries/backend", "sidecar": true }]
    }
  ]
}
```

- [ ] **Step 5: 配置 Cargo.toml 依赖**

`src-tauri/Cargo.toml` 的 `[dependencies]` 加入：

```toml
tauri-plugin-shell = "2"
tauri-plugin-dialog = "2"
```

并在 `src-tauri/src/lib.rs` 的 Builder 链上注册插件（此时 shell 尚不可执行，仅让编译通过）：

```rust
tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .plugin(tauri_plugin_dialog::init())
    // ...其余保持生成模板
```

- [ ] **Step 6: 忽略构建产物**

`.gitignore` 追加：

```
src-tauri/target/
src-tauri/binaries/
```

- [ ] **Step 7: 编译验证**

Run: `cargo check`（在 `src-tauri/` 内）
Expected: 编译通过（首次拉取 crate 较慢）。

- [ ] **Step 8: Commit**

```bash
git add src-tauri frontend/package.json frontend/package-lock.json .gitignore
git commit -m "feat(desktop): scaffold tauri 2 shell with shell/dialog plugins"
```

---

### Task 3: 后端打包成 sidecar 单文件（pkg + better-sqlite3 原生模块）

**Files:**
- Modify: `backend/package.json`（加 `pkg` 配置与脚本）
- Create: `backend/build-sidecar.mjs`（构建+重命名脚本）
- Modify: `backend/src/database/database.service.ts`（仅在 `process.pkg` 下把原生 `.node` 复制到真实磁盘，供 dlopen）
- Create: `src-tauri/binaries/backend-<target-triple>`（构建产物，gitignored）
- Test: `backend/src/database/database.service.spec.ts` 若存在则补充 `process.pkg` 分支单测；无则用手动验证（Step 4/5）

**Interfaces:**
- Consumes: `backend/dist/main.js`（`npm run build` 产出）；Task 2 的 `src-tauri/binaries/` 目录。
- Produces: sidecar 二进制 `src-tauri/binaries/backend-<target-triple>[.exe]`；`backend/package.json` 脚本 `build:sidecar`。

- [ ] **Step 1: 确认构建机 Node 版本**

Run: `node --version`
Expected: `v22.x` 或 `v24.x`（@yao-pkg/pkg 要求 Node >= 22）。若为 v20 或更低，先切换到 >=22 的 Node（`nvm use 22` 或等效），再继续。

- [ ] **Step 2: 安装 pkg 并加配置**

Run: `cd backend && npm install -D @yao-pkg/pkg`

在 `backend/package.json` 追加：

```json
  "scripts": {
    "build:sidecar": "node build-sidecar.mjs"
  },
  "pkg": {
    "scripts": ["dist/main.js", "dist/**/*.js"],
    "assets": [
      "node_modules/better-sqlite3/build/Release/*.node"
    ],
    "outputPath": "build"
  }
```

> `assets` 是 pkg 把原生 `.node` 放进快照的关键。**不要**在 `targets` 里写死多平台：pkg 对原生模块无法交叉编译，本机构建必须只针对当前 host 平台。target 由 `build-sidecar.mjs` 按 host 动态传入（见 Step 4）。

- [ ] **Step 3: 处理 better-sqlite3 原生模块加载**

better-sqlite3 通过 `node-gyp-build` 用 `require.resolve` 定位 `.node`，pkg 快照里的 VFS 路径无法被 `dlopen`。在 `backend/src/database/database.service.ts` 文件顶部（`import Database` 之前）加入引导逻辑，把 `.node` 复制到真实磁盘并接管模块解析：

```ts
// pkg 快照内原生模块无法直接 dlopen：复制到真实磁盘并接管 require.resolve。
// 普通 node / 浏览器运行时不生效（process.pkg 不存在），不影响既有测试与部署。
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

// process.pkg 是 pkg 运行时注入的全局，标准 @types/node 没有它，用局部类型描述。
interface PkgGlobal {
  pkg?: { target: string };
}
type PkgEnv = NodeJS.Process & PkgGlobal;

function ensureNativeAddon(): void {
  const proc = process as PkgEnv;
  if (!proc.pkg) return;
  const Module = require('module') as {
    _resolveFilename: (...args: unknown[]) => string;
  };
  const src = path.join(
    path.dirname(require.resolve('better-sqlite3/package.json')),
    'build', 'Release', 'better_sqlite3.node',
  );
  const dst = path.join(os.tmpdir(), `better_sqlite3_${proc.pkg.target}.node`);
  if (!fs.existsSync(dst)) fs.copyFileSync(src, dst);
  const origResolve = Module._resolveFilename;
  Module._resolveFilename = function (request: string, ...rest: unknown[]): string {
    if (request.includes('better_sqlite3.node')) return dst;
    return origResolve.call(this, request, ...rest);
  };
}
ensureNativeAddon();
```

> 该方案针对 node-gyp-build 的 `require.resolve('./build/Release/better_sqlite3.node')` 生效。**Step 5 的验证是硬性关卡**：若仍报 dlopen 错误，说明 pkg 快照布局不同（`.node` 未被 `assets` 收进或路径变了），先 `npx @yao-pkg/pkg . --debug` 检查快照内实际路径，调整 `src` 拼接后重试；仍不行则走本任务「Fallback」节改用「Node 运行时 sidecar + resources」方案。

- [ ] **Step 4: 写并运行构建脚本**

创建 `backend/build-sidecar.mjs`：

```js
import { execSync } from 'node:child_process';
import { cpSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const binDir = join(root, '..', 'src-tauri', 'binaries');

// 按 host 平台/架构选择 pkg target（原生模块无法交叉编译，只构建当前平台）
const targetMap = {
  darwin: { arm64: 'node22-macos-arm64', x64: 'node22-macos-x64' },
  win32: { x64: 'node22-win-x64' },
};
const target = targetMap[process.platform]?.[process.arch];
if (!target) throw new Error(`Unsupported host: ${process.platform}/${process.arch}`);

// 1) nest build -> dist/
execSync('npm run build', { cwd: root, stdio: 'inherit' });
// 2) pkg -> backend/build/backend
// backend/package.json 无 main/bin 字段，必须显式传入口文件（否则 `pkg .` 报 entry 缺失）
execSync(`npx @yao-pkg/pkg dist/main.js --target ${target} --output build/backend`, {
  cwd: root,
  stdio: 'inherit',
});

// 3) 重命名为 Tauri 要求的 <name>-<target-triple>
const triple = execSync('rustc --print host-tuple').toString().trim();
const ext = process.platform === 'win32' ? '.exe' : '';
mkdirSync(binDir, { recursive: true });
cpSync(join(root, 'build', `backend${ext}`), join(binDir, `backend-${triple}${ext}`));
console.log(`sidecar -> src-tauri/binaries/backend-${triple}${ext}`);
```

- [ ] **Step 5: 手动验证 sidecar 能起服务并读库**

Run:

```bash
cd backend && npm run build:sidecar
ls ../src-tauri/binaries/            # 应出现 backend-<triple>
DB_PATH=$(pwd)/../data/market.db ./../src-tauri/binaries/backend-<triple> &
sleep 2
curl -s http://localhost:3100/api/stats | head -c 200
kill %1
```

Expected: 进程启动日志打印 listening，`curl` 返回 JSON（含 `stockCnt` 等）。若 `curl` 无响应/报 dlopen 错误，说明原生模块未落盘，应用 Task 3 Step 3 的 fallback 后重跑本步。

- [ ] **Step 6: Commit**

```bash
git add backend/package.json backend/build-sidecar.mjs backend/src/database/database.service.ts
git commit -m "build(backend): package nest backend as pkg sidecar binary"
```

**Fallback（仅当 Step 5 无法通过时使用）：** 若 pkg 对 better-sqlite3 始终无法干净打包，改用「Node 运行时 sidecar」：不打包 `backend/dist`，改为把 `backend/dist` 与生产依赖 `node_modules` 作为 Tauri `bundle.resources`，sidecar 为独立 Node 运行时二进制（`externalBin` 指向 node），Rust 侧用 `sidecar.args([mainJsResourcePath])` 启动。此方案体积更大但原生模块无需 dlopen 处理。遇到此分支时，把「Node 运行时 sidecar + resources」方案作为新的 Task 3 重写本任务。

---

### Task 4: Rust 侧启动 / 停止 sidecar（注入 PORT / DB_PATH）

**Files:**
- Modify: `src-tauri/src/lib.rs`（setup 里 spawn sidecar，RunEvent 里 kill）
- Modify: `src-tauri/Cargo.toml`（若需 `serde` 等，保持默认即可）

**Interfaces:**
- Consumes: Task 3 的 `src-tauri/binaries/backend-<triple>`；`app.path().app_config_dir()` 下的 `db_path.txt`（Task 5 写入，MVP 阶段可缺省）。
- Produces: 应用启动时自动拉起后端 `:3100`，退出时关闭；`BackendChild` state 持有子进程句柄。

- [ ] **Step 1: 在 lib.rs 注册 sidecar 启动逻辑**

`src-tauri/src/lib.rs` 改为（保留 `tauri::generate_context!()` 与插件注册）：

```rust
use std::sync::Mutex;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{process::{CommandChild, CommandEvent}, ShellExt};

struct BackendChild(Mutex<Option<CommandChild>>);

fn read_db_path(app: &tauri::AppHandle) -> String {
    let dir = app.path().app_config_dir().unwrap_or_default();
    std::fs::read_to_string(dir.join("db_path.txt")).unwrap_or_default()
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![get_db_path, set_db_path])
        .setup(|app| {
            let db_path = read_db_path(app.handle());
            let sidecar = app.shell().sidecar("binaries/backend")
                .expect("sidecar binary missing; run `npm run build:sidecar` in backend/");
            let (mut rx, child) = sidecar
                .env("PORT", "3100")
                .env("DB_PATH", &db_path)
                .spawn()
                .expect("failed to spawn backend sidecar");
            app.manage(BackendChild(Mutex::new(Some(child))));
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            println!("[backend] {}", String::from_utf8_lossy(&line).trim())
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("[backend] {}", String::from_utf8_lossy(&line).trim())
                        }
                        _ => {}
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(child) = app_handle.state::<BackendChild>().0.lock().unwrap().take() {
                    let _ = tauri::async_runtime::block_on(child.kill());
                }
            }
        });
}
```

> `get_db_path` / `set_db_path` 是 Task 5 的 command；若先做本任务，可先用 `#[tauri::command] fn get_db_path(_: tauri::AppHandle) -> Option<String> { None }` 与 `set_db_path` 空实现占位，Task 5 补齐实现，避免这里编译失败。

- [ ] **Step 2: 编译验证**

Run: `cd src-tauri && cargo check`
Expected: 编译通过。

- [ ] **Step 3: 运行验证 sidecar 自动拉起**

Run: `cd backend && npm run build:sidecar`，再 `cd .. && npx --prefix frontend tauri dev`
Expected: 窗口打开；终端出现 `[backend] Nest.js backend listening on http://localhost:3100/api`；浏览器/WebView 内页面能拉到数据。

- [ ] **Step 4: 退出时确认后端进程被关闭**

Run: 关闭应用窗口后，`lsof -i :3100 | grep LISTEN`
Expected: 无残留监听（`child.kill()` 生效）。若残留，确认 RunEvent 分支被触发（`ExitRequested`），必要时改用 `RunEvent::Exit`。

- [ ] **Step 5: Commit**

```bash
git add src-tauri/src/lib.rs src-tauri/Cargo.toml
git commit -m "feat(desktop): spawn and manage backend sidecar on app lifecycle"
```

---

### Task 5: 数据库文件选择（dialog + 配置持久化 + 前端入口）

**Files:**
- Modify: `src-tauri/src/lib.rs`（实现 `get_db_path` / `set_db_path` command）
- Modify: `frontend/src/components/Layout.tsx`（navbar 加「数据源」入口）
- Create: `frontend/src/components/DbPicker.tsx`
- Test: `frontend/src/__tests__/pages.test.tsx`（保持绿色；`IS_TAURI` 为 false 时组件不渲染）

**Interfaces:**
- Consumes: Task 4 的 `read_db_path`（读取 `app_config_dir/db_path.txt`）；`@tauri-apps/api/core` 的 `invoke`；`@tauri-apps/plugin-dialog` 的 `open`。
- Produces: `db_path.txt` 落盘；前端可选择数据库并提示重启生效。

- [ ] **Step 1: 实现 Rust command 读写数据库路径**

`src-tauri/src/lib.rs` 顶部（`pub fn run()` 之前）加入：

```rust
#[tauri::command]
fn get_db_path(app: tauri::AppHandle) -> Option<String> {
    let dir = app.path().app_config_dir().ok()?;
    std::fs::read_to_string(dir.join("db_path.txt")).ok()
}

#[tauri::command]
fn set_db_path(app: tauri::AppHandle, path: String) -> Result<(), String> {
    let dir = app.path().app_config_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    std::fs::write(dir.join("db_path.txt"), &path).map_err(|e| e.to_string())
}
```

- [ ] **Step 2: 编写前端 DbPicker 组件**

创建 `frontend/src/components/DbPicker.tsx`：

```tsx
import { useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';
import { IS_TAURI } from '../config';

export default function DbPicker() {
  const [path, setPath] = useState<string | null>(null);

  if (!IS_TAURI) return null;

  const pick = async () => {
    const selected = await open({
      multiple: false,
      directory: false,
      filters: [{ name: 'SQLite', extensions: ['db'] }],
    });
    if (typeof selected === 'string') {
      await invoke('set_db_path', { path: selected });
      setPath(selected);
      alert('已保存数据库路径，请重启应用生效。');
    }
  };

  return (
    <button type="button" className="nav-link" onClick={pick}>
      数据源{path ? ` · ${path.split('/').pop()}` : ''}
    </button>
  );
}
```

- [ ] **Step 3: 挂载到 Layout**

`frontend/src/components/Layout.tsx` 在 `<div className="data-date">` 前插入：

```tsx
<DbPicker />
```

并在文件顶部 import：

```tsx
import DbPicker from './DbPicker';
```

- [ ] **Step 4: 前端测试确认无回归**

Run: `cd frontend && npm test`
Expected: PASS（jsdom 下 `IS_TAURI` 为 false，`DbPicker` 返回 null，无副作用）。

- [ ] **Step 5: 手动验证选库流程**

Run: `cd backend && npm run build:sidecar && cd .. && npx --prefix frontend tauri dev`
操作：点击「数据源」→ 选择一个已有 `market.db` → 重启应用。
Expected: 重启后列表/首页数据来自所选数据库；`~/Library/Application Support/com.mstock.desktop/db_path.txt` 存在且内容为所选路径。

- [ ] **Step 6: Commit**

```bash
git add src-tauri/src/lib.rs frontend/src/components/DbPicker.tsx frontend/src/components/Layout.tsx
git commit -m "feat(desktop): let user pick sqlite database file"
```

---

### Task 6: 端到端本地验证

**Files:** 无代码改动（若验证发现问题，按 Task 3/4/5 修复并各自 commit）。

**Interfaces:** 依赖全部前置任务产物。

- [ ] **Step 1: 全新数据库场景**

Run: `cd backend && npm run build:sidecar`，`cd .. && npx --prefix frontend tauri dev`
用「数据源」选一个含 `market.db` 的目录，重启，核对：首页统计、股票/ETF 列表、详情、K 线、触发分析（纯技术面评分）、job 轮询。

- [ ] **Step 2: 浏览器端回归**

Run: `cd backend && npm run start:dev`（另一终端）`cd frontend && npm run dev`
Expected: `http://localhost:5173` 下页面与桌面端行为一致（验证未破坏浏览器部署）。

- [ ] **Step 3: 记录已知限制到文档（若适用）**

若发现仅桌面端出现的交互问题（如弹窗 focus、WebView 兼容），在本任务不修，仅记入 `doc/desktop.md` 的已知限制一节。

---

### Task 7: 打包分发（macOS / Windows + CI）

**Files:**
- Modify: `src-tauri/tauri.conf.json`（bundle 元数据，可选）
- Create: `.github/workflows/desktop-release.yml`

**Interfaces:**
- Consumes: Task 3 sidecar 构建脚本、Task 2 Tauri 骨架。

- [ ] **Step 1: 本机 macOS 打包**

Run: `cd backend && npm run build:sidecar && cd .. && npx --prefix frontend tauri build`
Expected: 产出 `src-tauri/target/release/bundle/dmg/*.dmg` 与 `.app`。安装并启动，确认端到端可用。

> macOS 分发需签名+公证（`APPLE_CERTIFICATE` / `APPLE_SIGNING_IDENTITY` 等），否则他机打开被 Gatekeeper 拦截。本地自用可跳过；对外分发按 Tauri 官方「Signing & Notarizing」配置，本任务不强制。

- [ ] **Step 2: 编写跨平台 CI**

创建 `.github/workflows/desktop-release.yml`（macOS arm64/x64 + Windows，基于官方 `tauri-action` 模板；backend 侧在 runner 上 `npm run build:sidecar`）：

```yaml
name: publish
on:
  workflow_dispatch:
  push:
    branches: [release]
jobs:
  publish-tauri:
    permissions: { contents: write }
    strategy:
      fail-fast: false
      matrix:
        include:
          # arm64（Apple Silicon）用默认 macos-latest（arm64 runner）
          - { platform: macos-latest, args: '--target aarch64-apple-darwin' }
          # x86_64 必须用 Intel runner（macos-13），arm64 runner 无法编译 x64 原生模块
          - { platform: macos-13, args: '--target x86_64-apple-darwin' }
          - { platform: windows-latest, args: '' }
    runs-on: ${{ matrix.platform }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: npm }
      - uses: dtolnay/rust-toolchain@stable
        with:
          targets: "${{ matrix.platform == 'macos-13' && 'x86_64-apple-darwin' || 'aarch64-apple-darwin' }}"
      - name: Install frontend deps
        run: cd frontend && npm ci
      - name: Install backend deps
        run: cd backend && npm ci
      - name: Build backend sidecar
        run: cd backend && npm run build:sidecar
      - uses: tauri-apps/tauri-action@v0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          tagName: app-v__VERSION__
          releaseName: 'M·STOCK v__VERSION__'
          releaseBody: 'See the assets to download this version and install.'
          releaseDraft: true
          prerelease: false
          args: ${{ matrix.args }}
```

> 注意：Windows runner 上 `build:sidecar` 会因 `rustc --print host-tuple` 得 `x86_64-pc-windows-msvc`，产物名带 `.exe`，与 Tauri externalBin 约定一致。macOS 两个 target 在对应架构 runner 上各自构建（arm64 runner 无法产出 x64 原生模块），`build-sidecar.mjs` 已按 host 平台动态选择 pkg target，无需额外配置。

- [ ] **Step 3: 验证 CI 产物**

Run: 推送 `release` 分支或手动 dispatch，确认 macOS / Windows 三个产物均可下载安装启动。
Expected: 两个 `.dmg`（arm64/x64）+ 一个 Windows 安装包（`.msi`/`.exe`）。

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/desktop-release.yml
git commit -m "ci(desktop): build and release tauri app for macos and windows"
```

---

### Task 8: 文档更新

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`（可选，补充桌面运行命令）
- Create: `doc/desktop.md`

**Interfaces:** 无代码依赖。

- [ ] **Step 1: 编写 doc/desktop.md**

创建 `doc/desktop.md`，覆盖：架构图（WebView ↔ localhost:3100 ↔ SQLite）、sidecar 生命周期、数据库选择流程、打包/签名说明、已知限制（better-sqlite3 原生模块打包注意、窗口关闭后的进程清理、WebView 兼容性）。

- [ ] **Step 2: 更新 README**

在 README.md 增加「桌面应用（Tauri）」一节：一句简介、启动命令（`cd backend && npm run build:sidecar` 后 `npx --prefix frontend tauri dev`）、打包命令、指向 `doc/desktop.md`。

- [ ] **Step 3: 更新 CLAUDE.md（可选）**

在「运行与测试命令」补充 Tauri dev/build 命令，方便后续 agent 直接使用。

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md doc/desktop.md
git commit -m "docs: add tauri desktop usage and architecture notes"
```
