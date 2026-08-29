# BizonVR v1.0.0

## Overview

BizonVR is a production-oriented Django commerce platform for VR equipment,
accessories, game packs, services, and manager-led order fulfillment.

## Highlights

- Django commerce platform for public storefront and internal operations.
- PostgreSQL-backed inventory and order workflow.
- Guest and authenticated checkout flows.
- Manager portal for deals, clients, inventory, reservations, shipments, finance, and documents.
- Reservations and shipment workflows with stock synchronization.
- Signed payment webhook protections.
- Authentication, password recovery, and email verification.
- CI and production configuration validation.

## Engineering

- Transaction boundaries built with `transaction.atomic()`.
- Targeted `select_for_update()` row locking for concurrency-sensitive state.
- Reservation rollback protection for strict inventory failures.
- Duplicate and regressive payment webhook protection.
- Shipment duplicate-consumption protection.
- One active PostgreSQL database contract.
- 778 automated tests across public and manager workflows.

## Portfolio Hardening

- Repository cleanup and removal of generated artifacts from tracking.
- Production configuration hardening.
- CI coverage for backend, frontend assets, and production checks.
- Architecture and local-development documentation.
- Portfolio screenshots for the public storefront flows.

## Known Trade-offs

- The application remains a modular monolith.
- Public payment is manager-led rather than an instant online payment flow.
- There is no background task queue; Redis and external integrations remain optional.
- No public hosted demo is currently available.
