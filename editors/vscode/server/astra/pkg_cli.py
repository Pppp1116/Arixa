#!/usr/bin/env python3
"""ASTRA Package Manager CLI - Command-line interface for package management."""

import argparse
import json
import sys
from pathlib import Path

from astra.package_manager import (
    PackagePublisher,
    PackageDiscovery,
    PackageInstaller,
    publish_command,
    search_command,
    install_command,
    list_command
)


def cmd_publish(args):
    """Publish a package."""
    try:
        package_dir = Path(args.directory) if args.directory else Path.cwd()
        
        if not package_dir.exists():
            print(f"Error: Directory {package_dir} does not exist")
            return 1
        
        publisher = PackagePublisher(package_dir)
        
        # Validate package first
        errors = publisher.validate_package()
        if errors:
            print("Package validation failed:")
            for error in errors:
                print(f"  - {error}")
            return 1
        
        print(f"Publishing package from {package_dir}")
        
        if args.target == "github":
            result = publisher.publish_to_github(create_release=args.create_release)
        elif args.target == "registry":
            result = publisher.publish_to_registry()
        else:
            print(f"Error: Unknown publish target {args.target}")
            return 1
        
        print(json.dumps(result, indent=2))
        
        if result.get("published", False) or result.get("release_created", False):
            print("✓ Package published successfully!")
        else:
            print("⚠ Package publishing completed with warnings")
            print(f"Message: {result.get('message', 'Unknown')}")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_search(args):
    """Search for packages."""
    try:
        discovery = PackageDiscovery()
        packages = discovery.search_packages(args.query, args.limit)
        
        if not packages:
            print(f"No packages found for '{args.query}'")
            return 0
        
        print(f"Found {len(packages)} packages for '{args.query}':\n")
        
        for pkg in packages:
            print(f"📦 {pkg['name']} v{pkg['version']}")
            print(f"   {pkg['description']}")
            if pkg.get('repository'):
                print(f"   📂 Repository: {pkg['repository']}")
            print()
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_install(args):
    """Install a package."""
    try:
        install_dir = Path(args.install_dir) if args.install_dir else Path.home() / ".astra" / "packages"
        installer = PackageInstaller(install_dir)
        
        print(f"Installing package '{args.package}' to {install_dir}")
        
        if args.package.startswith("https://github.com/"):
            result = installer.install_from_github(args.package)
        else:
            parts = args.package.split("@")
            name = parts[0]
            version = parts[1] if len(parts) > 1 else "latest"
            result = installer.install_from_registry(name, version)
        
        if result.get("installed", False):
            print(f"✓ Successfully installed {result['package_name']} v{result['version']}")
            print(f"   Location: {result['install_path']}")
        else:
            print(f"⚠ Installation completed with issues")
            print(f"Message: {result.get('message', 'Unknown')}")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_list(args):
    """List installed packages."""
    try:
        install_dir = Path(args.install_dir) if args.install_dir else Path.home() / ".astra" / "packages"
        installer = PackageInstaller(install_dir)
        
        packages = installer.list_installed_packages()
        
        if not packages:
            print("No packages installed")
            return 0
        
        print(f"Installed packages ({len(packages)}):\n")
        
        for pkg in packages:
            print(f"📦 {pkg['name']} v{pkg['version']}")
            print(f"   {pkg['description']}")
            print(f"   📍 {pkg['install_path']}")
            print()
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_info(args):
    """Show package information."""
    try:
        discovery = PackageDiscovery()
        
        # Try to get from registry first
        pkg_info = discovery.get_package_info(args.name)
        
        if not pkg_info:
            print(f"Package '{args.name}' not found in registry")
            return 1
        
        print(f"📦 {pkg_info['name']} v{pkg_info['version']}")
        print(f"📝 {pkg_info['description']}")
        
        if pkg_info.get('repository'):
            print(f"📂 Repository: {pkg_info['repository']}")
        
        if pkg_info.get('homepage'):
            print(f"🌐 Homepage: {pkg_info['homepage']}")
        
        if pkg_info.get('dependencies'):
            print("📋 Dependencies:")
            for dep, version in pkg_info['dependencies'].items():
                print(f"   - {dep} v{version}")
        
        if pkg_info.get('targets'):
            print("🎯 Targets:")
            for target, supported in pkg_info['targets'].items():
                status = "✓" if supported else "✗"
                print(f"   {status} {target}")
        
        if pkg_info.get('features'):
            print("⚡ Features:")
            for feature, description in pkg_info['features'].items():
                if isinstance(description, list):
                    print(f"   - {feature}: {', '.join(description)}")
                else:
                    print(f"   - {feature}")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_init(args):
    """Initialize a new package."""
    try:
        package_dir = Path(args.name)
        package_dir.mkdir(exist_ok=True)
        
        # Create directory structure
        (package_dir / "src").mkdir(exist_ok=True)
        (package_dir / "examples").mkdir(exist_ok=True)
        (package_dir / "tests").mkdir(exist_ok=True)
        
        # Create Astra.toml
        manifest = {
            "package": {
                "name": args.name,
                "version": "0.1.0",
                "description": args.description or f"A new ASTRA package: {args.name}",
                "authors": [args.author or "Your Name <you@example.com>"],
                "license": args.license or "MIT",
                "homepage": "",
                "repository": "",
                "documentation": "",
                "keywords": [],
                "categories": []
            },
            "dependencies": {
                "std": "1.0.0"
            },
            "dev-dependencies": {},
            "targets": {
                "freestanding": True,
                "gpu": False
            },
            "features": {
                "default": ["core"],
                "core": []
            },
            "package.metadata": {
                "publish": True,
                "auto-publish": False,
                "build-targets": ["x86_64"],
                "minimum-astra-version": "1.0.0"
            }
        }
        
        with open(package_dir / "Astra.toml", 'w') as f:
            json.dump(manifest, f, indent=2)
        
        # Create lib.arixa
        lib_content = f"""/// {args.name} library
/// {args.description or f'A new ASTRA package: {args.name}'}

import std.core;

/// Add your library functions here
fn hello_world() Int {{
    return 42;
}}

// Library constants
LIB_VERSION = "0.1.0";
"""
        
        with open(package_dir / "src" / "lib.arixa", 'w') as f:
            f.write(lib_content)
        
        # Create example
        example_content = f"""/// Example usage of {args.name}

import "src/lib.arixa";

fn main() Int {{
    result = hello_world();
    return result;
}}
"""
        
        with open(package_dir / "examples" / "demo.arixa", 'w') as f:
            f.write(example_content)
        
        print(f"✓ Created new package '{args.name}' in {package_dir}")
        print("📁 Structure:")
        print(f"   {package_dir}/")
        print("   ├── Astra.toml")
        print("   ├── src/")
        print("   │   └── lib.arixa")
        print("   ├── examples/")
        print("   │   └── demo.arixa")
        print("   └── tests/")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="ASTRA Package Manager CLI",
        prog="astra-pkg"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Publish command
    publish_parser = subparsers.add_parser("publish", help="Publish a package")
    publish_parser.add_argument(
        "--directory", "-d",
        help="Package directory (default: current directory)"
    )
    publish_parser.add_argument(
        "--target", "-t",
        choices=["github", "registry"],
        default="registry",
        help="Publish target (default: registry)"
    )
    publish_parser.add_argument(
        "--create-release",
        action="store_true",
        help="Create GitHub release when publishing to GitHub"
    )
    publish_parser.set_defaults(func=cmd_publish)
    
    # Search command
    search_parser = subparsers.add_parser("search", help="Search for packages")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument(
        "--limit", "-l",
        type=int,
        default=10,
        help="Maximum number of results (default: 10)"
    )
    search_parser.set_defaults(func=cmd_search)
    
    # Install command
    install_parser = subparsers.add_parser("install", help="Install a package")
    install_parser.add_argument("package", help="Package name or GitHub URL")
    install_parser.add_argument(
        "--install-dir",
        help="Installation directory (default: ~/.astra/packages)"
    )
    install_parser.set_defaults(func=cmd_install)
    
    # List command
    list_parser = subparsers.add_parser("list", help="List installed packages")
    list_parser.add_argument(
        "--install-dir",
        help="Installation directory (default: ~/.astra/packages)"
    )
    list_parser.set_defaults(func=cmd_list)
    
    # Info command
    info_parser = subparsers.add_parser("info", help="Show package information")
    info_parser.add_argument("name", help="Package name")
    info_parser.set_defaults(func=cmd_info)
    
    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize a new package")
    init_parser.add_argument("name", help="Package name")
    init_parser.add_argument("--description", help="Package description")
    init_parser.add_argument("--author", help="Package author")
    init_parser.add_argument("--license", default="MIT", help="Package license")
    init_parser.set_defaults(func=cmd_init)
    
    # Parse arguments
    args = parser.parse_args()
    
    if not hasattr(args, 'func'):
        parser.print_help()
        return 1
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
