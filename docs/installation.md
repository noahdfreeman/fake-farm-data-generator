---
layout: default
title: Installation
---

# Installation

## Requirements

- QGIS 3.28 or newer. QGIS 3.34, 3.40, 3.44, and 4.2 are currently live-tested.
- Windows, macOS, or Linux.
- No paid API, external Python package, or account is required.
- Internet access is optional. It is used only for automatic USDA crop lookup
  and online basemap tiles.

## Install the release ZIP

1. Download `fake_farm_data_generator-<version>.zip` from the GitHub release.
2. In QGIS, open **Plugins → Manage and Install Plugins**.
3. Select **Install from ZIP**.
4. Choose the downloaded ZIP, acknowledge the third-party plugin warning, and
   select **Install Plugin**.
5. Restart QGIS if replacing an earlier development build.

After installation, **Fake Farm Data Generator** appears in the Processing
Toolbox. The complete workflow also appears in the plugin menu and toolbar.

## Verify the installation

Search the Processing Toolbox for these five entries:

1. Create Complete Fake Farm Dataset
2. Create Fake Soil Test Data
3. Create Fake Planting Data
4. Create Fake As-Applied Data
5. Create Fake Yield Data

If the provider is missing, confirm that the ZIP contains one top-level folder
named `fake_farm_data_generator`, then restart QGIS and inspect the QGIS log
panel for a Python/plugin error.

## Updating

Install the newer ZIP through **Install from ZIP**. Saved JSON recipes retain
their settings, but review the changelog before reusing a recipe across major
versions. Generated data does not need the plugin to remain installed.
