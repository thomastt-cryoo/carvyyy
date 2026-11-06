# Connect the release download bucket

The customer ZIP is small. The launcher downloads the application, Python runtime and AI models from a separate Cloudflare R2 bucket. The bucket should contain release files only because the connected domain serves those files publicly.

## Owner setup in Cloudflare and GitHub

1. Open **Cloudflare → Storage & databases → R2 → Overview**. Create or choose a dedicated release bucket. In its **Settings → Custom Domains**, connect a download subdomain of a domain you control in Cloudflare. Wait for **Active**. Leave the public development URL disabled. [Cloudflare custom domain instructions](https://developers.cloudflare.com/r2/buckets/public-buckets/)
2. In R2 **Overview → Manage API Tokens**, create an **Object Read & Write** token scoped to that bucket. Keep the Access Key ID and Secret Access Key private. Cloudflare shows the S3 endpoint in R2 Overview or when creating the token. The S3 endpoint and public download URL are separate addresses. [Cloudflare S3 credentials instructions](https://developers.cloudflare.com/r2/get-started/s3/)
3. In the GitHub repository, go to **Settings → Environments** and create **r2-release**. Limit deployment branches to the trusted release branch or default branch and add a required reviewer if your plan supports it. Enter the following values there. Do not paste credentials into chat, files, issues or Git history.

| Where in the environment | Name | Value |
| --- | --- | --- |
| Environment variable | `R2_ENDPOINT` | HTTPS S3 API endpoint shown by Cloudflare |
| Environment variable | `R2_BUCKET` | Exact dedicated bucket name |
| Environment variable | `R2_PUBLIC_BASE_URL` | HTTPS custom download domain shown as Active, with an optional release path prefix |
| Environment secret | `R2_ACCESS_KEY_ID` | Bucket-scoped Access Key ID |
| Environment secret | `R2_SECRET_ACCESS_KEY` | Bucket-scoped Secret Access Key |

## Release operator verification

After the workflow is available on the GitHub default branch, open **Actions → M6 release verification → Run workflow**. Select the trusted release branch and choose **r2**. The **controlled** option uses local test downloads and requires no R2 settings. The workflow is available for automatic controlled tests on the M6 pull request before the manual workflow is enabled. [GitHub manual workflow instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)

The R2 run gives the archives a unique release version, creates the manifest with the actual HTTPS URLs and builds a launcher pinned to that manifest. The publisher creates the component objects without overwriting previous versions. It verifies full bytes and SHA-256, then checks a resumed Range response on the public domain. Each native runner then extracts its actual customer ZIP and runs a fresh setup from that domain. The workflow provides ZIPs and checksums only for jobs that pass. Confirm **both** platforms succeeded before considering either ZIP for customer distribution.

The workflow uploads the component archives to R2. Etsy delivery uses the small ZIP for the customer's platform. Keep previous component objects available for reinstall and rollback.

Current deployment status is **pending owner configuration and a verified R2 run**.
