import pandas as pd
import pytest
from io import BytesIO
from openpyxl import Workbook
from src.ingestion import normalize_columns, load_input

class NamedBytesIO(BytesIO):
    def __init__(self, data, name):
        super().__init__(data); self.name=name

def test_alias_mapping():
    result = normalize_columns(pd.DataFrame({"Tag Name": ["T-1"], "I/O": ["AI"], "Grp": ["G1"]}))
    assert result.loc[0, "tag"] == "T-1"
    assert result.loc[0, "io_type"] == "AI"
    assert result.loc[0, "group"] == "G1"

def test_duplicate_tags_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        normalize_columns(pd.DataFrame({"Tag": ["T-1", "T-1"]}))

def test_loader_detects_duplicate_source_headers_csv_and_excel():
    with pytest.raises(ValueError,match="Ambiguous mapping"):
        load_input(NamedBytesIO(b"Tag,Tag Name,IO\nT1,T1,AI\n","bad.csv"))
    wb=Workbook(); ws=wb.active; ws.append(["Tag","Tag","IO"]); ws.append(["T1","T1","AI"])
    b=BytesIO(); wb.save(b)
    with pytest.raises(ValueError,match="Duplicate input header"):
        load_input(NamedBytesIO(b.getvalue(),"bad.xlsx"))
    with pytest.raises(ValueError,match="Duplicate input header"):
        load_input(NamedBytesIO(b"Tag,Tag,IO\nT1,T1,AI\n","dupe.csv"))

def test_loader_explicit_mapping_and_sheet_selection():
    wb=Workbook(); first=wb.active; first.title="Cover"; first.append(["Notes"]); first.append(["skip"])
    data=wb.create_sheet("MDB"); data.append(["Customer Point","Signal Category"]); data.append(["T-9","AI"])
    b=BytesIO(); wb.save(b)
    result=load_input(NamedBytesIO(b.getvalue(),"signals.xlsx"),mapping={"Customer Point":"tag","Signal Category":"io_type"},sheet_name="MDB")
    assert result.loc[0,"tag"]=="T-9" and result.loc[0,"io_type"]=="AI"

def test_loader_accepts_pathlib_and_string_paths():
    result=load_input("sample_data/sample_signals.xlsx")
    assert len(result)==6 and result.tag.notna().all()
