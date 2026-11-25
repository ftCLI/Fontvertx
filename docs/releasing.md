# Releasing Fontvertx

The version is written in a few places: `pyproject.toml` (`[project].version` and
`[tool.bumpversion].current_version`), the README links pinned to the release tag
(`…/Fontvertx/v<version>/…`, needed because the README is also the PyPI page) and the
`Version <version> · <Month Year>` line at the top of `docs/manual.md`. The app reads its
version from the package metadata, so nothing in `src/` needs editing.
[bump-my-version](https://callowayproject.github.io/bump-my-version/) updates all of them in
one command; `tests/test_version_consistency.py` fails CI if they ever disagree.

## Steps

1. Finish the changes for the release, `CHANGELOG.md` included.
2. Bump the version and update the lock file:

   ```console
   uv run bump-my-version bump patch    # or minor, major, or --new-version X.Y.Z
   uv lock
   ```

   This sets the manual's date line to the current month and year. Add `--dry-run -v` to
   the bump command to preview the changes first.
3. Commit and merge to `main`.
4. Create the tag `v<version>` and the GitHub release. The `build.yml` workflow runs on the
   release and attaches the Windows and macOS zips.

The bump is the last step before tagging: the README links point to the `v<version>` tag,
so they return 404 on GitHub until the release is published.
