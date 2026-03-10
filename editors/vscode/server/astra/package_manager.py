"""ASTRA Package Manager - Handles publishing, discovery, and installation of packages."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List
import urllib.error
import urllib.parse
import urllib.request
import hashlib

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


_HTTP_TIMEOUT_SECONDS = 20
_GITHUB_API_URL = "https://api.github.com"
_DEFAULT_REGISTRY_URL = os.getenv("ASTRA_REGISTRY_URL", "https://registry.astra-lang.org")


class HTTPRequestError(RuntimeError):
    """HTTP request failed."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def _parse_toml_fallback(content: str) -> Dict[str, Any]:
    """Very basic TOML parser fallback for simple cases."""
    result: dict[str, Any] = {}
    current_section: str | None = None

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            if "." in current_section:
                parts = current_section.split(".")
                current = result
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                if parts[-1] not in current:
                    current[parts[-1]] = {}
            else:
                if current_section not in result:
                    result[current_section] = {}
            continue

        if "=" in line:
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.isdigit():
                value = int(value)
            elif value == "true":
                value = True
            elif value == "false":
                value = False
            elif value.startswith("[") and value.endswith("]"):
                value = value[1:-1].split(",")
                value = [v.strip().strip('"') for v in value if v.strip()]

            if current_section and "." in current_section:
                parts = current_section.split(".")
                current = result
                for part in parts:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                current[key] = value
            elif current_section:
                result[current_section][key] = value
            else:
                result[key] = value

    return result


def _load_manifest(path: Path) -> Dict[str, Any]:
    """Load manifest from TOML/JSON with compatibility fallbacks."""
    with open(path, "rb") as f:
        raw_bytes = f.read()

    if tomllib is not None:
        try:
            return tomllib.loads(raw_bytes.decode("utf-8"))
        except Exception:
            pass

    text = raw_bytes.decode("utf-8")

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    return _parse_toml_fallback(text)


def _bundled_registry_path() -> Path | None:
    """Locate registry/packages.json in this repository layout."""
    start = Path(__file__).resolve().parent
    for base in [start, *start.parents]:
        candidate = base / "registry" / "packages.json"
        if candidate.exists():
            return candidate
    return None


def _local_registry_path() -> Path:
    return Path.home() / ".astra" / "registry" / "packages.json"


def _load_registry_index() -> dict[str, dict[str, Any]]:
    """Load merged registry index from bundled and local registries."""
    merged: dict[str, dict[str, Any]] = {}

    paths: list[Path] = []
    bundled = _bundled_registry_path()
    if bundled is not None:
        paths.append(bundled)
    paths.append(_local_registry_path())

    for path in paths:
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for name, info in data.items():
                    if isinstance(info, dict):
                        merged[name] = dict(info)
        except Exception:
            continue

    return merged


