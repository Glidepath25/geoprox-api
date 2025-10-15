# Deploying the GeoProx Mobile Backend on AWS App Runner

The FastAPI backend supports two modes of operation:

- `USE_GEOPROX_PROD=1` (default) talks to the production Aurora PostgreSQL cluster.
- `USE_GEOPROX_PROD=0` skips Aurora entirely and serves the bundled demo dataset (`demo.user / password123`).

Follow the steps below to package the backend into a container image, push it to ECR, and deploy it on App Runner.

## 1. Prerequisites

- AWS account with permission to use ECR and App Runner.
- AWS CLI v2 installed and configured (`aws configure`).
- Docker installed locally.
- Values for existing secrets (DB credentials, JWT secret, etc.).

## 2. Build and Push the Container Image

```powershell
# From the repository root
docker build -t geoprox-mobile-backend .

# Create the ECR repository (only once)
aws ecr create-repository --repository-name geoprox-mobile-backend

# Authenticate Docker to ECR
$ACCOUNT_ID = "<ACCOUNT_ID>"
$REGION = "<REGION>"
aws ecr get-login-password --region $REGION `
  | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

# Tag and push the image
docker tag geoprox-mobile-backend:latest "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/geoprox-mobile-backend:latest"
docker push "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/geoprox-mobile-backend:latest"
```

> Replace `<ACCOUNT_ID>` / `<REGION>` with your AWS account ID (e.g. `342597974606`) and region (e.g. `eu-west-1`).
>
> Repeat the build + push step every time backend code changes—App Runner always pulls the latest image from ECR.

## 3. Create or Update the App Runner Service

1. In **AWS Console → App Runner**, choose **Create service** (or **Deploy → Deploy latest image** if the service already exists).
2. Source: **Container registry** → Select the ECR repository above and the `latest` tag.
3. Runtime configuration: port `8000`; leave the start command blank (the Dockerfile runs `uvicorn backend.server:app`).
4. Environment variables: add the following keys (adjust values as required):
   - `MONGO_URL` – e.g. `mongodb://localhost:27017`
   - `DB_NAME` – e.g. `geoprox_mobile`
   - `SKIP_MONGO_INIT=1` – skip seeding when you keep data between runs
   - `JWT_SECRET` – must match the desktop/backend secret
   - `USE_GEOPROX_PROD=0` while Aurora is unreachable; flip to `1` when the production DB is healthy
5. Networking: attach the VPC connector/subnets/security groups that allow outbound TCP 5432 to Aurora when you re-enable production mode.
6. Deploy and wait for the deployment status to become **Succeeded**.

## 4. Smoke Test the Service

- Open `https://<service-id>.<region>.awsapprunner.com/` – you should see `{"status":"ok","service":"GeoProx Mobile API"}`.
- Call `/api/mobile/auth/login` with the demo credentials. With `USE_GEOPROX_PROD=0` the response includes `"mode": "local"` and returns immediately.
- When `USE_GEOPROX_PROD=1`, the same endpoint should log in against the production Aurora database.

## 5. Point the Expo App at App Runner

Set the frontend environment variable (through `.env`, `app.json`, or EAS secrets):

```bash
EXPO_PUBLIC_BACKEND_URL=https://<service-id>.<region>.awsapprunner.com
```

The OTA update `login-offline-guidance` already displays the correct messaging when the backend returns demo-mode responses.

## 6. (Optional) Build an Android binary with EAS

```powershell
cd frontend
npm install
npm install --global eas-cli
eas login
eas build --platform android --profile preview
```

Expo will output a download link once the build completes.

---

With the image pushed to ECR and App Runner redeployed, the mobile app can reach the backend without depending on a developer laptop. Flip `USE_GEOPROX_PROD` back to `1` once the Aurora database is accessible again.
