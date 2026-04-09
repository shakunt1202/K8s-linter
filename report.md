# K8s Environment Lint Report

| Field | Value |
|-------|-------|
| Generated | `2026-03-31T09:09:48Z` |
| Namespace | `widgetbot` |
| Profile | K8s Custom Hardening Profile |
| Source | cluster |
| **Score** | **27.5% [F]** |
| Passed | 6 |
| Failed | 13 |
| Warnings | 0 |

## Executive Summary

Executive Summary:

The Kubernetes environment audit report reveals a concerning health score of 27.5, resulting in an F grade. The majority of findings (13/19) fall under the "reliability" category, with critical failures identified in deployment configurations.

Notably, all containers lack essential security context settings (read-only root filesystem and runAsNonRoot), liveness and readiness probes are missing or null, and CPU and memory limits are not set. These findings indicate a high risk of security vulnerabilities and potential service disruptions.

To address these issues, we recommend prioritizing the remediation of deployment configurations to ensure all containers have valid security context settings, liveness and readiness probes are defined, and CPU and memory limits are properly configured.

## Networking  _(failures: 1)_

| Status | Rule | Severity | Resource | Detail |
|--------|------|----------|----------|--------|
| ❌ | Ingress TLS configured | `Severity.HIGH` | `Ingress/widget-ingress` | Required field 'spec.tls' is missing or null. |
| ✅ | No NodePort services | `Severity.HIGH` | `Service/businessnext-widgetbot` | Field 'spec.type' = ['ClusterIP'] — OK. |

### Remediations

#### `net-03` — Ingress TLS configured
**Resource:** `Ingress/widget-ingress`  
**Severity:** `Severity.HIGH`  

This matters because missing or incomplete TLS configuration on the ingress controller can leave your cluster vulnerable to man-in-the-middle attacks and eavesdropping.

To fix this, follow these steps:

1. **Create a cert-manager Certificate**: Run `kubectl apply -f https://raw.githubusercontent.com/jetstack/cert-manager/master/deploy/manifests/tls.yaml` to deploy cert-manager.
2. **Configure tls blocks on Ingress**: Update the ingress resource by adding a `spec.tls` block, for example: 
```yaml
apiVersion: networking.k8s.io/v1beta1
kind: Ingress
metadata:
  name: widget-ingress
spec:
  tls:
  - hosts:
    - widgetbot.com
    secretName: widgetbot-tls
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
```
3. (Optional) **Create a cert-manager Certificate**: Create a YAML file `widgetbot-tls.yaml` with the following content:
```yaml
apiVersion: certmanager.k8s.io/v1beta1
kind: Certificate
metadata:
  name: widgetbot-tls
spec:
  secretName: widgetbot-tls
  dnsNames:
  - widgetbot.com
```
Run `kubectl apply -f widgetbot-tls.yaml` to create the certificate.

## Rbac  _(failures: 0)_

