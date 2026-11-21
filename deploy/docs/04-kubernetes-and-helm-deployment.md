# 04. Kubernetes & Helm v3 Deployment Guide (`deploy/k8s` & `deploy/helm`)

This guide provides step-by-step instructions for deploying **`py-phone-caller`** and **`openalertd`** onto any Kubernetes cluster (`GKE`, `EKS`, `AKS`, `k3s`, `OpenShift`, or `kubeadm`) using either:
- **Option A: The Production Helm v3 Chart** (`deploy/helm/py-phone-caller` or `dist/k8s/py-phone-caller-1.0.0.tgz`) — *Recommended for parameterized installations and upgrades*.
- **Option B: Raw Kustomize / Kubernetes Manifests** (`deploy/k8s/` or `dist/k8s/py-phone-caller-k8s-manifests-v1.0.0.tar.gz`) — *Recommended for GitOps (`ArgoCD` / `Flux`) or declarative manifest inspection*.

> [!NOTE]
> **Live Kubernetes Qualification (`k3s` & Google Kubernetes Engine `GKE`)**
> Certified end-to-end on both:
> - **Google Kubernetes Engine (`GKE v1.36.4-gke.2377000`)**: 2-node cluster (`Container-Optimized OS`, `containerd://2.2.7`, `standard-rwo` CSI Persistent Disks, and Google Artifact Registry) — certified both **Option A (Helm v3, 17/17 Deployments `1/1 Running`)** and **Option B (Kustomize `kubectl apply -k deploy/k8s/`, 18/18 Deployments `1/1 Running`)**, all 3 PVCs `Bound`, and all in-cluster HTTP & cross-VPC Asterisk 22 ARI (`:8088`) endpoints returning `200 OK`.
> - **Single-Node `k3s` (`v1.34.6+k3s1` / `v1.37.2+k3s1`) on Debian 13 AMD64**: Certified with local `containerd` image import and `helm v3`.

---

## Step 1: Prepare Container Images for Your Cluster

By default, the Helm chart and raw manifests reference:
- **Helm Chart (`values.yaml`)**: `global.imageRegistry: "quay.io/py-phone-caller"` and `global.imageTag: "1.0.0"`
- **Raw Manifests (`deploy/k8s/*.yml`)**: `quay.io/py-phone-caller/<service>:1.0.0`

### If Using a Private Container Registry (e.g. Google Artifact Registry, ECR, ACR, Harbor)
Build and push all 12 images using `./src/build_all_images.sh`:

```bash
CONTAINER_ENGINE=docker \
IMAGE_REGISTRY=registry.example.com/py-phone-caller \
IMAGE_TAG=1.0.0 \
./src/build_all_images.sh

for svc in asterisk_caller asterisk_recaller asterisk_ws_monitor caller_prometheus_webhook \
           caller_register caller_scheduler caller_sms generate_audio caller_address_book \
           py_phone_caller_ui celery_worker openalertd; do
  docker push "registry.example.com/py-phone-caller/${svc}:1.0.0"
done
```

### If Using a Single-Node `k3s` Cluster (Air-Gapped / Local Import)
If you built the images locally on your `k3s` node with `IMAGE_REGISTRY=quay.io/py-phone-caller IMAGE_TAG=1.0.0`, import them directly into `k3s` `containerd` without needing an external registry:

```bash
for svc in asterisk_caller asterisk_recaller asterisk_ws_monitor caller_prometheus_webhook \
           caller_register caller_scheduler caller_sms generate_audio caller_address_book \
           py_phone_caller_ui celery_worker openalertd; do
  docker save "quay.io/py-phone-caller/${svc}:1.0.0" | sudo k3s ctr images import -
done
```

> [!IMPORTANT]
> **Cloud VPC Firewall Note for GKE / EKS / AKS External Asterisk PBX (`:8088`)**
> When Kubernetes pods connect to your external Asterisk PBX via `asterisk-service:8088` (`Endpoints/asterisk-service`), packets originate from the cluster's **Pod CIDR** (for example, GKE's secondary IP range `clusterIpv4Cidr`, such as `10.80.0.0/14`). On Google Cloud (`GKE`), the default `default-allow-internal` VPC firewall rule only covers primary VM subnet ranges (`10.128.0.0/9`), **not** the GKE secondary Pod CIDR. Ensure your VPC firewall allows ingress to `tcp:8088` on your Asterisk PBX host from the cluster's Pod CIDR:
> ```bash
> POD_CIDR=$(gcloud container clusters describe <CLUSTER_NAME> --zone=<ZONE> --format="value(clusterIpv4Cidr)")
> gcloud compute firewall-rules create allow-gke-pods-to-asterisk \
>   --network=default --allow=tcp:8088 --source-ranges="${POD_CIDR}"
> ```

