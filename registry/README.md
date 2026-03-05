# ASTRA Package Registry

This directory contains the canonical package index used by `astpm`.
It also contains toolchain update metadata used by the VS Code extension.

## Format

`packages.json` maps package names to metadata:

```json
{
  "name": {
    "repo": "https://host/org/repo",
    "description": "short summary",
    "version": "1.2.3"
}
}
```

`toolchain-updates.json` provides online update metadata for the VS Code extension:

```json
{
  "stable": {
    "version": "0.4.0",
    "minExtensionVersion": "0.4.0",
    "downloadUrl": "https://github.com/Pppp1116/ASTRA/releases",
    "notesUrl": "https://github.com/Pppp1116/ASTRA/releases"
  },
  "prerelease": {
    "version": "0.5.0-beta.1",
    "minExtensionVersion": "0.4.0",
    "downloadUrl": "https://github.com/Pppp1116/ASTRA/releases",
    "notesUrl": "https://github.com/Pppp1116/ASTRA/releases"
  }
}
```

## Add a package

1. Publish your package repository with a valid `Astra.toml`.
2. Add an entry to `registry/packages.json`.
3. Open a pull request against the ASTRA repository.

Package naming should use lowercase ASCII and match the import name users write:

```astra
import "yourpkg";
```
