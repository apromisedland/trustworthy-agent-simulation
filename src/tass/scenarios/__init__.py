"""Scenario plugins are discovered through Python entry points."""

from importlib.metadata import entry_points


def load_scenario(name: str):
    matches = list(entry_points(group="tass.scenarios", name=name))
    if len(matches) != 1:
        raise ValueError(
            f"Expected one installed scenario plugin named {name!r}; found {len(matches)}"
        )
    return matches[0].load()()
