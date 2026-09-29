from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from tass import dashboard


def test_dashboard_start_uses_entered_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "town.yaml").write_text("name: ui-test\n", encoding="utf-8")
    launched = []

    def fake_process(command, **kwargs):
        launched.append(command)
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(dashboard.subprocess, "Popen", fake_process)
    app = AppTest.from_file(str(Path(dashboard.__file__)), default_timeout=15).run()
    assert not app.exception
    app.sidebar.text_input[0].input("ui-check").run()
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert len(launched) == 1
    assert str(tmp_path / "runs" / "ui-check") in launched[0]
    assert app.session_state["selected_run"] == tmp_path / "runs" / "ui-check"
