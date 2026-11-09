//! Native installer and offline application supervisor.
#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    env, fs,
    fs::{File, OpenOptions},
    io::{Read, Write},
    path::{Component, Path, PathBuf},
    process::{Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};
use tiny_http::{Header, Response, Server};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

#[derive(Clone, Deserialize, Serialize)]
struct Manifest {
    schema_version: u32,
    version: String,
    platform: String,
    components: Vec<Artifact>,
    executable: String,
    arguments: Vec<String>,
}

#[derive(Clone, Deserialize, Serialize)]
struct Artifact {
    id: String,
    #[serde(default)]
    url: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    bundled_path: Option<String>,
    size_bytes: u64,
    unpacked_limit_bytes: u64,
    sha256: String,
}

#[derive(Default, Serialize)]
struct Progress {
    stage: String,
    downloaded: u64,
    total: u64,
    app_url: Option<String>,
    error: Option<String>,
    can_cancel: bool,
    #[serde(skip)]
    cancel: bool,
    #[serde(skip)]
    retry: bool,
}

type State = Arc<Mutex<Progress>>;

fn safe_relative(path: &str) -> Result<PathBuf> {
    let path = Path::new(path);
    if path.as_os_str().is_empty()
        || path
            .components()
            .any(|c| !matches!(c, Component::Normal(_)))
        || path.to_string_lossy().contains(['\\', ':'])
    {
        return Err("unsafe relative path".into());
    }
    for name in path.components() {
        let name = name.as_os_str().to_string_lossy();
        let base = name.split('.').next().unwrap_or("").to_ascii_uppercase();
        if name.ends_with(['.', ' '])
            || matches!(
                base.as_str(),
                "CON"
                    | "PRN"
                    | "AUX"
                    | "NUL"
                    | "COM1"
                    | "COM2"
                    | "COM3"
                    | "COM4"
                    | "COM5"
                    | "COM6"
                    | "COM7"
                    | "COM8"
                    | "COM9"
                    | "LPT1"
                    | "LPT2"
                    | "LPT3"
                    | "LPT4"
                    | "LPT5"
                    | "LPT6"
                    | "LPT7"
                    | "LPT8"
                    | "LPT9"
            )
        {
            return Err("unsafe platform filename".into());
        }
    }
    Ok(path.to_path_buf())
}

fn secret() -> Result<String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|e| format!("Cannot create launch credential: {e}"))?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

fn plain_path(root: &Path, target: &Path) -> Result<()> {
    if !target.starts_with(root) {
        return Err("Path escapes installation".into());
    }
    let mut current = root.to_path_buf();
    let mut paths = vec![current.clone()];
    for part in target.strip_prefix(root)?.components() {
        current.push(part);
        paths.push(current.clone());
    }
    for path in paths {
        if let Ok(meta) = fs::symlink_metadata(path) {
            if meta.file_type().is_symlink() {
                return Err("Linked installation path refused".into());
            }
            #[cfg(windows)]
            {
                use std::os::windows::fs::MetadataExt;
                if meta.file_attributes() & 0x400 != 0 {
                    return Err("Reparse installation path refused".into());
                }
            }
        }
    }
    Ok(())
}

fn plain_member(
    root: &Path,
    target: &Path,
    checked: &mut std::collections::HashSet<PathBuf>,
) -> Result<()> {
    let parent = target.parent().ok_or("missing parent")?;
    if !checked.contains(parent) {
        plain_path(root, parent)?;
        checked.insert(parent.to_path_buf());
    }
    if let Ok(meta) = fs::symlink_metadata(target) {
        if meta.file_type().is_symlink() {
            return Err("Linked component file refused".into());
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            if meta.file_attributes() & 0x400 != 0 {
                return Err("Reparse component file refused".into());
            }
        }
    }
    Ok(())
}

fn remove_staging(path: &Path) -> Result<()> {
    let meta = fs::symlink_metadata(path)?;
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if meta.file_attributes() & 0x400 != 0 {
            return Err("Linked staging path refused".into());
        }
    }
    if meta.file_type().is_symlink() {
        return Err("Linked staging path refused".into());
    }
    if meta.is_dir() {
        for child in fs::read_dir(path)? {
            remove_staging(&child?.path())?;
        }
        fs::remove_dir(path)?;
    } else {
        fs::remove_file(path)?;
    }
    Ok(())
}

fn check_cancel(state: &State) -> Result<()> {
    if state.lock().unwrap().cancel {
        return Err("Setup canceled. Choose Retry setup to continue.".into());
    }
    Ok(())
}

