from pathlib import Path
import time

import pytest

from astra.ast import ImportDecl
from astra.module_resolver import (
    ModuleResolutionError,
    discover_stdlib_modules,
    resolve_import_path,
    stdlib_latest_mtime,
)


def test_module_import_resolves_from_package_root(tmp_path: Path):
    root = tmp_path / "app"
    root.mkdir(parents=True)
    (root / "Astra.toml").write_text('name = "app"\n')
    (root / "lib").mkdir(parents=True)
    (root / "src").mkdir(parents=True)
    (root / "lib" / "math.arixa").write_text("fn id(x Int) Int{ return x; }\n")
    importer = root / "src" / "main.astra"
    importer.write_text("fn main() Int{ return 0; }\n")
    resolved = resolve_import_path(ImportDecl(path=["lib", "math"]), str(importer))
    assert resolved == (root / "lib" / "math.arixa").resolve()


def test_string_import_resolves_relative_to_importer(tmp_path: Path):
    root = tmp_path / "app"
    root.mkdir(parents=True)
    (root / "Astra.toml").write_text('name = "app"\n')
    (root / "src").mkdir(parents=True)
    (root / "helper.arixa").write_text("fn a() Int{ return 1; }\n")
    (root / "src" / "helper.arixa").write_text("fn b() Int{ return 2; }\n")
    importer = root / "src" / "main.astra"
    importer.write_text("fn main() Int{ return 0; }\n")
    resolved = resolve_import_path(ImportDecl(path=[], source="helper"), str(importer))
    assert resolved == (root / "src" / "helper.arixa").resolve()


def test_std_import_uses_configured_stdlib(monkeypatch, tmp_path: Path):
    stdlib = tmp_path / "custom_stdlib"
    (stdlib / "io").mkdir(parents=True)
    (stdlib / "io" / "fs.arixa").write_text("fn noop() Int{ return 0; }\n")
    monkeypatch.setenv("ASTRA_STDLIB_PATH", str(stdlib))
    resolved = resolve_import_path(ImportDecl(path=["std", "io", "fs"]), "<input>")
    assert resolved == (stdlib / "io" / "fs.arixa").resolve()


def test_missing_import_is_reported(tmp_path: Path):
    importer = tmp_path / "main.astra"
    importer.write_text("fn main() Int{ return 0; }\n")
    with pytest.raises(ModuleResolutionError, match="cannot resolve import missing.mod"):
        resolve_import_path(ImportDecl(path=["missing", "mod"]), str(importer))


def test_package_submodule_import_resolves_from_cache(monkeypatch, tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir(parents=True)
    cache = tmp_path / "cache"
    monkeypatch.setenv("ARIXA_PKG_HOME", str(cache))
    (project / "Astra.toml").write_text('[project]\nname = "app"\nversion = "0.1.0"\n[dependencies]\nsdl2 = "0.1.0"\n')
    importer = project / "src" / "main.astra"
    importer.parent.mkdir(parents=True)
    importer.write_text('import "sdl2/video";\nfn main() Int{ return 0; }\n')

    pkg_dir = cache / "sdl2" / "0.1.0" / "sdl2"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "video.arixa").write_text("fn noop() Int{ return 0; }\n")

    resolved = resolve_import_path(ImportDecl(path=[], source="sdl2/video"), str(importer))
    assert resolved == (pkg_dir / "video.arixa").resolve()


def test_stdlib_module_discovery_is_filesystem_driven(monkeypatch, tmp_path: Path):
    stdlib = tmp_path / "stdlib"
    (stdlib / "io").mkdir(parents=True)
    (stdlib / "io" / "fs.arixa").write_text("fn noop() Int { return 0; }\n")
    (stdlib / "core.arixa").write_text("fn base() Int { return 0; }\n")
    (stdlib / "bindings").mkdir()
    (stdlib / "bindings" / "ffi.arixa").write_text("fn ext() Int { return 0; }\n")
    monkeypatch.setenv("ASTRA_STDLIB_PATH", str(stdlib))

    with_bindings = discover_stdlib_modules(include_bindings=True)
    without_bindings = discover_stdlib_modules(include_bindings=False)
    assert "core" in with_bindings
    assert "io.fs" in with_bindings
    assert "bindings.ffi" in with_bindings
    assert "bindings.ffi" not in without_bindings


def test_stdlib_latest_mtime_updates_when_stdlib_changes(monkeypatch, tmp_path: Path):
    stdlib = tmp_path / "stdlib"
    stdlib.mkdir(parents=True)
    (stdlib / "core.arixa").write_text("fn base() Int { return 0; }\n")
    monkeypatch.setenv("ASTRA_STDLIB_PATH", str(stdlib))
    before = stdlib_latest_mtime()

    time.sleep(1.05)
    (stdlib / "future.arixa").write_text("fn add() Int { return 1; }\n")
    after = stdlib_latest_mtime()
    assert after > before
