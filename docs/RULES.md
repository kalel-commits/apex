# Configuration and rule semantics

`rules.yaml` is YAML, schema version `1`. Parsing uses `yaml.safe_load`; arbitrary code execution is not supported. `src/rules.py` rejects unknown rule types and invalid values. Each rule has a unique `id`, supported `type`, optional `enabled` boolean, and hard `severity` (the solver does not soften mandatory rules).

## Supported rule types

| Type | Semantics | Required evidence / limits |
|---|---|---|
| `spare_capacity` | Maximum occupied slots is `floor(capacity × (1 − minimum_percent/100))` at the requested scope. | `basis` is `physical` or `available`. For non-global scopes, enforced separately per cabinet/CIOC/baseplate. Compatible capacity is not separately calculated. |
| `group_together` | All nonblank values of `group_by` must have the same configured hierarchy key. | Set `level` to `cabinet`, `cioc`, or `baseplate`; this is exact co-location at that level, not proximity. |
| `separation` | Signals with a common nonblank group and explicit A/B side may not share the same configured hierarchy key. | `group_by`, `side_by`, and `level` are configurable; missing/inconsistent group-side records become TQs. No tag-name inference. |
| `cable_pair_order` | Within each cable, consecutive sorted pair numbers must occupy consecutive positions in one explicitly declared adjacency domain. | Requires unique numeric pair numbers, inventory `physical_sequence` and `adjacency_domain`. This generic semantics must be approved against the project's cable schedule. |

Rule configuration does not add new compiler code for changing a supported rule's fields or scope. A genuinely new rule type needs a reviewed validator and solver implementation.

## Optimization

`optimization.time_limit_seconds`, `num_search_workers`, `random_seed`, `preserve_previous_assignments`, `move_penalty` and `move_costs` configure CP-SAT. Previous slot assignment is a soft objective; hard rules always take precedence. Lifecycle weights are user-provided relative points, not monetary engineering-cost estimates. The revision report marks movement necessity as unproven unless additional diagnosis is implemented.

## Spare capacity

Reserve uses a floor for the maximum occupied count at each scope. With a 2-slot cabinet and 25% reserve, the maximum is `floor(1.5)=1`; a fractional slot is not treated as a spare. `physical` counts all inventory positions; `available` counts positions marked available. It does not currently reduce usable capacity by signal-specific compatibility, so use caution with heterogeneous inventory.

## Compatibility

See `docs/HARDWARE_INVENTORY.md`. Explicit compatibility checks can filter candidates by supported I/O types, CHARM/TB type and supplied requirement flags. Unknown fields remain unresolved; they are not assumed compatible. Synthetic fixture compatibility validates the code path only.
