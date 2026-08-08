"""Direct Chaquopy transport for Android.

Python remains the commit coordinator. Each logical operation is sent to a
small Java transaction builder, and Java applies the completed transaction on
the UI thread. There is no message envelope, opcode table, or binary codec on
this path.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from vyne.protocol import JsonObject, _to_json_compatible


_VALUE_NULL = 0
_VALUE_BOOL = 1
_VALUE_INT = 2
_VALUE_FLOAT = 3
_VALUE_STRING = 4
_VALUE_JSON = 5


class DirectTransport:
    """Publish logical commits through direct Java method calls."""

    # Kotlin's transaction builder and Renderer preflight validate the direct
    # operation stream before it mutates the accepted native tree. The runtime
    # can therefore skip the legacy JSON-envelope validation pass.
    preflights_commits = True

    def __init__(self, host: Any, session_id: str | None = None) -> None:
        from uuid import uuid4

        self.host = host
        self.session_id = session_id if session_id is not None else uuid4().hex
        self.send_count = 0
        self._latest: JsonObject | None = None
        self._session_published = False

    @property
    def latest(self) -> JsonObject | None:
        return self._latest

    def send(self, message: JsonObject) -> None:
        # Publish the session identity on the host BEFORE the first commit
        # so native receipts carry the real session id (design-pattern #1).
        if not self._session_published:
            setter = getattr(self.host, "setSessionId", None)
            if setter is not None:
                setter(self.session_id)
            self._session_published = True
        if message.get("type") != "commit":
            raise ValueError("DirectTransport only accepts commit messages")

        revision = message.get("revision")
        if not isinstance(revision, int):
            raise TypeError("Direct commit revision must be an integer")

        operations = list(message.get("ops", ()))
        if self._try_send_mount_commit(operations, revision):
            self.send_count += 1
            self._latest = message
            return

        if len(operations) >= 1 and all(
            operation["op"] == "set_prop" for operation in operations
        ):
            self._send_prop_batch(operations, revision=revision)
            self.send_count += 1
            self._latest = message
            return

        self.host.beginCommit(revision)
        try:
            index = 0
            while index < len(operations):
                mounted, next_index = self._collect_mount_nodes(
                    operations,
                    index,
                )
                if len(mounted) > 1:
                    self._send_mount_nodes(mounted)
                    index = next_index
                    continue

                if operations[index]["op"] == "set_prop":
                    end = index + 1
                    while (
                        end < len(operations)
                        and operations[end]["op"] == "set_prop"
                    ):
                        end += 1
                    if end - index > 1:
                        self._send_prop_batch(operations[index:end])
                        index = end
                        continue

                self._send_operation(operations[index])
                index += 1
            self.host.finishCommit()
        except Exception:
            self.host.abortCommit()
            raise

        self.send_count += 1
        self._latest = message

    def _send_operation(self, operation: JsonObject) -> None:
        name = operation["op"]
        host = self.host

        if name == "clear":
            host.clear(int(operation["id"]))
        elif name == "create":
            host.create(int(operation["id"]), str(operation["kind"]))
        elif name == "set_props":
            self._send_props(int(operation["id"]), operation["props"])
        elif name == "set_prop":
            self._send_props(
                int(operation["id"]),
                {str(operation["name"]): operation.get("value")},
                single=True,
            )
        elif name == "remove_prop":
            host.removeProp(int(operation["id"]), str(operation["name"]))
        elif name in {"listen", "listen_latest"}:
            host.listen(
                int(operation["id"]),
                str(operation["event"]),
                int(operation["handler"]),
                name == "listen_latest",
            )
        elif name == "unlisten":
            host.unlisten(int(operation["id"]), str(operation["event"]))
        elif name == "insert_child":
            host.insertChild(
                int(operation["parent"]),
                int(operation["child"]),
                int(operation["index"]),
            )
        elif name == "move_child":
            host.moveChild(
                int(operation["parent"]),
                int(operation["child"]),
                int(operation["index"]),
            )
        elif name == "remove_child":
            host.removeChild(int(operation["parent"]), int(operation["child"]))
        elif name == "remove":
            host.remove(int(operation["id"]))
        elif name == "scroll_to":
            host.scrollTo(
                int(operation["id"]),
                float(operation["offset_x"]),
                float(operation["offset_y"]),
                bool(operation["animated"]),
            )
        elif name == "motion_set_target":
            host.motionSetTarget(
                int(operation["animation_id"]),
                str(operation["slot_key"]),
                int(operation["node_id"]),
                str(operation["property"]),
                [float(value) for value in operation["targets"]],
                (
                    str(operation["slot_id"])
                    if operation.get("slot_id") is not None
                    else None
                ),
                str(operation.get("spec_type", "tween")),
                (
                    float(operation["from_value"])
                    if operation.get("from_value") is not None
                    else None
                ),
                int(operation.get("duration_ms", 300)),
                str(operation.get("easing", "ease_out")),
                float(operation.get("damping_ratio", 0.8)),
                float(operation.get("stiffness", 380.0)),
                float(operation.get("rest_value_threshold", 0.01)),
                float(operation.get("rest_velocity_threshold", 0.01)),
                str(operation.get("retarget", "restart")),
            )
        elif name == "motion_cancel":
            host.motionCancel(
                int(operation["animation_id"]),
                str(operation["slot_key"]),
            )
        elif name == "motion_driver_set_target":
            host.motionDriverSetTarget(
                int(operation["animation_id"]),
                int(operation["driver_id"]),
                int(operation["node_id"]),
                str(operation["property"]),
                [float(value) for value in operation["targets"]],
                str(operation.get("spec_type", "tween")),
                (
                    float(operation["from_value"])
                    if operation.get("from_value") is not None
                    else None
                ),
                int(operation.get("duration_ms", 300)),
                str(operation.get("easing", "ease_out")),
                float(operation.get("damping_ratio", 0.8)),
                float(operation.get("stiffness", 380.0)),
                float(operation.get("rest_value_threshold", 0.01)),
                float(operation.get("rest_velocity_threshold", 0.01)),
                str(operation.get("retarget", "restart")),
            )
        elif name == "motion_driver_cancel":
            host.motionDriverCancel(
                int(operation["animation_id"]),
                int(operation["driver_id"]),
            )
        else:
            raise ValueError(f"Unsupported direct operation: {name!r}")

    def _collect_mount_nodes(
        self,
        operations: list[JsonObject],
        start: int,
    ) -> tuple[list[tuple[JsonObject, Mapping[str, Any], JsonObject | None]], int]:
        """Collect consecutive create/props/attach node units.

        Initial mounts naturally contain hundreds of these units. Sending the
        typed columns once keeps the direct API while avoiding one JNI
        crossing for every create, property block, and insertion.
        """
        mounted = []
        index = start
        while index < len(operations) and operations[index]["op"] == "create":
            create = operations[index]
            node_id = int(create["id"])
            index += 1

            props: Mapping[str, Any] = {}
            if (
                index < len(operations)
                and operations[index]["op"] == "set_props"
                and int(operations[index]["id"]) == node_id
            ):
                props = operations[index]["props"]
                index += 1

            attachment = None
            if index < len(operations):
                candidate = operations[index]
                if (
                    candidate["op"] == "insert_child"
                    and int(candidate["child"]) == node_id
                ):
                    attachment = candidate
                    index += 1

            mounted.append((create, props, attachment))

        return mounted, index

    def _try_send_mount_commit(
        self,
        operations: list[JsonObject],
        revision: int,
    ) -> bool:
        """Send a complete mount as one typed Chaquopy call when possible.

        Reconciliation emits a fresh tree as create/set_props/insert units,
        followed by the root insertion and listener registrations.  Keeping
        those logical operations ordered inside one Kotlin entry point removes
        the begin/mount/insert/listen/finish JNI round trips without restoring
        an encoded opcode protocol.
        """
        if not operations or operations[0].get("op") != "create":
            return False

        mounted, index = self._collect_mount_nodes(operations, 0)
        if not mounted:
            return False

        mounted_ids = {int(create["id"]) for create, _, _ in mounted}
        post_attachments: list[JsonObject] = []
        while index < len(operations):
            operation = operations[index]
            if (
                operation.get("op") != "insert_child"
                or int(operation["child"]) not in mounted_ids
            ):
                break
            post_attachments.append(operation)
            index += 1

        listeners: list[JsonObject] = []
        while index < len(operations):
            operation = operations[index]
            if operation.get("op") not in {"listen", "listen_latest"}:
                break
            listeners.append(operation)
            index += 1

        if index != len(operations):
            return False

        self._send_mount_nodes(
            mounted,
            revision=revision,
            post_attachments=post_attachments,
            listeners=listeners,
        )
        return True

    def _send_mount_nodes(
        self,
        mounted: list[
            tuple[JsonObject, Mapping[str, Any], JsonObject | None]
        ],
        *,
        revision: int | None = None,
        post_attachments: Sequence[JsonObject] = (),
        listeners: Sequence[JsonObject] = (),
    ) -> None:
        ids: list[int] = []
        kinds: list[str] = []
        prop_counts: list[int] = []
        parent_ids: list[int] = []
        insertion_modes = bytearray()
        insertion_indices: list[int] = []
        names: list[str] = []
        tags = bytearray()
        long_values: list[int] = []
        double_values: list[float] = []
        string_values: list[str] = []

        for create, props, attachment in mounted:
            ids.append(int(create["id"]))
            kinds.append(str(create["kind"]))
            before = len(names)
            self._encode_props_into(
                props,
                names,
                tags,
                long_values,
                double_values,
                string_values,
            )
            prop_counts.append(len(names) - before)

            if attachment is None:
                parent_ids.append(0)
                insertion_modes.append(0)
                insertion_indices.append(0)
            else:
                parent_ids.append(int(attachment["parent"]))
                insertion_modes.append(1)
                insertion_indices.append(int(attachment["index"]))

        columns = (
            ids,
            kinds,
            prop_counts,
            names,
            bytes(tags),
            long_values,
            double_values,
            string_values,
            parent_ids,
            bytes(insertion_modes),
            insertion_indices,
        )
        if revision is None:
            self.host.mountNodes(*columns)
            return

        self.host.commitMountNodes(
            revision,
            *columns,
            [int(operation["parent"]) for operation in post_attachments],
            [int(operation["child"]) for operation in post_attachments],
            [int(operation["index"]) for operation in post_attachments],
            [int(operation["id"]) for operation in listeners],
            [str(operation["event"]) for operation in listeners],
            [int(operation["handler"]) for operation in listeners],
            bytes(
                operation["op"] == "listen_latest"
                for operation in listeners
            ),
        )

    def _send_prop_batch(
        self,
        operations: list[JsonObject],
        *,
        revision: int | None = None,
    ) -> None:
        compact = self._compact_string_batch(operations)
        if compact is not None:
            ids, name, values, contiguous = compact
            if contiguous:
                method = (
                    self.host.setContiguousStringPropBatch
                    if revision is None
                    else self.host.commitContiguousStringPropBatch
                )
                arguments = (ids[0], name, values)
            else:
                method = (
                    self.host.setStringPropBatch
                    if revision is None
                    else self.host.commitStringPropBatch
                )
                arguments = (ids, name, values)
            if revision is None:
                method(*arguments)
            else:
                method(revision, *arguments)
            return

        ids: list[int] = []
        names: list[str] = []
        tags = bytearray()
        long_values: list[int] = []
        double_values: list[float] = []
        string_values: list[str] = []

        for operation in operations:
            ids.append(int(operation["id"]))
            self._encode_prop_into(
                str(operation["name"]),
                operation.get("value"),
                names,
                tags,
                long_values,
                double_values,
                string_values,
            )

        columns = (
            ids,
            names,
            bytes(tags),
            long_values,
            double_values,
            string_values,
        )

        if revision is None:
            self.host.setPropBatch(*columns)
        else:
            self.host.commitPropBatch(revision, *columns)

    @staticmethod
    def _compact_string_batch(
        operations: list[JsonObject],
    ) -> tuple[list[int], str, list[str], bool] | None:
        """Return compact columns for one repeated string property."""
        if not operations:
            return None

        name = str(operations[0]["name"])
        ids: list[int] = []
        values: list[str] = []
        contiguous = True
        previous_id: int | None = None

        for operation in operations:
            value = operation.get("value")
            if str(operation["name"]) != name or not isinstance(value, str):
                return None
            node_id = int(operation["id"])
            if previous_id is not None and node_id != previous_id + 1:
                contiguous = False
            ids.append(node_id)
            values.append(value)
            previous_id = node_id

        return ids, name, values, contiguous

    def _send_props(
        self,
        node_id: int,
        props: Mapping[str, Any],
        *,
        single: bool = False,
    ) -> None:
        encoded = self._encode_props(props)
        host_method = self.host.setProp if single else self.host.setProps
        host_method(node_id, *encoded)

    def _encode_props(
        self,
        props: Mapping[str, Any],
    ) -> tuple[
        list[str],
        bytes,
        list[int],
        list[float],
        list[str],
    ]:
        names: list[str] = []
        tags = bytearray()
        long_values: list[int] = []
        double_values: list[float] = []
        string_values: list[str] = []

        self._encode_props_into(
            props,
            names,
            tags,
            long_values,
            double_values,
            string_values,
        )
        return (
            names,
            bytes(tags),
            long_values,
            double_values,
            string_values,
        )

    def _encode_props_into(
        self,
        props: Mapping[str, Any],
        names: list[str],
        tags: bytearray,
        long_values: list[int],
        double_values: list[float],
        string_values: list[str],
    ) -> None:
        for raw_name, raw_value in props.items():
            self._encode_prop_into(
                str(raw_name),
                raw_value,
                names,
                tags,
                long_values,
                double_values,
                string_values,
            )

    @staticmethod
    def _encode_prop_into(
        name: str,
        raw_value: Any,
        names: list[str],
        tags: bytearray,
        long_values: list[int],
        double_values: list[float],
        string_values: list[str],
    ) -> None:
        names.append(name)

        # Scalar values are already JSON-compatible. Avoid recursive bridge
        # conversion and temporary containers on the overwhelmingly common
        # set_prop path.
        if raw_value is None:
            tags.append(_VALUE_NULL)
        elif isinstance(raw_value, bool):
            tags.append(_VALUE_BOOL)
            long_values.append(1 if raw_value else 0)
        elif (
            isinstance(raw_value, int)
            and -(1 << 63) <= raw_value < (1 << 63)
        ):
            tags.append(_VALUE_INT)
            long_values.append(raw_value)
        elif isinstance(raw_value, float):
            if not math.isfinite(raw_value):
                raise ValueError(f"Non-finite prop {name!r}")
            tags.append(_VALUE_FLOAT)
            double_values.append(raw_value)
        elif isinstance(raw_value, str):
            tags.append(_VALUE_STRING)
            string_values.append(raw_value)
        elif isinstance(raw_value, Mapping) or (
            isinstance(raw_value, Sequence)
            and not isinstance(raw_value, (str, bytes, bytearray))
        ):
            value = _to_json_compatible(raw_value)
            tags.append(_VALUE_JSON)
            string_values.append(
                json.dumps(value, separators=(",", ":"), allow_nan=False)
            )
        else:
            raise TypeError(
                f"Unsupported direct prop {name!r}: "
                f"{type(raw_value).__name__}"
            )
