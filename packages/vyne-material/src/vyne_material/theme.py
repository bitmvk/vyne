"""Material 3 Expressive design tokens.

The types in this module intentionally stay on the Python side.  Components
resolve a :class:`MaterialTheme` into ordinary Vyne primitive props before the
element tree reaches the renderer.

"""

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(frozen=True)
class ColorScheme:
    primary: str = "#6750A4"
    on_primary: str = "#FFFFFF"
    primary_container: str = "#EADDFF"
    on_primary_container: str = "#21005D"
    secondary: str = "#625B71"
    on_secondary: str = "#FFFFFF"
    secondary_container: str = "#E8DEF8"
    on_secondary_container: str = "#1D192B"
    tertiary: str = "#7D5260"
    on_tertiary: str = "#FFFFFF"
    tertiary_container: str = "#FFD8E4"
    on_tertiary_container: str = "#31111D"
    error: str = "#B3261E"
    on_error: str = "#FFFFFF"
    error_container: str = "#F9DEDC"
    on_error_container: str = "#410E0B"
    surface: str = "#FFFBFE"
    on_surface: str = "#1D1B20"
    surface_variant: str = "#E7E0EC"
    on_surface_variant: str = "#49454F"
    surface_container_lowest: str = "#FFFFFF"
    surface_container_low: str = "#F7F2FA"
    surface_container: str = "#F3EDF7"
    surface_container_high: str = "#ECE6F0"
    surface_container_highest: str = "#E6E0E9"
    outline: str = "#79747E"
    outline_variant: str = "#CAC4D0"
    inverse_surface: str = "#322F35"
    inverse_on_surface: str = "#F5EFF7"
    inverse_primary: str = "#D0BCFF"
    scrim: str = "#000000"
    shadow: str = "#000000"


@dataclass(frozen=True)
class TypeStyle:
    font_size: float
    line_height: float


@dataclass(frozen=True)
class Typography:
    display_large: TypeStyle = field(default_factory=lambda: TypeStyle(57, 64))
    display_medium: TypeStyle = field(default_factory=lambda: TypeStyle(45, 52))
    display_small: TypeStyle = field(default_factory=lambda: TypeStyle(36, 44))
    headline_large: TypeStyle = field(default_factory=lambda: TypeStyle(32, 40))
    headline_medium: TypeStyle = field(default_factory=lambda: TypeStyle(28, 36))
    headline_small: TypeStyle = field(default_factory=lambda: TypeStyle(24, 32))
    title_large: TypeStyle = field(default_factory=lambda: TypeStyle(22, 28))
    title_medium: TypeStyle = field(default_factory=lambda: TypeStyle(16, 24))
    title_small: TypeStyle = field(default_factory=lambda: TypeStyle(14, 20))
    body_large: TypeStyle = field(default_factory=lambda: TypeStyle(16, 24))
    body_medium: TypeStyle = field(default_factory=lambda: TypeStyle(14, 20))
    body_small: TypeStyle = field(default_factory=lambda: TypeStyle(12, 16))
    label_large: TypeStyle = field(default_factory=lambda: TypeStyle(14, 20))
    label_medium: TypeStyle = field(default_factory=lambda: TypeStyle(12, 16))
    label_small: TypeStyle = field(default_factory=lambda: TypeStyle(11, 16))


@dataclass(frozen=True)
class ShapeScale:
    none: float = 0
    extra_small: float = 4
    small: float = 8
    medium: float = 12
    large: float = 16
    extra_large: float = 28
    full: float = 999


@dataclass(frozen=True)
class MaterialTheme:
    colors: ColorScheme = field(default_factory=ColorScheme)
    typography: Typography = field(default_factory=Typography)
    shapes: ShapeScale = field(default_factory=ShapeScale)


DEFAULT_THEME = MaterialTheme()


__all__ = [
    "ColorScheme",
    "DEFAULT_THEME",
    "MaterialTheme",
    "ShapeScale",
    "Typography",
    "TypeStyle",
]
