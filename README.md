<p align="center"><img src="logo.png" width="140"></p>

# ChATlas

**Retina connectome explorer** for CAVE / Neuroglancer datasets (built for `stroeh_mouse_retina`).
It places cells in **ChAT-normalised depth** (0 = OFF starburst band, 1 = ON band), using surfaces fitted to the labelled starburst amacrine cells around the region you look at.

## Download and install

**Easiest:** download the installer for your computer from the [latest release](https://github.com/jerjely/ChATlas/releases/latest) — no Miniconda or Python needed:

| Computer | File |
|---|---|
| Windows (64-bit) | `ChATlas-<version>-Windows-x86_64.exe` |
| Mac with Apple silicon | `ChATlas-<version>-MacOSX-arm64.pkg` |
| Mac with Intel processor | `ChATlas-<version>-MacOSX-x86_64.pkg` |

The installers are not code-signed yet. On Windows, if SmartScreen appears, click **More info → Run anyway**; on macOS, **right-click the .pkg → Open** (or allow it in *System Settings → Privacy & Security*).
Windows: shortcuts on the desktop and in the Start menu. macOS: **ChATlas** in Applications.

### From source (with Miniconda)

Download the code (**Code → Download ZIP**, or `git clone https://github.com/jerjely/ChATlas.git`), then run **`install.bat`** (Windows) or **`install.command`** (macOS; if blocked, right-click → Open, or `bash install.command` in Terminal). This creates a conda environment called `chatlas`.

### First start
Open **Settings**:
- **Open token page**, log in with the Google account you use in Neuroglancer, copy the token, paste it and click **Save token**. Then **Test connection**.
- Optional: point **mesh cache** to a folder of meshes you already downloaded, so nothing is downloaded twice. Click **Save settings**.

To update: install the new version over the old one. Your data folder (`~/ChATlas`: settings, mesh cache, outputs) is never touched by installing or uninstalling.

## Synapse partners

For a cell annotated with **line annotations** in Neuroglancer (one end on the target cell, the other on a partner):

1. **Load Neuroglancer state…** – a `.txt`/`.json` file containing the JSON state (text before the first `{` is ignored, so a pasted email works).
2. **Analyse partners** – looks up the segment at both ends of every line (current root IDs), identifies the target cell, looks every partner up in the manual and machine cell-type tables, fits the ChAT surfaces from nearby SACs, measures the stratification of bipolar-like partners, and classifies unlabelled ones with a classifier trained on labelled bipolars nearby (cross-validated accuracy in the log).
3. **Partner types** – tick types to show/hide; hover any point or mesh for type and root ID. **Load partner meshes** adds the 3D partner cells for the ticked types.
4. **Distance** – **Pick origin** and click on the target cell where the primary dendrite leaves the soma (or type a Neuroglancer voxel). **Distance plots** shows distance per type, cumulative distributions, a map around the origin, depth vs distance, and polar plots per type; the log lists KS tests per type.
5. **Depth plots**, **Export tables** (partners, annotations with distances, classifier report, screenshot).

Clicking a table row copies the root ID and centres the view on that partner.

## Cell types

1. **Load cell-type tables**, choose label source (manual or manual+machine), class and type (any class: BC, AC, RGC, …).
2. Set the region: centre voxel (Neuroglancer x, y) or **Centre on cell** by root ID, and a radius.
3. **Show cells** – meshes of all cells of that type with soma in the region, optional ChAT surfaces and somata of all labelled cells nearby (hover for class/type/ID).
4. **Stratification & mosaic** – per-cell depth profiles, outlines at the main stratification depth (mosaic) and depth vs size; the table gains the measurements.

## Viewing in Neuroglancer

Every tab has an **Open in Neuroglancer** button. It builds a Neuroglancer state with the current selection (cells coloured as in ChATlas, synapse points / somata / search square as annotation layers), uploads it to the dataset's CAVE state server and opens the link in the browser (the link is also copied). Neuroglancer streams multi-resolution meshes, so it is the fastest way to look at many large cells; use ChATlas for selection and analysis.

## Notes

- Meshes are cached in the mesh cache folder; the first look at a region downloads them, later views are fast.
- Distances: choose **straight line in 3D** or **along the cell** in the Partners tab. Path distances use the target's L2 chunk graph (chunked-graph adjacency + L2-cache positions; Dijkstra from the origin), falling back to the mesh surface. Annotations on pieces not connected to the origin get no path distance.
- Partner direction (pre/post) is not encoded in line annotations.
- Data folder: `~/ChATlas` (Windows: `%USERPROFILE%\ChATlas`) — settings, mesh cache, outputs, `chatlas.log`.

## Releases (maintainers)

Installers are built automatically by GitHub Actions (`.github/workflows/build-installers.yml`) with conda **constructor** (`installer/construct.yaml`):

1. Set the new version in `chatlas/__init__.py` and `pyproject.toml`.
2. Commit, then tag and push: `git tag v1.5.1 && git push origin v1.5.1` (in GitHub Desktop: *History → right-click the commit → Create Tag…*, then *Push*).
3. About 20–30 minutes later the release appears under **Releases** with the three installers attached.

The workflow can also be started by hand from the **Actions** tab (installers are then kept as workflow artifacts for one day).

Private repository: GitHub Free includes 2,000 Actions minutes a month, and macOS / Windows jobs count 10× / 2×, so one release uses roughly 550 minutes (about three releases a month for free). Public repositories build for free. Only collaborators can download releases of a private repository.

## License

MIT — see [LICENSE](LICENSE). © 2026 Gergely Szarka, Szentágothai Research Centre, University of Pécs.
