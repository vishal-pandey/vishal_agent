"""Decoding must be deterministic.

The same request, repeated against the deployed agent, booked 2026-09-09 once
and 2026-09-16 another time -- 09-16 being inside the date range the model
memorised from its booking training data. The held-out eval, which pins
temperature to 0.0, saw the date resolved correctly 10/10.

Sampling is the difference. For an agent whose job is to extract a name, an
email and a timestamp and put them on a real calendar, there is nothing for
temperature to buy, and a wrong date is a meeting nobody attends.
"""
from vishal_agent.agent import root_agent


def test_temperature_is_pinned_to_zero():
    cfg = root_agent.generate_content_config
    assert cfg is not None, "no generate_content_config: decoding is left to the server default"
    assert cfg.temperature == 0.0, f"temperature must be 0.0 for booking, got {cfg.temperature}"


def test_top_p_does_not_reintroduce_sampling():
    cfg = root_agent.generate_content_config
    assert cfg.top_p in (None, 1.0), f"top_p must not resample, got {cfg.top_p}"
