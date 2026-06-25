# {{project_name}} Architecture Spec

Use this spec as the first project-specific map. Keep it short, factual, and easy to search.

## Project

- Project id: `{{project_id}}`
- Primary repository: `TODO`
- Runtime or framework: `TODO`
- Owners or review group: `TODO`

## Boundaries

Describe the main system boundaries and the code paths that implement them.

| Area | Purpose | Source paths |
| --- | --- | --- |
| Core domain | TODO | `src/**` |
| Interfaces | TODO | `api/**`, `ui/**` |
| Persistence | TODO | `db/**`, `migrations/**` |

## Architecture Rules

- ADRs are the authority for accepted decisions.
- UML diagrams describe the current intended structure.
- Specs hold setup, boundary, and source-area facts that support ADRs and diagrams.

## Open Questions

- Which source areas should be registered first?
- Which diagrams are required before the next architecture review?
- Which decisions are missing an ADR?
