# AGENTS.md

## Project
BizonVR — сайт продажи VR-оборудования, аксессуаров, игровых паков и решений для бизнеса и физических лиц.

## Main business goal
Сайт должен продавать VR-оборудование, собирать заявки, показывать товары, игровые паки, услуги, подписки и решения для VR-клубов.



## What can be improved
- public website pages
- catalog
- product cards
- game packs
- VR club games section
- checkout
- header/navigation
- public lead forms
- admin panel configurability
- documentation
- dead/obsolete docs

## Rules
- Do not delete files immediately.
- First create a report with suggested deletions.
- Do not remove migrations.
- Do not edit .env or secrets.
- Do not change production settings without approval.
- Keep changes small and testable.
- Prefer admin-configurable content over hardcoded content.
- Preserve existing business logic unless it is clearly broken.
- Update README or docs only if needed.

## Validation
Before final report, run available checks:
- python manage.py check
- python manage.py test
- npm run build, if frontend build exists
- npm run lint, if lint exists

## Done means
- Public site works.
- Header works in all states.
- Game packs and games are visually polished.
- Important content is configurable through admin panel.
- Obsolete docs are listed or cleaned only after confirmation.
- Manager portal is untouched.