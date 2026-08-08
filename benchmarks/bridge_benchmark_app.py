"""Deterministic on-device bridge benchmark.

The initial tree deliberately emits roughly 200 native operations. Tapping the
root updates every text node, providing a repeatable incremental-commit sample.
"""

from vyne import Column, Text, run_app, state


LEAF_COUNT = 66


def App():
    generation = state(0)

    def leaf(index: int):
        props = {
            "text": f"row-{index}-generation-{generation.value}",
            "key": f"row-{index}",
        }
        if index == 3:
            props["on_click"] = lambda _event: generation.set(generation.value + 1)
        return Text(**props)

    return Column(
        *(leaf(index) for index in range(LEAF_COUNT)),
    )


run_app(App)
