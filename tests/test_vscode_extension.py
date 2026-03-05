import json
from pathlib import Path


def _pkg() -> dict:
    return json.loads(Path("editors/vscode/package.json").read_text())


def test_vscode_extension_has_marketplace_icon_and_language_icon():
    pkg = _pkg()
    assert pkg.get("icon") == "images/astra.png"
    lang = next(x for x in pkg["contributes"]["languages"] if x["id"] == "astra")
    assert lang["icon"]["light"] == "images/astra.png"
    assert lang["icon"]["dark"] == "images/astra.png"
    assert Path("editors/vscode/images/astra.png").exists()


def test_vscode_extension_scoped_editor_defaults_for_astra():
    pkg = _pkg()
    scoped = pkg["contributes"]["configurationDefaults"]["[astra]"]
    assert scoped["editor.tabSize"] == 4
    assert scoped["editor.insertSpaces"] is True
    assert scoped["editor.detectIndentation"] is False
    assert scoped["editor.rulers"] == [100]
    assert scoped["editor.fontLigatures"] is False
