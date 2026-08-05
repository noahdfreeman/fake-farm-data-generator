# SPDX-License-Identifier: GPL-3.0-or-later
"""QGIS entry point for Fake Farm Data Generator."""


def classFactory(iface):
    """Return the plugin instance expected by QGIS."""

    from .plugin import FakeFarmDataGeneratorPlugin

    return FakeFarmDataGeneratorPlugin(iface)
