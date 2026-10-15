# Allocation workbook template adapter

No organizer/customer allocation workbook was present in this repository during the implementation audit. The current `.xlsx` fixtures contain synthetic signal inputs; they are not an allocation template. Therefore, official workbook compatibility is **not verified**.

The frontend accepts an optional `.xlsx` template. Configure a mapping in the rules YAML and upload that workbook in **Input & inventory**:

```yaml
reporting:
  template_mapping:
    sheet_name: Allocation
    header_row: 1
    data_start_row: 2
    columns:
      "Signal Tag": tag
      "I/O Type": io_type
      "Cabinet": cabinet
      "CHARM Slot": charm_slot
      "Terminal Block": terminal_block_id
```

`columns` maps exact template header labels to fields in the allocation dataframe. Header matching ignores case and surrounding whitespace. The adapter fills only mapped cells, preserves the workbook's sheets and styles, and translates formulas from the template's first data row into added rows where possible. Mapping errors are reported rather than guessed.

The **full Excel report** remains available separately and includes allocation, unallocated signals, TQs, grouped TQ causes, validation, cabinet utilization, metadata, summary, and revision comparison when present. The mapped template download fills the configured allocation sheet; it does not claim that the external template's formulas, macros, validations, or required supplementary sheets are correct until tested against the actual organizer workbook.

Before presentation, obtain the official template and verify the worksheet names, headers, row offsets, formulas, formatting, and any mandatory side sheets. Add a fixture copied from that authorized template and a round-trip test before claiming compatibility.
