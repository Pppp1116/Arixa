# ASTRA Package Registry

This directory contains the canonical package index used by `astpm`.

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

## Add a package

1. Publish your package repository with a valid `Astra.toml`.
2. Add an entry to `registry/packages.json`.
3. Open a pull request against the ASTRA repository.

Package naming should use lowercase ASCII and match the import name users write:

```astra
import "yourpkg";
```
