"""VRAM-aware model routing (Phase 1.5, KD spec §10)."""
from providers.llm_router import LLMRouter, estimate_size_gb


def _fleet():
    return {
        "vram_budget_gb": 7.0,
        "models": [
            {"name": "qwen3.5:27b", "tier": "premium", "cost": 10},
            {"name": "qwen3.5:4b", "tier": "standard", "cost": 3},
            {"name": "qwen3.5:0.8b", "tier": "cheap", "cost": 1},
        ],
    }


def test_estimate_from_name():
    assert estimate_size_gb("qwen3.5:27b") > 15
    assert 3.0 < estimate_size_gb("qwen3.5:4b") < 5.0
    assert estimate_size_gb("gpt-4o") == 0.0          # cloud: unknown, unpenalized


def test_router_prefers_fitting_model():
    router = LLMRouter(_fleet())
    # premium would outrank only via escalation; cheap fits and wins selection
    model = router.select()
    assert model.name == "qwen3.5:0.8b"
    assert router._fits_vram(model)


def test_router_overflow_still_available_when_nothing_fits():
    cfg = _fleet()
    cfg["models"] = [{"name": "qwen3.5:35b", "tier": "standard", "cost": 3}]
    router = LLMRouter(cfg)
    model = router.select()
    assert model is not None and model.name == "qwen3.5:35b"   # falls back, not hidden


def test_zero_budget_means_no_penalty():
    cfg = _fleet()
    cfg["vram_budget_gb"] = 0
    router = LLMRouter(cfg)
    assert router._fits_vram(router.models[0])
