# -*- coding: utf-8 -*-
"""GUI editor/executor for openQCM NEXT measurement sequences."""

import json

try:
    from PyQt5 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

from openQCM.core.sequence import (
    OperationType,
    SequenceOperation,
    SequenceRunner,
)


OVERTONES = [
    (0, "F0"),
    (3, "F3"),
    (5, "F5"),
    (7, "F7"),
    (9, "F9"),
]


class SequenceDialog(QtWidgets.QDialog):

    def __init__(self, adapter, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Measurement Sequence")
        self.resize(680, 620)

        self.runner = SequenceRunner(adapter)

        self._elapsed = QtCore.QElapsedTimer()
        self._duration_ms = 0

        self._waiting_for_temperature = False
        self._target_temperature = None

        self._build_ui()

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):

        root = QtWidgets.QVBoxLayout(self)

        # --------------------------------------------------------------
        # Title
        # --------------------------------------------------------------

        title = QtWidgets.QLabel("Measurement Sequence")
        title.setStyleSheet(
            "font-size:18px;font-weight:bold;"
        )
        root.addWidget(title)

        # --------------------------------------------------------------
        # Sequence table
        # --------------------------------------------------------------

        self.table = QtWidgets.QTableWidget(0, 6)

        self.table.setHorizontalHeaderLabels(
            [
                "#",
                "Operation",
                "Overtone(s)",
                "Temperature",
                "Duration",
                "Status",
            ]
        )

        # Hide vertical header
        self.table.verticalHeader().setVisible(False)

        # Table must NOT be editable
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )

        # Select complete row
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )

        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )

        # Requested column widths
        self.table.setColumnWidth(0, 20)
        self.table.setColumnWidth(1, 200)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 100)

        self.table.horizontalHeader().setStretchLastSection(True)

        root.addWidget(self.table, 1)

        # --------------------------------------------------------------
        # Operation form
        # --------------------------------------------------------------

        form = QtWidgets.QGridLayout()

        # Operation type
        self.type_combo = QtWidgets.QComboBox()

        self.type_combo.addItem(
            "Single Measurement",
            OperationType.SINGLE,
        )

        self.type_combo.addItem(
            "Multiscan Measurement",
            OperationType.MULTISCAN,
        )

        self.type_combo.addItem(
            "Pause",
            OperationType.PAUSE,
        )

        self.type_combo.addItem(
            "Stop",
            OperationType.STOP,
        )

        form.addWidget(
            QtWidgets.QLabel("Operation"),
            0,
            0,
        )

        form.addWidget(
            self.type_combo,
            0,
            1,
        )

        # --------------------------------------------------------------
        # Overtones
        # --------------------------------------------------------------

        self.ov_group = QtWidgets.QGroupBox("Overtone(s)")

        ovl = QtWidgets.QHBoxLayout(self.ov_group)

        self.ov_buttons = {}

        for value, label in OVERTONES:

            cb = QtWidgets.QCheckBox(label)

            self.ov_buttons[value] = cb

            ovl.addWidget(cb)

            # Used to enforce one overtone for Single Measurement
            cb.toggled.connect(
                lambda checked, v=value:
                self._single_overtone_changed(v, checked)
            )

        form.addWidget(
            self.ov_group,
            0,
            2,
            1,
            3,
        )

        # --------------------------------------------------------------
        # Target temperature
        # --------------------------------------------------------------

        self.use_temp = QtWidgets.QCheckBox(
            "Use target temperature"
        )

        self.use_temp.setChecked(False)

        form.addWidget(
            self.use_temp,
            1,
            0,
        )

        self.temp = QtWidgets.QDoubleSpinBox()

        self.temp.setRange(
            -50,
            150,
        )

        self.temp.setDecimals(2)

        self.temp.setSuffix(" °C")

        self.temp.setValue(25)

        self.temp.setEnabled(False)

        form.addWidget(
            self.temp,
            1,
            1,
        )

        # --------------------------------------------------------------
        # Duration
        # --------------------------------------------------------------

        self.duration = QtWidgets.QDoubleSpinBox()

        self.duration.setRange(
            0.1,
            86400,
        )

        self.duration.setDecimals(1)

        self.duration.setSuffix(" s")

        self.duration.setValue(60)

        form.addWidget(
            QtWidgets.QLabel("Duration"),
            1,
            2,
        )

        form.addWidget(
            self.duration,
            1,
            3,
        )

        root.addLayout(form)

        # --------------------------------------------------------------
        # Buttons
        # --------------------------------------------------------------

        edit = QtWidgets.QHBoxLayout()

        buttons = [
            ("Add", self._add),
            ("Remove", self._remove),
            ("↑", lambda: self._move(-1)),
            ("↓", lambda: self._move(1)),
        ]

        for text, slot in buttons:

            button = QtWidgets.QPushButton(text)

            button.clicked.connect(slot)

            attribute_name = (
                "_"
                + text.replace("↑", "up")
                .replace("↓", "down")
                .lower()
                + "_btn"
            )

            setattr(
                self,
                attribute_name,
                button,
            )

            edit.addWidget(button)

        # --------------------------------------------------------------
        # JSON buttons
        # --------------------------------------------------------------

        save_btn = QtWidgets.QPushButton(
            "Save JSON"
        )

        load_btn = QtWidgets.QPushButton(
            "Load JSON"
        )

        save_btn.clicked.connect(
            self.save_json
        )

        load_btn.clicked.connect(
            self.load_json
        )

        self._save_btn = save_btn
        self._load_btn = load_btn

        edit.addWidget(save_btn)
        edit.addWidget(load_btn)

        edit.addStretch(1)

        # --------------------------------------------------------------
        # Start / Cancel
        # --------------------------------------------------------------

        self.start_btn = QtWidgets.QPushButton(
            "Start Sequence"
        )

        self.cancel_btn = QtWidgets.QPushButton(
            "Cancel Sequence"
        )

        self.cancel_btn.setEnabled(False)

        self.start_btn.clicked.connect(
            self.start_sequence
        )

        self.cancel_btn.clicked.connect(
            self.cancel_sequence
        )

        edit.addWidget(
            self.start_btn
        )

        edit.addWidget(
            self.cancel_btn
        )

        root.addLayout(edit)

        # --------------------------------------------------------------
        # Status / progress
        # --------------------------------------------------------------

        self.status = QtWidgets.QLabel(
            "Ready"
        )

        self.progress = QtWidgets.QProgressBar()

        self.progress.setRange(
            0,
            100,
        )

        root.addWidget(
            self.status
        )

        root.addWidget(
            self.progress
        )

        # --------------------------------------------------------------
        # Signals
        # --------------------------------------------------------------

        self.type_combo.currentIndexChanged.connect(
            self._type_changed
        )

        self.use_temp.toggled.connect(
            self._temperature_option_changed
        )

        self._type_changed()

    # ------------------------------------------------------------------
    # Overtone handling
    # ------------------------------------------------------------------

    def _single_overtone_changed(
        self,
        value,
        checked,
    ):
        """
        Single Measurement allows exactly one overtone.

        Multiscan allows multiple overtones.
        """

        if not checked:
            return

        if self.type_combo.currentData() != OperationType.SINGLE:
            return

        # Deselect all other overtones
        for other_value, cb in self.ov_buttons.items():

            if other_value == value:
                continue

            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)

    # ------------------------------------------------------------------
    # Operation type
    # ------------------------------------------------------------------

    def _type_changed(self):

        typ = self.type_combo.currentData()

        measurement = typ in (
            OperationType.SINGLE,
            OperationType.MULTISCAN,
        )

        self.ov_group.setEnabled(
            measurement
        )

        self.use_temp.setEnabled(
            measurement
        )

        self.temp.setEnabled(
            measurement
            and self.use_temp.isChecked()
        )

        # All overtones are available for both
        # Single and Multiscan.
        for cb in self.ov_buttons.values():
            cb.setEnabled(measurement)

        # --------------------------------------------------------------
        # Single Measurement
        # --------------------------------------------------------------

        if typ == OperationType.SINGLE:

            checked = [
                value
                for value, cb in self.ov_buttons.items()
                if cb.isChecked()
            ]

            # Default to F0
            if not checked:

                self.ov_buttons[0].setChecked(
                    True
                )

            # Make sure only one is selected
            elif len(checked) > 1:

                first = checked[0]

                for value, cb in self.ov_buttons.items():

                    if value != first:

                        cb.blockSignals(True)

                        cb.setChecked(
                            False
                        )

                        cb.blockSignals(False)

        # --------------------------------------------------------------
        # Multiscan Measurement
        # --------------------------------------------------------------

        elif typ == OperationType.MULTISCAN:

            if not any(
                cb.isChecked()
                for cb in self.ov_buttons.values()
            ):

                # Default: all overtones
                for cb in self.ov_buttons.values():
                    cb.setChecked(True)

        # --------------------------------------------------------------
        # Pause / Stop
        # --------------------------------------------------------------

        elif typ in (
            OperationType.PAUSE,
            OperationType.STOP,
        ):

            for cb in self.ov_buttons.values():
                cb.setChecked(False)

        # Stop has no duration
        self.duration.setEnabled(
            typ != OperationType.STOP
        )

    # ------------------------------------------------------------------
    # Temperature
    # ------------------------------------------------------------------

    def _temperature_option_changed(
        self,
        checked,
    ):

        measurement = self.type_combo.currentData() in (
            OperationType.SINGLE,
            OperationType.MULTISCAN,
        )

        self.temp.setEnabled(
            checked and measurement
        )

    # ------------------------------------------------------------------
    # Read form
    # ------------------------------------------------------------------

    def _read_form(self):

        typ = self.type_combo.currentData()

        overtones = [
            value
            for value, cb in self.ov_buttons.items()
            if cb.isChecked()
        ]

        # Single = exactly one overtone
        if typ == OperationType.SINGLE:

            if not overtones:
                overtones = [0]

            overtones = [
                overtones[0]
            ]

        # Multiscan = at least one overtone
        elif typ == OperationType.MULTISCAN:

            if not overtones:
                raise ValueError(
                    "Select at least one overtone"
                )

        # Temperature is optional
        temperature = None

        if (
            typ in (
                OperationType.SINGLE,
                OperationType.MULTISCAN,
            )
            and self.use_temp.isChecked()
        ):

            temperature = self.temp.value()

        duration = (
            0
            if typ == OperationType.STOP
            else self.duration.value()
        )

        return SequenceOperation(
            typ,
            duration,
            overtones,
            temperature,
        )

    # ------------------------------------------------------------------
    # Set form
    # ------------------------------------------------------------------

    def _set_form(self, op):

        index = self.type_combo.findData(
            op.operation_type
        )

        self.type_combo.setCurrentIndex(
            index
        )

        for value, cb in self.ov_buttons.items():

            cb.blockSignals(True)

            cb.setChecked(
                value in op.overtones
            )

            cb.blockSignals(False)

        self.use_temp.setChecked(
            op.temperature_c is not None
        )

        if op.temperature_c is not None:

            self.temp.setValue(
                op.temperature_c
            )

        if op.operation_type != OperationType.STOP:

            self.duration.setValue(
                op.duration_s
            )

        self._type_changed()

    # ------------------------------------------------------------------
    # Refresh table
    # ------------------------------------------------------------------

    def _refresh(self, select=-1):

        self.table.setRowCount(0)

        for n, op in enumerate(
            self.runner.operations,
            1,
        ):

            self.table.insertRow(
                n - 1
            )

            values = [
                str(n),

                op.operation_type.value,

                ", ".join(
                    "F{}".format(x)
                    for x in op.overtones
                ) or "—",

                (
                    "—"
                    if op.temperature_c is None
                    else "{} °C".format(
                        op.temperature_c
                    )
                ),

                (
                    "—"
                    if op.operation_type
                    == OperationType.STOP
                    else "{} s".format(
                        op.duration_s
                    )
                ),

                "",
            ]

            for c, value in enumerate(values):

                item = QtWidgets.QTableWidgetItem(
                    value
                )

                # Explicitly make every table cell read-only
                item.setFlags(
                    item.flags()
                    & ~QtCore.Qt.ItemIsEditable
                )

                self.table.setItem(
                    n - 1,
                    c,
                    item,
                )

        if (
            0 <= select
            < self.table.rowCount()
        ):

            self.table.selectRow(
                select
            )

    # ------------------------------------------------------------------
    # Add
    # ------------------------------------------------------------------

    def _add(self):

        try:

            operation = self._read_form()

            self.runner.operations.append(
                operation
            )

            self._refresh(
                len(self.runner.operations) - 1
            )

        except ValueError as e:

            QtWidgets.QMessageBox.warning(
                self,
                "Invalid operation",
                str(e),
            )

    # ------------------------------------------------------------------
    # Remove
    # ------------------------------------------------------------------

    def _remove(self):

        row = self.table.currentRow()

        if row < 0:
            return

        self.runner.operations.pop(
            row
        )

        self._refresh(
            min(
                row,
                len(self.runner.operations) - 1,
            )
        )

    # ------------------------------------------------------------------
    # Move operation
    # ------------------------------------------------------------------

    def _move(self, delta):

        row = self.table.currentRow()

        new = row + delta

        if (
            row < 0
            or new < 0
            or new >= len(self.runner.operations)
        ):
            return

        operations = self.runner.operations

        operations[row], operations[new] = (
            operations[new],
            operations[row],
        )

        self._refresh(
            new
        )

    # ------------------------------------------------------------------
    # Highlight current operation
    # ------------------------------------------------------------------

    def _highlight(self, row):

        self.table.selectRow(
            row
        )

        for r in range(
            self.table.rowCount()
        ):

            for c in range(
                self.table.columnCount()
            ):

                item = self.table.item(
                    r,
                    c,
                )

                if item:

                    item.setBackground(
                        QtCore.Qt.yellow
                        if r == row
                        else QtCore.Qt.white
                    )

        for r in range(
            self.table.rowCount()
        ):

            self.table.item(
                r,
                5,
            ).setText("")

        if (
            0 <= row
            < self.table.rowCount()
        ):

            self.table.item(
                row,
                5,
            ).setText(
                "RUNNING"
            )

    # ------------------------------------------------------------------
    # Save JSON
    # ------------------------------------------------------------------

    def save_json(self):

        if self.runner.running:
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save measurement sequence",
            "",
            "JSON files (*.json)",
        )

        if not path:
            return

        if not path.lower().endswith(
            ".json"
        ):

            path += ".json"

        data = {
            "format":
                "openQCM NEXT measurement sequence",

            "version":
                1,

            "operations": [
                operation.to_dict()
                for operation in self.runner.operations
            ],
        }

        try:

            with open(
                path,
                "w",
                encoding="utf-8",
            ) as f:

                json.dump(
                    data,
                    f,
                    indent=2,
                    ensure_ascii=False,
                )

            self.status.setText(
                "Sequence saved: {}".format(
                    path
                )
            )

        except (
            OSError,
            TypeError,
            ValueError,
        ) as e:

            QtWidgets.QMessageBox.critical(
                self,
                "Save error",
                str(e),
            )

    # ------------------------------------------------------------------
    # Load JSON
    # ------------------------------------------------------------------

    def load_json(self):

        if self.runner.running:
            return

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load measurement sequence",
            "",
            "JSON files (*.json)",
        )

        if not path:
            return

        try:

            with open(
                path,
                "r",
                encoding="utf-8",
            ) as f:

                data = json.load(f)

            raw_operations = (
                data.get("operations")
                if isinstance(data, dict)
                else data
            )

            if not isinstance(
                raw_operations,
                list,
            ):

                raise ValueError(
                    "Invalid JSON: "
                    "'operations' must be a list."
                )

            operations = [
                SequenceOperation.from_dict(
                    item
                )
                for item in raw_operations
            ]

            for operation in operations:

                if (
                    operation.operation_type
                    == OperationType.MULTISCAN
                    and not operation.overtones
                ):

                    raise ValueError(
                        "Multiscan operation "
                        "without overtones."
                    )

                if (
                    operation.operation_type
                    == OperationType.SINGLE
                    and not operation.overtones
                ):

                    operation.overtones = [0]

                # Single must always contain
                # exactly one overtone.
                if (
                    operation.operation_type
                    == OperationType.SINGLE
                    and len(operation.overtones) > 1
                ):

                    operation.overtones = [
                        operation.overtones[0]
                    ]

            self.runner.set_operations(
                operations
            )

            self._refresh()

            self.status.setText(
                "Sequence loaded: {}".format(
                    path
                )
            )

        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ) as e:

            QtWidgets.QMessageBox.critical(
                self,
                "Load error",
                str(e),
            )

    # ------------------------------------------------------------------
    # Start sequence
    # ------------------------------------------------------------------

    def start_sequence(self):

        if not self.runner.operations:

            QtWidgets.QMessageBox.warning(
                self,
                "Sequence",
                "The sequence is empty.",
            )

            return

        self._set_edit_enabled(
            False
        )

        try:

            operation = self.runner.start()

        except Exception as e:

            self._set_edit_enabled(
                True
            )

            QtWidgets.QMessageBox.critical(
                self,
                "Sequence error",
                str(e),
            )

            return

        if operation is None:

            self._finished()

            return

        self._begin_operation(
            operation
        )

    # ------------------------------------------------------------------
    # Begin operation
    # ------------------------------------------------------------------

    def _begin_operation(
        self,
        operation,
    ):

        row = self.runner.index

        self._highlight(
            row
        )

        self._duration_ms = int(
            operation.duration_s * 1000
        )

        self._target_temperature = (
            operation.temperature_c
        )

        self._waiting_for_temperature = (
            operation.operation_type
            in (
                OperationType.SINGLE,
                OperationType.MULTISCAN,
            )
            and operation.temperature_c is not None
            and hasattr(
                self.runner.adapter,
                "temperature_reached",
            )
        )

        self._elapsed.restart()

        self.progress.setValue(
            0
        )

        # --------------------------------------------------------------
        # STOP
        # --------------------------------------------------------------

        if (
            operation.operation_type
            == OperationType.STOP
        ):

            self.status.setText(
                "STOP"
            )

            self._finished()

            return

        # --------------------------------------------------------------
        # Temperature wait
        # --------------------------------------------------------------

        if self._waiting_for_temperature:

            self.status.setText(
                "{}/{} — {} — waiting for {:.2f} °C".format(
                    row + 1,
                    len(self.runner.operations),
                    operation.display(),
                    operation.temperature_c,
                )
            )

        else:

            self.status.setText(
                "{}/{} — {}".format(
                    row + 1,
                    len(self.runner.operations),
                    operation.display(),
                )
            )

        self._timer.start()

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------

    def _tick(self):

        if not self.runner.running:

            self._timer.stop()

            return

        # --------------------------------------------------------------
        # Wait for temperature
        # --------------------------------------------------------------

        if self._waiting_for_temperature:

            try:

                ready = (
                    self.runner.adapter.temperature_reached(
                        self._target_temperature
                    )
                )

            except Exception:

                ready = False

            if not ready:

                self.status.setText(
                    "{}/{} — waiting for {:.2f} °C".format(
                        self.runner.index + 1,
                        len(self.runner.operations),
                        self._target_temperature,
                    )
                )

                return

            # Temperature reached
            self._waiting_for_temperature = False

            self._elapsed.restart()

            self.status.setText(
                "{}/{} — {}".format(
                    self.runner.index + 1,
                    len(self.runner.operations),
                    self.runner.operations[
                        self.runner.index
                    ].display(),
                )
            )

        # --------------------------------------------------------------
        # Duration
        # --------------------------------------------------------------

        elapsed = self._elapsed.elapsed()

        if self._duration_ms <= 0:

            percentage = 100

        else:

            percentage = min(
                100,
                int(
                    elapsed
                    * 100
                    / self._duration_ms
                ),
            )

        self.progress.setValue(
            percentage
        )

        if elapsed >= self._duration_ms:

            self._timer.stop()

            operation = (
                self.runner.finish_current()
            )

            if operation is None:

                self._finished()

            else:

                self._begin_operation(
                    operation
                )

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    def cancel_sequence(self):

        self._timer.stop()

        self.runner.cancel()

        self.status.setText(
            "Sequence cancelled"
        )

        self.progress.setValue(
            0
        )

        self._set_edit_enabled(
            True
        )

        self._clear_highlight()

    # ------------------------------------------------------------------
    # Finished
    # ------------------------------------------------------------------

    def _finished(self):

        self._timer.stop()

        self.progress.setValue(
            100
        )

        self.status.setText(
            "Sequence completed"
        )

        self._set_edit_enabled(
            True
        )

        self._clear_highlight()

    # ------------------------------------------------------------------
    # Clear highlight
    # ------------------------------------------------------------------

    def _clear_highlight(self):

        for r in range(
            self.table.rowCount()
        ):

            for c in range(
                self.table.columnCount()
            ):

                item = self.table.item(
                    r,
                    c,
                )

                if item:

                    item.setBackground(
                        QtCore.Qt.white
                    )

            self.table.item(
                r,
                5,
            ).setText("")

    # ------------------------------------------------------------------
    # Enable / disable editing controls
    # ------------------------------------------------------------------

    def _set_edit_enabled(
        self,
        enabled,
    ):

        for name in (
            "_add_btn",
            "_remove_btn",
            "_up_btn",
            "_down_btn",
            "_save_btn",
            "_load_btn",
        ):

            getattr(
                self,
                name,
            ).setEnabled(
                enabled
            )

        self.type_combo.setEnabled(
            enabled
        )

        self.ov_group.setEnabled(
            enabled
            and self.type_combo.currentData()
            in (
                OperationType.SINGLE,
                OperationType.MULTISCAN,
            )
        )

        self.use_temp.setEnabled(
            enabled
            and self.type_combo.currentData()
            in (
                OperationType.SINGLE,
                OperationType.MULTISCAN,
            )
        )

        self.temp.setEnabled(
            enabled
            and self.use_temp.isChecked()
            and self.type_combo.currentData()
            in (
                OperationType.SINGLE,
                OperationType.MULTISCAN,
            )
        )

        self.duration.setEnabled(
            enabled
            and self.type_combo.currentData()
            != OperationType.STOP
        )

        self.start_btn.setEnabled(
            enabled
        )

        self.cancel_btn.setEnabled(
            not enabled
        )

        # The table remains selectable but never editable.
        self.table.setEnabled(
            True
        )