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


def _write_multi_registry(path: Path, pkg_name: str, repos_by_version: dict[str, str]) -> None:
    payload = {
        pkg_name: {
            "description": f"{pkg_name} bindings",
            "versions": {ver: {"repo": repo, "checksum": f"sha256:{ver.replace('.', '')}"} for ver, repo in repos_by_version.items()},
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


def test_astpm_fetch_registry_uses_cache_fallback(monkeypatch, tmp_path: Path):
    cache_file = tmp_path / "registry-cache.json"
    cache_file.write_text(
        json.dumps({"cached_pkg": {"repo": "https://example.invalid/repo", "version": "1.0.0"}})
    )
    monkeypatch.setenv("ASTRA_REGISTRY_CACHE", str(cache_file))
    monkeypatch.setenv("ASTRA_REGISTRY_URL", "http://127.0.0.1:9/registry.json")
    monkeypatch.delenv("ASTRA_REGISTRY_PATH", raising=False)

    data = astra.pkg._fetch_registry()
    assert "cached_pkg" in data


def test_astpm_lock_resolves_semver_constraints(monkeypatch, tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir(parents=True)
    monkeypatch.chdir(project)
    monkeypatch.setenv("ARIXA_PKG_HOME", str(tmp_path / "cache"))

    pkg_v1 = tmp_path / "pkgdemo-v1"
    pkg_v1.mkdir()
    (pkg_v1 / "pkgdemo.arixa").write_text("fn v() Int{ return 1; }\n")
    pkg_v2 = tmp_path / "pkgdemo-v2"
    pkg_v2.mkdir()
    (pkg_v2 / "pkgdemo.arixa").write_text("fn v() Int{ return 2; }\n")

    reg = tmp_path / "packages.json"
    _write_multi_registry(reg, "pkgdemo", {"1.2.0": str(pkg_v1), "1.9.3": str(pkg_v2), "2.1.0": str(pkg_v2)})
    monkeypatch.setenv("ASTRA_REGISTRY_PATH", str(reg))

    astra.pkg.main(["init", "demo"])
    astra.pkg.main(["add", "pkgdemo", "^1.0.0"])

    lock = json.loads((project / "Astra.lock").read_text())
    assert lock["packages"]["pkgdemo"]["constraint"] == "^1.0.0"
    assert lock["packages"]["pkgdemo"]["version"] == "1.9.3"
    assert lock["packages"]["pkgdemo"]["source"] == str(pkg_v2)
    assert lock["packages"]["pkgdemo"]["checksum"] == "sha256:193"


def test_astpm_lock_includes_transitive_dependencies(monkeypatch, tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir(parents=True)
    monkeypatch.chdir(project)
    cache = tmp_path / "cache"
    monkeypatch.setenv("ARIXA_PKG_HOME", str(cache))

    dep_repo = tmp_path / "dep_repo"
    dep_repo.mkdir()
    (dep_repo / "Astra.toml").write_text('[package]\nname = "dep"\nversion = "1.4.0"\n')
    (dep_repo / "dep.arixa").write_text("fn dep_ping() Int{ return 1; }\n")

    root_repo = tmp_path / "root_repo"
    root_repo.mkdir()
    (root_repo / "Astra.toml").write_text(
        '[package]\nname = "root"\nversion = "1.0.0"\n[dependencies]\ndep = "^1.0.0"\n'
    )
    (root_repo / "root.arixa").write_text("fn root_ping() Int{ return 2; }\n")

    reg = tmp_path / "packages.json"
    reg.write_text(
        json.dumps(
            {
                "root": {"versions": {"1.0.0": {"repo": str(root_repo)}}},
                "dep": {"versions": {"1.4.0": {"repo": str(dep_repo)}}},
            }
        )
    )
    monkeypatch.setenv("ASTRA_REGISTRY_PATH", str(reg))

    astra.pkg.main(["init", "demo"])
    astra.pkg.main(["add", "root", "^1.0.0"])
    lock = json.loads((project / "Astra.lock").read_text())
    assert lock["packages"]["root"]["version"] == "1.0.0"
    assert lock["packages"]["dep"]["version"] == "1.4.0"
    assert lock["packages"]["dep"]["constraint"] == "^1.0.0"


def test_astpm_add_remove_cycle(monkeypatch, tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir()
    pkg_repo = tmp_path / "astra-sdl2"
    pkg_repo.mkdir()
    (pkg_repo / "Astra.toml").write_text(
        "[package]\nname = \"sdl2\"\nversion = \"2.0.0\"\n[native]\nlibs = [\"SDL2\"]\n"
    )
    (pkg_repo / "sdl2.arixa").write_text('@link("SDL2") extern fn SDL_Init(flags u32) i32;\n')

    reg = tmp_path / "packages.json"
    _write_registry(reg, "sdl2", str(pkg_repo), "2.0.0")
    monkeypatch.setenv("ASTRA_REGISTRY_PATH", str(reg))
    monkeypatch.setenv("ARIXA_PKG_HOME", str(tmp_path / "cache"))
    monkeypatch.chdir(project)

    astra.pkg.main(["init", "demo"])
    astra.pkg.main(["add", "sdl2"])
    manifest = (project / "Astra.toml").read_text()
    assert 'sdl2 = "2.0.0"' in manifest
    assert (tmp_path / "cache" / "sdl2" / "2.0.0" / "sdl2.arixa").exists()

    astra.pkg.main(["remove", "sdl2"])
    manifest2 = (project / "Astra.toml").read_text()
    assert "sdl2" not in manifest2
    assert not (tmp_path / "cache" / "sdl2").exists()


def test_import_resolution_uses_installed_package_cache(monkeypatch, tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir(parents=True)
    cache = tmp_path / "cache"
    (project / "Astra.toml").write_text('name = "demo"\n[dependencies]\npkgdemo = "2.0.0"\n')
    (project / "main.astra").write_text('import "pkgdemo";\nfn main() Int{ return 0; }\n')
    pkg_dir = cache / "pkgdemo" / "2.0.0"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "pkgdemo.arixa").write_text('@link("pkgdemo") extern fn demo_init(flags u32) i32;\n')
    monkeypatch.setenv("ARIXA_PKG_HOME", str(cache))

    resolved = resolve_import_path(ImportDecl(path=[], source="pkgdemo"), str(project / "main.astra"))
    assert resolved == (pkg_dir / "pkgdemo.arixa").resolve()


def test_import_resolution_prefers_lockfile_version(monkeypatch, tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir(parents=True)
    cache = tmp_path / "cache"
    monkeypatch.setenv("ARIXA_PKG_HOME", str(cache))
    (project / "Astra.toml").write_text('name = "demo"\n[dependencies]\npkgdemo = "^1.0.0"\n')
    (project / "Astra.lock").write_text(
        json.dumps(
            {
                "version": 1,
                "packages": {
                    "pkgdemo": {
                        "version": "1.9.3",
                        "constraint": "^1.0.0",
                        "source": "",
                        "checksum": "",
                    }
                },
            }
        )
    )
    (project / "main.astra").write_text('import "pkgdemo";\nfn main() Int{ return 0; }\n')
    pkg_dir = cache / "pkgdemo" / "1.9.3"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "pkgdemo.arixa").write_text("fn ping() Int{ return 0; }\n")

    resolved = resolve_import_path(ImportDecl(path=[], source="pkgdemo"), str(project / "main.astra"))
    assert resolved == (pkg_dir / "pkgdemo.arixa").resolve()


def test_build_with_dependency_auto_adds_native_link_flags(monkeypatch, tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir(parents=True)
    cache = tmp_path / "cache"
    monkeypatch.setenv("ARIXA_PKG_HOME", str(cache))

    (project / "Astra.toml").write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\n[dependencies]\npkgdemo = "2.0.0"\n'
    )
    (project / "main.astra").write_text('import "pkgdemo";\nfn main() Int{ return demo_init(0u32); }\n')

    pkg_dir = cache / "pkgdemo" / "2.0.0"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "Astra.toml").write_text(
        "[package]\nname = \"pkgdemo\"\nversion = \"2.0.0\"\n[native]\nlibs = [\"demoffi\"]\n"
    )
    (pkg_dir / "pkgdemo.arixa").write_text('@link("demoffi") extern fn demo_init(flags u32) i32;\n')

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


def test_build_uses_project_package_link_overrides(monkeypatch, tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir(parents=True)
    cache = tmp_path / "cache"
    monkeypatch.setenv("ARIXA_PKG_HOME", str(cache))

    (project / "Astra.toml").write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\n'
        '[dependencies]\npkgdemo = "2.0.0"\n'
        '[package.pkgdemo]\nlink.linux = ["demo_override"]\npkg_config = "demoffi"\n'
    )
    (project / "main.astra").write_text('import "pkgdemo";\nfn main() Int{ return demo_init(0u32); }\n')

    pkg_dir = cache / "pkgdemo" / "2.0.0"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "Astra.toml").write_text(
        "[package]\nname = \"pkgdemo\"\nversion = \"2.0.0\"\n[native]\nlibs = [\"demoffi\"]\n"
    )
    (pkg_dir / "pkgdemo.arixa").write_text('extern fn demo_init(flags u32) Int;\n')

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

    monkeypatch.setattr("astra.build.shutil.which", lambda tool: "/usr/bin/pkg-config" if tool == "pkg-config" else "/usr/bin/clang")
    monkeypatch.setattr("astra.build.subprocess.run", fake_run)
    monkeypatch.setattr("astra.build.sys.platform", "linux")
    monkeypatch.setattr("astra.build._pkg_config_link_args", lambda _: ["-L/opt/demo/lib", "-ldemoffi_extra"])

    out = project / "app"
    state = build(str(project / "main.astra"), str(out), "native")
    assert state in {"built", "cached"}
    flat = [arg for cmd in seen_cmds for arg in cmd]
    assert "-ldemoffi" in flat
    assert "-ldemo_override" in flat
    assert "-L/opt/demo/lib" in flat
    assert "-ldemoffi_extra" in flat


def test_astpm_verify_checks_cached_checksum(monkeypatch, tmp_path: Path, capsys):
    project = tmp_path / "app"
    project.mkdir(parents=True)
    cache = tmp_path / "cache"
    monkeypatch.chdir(project)
    monkeypatch.setenv("ARIXA_PKG_HOME", str(cache))

    pkg_dir = cache / "pkgdemo" / "1.0.0"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "pkgdemo.arixa").write_text("fn ping() Int{ return 0; }\n")
    digest = astra.pkg._dir_digest(pkg_dir)
    (project / "Astra.lock").write_text(
        json.dumps(
            {
                "version": 1,
                "packages": {
                    "pkgdemo": {
                        "version": "1.0.0",
                        "constraint": "1.0.0",
                        "source": str(pkg_dir),
                        "checksum": f"sha256:{digest}",
                    }
                },
            }
        )
    )

    astra.pkg.main(["verify"])
    out = capsys.readouterr().out
    assert "verified 1 package(s)" in out
