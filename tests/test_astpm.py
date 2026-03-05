import json
from pathlib import Path

from astra.ast import ImportDecl
from astra.build import build
from astra.module_resolver import resolve_import_path
import astra.pkg


def _write_registry(path: Path, pkg_name: str, repo: str, version: str = "2.0.0") -> None:
    payload = {
        pkg_name: {
            "repo": repo,
            "description": f"{pkg_name} bindings",
            "version": version,
        }
    }
    path.write_text(json.dumps(payload))


def test_astpm_search_uses_registry(monkeypatch, tmp_path: Path, capsys):
    reg = tmp_path / "packages.json"
    _write_registry(reg, "sdl2", "https://example.invalid/astra-sdl2", "2.0.0")
    monkeypatch.setenv("ASTRA_REGISTRY_PATH", str(reg))

    astra.pkg.main(["search", "sdl2"])
    out = capsys.readouterr().out
    assert "sdl2 2.0.0" in out


def test_astpm_add_remove_cycle(monkeypatch, tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir()
    pkg_repo = tmp_path / "astra-sdl2"
    pkg_repo.mkdir()
    (pkg_repo / "Astra.toml").write_text(
        "[package]\nname = \"sdl2\"\nversion = \"2.0.0\"\n[native]\nlibs = [\"SDL2\"]\n"
    )
    (pkg_repo / "sdl2.astra").write_text('@link("SDL2") extern fn SDL_Init(flags: u32) -> i32;\n')

    reg = tmp_path / "packages.json"
    _write_registry(reg, "sdl2", str(pkg_repo), "2.0.0")
    monkeypatch.setenv("ASTRA_REGISTRY_PATH", str(reg))
    monkeypatch.setenv("ASTRA_PKG_HOME", str(tmp_path / "cache"))
    monkeypatch.chdir(project)

    astra.pkg.main(["init", "demo"])
    astra.pkg.main(["add", "sdl2"])
    manifest = (project / "Astra.toml").read_text()
    assert 'sdl2 = "2.0.0"' in manifest
    assert (tmp_path / "cache" / "sdl2" / "2.0.0" / "sdl2.astra").exists()

    astra.pkg.main(["remove", "sdl2"])
    manifest2 = (project / "Astra.toml").read_text()
    assert "sdl2" not in manifest2
    assert not (tmp_path / "cache" / "sdl2").exists()


def test_import_resolution_uses_installed_package_cache(monkeypatch, tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir(parents=True)
    cache = tmp_path / "cache"
    (project / "Astra.toml").write_text('name = "demo"\n[dependencies]\npkgdemo = "2.0.0"\n')
    (project / "main.astra").write_text('import "pkgdemo";\nfn main() -> Int { return 0; }\n')
    pkg_dir = cache / "pkgdemo" / "2.0.0"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "pkgdemo.astra").write_text('@link("pkgdemo") extern fn demo_init(flags: u32) -> i32;\n')
    monkeypatch.setenv("ASTRA_PKG_HOME", str(cache))

    resolved = resolve_import_path(ImportDecl(path=[], source="pkgdemo"), str(project / "main.astra"))
    assert resolved == (pkg_dir / "pkgdemo.astra").resolve()


def test_build_with_dependency_auto_adds_native_link_flags(monkeypatch, tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir(parents=True)
    cache = tmp_path / "cache"
    monkeypatch.setenv("ASTRA_PKG_HOME", str(cache))

    (project / "Astra.toml").write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\n[dependencies]\npkgdemo = "2.0.0"\n'
    )
    (project / "main.astra").write_text('import "pkgdemo";\nfn main() -> Int { return demo_init(0u32); }\n')

    pkg_dir = cache / "pkgdemo" / "2.0.0"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "Astra.toml").write_text(
        "[package]\nname = \"pkgdemo\"\nversion = \"2.0.0\"\n[native]\nlibs = [\"demoffi\"]\n"
    )
    (pkg_dir / "pkgdemo.astra").write_text('@link("demoffi") extern fn demo_init(flags: u32) -> i32;\n')

    seen_cmds: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True):
        seen_cmds.append(cmd)
        out_idx = cmd.index("-o") + 1 if "-o" in cmd else -1
        if out_idx > 0:
            Path(cmd[out_idx]).write_text("")
        class CP:
            returncode = 0
            stderr = ""
            stdout = ""
        return CP()

    monkeypatch.setattr("astra.build.shutil.which", lambda _: "/usr/bin/clang")
    monkeypatch.setattr("astra.build.subprocess.run", fake_run)

    out = project / "app"
    state = build(str(project / "main.astra"), str(out), "native")
    assert state in {"built", "cached"}
    assert any("-ldemoffi" in arg for cmd in seen_cmds for arg in cmd)
