"""Keep local protocol testing independent of Home Assistant."""

import importlib.util

collect_ignore = ["ha"] if importlib.util.find_spec("homeassistant") is None else []
