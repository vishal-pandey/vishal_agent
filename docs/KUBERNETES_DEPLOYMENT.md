# Kubernetes Deployment with ArgoCD + Auto-Ingestion

This guide explains how to deploy Vishal's AI Agent on Kubernetes with automatic embedding updates.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │  ArgoCD watches Git repo                         │  │
│  │  → Detects changes in knowledge_base/           │  │
│  │  → Triggers deployment                           │  │
│  └──────────────────────────────────────────────────┘  │
│                         ↓                               │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Init Container (runs before main app)          │  │
│  │  → Reads knowledge_base ConfigMap               │  │
│  │  → Connects to PostgreSQL                       │  │
│  │  → Ingests documents into pgvector              │  │
│  │  → Generates embeddings (CPU)                   │  │
│  └──────────────────────────────────────────────────┘  │
│                         ↓                               │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Main App Pods (2+ replicas)                    │  │
│  │  → Connects to external Ollama (M1 Mac)        │  │
│  │  → Uses pgvector for RAG                       │  │
│  │  → Serves API requests                         │  │
│  └──────────────────────────────────────────────────┘  │
│                         ↓                               │
│  ┌──────────────────────────────────────────────────┐  │
│  │  PostgreSQL StatefulSet (pgvector)              │  │
│  │  → Stores sessions + embeddings                 │  │
│  │  → Persistent volume                            │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         ↓
              ┌───────────────────────┐
              │  External M1 MacBook  │
              │  → Ollama + Llama 3.2 │
              │  → Exposed on network │
              └───────────────────────┘
```

## Quick Start

### 1. Update Configuration

**Edit k8s/kustomization.yaml:**
```yaml
secretGenerator:
  - name: vishal-agent-secrets
    literals:
      - DATABASE_URL=postgresql+asyncpg://vishal_agent:vishal_agent_secret@postgres-service:5432/vishal_agent_sessions
      - OLLAMA_API_BASE=http://192.168.1.100:11434  # ← Your M1 Mac IP
```

**On your M1 Mac (Ollama host):**
```bash
# Make Ollama accessible from k8s cluster
export OLLAMA_HOST=0.0.0.0:11434
ollama serve

# Or update ~/.ollama/ollama.service to bind to 0.0.0.0
```

### 2. Deploy to Kubernetes

**Option A: Using kubectl directly**
```bash
# Apply all manifests
kubectl apply -k k8s/

# Watch deployment
kubectl get pods -w
```

**Option B: Using ArgoCD**
```bash
# Create ArgoCD application
kubectl apply -f k8s/argocd-app.yaml

# Watch in ArgoCD UI
argocd app get vishal-agent
argocd app sync vishal-agent
```

### 3. Verify Deployment

```bash
# Check init container logs (document ingestion)
kubectl logs -l app=vishal-agent -c ingest-documents

# Check main app logs
kubectl logs -l app=vishal-agent -c vishal-agent

# Check PostgreSQL
kubectl exec -it postgres-0 -- psql -U vishal_agent -d vishal_agent_sessions -c "SELECT COUNT(*) FROM documents;"
```

### 4. Test the API

```bash
# Port forward to access locally
kubectl port-forward svc/vishal-agent-service 8000:80

# Test query
curl -X POST "http://localhost:8000/run" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test",
    "new_message": {
      "role": "user",
      "parts": [{"text": "What are Vishal's recent interests?"}]
    }
  }'
```

## How Auto-Update Works

### Workflow

1. **You update documents:**
   ```bash
   # Add new file to knowledge_base/
   echo "New content" > knowledge_base/new_doc.txt
   git add knowledge_base/
   git commit -m "Add new documentation"
   git push
   ```

2. **ArgoCD detects change:**
   - Monitors your Git repo
   - Sees `knowledge_base/` changed
   - ConfigMap hash changes
   - Triggers deployment

3. **Kubernetes redeploys:**
   - Pulls new image
   - **Init container runs FIRST:**
     - Reads updated ConfigMap
     - Clears old embeddings (INGEST_MODE=replace)
     - Generates new embeddings
     - Stores in pgvector
   - Main app starts only AFTER init succeeds
   - Uses fresh embeddings

4. **Users get updated knowledge:**
   - No downtime (rolling update)
   - Instant access to new docs
   - Old pods drain gracefully

### ConfigMap Strategy

**knowledge_base as ConfigMap:**
```yaml
configMapGenerator:
  - name: vishal-agent-knowledge-base
    files:
      - ../knowledge_base/example.txt
      - ../knowledge_base/tech.txt
      - ../knowledge_base/projects.txt
    options:
      disableNameSuffixHash: false  # Creates new ConfigMap on change
```

**Benefits:**
- GitOps: Documents version-controlled
- Automatic: No manual intervention
- Atomic: All or nothing updates
- Auditable: Git history tracks changes

## Deployment Modes

### Replace Mode (Default - Recommended)
```yaml
env:
  - name: INGEST_MODE
    value: "replace"
