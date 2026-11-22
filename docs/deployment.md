# Optional GCP deployment — unverified

No paid resources were created. Earlier local checks recorded Terraform format/schema validation; Terraform was unavailable for a release-time rerun. The combined image is tested locally separately from cloud deployment. Review quotas, IAM, regional support and current prices before explicitly choosing to provision.

## Resources

`deploy/main.tf` declares APIs, runtime service account, PostgreSQL 16 Cloud SQL/database, private original-file bucket with 30-day expiry, database-URL Secret Manager container and IAM. Passwords and secret versions are intentionally outside Terraform state. `deploy/service.yaml.example` configures Cloud Run; the root Dockerfile builds one same-origin UI/API image. Artifact Registry and secret versions need explicit setup.

Cloud SQL supports pgvector using `CREATE EXTENSION vector`. Cloud Run's SQL attachment exposes `/cloudsql/PROJECT:REGION:INSTANCE`. Consult [supported extensions](https://docs.cloud.google.com/sql/docs/postgres/extensions) and [Cloud Run SQL connections](https://docs.cloud.google.com/sql/docs/postgres/connect-run).

## Provision only after authorization

1. Authenticate `gcloud`, select a billing project and supported region, and enable any bootstrap APIs needed. Use protected remote Terraform state for shared deployments.
2. Run `terraform -chdir=deploy init`, `terraform -chdir=deploy validate`, then `terraform -chdir=deploy plan -var=project_id=PROJECT -var=bucket_name=GLOBALLY_UNIQUE_BUCKET`. Review paid resources. Run the corresponding `apply` only when authorized. No plan/apply against an account was executed during local verification.
3. Create an application database user with a strong password through secure console/CLI input. Use an admin/setup identity to install `vector`, run Alembic and grant runtime table permissions. Do not retain an instance-admin account as runtime identity. Database role separation is an explicit setup step beyond the small Terraform template.
4. Add a Secret Manager version containing `postgresql+psycopg://USER:ENCODED_PASSWORD@/databridge?host=/cloudsql/PROJECT:REGION:databridge-db`. URL-encode password characters. Use stdin/console rather than committed files or shell-history literals.
5. Create an Artifact Registry Docker repository; build the root image for linux/amd64, tag and push. Example with replaced values: `docker build --platform linux/amd64 -t REGION-docker.pkg.dev/PROJECT/REPOSITORY/databridge:TAG .`.

## Bootstrap and service

Use the same image, region, SQL attachment and DATABASE_URL secret for setup jobs. Example migration job with replaced placeholders:

```sh
gcloud run jobs create databridge-migrate --image IMAGE --region REGION --service-account SERVICE_ACCOUNT --set-cloudsql-instances PROJECT:REGION:databridge-db --set-secrets DATABASE_URL=databridge-database-url:latest --command alembic --args upgrade,head
gcloud run jobs execute databridge-migrate --region REGION --wait
```

Provision the operator using a separate short-lived setup job: `--command python --args=-m,app.cli,setup-operator,--username,operator`. Bind SETUP_PASSWORD from a short-lived secret, not plaintext flags. Delete setup jobs and password secret afterward. Use a migration/setup database identity for bootstrap and least-privilege runtime grants afterward.

Run a separate ingestion job with `--command python --args=-m,app.cli,ingest`. Supply AI_MODE=vertex, project, region, verified embedding model and dimensions; this makes billable embedding calls. Confirm a nonempty Vertex collection. Mock chunks cannot satisfy Vertex retrieval.

Copy the service example to an untracked local file and replace every placeholder. Configure accessible Gemini generation and compatible embedding model identifiers; dimensions must match ingestion. Set COOKIE_SECURE=true, AI_MODE=vertex and GCS_BUCKET. Deploy initially with restricted invocation, discover its actual URL, then set ALLOWED_ORIGINS to exactly that HTTPS origin. Decide explicitly whether browser invocation should be public; application login is still required. Apply the completed service file with `gcloud run services replace YOUR_FILE --region REGION`. Configure current Cloud Run ingress/IAM for your audience.

Optional GCS archives use generated `uploads/UUID/HASH.csv` object names and create-only permission. Storage failure aborts upload. A later database error can leave an orphan object; lifecycle expiry removes it. Cloud SQL parsed values/reports need their own retention policy; bucket expiry does not delete them.

## Credentialed verification still required

- Verify project/region access to generation/embedding models, dimensions and structured outputs.
- Verify SQL migration, vector extension, unique constraints, secret mounting, runtime grants and private object writes.
- Provision/login over HTTPS; inspect Secure/HttpOnly cookies, CSRF/origin handling and logout.
- Ingest, retrieve and inspect actual vector results and citations; change/delete documents and verify stale-chunk removal and collection isolation.
- Exercise real Mapping Agent and Category Transformation Agent calls, the one-refinement budget, malformed outputs, ambiguous dates, prompt injection, timeout and credential failures. Confirm manual mapping remains available.
- Configure dated prices and inspect actual ADK token metadata. Run the evaluator in a separate databridge_test database and save Vertex results separately; it resets data and incurs model charges.
- Repeat browser workflows against the deployed URL and concurrency/rollback checks in an isolated cloud test database.

## Cost and cleanup

Cloud SQL compute, storage and backups continue charging when Cloud Run scales to zero. Buckets, images, secrets, generation and embeddings can also incur charges. Consult current pricing and set billing budgets.

After backing up needed data, delete Cloud Run services/jobs, Artifact Registry images/repository, bucket objects and secrets. SQL deletion protection must deliberately be set false and applied before destroying the instance. The bucket refuses destruction while nonempty. Review and run Terraform destroy with the same state/variables only when authorized. Audit retained backups, images and objects afterward. Database deletion is permanent.
