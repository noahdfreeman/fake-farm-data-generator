# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin lifecycle for Fake Farm Data Generator."""

from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication

from .complete_dialog import CompleteDatasetDialog
from .provider import FakeFarmDataGeneratorProvider


class FakeFarmDataGeneratorPlugin:
    """Register and unregister the Processing provider and launch action."""

    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.action = None
        self.dialog = None

    def initProcessing(self):
        if self.provider is None:
            self.provider = FakeFarmDataGeneratorProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        if self.iface is not None and self.action is None:
            icon = QIcon(
                str(
                    Path(__file__).parent
                    / "resources"
                    / "fake_farm_data_generator.png"
                )
            )
            self.action = QAction(
                icon,
                "Create Complete Fake Farm Dataset…",
                self.iface.mainWindow(),
            )
            self.action.setObjectName("fakeFarmDataGeneratorAction")
            self.action.setToolTip("Create clearly labeled fake farm datasets")
            self.action.triggered.connect(self.open_complete_dialog)
            self.iface.addPluginToMenu("Fake Farm Data Generator", self.action)
            self.iface.addToolBarIcon(self.action)

    def open_complete_dialog(self):
        self.dialog = CompleteDatasetDialog(self.iface)
        self.dialog.exec()

    def unload(self):
        if self.dialog is not None:
            self.dialog.shutdown()
            self.dialog.deleteLater()
            self.dialog = None
        if self.action is not None and self.iface is not None:
            self.iface.removePluginMenu("Fake Farm Data Generator", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
