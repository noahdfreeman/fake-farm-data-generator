# SPDX-License-Identifier: GPL-3.0-or-later
"""Processing provider exposed by Fake Farm Data Generator."""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsProcessingProvider

from .algorithms.complete_dataset import CreateCompleteFakeFarmDatasetAlgorithm
from .algorithms.applications import CreateFakeApplicationsAlgorithm
from .algorithms.planting import CreateFakePlantingAlgorithm
from .algorithms.soil_tests import CreateFakeSoilTestsAlgorithm
from .algorithms.yield_data import CreateFakeYieldAlgorithm


class FakeFarmDataGeneratorProvider(QgsProcessingProvider):
    """Expose the complete-run tool and four data generators."""

    def id(self):
        return "fake_farm_data_generator"

    def name(self):
        return QCoreApplication.translate(
            "FakeFarmDataGeneratorProvider", "Fake Farm Data Generator"
        )

    def longName(self):
        return self.name()

    def loadAlgorithms(self):
        self.addAlgorithm(CreateCompleteFakeFarmDatasetAlgorithm())
        self.addAlgorithm(CreateFakeSoilTestsAlgorithm())
        self.addAlgorithm(CreateFakePlantingAlgorithm())
        self.addAlgorithm(CreateFakeApplicationsAlgorithm())
        self.addAlgorithm(CreateFakeYieldAlgorithm())
