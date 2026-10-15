# Hardware inventory and compatibility import

Use `schemas/hardware_inventory.schema.json` (schema version 1) for JSON inventory imports. An inventory lists one row per physical CHARM slot and its terminal-block endpoint. Required properties are the destination IDs, `availability` (`available`, `reserved`, `unavailable`), `supported_io_types`, and compatibility facts. Compatibility facts may be `null` to mean unknown; unknown data never means compatible.

Example slot:

```json
{
  "slot_id": "CAB-A/CIOC-1/BP-1/CH-01",
  "cabinet": "CAB-A",
  "cioc": "CAB-A/CIOC-1",
  "baseplate": "CAB-A/CIOC-1/BP-1",
  "charm_slot": "CH-01",
  "terminal_block_id": "TB-1:01",
  "availability": "available",
  "supported_io_types": ["AI"],
  "charm_type": "ENGINEER-VERIFIED-TYPE",
  "terminal_block_type": "ENGINEER-VERIFIED-TB",
  "isolation": true,
  "fused": false,
  "injected_power": false,
  "physical_sequence": 1,
  "adjacency_domain": "CAB-A/CIOC-1/BP-1"
}
```

`source_authority` is an operator-declared provenance label (`synthetic`, `customer`, or `vendor_documented`); the software does not authenticate source documents or certify an inventory as vendor-authoritative. Include a traceable `source_reference`. A `vendor_documented` label is still an assertion that must be reviewed by the project engineer.

In YAML, attach the imported object at `hardware.inventory` and configure `compatibility.enabled: true`. Optional `require_*` switches make CHARM/TB/isolation/fusing/injected-power data mandatory for matching. Any supplied specific signal requirement is compared even if its `require_*` switch is false. Slots with `reserved` or `unavailable` status are never candidates.

## Cable-pair adjacency

This project has no vendor or organizer definition of cable-pair physical adjacency. The solver therefore does not interpret global generated slot indices as electrical adjacency. When `cable_pair_order` is enabled, the inventory must provide unique `physical_sequence` integers within each `adjacency_domain`; each consecutive sorted pair is constrained to the next sequence in the same domain. A boundary between domains cannot be crossed. This is a configurable generic interpretation, not a universal vendor requirement; obtain engineering approval before enabling it. Missing sequence/domain data yields TQs.

## Synthetic fixture

`sample_data/synthetic_test_inventory.json` exercises these fields and is explicitly synthetic. It contains no DeltaV part numbers, limits or vendor compatibility claims.