fn sha_file(path: &Path, state: Option<&State>) -> Result<String> {
    let mut file = File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        if let Some(state) = state {
            check_cancel(state)?;
        }
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn stage(state: &State, message: &str) {
    let mut progress = state.lock().unwrap();
    progress.stage = message.into();
    progress.total = 0;
    progress.downloaded = 0;
}

fn verify_url(url: &str, allow_local: bool) -> Result<()> {
    let url = reqwest::Url::parse(url)?;
    if !url.username().is_empty() || url.password().is_some() {
        return Err("download URLs must not contain credentials".into());
    }
    if url.scheme() != "https"
        && !(allow_local && url.scheme() == "http" && url.host_str() == Some("127.0.0.1"))
    {
        return Err("components require HTTPS (test HTTP is restricted to 127.0.0.1)".into());
    }
    Ok(())
}

fn download_client(allow_local: bool) -> Result<Client> {
    Ok(Client::builder()
        .user_agent("PhotoReliefStudio/1.1.2")
        .connect_timeout(Duration::from_secs(20))
        .timeout(Duration::from_secs(30))
        .redirect(reqwest::redirect::Policy::custom(move |attempt| {
            if attempt.previous().len() >= 10 {
                attempt.error("Too many download redirects")
            } else if verify_url(attempt.url().as_str(), allow_local).is_err() {
                attempt.error("Insecure download redirect refused")
            } else {
                attempt.follow()
            }
        }))
        .build()?)
}

fn bundled_archive(item: &Artifact, bundle: &Path, cache: &Path, state: &State) -> Result<PathBuf> {
    if !item.url.is_empty() || item.id != "application" {
        return Err("Only the application may use a bundled archive, with no download URL".into());
    }
    let relative = safe_relative(item.bundled_path.as_deref().ok_or("missing bundled path")?)?;
    if item.sha256.len() != 64 || !item.sha256.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("invalid SHA-256".into());
    }
    let target = cache.join(format!("{}.zip", item.sha256));
    plain_path(cache, &target)?;
    if target.is_file()
        && target.metadata()?.len() == item.size_bytes
        && sha_file(&target, Some(state))? == item.sha256
    {
        return Ok(target);
    }
    let source = bundle.join(relative);
    plain_path(bundle, &source)?;
    stage(state, "Verifying bundled application");
    if !source.is_file()
        || source.metadata()?.len() != item.size_bytes
        || sha_file(&source, Some(state))? != item.sha256
    {
        return Err("The bundled application is missing or damaged. Extract the complete ZIP again and choose Retry setup.".into());
    }
    let partial = cache.join(format!("{}.part", item.sha256));
    plain_path(cache, &partial)?;
    let mut input = File::open(source)?;
    let mut output = File::create(&partial)?;
    let mut buffer = [0u8; 65536];
    let mut copied = 0u64;
    loop {
        check_cancel(state)?;
        let count = input.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        copied += count as u64;
        if copied > item.size_bytes {
            return Err("Bundled application changed while copying".into());
        }
        output.write_all(&buffer[..count])?;
    }
    output.sync_all()?;
    drop(output);
    if copied != item.size_bytes || sha_file(&partial, Some(state))? != item.sha256 {
        return Err("Bundled application failed SHA-256 verification; not executed".into());
    }
    // Windows rename cannot replace an existing corrupt cache entry.
    if target.exists() {
        fs::remove_file(&target)?;
    }
    fs::rename(partial, &target)?;
    Ok(target)
}

fn download(
    client: &Client,
    item: &Artifact,
    root: &Path,
    state: &State,
    local: bool,
) -> Result<PathBuf> {
    verify_url(&item.url, local)?;
    safe_relative(&item.id)?;
    if item.sha256.len() != 64 || !item.sha256.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("invalid SHA-256".into());
    }
    plain_path(root, root)?;
    let final_path = root.join(format!("{}.zip", item.sha256));
    let partial = root.join(format!("{}.part", item.sha256));
    plain_path(root, &final_path)?;
    plain_path(root, &partial)?;
    if final_path.exists()
        && final_path.metadata()?.len() == item.size_bytes
        && sha_file(&final_path, Some(state))? == item.sha256
    {
        return Ok(final_path);
    }
    let mut offset = partial.metadata().map(|m| m.len()).unwrap_or(0);
    if offset > item.size_bytes {
        File::create(&partial)?;
        offset = 0;
    }
    if offset < item.size_bytes {
        let mut request = client.get(&item.url);
        if offset > 0 {
            request = request.header("Range", format!("bytes={offset}-"));
        }
        let mut response = request
            .send()
            .map_err(|_| "Could not connect to the download server. Check your connection and choose Retry setup.")?;
        if !response.status().is_success() {
            return Err(format!(
                "The download server returned HTTP {}. Choose Retry setup to try again.",
                response.status().as_u16()
            )
            .into());
        }
        // A server ignoring Range is legal: restart, never append a complete response.
        if offset > 0 && response.status().as_u16() == 200 {
            offset = 0;
        } else if response.status().as_u16() == 206 {
            let expected = format!("bytes {offset}-{}/{}", item.size_bytes - 1, item.size_bytes);
            let content_range = response
                .headers()
                .get("content-range")
                .and_then(|h| h.to_str().ok())
                .unwrap_or("");
            if content_range != expected {
                return Err("The download server returned an invalid resume range. Choose Retry setup to try again.".into());
            }
        } else if response.status().as_u16() != 200 {
            return Err("unexpected download response".into());
        }
        let mut output = OpenOptions::new()
            .create(true)
            .write(true)
            .append(offset > 0)
            .truncate(offset == 0)
            .open(&partial)?;
        {
            let mut progress = state.lock().unwrap();
            progress.total = item.size_bytes;
            progress.downloaded = offset;
            progress.stage = format!("Downloading {}", item.id);
        }
        let mut buffer = [0u8; 65536];
        loop {
            check_cancel(state)?;
            let count = response.read(&mut buffer).map_err(
                |_| "The download was interrupted. Check your connection and choose Retry setup.",
            )?;
            if count == 0 {
                break;
            }
            if offset + count as u64 > item.size_bytes {
                return Err("download exceeds manifest size".into());
            }
            output.write_all(&buffer[..count])?;
            offset += count as u64;
            state.lock().unwrap().downloaded = offset;
        }
        output.sync_all()?;
    }
    stage(state, "Verifying SHA-256");
    if partial.metadata()?.len() != item.size_bytes
        || sha_file(&partial, Some(state))? != item.sha256
    {
        // Preserve interrupted bytes for retry; discard a complete corrupt payload.
        if partial.metadata()?.len() == item.size_bytes {
            fs::remove_file(&partial)?;
        }
        return Err("component size or SHA-256 mismatch; component was not executed".into());
    }
    fs::rename(partial, &final_path)?;
    Ok(final_path)
}

