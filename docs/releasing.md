# Releasing Perq

## Initial PyPI setup

In the intended owning PyPI account, add a pending publisher at
[account publishing](https://pypi.org/manage/account/publishing/) with these values:

| Field | Value |
|---|---|
| PyPI project name | `perq` |
| GitHub owner | `shaneaevans` |
| GitHub repository | `perq` |
| Workflow filename | `publish.yml` |
| Environment | `pypi` |

The GitHub environment is also named `pypi`. Trusted publishing uses short-lived
credentials from GitHub Actions; a PyPI API token is not required in repository
secrets. The first successful upload creates the PyPI project. See the official
[pending publisher instructions](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

## Release procedure

1. Update the version in `pyproject.toml` and date the changelog. Complete the checks
   in [contributing](../CONTRIBUTING.md), including a clean wheel install.
2. Commit and push the changes. Wait for every job in the cross-platform CI matrix
   and the distribution job to pass on the release commit.
3. Tag that commit with `v` followed by the package version. Publish a GitHub release
   with its wheel, source distribution, and migration notes.
4. Once the PyPI publisher is configured, dispatch the publishing workflow against
   the version tag. For version 0.2.0:

   ```sh
   gh workflow run publish.yml --repo shaneaevans/perq --ref v0.2.0
   ```

5. Check the workflow result and install the published version in a clean environment.
   Update the README installation instructions once PyPI publication succeeds.

The publishing workflow accepts version tags, checks the tag against package metadata,
tests and builds distributions in a separate job, then uploads them with PyPI
attestations. Creating a GitHub release alone does not trigger a PyPI upload.
