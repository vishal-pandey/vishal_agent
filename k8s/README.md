# Kubernetes Manifests

Kubernetes deployment files for Vishal's AI Agent with auto-updating RAG.

## Files

- **deployment.yaml** - Main app deployment with init container for auto-ingestion
- **postgres.yaml** - PostgreSQL StatefulSet with pgvector
- **argocd-app.yaml** - ArgoCD Application definition
- **kustomization.yaml** - Kustomize configuration
- **reingest-job.yaml** - Manual re-ingestion job

## Quick Deploy

```bash
# Deploy everything
kubectl apply -k .

# Or with ArgoCD
kubectl apply -f argocd-app.yaml
```

## Configuration Required

1. **Update OLLAMA_API_BASE** in `kustomization.yaml` with your M1 Mac IP
2. **Update knowledge base** files in the ConfigMap
3. **(Optional)** Use sealed-secrets for production secrets

See [KUBERNETES_DEPLOYMENT.md](../docs/KUBERNETES_DEPLOYMENT.md) for full guide.
