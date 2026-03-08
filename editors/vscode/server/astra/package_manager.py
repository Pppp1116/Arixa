"""ASTRA Package Manager - Handles publishing, discovery, and installation of packages."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List
import urllib.request
import urllib.parse
import hashlib

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


class PackagePublisher:
    """Handles publishing ASTRA packages to registries and GitHub."""
    
    def __init__(self, package_dir: Path):
        self.package_dir = package_dir
        self.manifest_path = package_dir / "Astra.toml"
        self.registry_url = "https://registry.astra-lang.org"
        
    def load_manifest(self) -> Dict[str, Any]:
        """Load and validate package manifest."""
        if not self.manifest_path.exists():
            raise ValueError("Astra.toml not found")
        
        with open(self.manifest_path, 'rb') as f:
            if tomllib:
                manifest = tomllib.load(f)
            else:
                # Fallback: try to parse as JSON if TOML not available
                content = f.read().decode('utf-8')
                # Simple TOML to JSON conversion for basic cases
                manifest = self._parse_toml_fallback(content)
        
        required_fields = ["package", "dependencies"]
        for field in required_fields:
            if field not in manifest:
                raise ValueError(f"Missing required field: {field}")
        
        return manifest
    
    def _parse_toml_fallback(self, content: str) -> Dict[str, Any]:
        """Very basic TOML parser fallback for simple cases."""
        result = {}
        current_section = None
        
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Section headers
            if line.startswith('[') and line.endswith(']'):
                current_section = line[1:-1]
                if '.' in current_section:
                    # Handle nested sections like [package.metadata]
                    parts = current_section.split('.')
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
            
            # Key-value pairs
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # Handle basic value types
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]  # Remove quotes
                elif value.isdigit():
                    value = int(value)
                elif value == 'true':
                    value = True
                elif value == 'false':
                    value = False
                elif value.startswith('[') and value.endswith(']'):
                    # Basic array parsing
                    value = value[1:-1].split(',')
                    value = [v.strip().strip('"') for v in value if v.strip()]
                
                # Store in appropriate section
                if current_section and '.' in current_section:
                    parts = current_section.split('.')
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
    
    def validate_package(self) -> List[str]:
        """Validate package structure and manifest."""
        errors = []
        manifest = self.load_manifest()
        
        # Check package structure
        src_dir = self.package_dir / "src"
        if not src_dir.exists():
            errors.append("src/ directory not found")
        
        lib_file = src_dir / "lib.arixa"
        if not lib_file.exists():
            errors.append("src/lib.arixa not found")
        
        # Validate manifest fields
        pkg_info = manifest.get("package", {})
        required_pkg_fields = ["name", "version", "description"]
        for field in required_pkg_fields:
            if field not in pkg_info:
                errors.append(f"Missing package.{field}")
        
        # Check GitHub repository
        repo_url = pkg_info.get("repository", "")
        if repo_url and not repo_url.startswith("https://github.com/"):
            errors.append("Repository must be a GitHub URL")
        
        return errors
    
    def create_package_archive(self) -> Path:
        """Create a distributable package archive."""
        manifest = self.load_manifest()
        pkg_info = manifest["package"]
        name = pkg_info["name"]
        version = pkg_info["version"]
        
        # Create temporary archive
        archive_name = f"{name}-{version}.tar.gz"
        archive_path = Path(tempfile.gettempdir()) / archive_name
        
        # Create archive
        cmd = [
            "tar", "-czf", str(archive_path),
            "-C", str(self.package_dir.parent),
            str(self.package_dir.name)
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
    
    def publish_to_github(self, create_release: bool = True) -> Dict[str, Any]:
        """Publish package to GitHub releases."""
        manifest = self.load_manifest()
        pkg_info = manifest["package"]
        
        repo_url = pkg_info.get("repository", "")
        if not repo_url:
            raise ValueError("Repository URL not specified in manifest")
        
        # Parse GitHub URL
        if "github.com" not in repo_url:
            raise ValueError("Only GitHub repositories are supported")
        
        # Extract owner/repo from URL
        parts = repo_url.strip("/").split("/")
        if len(parts) < 2:
            raise ValueError("Invalid GitHub URL format")
        
        owner, repo = parts[-2], parts[-1]
        
        # Create archive
        archive_path = self.create_package_archive()
        checksum = self.calculate_checksum(archive_path)
        
        result = {
            "archive_path": str(archive_path),
            "checksum": checksum,
            "github_repo": f"{owner}/{repo}",
            "version": pkg_info["version"]
        }
        
        if create_release:
            # TODO: Implement GitHub API calls for creating releases
            # This would require GitHub token authentication
            result["release_created"] = False
            result["message"] = "GitHub release creation not yet implemented"
        
        return result
    
    def publish_to_registry(self) -> Dict[str, Any]:
        """Publish package to ASTRA registry."""
        manifest = self.load_manifest()
        pkg_info = manifest["package"]
        
        # Validate package
        errors = self.validate_package()
        if errors:
            raise ValueError(f"Package validation failed: {', '.join(errors)}")
        
        # Create archive
        archive_path = self.create_package_archive()
        checksum = self.calculate_checksum(archive_path)
        
        # Prepare registry payload
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
            "archive_size": archive_path.stat().st_size
        }
        
        # TODO: Implement actual registry API call
        result = {
            "published": False,
            "message": "Registry publishing not yet implemented",
            "payload": payload,
            "archive_path": str(archive_path)
        }
        
        return result


class PackageDiscovery:
    """Handles discovering and searching for packages."""
    
    def __init__(self, registry_url: str = "https://registry.astra-lang.org"):
        self.registry_url = registry_url
        self.cache_dir = Path.home() / ".astra" / "package_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def search_packages(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for packages in the registry."""
        # TODO: Implement registry API call
        # For now, return mock results based on local registry
        return self._search_local_registry(query, limit)
    
    def _search_local_registry(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Search local registry file."""
        registry_path = Path(__file__).parent.parent / "registry" / "packages.json"
        
        if not registry_path.exists():
            return []
        
        with open(registry_path, 'r') as f:
            registry = json.load(f)
        
        results = []
        query_lower = query.lower()
        
        for name, info in registry.items():
            if query_lower in name.lower() or query_lower in info.get("description", "").lower():
                results.append({
                    "name": name,
                    "description": info.get("description", ""),
                    "version": info.get("version", "1.0.0"),
                    "repository": info.get("repo", ""),
                    "keywords": []  # TODO: Add keywords to registry
                })
            
            if len(results) >= limit:
                break
        
        return results
    
    def get_package_info(self, name: str) -> Dict[str, Any]:
        """Get detailed information about a package."""
        # TODO: Implement registry API call
        return self._get_local_package_info(name)
    
    def _get_local_package_info(self, name: str) -> Dict[str, Any]:
        """Get package info from local registry."""
        registry_path = Path(__file__).parent.parent / "registry" / "packages.json"
        
        if not registry_path.exists():
            return {}
        
        with open(registry_path, 'r') as f:
            registry = json.load(f)
        
        if name not in registry:
            return {}
        
        info = registry[name]
        return {
            "name": name,
            "description": info.get("description", ""),
            "version": info.get("version", "1.0.0"),
            "repository": info.get("repo", ""),
            "download_url": f"https://github.com/{info.get('repo', '').replace('https://github.com/', '')}/archive/refs/tags/v{info.get('version', '1.0.0')}.tar.gz",
            "dependencies": {},
            "targets": {"freestanding": True},
            "features": {}
        }
    
    def list_categories(self) -> List[str]:
        """List available package categories."""
        # TODO: Implement registry API call
        return ["Mathematics", "Algorithms", "Data Structures", "Graphics", "Networking", "Database", "CLI", "Web"]


class PackageInstaller:
    """Handles installing packages from registries and GitHub."""
    
    def __init__(self, install_dir: Path):
        self.install_dir = install_dir
        self.cache_dir = Path.home() / ".astra" / "package_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def install_from_github(self, repo_url: str, version: str = "latest") -> Dict[str, Any]:
        """Install package from GitHub repository."""
        # Parse GitHub URL
        if "github.com" not in repo_url:
            raise ValueError("Only GitHub repositories are supported")
        
        parts = repo_url.strip("/").split("/")
        if len(parts) < 2:
            raise ValueError("Invalid GitHub URL format")
        
        owner, repo = parts[-2], parts[-1]
        
        # Determine download URL
        if version == "latest":
            # TODO: Get latest release from GitHub API
            download_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/main.tar.gz"
            package_name = f"{repo}-main"
        else:
            download_url = f"https://github.com/{owner}/{repo}/archive/refs/tags/v{version}.tar.gz"
            package_name = f"{repo}-{version}"
        
        # Download package
        package_path = self.cache_dir / f"{package_name}.tar.gz"
        
        try:
            urllib.request.urlretrieve(download_url, package_path)
        except Exception as e:
            raise RuntimeError(f"Failed to download package: {e}")
        
        # Extract package
        extract_dir = self.cache_dir / package_name
        extract_dir.mkdir(exist_ok=True)
        
        cmd = ["tar", "-xzf", str(package_path), "-C", str(self.cache_dir)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to extract package: {result.stderr}")
        
        # Install to package directory
        install_path = self.install_dir / repo
        if install_path.exists():
            raise RuntimeError(f"Package {repo} is already installed")
        
        # Move extracted files to install location
        import shutil
        shutil.move(str(extract_dir), str(install_path))
        
        return {
            "installed": True,
            "package_name": repo,
            "version": version,
            "install_path": str(install_path),
            "download_url": download_url
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
        
        return self.install_from_github(repo_url, package_info.get("version", "latest"))
    
    def list_installed_packages(self) -> List[Dict[str, Any]]:
        """List all installed packages."""
        packages = []
        
        if not self.install_dir.exists():
            return packages
        
        for package_dir in self.install_dir.iterdir():
            if package_dir.is_dir():
                manifest_path = package_dir / "Astra.toml"
                if manifest_path.exists():
                    try:
                        with open(manifest_path, 'r') as f:
                            manifest = json.load(f)
                        
                        pkg_info = manifest.get("package", {})
                        packages.append({
                            "name": pkg_info.get("name", package_dir.name),
                            "version": pkg_info.get("version", "unknown"),
                            "description": pkg_info.get("description", ""),
                            "install_path": str(package_dir)
                        })
                    except Exception:
                        packages.append({
                            "name": package_dir.name,
                            "version": "unknown",
                            "description": "Invalid manifest",
                            "install_path": str(package_dir)
                        })
        
        return packages


def publish_command(package_dir: str, target: str = "registry") -> Dict[str, Any]:
    """Publish a package to the specified target."""
    package_path = Path(package_dir)
    
    if not package_path.exists():
        raise ValueError(f"Package directory {package_dir} not found")
    
    publisher = PackagePublisher(package_path)
    
    if target == "github":
        return publisher.publish_to_github()
    elif target == "registry":
        return publisher.publish_to_registry()
    else:
        raise ValueError(f"Unknown publish target: {target}")


def search_command(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search for packages."""
    discovery = PackageDiscovery()
    return discovery.search_packages(query, limit)


def install_command(package_spec: str, install_dir: str = None) -> Dict[str, Any]:
    """Install a package."""
    if install_dir is None:
        install_dir = Path.home() / ".astra" / "packages"
    else:
        install_dir = Path(install_dir)
    
    installer = PackageInstaller(install_dir)
    
    # Parse package specification
    if package_spec.startswith("https://github.com/"):
        return installer.install_from_github(package_spec)
    else:
        # Assume registry package
        parts = package_spec.split("@")
        name = parts[0]
        version = parts[1] if len(parts) > 1 else "latest"
        return installer.install_from_registry(name, version)


def list_command() -> List[Dict[str, Any]]:
    """List installed packages."""
    install_dir = Path.home() / ".astra" / "packages"
    installer = PackageInstaller(install_dir)
    return installer.list_installed_packages()
