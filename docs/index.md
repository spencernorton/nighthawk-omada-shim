# Nighthawk Omada Shim Documentation

This documentation describes the Netgear Nighthawk integration, Omada ECSP
protocol model, and software architecture used by Nighthawk Omada Shim.

## Guides

| Document | Purpose |
| --- | --- |
| [Operations](operations.md) | Netgear RS700/RS700S deployment, multi-AP isolation, observers, and rollback |
| [Configuration](configuration.md) | Environment variables and southbound options |
| [Protocol overview](protocol-overview.md) | High-level ECSP model and message families |
| [Wire format](ecsp-wire-format.md) | JSON envelope and 4-byte length framing |
| [Device lifecycle](device-lifecycle.md) | Discovery, adoption, authentication, sync, and reconnect |
| [Architecture](architecture.md) | Internal module boundaries and runtime data flow |
| [Protocol status](protocol-status.md) | Implemented and deferred message families |
| [Research methodology](research-methodology.md) | Evidence model and clean-room documentation rules |
| [Development](development.md) | Tests, style, and contributor workflow |

## Scope

The implementation pairs a conservative Omada ECSP V2 device agent (tested with
Omada Network Application 6.2 and 6.3) with a stock-firmware Netgear Nighthawk
southbound adapter. A message family is advertised as supported only when the
southbound can genuinely apply or observe it.

## Diagram language

Protocol and lifecycle documentation uses Mermaid `sequenceDiagram` blocks for
transport, direction, and message ordering, `flowchart` for static software
relationships, and `stateDiagram-v2` for internal lifecycle states.
