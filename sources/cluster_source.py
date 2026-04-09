"""
Cluster source — fetches resources from a live Kubernetes cluster via kubectl.
Falls back gracefully when kubectl is not available (returns mock data for testing).
"""

from __future__ import annotations

import json
import subprocess
import logging
from typing import Any, Dict, List

from models import ResourceContext

logger = logging.getLogger(__name__)

RESOURCE_KINDS = [
    "deployments",
    "statefulsets",
    "daemonsets",
    "services",
    "ingresses",
    "networkpolicies",
    "serviceaccounts",
    "pods",
]


class ClusterSource:
    def __init__(self, namespace: str = "default"):
        self.namespace = namespace
        self._kubectl_available = self._check_kubectl()

    def _check_kubectl(self) -> bool:
        try:
            result = subprocess.run(
                ["kubectl", "version", "--client", "--output=json"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _run_kubectl(self, *args: str) -> Dict[str, Any] | None:
        cmd = ["kubectl", *args, "--output=json"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            logger.warning("kubectl error: %s", e)
        return None

    def fetch(self) -> List[ResourceContext]:
        if not self._kubectl_available:
            logger.warning("kubectl not found — using mock cluster data for demo.")
            return self._mock_resources()

        resources = []
        for kind in RESOURCE_KINDS:
            data = self._run_kubectl("get", kind, "-n", self.namespace)
            if not data:
                continue
            for item in data.get("items", []):
                resources.append(ResourceContext(
                    kind=item.get("kind", kind.rstrip("s").capitalize()),
                    name=item["metadata"]["name"],
                    namespace=item["metadata"].get("namespace", self.namespace),
                    source="cluster",
                    raw=item,
                ))
        return resources

    def _mock_resources(self) -> List[ResourceContext]:
        """Return realistic mock resources that trigger various lint failures."""
        return [
            ResourceContext(
                kind="Deployment", name="api-server", namespace=self.namespace,
                source="cluster",
                raw={
                    "kind": "Deployment",
                    "metadata": {"name": "api-server", "namespace": self.namespace},
                    "spec": {
                        "replicas": 1,
                        "strategy": {"type": "RollingUpdate"},
                        "template": {
                            "spec": {
                                "serviceAccountName": "default",
                                "automountServiceAccountToken": True,
                                "containers": [{
                                    "name": "api",
                                    "image": "myrepo/api:latest",
                                    "securityContext": {
                                        "privileged": False,
                                        "readOnlyRootFilesystem": False,
                                        "allowPrivilegeEscalation": True,
                                    },
                                    "resources": {
                                        "requests": {"cpu": "100m"},
                                        # missing memory request, missing limits
                                    },
                                    # missing liveness + readiness probes
                                }]
                            }
                        }
                    }
                }
            ),
            ResourceContext(
                kind="Deployment", name="worker", namespace=self.namespace,
                source="cluster",
                raw={
                    "kind": "Deployment",
                    "metadata": {"name": "worker", "namespace": self.namespace},
                    "spec": {
                        "replicas": 3,
                        "strategy": {"type": "RollingUpdate"},
                        "template": {
                            "spec": {
                                "serviceAccountName": "worker-sa",
                                "automountServiceAccountToken": False,
                                "securityContext": {
                                    "runAsNonRoot": True,
                                    "runAsUser": 1000,
                                    "seccompProfile": {"type": "RuntimeDefault"},
                                },
                                "containers": [{
                                    "name": "worker",
                                    "image": "myrepo/worker:v2.1.3",
                                    "securityContext": {
                                        "readOnlyRootFilesystem": True,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                    "resources": {
                                        "requests": {"cpu": "250m", "memory": "256Mi"},
                                        "limits":   {"cpu": "500m", "memory": "512Mi"},
                                    },
                                    "livenessProbe": {"httpGet": {"path": "/health", "port": 8080}},
                                    "readinessProbe": {"httpGet": {"path": "/ready", "port": 8080}},
                                }]
                            }
                        }
                    }
                }
            ),
            ResourceContext(
                kind="Service", name="api-nodeport", namespace=self.namespace,
                source="cluster",
                raw={
                    "kind": "Service",
                    "metadata": {"name": "api-nodeport", "namespace": self.namespace},
                    "spec": {"type": "NodePort", "ports": [{"port": 80, "nodePort": 30080}]},
                }
            ),
            ResourceContext(
                kind="Ingress", name="api-ingress", namespace=self.namespace,
                source="cluster",
                raw={
                    "kind": "Ingress",
                    "metadata": {"name": "api-ingress", "namespace": self.namespace},
                    "spec": {
                        "rules": [{"host": "api.example.com"}],
                        # missing tls block
                    }
                }
            ),
        ]
