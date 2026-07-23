---
status: accepted
title: Sample Architecture
---

# Sample Architecture

This preamble must also survive the structured round trip.

## 1. Introduction

This SAD documents a sample system for round-trip verification.

## 5. Building Block View

The system has a core service and a CLI surface.

## 9. Decisions

| ID | Title | Status |
| --- | --- | --- |
| D1 | Prefer structured export | Accepted |
| D2 | Keep UML export separate | Accepted |
| D-SoR | Preserve decision identity | Accepted |

### D1: Prefer structured export

**Status:** Accepted

Reassemble architecture.md from sad_section and sad_decision items.

### D2: Keep UML export separate

**Status:** Accepted

Delegate diagram files to UMLService.export_diagrams.

### D-SoR: Preserve decision identity

**Status:** Accepted

Keep mixed-case decision identifiers and their source order.

## 12. Glossary

SAD: Software Architecture Document.
