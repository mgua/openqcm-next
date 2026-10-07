# -*- coding: utf-8 -*-
"""Sequence scheduler for openQCM NEXT.

The scheduler is intentionally independent from acquisition details.  MainWindow
implements the small adapter below and remains responsible for Worker lifecycle.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class OperationType(str, Enum):
    SINGLE = "Single Measurement"
    MULTISCAN = "Multiscan Measurement"
    PAUSE = "Pause"
    STOP = "Stop"


@dataclass
class SequenceOperation:
    operation_type: OperationType
    duration_s: float = 0.0
    overtones: List[int] = field(default_factory=list)
    temperature_c: Optional[float] = None

    def to_dict(self):
        return {
            "operation": self.operation_type.value,
            "duration_s": self.duration_s,
            "overtones": list(self.overtones),
            "temperature_c": self.temperature_c,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            OperationType(data["operation"]),
            float(data.get("duration_s", 0.0)),
            [int(x) for x in data.get("overtones", [])],
            None if data.get("temperature_c") is None else float(data["temperature_c"]),
        )

    def display(self):
        names = {0: "F0", 3: "F3", 5: "F5", 7: "F7", 9: "F9"}
        if self.operation_type == OperationType.SINGLE:
            ov = names.get(self.overtones[0], str(self.overtones[0])) if self.overtones else "F0"
            t = "" if self.temperature_c is None else ", T={} °C".format(self.temperature_c)
            return "Single Measurement ({}){}".format(ov, t)
        if self.operation_type == OperationType.MULTISCAN:
            ovs = ", ".join(names.get(x, str(x)) for x in self.overtones)
            t = "" if self.temperature_c is None else ", T={} °C".format(self.temperature_c)
            return "Multiscan Measurement ({}){}".format(ovs, t)
        if self.operation_type == OperationType.PAUSE:
            return "Pause"
        return "Stop"


class SequenceRunner:
    """State machine used by SequenceDialog.

    Timing is deliberately driven by QTimer in the dialog, never by sleep(),
    so the GUI remains responsive and Cancel remains immediate.
    """

    def __init__(self, adapter):
        self.adapter = adapter
        self.operations = []
        self.index = -1
        self.running = False
        self.cancelled = False

    def set_operations(self, operations):
        if self.running:
            raise RuntimeError("Sequence is running")
        self.operations = list(operations)

    def start(self):
        if not self.operations:
            raise ValueError("The sequence is empty")
        self.index = -1
        self.cancelled = False
        self.running = True
        return self.next_operation()

    def next_operation(self):
        if not self.running:
            return None
        self.index += 1
        if self.index >= len(self.operations):
            self.running = False
            return None

        op = self.operations[self.index]
        if op.operation_type == OperationType.STOP:
            self.adapter.stop_acquisition()
            self.running = False
            return op

        if op.operation_type == OperationType.SINGLE:
            self.adapter.start_single(op.overtones[0], op.temperature_c)
        elif op.operation_type == OperationType.MULTISCAN:
            self.adapter.start_multiscan(op.overtones, op.temperature_c)
        elif op.operation_type == OperationType.PAUSE:
            self.adapter.stop_acquisition()
        return op

    def finish_current(self):
        if not self.running:
            return None
        op = self.operations[self.index]
        if op.operation_type in (OperationType.SINGLE, OperationType.MULTISCAN):
            self.adapter.stop_acquisition()
        return self.next_operation()

    def cancel(self):
        self.cancelled = True
        self.running = False
        self.adapter.stop_acquisition()