def _write_local_registry_index(registry_data: dict[str, dict[str, Any]]) -> Path:
    """Persist package metadata in the user-scoped local registry."""
    out_path = _local_registry_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(registry_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path


def _join_url(base_url: str, endpoint: str) -> str:
    base = base_url.rstrip("/") + "/"
    return urllib.parse.urljoin(base, endpoint.lstrip("/"))


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = _HTTP_TIMEOUT_SECONDS,
) -> Any:
    """Perform an HTTP request and decode a JSON response."""
    req_headers = {
        "Accept": "application/json",
        "User-Agent": "astra-package-manager/1.0",
    }
    if headers:
        req_headers.update(headers)

    body = data
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=body, method=method, headers=req_headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        raise HTTPRequestError(
            f"{method} {url} failed with HTTP {exc.code}: {detail or exc.reason}",
            status=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPRequestError(f"{method} {url} failed: {exc.reason}") from exc

    if not raw:
        return {}

    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPRequestError(f"{method} {url} returned invalid JSON") from exc


def _parse_github_repo(repo_url: str) -> tuple[str, str]:
    """Parse a GitHub repository URL into owner/repo."""
    parsed = urllib.parse.urlparse(repo_url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host != "github.com":
        raise ValueError("Only GitHub repositories are supported")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("Invalid GitHub URL format")

    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    if not owner or not repo:
        raise ValueError("Invalid GitHub URL format")

    return owner, repo


def _normalize_repo_url(info: dict[str, Any]) -> str:
    return str(info.get("repository") or info.get("repo") or "")


def _version_tag(version: str) -> str:
    return version if version.startswith("v") else f"v{version}"


class PackagePublisher:
    """Handles publishing ASTRA packages to registries and GitHub."""

    def __init__(self, package_dir: Path, registry_url: str = _DEFAULT_REGISTRY_URL):
        self.package_dir = package_dir
        self.manifest_path = package_dir / "Astra.toml"
        self.registry_url = registry_url

    def load_manifest(self) -> Dict[str, Any]:
        """Load and validate package manifest."""
        if not self.manifest_path.exists():
            raise ValueError("Astra.toml not found")

        manifest = _load_manifest(self.manifest_path)

        required_fields = ["package", "dependencies"]
        for field in required_fields:
            if field not in manifest:
                raise ValueError(f"Missing required field: {field}")

        return manifest

    def validate_package(self) -> List[str]:
        """Validate package structure and manifest."""
        errors = []
        manifest = self.load_manifest()

        src_dir = self.package_dir / "src"
        if not src_dir.exists():
            errors.append("src/ directory not found")

        lib_file = src_dir / "lib.arixa"
        if not lib_file.exists():
            errors.append("src/lib.arixa not found")

        pkg_info = manifest.get("package", {})
        required_pkg_fields = ["name", "version", "description"]
        for field in required_pkg_fields:
            if field not in pkg_info:
                errors.append(f"Missing package.{field}")

        repo_url = pkg_info.get("repository", "")
        if repo_url:
            try:
                _parse_github_repo(repo_url)
            except ValueError:
                errors.append("Repository must be a valid GitHub URL")

        return errors

    def create_package_archive(self) -> Path:
        """Create a distributable package archive."""
        manifest = self.load_manifest()
        pkg_info = manifest["package"]
        name = pkg_info["name"]
        version = pkg_info["version"]

        archive_name = f"{name}-{version}.tar.gz"
        archive_path = Path(tempfile.gettempdir()) / archive_name

        cmd = [
            "tar",
            "-czf",
            str(archive_path),
            "-C",
            str(self.package_dir.parent),
            str(self.package_dir.name),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create archive: {result.stderr}")

        return archive_path

    def calculate_checksum(self, archive_path: Path) -> str:
        """Calculate SHA256 checksum for package archive."""
        sha256_hash = hashlib.sha256()
        with open(archive_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def _github_token(self) -> str | None:
        return os.getenv("ASTRA_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")

    def _github_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _ensure_github_release(self, owner: str, repo: str, version: str, token: str) -> dict[str, Any]:
        tag = _version_tag(version)
        encoded_tag = urllib.parse.quote(tag, safe="")
        release_url = f"{_GITHUB_API_URL}/repos/{owner}/{repo}/releases/tags/{encoded_tag}"

        try:
            existing = _request_json(release_url, headers=self._github_headers(token))
            if isinstance(existing, dict):
                return existing
        except HTTPRequestError as exc:
            if exc.status != 404:
                raise

        create_url = f"{_GITHUB_API_URL}/repos/{owner}/{repo}/releases"
        payload = {
            "tag_name": tag,
            "name": tag,
            "draft": False,
            "prerelease": False,
            "generate_release_notes": True,
        }
        created = _request_json(create_url, method="POST", payload=payload, headers=self._github_headers(token))
        if not isinstance(created, dict):
            raise RuntimeError("GitHub release API returned an unexpected payload")
        return created

    def _upload_github_asset(self, release: dict[str, Any], archive_path: Path, token: str) -> dict[str, Any]:
        upload_template = str(release.get("upload_url") or "")
        if not upload_template:
            raise RuntimeError("GitHub release response did not include upload_url")

        upload_base = upload_template.split("{", 1)[0]
        asset_name = archive_path.name
        upload_url = f"{upload_base}?name={urllib.parse.quote(asset_name)}"
        headers = self._github_headers(token)
        headers["Content-Type"] = "application/gzip"
        headers["Accept"] = "application/json"

        data = archive_path.read_bytes()

        try:
            uploaded = _request_json(upload_url, method="POST", data=data, headers=headers)
            if isinstance(uploaded, dict):
                return uploaded
            raise RuntimeError("GitHub asset upload returned an unexpected payload")
        except HTTPRequestError as exc:
            if exc.status != 422:
                raise

            assets_url = str(release.get("assets_url") or "")
            if not assets_url:
                raise RuntimeError("GitHub reported duplicate asset and assets_url was missing")
            assets = _request_json(assets_url, headers=self._github_headers(token))
            if not isinstance(assets, list):
                raise RuntimeError("GitHub assets API returned an unexpected payload")
            for asset in assets:
                if isinstance(asset, dict) and asset.get("name") == asset_name:
                    return asset
            raise RuntimeError("GitHub reported duplicate asset but matching asset was not found")

    def publish_to_github(self, create_release: bool = True) -> Dict[str, Any]:
        """Publish package to GitHub releases."""
        manifest = self.load_manifest()
        pkg_info = manifest["package"]

        repo_url = pkg_info.get("repository", "")
        if not repo_url:
            raise ValueError("Repository URL not specified in manifest")

        owner, repo = _parse_github_repo(repo_url)

        archive_path = self.create_package_archive()
        checksum = self.calculate_checksum(archive_path)

        result: dict[str, Any] = {
            "archive_path": str(archive_path),
            "checksum": checksum,
            "github_repo": f"{owner}/{repo}",
            "version": pkg_info["version"],
        }

        if not create_release:
            return result

        token = self._github_token()
        if not token:
            result["release_created"] = False
            result["message"] = "Set ASTRA_GITHUB_TOKEN (or GITHUB_TOKEN) to publish GitHub releases"
            return result

        try:
            release = self._ensure_github_release(owner, repo, str(pkg_info["version"]), token)
            asset = self._upload_github_asset(release, archive_path, token)
            result.update(
                {
                    "release_created": True,
                    "release_id": release.get("id"),
                    "release_tag": release.get("tag_name"),
                    "release_url": release.get("html_url"),
                    "asset_url": asset.get("browser_download_url"),
                }
            )
        except Exception as exc:
            result["release_created"] = False
            result["message"] = str(exc)

        return result

    def _registry_publish_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        token = os.getenv("ASTRA_REGISTRY_TOKEN") or os.getenv("ARPM_REGISTRY_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _publish_to_registry_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoints = (
            "/api/v1/packages",
            "/api/packages",
            "/packages",
        )
        errors: list[str] = []

        for endpoint in endpoints:
            url = _join_url(self.registry_url, endpoint)
            try:
                response = _request_json(
                    url,
                    method="POST",
                    payload=payload,
                    headers=self._registry_publish_headers(),
                )
                if isinstance(response, dict):
                    return response
                return {"response": response}
            except HTTPRequestError as exc:
                if exc.status in {404, 405}:
                    errors.append(str(exc))
                    continue
                raise RuntimeError(f"Registry publish failed: {exc}") from exc

        raise RuntimeError(
            "Registry API endpoint was not available"
            + (f" ({'; '.join(errors)})" if errors else "")
        )

    def _publish_to_local_registry(self, payload: dict[str, Any], archive_path: Path) -> dict[str, Any]:
        registry = _load_registry_index()

        entry = {
            "repo": payload.get("repository", ""),
            "description": payload.get("description", ""),
            "version": payload.get("version", "0.1.0"),
            "license": payload.get("license", ""),
            "authors": payload.get("authors", []),
            "homepage": payload.get("homepage", ""),
            "keywords": payload.get("keywords", []),
            "categories": payload.get("categories", []),
            "dependencies": payload.get("dependencies", {}),
            "targets": payload.get("targets", {}),
            "features": payload.get("features", {}),
            "checksum": payload.get("checksum", ""),
        }

        registry[payload["name"]] = entry
        local_index_path = _write_local_registry_index(registry)

        archive_dir = Path.home() / ".astra" / "registry" / "archives" / payload["name"]
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_dest = archive_dir / f"{payload['version']}.tar.gz"
        shutil.copy2(archive_path, archive_dest)

        return {
            "published": True,
            "registry": "local",
            "message": "Published to local fallback registry",
            "index_path": str(local_index_path),
            "archive_path": str(archive_dest),
        }

    def publish_to_registry(self) -> Dict[str, Any]:
        """Publish package to ASTRA registry."""
        manifest = self.load_manifest()
        pkg_info = manifest["package"]

        errors = self.validate_package()
        if errors:
            raise ValueError(f"Package validation failed: {', '.join(errors)}")

        archive_path = self.create_package_archive()
        checksum = self.calculate_checksum(archive_path)

        payload = {
            "name": pkg_info["name"],
            "version": pkg_info["version"],
            "description": pkg_info["description"],
            "authors": pkg_info.get("authors", []),
            "license": pkg_info.get("license", ""),
            "homepage": pkg_info.get("homepage", ""),
            "repository": pkg_info.get("repository", ""),
            "documentation": pkg_info.get("documentation", ""),
            "keywords": pkg_info.get("keywords", []),
            "categories": pkg_info.get("categories", []),
            "dependencies": manifest.get("dependencies", {}),
            "dev_dependencies": manifest.get("dev-dependencies", {}),
            "targets": manifest.get("targets", {}),
            "features": manifest.get("features", {}),
            "checksum": checksum,
            "archive_size": archive_path.stat().st_size,
        }

        api_error: str | None = None
        try:
            remote = self._publish_to_registry_api(payload)
            return {
                "published": True,
                "registry": "remote",
                "archive_path": str(archive_path),
                "checksum": checksum,
                "response": remote,
            }
        except Exception as exc:
            api_error = str(exc)

        local = self._publish_to_local_registry(payload, archive_path)
        if api_error:
            local["api_error"] = api_error
        local["checksum"] = checksum
        return local


class PackageDiscovery:
    """Handles discovering and searching for packages."""

    def __init__(self, registry_url: str = _DEFAULT_REGISTRY_URL):
        self.registry_url = registry_url
        self.cache_dir = Path.home() / ".astra" / "package_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _fetch_registry_json(self, paths: list[str], query: dict[str, Any] | None = None) -> Any | None:
        for path in paths:
            url = _join_url(self.registry_url, path)
            if query:
                url = f"{url}?{urllib.parse.urlencode(query)}"
            try:
                return _request_json(url)
            except HTTPRequestError as exc:
                if exc.status in {404, 405}:
                    continue
            except Exception:
                continue
        return None

    def _search_local_registry(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Search merged local registry index."""
        registry = _load_registry_index()
        if not registry:
            return []

        results = []
        query_lower = query.lower()

        for name, info in registry.items():
            description = str(info.get("description", ""))
            keywords = info.get("keywords", [])
            if not isinstance(keywords, list):
                keywords = []

            searchable = " ".join([name, description] + [str(k) for k in keywords]).lower()
            if query_lower in searchable:
                results.append(
                    {
                        "name": name,
                        "description": description,
                        "version": str(info.get("version", "1.0.0")),
                        "repository": _normalize_repo_url(info),
                        "keywords": keywords,
                        "categories": info.get("categories", []),
                    }
                )

            if len(results) >= limit:
                break

        return results

    def search_packages(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for packages in the registry."""
        safe_limit = max(1, int(limit))

        remote = self._fetch_registry_json(
            ["/api/v1/search", "/api/packages/search", "/search"],
            {"q": query, "limit": safe_limit},
        )
        if remote is not None:
            if isinstance(remote, dict):
                items = remote.get("packages") or remote.get("results") or remote.get("items") or []
            else:
                items = remote
            if isinstance(items, list):
                normalized: list[dict[str, Any]] = []
                for item in items[:safe_limit]:
                    if not isinstance(item, dict):
                        continue
                    normalized.append(
                        {
                            "name": item.get("name", ""),
                            "description": item.get("description", ""),
                            "version": item.get("version", "1.0.0"),
                            "repository": _normalize_repo_url(item),
                            "keywords": item.get("keywords", []),
                            "categories": item.get("categories", []),
                        }
                    )
                if normalized:
                    return normalized

        return self._search_local_registry(query, safe_limit)

    def _get_local_package_info(self, name: str) -> Dict[str, Any]:
        """Get package info from merged local registry index."""
        registry = _load_registry_index()
        if name not in registry:
            return {}

        info = dict(registry[name])
        repo_url = _normalize_repo_url(info)
        version = str(info.get("version", "1.0.0"))
        tag = _version_tag(version)

        return {
            "name": name,
            "description": info.get("description", ""),
            "version": version,
            "repository": repo_url,
            "homepage": info.get("homepage", ""),
            "license": info.get("license", ""),
            "authors": info.get("authors", []),
            "keywords": info.get("keywords", []),
            "categories": info.get("categories", []),
            "download_url": f"https://github.com/{repo_url.replace('https://github.com/', '')}/archive/refs/tags/{tag}.tar.gz"
            if repo_url.startswith("https://github.com/")
            else "",
            "dependencies": info.get("dependencies", {}),
            "targets": info.get("targets", {"freestanding": True}),
            "features": info.get("features", {}),
        }

    def get_package_info(self, name: str) -> Dict[str, Any]:
        """Get detailed information about a package."""
        encoded_name = urllib.parse.quote(name, safe="")
        remote = self._fetch_registry_json(
            [f"/api/v1/packages/{encoded_name}", f"/api/packages/{encoded_name}", f"/packages/{encoded_name}"]
        )
        if isinstance(remote, dict) and remote:
            normalized = {
                "name": remote.get("name", name),
                "description": remote.get("description", ""),
                "version": remote.get("version", "1.0.0"),
                "repository": _normalize_repo_url(remote),
                "homepage": remote.get("homepage", ""),
                "license": remote.get("license", ""),
                "authors": remote.get("authors", []),
                "keywords": remote.get("keywords", []),
                "categories": remote.get("categories", []),
                "download_url": remote.get("download_url", ""),
                "dependencies": remote.get("dependencies", {}),
                "targets": remote.get("targets", {"freestanding": True}),
                "features": remote.get("features", {}),
            }
            if normalized["download_url"]:
                return normalized
            local_download = self._get_local_package_info(normalized["name"]).get("download_url", "")
            normalized["download_url"] = local_download
            return normalized

        return self._get_local_package_info(name)

    def list_categories(self) -> List[str]:
        """List available package categories."""
        remote = self._fetch_registry_json(["/api/v1/categories", "/api/packages/categories", "/categories"])
        if isinstance(remote, list):
            return sorted({str(item) for item in remote if isinstance(item, str)})
        if isinstance(remote, dict):
            items = remote.get("categories")
            if isinstance(items, list):
                return sorted({str(item) for item in items if isinstance(item, str)})

        categories: set[str] = set()
        for info in _load_registry_index().values():
            raw_categories = info.get("categories", [])
            if isinstance(raw_categories, list):
                for category in raw_categories:
                    if isinstance(category, str) and category:
                        categories.add(category)
        return sorted(categories)


class PackageInstaller:
    """Handles installing packages from registries and GitHub."""

    def __init__(self, install_dir: Path):
        self.install_dir = install_dir
        self.cache_dir = Path.home() / ".astra" / "package_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.install_dir.mkdir(parents=True, exist_ok=True)

    def _fetch_latest_github_release(self, owner: str, repo: str) -> dict[str, Any] | None:
        url = f"{_GITHUB_API_URL}/repos/{owner}/{repo}/releases/latest"
        try:
            resp = _request_json(url, headers={"X-GitHub-Api-Version": "2022-11-28"})
        except HTTPRequestError as exc:
            if exc.status == 404:
                return None
            return None

        if isinstance(resp, dict):
            return resp
        return None

    def _download_archive(self, download_url: str, output_path: Path) -> None:
        try:
            urllib.request.urlretrieve(download_url, output_path)
        except Exception as exc:
            raise RuntimeError(f"Failed to download package: {exc}") from exc

    def _safe_extract_tar(self, tar_path: Path, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        destination_resolved = destination.resolve()

        with tarfile.open(tar_path, "r:gz") as tar:
            members = tar.getmembers()
            roots: set[str] = set()
            for member in members:
                name = member.name.lstrip("/")
                if not name:
                    continue
                root = Path(name).parts[0]
                roots.add(root)
                target = (destination / name).resolve()
                if not str(target).startswith(str(destination_resolved) + os.sep) and target != destination_resolved:
                    raise RuntimeError(f"Unsafe archive entry: {member.name}")
            tar.extractall(path=destination)

        if len(roots) != 1:
            raise RuntimeError("Unexpected archive layout: expected a single root directory")
        root = next(iter(roots))
        extracted_root = destination / root
        if not extracted_root.exists():
            raise RuntimeError("Archive extracted but root directory was not found")
        return extracted_root

    def install_from_github(self, repo_url: str, version: str = "latest") -> Dict[str, Any]:
        """Install package from GitHub repository."""
        owner, repo = _parse_github_repo(repo_url)

        resolved_version = version
        if version == "latest":
            release = self._fetch_latest_github_release(owner, repo)
            if release and release.get("tarball_url"):
                download_url = str(release["tarball_url"])
                resolved_version = str(release.get("tag_name") or "latest")
            else:
                download_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/main.tar.gz"
                resolved_version = "main"
        else:
            tag = _version_tag(version)
            download_url = f"https://github.com/{owner}/{repo}/archive/refs/tags/{tag}.tar.gz"

        safe_version = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in resolved_version)
        package_path = self.cache_dir / f"{repo}-{safe_version}.tar.gz"
        self._download_archive(download_url, package_path)

        install_path = self.install_dir / repo
        if install_path.exists():
            raise RuntimeError(f"Package {repo} is already installed")

        extract_parent = Path(tempfile.mkdtemp(prefix=f"{repo}-extract-", dir=str(self.cache_dir)))
        extracted_root: Path | None = None
        try:
            extracted_root = self._safe_extract_tar(package_path, extract_parent)
            shutil.move(str(extracted_root), str(install_path))
        finally:
            if extract_parent.exists():
                shutil.rmtree(extract_parent, ignore_errors=True)

        return {
            "installed": True,
            "package_name": repo,
            "version": resolved_version,
            "install_path": str(install_path),
            "download_url": download_url,
        }

    def install_from_registry(self, name: str, version: str = "latest") -> Dict[str, Any]:
        """Install package from ASTRA registry."""
        discovery = PackageDiscovery()
        package_info = discovery.get_package_info(name)

        if not package_info:
            raise ValueError(f"Package {name} not found in registry")

        repo_url = package_info.get("repository", "")
        if not repo_url:
            raise ValueError(f"Package {name} has no repository URL")

        resolved_version = package_info.get("version", "latest") if version == "latest" else version
        return self.install_from_github(str(repo_url), str(resolved_version))

    def list_installed_packages(self) -> List[Dict[str, Any]]:
        """List all installed packages."""
        packages = []

        if not self.install_dir.exists():
            return packages

        for package_dir in self.install_dir.iterdir():
            if not package_dir.is_dir():
                continue

            manifest_path = package_dir / "Astra.toml"
            if not manifest_path.exists():
                packages.append(
                    {
                        "name": package_dir.name,
                        "version": "unknown",
                        "description": "Missing manifest",
                        "install_path": str(package_dir),
                    }
                )
                continue

            try:
                manifest = _load_manifest(manifest_path)
                pkg_info = manifest.get("package", {}) if isinstance(manifest, dict) else {}
                packages.append(
                    {
                        "name": pkg_info.get("name", package_dir.name),
                        "version": pkg_info.get("version", "unknown"),
                        "description": pkg_info.get("description", ""),
                        "install_path": str(package_dir),
                    }
                )
            except Exception:
                packages.append(
                    {
                        "name": package_dir.name,
                        "version": "unknown",
                        "description": "Invalid manifest",
                        "install_path": str(package_dir),
                    }
                )

        return packages


def publish_command(package_dir: str, target: str = "registry") -> Dict[str, Any]:
    """Publish a package to the specified target."""
    package_path = Path(package_dir)

    if not package_path.exists():
        raise ValueError(f"Package directory {package_dir} not found")

    publisher = PackagePublisher(package_path)

    if target == "github":
        return publisher.publish_to_github()
    if target == "registry":
        return publisher.publish_to_registry()
    raise ValueError(f"Unknown publish target: {target}")


def search_command(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search for packages."""
    discovery = PackageDiscovery()
    return discovery.search_packages(query, limit)


def install_command(package_spec: str, install_dir: str = None) -> Dict[str, Any]:
    """Install a package."""
    if install_dir is None:
        resolved_install_dir = Path.home() / ".astra" / "packages"
    else:
        resolved_install_dir = Path(install_dir)

    installer = PackageInstaller(resolved_install_dir)

    if package_spec.startswith("https://github.com/"):
        return installer.install_from_github(package_spec)

    parts = package_spec.split("@")
    name = parts[0]
    version = parts[1] if len(parts) > 1 else "latest"
    return installer.install_from_registry(name, version)


def list_command() -> List[Dict[str, Any]]:
    """List installed packages."""
    install_dir = Path.home() / ".astra" / "packages"
    installer = PackageInstaller(install_dir)
    return installer.list_installed_packages()
