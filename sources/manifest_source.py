"""
Manifest source — loads Kubernetes YAML/JSON manifests from a local directory.
Handles multi-document YAML files and basic Helm rendered output.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import yaml

from models import ResourceContext

logger = logging.getLogger(__name__)

SUPPORTED_KINDS = {
    "Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob",
    "Service", "Ingress", "NetworkPolicy", "ServiceAccount",
    "Pod", "ReplicaSet",
}


class ManifestSource:
    def __init__(self, path: str):
        self.root = Path(path)

    def fetch(self) -> List[ResourceContext]:
        if not self.root.exists():
            logger.warning("Manifest path %s does not exist — using built-in samples.", self.root)
            return self._sample_manifests()

        resources: List[ResourceContext] = []
        patterns = ["**/*.yaml", "**/*.yml", "**/*.json"]
        files = []
        for pat in patterns:
            files.extend(self.root.glob(pat))

        for fpath in sorted(set(files)):
            resources.extend(self._load_file(fpath))

        if not resources:
            logger.warning("No manifests found in %s — using built-in samples.", self.root)
            return self._sample_manifests()

        return resources

    def _load_file(self, fpath: Path) -> List[ResourceContext]:
        results = []
        try:
            with open(fpath) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                kind = doc.get("kind", "")
                if kind not in SUPPORTED_KINDS:
                    continue
                name = doc.get("metadata", {}).get("name", "unknown")
                ns   = doc.get("metadata", {}).get("namespace", "default")
                results.append(ResourceContext(
                    kind=kind, name=name, namespace=ns,
                    source="manifest", raw=doc,
                ))
        except Exception as e:
            logger.warning("Failed to parse %s: %s", fpath, e)
        return results

    def _sample_manifests(self) -> List[ResourceContext]:
        """Built-in sample manifests that exercise a variety of checks."""
        raw_deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "frontend", "namespace": "default"},
            "spec": {
                "replicas": 1,
                "strategy": {"type": "Recreate"},   # wrong strategy
                "template": {
                    "spec": {
                        "serviceAccountName": "default",   # bad: using default SA
                        "hostNetwork": True,               # bad: host network
                        "containers": [{
                            "name": "frontend",
                            "image": "nginx:latest",       # bad: latest tag
                            "securityContext": {
                                "privileged": True,        # bad: privileged
                                "readOnlyRootFilesystem": False,
                            },
                            "resources": {},               # bad: no resources at all
                        }]
                    }
                }
            }
        }

        raw_service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "frontend-svc", "namespace": "default"},
            "spec": {"type": "NodePort", "ports": [{"port": 80, "nodePort": 30000}]},
        }

        return [
            ResourceContext(kind="Deployment", name="frontend", namespace="default",
                            source="manifest", raw=raw_deployment),
            ResourceContext(kind="Service", name="frontend-svc", namespace="default",
                            source="manifest", raw=raw_service),
        ]
