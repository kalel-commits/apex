from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_frontend_renders_without_uploaded_inputs():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
    assert not app.exception
    assert any(element.value == "IO Signal Sudoku" for element in app.title)
    assert any("Signal list" in element.label for element in app.get("file_uploader"))
    assert any("allocation template" in element.label for element in app.get("file_uploader"))
