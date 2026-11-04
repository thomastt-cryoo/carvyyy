//! M1 feasibility proof; intentionally not a production installer.
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
    url: String,
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
    Ok(path.to_path_buf())
}

fn sha_file(path: &Path) -> Result<String> {
    let mut file = File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn stage(state: &State, message: &str) {
    state.lock().unwrap().stage = message.into();
}

fn verify_url(url: &str, allow_local: bool) -> Result<()> {
    let url = reqwest::Url::parse(url)?;
    if url.scheme() != "https"
        && !(allow_local && url.scheme() == "http" && url.host_str() == Some("127.0.0.1"))
    {
        return Err("components require HTTPS (test HTTP is restricted to 127.0.0.1)".into());
    }
    Ok(())
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
    let final_path = root.join(format!("{}.zip", item.sha256));
    let partial = root.join(format!("{}.part", item.sha256));
    if final_path.exists()
        && final_path.metadata()?.len() == item.size_bytes
        && sha_file(&final_path)? == item.sha256
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
        let mut response = request.send()?.error_for_status()?;
        // A server ignoring Range is legal: restart, never append a complete response.
        if offset > 0 && response.status().as_u16() == 200 {
            offset = 0;
        } else if response.status().as_u16() == 206 {
            let expected = format!("bytes {offset}-");
            let content_range = response
                .headers()
                .get("content-range")
                .and_then(|h| h.to_str().ok())
                .unwrap_or("");
            if !content_range.starts_with(&expected)
                || !content_range.ends_with(&format!("/{}", item.size_bytes))
            {
                return Err("invalid resumed Content-Range".into());
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
            let count = response.read(&mut buffer)?;
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
    if partial.metadata()?.len() != item.size_bytes || sha_file(&partial)? != item.sha256 {
        // Preserve interrupted bytes for retry; discard a complete corrupt payload.
        if partial.metadata()?.len() == item.size_bytes {
            fs::remove_file(&partial)?;
        }
        return Err("component size or SHA-256 mismatch; component was not executed".into());
    }
    fs::rename(partial, &final_path)?;
    Ok(final_path)
}

fn extract(archive: &Path, dest: &Path, limit: u64) -> Result<()> {
    let mut zip = zip::ZipArchive::new(File::open(archive)?)?;
    let mut total = 0u64;
    for index in 0..zip.len() {
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
        if entry.is_dir() {
            fs::create_dir_all(&target)?;
        } else {
            fs::create_dir_all(target.parent().ok_or("no parent")?)?;
            let mut out = File::create(&target)?;
            std::io::copy(&mut entry, &mut out)?;
            out.sync_all()?;
            #[cfg(unix)]
            if let Some(mode) = entry.unix_mode() {
                use std::os::unix::fs::PermissionsExt;
                fs::set_permissions(&target, fs::Permissions::from_mode(mode & 0o777))?;
            }
        }
    }
    Ok(())
}

fn verify_installed(manifest: &Manifest, installed: &Path, cache: &Path) -> Result<()> {
    // The local completion marker is not a trust root. Revalidate installed bytes
    // against the archives authenticated by the pinned manifest before execution.
    for item in &manifest.components {
        let archive = cache.join(format!("{}.zip", item.sha256));
        if archive.metadata()?.len() != item.size_bytes || sha_file(&archive)? != item.sha256 {
            return Err("cached component failed verification".into());
        }
        let mut zip = zip::ZipArchive::new(File::open(archive)?)?;
        for index in 0..zip.len() {
            let mut entry = zip.by_index(index)?;
            if entry.is_dir() {
                continue;
            }
            let relative = entry.enclosed_name().ok_or("unsafe archive member")?;
            let path = installed.join(relative);
            if fs::symlink_metadata(&path)?.file_type().is_symlink()
                || path.metadata()?.len() != entry.size()
            {
                return Err("installed component is missing, replaced or corrupt".into());
            }
            let mut expected = Sha256::new();
            let mut buffer = [0u8; 65536];
            loop {
                let count = entry.read(&mut buffer)?;
                if count == 0 {
                    break;
                }
                expected.update(&buffer[..count]);
            }
            if sha_file(&path)? != format!("{:x}", expected.finalize()) {
                return Err("installed component SHA-256 mismatch; not executed".into());
            }
        }
    }
    Ok(())
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
    let url = format!("http://{}/", server.server_addr());
    thread::spawn(move || {
        for request in server.incoming_requests() {
            if request.method().as_str() != "GET" {
                let _ = request.respond(Response::empty(405));
                continue;
            }
            let (body, content_type) = match request.url() {
                "/" => (PAGE.to_owned(), "text/html; charset=utf-8"),
                "/status" => (
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
    if manifest.schema_version != 1 || manifest.platform != platform_id() {
        return Err("unsupported manifest schema or platform".into());
    }
    safe_relative(&manifest.version)?;
    let executable = safe_relative(&manifest.executable)?;
    let client = Client::builder()
        .connect_timeout(Duration::from_secs(20))
        .timeout(Duration::from_secs(1800))
        .redirect(reqwest::redirect::Policy::none())
        .build()?;
    let cache = root.join("downloads");
    fs::create_dir_all(&cache)?;
    let installed = root.join("versions").join(&manifest.version);
    let manifest_bytes = serde_json::to_vec(&manifest)?;
    let marker = installed.join("verified-manifest.json");
    let valid_install = marker.exists() && fs::read(&marker)? == manifest_bytes;
    if !valid_install {
        let staging = root.join("staging").join(&manifest.version);
        // Never recursively replace an existing installation in this M1 proof.
        if staging.exists() || installed.exists() {
            return Err("staging/version already exists; use a new test root or version".into());
        }
        let mut archives = Vec::new();
        for item in &manifest.components {
            archives.push((download(&client, item, &cache, state, local)?, item));
        }
        fs::create_dir_all(&staging)?;
        for (archive, item) in archives {
            stage(state, &format!("Extracting verified {}", item.id));
            extract(&archive, &staging, item.unpacked_limit_bytes)?;
        }
        if !staging.join(&executable).is_file() {
            return Err("manifest executable is missing from verified components".into());
        }
        fs::write(staging.join("verified-manifest.json"), manifest_bytes)?;
        fs::create_dir_all(installed.parent().ok_or("no version parent")?)?;
        fs::rename(staging, &installed)?;
    }
    stage(state, "Verifying installed components");
    verify_installed(&manifest, &installed, &cache)?;
    if install_only {
        stage(state, "Verified installation ready");
        return Ok(());
    }
    stage(state, "Starting local application");
    // Reserve a loopback port; production needs a child handshake to eliminate this race.
    let socket = std::net::TcpListener::bind("127.0.0.1:0")?;
    let port = socket.local_addr()?.port();
    drop(socket);
    let app_url = format!("http://127.0.0.1:{port}/");
    let log = File::create(root.join("backend.log"))?;
    let mut command = Command::new(installed.join(executable));
    command
        .args(
            manifest
                .arguments
                .iter()
                .map(|a| a.replace("{port}", &port.to_string())),
        )
        .current_dir(&installed)
        .env("P2R_DATA_DIR", root.join("data"))
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
    let mut child = command.spawn()?;
    let started = Instant::now();
    while started.elapsed() < Duration::from_secs(90) {
        if child.try_wait()?.is_some() {
            return Err("backend exited before readiness; see backend.log".into());
        }
        if client
            .get(format!("{app_url}api/health"))
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
            let status = child.wait()?;
            if !status.success() {
                return Err("backend exited with an error".into());
            }
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }
    child.kill()?;
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
        std::process::exit(1);
    }
}

fn entry() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.get(1).map(String::as_str) == Some("--demo-backend") {
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
    let manifest_path = PathBuf::from(value("--manifest")?);
    let pinned = value("--manifest-sha256")?;
    if sha_file(&manifest_path)? != pinned {
        return Err("manifest SHA-256 does not match trusted pin".into());
    }
    let manifest: Manifest = serde_json::from_slice(&fs::read(&manifest_path)?)?;
    let state: State = Arc::new(Mutex::new(Progress::default()));
    let setup_url = setup_server(state.clone())?;
    fs::write(root.join("setup-url.txt"), &setup_url)?;
    if !args.iter().any(|a| a == "--no-browser") {
        open_browser(&setup_url)?;
    }
    let outcome = run(
        manifest,
        &root,
        &state,
        args.iter().any(|a| a == "--allow-local-http"),
        args.iter().any(|a| a == "--install-only"),
    );
    if let Err(ref error) = outcome {
        let mut progress = state.lock().unwrap();
        progress.stage = "Setup stopped".into();
        progress.error = Some(error.to_string());
    }
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
    }
}
