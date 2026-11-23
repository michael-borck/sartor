use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

const KEYRING_SERVICE: &str = "org.borck.sartor";
const KEYRING_ACCOUNT: &str = "provider-api-key";
const API_KEY_REF: &str = "${SARTOR_API_KEY}";

#[derive(Serialize, Deserialize, Default, Clone)]
struct DesktopStateFile {
    project_path: Option<String>,
}

#[derive(Serialize, Deserialize, Default, Clone)]
pub struct ProviderSettings {
    pub provider: String,
    pub base_url: String,
    pub model: String,
    pub theme: String,
    pub api_key: String,
    pub clear_api_key: bool,
    pub api_key_set: bool,
}

fn desktop_state_path(app: &AppHandle) -> Result<PathBuf, String> {
    let data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    fs::create_dir_all(&data_dir).map_err(|e| e.to_string())?;
    Ok(data_dir.join("desktop-settings.json"))
}

pub fn default_project_path(app: &AppHandle) -> PathBuf {
    if let Ok(documents) = app.path().document_dir() {
        return documents.join("Sartor");
    }
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("Sartor")
}

pub fn load_project_path(app: &AppHandle) -> PathBuf {
    let Ok(path) = desktop_state_path(app) else {
        return default_project_path(app);
    };
    let Ok(text) = fs::read_to_string(path) else {
        return default_project_path(app);
    };
    let Ok(state) = serde_json::from_str::<DesktopStateFile>(&text) else {
        return default_project_path(app);
    };
    state
        .project_path
        .filter(|value| !value.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| default_project_path(app))
}

pub fn save_project_path(app: &AppHandle, project: &Path) -> Result<(), String> {
    let path = desktop_state_path(app)?;
    let state = DesktopStateFile {
        project_path: Some(project.to_string_lossy().to_string()),
    };
    fs::write(
        path,
        serde_json::to_string_pretty(&state).unwrap_or_default(),
    )
    .map_err(|e| e.to_string())
}

fn config_path(project: &Path) -> PathBuf {
    project.join("sartor.yaml")
}

fn yaml_string(value: &serde_yaml::Value, key: &str) -> String {
    match value.get(key) {
        Some(serde_yaml::Value::String(text)) => text.clone(),
        Some(serde_yaml::Value::Number(number)) => number.to_string(),
        Some(serde_yaml::Value::Bool(flag)) => flag.to_string(),
        _ => String::new(),
    }
}

fn set_optional(map: &mut serde_yaml::Mapping, key: &str, value: &str) {
    let yaml_key = serde_yaml::Value::String(key.to_string());
    let trimmed = value.trim();
    if trimmed.is_empty() {
        map.remove(&yaml_key);
    } else {
        map.insert(yaml_key, trimmed.to_string().into());
    }
}

fn api_key_entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT).map_err(|e| e.to_string())
}

pub fn provider_api_key() -> Option<String> {
    api_key_entry()
        .ok()?
        .get_password()
        .ok()
        .filter(|value| !value.trim().is_empty())
}

fn has_provider_api_key(root: &serde_yaml::Value) -> bool {
    if provider_api_key().is_some() {
        return true;
    }
    let raw = yaml_string(root, "api_key");
    if raw.trim().is_empty() {
        return false;
    }
    if let Some(name) = raw
        .trim()
        .strip_prefix("${")
        .and_then(|value| value.strip_suffix('}'))
    {
        return std::env::var(name)
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false);
    }
    true
}

pub fn read_settings(project: &Path) -> ProviderSettings {
    let mut settings = ProviderSettings {
        provider: "openai-compatible".into(),
        base_url: "http://localhost:11434/v1".into(),
        model: String::new(),
        theme: "ats-plain".into(),
        api_key: String::new(),
        clear_api_key: false,
        api_key_set: false,
    };
    let Ok(text) = fs::read_to_string(config_path(project)) else {
        settings.api_key_set = provider_api_key().is_some();
        return settings;
    };
    let Ok(root) = serde_yaml::from_str::<serde_yaml::Value>(&text) else {
        settings.api_key_set = provider_api_key().is_some();
        return settings;
    };

    let provider = yaml_string(&root, "provider");
    if !provider.is_empty() {
        settings.provider = provider;
    }
    let base_url = yaml_string(&root, "base_url");
    if !base_url.is_empty() {
        settings.base_url = base_url;
    }
    settings.model = yaml_string(&root, "model");
    let theme = yaml_string(&root, "theme");
    if !theme.is_empty() {
        settings.theme = theme;
    }
    settings.api_key_set = has_provider_api_key(&root);
    settings
}

pub fn write_settings(project: &Path, settings: &ProviderSettings) -> Result<(), String> {
    let provider = settings.provider.trim().to_string();
    if !["openai-compatible", "anthropic"].contains(&provider.as_str()) {
        return Err("Pick a provider: openai-compatible or anthropic".into());
    }
    let theme = if settings.theme.trim().is_empty() {
        "ats-plain".to_string()
    } else {
        settings.theme.trim().to_string()
    };
    if !["ats-plain", "modern", "academic"].contains(&theme.as_str()) {
        return Err("Pick a theme: ats-plain, modern, or academic".into());
    }

    let path = config_path(project);
    if !path.is_file() {
        return Err(format!(
            "No Sartor project config at {}; start the project first",
            path.display()
        ));
    }
    let mut root = fs::read_to_string(&path)
        .ok()
        .and_then(|text| serde_yaml::from_str::<serde_yaml::Value>(&text).ok())
        .unwrap_or(serde_yaml::Value::Mapping(Default::default()));
    let serde_yaml::Value::Mapping(map) = &mut root else {
        return Err(format!(
            "{} is not a YAML mapping; edit it by hand",
            path.display()
        ));
    };

    set_optional(map, "provider", &provider);
    set_optional(map, "base_url", &settings.base_url);
    set_optional(map, "model", &settings.model);
    set_optional(map, "theme", &theme);

    let api_key = settings.api_key.trim().to_string();
    if settings.clear_api_key {
        if let Ok(entry) = api_key_entry() {
            match entry.delete_credential() {
                Ok(()) | Err(keyring::Error::NoEntry) => {}
                Err(error) => return Err(error.to_string()),
            }
        }
        map.remove(&serde_yaml::Value::String("api_key".into()));
    } else if !api_key.is_empty() {
        api_key_entry()?
            .set_password(&api_key)
            .map_err(|e| e.to_string())?;
        set_optional(map, "api_key", API_KEY_REF);
    }

    let text = serde_yaml::to_string(&root).map_err(|e| e.to_string())?;
    fs::write(&path, text).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(&path, fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_project(name: &str) -> PathBuf {
        let path =
            std::env::temp_dir().join(format!("sartor-desktop-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).unwrap();
        path
    }

    #[test]
    fn settings_preserve_unrelated_yaml_and_never_return_key() {
        let project = temp_project("settings");
        fs::write(
            config_path(&project),
            "provider: anthropic\nmodel: claude-test\ncustom: kept\napi_key: ${SARTOR_API_KEY}\n",
        )
        .unwrap();
        let settings = read_settings(&project);
        assert_eq!(settings.provider, "anthropic");
        assert_eq!(settings.model, "claude-test");
        assert!(settings.api_key.is_empty());

        write_settings(
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
        )
        .unwrap();
        let text = fs::read_to_string(config_path(&project)).unwrap();
        assert!(text.contains("custom: kept"));
        assert!(text.contains("api_key: ${SARTOR_API_KEY}"));
        let _ = fs::remove_dir_all(project);
    }
}
