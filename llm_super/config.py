"""Load and validate models.yaml into typed config objects."""

from __future__ import annotations

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

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * self.price_in_per_m + tokens_out * self.price_out_per_m) / 1e6


@dataclass(frozen=True)
class Execution:
    backend: str = "local"
    gcloud_zone: str = "us-central1-a"
    gcloud_machine_type: str = "e2-micro"


@dataclass(frozen=True)
class Supervision:
    score_scale: int = 20
    pass_threshold: float = 0.70
    verify_repeats: int = 1
    adversarial_repeats: int = 3   # K for the adversarial tier (variance ↓ 1/K)
    max_repairs: int = 2
    max_output_tokens: int = 16384  # executor completion budget; reasoning
    # models can burn 8k on thought alone and return an EMPTY answer
    confirm_new_sessions: bool = True  # ingress gate: first message of an
    # unknown conversation gets a no-model-call warning; continuing confirms
    budget_usd_per_task: float = 0.50
    trailer: bool = True
    turn_timeout_s: float = 1800.0
    plan_threshold_chars: int = 1200
    max_plan_units: int = 6


@dataclass
class Config:
    providers: dict[str, Provider]
    models: dict[str, Model]
    default_executor: str
    utility: str
    verifier_pool: list[str]
    supervision: Supervision
    execution: Execution
    learned_routing: bool = True
    min_routing_samples: int = 5
    referee: str = ""              # large model that picks repair strategies
    trivial_executor: str = ""     # cheap model for difficulty="trivial" turns
    path: Path = field(default_factory=lambda: Path("models.yaml"))

    def model(self, name: str) -> Model:
        if name not in self.models:
            raise KeyError(f"model {name!r} not in registry ({', '.join(self.models)})")
        return self.models[name]

    def provider_for(self, model: Model) -> Provider:
        return self.providers[model.provider]

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
        )
        if models[name].provider not in providers:
            raise ValueError(f"model {name!r} references unknown provider {models[name].provider!r}")

    routing = raw.get("routing", {})
    for key in ("referee", "trivial_executor"):
        name = routing.get(key, "")
        if name and name not in models:
            raise ValueError(f"routing.{key} references unknown model {name!r}")
    sup = Supervision(**raw.get("supervision", {}))
    execution = Execution(**raw.get("execution", {}))
    return Config(
        providers=providers,
        models=models,
        default_executor=routing.get("default_executor", next(iter(models))),
        utility=routing.get("utility", next(iter(models))),
        verifier_pool=list(routing.get("verifier_pool", [])),
        supervision=sup,
        execution=execution,
        learned_routing=bool(routing.get("learned", True)),
        min_routing_samples=int(routing.get("min_samples", 5)),
        referee=str(routing.get("referee", "")),
        trivial_executor=str(routing.get("trivial_executor", "")),
        path=path,
    )
