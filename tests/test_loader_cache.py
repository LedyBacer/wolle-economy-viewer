import pandas as pd

from wolle_economy.domain import loader


def test_marketplace_loaders_use_independent_cache_entries(monkeypatch):
    calls = []

    def load(code, **kwargs):
        calls.append(code)
        return pd.DataFrame({"source": [code]})

    monkeypatch.setattr(loader, "_load_orders_for_code", load)
    for spec in loader.get_marketplace_specs():
        spec.load_orders.clear()
    try:
        for _ in range(2):
            for spec in loader.get_marketplace_specs():
                assert spec.load_orders()["source"].tolist() == [spec.code]
        assert calls == [spec.code for spec in loader.get_marketplace_specs()]
    finally:
        for spec in loader.get_marketplace_specs():
            spec.load_orders.clear()
