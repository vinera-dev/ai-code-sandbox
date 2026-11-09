# ai-code-sandbox

A service that runs untrusted or LLM-generated Python code in isolated containers, with strict limits and an attack test suite.

> **Status:** early development. The HTTP API, input validation, static policy checks, audit log and concurrency limit are implemented and tested. The container runner is not implemented yet, so `POST /runs` answers `501` until a runner is configured. Nothing here isolates code yet.

## Purpose

Show how to execute AI-generated code safely: network isolation, resource limits, least privilege, policy checks and auditability, plus tests that try to break out.

## What works today

- `POST /runs` validates the request (code size, timeout bounds) and answers `422` for invalid input
- A static AST policy blocks forbidden imports, calls and attributes, configured in `app/policy.yaml`, and answers `403` with the violated rules and line numbers. It fails closed on code that cannot be parsed. It is defense in depth, not the security boundary: it is easy to bypass and the tests say so
- Every run, blocked, rejected or executed, is written to a JSON lines audit log with the code hash, policy hash, status and duration. The code and the output are never logged
- `GET /runs/{id}` returns the audit entry of a run
- At most N runs execute at once (`MAX_CONCURRENT_RUNS`, default 4); extra requests get `429`

```bash
pip install -e ".[dev]"
pytest
uvicorn app.main:app
```

## Planned scope

- HTTP API to submit code and receive stdout, stderr, exit status and resource usage
- One short-lived container per run: no network, read-only filesystem, non-root user
- CPU, memory, process and wall-clock limits, plus output size caps
- Static policy checks on the code before execution
- Audit log of every run
- Attack test suite: fork bombs, network egress attempts, filesystem escape, environment secret access, infinite loops

## Planned stack

Python, FastAPI, Docker, pytest, GitHub Actions.

## Roadmap

- [x] 1. API skeleton, tests and CI
- [ ] 2. Container runner with no network and a read-only filesystem
- [ ] 3. Resource and time limits
- [x] 4. Static policy checks
- [x] 5. Audit log
- [ ] 6. Attack test suite and documented threat model

## Security

See the [threat model](THREAT_MODEL.md) for the assets, trust boundaries and planned mitigations.

## License

Released under the [MIT License](LICENSE).
