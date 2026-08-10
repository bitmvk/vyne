# vyne-material

Material 3 Expressive widgets for Vyne.

This package provides the Material component catalog (`Button`, `Card`,
`Slider`, `Switch`, `TextField`, and the rest) as Python-owned composites
that lower to Vyne primitives.

```python
from vyne_material import Button, Slider, MaterialTheme

Button(label="Press", on_click=...)
```

Requires the `vyne` core package.
