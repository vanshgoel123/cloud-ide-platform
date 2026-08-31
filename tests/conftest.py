"""
conftest.py

Injects stub modules before any application code is imported so that:
  - The 'docker' SDK is not required (no Docker daemon needed in CI).
  - Prometheus counters use a fresh per-test registry so they never clash.

This file is loaded automatically by pytest before collecting tests.
"""
import sys
import types

import prometheus_client


# ── 1. Fake docker SDK ────────────────────────────────────────────────────────

def _build_docker_stub() -> None:
    """Register minimal fake 'docker' and 'docker.errors' packages."""
    errors = types.ModuleType("docker.errors")
    errors.NotFound        = type("NotFound",        (Exception,), {})
    errors.DockerException = type("DockerException", (Exception,), {})
    errors.APIError        = type("APIError",        (Exception,), {})

    docker = types.ModuleType("docker")
    docker.errors       = errors
    docker.DockerClient = type("DockerClient", (), {})
    docker.from_env     = lambda **kw: docker.DockerClient()

    sys.modules.setdefault("docker",        docker)
    sys.modules.setdefault("docker.errors", errors)


_build_docker_stub()


# ── 2. Fresh Prometheus registry per test run ─────────────────────────────────
# patch prometheus_client so Counter() uses the *given* registry and the
# global default registry is never written to during tests.

_original_counter_init = prometheus_client.Counter.__init__


def _patched_counter_init(self, name, documentation, labelnames=(), *args, registry=None, **kwargs):  # noqa: D401
    if registry is None:
        registry = prometheus_client.CollectorRegistry()
    _original_counter_init(self, name, documentation, labelnames, *args, registry=registry, **kwargs)


prometheus_client.Counter.__init__ = _patched_counter_init
