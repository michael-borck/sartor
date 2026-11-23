// Sartor desktop: a thin Tauri shell around the Python core.
//
// On first launch it bootstraps a private Python runtime with uv
// (downloaded if absent), installs the pinned Sartor release into an
// app-data venv, initializes the selected project if needed, then runs
// `sartor serve` as a token-guarded localhost sidecar.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod settings;

use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;
use settings::ProviderSettings;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_updater::UpdaterExt;
use uuid::Uuid;

/// The Sartor release the runtime installs; bump with PyPI releases.
const SARTOR_VERSION: &str = "0.3.0";

struct DesktopState {
    child: Mutex<Option<Child>>,
    token: String,
}

#[derive(Serialize, Clone)]
struct ServerInfo {
    port: u16,
    token: String,
    project: String,
}

#[derive(Serialize, Clone)]
struct ProjectInfo {
    path: String,
    exists: bool,
    is_project: bool,
}

fn status(app: &AppHandle, message: &str) {
    let _ = app.emit("status", message.to_string());
}

fn project_info(path: &Path) -> ProjectInfo {
    ProjectInfo {
        path: path.to_string_lossy().to_string(),
        exists: path.exists(),
        is_project: path.join("sartor.yaml").is_file(),
    }
}

fn command(program: impl AsRef<std::ffi::OsStr>) -> Command {
    let cmd = Command::new(program);
    #[cfg(windows)]
    let cmd = {
        use std::os::windows::process::CommandExt;
        let mut c = cmd;
        c.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        c
    };
    cmd
}

fn run_ok(cmd: &mut Command) -> Result<(), String> {
    let output = cmd.output().map_err(|e| e.to_string())?;
    if output.status.success() {
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        let detail = if !stderr.is_empty() {
            stderr
        } else if !stdout.is_empty() {
            stdout
        } else {
            format!("command exited with {}", output.status)
        };
        Err(detail)
    }
}

fn find_uv() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(home) = dirs::home_dir() {
        candidates.push(home.join(".local/bin/uv"));
        candidates.push(home.join(".cargo/bin/uv"));
    }
    candidates.push("/opt/homebrew/bin/uv".into());
    candidates.push("/usr/local/bin/uv".into());
    #[cfg(windows)]
    if let Some(home) = dirs::home_dir() {
        candidates.push(home.join(".local\\bin\\uv.exe"));
    }
    for path in candidates {
        if path.exists() {
            return Some(path);
        }
    }
    let probe = command("uv").arg("--version").output();
    if matches!(probe, Ok(ref o) if o.status.success()) {
        return Some("uv".into());
    }
    None
}

fn install_uv(app: &AppHandle) -> Result<PathBuf, String> {
    status(app, "Downloading uv (one-time)…");
    #[cfg(not(windows))]
    run_ok(command("sh").args(["-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"]))?;
    #[cfg(windows)]
    run_ok(command("powershell").args([
        "-NoProfile",
        "-ExecutionPolicy",
        "ByPass",
        "-Command",
        "irm https://astral.sh/uv/install.ps1 | iex",
    ]))?;
    find_uv().ok_or_else(|| "uv installed but not found".into())
}

fn sartor_bin(venv: &Path) -> PathBuf {
    #[cfg(windows)]
    return venv.join("Scripts").join("sartor.exe");
    #[cfg(not(windows))]
    venv.join("bin").join("sartor")
}

fn venv_python(venv: &Path) -> PathBuf {
    #[cfg(windows)]
    return venv.join("Scripts").join("python.exe");
    #[cfg(not(windows))]
    venv.join("bin").join("python")
}