fn extract(archive: &Path, dest: &Path, limit: u64, state: &State) -> Result<()> {
    let mut zip = zip::ZipArchive::new(File::open(archive)?)?;
    let mut total = 0u64;
    let mut checked = std::collections::HashSet::new();
    for index in 0..zip.len() {
        check_cancel(state)?;
        let mut entry = zip.by_index(index)?;
        // Reject links and path traversal before writing any member.
        if entry
            .unix_mode()
            .map(|m| m & 0o170000 == 0o120000)
            .unwrap_or(false)
        {
            return Err("archive symlinks are not accepted in this prototype".into());
        }
        let enclosed = entry.enclosed_name().ok_or("unsafe archive member")?;
        safe_relative(enclosed.to_str().ok_or("non-UTF8 archive member")?)?;
        total = total
            .checked_add(entry.size())
            .ok_or("unpacked size overflow")?;
        if total > limit {
            return Err("archive exceeds unpacked size limit".into());
        }
        let target = dest.join(enclosed);
        plain_member(dest, &target, &mut checked)?;
        if entry.is_dir() {
            fs::create_dir_all(&target)?;
        } else {
            fs::create_dir_all(target.parent().ok_or("no parent")?)?;
            let mut out = File::create(&target)?;
            let expected = entry.size();
            let copied =
                std::io::copy(&mut (&mut entry).take(expected.saturating_add(1)), &mut out)?;
            if copied != expected {
                return Err("archive member size mismatch".into());
            }
            out.flush()?;
            #[cfg(unix)]
            if let Some(mode) = entry.unix_mode() {
                use std::os::unix::fs::PermissionsExt;
                fs::set_permissions(&target, fs::Permissions::from_mode(mode & 0o777))?;
            }
        }
    }
    Ok(())
}

fn verify_installed(
    manifest: &Manifest,
    installed: &Path,
    cache: &Path,
    state: &State,
) -> Result<()> {
    // The local completion marker is not a trust root. Revalidate installed bytes
    // against the archives authenticated by the pinned manifest before execution.
    let mut checked = std::collections::HashSet::new();
    for item in &manifest.components {
        let archive = cache.join(format!("{}.zip", item.sha256));
        if archive.metadata()?.len() != item.size_bytes
            || sha_file(&archive, Some(state))? != item.sha256
        {
            return Err("cached component failed verification".into());
        }
        let mut zip = zip::ZipArchive::new(File::open(archive)?)?;
        for index in 0..zip.len() {
            check_cancel(state)?;
            let mut entry = zip.by_index(index)?;
            if entry.is_dir() {
                continue;
            }
            let relative = entry.enclosed_name().ok_or("unsafe archive member")?;
            let path = installed.join(relative);
            plain_member(installed, &path, &mut checked)?;
            if fs::symlink_metadata(&path)?.file_type().is_symlink()
                || path.metadata()?.len() != entry.size()
            {
                return Err("installed component is missing, replaced or corrupt".into());
            }
            let mut expected = Sha256::new();
            let mut buffer = [0u8; 65536];
            loop {
                check_cancel(state)?;
                let count = entry.read(&mut buffer)?;
                if count == 0 {
                    break;
                }
                expected.update(&buffer[..count]);
            }
            if sha_file(&path, Some(state))? != format!("{:x}", expected.finalize()) {
                return Err("installed component SHA-256 mismatch; not executed".into());
            }
        }
    }
    Ok(())
}

fn finish_cancellable_setup(state: &State) -> Result<()> {
    let mut progress = state.lock().unwrap();
    if progress.cancel {
        return Err("Setup canceled. Choose Retry setup to continue.".into());
    }
    progress.can_cancel = false;
    Ok(())
}

struct BackendProcess {
    child: std::process::Child,
}