---

## Step 2: Deploy via Option A — Helm v3 Chart (Recommended)

The Helm chart lives in `deploy/helm/py-phone-caller/` and is also packaged as `dist/k8s/py-phone-caller-1.0.0.tgz`.

### 1. Create a Custom `my-values.yaml` (or use `--set`)

Create a `my-values.yaml` file (keep it outside Git if it contains credentials, or reference an `existingSecret`):

```yaml
global:
  imageRegistry: "quay.io/py-phone-caller"
  imageTag: "1.0.0"
  imagePullPolicy: IfNotPresent
  timezone: "Europe/Rome"

# Point to your external Asterisk PBX ARI host
asterisk:
  externalIp: "192.0.2.10"
  webPort: 8088
  user: "py-phone-caller"
  context: "py-phone-caller"
  extension: "3216"
  chanType: "PJSIP/sip-provider"
  callerId: "Py-Phone-Caller"
  stasisApp: "py-phone-caller"

# Credentials injected into .secrets.toml
secrets:
  asteriskPass: "YOUR_ASTERISK_ARI_PASSWORD"
  dbPassword: "YOUR_POSTGRES_PASSWORD"
  twilioAccountSid: ""
  twilioAuthToken: ""
  uiSecretKey: "YOUR_32_CHAR_RANDOM_SESSION_SECRET"
  uiAdminPassword: "YOUR_UI_ADMIN_PASSWORD"
  keycloakAdminPassword: "YOUR_KEYCLOAK_ADMIN_PASSWORD"

# TTS & UI settings
tts:
  engine: "piper_tts"      # or kokoro_tts / silero_tts
  languageCode: "en"
  storage: "5Gi"

ui:
  adminUser: "admin@py-phone-caller.link"
  resetPassword: true      # Set true on initial install to bootstrap admin user

# Optional Enterprise Gateway (APISIX + etcd + Keycloak OIDC)
gateway:
  enabled: false

# Optional Kubernetes Ingress
ingress:
  enabled: false
  className: "nginx"
  uiHost: "alerts.example.internal"
```

### 2. Lint and Install the Helm Release

```bash
# Lint the chart first
helm lint deploy/helm/py-phone-caller -f my-values.yaml

# Install (or upgrade) from the directory or from dist/k8s/py-phone-caller-1.0.0.tgz
helm upgrade --install py-phone-caller deploy/helm/py-phone-caller \
  --namespace py-phone-caller --create-namespace \
  -f my-values.yaml
```

> [!TIP]
> **Minimal One-Line Helm Install**
> You can also install directly from the packaged archive using `--set` flags:
> ```bash
> helm upgrade --install py-phone-caller dist/k8s/py-phone-caller-1.0.0.tgz \
>   --namespace py-phone-caller --create-namespace \
>   --set asterisk.externalIp="192.0.2.10" \
>   --set secrets.asteriskPass="your-ari-secret" \
>   --set secrets.dbPassword="your-postgres-secret" \
>   --set secrets.uiSecretKey="your-session-secret-key-1234567890" \
>   --set secrets.uiAdminPassword="your-admin-password"
> ```

---

## Step 3: Deploy via Option B — Raw Kubernetes / Kustomize Manifests (`deploy/k8s`)

If you prefer raw YAML manifests over Helm, `deploy/k8s/` contains all 20 manifest files orchestrated by `deploy/k8s/kustomization.yaml`.

### Manifest Inventory

