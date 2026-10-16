[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23404697.svg)](https://doi.org/10.5281/zenodo.23404697)


# WUI Mapping Tool

A Python tool for mapping the Wildland-Urban Interface (WUI) anywhere in the contiguous United States. It combines building density from [HISDAC-US](https://doi.org/10.7910/DVN/U2P66Z) historical built-up property records with vegetation from the [National Land Cover Database (NLCD)](https://www.mrlc.gov/), and classifies WUI intermix and interface zones following the Radeloff/SILVIS methodology. Results can optionally be validated against [SILVIS Lab](https://silvis.forest.wisc.edu/data/wui-change/) WUI maps.

The initial tool was developed by Max Warnock, Quin Browder, and Victoria Madden for GEOG 4303 at CU Boulder (Spring 2025). See the [project paper](docs/wui_mapping_paper.pdf) for methods and results as of May 2025. I have since added additional features and improvements, such as automatic downloads for anywhere in the country, and fixes for some of the WUI mapping calculations and SILVIS map comparisons. 

![WUI map of Colorado's Northern Front Range, with intermix in red and interface in orange](docs/images/front_range_wui.jpg)

*WUI map of Colorado's Northern Front Range, from Fort Collins to Castle Rock. Intermix (red) is housing mixed into wildland vegetation, and interface (orange) is housing next to large vegetated areas.*

## Features

- Downloads NLCD land cover and HISDAC-US built-up property locations (BUPL) for any state and year, plus SILVIS Lab WUI maps if you want them
- Adjustable WUI criteria (moving window radius, housing density threshold, vegetation thresholds, and buffer distance), with standard values suggested at each prompt
- Intermix and interface classification using circular moving windows
- Optional WUI map split by forest and shrubland cover
- Comparison to SILVIS Lab maps with accuracy, precision, recall, F1, and a confusion matrix
- ArcGIS Pro layer files (.lyrx) for map symbology

## How it works

1. NLCD is reprojected and resampled to the BUPL grid (about 250 m), and BUPL is clipped to the NLCD study area.
2. A circular moving window calculates the share of wildland vegetation and the building density around each cell. Wildland vegetation includes the NLCD forest, shrubland, grassland, and wetland classes. Agriculture is left out, as in SILVIS.
3. Cells below the minimum building density are removed. The standard value is 6.17 buildings per km², or about 1 housing unit per 40 acres.
4. Cells with at least 50% wildland vegetation (the standard value) are classified as intermix.
5. Cells with less vegetation are classified as interface if they fall within 2.4 km of a large vegetated area. By default, a large vegetated area is at least 5 km² with at least 75% vegetation.

## Requirements

- ArcGIS Pro with the Spatial Analyst extension, for `arcpy`
- scikit-learn in the ArcGIS Pro Python environment, for the SILVIS comparison statistics
- A separate conda environment with `geopandas`, `rasterio`, and `requests` for the data download script ([environment.yml](environment.yml)). These are kept separate from the ArcGIS Pro environment because they can conflict with the package versions ArcGIS Pro uses.

## Installation

```bash
git clone https://github.com/maxwarnock/wui_mapping.git
cd wui_mapping
```

### ArcGIS Pro environment

This environment runs the mapping tool. ArcGIS Pro's default environment can't be modified, so you need to clone it first. You can do this in ArcGIS Pro's Package Manager (under Settings), or from the Python Command Prompt:

```bash
conda create --clone arcgispro-py3 --name wui_mapping
activate wui_mapping
conda install scikit-learn
```

### Download environment

This environment runs `download_data.py`:

```bash
conda env create -f environment.yml
```

## Usage

### 1. Download data

In the `wui_data_download` environment:

```bash
python download_data.py --state CO --year 2020 --silvis
```

This saves `data/nlcd_CO_2019.tif`, `data/BUPL_CO_2020.tif`, and the SILVIS Lab WUI map for Colorado in `silvis_data/`. NLCD is only published for certain years (2001, 2004, 2006, 2008, 2011, 2013, 2016, 2019, and 2021), so the closest available year is used. If you run the script without any arguments, it will ask you for the state and year.

| Option | Description |
|---|---|
| `--state` | State name or two-letter abbreviation |
| `--year` | Year to download |
| `--resolution` | NLCD resolution in meters (default: 90). Only use 30 for small states, since downloading a whole state at 30 m can run out of memory. |
| `--silvis` | Also download the state's SILVIS Lab WUI map. This is off by default because the files are large (about 170 MB for Colorado and 400 MB for California). |
| `--skip-nlcd`, `--skip-bupl` | Skip downloading NLCD or BUPL, for example if you only need the SILVIS map |

### 2. Run the mapping tool

In the `wui_mapping` (ArcGIS Pro) environment:

```bash
python wui_mapping_tool.py
```

The tool uses the most recently downloaded `nlcd_*.tif` and `BUPL_*.tif` files in `data/`, then asks a series of questions. Press Enter at any prompt to use the standard value.

| # | Question | Standard value | Affects |
|---|---|---|---|
| 1 | Also produce a WUI map split by vegetation class? | | Extra output |
| 2 | Moving window radius (1 = 250 m) | 2 | Intermix and interface |
| 3 | Minimum building density (buildings per km²) | 6.17 | Intermix and interface |
| 4 | Minimum wildland vegetation for intermix (%) | 50 | Intermix |
| 5 | Minimum size of a large vegetated area (km²) | 5 | Interface |
| 6 | Minimum vegetation cover in large vegetated areas (%) | 75 | Interface |
| 7 | Buffer distance around large vegetated areas (km) | 2.4 | Interface |
| 8 | Compare the result to a SILVIS Lab WUI map? | | Validation |
| 9 | Recompute statistics and a confusion matrix with scikit-learn? | | Validation |

To use specific files instead of the most recent downloads, set these environment variables:

| Variable | Purpose |
|---|---|
| `WUI_NLCD_PATH` | Path to a specific NLCD raster |
| `WUI_BUPL_PATH` | Path to a specific BUPL raster |
| `WUI_SILVIS_PATH` | Path to a specific SILVIS shapefile |
| `WUI_MAPPING_WORKSPACE` | Workspace folder (default: the repository folder) |

### 3. View the results

Outputs are saved to `results/` and named with the state and year of the input data:

- `wui_<STATE>_<YEAR>.tif` is the WUI map (intermix and interface).
- `wui_veg_<STATE>_<YEAR>.tif` is the WUI map by vegetation class, if you answered yes to question 1.

Intermediate rasters and shapefiles are saved to `steps/`.

To apply the symbology in ArcGIS Pro, add the raster to a map and open its Symbology pane. Open the menu in the top right corner, choose Import from layer file, and select `wui_symbology.lyrx` (or `wui_veg_symbology.lyrx` for the vegetation map).

## Comparing to SILVIS Lab WUI maps

Answer yes to question 8 to compare your map with the [SILVIS Lab](https://silvis.forest.wisc.edu/data/wui-change/) WUI map for the same state. You'll need to download the SILVIS map first with `--silvis` (see above). The tool finds the file for your state and compares against the SILVIS year (1990, 2000, 2010, or 2020) closest to your input data.

The comparison uses SILVIS as the reference and scores each cell as WUI or non-WUI, then reports accuracy, precision, recall, and F1. Answer yes to question 9 to also see a confusion matrix. Most cells in a study area are usually non-WUI, so precision, recall, and F1 are more useful than overall accuracy.

## Project structure

| Path | Contents |
|---|---|
| `wui_mapping_tool.py` | Main script: data preparation, WUI classification, and prompts |
| `wui_mapping_module.py` | Moving windows, vegetation mapping, and SILVIS comparison |
| `download_data.py` | Downloads NLCD, HISDAC-US BUPL, and SILVIS data for a state |
| `environment.yml` | Conda environment for `download_data.py` |
| `wui_symbology.lyrx` | ArcGIS Pro symbology for the WUI map |
| `wui_veg_symbology.lyrx` | ArcGIS Pro symbology for the vegetation WUI map |
| `docs/` | Project paper and README images |
| `data/` | Input rasters (created by `download_data.py`) |
| `silvis_data/` | SILVIS Lab shapefiles (created by `download_data.py --silvis`) |
| `steps/` | Intermediate outputs (created when the tool runs) |
| `results/` | Final WUI maps (created when the tool runs) |

## Data sources

- NLCD: U.S. Geological Survey, [Multi-Resolution Land Characteristics Consortium](https://www.mrlc.gov/)
- HISDAC-US BUPL: Uhl, J. H., and Leyk, S. *Historical Settlement Data Compilation for the United States*, Harvard Dataverse. https://doi.org/10.7910/DVN/U2P66Z
- SILVIS Lab WUI maps: University of Wisconsin-Madison SILVIS Lab. https://silvis.forest.wisc.edu/data/wui-change/
- State boundaries: U.S. Census Bureau TIGER/Line

## References

- Bar-Massada, A., Stewart, S. I., Hammer, R. B., Mockrin, M. H., and Radeloff, V. C. (2013). Using structure locations as a basis for mapping the wildland urban interface. *Journal of Environmental Management*, 128, 540-547. https://www.fs.usda.gov/rm/pubs_other/rmrs_2013_bar_masada_a001.pdf
- Radeloff, V. C., Helmers, D. P., Kramer, H. A., et al. (2018). Rapid growth of the US wildland-urban interface raises wildfire risk. *Proceedings of the National Academy of Sciences*, 115(13), 3314-3319. https://doi.org/10.1073/pnas.1718850115

## License

This project is licensed under the [MIT License](LICENSE.md).