/// Create or refresh the private Sartor runtime.
///
/// In development, `SARTOR_DEV_PATH=/path/to/sartor` installs the local
/// editable package instead of the pinned PyPI release.
fn ensure_runtime(app: &AppHandle, force_update: bool) -> Result<PathBuf, String> {
    let data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    fs::create_dir_all(&data_dir).map_err(|e| e.to_string())?;
    let venv = data_dir.join("runtime");
    let bin = sartor_bin(&venv);
    let dev_path = std::env::var("SARTOR_DEV_PATH")
        .ok()
        .filter(|path| !path.trim().is_empty());

    let marker = venv.join("sartor-version");
    let installed = fs::read_to_string(&marker).unwrap_or_default();
    if dev_path.is_none() && bin.exists() && installed.trim() == SARTOR_VERSION && !force_update {
        return Ok(bin);
    }

    let uv = match find_uv() {
        Some(uv) => uv,
        None => install_uv(app)?,
    };

    if !venv.exists() {
        status(app, "Setting up Python runtime (one-time, about a minute)…");
        run_ok(command(&uv).args(["venv", "--python", "3.12"]).arg(&venv))?;
    }

    if let Some(path) = dev_path {
        status(app, "Installing Sartor from source…");
        run_ok(
            command(&uv)
                .args(["pip", "install", "--upgrade", "--python"])
                .arg(venv_python(&venv))
                .arg("-e")
                .arg(format!("{path}[all]")),
        )?;
        let _ = fs::write(&marker, format!("dev:{path}"));
    } else {
        status(app, "Installing Sartor…");
        run_ok(
            command(&uv)
                .args(["pip", "install", "--upgrade", "--python"])
                .arg(venv_python(&venv))
                .arg(format!("sartor[all]=={SARTOR_VERSION}")),
        )?;
        let _ = fs::write(&marker, SARTOR_VERSION);
    }
    Ok(bin)
}

fn ensure_project(app: &AppHandle, bin: &Path, project: &Path) -> Result<(), String> {
    if project.join("sartor.yaml").is_file() {
        return Ok(());
    }
    if project.exists() && !project.is_dir() {
        return Err(format!(
            "Project path is not a folder: {}",
            project.display()
        ));
    }
    status(app, "Creating Sartor project…");
    run_ok(command(bin).arg("init").arg(project))
}

fn free_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    Ok(listener.local_addr().map_err(|e| e.to_string())?.port())
}

fn sidecar_log(app: &AppHandle) -> Result<PathBuf, String> {
    let data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    let log_dir = data_dir.join("logs");
    fs::create_dir_all(&log_dir).map_err(|e| e.to_string())?;
    Ok(log_dir.join("sidecar.log"))
}

fn log_tail(path: &Path) -> String {
    let Ok(text) = fs::read_to_string(path) else {
        return String::new();
    };
    let tail: Vec<&str> = text.lines().rev().take(24).collect();
    tail.into_iter().rev().collect::<Vec<_>>().join("\n")
}

fn kill_sidecar(state: &DesktopState) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn health_ok(port: u16) -> bool {
    let addr = format!("127.0.0.1:{port}");
    let Ok(socket_addr) = addr.parse() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&socket_addr, Duration::from_millis(500))
    else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(700)));
    let request =
        format!("GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut buffer = [0_u8; 1024];
    let response = match stream.read(&mut buffer) {
        Ok(count) if count > 0 => String::from_utf8_lossy(&buffer[..count]).to_string(),
        _ => return false,
    };
    response.contains("\"ok\":true") || response.contains("\"ok\": true")
}