| Manifest File | Kubernetes Objects | Purpose |
| :--- | :--- | :--- |
| `00_py_phone_caller_namespace.yml` | `Namespace` (`py-phone-caller`) | Isolates all resources |
| `01_asterisk_endpoint.yml` | `Service` + `Endpoints` (`asterisk-service`) | Bridges cluster traffic to your external Asterisk PBX IP (`:8088`) |
| `02_ingress.yml` | `Ingress` | Exposes HTTP/HTTPS routes through your cluster Ingress controller |
| `03_postgresql.yml` | `PVC`, `Deployment`, `Service` (`postgresql-service:5432`) | PostgreSQL 17 database (`PGDATA=/var/lib/postgresql/data/pgdata` for cloud `ext4` CSI volumes) |
| `03_redis.yml` | `Deployment`, `Service` (`redis-service:6379`) | Redis 7 message broker |
| `04_caller_config.yml` | `ConfigMap` (`py-phone-caller-config`) | Mounts `/app/py-phone-caller/config/settings.toml` (zero plaintext secrets) |
| `04_caller_secrets.yml` | `Secret` (`py-phone-caller-secrets`) | Mounts `/app/py-phone-caller/config/.secrets.toml` and environment credentials |
| `05` – `15_*.yml` | `Deployment` + `Service` (11 microservices) | All 11 Python services + `audio-pvc` |
| `16_haproxy.yml` | `ConfigMap`, `Deployment`, `Service` (`haproxy-service:8080`) | Internal HAProxy aggregator |
| `17_openalertd.yml` | `PVC`, `Deployment`, `Service` (`openalertd-service`) | OpenAlert daemon (`:8090`, `:8088`, `:19876/udp`) with `OPENALERT_TEMPLATES__TEMPLATE_DIR=/templates` and `fsGroup: 10001` |
| `18_gateway_apisix_keycloak.yml` | `ConfigMap`, `Deployment`, `Service` (`apisix`, `etcd`, `keycloak`) | Enterprise APISIX + Keycloak OIDC gateway (`apisix-config` pointing to `apisix-etcd-service:2379`) |

### 1. Edit Asterisk IP, Secrets & Registry Prefix Before Applying

1. Edit `deploy/k8s/01_asterisk_endpoint.yml` and replace `192.168.1.200` with your Asterisk PBX IP (note that Kubernetes `Endpoints` reject loopback `127.0.0.0/8` addresses).
2. Edit `deploy/k8s/04_caller_secrets.yml` and replace `CHANGE_ME_*` / `use-a-secure-password` placeholders with your real Asterisk ARI, PostgreSQL, and UI passwords.
3. If you pushed images to a custom registry (e.g. Google Artifact Registry `europe-west4-docker.pkg.dev/my-project/py-phone-caller`), update the image registry prefix across `deploy/k8s/*.yml`:
   ```bash
   sed -i 's|quay.io/py-phone-caller/|registry.example.com/py-phone-caller/|g' deploy/k8s/*.yml
   ```

### 2. Server-Side Dry-Run & Apply via Kustomize

```bash
# 1. Ensure the target namespace exists, then validate against your Kubernetes API server
kubectl apply -f deploy/k8s/00_py_phone_caller_namespace.yml
kubectl apply -k deploy/k8s/ --dry-run=server

# 2. Apply the stack
kubectl apply -k deploy/k8s/
```

---

## Step 4: Verify Rollout, Persistent Volumes & In-Cluster Health

1. **Wait for All Deployments to Become Ready**:
   ```bash
   kubectl rollout status deployment -n py-phone-caller --timeout=300s
   kubectl get pods,pvc,svc -n py-phone-caller
   ```
   All Deployments should show `1/1 Running` and all 3 PVCs (`postgresql`, `openalertd`, and `generate-audio`) should show `Bound`.

2. **Verify All Microservice Health Endpoints Inside the Cluster**:
   ```bash
   kubectl exec -n py-phone-caller deployment/py-phone-caller-ui-deployment -- python3 -c '
   import urllib.request
   for url in [
       "http://caller-register-service:8083/health",
       "http://caller-address-book-service:8087/health",
       "http://caller-scheduler-service:8086/health",
       "http://caller-sms-service:8085/health",
       "http://asterisk-caller-service:8081/health",
       "http://generate-audio-service:8082/health",
       "http://caller-prometheus-webhook-service:8084/health",
       "http://py-phone-caller-ui-service:5000/health",
       "http://openalertd-service:8090/api/v1/status",
   ]:
       with urllib.request.urlopen(url, timeout=10) as r:
           print(url, "->", r.status, r.read().decode("utf-8")[:100])
   '
   ```

3. **Access the Web UI Locally via Port-Forward**:
   ```bash
   kubectl port-forward -n py-phone-caller svc/py-phone-caller-ui-service 5000:5000
   ```
   Then open `http://127.0.0.1:5000/login` in your browser.
