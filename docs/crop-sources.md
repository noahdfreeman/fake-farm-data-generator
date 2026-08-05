---
layout: default
title: Crop lookup and privacy
---

# Crop lookup and privacy

The complete-run dialog uses the public USDA CroplandCROS ArcGIS image service.
Select **Pull Crops from USDA CDL** after choosing boundary layers and years.
The returned field-year crops appear in a table before generation.

Only a bounding rectangle is sent to the remote image service. Field polygon
geometry and input attributes are not uploaded. Downloaded subsets are temporary
and are removed when the lookup finishes. The complete-run interface has no
local-CDL, persistent-cache, or manual-profile controls.

The plugin calculates a class histogram inside each field and ignores
background/nonagricultural classes when selecting the dominant crop. Missing CDL
years are estimated from nearby API observations when a usable rotation pattern
exists. Every inferred row is labeled `rotation_inference`; it is never presented
as an observed CDL crop. A field-year remains unresolved and blocks generation
when neither an API observation nor rotation inference is available.

Crop identity is the only optional real-world classification used by v1. It
selects a fake crop profile and records provenance; it does not make generated
planting, application, soil, or yield values real or correlated.

Built-in profiles: Corn, Soybeans, Wheat, Cotton, Grain sorghum, Barley, Oats,
Canola, Dry beans, Sunflowers, Alfalfa, and Other Crop.
