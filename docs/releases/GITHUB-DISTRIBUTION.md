# GitHub customer distribution

This replaces Cloudflare R2. No Cloudflare account, bucket, custom domain, hosting subscription or billing card is used by this pipeline.

## What the customer receives

The platform-specific Etsy ZIP contains the native launcher, its SHA-256-pinned manifest, the small application archive, dependency notices and the customer guide. The packager refuses a ZIP at or above the internal 19,000,000-byte budget, below Etsy's 20 MB limit. The customer extracts the entire ZIP and opens the application normally. There is no GitHub account, Python installation, terminal command or manual model setup.

Windows x64 requires Windows 11 on Intel/AMD x64. The unsigned Apple Silicon build requires macOS 15 or later. SmartScreen, Gatekeeper and managed-device restrictions can still apply. The guide explains the unsigned distribution route and Apple's Open Anyway procedure; signing and notarization are not prerequisites.

## Public release contents and privacy boundary

Only four third-party dependency archives are uploaded as public release assets: runtime and models for Windows x64 and macOS arm64. The depth model is pinned Depth Anything V2 Small. The model component also preserves U2NETP for optional offline background isolation. DA3 Mono Large and V2 Large are not customer model choices or bundled weights.

The application archive, Etsy ZIP, customer projects, photographs and development credentials are not release assets. The publisher accepts a complete, version-matched allowlist and checks archive member roots before creating a draft. It fails if the input contains application ZIPs, unexpected members, duplicate assets or removed depth models. It compares GitHub's uploaded byte counts and SHA-256 digests before publication.

GitHub automatically offers source archives for release tags. Component tags therefore point to a fresh, parentless dependency-inventory commit containing only a README and dependency checksums, rather than the application source tree. The repository's existing public visibility is not changed. Existing application source and Actions artifacts in a public repository are not an access-control boundary for a paid product. Keeping future application source private would require a separate private development repository; this integration does not migrate or change repository visibility.

## Immutable versions and trust

Each run gets a unique `1.1.2-gh-RUN_ID-ATTEMPT` version and a `components-...` tag. GitHub release immutability must be enabled in repository Settings → General → Releases. The publisher never overwrites existing releases and refuses qualification unless GitHub reports the published release immutable. The tag starts with `components-`, so it does not trigger the legacy `v*` container publisher.

Customer manifests contain stable `https://github.com/OWNER/REPO/releases/download/TAG/ASSET` addresses, actual byte sizes and SHA-256 values. They do not use expiring CDN URLs, `latest`, the GitHub API or credentials. The native binary embeds the manifest digest. Bundled application bytes pass the same size and checksum verification as downloaded dependencies. Installed files are verified against authenticated cached archives before execution. Versions, previous launchers and customer data remain available for recovery.

Downloads follow at most ten redirects, retaining HTTPS and rejecting embedded URL credentials. Test-only HTTP is restricted to 127.0.0.1, including redirects. Interrupted bytes stay in a `.part` file and retries use Range from the verified offset. A server returning 200 instead of 206 restarts safely. Complete corrupt payloads are discarded and never executed. The browser setup screen retains byte progress, cancellation, errors and Retry setup.

## Actions pipeline

`GitHub customer distribution` builds both native targets from the current branch and locked dependencies. The dedicated integration branch triggers it on push. After the workflow reaches the default branch, maintainers can also use Run workflow. No customer action is involved.

Build jobs upload dependency-only staging artifacts separately from Etsy candidates. The publication job downloads only the dependency artifacts and has `contents: write`; the other jobs have `contents: read`. Its ephemeral `GITHUB_TOKEN` exists only in the publication step. It is never included in manifests, archives, URLs or launchers. No personal access token or additional secret is required.

After publication, fresh native jobs fetch the actual public links anonymously, verify full bytes and checksums and request a resumed Range response. They extract the actual customer ZIP and test first installation with a minimal PATH, duplicate launch, local API protections, real new-photo inference, STL/OBJ export, offline reopen through an unavailable external proxy, project preservation and cached repair after deliberate installed-file damage. A separate extracted-runtime process denies external socket connections and checks fresh inference, alpha and U2NETP isolation, brush editing, previews, global Undo/Redo, saved projects and watertight STL/OBJ exports. Only successful jobs produce `verified-etsy-*` artifacts.

Windows/macOS runner checks are not equivalent to physical desktop or Finder/Gatekeeper tests. A local Windows browser journey is recorded separately. No final Etsy publication is performed by this workflow.

## Operator recovery

If a build or upload fails, fix forward with a new run/version. Do not replace assets under an existing tag. Leave older immutable components published for customers reinstalling an older Etsy ZIP. A release that has published components but has not passed both qualification jobs is not a customer-ready installer release. Retrieve only the pair of successful `verified-etsy-*` artifacts for delivery.

References: [GitHub immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases), [release asset API](https://docs.github.com/en/rest/releases/assets), [repository release immutability API](https://docs.github.com/en/rest/repos/repos#enable-immutable-releases).
