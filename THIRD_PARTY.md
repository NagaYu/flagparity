# Third-party material

The licence check was done on 2026-11-25. Licence texts were read at the pinned commit or tag. Only material whose
licence was confirmed there, and is permissive, is shipped in this export. Everything else is listed in
`third_party_manifest.json` with its URL at the pinned commit and its sha256, and can be fetched with
`python3 -I scripts/fetch_third_party.py`. The script writes a file only when its sha256 matches.

## Upstream sources (read as data; never executed)

| Directory under `vectors/upstream/` | Project @ pinned ref | Licence at that ref | In this export |
|---|---|---|---|
| `flagd@b9c099cb-G1`, `flagd@v0.17.1-G2`, `flagd@v0.18.0-G3`, `flagd@v0.19.0`, `docs/flagd@v0.19.0` | open-feature/flagd @ b9c099cb / 0c5b766d (v0.17.1) / ac826d8e (v0.18.0) / flagd/v0.19.0 | Apache-2.0 (no NOTICE file at these refs) | yes, with `LICENSE` |
| `flipt-client-sdks@19e54652` | flipt-io/flipt-client-sdks @ 19e54652 | MIT (root and `flipt-evaluation/`) | yes, with `LICENSE` |
| `goff@v1.31.2`, `goff@v1.59.1` | thomaspoignant/go-feature-flag @ v1.31.2 / v1.59.1 | MIT | yes, with `LICENSE` |
| `gofr` | go-feature-flag/rules @ e9704fa7 (fork of nikunjy/rules) | MIT | yes, with `LICENSE` |
| `go-yaml@v3.0.1` | go-yaml/yaml @ v3.0.1 | MIT and Apache-2.0 | yes, with `LICENSE` |
| `jsonlogic@v3.10.2` | diegoholiveira/jsonlogic @ v3.10.2 | MIT | yes, with `LICENSE` |
| `go.mod/flagd@*`, `go.mod/goff@*` | as above | Apache-2.0 / MIT | yes |
| `flipt@v1.62.1`, `docs/flipt@v1.62.1`, `go.mod/flipt@v1.62.1.go.mod` | flipt-io/flipt @ v1.62.1 | **GPL-3.0** | no: listed for fetching (whether to ship GPL files is an owner decision) |
| `flipt@v2.14.2`, `docs/flipt@v2.14.2`, `go.mod/flipt@v2.14.2.go.mod` | flipt-io/flipt @ v2.14.2 | **FCL-1.0-MIT (Fair Core License)** | no: listed for fetching (owner decision) |
| `flagd-testbed` | open-feature/flagd-testbed @ 7690b548 | **none found**: no licence file at the pinned commit, and GitHub reports no licence for the repository | no: listed for fetching |

## Flag definition files from public repositories

- `smoke/census/files/` (the Phase 0 census, 640 files) and `bench/files/real/` (48 files) are third-party files from
  public GitHub repositories. Of the 41 source repositories behind the dev bench, GitHub's repository metadata
  (default branch, not the pinned commit) reports: 19 none, 10 Apache-2.0, 6 MIT, 4 NOASSERTION, 1 GPL-3.0,
  1 AGPL-3.0. None was confirmed at the pinned commit, so none is shipped.
- `bench/files/constructed/` (47 files) are those files with one injected defect, so they follow the licence of
  their source file and are not shipped either. After fetching the census files,
  `python3 bench/build.py && python3 bench/manual_cases.py` rebuilds all 95 bench files byte-identically.
- `smoke/census/inventory.csv` is shipped with only the 634 counted rows, and without the repository-description column.
- The sealed Phase 2 holdout is not shipped. `holdout/PUBLIC_MANIFEST.json` lists only the sha256 and source URL of
  each of its 148 inputs.

## Open question for the owner (not a legal opinion)

The semantics modules (`flagparity/semantics/*.py`) re-implement bucketing and evaluation behaviour after reading the
pinned sources, including Flipt's GPL-3.0 (v1.62.1) and FCL (v2.14.2) code. FlagParity is proprietary, so whether that
re-implementation carries any obligation from those licences matters more than it would for a permissive licence. It
has not been assessed and should be reviewed (with legal advice if wanted) before publication.