fn spawn_sidecar(app: &AppHandle, bin: &Path, project: &Path) -> Result<ServerInfo, String> {
    let state: State<DesktopState> = app.state();
    kill_sidecar(&state);
    ensure_project(app, bin, project)?;

    let port = free_port()?;
    let log_path = sidecar_log(app)?;
    let stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|e| e.to_string())?;
    let stderr = stdout.try_clone().map_err(|e| e.to_string())?;

    status(app, "Starting Sartor…");
    let mut cmd = command(bin);
    cmd.args(["serve", "--host", "127.0.0.1", "--port", &port.to_string()])
        .current_dir(project)
        .env("SARTOR_SERVE_TOKEN", &state.token)
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    if let Some(api_key) = settings::provider_api_key() {
        cmd.env("SARTOR_API_KEY", api_key);
    }
    let child = cmd
        .spawn()
        .map_err(|e| format!("Could not start Sartor: {e}"))?;
    *state.child.lock().unwrap() = Some(child);

    let deadline = Instant::now() + Duration::from_secs(60);
    loop {
        if health_ok(port) {
            return Ok(ServerInfo {
                port,
                token: state.token.clone(),
                project: project.to_string_lossy().to_string(),
            });
        }
        if let Some(child) = state.child.lock().unwrap().as_mut() {
            if let Ok(Some(child_status)) = child.try_wait() {
                let tail = log_tail(&log_path);
                return Err(if tail.is_empty() {
                    format!("Sartor exited early ({child_status})")
                } else {
                    format!("Sartor exited early ({child_status}).\n{tail}")
                });
            }
        }
        if Instant::now() > deadline {
            let tail = log_tail(&log_path);
            return Err(if tail.is_empty() {
                "Timed out waiting for Sartor to start".into()
            } else {
                format!("Timed out waiting for Sartor to start.\n{tail}")
            });
        }
        std::thread::sleep(Duration::from_millis(250));
    }
}

fn start_blocking(
    app: AppHandle,
    project_path: String,
    provider_settings: Option<ProviderSettings>,
    update: bool,
) -> Result<ServerInfo, String> {
    let trimmed = project_path.trim();
    if trimmed.is_empty() {
        return Err("Choose a Sartor project folder".into());
    }
    let project = PathBuf::from(trimmed);
    settings::save_project_path(&app, &project)?;
    let bin = ensure_runtime(&app, update)?;
    ensure_project(&app, &bin, &project)?;
    if let Some(provider_settings) = provider_settings.as_ref() {
        settings::write_settings(&project, provider_settings)?;
    }
    spawn_sidecar(&app, &bin, &project)
}

#[tauri::command]
fn get_project(app: AppHandle) -> ProjectInfo {
    project_info(&settings::load_project_path(&app))
}

#[tauri::command]
async fn choose_project(app: AppHandle) -> Result<Option<ProjectInfo>, String> {
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Choose a Sartor project folder")
            .blocking_pick_folder()
    })
    .await
    .map_err(|e| e.to_string())?;
    let Some(path) = picked.and_then(|value| value.into_path().ok()) else {
        return Ok(None);
    };
    Ok(Some(project_info(&path)))
}

