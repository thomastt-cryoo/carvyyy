# M5 engineering status

M5 is in progress on codex/m5-production-launcher, based on approved M4 60883a6. Current files are implementation work and test candidates.

The native Rust supervisor uses a manifest SHA-256 embedded at compilation as its trust root. The adjacent release.json can be distributed in the small launcher ZIP. Changing any metadata or download URL requires a newly pinned launcher. This provides an immutable release mechanism without requiring a live update service for normal startup.

Runtime packaging installs a standalone Python 3.12.16 distribution and hash-locked CPU dependencies into a dedicated build prefix. It packages runtime, application, and Small model components separately. It does not copy the development virtual environment. The packaged backend reserves its own loopback socket, supplies readiness information to the supervisor, and requires a fresh launch credential. Browser entry sets an HttpOnly SameSite=Strict cookie and redirects away from the credential URL. Host and Origin checks also apply to static resources and local APIs.

Local regression results so far are 200 Python fast passes, 8 Node passes, and 6 Rust unit passes. Full runtime extraction and inference acceptance is pending. The legacy M1 smoke uncovered a behavior change where a tampered legacy installation was repaired instead of rejected. Legacy schema 1 rejection has been restored while schema 2 retains component repair. Retesting is pending.

No R2 bucket or public release has been configured. Local candidate component URLs use a controlled loopback test server. Signing credentials are unavailable. Native Mac execution, Finder and Gatekeeper checks require separate evidence. Completion must be recorded only after the actual integration and candidate checks run.

## Provenance

- Python standalone distributions https://docs.astral.sh/python-build-standalone/
- Default Small model and Apache-2.0 metadata https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf
- uv acquisition checksum and exact release are recorded under data/m5/tools/uv-provenance.json locally.

## R2 publishing

The publishing tool accepts R2_ENDPOINT, R2_BUCKET, R2_PUBLIC_BASE_URL, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY through the publisher environment. These values stay outside customer artifacts. Immutable objects use conditional writes and checksum metadata. Public custom-domain downloads must be independently verified before a launcher is distributed. boto3 is a publisher dependency, and it is separate from the customer runtime.

The first clean Windows installation attempt reached its 600-second test limit while extracting/verifying files. The launcher now caches ancestor checks within a pass, avoids per-file disk flushes during staged extraction, and performs one installed-byte verification per launch. An interrupted-installation retry is in progress. The Windows test ZIP with a pinned manifest is 1,119,360 bytes and its PE subsystem is Windows GUI. The tests run without elevated privileges. The preview timing case passed on its focused rerun, followed by a complete 200-test fast pass.

The Windows RC2 native acceptance passed a fresh install (184.97 s), new Small inference (14.53 s), STL/OBJ exports, unauthorized and cross-origin HTTP refusal, offline relaunch (40.58 s), and project preservation. A separate extracted-runtime test denied external Python socket connections and passed new inference (14.69 s), alpha isolation, depth editing, preview and watertight 150 mm STL/OBJ exports. A connection-reset shutdown issue on Windows prompted an explicit Uvicorn Selector loop factory and bounded graceful shutdown. A direct real-runtime regression exited after 1.34 s. Native RC3 and GUI acceptance are being checked. macOS 14 runner configuration was rejected by GitHub, so preserved and M5 workflows now use the supported macOS 15 arm64 runner.

The distribution build includes locked ONNX Runtime and verified U2NETP assets to preserve the optional offline isolation method. The default Small model is pinned to revision 5426e4f0f36572d16453bbda7a8389317b1bef99. Native network failure acceptance passed interrupted transfer, Range resume, complete corruption rejection, successful retry and customer-data preservation. The Windows launcher now statically links its C runtime so first launch does not depend on a separately installed Visual C++ redistributable. Final candidate measurements and remaining platform evidence are being assembled.
