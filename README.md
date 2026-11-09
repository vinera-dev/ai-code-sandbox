# ai-code-sandbox

A service that runs untrusted or LLM-generated Python code in isolated containers, with strict limits and an attack test suite.

> **Status:** early development. The API skeleton and CI are in place; the container runner is next.

## Purpose

Show how to execute AI-generated code safely: network isolation, resource limits, least privilege, policy checks and auditability, plus tests that try to break out.

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
- [ ] 4. Static policy checks
- [ ] 5. Audit log
- [ ] 6. Attack test suite and documented threat model

## Security

See the [threat model](THREAT_MODEL.md) for the assets, trust boundaries and planned mitigations.

## License

Released under the [MIT License](LICENSE).
