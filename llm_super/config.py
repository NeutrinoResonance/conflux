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
    max_repairs: int = 2
    budget_usd_per_task: float = 0.50
    trailer: bool = True


@dataclass
class Config:
    providers: dict[str, Provider]
    models: dict[str, Model]
    default_executor: str
    utility: str
    verifier_pool: list[str]
    supervision: Supervision
    execution: Execution
    path: Path = field(default_factory=lambda: Path("models.yaml"))

    def model(self, name: str) -> Model:
        if name not in self.models:
            raise KeyError(f"model {name!r} not in registry ({', '.join(self.models)})")
        return self.models[name]

    def provider_for(self, model: Model) -> Provider:
        return self.providers[model.provider]

    def pick_verifier(self, executor_family: str) -> Model:
        """Cross-family rule: verifier family must differ from the executor's."""
        for name in self.verifier_pool:
            m = self.models[name]
            if m.family != executor_family and m.logprobs and "verifier" in m.roles:
                return m
        raise RuntimeError(f"no logprobs-capable verifier outside family {executor_family!r}")


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
        )
        if models[name].provider not in providers:
            raise ValueError(f"model {name!r} references unknown provider {models[name].provider!r}")

    routing = raw.get("routing", {})
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
        path=path,
    )