```
- Clears all old documents
- Ingests fresh from ConfigMap
- Ensures no stale data
- Best for most use cases

### Append Mode
```yaml
env:
  - name: INGEST_MODE
    value: "append"
```
- Keeps existing documents
- Adds new ones
- Useful for incremental updates
- Risk of duplicates

## Manual Re-ingestion

If you need to re-ingest without redeploying:

```bash
# Run one-off job
kubectl apply -f k8s/reingest-job.yaml

# Watch progress
kubectl logs -f job/vishal-agent-reingest

# Clean up
kubectl delete job vishal-agent-reingest
```

## Production Considerations

### 1. Secrets Management

**Don't hardcode secrets!** Use Sealed Secrets or External Secrets:

```bash
# Example with sealed-secrets
kubectl create secret generic vishal-agent-secrets \
  --from-literal=DATABASE_URL='postgresql+asyncpg://...' \
  --from-literal=OLLAMA_API_BASE='http://...' \
  --dry-run=client -o yaml | \
  kubeseal -o yaml > sealed-secret.yaml
```

### 2. Network Policy (M1 Mac Access)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ollama-access
spec:
  podSelector:
    matchLabels:
      app: vishal-agent
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 192.168.1.100/32  # Your M1 Mac IP
    ports:
    - protocol: TCP
      port: 11434
```

### 3. Resource Limits

**Init container needs more resources for embedding generation:**
```yaml
initContainers:
  resources:
    requests:
      cpu: "500m"     # More CPU for embeddings
      memory: "512Mi"
    limits:
      cpu: "1000m"
      memory: "1Gi"
```

**Main app can be lighter:**
```yaml
containers:
  resources:
    requests:
      cpu: "250m"     # Less CPU for API serving
      memory: "512Mi"
```

### 4. Persistent Storage

PostgreSQL uses StatefulSet with PVC:
```yaml
volumeClaimTemplates:
  - metadata:
      name: postgres-storage
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: fast-ssd  # ← Use your storage class
      resources:
        requests:
          storage: 10Gi
```

### 5. Horizontal Scaling

```bash
# Scale app pods
kubectl scale deployment vishal-agent --replicas=4

# PostgreSQL sessions in DB = works with multiple pods ✅
# Embeddings in pgvector = shared across all pods ✅
```

## Monitoring

### Key Metrics to Watch

```bash
# Init container success rate
kubectl get pods -l app=vishal-agent -o jsonpath='{.items[*].status.initContainerStatuses[0].state.terminated.exitCode}'

# Document count in DB
kubectl exec -it postgres-0 -- psql -U vishal_agent -d vishal_agent_sessions -c \
  "SELECT COUNT(*) as total_docs, COUNT(DISTINCT metadata->>'source') as unique_files FROM documents;"

# Pod resource usage
kubectl top pods -l app=vishal-agent
```

### Logging

```bash
# All logs
kubectl logs -l app=vishal-agent --all-containers --prefix

# Just ingestion
kubectl logs -l app=vishal-agent -c ingest-documents --previous

# Follow main app
kubectl logs -l app=vishal-agent -c vishal-agent -f
```

## Troubleshooting

### Init Container Fails

```bash
# Check logs
kubectl logs <pod-name> -c ingest-documents

# Common issues:
# 1. DATABASE_URL wrong → Check secret
# 2. ConfigMap not mounted → Check volume mount
# 3. Embedding model download slow → Increase timeout
# 4. Out of memory → Increase init container memory
```

### Ollama Connection Issues

```bash
# Test from pod
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl http://YOUR_M1_IP:11434/api/tags

# Check network policy
kubectl describe networkpolicy allow-ollama-access

# Verify Ollama is accessible
# On M1 Mac:
curl http://0.0.0.0:11434/api/tags
```

### Documents Not Updating

```bash
# Check ConfigMap hash changed
kubectl get configmap -l app.kubernetes.io/name=vishal-agent -o yaml

# Force rollout
kubectl rollout restart deployment vishal-agent

# Check init container ran
kubectl describe pod <pod-name> | grep -A 10 "Init Containers"
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Update Knowledge Base
on:
  push:
    paths:
      - 'knowledge_base/**'

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Trigger ArgoCD Sync
        run: |
          argocd app sync vishal-agent --force
```

## Migration from Docker Compose

```bash
# 1. Export existing data from docker-compose
docker exec postgres-sessions pg_dump -U vishal_agent vishal_agent_sessions > backup.sql

# 2. Deploy to k8s
kubectl apply -k k8s/

# 3. Import data (if needed)
kubectl exec -i postgres-0 -- psql -U vishal_agent vishal_agent_sessions < backup.sql
```

## Next Steps

1. ✅ Update `OLLAMA_API_BASE` with your M1 Mac IP
2. ✅ Add your documents to `knowledge_base/`
3. ✅ Commit and push to Git
4. ✅ Apply ArgoCD application: `kubectl apply -f k8s/argocd-app.yaml`
5. ✅ Watch deployment: `argocd app get vishal-agent`
6. ✅ Test the API

---

**Questions?** Check the main [RAG_SETUP.md](RAG_SETUP.md) guide or open an issue!
