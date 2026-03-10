import json
from pathlib import Path

from astra.package_manager import PackageDiscovery, PackageInstaller, PackagePublisher


def _create_sample_package(package_dir: Path) -> None:
    (package_dir / "src").mkdir(parents=True)
    (package_dir / "src" / "lib.arixa").write_text(
        "fn answer() Int {\n  return 42;\n}\n",
        encoding="utf-8",
    )
    manifest = {
        "package": {
            "name": "pkgdemo",
            "version": "0.1.0",
            "description": "Demo package",
            "repository": "https://github.com/example/pkgdemo",
            "authors": ["Example"],
            "keywords": ["demo"],
            "categories": ["Testing"],
        },
        "dependencies": {},
        "dev-dependencies": {},
        "targets": {"freestanding": True},
        "features": {},
    }
    (package_dir / "Astra.toml").write_text(json.dumps(manifest), encoding="utf-8")


def test_discovery_search_local_registry_includes_keywords(monkeypatch):
    discovery = PackageDiscovery()
    monkeypatch.setattr(discovery, "_fetch_registry_json", lambda *args, **kwargs: None)

    results = discovery.search_packages("networking", limit=20)

    curl = next(item for item in results if item["name"] == "curl")
    assert "networking" in [kw.lower() for kw in curl.get("keywords", [])]


def test_discovery_get_package_info_reads_local_registry(monkeypatch):
    discovery = PackageDiscovery()
    monkeypatch.setattr(discovery, "_fetch_registry_json", lambda *args, **kwargs: None)

    info = discovery.get_package_info("curl")

    assert info["name"] == "curl"
    assert info["dependencies"]["c"] == "1.0.0"
    assert info["repository"].startswith("https://github.com/")


def test_discovery_list_categories_from_local_registry(monkeypatch):
    discovery = PackageDiscovery()
    monkeypatch.setattr(discovery, "_fetch_registry_json", lambda *args, **kwargs: None)

    categories = discovery.list_categories()

    assert "Networking" in categories
    assert "Graphics" in categories


def test_publish_to_registry_falls_back_to_local_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    package_dir = tmp_path / "pkgdemo"
    _create_sample_package(package_dir)

    publisher = PackagePublisher(package_dir, registry_url="http://127.0.0.1:9")
    result = publisher.publish_to_registry()

    assert result["published"] is True
    assert result["registry"] == "local"

    index_path = Path(result["index_path"])
    assert index_path.exists()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert "pkgdemo" in index
    assert index["pkgdemo"]["version"] == "0.1.0"


def test_install_from_github_latest_prefers_release_tarball(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    install_dir = tmp_path / "packages"
    installer = PackageInstaller(install_dir)

    seen: dict[str, str] = {}

    monkeypatch.setattr(
        installer,
        "_fetch_latest_github_release",
        lambda owner, repo: {
            "tag_name": "v1.2.3",
            "tarball_url": "https://example.invalid/demo-v1.2.3.tar.gz",
        },
    )

    def fake_download(download_url: str, output_path: Path) -> None:
        seen["download_url"] = download_url
        output_path.write_bytes(b"dummy")

    monkeypatch.setattr(installer, "_download_archive", fake_download)

    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "Astra.toml").write_text(
        '[package]\nname = "demo"\nversion = "1.2.3"\ndescription = "demo"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(installer, "_safe_extract_tar", lambda tar_path, destination: extracted)

    result = installer.install_from_github("https://github.com/acme/demo", version="latest")

    assert result["installed"] is True
    assert result["version"] == "v1.2.3"
    assert result["download_url"] == seen["download_url"]
    assert (install_dir / "demo").exists()


def test_list_installed_packages_reads_toml_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    install_dir = tmp_path / "packages"
    package_dir = install_dir / "sample"
    package_dir.mkdir(parents=True)
    (package_dir / "Astra.toml").write_text(
        '[package]\nname = "sample"\nversion = "2.0.0"\ndescription = "sample package"\n',
        encoding="utf-8",
    )

    installer = PackageInstaller(install_dir)
    packages = installer.list_installed_packages()

    assert packages == [
        {
            "name": "sample",
            "version": "2.0.0",
            "description": "sample package",
            "install_path": str(package_dir),
        }
    ]
