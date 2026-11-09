# Threat model

Status: reviewed after the container runner and the attack suite were implemented. The table below records what is implemented and which test covers it. Controls were checked by weakening them and confirming that the matching test fails.

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

| ID | Threat | Severity | Mitigation | Status and test |
|---|---|---|---|---|
| T1 | Network egress: call external hosts, scan the internal network, reach the cloud metadata endpoint | High | Container started with networking disabled; no published ports; metadata address unreachable by construction | Implemented. `tests/attacks/test_attacks.py::test_outbound_traffic_is_blocked` |
| T2 | Filesystem escape: read host files, write outside the working area, abuse symlinks | High | Read-only root filesystem; small in-memory `/tmp` as the only writable path; no host mounts | Implemented. `test_writing_to_the_root_filesystem_fails`, `tests/attacks/test_escapes.py` |
| T3 | Reading service secrets from the environment | High | Container gets an empty, explicit environment; the API never forwards its own variables | Implemented. `test_service_secrets_are_not_readable`, `test_host_environment_is_not_visible` |
| T4 | Privilege escalation inside the container | High | Non-root user, `no-new-privileges`, all capabilities dropped, default seccomp profile, no privileged mode, no Docker socket | Implemented. `test_privileged_operations_are_refused`, tests for uid, capabilities and seccomp |
| T5 | Fork bomb or process exhaustion | Medium | Process count limit (`pids-limit`) | Implemented. `test_fork_bomb_is_contained` |
| T6 | Memory exhaustion | Medium | Hard memory limit with swap disabled | Implemented. `test_memory_exhaustion_is_killed` |
| T7 | CPU burn and infinite loops | Medium | CPU quota plus a wall-clock timeout enforced by the API, which kills and removes the container | Implemented. `test_infinite_loop_is_terminated_on_time` |
| T8 | Disk exhaustion through large writes | Medium | Size-limited in-memory `/tmp`; no persistent volumes | Implemented. `test_tmp_is_writable_but_small` |
| T9 | Output flooding to exhaust API memory or logs | Medium | Hard cap on captured stdout and stderr, with truncation flagged in the response | Implemented. `test_huge_output_is_truncated` |
| T10 | Oversized or malformed submissions | Low | Request validation: maximum code size, language allow-list, timeout bounds | Partly implemented. Size and timeout bounds return 422; there is no language allow-list because only Python is supported |
| T11 | Container option injection through request fields | High | Request fields are never interpolated into commands or options; the runner uses the Docker API with fixed arguments | Implemented for code. Code travels on stdin and the argument list is fixed; `test_shell_metacharacters_in_code_stay_literal`. The image name and runtime come from operator configuration only |
| T12 | Leftover state between runs | Medium | One short-lived container per run, always removed in a `finally` block, including after timeouts and API errors | Implemented. `test_nothing_from_a_previous_run_is_visible`, `test_container_is_removed_when_the_runner_fails_midway` |
| T13 | Abuse of the service itself: request flooding, many concurrent runs | Medium | Concurrency cap and request rate limit per caller | Partly implemented. Concurrency cap returns 429; there is no per-caller rate limit |
| T14 | Dangerous code submitted knowingly (for example miners, destructive patterns) | Low | Static policy check before execution as defense in depth only, never as the boundary | Implemented as defense in depth. `tests/test_policy.py` |
| T15 | Missing evidence after an incident | Medium | Audit log with caller, code hash, limits applied, result and duration for every run | Partly implemented. The audit log has code hash, policy hash, status, exit code and duration; it has no caller identity and does not record the limits applied |

## Syscall filtering and hardened runtime

Every container runs under Docker's default seccomp profile, which blocks roughly 40 dangerous system calls, among them `mount`, `ptrace` against other processes, `kexec_load`, `bpf` and the creation of user namespaces. The profile is not disabled anywhere in the runner, and a test fails if it is: it calls `unshare(CLONE_NEWUSER)`, which the default profile rejects with `EPERM` and an unconfined container accepts. The same test was verified to fail after adding `seccomp=unconfined`.

Seccomp narrows the kernel surface but does not remove it: allowed system calls still run against the shared host kernel. For deployments that need a stronger boundary the runner accepts an alternative OCI runtime. Setting `SANDBOX_RUNTIME=runsc` passes `--runtime runsc` to `docker run`, which executes the container under gVisor. gVisor intercepts system calls in a user-space kernel, so a kernel bug in the host is much harder to reach, at the cost of slower system calls and some unsupported ones.

The gVisor path is wired and its argument is unit-tested, but it has not been exercised end to end in this repository because it needs `runsc` installed on the Docker host. Treat it as an option to validate in the target environment, not as a tested guarantee.

## Design principles

- **Isolation is the boundary, not inspection.** Static checks reduce noise; they are never relied on to stop an attacker.
- **Deny by default.** No network, no writable disk, no capabilities, no environment, then open only what a feature needs.
- **Fail closed.** If a limit cannot be applied, the run is refused.
- **Every claim has a test.** A mitigation is only listed as done after an attack test fails without it, by deliberately removing the control and checking that the test notices.

## Residual risks

- **Shared kernel.** A kernel vulnerability reachable through an allowed system call defeats every control above. Seccomp reduces the surface; gVisor (see above) would reduce it further but has not been run here.
- **The API process controls Docker.** It needs access to the Docker daemon, which is equivalent to root on the host. Anything that compromises the API compromises the host. The daemon socket must not be exposed to any other component.
- **No authentication and no rate limit.** The trust boundary above assumes an authenticated caller, but the API does not authenticate yet. Only the concurrency cap protects availability.
- **The static policy is bypassable.** It is a filter, not a boundary, and its tests say so.
- **Cold start counts against the timeout.** The wall-clock deadline includes container start-up, so a slow host shortens the usable time of a run.
- **Memory and process accounting is per container.** The 16 MB tmpfs counts toward the memory limit, and many parallel containers can still exhaust the host even though each one is capped. The concurrency cap bounds this.
- **Orphaned containers after a crash.** Containers are removed in a `finally` block, but if the API process is killed hard, a running container keeps going because nothing enforces the deadline any more. A sweep for leftover `sbx-` containers at start-up is not implemented.
- **Image supply chain.** The base image is a floating tag, not pinned by digest.
- **Daemon defaults are relied on.** Masked `/proc` paths and the default seccomp profile come from the Docker daemon configuration. The tests detect a removed seccomp profile, but the `/proc` test cannot detect a daemon that stopped masking those paths.
- **Tested on one platform.** The attack suite was run against Docker Desktop on Windows with a Linux VM. The CI workflow runs it on Linux, but no green pipeline run has been observed yet.
- **Side channels** (timing, cache) and multi-tenant accounting remain out of scope.

## Review

This document was last reviewed when the attack suite was completed. It is revisited when a roadmap stage closes. Changes to limits, new capabilities of the runner and every confirmed finding from the attack suite are recorded here.
