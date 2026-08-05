---
layout: default
title: Individual Processing tools
---

# Individual Processing tools

All four generators work from the QGIS Processing Toolbox, `qgis_process`,
Processing models, and Python.

## Soil tests

Creates scheduled sample points using a rotated regular grid or deterministic
random placement. Attributed mode includes the full fake nutrient profile.
Unattributed mode creates locations only and disables interpolation. Optional
polygon-grid surfaces use IDW or ordinary kriging with spherical, exponential,
or Gaussian variograms.

## Planting

Creates planter-center points, row-unit points, or both. Pass direction can be
derived from the field's longest oriented axis or entered manually. Row-unit
records link to their center record and retain pass, row, section, timestamp,
speed, population, seed spacing, seed depth, and headland state.

## As-applied

Creates one application operation per tool invocation. Supported categories are
dry fertilizer, liquid fertilizer, lime, chemical spraying, manure, and
broadcast seeding. Flat rate represents one target setting with bounded logged
variation; variable rate adds an independent smooth fake target pattern.

## Yield

Creates combine-style points and an optional clipped polygon grid. Twelve crop
profiles supply starting yield and moisture defaults. Output includes dry and
wet yield, moisture, speed, swath, pass, timestamp, headland state, and explicit
crop provenance.

Each tool writes a run manifest, fake-data README, optional derivatives, and a
portable HTML review using the same rules as the complete workflow.