| Status | Rule | Severity | Resource | Detail |
|--------|------|----------|----------|--------|
| ✅ | Default service account not used | `Severity.HIGH` | `Deployment/businessnext-widgetbot` | Field 'spec.template.spec.serviceAccountName' absent (bad value 'default' not pr |

## Reliability  _(failures: 3)_

| Status | Rule | Severity | Resource | Detail |
|--------|------|----------|----------|--------|
| ❌ | Liveness probe defined | `Severity.CRITICAL` | `Deployment/businessnext-widgetbot` | Required field 'spec.template.spec.containers[*].livenessProbe' is missing or nu |
| ❌ | Readiness probe defined | `Severity.CRITICAL` | `Deployment/businessnext-widgetbot` | Required field 'spec.template.spec.containers[*].readinessProbe' is missing or n |
| ❌ | Minimum replica count | `Severity.HIGH` | `Deployment/businessnext-widgetbot` | Field 'spec.replicas' = [0], required ≥ 2. |
| ✅ | Rolling update strategy | `Severity.HIGH` | `Deployment/businessnext-widgetbot` | Field 'spec.strategy.type' correctly set to 'RollingUpdate'. |

### Remediations

#### `rel-01` — Liveness probe defined
**Resource:** `Deployment/businessnext-widgetbot`  
**Severity:** `Severity.CRITICAL`  

This critical reliability issue must be addressed to ensure the Deployment's containers can detect and recover from failures, preventing cascading effects on the entire application.

To fix the issue:

1. Update the Deployment YAML file (`businessnext-widgetbot` in namespace `widgetbot`) by adding a `livenessProbe` configuration for each container:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: businessnext-widgetbot
spec:
  selector:
    matchLabels:
      app: businessnext-widgetbot
  template:
    metadata:
      labels:
        app: businessnext-widgetbot
    spec:
      containers:
      - name: businessnext-widgetbot
        image: <image-name>
        livenessProbe:
          httpGet:
            path: /
            port: 80
```
2. Apply the updated YAML file to the Deployment using `kubectl apply`:
```bash
kubectl apply -f businessnext-widgetbot.yaml
```
3. Verify that the liveness probe is configured correctly by checking the Deployment's status:
```bash
kubectl get deployment businessnext-widgetbot -o yaml
```
4. (Optional) Update the container's image to include a default liveness probe configuration, if desired.

By following these steps, you'll ensure the Deployment's containers can detect and recover from failures, preventing potential reliability issues.

#### `rel-02` — Readiness probe defined
**Resource:** `Deployment/businessnext-widgetbot`  
**Severity:** `Severity.CRITICAL`  

**Remediation Plan:** Define Readiness Probe Separately from Liveness

**Why this matters:** A missing or null readiness probe can lead to unpredictable application behavior and potential crashes, causing the deployment to fail.

**Steps to fix:**

1. **Update Deployment YAML**: Add a `spec.template.spec.containers[*].readinessProbe` field with the following configuration:
```yaml
spec:
  template:
    spec:
      containers:
        - name: businessnext-widgetbot
          readinessProbe:
            httpGet:
              path: /health/ready
              initialDelaySeconds: 30 # adjust to account for startup time
```
2. **Apply updated YAML**: Run `kubectl apply -f deployment.yaml` (assuming the updated YAML is in a file named `deployment.yaml`) to update the Deployment resource.
3. **Verify readiness probe configuration**: Run `kubectl get deployments -n widgetbot | grep businessnext-widgetbot` and check that the readiness probe is now defined.

**Note:** Ensure to adjust the `initialDelaySeconds` value according to your application's startup time.

#### `rel-03` — Minimum replica count
**Resource:** `Deployment/businessnext-widgetbot`  
**Severity:** `Severity.HIGH`  

This matters because a Deployment with zero replicas is not only unreliable but also vulnerable to being terminated by the scheduler, potentially leading to data loss or service unavailability.

To fix this issue:

1. Update the `spec.replicas` field in the `businessnext-widgetbot` Deployment YAML file to at least 2:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: businessnext-widgetbot
spec:
  replicas: 2 # Set minimum replicas to 2
  ...
```
 Run `kubectl apply -f businessnext-widgetbot-deployment.yaml` to update the deployment.

2. Create a PodDisruptionBudget (PDB) to ensure at least one pod remains available during scaling:
```yaml
apiVersion: policy/v1beta1
kind: PodDisruptionBudget
metadata:
  name: businessnext-widgetbot-pdb
spec:
  selector:
    matchLabels:
      app: businessnext-widgetbot
  minAvailable: 1 # Ensure at least one pod remains available
```
 Run `kubectl apply -f businessnext-widgetbot-pdb.yaml` to create the PDB.

3. Verify the updated deployment and PDB using `kubectl get deployments` and `kubectl get pod-disruption-budgets`.

## Resources  _(failures: 4)_

| Status | Rule | Severity | Resource | Detail |
|--------|------|----------|----------|--------|
| ❌ | CPU limits set | `Severity.CRITICAL` | `Deployment/businessnext-widgetbot` | Required field 'spec.template.spec.containers[*].resources.limits.cpu' is missin |
| ❌ | Memory limits set | `Severity.CRITICAL` | `Deployment/businessnext-widgetbot` | Required field 'spec.template.spec.containers[*].resources.limits.memory' is mis |
| ❌ | CPU requests set | `Severity.HIGH` | `Deployment/businessnext-widgetbot` | Required field 'spec.template.spec.containers[*].resources.requests.cpu' is miss |
| ❌ | Memory requests set | `Severity.HIGH` | `Deployment/businessnext-widgetbot` | Required field 'spec.template.spec.containers[*].resources.requests.memory' is m |

### Remediations

#### `res-01` — CPU limits set
**Resource:** `Deployment/businessnext-widgetbot`  
**Severity:** `Severity.CRITICAL`  

This matter is critical as missing CPU limits can lead to resource starvation and performance degradation in the Deployment.

To fix this issue, follow these steps:

1. **Update the Deployment YAML**: Open the `businessnext-widgetbot` Deployment YAML file and add the required `resources.limits.cpu` field for each container:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: businessnext-widgetbot
spec:
  template:
    spec:
      containers:
      - name: <container-name>
        resources:
          limits:
            cpu: 100m
```
2. **Apply the updated YAML**: Run `kubectl apply -f businessnext-widgetbot.yaml` to update the Deployment configuration.
3. (Optional) **Enable Vertical Pod Autoscaling (VPA)**: To right-size your Pods over time, enable VPA for the `businessnext-widgetbot` Deployment:
```bash
kubectl autoscale deployment/businessnext-widgetbot --min-pods=1 --max-pods=10 --cpu-percent=50
```
This will automatically adjust CPU resources based on pod utilization.

#### `res-02` — Memory limits set
**Resource:** `Deployment/businessnext-widgetbot`  
**Severity:** `Severity.CRITICAL`  

This rule matters because setting memory limits is crucial to prevent resource starvation and ensure the stability of the application.

To fix this issue, follow these steps:

1. Open the `businessnext-widgetbot` deployment YAML file in a text editor: `kubectl get deployment businessnext-widgetbot -o yaml`
2. Add or update the `resources.limits.memory` field with a value that is approximately 20% above the request size, e.g., `memory: 512Mi`. For example:
```yaml
spec:
  template:
    spec:
      containers:
      - name: businessnext-widgetbot
        resources:
          limits:
            memory: 512Mi
```
3. If your application uses a JVM workload, add the `-XX:MaxRAMPercentage` flag to match the container limit. For example:
```yaml
spec:
  template:
    spec:
      containers:
      - name: businessnext-widgetbot
        resources:
          limits:
            memory: 512Mi
        env:
        - name: JAVA_OPTS
          value: "-XX:MaxRAMPercentage=200"
```
4. Apply the updated deployment YAML file to your cluster using `kubectl apply`: `kubectl apply -f businessnext-widgetbot.yaml`

#### `res-03` — CPU requests set
**Resource:** `Deployment/businessnext-widgetbot`  
**Severity:** `Severity.HIGH`  

**Remediation Plan:** Update Deployment `businessnext-widgetbot` to set CPU requests.

**Why this matters:** Setting CPU requests ensures that the deployment's resources are allocated correctly, affecting scheduler placement decisions and potentially impacting application performance.

**Steps:**

1. **Update Deployment YAML**: Open the Deployment `businessnext-widgetbot` in your preferred editor and update its YAML file by adding the following snippet:
```yaml
spec:
  template:
    spec:
      containers:
        - resources:
            requests:
              cpu: 100m
```
Replace `100m` with the desired CPU request value.

2. **Apply updated Deployment**: Run the following command to apply the changes:
```bash
kubectl apply -f businessnext-widgetbot-deployment.yaml
```

3. (Optional) **Verify and check for limits**: Ensure that the requested CPU is less than or equal to the limit by running:
```bash
kubectl get deployment businessnext-widgetbot -o yaml | grep resources.requests.cpu
```
This will display the updated `resources.requests.cpu` field in the Deployment's YAML output.

#### `res-04` — Memory requests set
**Resource:** `Deployment/businessnext-widgetbot`  
**Severity:** `Severity.HIGH`  

This matter requires immediate attention to prevent pod eviction due to memory pressure, which can lead to application downtime.

To fix the issue:

1. Open the `businessnext-widgetbot` deployment YAML file in a text editor and add the following line under `spec.template.spec.containers[*].resources.requests.memory`: `100m` (set a conservative memory request with 20% headroom). For example:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: businessnext-widgetbot
spec:
  template:
    spec:
      containers:
      - name: businessnext-widgetbot
        resources:
          requests:
            memory: 100m
```
2. Apply the updated deployment YAML file using `kubectl apply -f businessnext-widgetbot-deployment.yaml` (assuming you saved the changes in a new file named `businessnext-widgetbot-deployment.yaml`).
3. Verify that the memory request has been successfully applied by running `kubectl get deployments businessnext-widgetbot -o yaml` and checking for the updated `resources.requests.memory` field.

## Security  _(failures: 5)_

| Status | Rule | Severity | Resource | Detail |
|--------|------|----------|----------|--------|
| ❌ | Read-only root filesystem | `Severity.CRITICAL` | `Deployment/businessnext-widgetbot` | Field 'spec.template.spec.containers[*].securityContext.readOnlyRootFilesystem'  |
| ❌ | No runAsRoot | `Severity.CRITICAL` | `Deployment/businessnext-widgetbot` | Field 'spec.template.spec.securityContext.runAsNonRoot' is absent (expected True |
| ❌ | Seccomp profile enforced | `Severity.HIGH` | `Deployment/businessnext-widgetbot` | Required field 'spec.template.spec.securityContext.seccompProfile' is missing or |
| ❌ | Capabilities dropped | `Severity.HIGH` | `Deployment/businessnext-widgetbot` | Field 'spec.template.spec.containers[*].securityContext.capabilities.drop' does  |
| ❌ | No automount of service account token | `Severity.MEDIUM` | `Deployment/businessnext-widgetbot` | Field 'spec.template.spec.automountServiceAccountToken' is absent (expected Fals |
| ✅ | No privileged containers | `Severity.CRITICAL` | `Deployment/businessnext-widgetbot` | Field 'spec.template.spec.containers[*].securityContext.privileged' absent (bad  |
| ✅ | Image tag is not latest | `Severity.HIGH` | `Deployment/businessnext-widgetbot` | No image tags with suffix ':latest'. |
| ✅ | No host namespace sharing | `Severity.HIGH` | `Deployment/businessnext-widgetbot` | No disallowed values in host namespace fields. |

### Remediations

#### `sec-02` — Read-only root filesystem
**Resource:** `Deployment/businessnext-widgetbot`  
**Severity:** `Severity.CRITICAL`  

**Remediation Plan for sec-02 Read-only root filesystem**

This matters because a non-read-only root filesystem can introduce security risks, allowing unauthorized access to sensitive data and potentially leading to container escape.

To fix this issue:

1. **Update the Deployment YAML**: Open the `businessnext-widgetbot` Deployment in your preferred editor and update the `spec.template.spec.containers[*].securityContext.readOnlyRootFilesystem` field to `true`. For example:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: businessnext-widgetbot
spec:
  template:
    spec:
      containers:
      - name: <container-name>
        image: <image-name>
        securityContext:
          readOnlyRootFilesystem: true
```
2. **Verify the update**: Run `kubectl get deployment businessnext-widgetbot -o yaml` to confirm the change.
3. (Optional) **Add emptyDir volumes for writable paths**: To ensure that even if a container's root filesystem is read-only, it can still write data to a specific directory, add an emptyDir volume to the container spec. For example:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: businessnext-widgetbot
spec:
  template:
    spec:
      containers:
      - name: <container-name>
        image: <image-name>
        securityContext:
          readOnlyRootFilesystem: true
        volumeMounts:
        - name: writable-data
          mountPath: /writable/data
      volumes:
      - name: writable-data
        emptyDir: {}
```
4. **Verify the emptyDir volume**: Run `kubectl get pod <pod-name> -o yaml` to confirm that the container has access to the writable directory.

By following these steps, you should be able to remediate the sec-02 Read-only root filesystem issue and ensure a more secure Deployment.

#### `sec-03` — No runAsRoot
**Resource:** `Deployment/businessnext-widgetbot`  
**Severity:** `Severity.CRITICAL`  

**Remediation Plan:** Fixing No runAsRoot in Deployment/businessnext-widgetbot

**Why this matters:** The `runAsNonRoot` field is crucial to prevent the deployment from running as root, reducing the attack surface and ensuring security.

**Steps to fix:**

1. **Update YAML file**: Open the `businessnext-widgetbot` deployment's YAML file (e.g., `/etc/kubernetes/deployments/businessnext-widgetbot.yaml`) in a text editor and add the following configuration:
```yaml
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        allowPrivilegeEscalation: false
```
2. **Apply changes**: Run `kubectl apply -f /etc/kubernetes/deployments/businessnext-widgetbot.yaml` to update the deployment configuration.
3. (Optional) **Verify with kubectl**: Run `kubectl get deployments businessnext-widgetbot -o yaml` to confirm the updated configuration.

By following these steps, you should resolve the `sec-03: No runAsRoot` finding and improve the security posture of your deployment.

#### `sec-04` — Seccomp profile enforced
**Resource:** `Deployment/businessnext-widgetbot`  
**Severity:** `Severity.HIGH`  

This rule matters because a missing or null seccomp profile can leave the container vulnerable to malicious actions.

To fix this issue, follow these steps:

1. Update the Deployment's YAML file (`businessnext-widgetbot`) by adding `spec.template.spec.securityContext.seccompProfile` with a valid value:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: businessnext-widgetbot
spec:
  ...
  template:
    spec:
      securityContext:
        seccompProfile:
          type: RuntimeDefault
```
2. Verify the updated seccomp profile using `kubectl`:
```bash
kubectl get pod <n> -o jsonpath='{.spec.securityContext.seccompProfile}'
```
3. Apply the changes to the Deployment:
```bash
kubectl apply -f businessnext-widgetbot.yaml
```
4. (Optional) Verify that the seccomp profile is enforced by running a container with malicious actions and observing its behavior:
```bash
kubectl exec -it <n> -- /bin/bash -c 'echo "Hello World!"'
```
Note: Replace `<n>` with the actual pod name.

#### `sec-06` — Capabilities dropped
**Resource:** `Deployment/businessnext-widgetbot`  
**Severity:** `Severity.HIGH`  

This matter requires immediate attention to prevent potential security vulnerabilities in the `businessnext-widgetbot` Deployment.

To fix the issue:

1. Open the YAML file of the `businessnext-widgetbot` Deployment: `kubectl get deployment businessnext-widgetbot -o yaml`
2. Update the `spec.template.spec.containers[*].securityContext.capabilities.drop` field to include only required values, e.g., `NET_BIND_SERVICE`: 
```yaml
spec:
  template:
    spec:
      containers:
      - securityContext:
        capabilities:
          drop: ["ALL", "NET_BIND_SERVICE"]
```
3. Apply the updated YAML file to the Deployment: `kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: businessnext-widgetbot
spec:
  template:
    spec:
      containers:
      - securityContext:
        capabilities:
          drop: ["ALL", "NET_BIND_SERVICE"]
EOF`
4. Verify the updated configuration with `kubectl get deployment businessnext-widgetbot -o yaml`

#### `sec-08` — No automount of service account token
**Resource:** `Deployment/businessnext-widgetbot`  
**Severity:** `Severity.MEDIUM`  

This rule matters because automounting service account tokens can introduce security risks, such as unauthorized access to cluster resources.

To fix this issue:

1. Open the Deployment YAML file (`businessnext-widgetbot`) in your preferred editor and navigate to the `spec.template.spec` section.
2. Update the `automountServiceAccountToken` field to `false`, like so:
```yaml
spec:
  template:
    spec:
      automountServiceAccountToken: false
```
Alternatively, you can update the ServiceAccount YAML file (`businessnext-widgetbot-serviceaccount`) by setting its `automountServiceAccountToken` field to `false`. For example:
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: businessnext-widgetbot
spec:
  automountServiceAccountToken: false
```
3. Verify the change by running `kubectl get deployments -n widgetbot` and checking that the `automountServiceAccountToken` field is now set to `false`.
