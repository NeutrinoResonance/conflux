"""Load and validate models.yaml into typed config objects."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    key_source: str
    # declared usage limits, e.g. {usd_5h: 12, usd_week: 30, usd_month: 60}
    # (Go dollar windows) or {input_tokens_week: 60000000} (NanoGPT)
    limits: dict = field(default_factory=dict)
    # extra request headers; the value "{session}" becomes a stable id for
    # this proxy process (OpenCode Go rejects requests without one)
    headers: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Model:
    name: str          # registry key, e.g. "deepseek-v4-pro"
    provider: str
    id: str            # provider-side model id
    family: str
    roles: tuple[str, ...]
    logprobs: bool
    top_logprobs_max: int
    price_in_per_m: float
    price_out_per_m: float
    failure_priors: tuple[str, ...] = ()
    fallbacks: tuple[str, ...] = ()
    # Provider request parameters sent with every call to this model, e.g.
    # {reasoning_effort: high} where a gateway's default is rejected upstream.
    request: dict = field(default_factory=dict, hash=False, compare=False)

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * self.price_in_per_m + tokens_out * self.price_out_per_m) / 1e6


@dataclass(frozen=True)
class Execution:
    backend: str = "gce"
    # When set, neither an agent nor a runtime/UI override can move generated
    # workloads to another backend. "off" remains allowed because it spawns
    # nothing. Changing this value is an operator configuration change.
    locked_backend: str | None = "gce"
    gcloud_project: str = ""
    gcloud_account: str = ""
    gcloud_zone: str = "us-central1-a"
    gcloud_machine_type: str = "e2-micro"
    # Docker adapter target (trusted operator config; never agent-visible).
    # Selecting it is an operator change: locked_backend: docker.
    docker_container: str = ""

    def resolve_backend(self, requested: str | None = None) -> str:
        desired = self.backend if requested in (None, "", "auto") else requested
        if desired == "off":
            return "off"
        if self.locked_backend and desired != self.locked_backend:
            from .execution_backends import ExecutionBoundaryError
            raise ExecutionBoundaryError(
                f"generated-code execution is locked to {self.locked_backend!r}; "
                f"refusing {desired!r}"
            )
        return desired

    def boundary_lock(self):
        from .execution_backends import ExecutionBackendLock
        if not self.locked_backend:
            return None
        if self.locked_backend == "docker":
            return ExecutionBackendLock(
                "docker",
                {"mode": "persistent-container",
                 "container": self.docker_container or "conflux-agent"},
            )
        return ExecutionBackendLock(
            self.locked_backend,
            {"mode": "ephemeral", "project": self.gcloud_project or "active-gcloud-project",
             "account": self.gcloud_account or "active-gcloud-account",
             "zone": self.gcloud_zone, "machine_type": self.gcloud_machine_type},
        )


@dataclass(frozen=True)
class AdminAuth:
    """Control-plane authentication. DISABLED by default.

    Enabling is one setting: put a non-empty token in models.yaml
    (``admin.token``) or export ``CONFLUX_ADMIN_TOKEN``. When set, every
    /admin/* route — including the action-decision endpoints — requires the
    token via ``Authorization: Bearer``, the ``X-Conflux-Token`` header,
    the ``conflux_admin`` cookie, or a one-time ``?token=`` query (which
    sets the cookie for browser dashboards). When unset, the server prints
    an explicit warning that the control plane is reachable by anyone who
    can reach the port.
    """
    token: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.token)


@dataclass(frozen=True)
class Summaries:
    """Incremental summary generation. DISABLED by default: each run invokes
    the local Claude CLI and spends real model budget, so turning it on is an
    explicit operator choice. When enabled, the server periodically runs the
    same resumable message/step backfills the CLI commands use, and every
    run — manual or incremental — is recorded in the durable summary_jobs
    ledger."""
    incremental: bool = False
    interval_s: float = 600.0
    message_model: str = "sonnet"
    step_model: str = "haiku"
    max_budget_usd: float = 0.75
    batch_size: int = 8
    batch_chars: int = 40_000


@dataclass(frozen=True)
class Supervision:
    score_scale: int = 20
    pass_threshold: float = 0.70
    # min: every criterion must pass the threshold (no criterion is averaged
    # away by the others); mean: the legacy average over criteria.
    criteria_aggregate: str = "min"
    verify_max_tokens: int = 8000   # thinking verifiers spend budget before scoring
    verify_repeats: int = 1
    adversarial_repeats: int = 3   # K for the adversarial tier (variance ↓ 1/K)
    max_repairs: int = 2
    max_output_tokens: int = 16384  # executor completion budget; reasoning
    # models can burn 8k on thought alone and return an EMPTY answer
    # Streaming supervised turns surface live supervisor progress instead of
    # blind keepalives: "comments" (default) emits SSE comment lines — every
    # OpenAI-compatible client ignores them, so message content is untouched;
    # "content" emits visible "[conflux] …" delta lines (SPEC §7.2 in-band
    # notices — opt-in because they become part of the assistant message);
    # "off" restores plain keepalives.
    stream_status: str = "comments"
    confirm_new_sessions: bool = True  # ingress gate: first message of an
    # unknown conversation gets a no-model-call warning; continuing confirms
    # Legacy stateful /v1/chat/completions mode. OFF by default: the compat
    # endpoint is a stateless "one supervised turn as a model" adapter —
    # per-request session identity (or the explicit conversation header),
    # no first-message-hash identity, no alias/!attach, no new-conversation
    # gate, no in-band !commands, no transcript-diff edit bookkeeping.
    # ON restores the old behavior for clients that depend on it; the
    # workspace UI is unaffected either way.
    stateful_chat_endpoint: bool = False
    budget_usd_per_task: float = 0.50
    trailer: bool = True
    turn_timeout_s: float = 1800.0
    plan_threshold_chars: int = 1200
    max_plan_units: int = 6


# How a senate's member ratings combine into an approve/deny decision.
#   max     approve only if the most cautious member is below the threshold
#   median  the middle member decides
#   mean    the average rating decides
#   quorum  deny once `quorum` members rate at or above the threshold
SENATE_DECISIONS = ("max", "median", "mean", "quorum")
# Legacy verdict feedback selection. The decision panel always receives every
# member's concerns, including approvals, regardless of this setting.
SENATE_CONCERNS = ("all", "top")


@dataclass
class SenateSettings:
    members: list[str] = field(default_factory=list)
    decision: str = "max"
    approve_below: float = 0.5
    quorum: int = 1
    concerns: str = "all"

    def __post_init__(self) -> None:
        if self.decision not in SENATE_DECISIONS:
            raise ValueError(f"senate.decision must be one of {SENATE_DECISIONS}, got {self.decision!r}")
        if self.concerns not in SENATE_CONCERNS:
            raise ValueError(f"senate.concerns must be one of {SENATE_CONCERNS}, got {self.concerns!r}")
        if (isinstance(self.quorum, bool) or not isinstance(self.quorum, int)
                or self.quorum < 1):
            raise ValueError("senate.quorum must be a positive integer")
        if (isinstance(self.approve_below, bool)
                or not isinstance(self.approve_below, (int, float))
                or not math.isfinite(self.approve_below)
                or not 0 <= self.approve_below <= 1):
            raise ValueError("senate.approve_below must be a finite number between 0 and 1")
        if (not isinstance(self.members, list)
                or any(not isinstance(name, str) or not name for name in self.members)):
            raise ValueError("senate.members must be a list of model names")
        if len(set(self.members)) != len(self.members):
            raise ValueError("senate.members must not contain duplicate models")
        self.members = list(self.members)


@dataclass
class DeciderSettings:
    enabled: bool = True
    members: list[str] = field(default_factory=lambda: ["deepseek-v4-pro", "glm-5.3"])
    done_requires: str = "all"
    next_step_from: str = "all"
    family_rule: str = "any"
    frequency: str = "every_step"
    max_tokens: int = 24000
    timeout_s: float = 300
    max_repairs: int = 1
    # Executor retries of one decision after a deterministic refusal (scope
    # gate, governor policy, malformed or empty reply) before re-deciding.
    executor_repairs: int = 2
    max_decisions_per_request: int = 4
    max_checks_per_turn: int = 4
    failure_mode: str = "closed"

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("decider.enabled must be a boolean")
        if (not isinstance(self.members, list) or not self.members
                or any(not isinstance(n, str) or not n for n in self.members)
                or len(set(self.members)) != len(self.members)):
            raise ValueError("decider.members must be a nonempty list of unique model names")
        self.members = list(self.members)
        for key, choices in {
            "done_requires": ("all", "any", "majority"),
            "next_step_from": ("all", "first", "each_in_turn"),
            "family_rule": ("any", "different_from_executor"),
            "frequency": ("every_step",), "failure_mode": ("closed",),
        }.items():
            if getattr(self, key) not in choices:
                raise ValueError(f"decider.{key} must be one of {choices}")
        for key, minimum in (("max_tokens", 1), ("max_repairs", 0), ("executor_repairs", 0),
                             ("max_decisions_per_request", 1), ("max_checks_per_turn", 1)):
            if type(getattr(self, key)) is not int or getattr(self, key) < minimum:
                raise ValueError(f"decider.{key} must be an integer >= {minimum}")
        if (isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, (int, float))
                or not math.isfinite(self.timeout_s) or self.timeout_s <= 0):
            raise ValueError("decider.timeout_s must be a positive finite number")


@dataclass
class Config:
    providers: dict[str, Provider]
    models: dict[str, Model]
    default_executor: str
    utility: str
    verifier_pool: list[str]
    supervision: Supervision
    execution: Execution
    admin: AdminAuth = field(default_factory=AdminAuth)
    summaries: Summaries = field(default_factory=Summaries)
    senate: SenateSettings = field(default_factory=SenateSettings)
    decider: DeciderSettings = field(default_factory=DeciderSettings)
    learned_routing: bool = True
    min_routing_samples: int = 5
    referee: str = ""              # large model that picks repair strategies
    trivial_executor: str = ""     # cheap model for difficulty="trivial" turns
    path: Path = field(default_factory=lambda: Path("models.yaml"))

    def model(self, name: str) -> Model:
        if name not in self.models:
            raise KeyError(f"model {name!r} not in registry ({', '.join(self.models)})")
        return self.models[name]

    def critic_settings(self, overrides: Mapping | None = None) -> SenateSettings:
        """Resolve a critic node's settings without changing shared defaults."""
        raw = dict(overrides or {})
        values = {key: raw.get(key, getattr(self.senate, key)) for key in (
            "members", "decision", "approve_below", "quorum", "concerns",
        )}
        if values["members"] == "auto":
            values["members"] = self.senate.members
        settings = SenateSettings(**values)
        for name in settings.members:
            if name not in self.models:
                raise ValueError(f"senate.members references unknown model {name!r}")
        return settings

    def provider_for(self, model: Model) -> Provider:
        return self.providers[model.provider]

    def decider_settings(self, overrides: Mapping | None = None) -> DeciderSettings:
        raw = dict(overrides or {})
        # Graph display/control keys are not model settings.
        unknown = set(raw) - set(DeciderSettings.__dataclass_fields__) - {"prompt"}
        if unknown:
            raise ValueError(f"unknown decider settings: {', '.join(sorted(unknown))}")
        settings = DeciderSettings(**{
            key: raw.get(key, getattr(self.decider, key))
            for key in DeciderSettings.__dataclass_fields__
        })
        if settings.enabled:
            for name in settings.members:
                if name not in self.models:
                    raise ValueError(f"decider.members references unknown model {name!r}")
        return settings

    def eligible_verifiers(self, executor_family: str) -> list[Model]:
        """Cross-family rule: verifier family must differ from the executor's.
        Ordered by failure-prior overlap with the executor (uncorrelated
        priors first — SPEC §3), then pool priority; callers fail over down
        the list."""
        exec_priors = set()
        for m in self.models.values():
            if m.family == executor_family:
                exec_priors |= set(m.failure_priors)
        out = [
            self.models[name]
            for name in self.verifier_pool
            if self.models[name].family != executor_family
            and self.models[name].logprobs
            and "verifier" in self.models[name].roles
        ]
        if not out:
            raise RuntimeError(f"no logprobs-capable verifier outside family {executor_family!r}")
        return sorted(out, key=lambda m: len(exec_priors & set(m.failure_priors)))

    def pick_verifier(self, executor_family: str) -> Model:
        return self.eligible_verifiers(executor_family)[0]

    def set_fallbacks(self, name: str, fallbacks: list[str]) -> None:
        """Runtime reorder/replace of a model's provider-rotation chain
        (the model itself is always first; see executor_chain). In-memory
        only — models.yaml stays the on-disk source of truth."""
        import dataclasses
        m = self.model(name)
        seen: set[str] = set()
        clean: list[str] = []
        for n in fallbacks:
            if n == name or n in seen:
                continue
            if n not in self.models:
                raise ValueError(f"unknown fallback model {n!r} for {name!r}")
            seen.add(n)
            clean.append(n)
        self.models[name] = dataclasses.replace(m, fallbacks=tuple(clean))

    def executor_chain(self, name: str) -> list[Model]:
        """The model plus its declared fallbacks (deduped, existing only)."""
        chain, seen = [], set()
        for n in (name, *self.models[name].fallbacks):
            if n in self.models and n not in seen:
                chain.append(self.models[n])
                seen.add(n)
        return chain


def load(path: str | Path = "models.yaml") -> Config:
    path = Path(path)
    raw = yaml.safe_load(path.read_text())

    providers = {
        name: Provider(name=name, **spec) for name, spec in raw["providers"].items()
    }
    models = {}
    for name, spec in raw["models"].items():
        models[name] = Model(
            name=name,
            provider=spec["provider"],
            id=spec["id"],
            family=spec["family"],
            roles=tuple(spec.get("roles", ())),
            logprobs=bool(spec.get("logprobs", False)),
            top_logprobs_max=int(spec.get("top_logprobs_max", 5)),
            price_in_per_m=float(spec.get("price_in_per_m", 0.0)),
            price_out_per_m=float(spec.get("price_out_per_m", 0.0)),
            failure_priors=tuple(spec.get("failure_priors", ())),
            fallbacks=tuple(spec.get("fallbacks", ())),
            request=dict(spec.get("request") or {}),
        )
        if models[name].provider not in providers:
            raise ValueError(f"model {name!r} references unknown provider {models[name].provider!r}")

    routing = raw.get("routing", {})
    for key in ("referee", "trivial_executor"):
        name = routing.get(key, "")
        if name and name not in models:
            raise ValueError(f"routing.{key} references unknown model {name!r}")
    senate = SenateSettings(**(raw.get("senate", {}) or {}))
    for name in senate.members:
        if name not in models:
            raise ValueError(f"senate.members references unknown model {name!r}")
    sup = Supervision(**raw.get("supervision", {}))
    decider = DeciderSettings(**(raw.get("decider", {}) or {}))
    if decider.enabled:
        for name in decider.members:
            if name not in models:
                raise ValueError(f"decider.members references unknown model {name!r}")
    execution = Execution(**raw.get("execution", {}))
    admin_raw = raw.get("admin", {}) or {}
    admin = AdminAuth(
        token=os.environ.get("CONFLUX_ADMIN_TOKEN")
        or (str(admin_raw.get("token") or "") or None),
    )
    return Config(
        providers=providers,
        models=models,
        default_executor=routing.get("default_executor", next(iter(models))),
        utility=routing.get("utility", next(iter(models))),
        verifier_pool=list(routing.get("verifier_pool", [])),
        supervision=sup,
        execution=execution,
        admin=admin,
        summaries=Summaries(**(raw.get("summaries", {}) or {})),
        senate=senate,
        decider=decider,
        learned_routing=bool(routing.get("learned", True)),
        min_routing_samples=int(routing.get("min_samples", 5)),
        referee=str(routing.get("referee", "")),
        trivial_executor=str(routing.get("trivial_executor", "")),
        path=path,
    )
