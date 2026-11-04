# M1 native bootstrap feasibility proof

This is an engineering prototype, not the production customer installer.
See [the architecture decision](../docs/m1/ARCHITECTURE.md) and
[milestone report](../docs/m1/REPORT.md).

Build from this directory with a Rust toolchain and native linker/SDK:

```text
cargo build --release --locked
cargo test --locked
```

Run the executable acceptance harness from the repository root (Python is needed
by the developer harness only, not by the native launcher):

```text
.venv/Scripts/python.exe -m tools.m1.bootstrap_smoke --exe bootstrapper/target/release/relief-bootstrap.exe --output data/m1/bootstrap-proof
```

Use `.venv/bin/python` and `bootstrapper/target/release/relief-bootstrap` on macOS.
The output directory must be new. The proof serves an explicitly labeled native
demo backend, not fake AI. It tests interrupted downloads, Range resume, ignored
Range, genuine byte progress, corruption, manifest trust, unsafe archives,
installed-file integrity and offline restart. It records executable/ZIP sizes.

Manual prototype arguments are `--manifest FILE --manifest-sha256 DIGEST`;
optional `--root DIR`, `--no-browser`, `--install-only`. `--allow-local-http` is
strictly for the test source server on 127.0.0.1. The sample manifest uses
nonexistent `.invalid` URLs and zero hashes deliberately; production R2 setup is
outside M1. No customer should be asked to use these developer commands.
