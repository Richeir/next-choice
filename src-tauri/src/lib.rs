use std::sync::Mutex;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{process::{CommandChild, CommandEvent}, ShellExt};

struct BackendChild(Mutex<Option<CommandChild>>);

#[tauri::command]
fn get_db_path(_: tauri::AppHandle) -> Option<String> { None }

#[tauri::command]
fn set_db_path(_: tauri::AppHandle, _path: String) -> Result<(), String> { Ok(()) }

fn read_db_path(app: &tauri::AppHandle) -> String {
    let dir = app.path().app_config_dir().unwrap_or_default();
    std::fs::read_to_string(dir.join("db_path.txt")).unwrap_or_default()
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
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                if let Some(child) = app_handle.state::<BackendChild>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
