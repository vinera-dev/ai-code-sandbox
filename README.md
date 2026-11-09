# ai-code-sandbox

[![CI](https://github.com/vinera-dev/ai-code-sandbox/actions/workflows/ci.yml/badge.svg)](https://github.com/vinera-dev/ai-code-sandbox/actions/workflows/ci.yml)

A service that runs untrusted or LLM-generated Python code in isolated containers, with strict limits and an attack test suite.

> **Status:** the API, policy, audit log and Docker runner with all planned limits are implemented and tested locally on Docker Desktop. The CI workflow runs the container and attack tests on Linux, but no pipeline run has been observed yet. Not hardened for production use: see the residual risks in the threat model.

## Purpose

Show how to execute AI-generated code safely: network isolation, resource limits, least privilege, policy checks and auditability, plus tests that try to break out.

## What works today

- `POST /runs` validates the request (code size, timeout bounds) and answers `422` for invalid input
- A static AST policy blocks forbidden imports, calls and attributes, configured in `app/policy.yaml`, and answers `403` with the violated rules and line numbers. It fails closed on code that cannot be parsed. It is defense in depth, not the security boundary: it is easy to bypass and the tests say so
- Every run, blocked, rejected or executed, is written to a JSON lines audit log with the code hash, policy hash, status and duration. The code and the output are never logged
- `GET /runs/{id}` returns the audit entry of a run
- At most N runs execute at once (`MAX_CONCURRENT_RUNS`, default 4); extra requests get `429`
- With `SANDBOX_RUNNER=docker`, each run executes in one short-lived container built from `docker/Dockerfile`: no network, read-only root filesystem with a 16 MB in-memory `/tmp`, unprivileged user, all capabilities dropped, `no-new-privileges`, default seccomp profile, 128 MB memory without swap, 0.5 CPU, 64 processes, a wall-clock timeout that removes the container, 64 KiB cap per output stream and an empty environment. `SANDBOX_IMAGE` and `SANDBOX_RUNTIME` (for example `runsc`, untested) are optional
- An attack suite in `tests/attacks` tries a fork bomb, outbound traffic, writes to `/`, `/proc` access, secret theft, memory exhaustion, infinite loops, privileged calls, symlink tricks and host mounts

```bash
pip install -e ".[dev]"
pytest -m "not docker"
pytest
docker build -t sbx-python:latest -f docker/Dockerfile docker
SANDBOX_RUNNER=docker uvicorn app.main:app
```

`pytest` without a filter also runs the container tests when Docker is available and skips them otherwise.

## Integration example

`examples/llm_integration.py` shows the intended flow for an application that lets a model write code: the code goes through the static policy first, then runs in a container, and the caller gets a small outcome object. The model here is scripted so the example is deterministic.

```bash
docker build -t sbx-python:latest -f docker/Dockerfile docker
python -m examples.llm_integration
```

Expected output:

```
sum the first hundred integers: completed 5050
read the service secrets: blocked forbidden_import
call an external host: blocked forbidden_import
wait forever: timeout
```

## Scope

- HTTP API to submit code and receive stdout, stderr, exit status and resource usage
- One short-lived container per run: no network, read-only filesystem, non-root user
- CPU, memory, process and wall-clock limits, plus output size caps
- Static policy checks on the code before execution
- Audit log of every run
- Attack test suite: fork bombs, network egress attempts, filesystem escape, environment secret access, infinite loops

## Stack

Python, FastAPI, Docker, pytest, GitHub Actions.

## Roadmap

- [x] 1. API skeleton, tests and CI
- [x] 2. Container runner with no network and a read-only filesystem
- [x] 3. Resource and time limits
- [x] 4. Static policy checks
- [x] 5. Audit log
- [x] 6. Attack test suite and documented threat model
- [ ] 7. Authentication, per-caller rate limit and start-up sweep of leftover containers

## Security

See the [threat model](THREAT_MODEL.md) for the assets, trust boundaries, mitigations with their tests and the residual risks.

## License

Released under the [MIT License](LICENSE).