impl Drop for BackendProcess {
    fn drop(&mut self) {
        if matches!(self.child.try_wait(), Ok(None)) {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}

fn existing_application(root: &Path) -> Option<String> {
    let state: serde_json::Value =
        serde_json::from_slice(&fs::read(root.join("running.json")).ok()?).ok()?;
    let address = state.get("app_url")?.as_str()?;
    let url = reqwest::Url::parse(address).ok()?;
    if url.scheme() != "http"
        || url.host_str() != Some("127.0.0.1")
        || url.path() != "/"
        || url.port().is_none()
    {
        return None;
    }
    let token = url
        .query_pairs()
        .find(|(key, _)| key == "launch")?
        .1
        .into_owned();
    if token.len() != 64 || !token.bytes().all(|b| b.is_ascii_hexdigit()) {
        return None;
    }
    let mut health = url.clone();
    health.set_query(None);
    health.set_path("/api/health");
    let client = Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(2))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .ok()?;
    if client
        .get(health)
        .header("X-Relief-Token", token)
        .send()
        .ok()?
        .status()
        .is_success()
    {
        Some(address.to_owned())
    } else {
        None
    }
}

fn open_browser(url: &str) -> Result<()> {
    #[cfg(windows)]
    let mut command = Command::new("explorer.exe");
    #[cfg(target_os = "macos")]
    let mut command = Command::new("/usr/bin/open");
    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = Command::new("xdg-open");
    command.arg(url).spawn()?;
    Ok(())
}

const PAGE: &str = include_str!("setup.html");

fn setup_server(state: State) -> Result<String> {
    let server = Server::http("127.0.0.1:0")?;
    let secret = secret()?;
    let authority = server.server_addr().to_string();
    let prefix = format!("/{secret}/");
    let url = format!("http://{authority}{prefix}");
    thread::spawn(move || {
        for request in server.incoming_requests() {
            let host = request
                .headers()
                .iter()
                .find(|h| h.field.equiv("Host"))
                .map(|h| h.value.as_str())
                .unwrap_or("");
            let origin = request
                .headers()
                .iter()
                .find(|h| h.field.equiv("Origin"))
                .map(|h| h.value.as_str());
            if host != authority
                || origin.is_some_and(|o| o != format!("http://{authority}"))
                || !request.url().starts_with(&prefix)
            {
                let _ = request.respond(Response::empty(403));
                continue;
            }
            let path = &request.url()[prefix.len()..];
            if request.method().as_str() == "POST" && matches!(path, "retry" | "cancel") {
                let mut progress = state.lock().unwrap();
                if path == "cancel" && progress.can_cancel {
                    progress.cancel = true;
                    progress.can_cancel = false;
                    progress.stage = "Stopping setup safely".into();
                } else if path == "retry" && progress.error.is_some() {
                    progress.retry = true;
                } else {
                    let _ = request.respond(Response::empty(409));
                    continue;
                }
                let _ = request.respond(Response::empty(204));
                continue;
            }
            if request.method().as_str() != "GET" {
                let _ = request.respond(Response::empty(405));
                continue;
            }
            let (body, content_type) = match path {
                "" => (PAGE.to_owned(), "text/html; charset=utf-8"),
                "status" => (
                    serde_json::to_string(&*state.lock().unwrap()).unwrap(),
                    "application/json",
                ),
                _ => {
                    let _ = request.respond(Response::empty(404));
                    continue;
                }
            };
            let response = Response::from_string(body)
                .with_header(Header::from_bytes("Content-Type", content_type).unwrap())
                .with_header(Header::from_bytes("Cache-Control", "no-store").unwrap());
            let _ = request.respond(response);
        }
    });
    Ok(url)
}

fn platform_id() -> String {
    format!("{}-{}", env::consts::OS, env::consts::ARCH)
}

fn run(
    manifest: Manifest,
    root: &Path,
    state: &State,
    local: bool,
    install_only: bool,
) -> Result<()> {
    if !matches!(manifest.schema_version, 1 | 2) || manifest.platform != platform_id() {
        return Err("unsupported manifest schema or platform".into());
    }
    safe_relative(&manifest.version)?;
    if manifest.components.is_empty() || manifest.components.len() > 16 {
        return Err("invalid component count".into());
    }
    let mut ids = std::collections::HashSet::new();
    for item in &manifest.components {
        if !ids.insert(&item.id) || item.size_bytes == 0 || item.unpacked_limit_bytes == 0 {
            return Err("invalid component metadata".into());
        }
    }
    let executable = safe_relative(&manifest.executable)?;
    let client = download_client(local)?;
    let cache = root.join("downloads");
    plain_path(root, &cache)?;
    fs::create_dir_all(&cache)?;
    let installed = root.join("versions").join(&manifest.version);
    plain_path(root, &installed)?;
    let manifest_bytes = serde_json::to_vec(&manifest)?;
    let marker = installed.join("verified-manifest.json");
    let valid_install = if marker.exists() && fs::read(&marker)? == manifest_bytes {
        stage(state, "Verifying installed files");
        let verification = verify_installed(&manifest, &installed, &cache, state);
        check_cancel(state)?;
        if manifest.schema_version == 1 {
            verification?;
            true
        } else {
            verification.is_ok()
        }
    } else {
        false
    };
    if !valid_install {
        let staging = root.join("staging").join(&manifest.version);
        plain_path(root, &staging)?;
        if staging.exists() {
            remove_staging(&staging)?;
        }
        let required = manifest
            .components
            .iter()
            .try_fold(0u64, |sum, item| {
                sum.checked_add(item.size_bytes)?
                    .checked_add(item.unpacked_limit_bytes)
            })
            .ok_or("component sizes overflow")?;
        if fs2::available_space(root)? < required.saturating_add(256 * 1024 * 1024) {
            return Err(
                "There is not enough free disk space to install safely. Free space and retry."
                    .into(),
            );
        }
        let mut archives = Vec::new();
        for item in manifest
            .components
            .iter()
            .filter(|item| item.bundled_path.is_some())
            .chain(
                manifest
                    .components
                    .iter()
                    .filter(|item| item.bundled_path.is_none()),
            )
        {
            let archive = if item.bundled_path.is_some() {
                let executable = env::current_exe()?;
                bundled_archive(
                    item,
                    executable.parent().ok_or("missing launcher folder")?,
                    &cache,
                    state,
                )?
            } else {
                download(&client, item, &cache, state, local)?
            };
            archives.push((archive, item));
        }
        fs::create_dir_all(&staging)?;
        for (archive, item) in archives {
            stage(state, &format!("Extracting verified {}", item.id));
            extract(&archive, &staging, item.unpacked_limit_bytes, state)?;
        }
        check_cancel(state)?;
        if !staging.join(&executable).is_file() {
            return Err("manifest executable is missing from verified components".into());
        }
        fs::write(staging.join("verified-manifest.json"), manifest_bytes)?;
        fs::create_dir_all(installed.parent().ok_or("no version parent")?)?;
        stage(state, "Verifying installed files");
        verify_installed(&manifest, &staging, &cache, state)?;
        finish_cancellable_setup(state)?;
        if installed.exists() {
            let previous =
                installed.with_file_name(format!("{}-repair-{}", manifest.version, secret()?));
            fs::rename(&installed, &previous)?;
            if let Err(error) = fs::rename(staging, &installed) {
                fs::rename(previous, &installed)?;
                return Err(error.into());
            }
        } else {
            fs::rename(staging, &installed)?;
        }
    }
    finish_cancellable_setup(state)?;
    // The cached install or staged replacement has already passed byte verification.
    if install_only {
        stage(state, "Verified installation ready");
        return Ok(());
    }
    stage(state, "Starting local application");
    let token = secret()?;
    let ready = root.join("backend-ready.json");
    if ready.exists() {
        fs::remove_file(&ready)?;
    }
    let legacy_listener = if manifest.schema_version == 1 {
        Some(std::net::TcpListener::bind("127.0.0.1:0")?)
    } else {
        None
    };
    let legacy_port = legacy_listener
        .as_ref()
        .map(|l| l.local_addr().unwrap().port());
    drop(legacy_listener);
    let log = File::create(root.join("backend.log"))?;
    let mut command = Command::new(installed.join(executable));
    command
        .args(
            manifest
                .arguments
                .iter()
                .map(|a| a.replace("{port}", &legacy_port.unwrap_or(0).to_string())),
        )
        .current_dir(if manifest.schema_version == 2 {
            installed.join("application")
        } else {
            installed.clone()
        })
        .env("P2R_DATA_DIR", root.join("data"))
        .env("P2R_LAUNCH_TOKEN", &token)
        .env("P2R_READY_FILE", &ready)
        .env("P2R_MODELS_DIR", installed.join("models"))
        .env("HF_HOME", installed.join("models"))
        .env("P2R_DEFAULT_MODEL_ID", "da2-small")
        .env("P2R_DEVICE", "cpu")
        .env("PYTHONNOUSERSITE", "1")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME")
        .env("HF_HUB_OFFLINE", "1")
        .env("TRANSFORMERS_OFFLINE", "1")
        .env("HF_HUB_DISABLE_TELEMETRY", "1")
        .stdin(Stdio::null())
        .stdout(log.try_clone()?)
        .stderr(log);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let local_client = Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .build()?;
    let mut backend = BackendProcess {
        child: command.spawn()?,
    };
    let started = Instant::now();
    while started.elapsed() < Duration::from_secs(90) {
        if backend.child.try_wait()?.is_some() {
            return Err("backend exited before readiness; see backend.log".into());
        }
        let port = legacy_port.map(u64::from).or_else(|| {
            fs::read(&ready)
                .ok()
                .and_then(|b| serde_json::from_slice::<serde_json::Value>(&b).ok())
                .and_then(|v| v["port"].as_u64())
                .filter(|p| *p > 0 && *p <= 65535)
        });
        let Some(port) = port else {
            thread::sleep(Duration::from_millis(100));
            continue;
        };
        let app_url = if manifest.schema_version == 1 {
            format!("http://127.0.0.1:{port}/")
        } else {
            format!("http://127.0.0.1:{port}/?launch={token}")
        };
        if local_client
            .get(format!("http://127.0.0.1:{port}/api/health"))
            .header("X-Relief-Token", &token)
            .timeout(Duration::from_secs(1))
            .send()
            .map(|r| r.status().is_success())
            .unwrap_or(false)
        {
            let mut progress = state.lock().unwrap();
            progress.stage = "Ready — running locally".into();
            progress.app_url = Some(app_url.clone());
            drop(progress);
            fs::write(
                root.join("running.json"),
                serde_json::to_vec(&*state.lock().unwrap())?,
            )?;
            let status = backend.child.wait()?;
            if !status.success() {
                return Err("backend exited with an error".into());
            }
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }
    backend.child.kill()?;
    Err("backend readiness timed out".into())
}

fn demo_backend(port: &str) -> Result<()> {
    let server = Server::http(format!("127.0.0.1:{port}"))?;
    for request in server.incoming_requests() {
        let (body, kind) = if request.url() == "/api/health" {
            ("{\"status\":\"ok\",\"demo\":true}", "application/json")
        } else {
            (
                "<h1>Native bootstrap proof is running locally</h1><p>This is the M1 test backend, not Photo Relief Studio.</p>",
                "text/html",
            )
        };
        let _ = request.respond(
            Response::from_string(body)
                .with_header(Header::from_bytes("Content-Type", kind).unwrap()),
        );
    }
    Ok(())
}

fn main() {
    if let Err(error) = entry() {
        eprintln!("{error}");
        #[cfg(windows)]
        if !env::args().any(|a| a == "--no-browser") {
            #[link(name = "user32")]
            unsafe extern "system" {
                fn MessageBoxW(
                    window: *mut std::ffi::c_void,
                    text: *const u16,
                    title: *const u16,
                    flags: u32,
                ) -> i32;
            }
            let text: Vec<u16> = format!(
                "Photo Relief Studio could not start.\n\n{error}\n\nReopen the launcher to retry."
            )
            .encode_utf16()
            .chain(Some(0))
            .collect();
            let title: Vec<u16> = "Photo Relief Studio"
                .encode_utf16()
                .chain(Some(0))
                .collect();
            unsafe {
                MessageBoxW(std::ptr::null_mut(), text.as_ptr(), title.as_ptr(), 0x10);
            }
        }
        #[cfg(target_os = "macos")]
        if !env::args().any(|a| a == "--no-browser") {
            let escaped = error
                .to_string()
                .replace('&', "&amp;")
                .replace('<', "&lt;")
                .replace('>', "&gt;");
            let path = env::temp_dir().join(format!(
                "relief-startup-{}.html",
                secret().unwrap_or_else(|_| "error".into())
            ));
            let html = format!(
                "<!doctype html><meta charset=utf-8><title>Photo Relief Studio</title><style>body{{font:16px system-ui;background:#111;color:#eee;margin:10vh auto;max-width:600px;padding:24px}}p{{line-height:1.6}}</style><h1>Photo Relief Studio could not start</h1><p>{escaped}</p><p>Reopen the launcher to retry. Your projects stay on this computer.</p>"
            );
            if fs::write(&path, html).is_ok() {
                if let Ok(url) = reqwest::Url::from_file_path(path) {
                    let _ = open_browser(url.as_str());
                }
            }
        }
        std::process::exit(1);
    }
}

fn entry() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.get(1).map(String::as_str) == Some("--demo-backend") {
        if option_env!("P2R_MANIFEST_SHA256").is_some() {
            return Err("The engineering proof backend is unavailable in a pinned build.".into());
        }
        return demo_backend(args.get(2).ok_or("missing demo port")?);
    }
    let value = |key: &str| -> Result<String> {
        args.windows(2)
            .find(|pair| pair[0] == key)
            .map(|p| p[1].clone())
            .ok_or_else(|| format!("missing {key}").into())
    };
    let root = match value("--root") {
        Ok(value) => PathBuf::from(value),
        Err(_) => directories::ProjectDirs::from("com", "PhotoRelief", "PhotoReliefStudio")
            .ok_or("no writable application data directory")?
            .data_local_dir()
            .to_path_buf(),
    };
    fs::create_dir_all(&root)?;
    plain_path(&root, &root)?;
    let root = root.canonicalize()?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    }
    let _lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(root.join("launcher.lock"))?;
    if fs2::FileExt::try_lock_exclusive(&_lock).is_err() {
        if let Ok(url) = fs::read_to_string(root.join("setup-url.txt")) {
            if !args.iter().any(|a| a == "--no-browser") {
                open_browser(&url)?;
            }
        }
        return Ok(());
    }
    let manifest_path = value("--manifest")
        .map(PathBuf::from)
        .unwrap_or(env::current_exe()?.with_file_name("release.json"));
    let pinned = match option_env!("P2R_MANIFEST_SHA256") {
        Some(pin) => pin.to_owned(),
        None => value("--manifest-sha256")?,
    };
    if sha_file(&manifest_path, None)? != pinned {
        return Err("manifest SHA-256 does not match trusted pin".into());
    }
    let manifest: Manifest = serde_json::from_slice(&fs::read(&manifest_path)?)?;
    if let Some(address) = existing_application(&root) {
        if !args.iter().any(|a| a == "--no-browser") {
            open_browser(&address)?;
        }
        return Ok(());
    }
    let state: State = Arc::new(Mutex::new(Progress::default()));
    let setup_url = setup_server(state.clone())?;
    fs::write(root.join("setup-url.txt"), &setup_url)?;
    if !args.iter().any(|a| a == "--no-browser") {
        open_browser(&setup_url)?;
    }
    let interactive = !args.iter().any(|a| a == "--no-browser");
    let outcome = loop {
        {
            let mut progress = state.lock().unwrap();
            progress.error = None;
            progress.can_cancel = true;
            progress.cancel = false;
            progress.retry = false;
        }
        let attempt = run(
            manifest.clone(),
            &root,
            &state,
            args.iter().any(|a| a == "--allow-local-http"),
            args.iter().any(|a| a == "--install-only"),
        );
        if attempt.is_ok() {
            break attempt;
        }
        {
            let mut progress = state.lock().unwrap();
            progress.stage = "Setup stopped".into();
            progress.total = 0;
            progress.can_cancel = false;
            progress.error = Some(attempt.as_ref().unwrap_err().to_string());
        }
        fs::write(
            root.join("result.json"),
            serde_json::to_vec(&*state.lock().unwrap())?,
        )?;
        if !interactive {
            break attempt;
        }
        loop {
            if state.lock().unwrap().retry {
                break;
            }
            thread::sleep(Duration::from_millis(200));
        }
    };
    fs::write(
        root.join("result.json"),
        serde_json::to_vec(&*state.lock().unwrap())?,
    )?;
    // Leave a visible explanation in the browser on setup failure.
    if outcome.is_err() && !args.iter().any(|a| a == "--no-browser") {
        thread::sleep(Duration::from_secs(300));
    }
    outcome
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_unsafe_paths() {
        for path in [
            "../escape",
            "/root",
            "C:/Windows/x",
            "a\\..\\b",
            "",
            "a/../b",
            "CON",
            "test.",
            "AUX.log",
            "a/b ",
        ] {
            assert!(safe_relative(path).is_err(), "{path}");
        }
        assert!(safe_relative("runtime/python.exe").is_ok());
    }
    #[test]
    fn https_is_required_outside_loopback_test_mode() {
        assert!(verify_url("https://example.com/file.zip", false).is_ok());
        assert!(verify_url("http://example.com/file.zip", true).is_err());
        assert!(verify_url("http://127.0.0.1/file.zip", false).is_err());
        assert!(verify_url("http://127.0.0.1/file.zip", true).is_ok());
        assert!(verify_url("https://private:token@example.com/file.zip", false).is_err());
    }
    #[test]
    fn bundled_application_is_authenticated_and_recovers_from_cache() {
        let root = env::temp_dir().join(format!("relief-bundle-{}", secret().unwrap()));
        let cache = root.join("cache");
        fs::create_dir_all(&cache).unwrap();
        let source = root.join("application.zip");
        fs::write(&source, b"bundled paid application").unwrap();
        let mut item = Artifact {
            id: "application".into(),
            url: "".into(),
            bundled_path: Some("application.zip".into()),
            size_bytes: 24,
            unpacked_limit_bytes: 100,
            sha256: sha_file(&source, None).unwrap(),
        };
        item.size_bytes = source.metadata().unwrap().len();
        let state = Arc::new(Mutex::new(Progress::default()));
        fs::write(&source, b"damaged").unwrap();
        assert!(bundled_archive(&item, &root, &cache, &state).is_err());
        fs::write(&source, b"bundled paid application").unwrap();
        let verified = bundled_archive(&item, &root, &cache, &state).unwrap();
        assert_eq!(fs::read(&verified).unwrap(), b"bundled paid application");
        fs::remove_file(&source).unwrap();
        assert_eq!(
            bundled_archive(&item, &root, &cache, &state).unwrap(),
            verified
        );
        item.bundled_path = Some("../escape.zip".into());
        assert!(bundled_archive(&item, &root, &cache, &state).is_err());
        item.bundled_path = Some("application.zip".into());
        item.url = "https://example.com/application.zip".into();
        assert!(bundled_archive(&item, &root, &cache, &state).is_err());
        remove_staging(&root).unwrap();
    }
    #[test]
    fn interrupted_redirected_download_resumes_and_verifies() {
        use std::net::{Shutdown, TcpListener};
        let root = env::temp_dir().join(format!("relief-resume-{}", secret().unwrap()));
        fs::create_dir_all(&root).unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let handle = thread::spawn(move || {
            for index in 0..4 {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(10)))
                    .unwrap();
                let mut request = Vec::new();
                while !request.ends_with(b"\r\n\r\n") {
                    let mut b = [0];
                    if stream.read(&mut b).unwrap() == 0 {
                        break;
                    }
                    request.push(b[0]);
                }
                let text = String::from_utf8(request).unwrap().to_ascii_lowercase();
                if index >= 2 {
                    assert!(text.contains("range: bytes=3-"), "{text}");
                }
                let response = match index {
                    0 | 2 => format!("HTTP/1.1 302 Found\r\nLocation: http://{address}/payload\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"),
                    1 => "HTTP/1.1 200 OK\r\nContent-Length: 9\r\nConnection: close\r\n\r\nabc".into(),
                    _ => "HTTP/1.1 206 Partial Content\r\nContent-Length: 6\r\nContent-Range: bytes 3-8/9\r\nConnection: close\r\n\r\ndefghi".into(),
                };
                stream.write_all(response.as_bytes()).unwrap();
                stream.shutdown(Shutdown::Both).unwrap();
            }
        });
        let item = Artifact {
            id: "runtime".into(),
            url: format!("http://{address}/start"),
            bundled_path: None,
            size_bytes: 9,
            unpacked_limit_bytes: 9,
            sha256: format!("{:x}", Sha256::digest(b"abcdefghi")),
        };
        let state = Arc::new(Mutex::new(Progress::default()));
        let client = download_client(true).unwrap();
        assert!(download(&client, &item, &root, &state, true).is_err());
        assert_eq!(
            fs::read(root.join(format!("{}.part", item.sha256))).unwrap(),
            b"abc"
        );
        let verified = download(&client, &item, &root, &state, true).unwrap();
        assert_eq!(fs::read(verified).unwrap(), b"abcdefghi");
        handle.join().unwrap();
        remove_staging(&root).unwrap();
    }
    #[test]
    fn redirects_cannot_leave_secure_or_loopback_test_transport() {
        let server = Server::http("127.0.0.1:0").unwrap();
        let url = format!("http://{}/start", server.server_addr());
        let handle = thread::spawn(move || {
            server
                .recv()
                .unwrap()
                .respond(Response::empty(302).with_header(
                    Header::from_bytes("Location", "http://example.com/insecure").unwrap(),
                ))
                .unwrap();
        });
        assert!(download_client(true).unwrap().get(url).send().is_err());
        handle.join().unwrap();
    }
    #[test]
    fn rejects_traversal_and_oversized_extraction() {
        use zip::write::SimpleFileOptions;
        for (name, limit) in [("../outside.txt", 4096), ("safe/file.txt", 2)] {
            let root = env::temp_dir().join(format!("relief-test-{}", secret().unwrap()));
            fs::create_dir_all(&root).unwrap();
            let file = root.join("payload.zip");
            let mut zip = zip::ZipWriter::new(File::create(&file).unwrap());
            zip.start_file(name, SimpleFileOptions::default()).unwrap();
            zip.write_all(b"verified fixture").unwrap();
            zip.finish().unwrap();
            let output = root.join("staging");
            fs::create_dir(&output).unwrap();
            let state = Arc::new(Mutex::new(Progress::default()));
            assert!(extract(&file, &output, limit, &state).is_err());
            assert!(!root.join("outside.txt").exists());
            remove_staging(&root).unwrap();
        }
    }

    #[test]
    fn canceled_extraction_preserves_existing_files() {
        let root = env::temp_dir().join(format!("relief-test-{}", secret().unwrap()));
        fs::create_dir_all(&root).unwrap();
        let archive = root.join("payload.zip");
        let mut zip = zip::ZipWriter::new(File::create(&archive).unwrap());
        zip.start_file("file.txt", zip::write::SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"new").unwrap();
        zip.finish().unwrap();
        let output = root.join("staging");
        fs::create_dir(&output).unwrap();
        fs::write(output.join("file.txt"), b"original").unwrap();
        let state = Arc::new(Mutex::new(Progress {
            cancel: true,
            ..Default::default()
        }));
        assert!(extract(&archive, &output, 100, &state).is_err());
        assert_eq!(fs::read(output.join("file.txt")).unwrap(), b"original");
        remove_staging(&root).unwrap();
    }
    #[test]
    fn installation_repairs_from_verified_cache_and_keeps_projects() {
        let root = env::temp_dir().join(format!("relief-test-{}", secret().unwrap()));
        fs::create_dir_all(&root).unwrap();
        let payload = root.join("payload.zip");
        let mut zip = zip::ZipWriter::new(File::create(&payload).unwrap());
        zip.start_file(
            "application/backend",
            zip::write::SimpleFileOptions::default(),
        )
        .unwrap();
        zip.write_all(b"verified application").unwrap();
        zip.finish().unwrap();
        let bytes = fs::read(&payload).unwrap();
        let digest = sha_file(&payload, None).unwrap();
        let length = bytes.len() as u64;
        let server = Server::http("127.0.0.1:0").unwrap();
        let url = format!("http://{}/payload.zip", server.server_addr());
        let handle = thread::spawn(move || {
            let request = server.recv().unwrap();
            request.respond(Response::from_data(bytes)).unwrap();
        });
        let manifest = Manifest {
            schema_version: 2,
            version: "repair-test".into(),
            platform: platform_id(),
            components: vec![Artifact {
                id: "application".into(),
                url,
                bundled_path: None,
                size_bytes: length,
                unpacked_limit_bytes: 100,
                sha256: digest,
            }],
            executable: "application/backend".into(),
            arguments: vec![],
        };
        let state = Arc::new(Mutex::new(Progress::default()));
        fs::create_dir(root.join("data")).unwrap();
        fs::write(root.join("data/photo"), b"customer work").unwrap();
        run(manifest.clone(), &root, &state, true, true).unwrap();
        handle.join().unwrap();
        let installed = root.join("versions/repair-test/application/backend");
        state.lock().unwrap().cancel = true;
        let canceled = run(manifest.clone(), &root, &state, true, true).unwrap_err();
        assert!(canceled.to_string().contains("Setup canceled"));
        assert_eq!(fs::read(&installed).unwrap(), b"verified application");
        state.lock().unwrap().cancel = false;

        // The new version gets its own staging and cannot replace the old release.
        let mut upgrade = manifest.clone();
        upgrade.version = "failed-upgrade".into();
        upgrade.executable = "application/missing".into();
        assert!(run(upgrade, &root, &state, true, true).is_err());
        assert!(!root.join("versions/failed-upgrade").exists());
        run(manifest.clone(), &root, &state, true, true).unwrap();
        assert_eq!(fs::read(&installed).unwrap(), b"verified application");

        fs::write(&installed, b"damage").unwrap();
        fs::create_dir_all(root.join("staging/repair-test")).unwrap();
        fs::write(root.join("staging/repair-test/partial"), b"interrupted").unwrap();
        run(manifest, &root, &state, true, true).unwrap();
        assert_eq!(fs::read(installed).unwrap(), b"verified application");
        assert_eq!(fs::read(root.join("data/photo")).unwrap(), b"customer work");
        remove_staging(&root).unwrap();
    }

    #[test]
    fn insufficient_space_is_refused_before_download() {
        let root = env::temp_dir().join(format!("relief-test-{}", secret().unwrap()));
        fs::create_dir_all(&root).unwrap();
        let manifest = Manifest {
            schema_version: 2,
            version: "space-test".into(),
            platform: platform_id(),
            components: vec![Artifact {
                id: "runtime".into(),
                url: "http://127.0.0.1:1/file.zip".into(),
                bundled_path: None,
                size_bytes: 1,
                unpacked_limit_bytes: u64::MAX / 2,
                sha256: "0".repeat(64),
            }],
            executable: "runtime/python".into(),
            arguments: vec![],
        };
        let state = Arc::new(Mutex::new(Progress::default()));
        assert!(
            run(manifest, &root, &state, true, true)
                .unwrap_err()
                .to_string()
                .contains("disk space")
        );
        remove_staging(&root).unwrap();
    }
    #[test]
    fn unsupported_manifest_platform_is_refused_before_installation() {
        let root = env::temp_dir().join(format!("relief-test-{}", secret().unwrap()));
        let manifest = Manifest {
            schema_version: 2,
            version: "platform-test".into(),
            platform: "unsupported-architecture".into(),
            components: vec![],
            executable: "runtime/python".into(),
            arguments: vec![],
        };
        let state = Arc::new(Mutex::new(Progress::default()));
        assert!(
            run(manifest, &root, &state, false, true)
                .unwrap_err()
                .to_string()
                .contains("platform")
        );
        assert!(!root.exists());
    }
}
