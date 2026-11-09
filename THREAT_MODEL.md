# Threat model

Status: initial version, written before the runner exists. Mitigations below are the planned design; each one is tracked in the roadmap and will be backed by an attack test before it is marked as done.

## What is being protected

| Asset | Why it matters |
|---|---|
| The host machine and its Docker daemon | A breakout gives control of everything else running there |
| Secrets in the service environment (API tokens, database URLs) | Code must never read them |
| Other runs and their data | One submission must not observe or affect another |
| Availability of the service | One abusive run must not starve the others |
| The network the host sits on | Code must not be a launch point for scanning or exfiltration |

## Trust boundaries

1. **Caller to API.** The caller is authenticated but not trusted: the code, its size and its frequency are attacker-controlled. The caller may itself be an LLM that was prompt-injected.
2. **API to container runtime.** The API process can create containers, so it is the most privileged component. It must never pass untrusted strings into a shell or into container options.
3. **Container to host.** Everything inside the container, including the interpreter, is hostile.

## Assumptions and non-goals

- Containers share the host kernel. A kernel vulnerability is out of scope for the first version; the design reduces exposure (seccomp, dropped capabilities) but does not claim VM-grade isolation. Running the runner on a gVisor or Firecracker backend is a possible later step.
- The Docker daemon is trusted and patched.
- Side channels such as timing and cache attacks between runs are out of scope.
- Multi-tenant billing and quota accounting are out of scope.

## Threats and planned mitigations

Severity is the impact if the attack succeeds with no mitigation.

| ID | Threat | Severity | Planned mitigation | Planned test |
|---|---|---|---|---|
| T1 | Network egress: call external hosts, scan the internal network, reach the cloud metadata endpoint | High | Container started with networking disabled; no published ports; metadata address unreachable by construction | Code opens a socket to a public host, to a private range and to the metadata address; all must fail |
| T2 | Filesystem escape: read host files, write outside the working area, abuse symlinks | High | Read-only root filesystem; small in-memory `/tmp` as the only writable path; no host mounts | Write to `/`, read `/proc/1/environ` of the host, follow a symlink out of `/tmp` |
| T3 | Reading service secrets from the environment | High | Container gets an empty, explicit environment; the API never forwards its own variables | Code prints its environment and searches the filesystem for known canary secrets |
| T4 | Privilege escalation inside the container | High | Non-root user, `no-new-privileges`, all capabilities dropped, default seccomp profile, no privileged mode, no Docker socket | Attempt `setuid` binaries, `mount`, `ptrace` and capability use |
| T5 | Fork bomb or process exhaustion | Medium | Process count limit (`pids-limit`) | Fork loop; the run must end with a limit error and the host must stay responsive |
| T6 | Memory exhaustion | Medium | Hard memory limit with swap disabled | Allocate in a loop; the run must be killed by the limit |
| T7 | CPU burn and infinite loops | Medium | CPU quota plus a wall-clock timeout enforced by the API, which kills and removes the container | `while True` loop; the run must be terminated near the timeout |
| T8 | Disk exhaustion through large writes | Medium | Size-limited in-memory `/tmp`; no persistent volumes | Write until full; the write must fail without affecting the host |
| T9 | Output flooding to exhaust API memory or logs | Medium | Hard cap on captured stdout and stderr, with truncation flagged in the response | Print gigabytes; the response must stay under the cap |
| T10 | Oversized or malformed submissions | Low | Request validation: maximum code size, language allow-list, timeout bounds | Boundary and malformed payloads return 422 |
| T11 | Container option injection through request fields | High | Request fields are never interpolated into commands or options; the runner uses the Docker API with fixed arguments | Fuzz fields with shell metacharacters and option-like strings |
| T12 | Leftover state between runs | Medium | One short-lived container per run, always removed in a `finally` block, including after timeouts and API errors | Run twice and check that nothing from the first run is visible; check no containers remain |
| T13 | Abuse of the service itself: request flooding, many concurrent runs | Medium | Concurrency cap and request rate limit per caller | Burst of requests; excess gets 429 and the host stays within its limits |
| T14 | Dangerous code submitted knowingly (for example miners, destructive patterns) | Low | Static policy check before execution as defense in depth only, never as the boundary | Known-bad samples are rejected; a bypass of the check must still be contained by T1 to T9 |
| T15 | Missing evidence after an incident | Medium | Audit log with caller, code hash, limits applied, result and duration for every run | A run produces a complete audit record, including for rejected and timed-out runs |

## Syscall filtering and hardened runtime

Every container runs under Docker's default seccomp profile, which blocks roughly 40 dangerous system calls, among them `mount`, `ptrace` against other processes, `kexec_load`, `bpf` and the creation of user namespaces. The profile is not disabled anywhere in the runner, and a test fails if it is: it calls `unshare(CLONE_NEWUSER)`, which the default profile rejects with `EPERM` and an unconfined container accepts. The same test was verified to fail after adding `seccomp=unconfined`.

Seccomp narrows the kernel surface but does not remove it: allowed system calls still run against the shared host kernel. For deployments that need a stronger boundary the runner accepts an alternative OCI runtime. Setting `SANDBOX_RUNTIME=runsc` passes `--runtime runsc` to `docker run`, which executes the container under gVisor. gVisor intercepts system calls in a user-space kernel, so a kernel bug in the host is much harder to reach, at the cost of slower system calls and some unsupported ones.

The gVisor path is wired and its argument is unit-tested, but it has not been exercised end to end in this repository because it needs `runsc` installed on the Docker host. Treat it as an option to validate in the target environment, not as a tested guarantee.

## Design principles

- **Isolation is the boundary, not inspection.** Static checks reduce noise; they are never relied on to stop an attacker.
- **Deny by default.** No network, no writable disk, no capabilities, no environment, then open only what a feature needs.
- **Fail closed.** If a limit cannot be applied, the run is refused.
- **Every claim has a test.** A mitigation is only listed as done after an attack test fails without it, by deliberately removing the control and checking that the test notices.

## Residual risk

Kernel-level escapes remain possible with shared-kernel containers. Deployments that accept code from untrusted third parties should run the runner on a dedicated host or a stronger isolation backend, with no other workloads and no credentials on the machine.

## Review

This document is revisited when a roadmap stage closes. Changes to limits, new capabilities of the runner and every confirmed finding from the attack suite are recorded here.
