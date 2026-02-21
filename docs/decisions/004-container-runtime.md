# 004: Docker as the only container runtime

**Date:** 2026-02-21
**Status:** Accepted

## Context

The agent process runs inside a container for isolation. We need to decide which container runtimes to support.

## Decision

Docker only. No Podman, no Apple Containers.

## Rationale

- **Universal.** Docker runs on macOS (Docker Desktop), Linux (native), and Windows (WSL2). One codepath, one set of docs.
- **Simplicity.** Supporting multiple runtimes means testing multiple runtimes, handling subtle differences, and maintaining compatibility shims.
- **Sufficient.** For a single-user personal agent, Docker's isolation model is adequate. Rootless/daemonless (Podman's advantages) aren't critical here.

## Rejected alternatives

- **Docker + Podman:** Podman's CLI is mostly Docker-compatible but not perfectly. The marginal benefit of daemonless operation doesn't justify the testing burden.
- **Apple Containers:** macOS-only. Too niche, too new.
- **Defer containerization:** Considered but rejected — container isolation is a core design goal, not an afterthought.
