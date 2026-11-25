"""Load a script from a skill folder (the folder names have hyphens)."""

import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")


def load(folder, name, market="us"):
    """Each script picks its market (us or in) once, when it loads. The tests pin
    it, so a TRADER_MARKET in your shell or a trader/config.json with "market"
    in the folder you run them from cannot change what they test."""
    path = os.path.join(ROOT, folder, name + ".py")
    spec = importlib.util.spec_from_file_location("trader_%s_%s" % (name, market), path)
    mod = importlib.util.module_from_spec(spec)
    old = os.environ.get("TRADER_MARKET")
    os.environ["TRADER_MARKET"] = market
    try:
        spec.loader.exec_module(mod)
    finally:
        if old is None:
            os.environ.pop("TRADER_MARKET", None)
        else:
            os.environ["TRADER_MARKET"] = old
    return mod
