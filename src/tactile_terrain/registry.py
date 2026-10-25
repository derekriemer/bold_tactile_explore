"""Name-keyed registries for every extension point, loadable from entry points."""

from __future__ import annotations

from importlib.metadata import entry_points

ENTRY_POINT_PREFIX = "tactile_terrain."


class Registry[T]:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: dict[str, T] = {}

    def register(self, name: str, obj: T) -> None:
        self._items[name] = obj

    def get(self, name: str) -> T:
        try:
            return self._items[name]
        except KeyError:
            valid = ", ".join(self.names()) or "(none registered)"
            raise KeyError(f"Unknown {self.kind} '{name}'. Valid names: {valid}") from None

    def names(self) -> list[str]:
        return sorted(self._items)

    def load_entry_points(self) -> None:
        """Register everything declared in the entry-point group tactile_terrain.<kind>."""
        for ep in entry_points(group=ENTRY_POINT_PREFIX + self.kind):
            self.register(ep.name, ep.load())


elevation_providers: Registry = Registry("elevation_providers")
line_providers: Registry = Registry("line_providers")
area_providers: Registry = Registry("area_providers")
line_styles: Registry = Registry("line_styles")
textures: Registry = Registry("textures")
warps: Registry = Registry("warps")
analyzers: Registry = Registry("analyzers")
joints: Registry = Registry("joints")
exporters: Registry = Registry("exporters")

ALL_REGISTRIES: list[Registry] = [
    elevation_providers,
    line_providers,
    area_providers,
    line_styles,
    textures,
    warps,
    analyzers,
    joints,
    exporters,
]
