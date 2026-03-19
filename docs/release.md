# Release Guide

This document describes the intended release flow for the UnoLock Agent GitHub repository.

Official repository:

* `https://github.com/TechSologic/unolock-agent`

## Goals

Each release should:

* pass Python unit tests
* produce a source distribution and wheel
* produce standalone binaries for macOS, Windows, and Linux
* attach build artifacts to a GitHub Release
* optionally publish to PyPI once trusted publishing is configured

## Versioning

The package version currently lives in:

* [pyproject.toml](../pyproject.toml)

For now, use semantic versioning:

* patch: fixes and documentation improvements
* minor: new MCP tools or supported host/provider additions
* major: breaking protocol or installation changes

## Suggested Release Flow

1. Update version in `pyproject.toml`.
2. Update customer-facing docs if install or behavior changed.
3. Push to `main`.
4. Create and push a git tag such as:

```bash
git tag v0.1.0
git push origin v0.1.0
```

5. Let GitHub Actions build the release artifacts.
6. Review the GitHub Release output.
7. If PyPI publishing is enabled later, let the publish workflow run from the release or tag.

## GitHub Actions

Recommended workflows:

* `ci.yml`
  * runs unit tests and compile checks on push and pull request
* `release.yml`
  * builds a wheel and source distribution on version tags
  * builds standalone binaries on macOS, Windows, and Linux
  * uploads them to the GitHub Release

## PyPI Publishing

PyPI publishing is optional until you are ready.

When you enable it, prefer:

* PyPI trusted publishing from GitHub Actions

That avoids storing a long-lived PyPI token in repository secrets.

## Manual Build Commands

Local build:

```bash
cd unolock-agent
python3 -m pip install --user build
python3 -m build
```

Local standalone binary build:

```bash
cd unolock-agent
python3 -m pip install --user -e .[dev]
python3 scripts/build_binary.py --clean
```

Optional artifact validation:

```bash
python3 -m pip install --user twine
python3 -m twine check dist/*
```
