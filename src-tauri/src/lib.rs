use std::sync::Mutex;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{process::{CommandChild, CommandEvent}, ShellExt};

struct BackendChild(Mutex<Option<CommandChild>>);

#[tauri::command]
fn get_db_path(app: tauri::AppHandle) -> Option<String> {
    let dir = app.path().app_config_dir().ok()?;
    std::fs::read_to_string(dir.join("db_path.txt"))
        .ok()
        .map(|s| s.trim().to_string())
}

#[tauri::command]
fn set_db_path(app: tauri::AppHandle, path: String) -> Result<(), String> {
    let dir = app.path().app_config_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    std::fs::write(dir.join("db_path.txt"), path.trim()).map_err(|e| e.to_string())
}

fn read_db_path(app: &tauri::AppHandle) -> String {
    let dir = app.path().app_config_dir().unwrap_or_default();
    std::fs::read_to_string(dir.join("db_path.txt"))
        .map(|s| s.trim().to_string())
        .unwrap_or_default()
}

/// Resolve the DB path to inject via DB_PATH. Precedence:
/// 1. `db_path.txt` under the app config dir (user's saved choice, written by Task 5)
/// 2. Dev default: `<repo root>/data/market.db` (the same path the backend's
///    `resolveDbPath` would compute outside the pkg snapshot, where `__dirname`
///    points at `/snapshot/...` and the repo default does not exist)
/// 3. A fresh DB created in the app config dir
fn resolve_db_path(app: &tauri::AppHandle) -> String {
    let saved = read_db_path(app);
    if !saved.trim().is_empty() {
        return saved;
    }
    if let Ok(cwd) = std::env::current_dir() {
        for base in [cwd.clone(), cwd.parent().unwrap_or(&cwd).to_path_buf()] {
            let candidate = base.join("data").join("market.db");
            if candidate.is_file() {
                return candidate.to_string_lossy().into_owned();
            }
        }
    }
    let dir = app.path().app_config_dir().unwrap_or_default();
    let _ = std::fs::create_dir_all(&dir);
    dir.join("market.db").to_string_lossy().into_owned()
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![get_db_path, set_db_path])
        .setup(|app| {
            let db_path = resolve_db_path(app.handle());
            let sidecar = app.shell().sidecar("backend")
                .expect("sidecar binary missing; run `npm run build:sidecar` in backend/");
            // 后端是常驻桌面服务，禁掉"放行全部来源"的缺省 CORS：
            // 只允许 Tauri webview 来源（macOS WKWebView 用 tauri://localhost，
            // Windows/Linux WebView2 用 http://tauri.localhost），防止任何网页读
            // 写 localhost:3100（含 POST /api/analyze 触发 LLM 配额）。
            // 浏览器 dev（npm run start:dev）不设此变量，保持 origin: true。
            // tauri dev（debug 构建）下桌面前端走绝对地址 http://localhost:3100/api，
            // 而 WebView 页面来源是 devUrl http://localhost:5173，需额外放行该 origin；
            // tauri build（release 构建）只用 Tauri origin。
            let cors_origin = if cfg!(debug_assertions) {
                "tauri://localhost,http://tauri.localhost,http://localhost:5173"
            } else {
                "tauri://localhost,http://tauri.localhost"
            };
            let (mut rx, child) = sidecar
                .env("PORT", "3100")
                .env("DB_PATH", &db_path)
                .env("CORS_ORIGIN", cors_origin)
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
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                if let Some(child) = app_handle.state::<BackendChild>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