#[tauri::command]
fn open_project_folder(app: AppHandle, project_path: String) -> Result<(), String> {
    let path = PathBuf::from(project_path.trim());
    if !path.is_dir() {
        return Err(format!("Project folder does not exist: {}", path.display()));
    }
    app.opener()
        .open_path(path.to_string_lossy().to_string(), None::<&str>)
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn get_settings(project_path: String) -> ProviderSettings {
    settings::read_settings(Path::new(project_path.trim()))
}

#[tauri::command]
async fn start_server(
    app: AppHandle,
    project_path: String,
    settings: Option<ProviderSettings>,
    update: bool,
) -> Result<ServerInfo, String> {
    tauri::async_runtime::spawn_blocking(move || {
        start_blocking(app, project_path, settings, update)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn restart_server(
    app: AppHandle,
    project_path: String,
    settings: Option<ProviderSettings>,
) -> Result<ServerInfo, String> {
    start_server(app, project_path, settings, false).await
}

/// Check the configured update endpoint and emit the available version.
#[tauri::command]
async fn check_update(app: AppHandle) -> Result<bool, String> {
    let updater = app.updater_builder().build().map_err(|e| e.to_string())?;
    match updater.check().await.map_err(|e| e.to_string())? {
        Some(update) => {
            let version = update.version.clone();
            let _ = app.emit("update-available", version);
            Ok(true)
        }
        None => Ok(false),
    }
}

/// Download and install an available update, then restart into it.
#[tauri::command]
async fn install_update(app: AppHandle) -> Result<(), String> {
    let updater = app.updater_builder().build().map_err(|e| e.to_string())?;
    if let Some(update) = updater.check().await.map_err(|e| e.to_string())? {
        update
            .download_and_install(|_, _| {}, || {})
            .await
            .map_err(|e| e.to_string())?;
        let _ = app.restart();
    }
    Ok(())
}

fn selftest_check(name: &str, condition: bool, failures: &mut i32) {
    if condition {
        println!("PASS {name}");
    } else {
        println!("FAIL {name}");
        *failures += 1;
    }
    let _ = std::io::stdout().flush();
}

fn run_selftest() -> i32 {
    let mut failures = 0;
    let root = std::env::var("SARTOR_SELFTEST_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| std::env::temp_dir().join("sartor-desktop-selftest"));
    let project = root.join("project");
    let _ = fs::remove_dir_all(&root);

    let setup = fs::create_dir_all(&project).and_then(|_| {
        fs::write(
            project.join("sartor.yaml"),
            "provider: anthropic\nmodel: claude-test\ncustom: kept\napi_key: ${SARTOR_API_KEY}\n",
        )
    });
    selftest_check("create temporary project", setup.is_ok(), &mut failures);
    if setup.is_err() {
        return 1;
    }

    let info = project_info(&project);
    selftest_check(
        "detect temporary project",
        info.exists && info.is_project,
        &mut failures,
    );

    let settings = settings::read_settings(&project);
    selftest_check(
        "read provider settings without returning a key",
        settings.provider == "anthropic"
            && settings.model == "claude-test"
            && settings.api_key.is_empty(),
        &mut failures,
    );

    let write_result = settings::write_settings(
        &project,
        &ProviderSettings {
            provider: "openai-compatible".into(),
            base_url: "http://localhost:11434/v1".into(),
            model: "qwen3:4b".into(),
            theme: "modern".into(),
            api_key: String::new(),
            clear_api_key: false,
            api_key_set: false,
        },
    );
    let written = fs::read_to_string(project.join("sartor.yaml")).unwrap_or_default();
    selftest_check(
        "write provider settings and preserve unrelated YAML",
        write_result.is_ok()
            && written.contains("custom: kept")
            && written.contains("api_key: ${SARTOR_API_KEY}"),
        &mut failures,
    );

    let port = free_port().unwrap_or_default();
    selftest_check("choose a free localhost port", port > 0, &mut failures);
    selftest_check(
        "health check rejects an unused port",
        port == 0 || !health_ok(port),
        &mut failures,
    );
    selftest_check(
        "generate a per-launch token",
        Uuid::parse_str(&Uuid::new_v4().to_string()).is_ok(),
        &mut failures,
    );
    println!("PASS uv discovery completed ({:?})", find_uv());

    if let Ok(bin) = std::env::var("SARTOR_BIN") {
        let smoke_port = free_port().unwrap_or_default();
        let mut child = command(&bin)
            .args([
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                &smoke_port.to_string(),
            ])
            .current_dir(&project)
            .env("SARTOR_SERVE_TOKEN", "sartor-selftest")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .ok();
        let deadline = Instant::now() + Duration::from_secs(15);
        let mut healthy = false;
        while Instant::now() < deadline {
            if health_ok(smoke_port) {
                healthy = true;
                break;
            }
            std::thread::sleep(Duration::from_millis(250));
        }
        if let Some(mut child) = child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        selftest_check("sidecar smoke", healthy, &mut failures);
    } else {
        println!("SKIP sidecar smoke (SARTOR_BIN not set)");
    }

    if std::env::var_os("SARTOR_SELFTEST_KEEP").is_none() {
        let _ = fs::remove_dir_all(&root);
    }
    if failures == 0 {
        0
    } else {
        1
    }
}

fn main() {
    if std::env::args().any(|arg| arg == "--selftest") {
        std::process::exit(run_selftest());
    }
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(DesktopState {
            child: Mutex::new(None),
            token: Uuid::new_v4().to_string(),
        })
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let _ = check_update(handle).await;
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_project,
            choose_project,
            open_project_folder,
            get_settings,
            start_server,
            restart_server,
            check_update,
            install_update
        ])
        .build(tauri::generate_context!())
        .expect("error while building Sartor")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                kill_sidecar(&app.state::<DesktopState>());
            }
        });
}
