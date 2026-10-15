'''*********************************************
author: Max Warnock, Quin Browder, Victoria Madden
Date: 5/3/2025
GEOG 4303 Final Project
WUI Mapping Tool - Main .py file
*********************************************'''

import glob
import os
import re
import numpy
import numpy as np
import arcpy
from arcpy import env
import arcpy.sa as sa
import wui_mapping_module
import matplotlib.pyplot as plt
from sklearn.metrics import ConfusionMatrixDisplay

# Workspace defaults to this script's folder. Override by setting the
# WUI_MAPPING_WORKSPACE environment variable if you want to run against
# a different location.
BASE_DIR = os.environ.get("WUI_MAPPING_WORKSPACE", os.path.dirname(os.path.abspath(__file__)))
env.workspace = BASE_DIR
env.overwriteOutput = 1
arcpy.CheckOutExtension("Spatial")

# Make sure the folders that intermediate/final outputs get saved into exist.
os.makedirs(os.path.join(BASE_DIR, "steps"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "results"), exist_ok=True)


def find_data_file(pattern, description, override_env_var):
    '''Finds a data file in data/ matching pattern (e.g. "nlcd_*.tif"),
    so this script works with whatever year/state download_data.py last
    produced, instead of a hardcoded filename. If more than one file
    matches (e.g. leftover sample data alongside a fresh download), the
    most recently modified one is used. Set the given environment
    variable to an exact path to bypass this and pick a specific file.'''
    override = os.environ.get(override_env_var)
    if override:
        print(f"Using {description} from {override_env_var}: {override}")
        return override

    matches = sorted(glob.glob(os.path.join(BASE_DIR, "data", pattern)))
    if not matches:
        raise FileNotFoundError(
            f"No {description} found in data/ matching '{pattern}'. "
            f"Run download_data.py first, or set {override_env_var} to an exact file path."
        )
    chosen = max(matches, key=os.path.getmtime)
    if len(matches) > 1:
        others = ", ".join(os.path.basename(m) for m in matches if m != chosen)
        print(f"Multiple {description} files found in data/; using the most recently modified: "
              f"{os.path.basename(chosen)} (ignoring: {others})")
    else:
        print(f"Using {description}: {os.path.basename(chosen)}")
    return chosen


def parse_state_year(path):
    '''Extracts (state_abbr, year) from a filename produced by
    download_data.py, e.g. "nlcd_CO_2019.tif" -> ("CO", 2019). Falls back to
    (None, year) for older filenames without a state code (e.g. the original
    "nlcd_2020.tif" sample data), and to (None, None) if no year is found
    either. Used only to name result outputs - not required for the
    pipeline to run.'''
    name = os.path.splitext(os.path.basename(path))[0]
    match = re.match(r"^(?:nlcd|BUPL)_([A-Za-z]{2})_(\d{4})$", name)
    if match:
        return match.group(1), int(match.group(2))
    match = re.match(r"^(?:nlcd|BUPL)_(\d{4})$", name)
    if match:
        return None, int(match.group(1))
    return None, None


# DATA PREPARATION
# Define the NLCD raster from the data folder.
# This is the input raster that you can clip to your own study area of interest.
# You can use our sample data area for LA, or you can clip an NLCD
# raster to your own area of interest and input the name and path the line below.
nlcd_path = find_data_file("nlcd_*.tif", "NLCD raster", "WUI_NLCD_PATH")
nlcd = sa.Raster(nlcd_path)
print("NLCD height:",nlcd.height)
print("NLCD width:",nlcd.width)
print("NLCD cell height:",nlcd.meanCellHeight)
print("NLCD cell width:",nlcd.meanCellWidth)

# Define the BUPL raster
# We will clip the BUPL raster in this script, so you can use a larger BUPL raster if you want.
bupl_path = find_data_file("BUPL_*.tif", "BUPL raster", "WUI_BUPL_PATH")
bupl = sa.Raster(bupl_path)
arcpy.env.cellSize = bupl.meanCellHeight
print("BUPL height:",bupl.height)
print("BUPL width:",bupl.width)
print("BUPL cell height:",bupl.meanCellHeight)
print("BUPL cell width:",bupl.meanCellWidth)

# Tag result output filenames with the state/year the input data came from
# (when download_data.py's naming convention is detected), so results from
# different runs don't overwrite each other in results/.
_nlcd_state, _nlcd_year = parse_state_year(nlcd_path)
_bupl_state, _bupl_year = parse_state_year(bupl_path)
_result_state = _nlcd_state or _bupl_state
_result_year = _nlcd_year or _bupl_year
if _result_state and _result_year:
    RESULT_TAG = f"_{_result_state}_{_result_year}"
elif _result_year:
    RESULT_TAG = f"_{_result_year}"
else:
    RESULT_TAG = ""

# reproject NLCD raster to match BUPL
# Also, we're saving all intermediate steps to a 'steps' folder
#
# Note: env.snapRaster/env.extent are deliberately NOT set to nlcd here, even
# though nlcd defines the study area. nlcd is still in its original CRS at this
# point (e.g. geographic degrees, if it came from download_data.py), while
# ProjectRaster's output is in bupl's CRS (typically projected, meters). Setting
# env.extent from a geographic-CRS raster while outputting into a projected CRS
# was found to make ArcGIS silently misinterpret the extent bounds - reproduced
# with a Rhode Island test case where it produced a wildly distorted output
# (16463 x 368 cells instead of the correct ~469 x 368) with no error at all.
nlcd_reproject = arcpy.management.ProjectRaster(nlcd,'steps/nlcd_reproject.tif',bupl.spatialReference,"NEAREST", env.cellSize)

# resample NLCD raster to match BUPL
nlcd_resample = arcpy.management.Resample(nlcd_reproject, 'steps/nlcd_resample.tif', env.cellSize, "NEAREST")
nlcd_resample = sa.Raster('steps/nlcd_resample.tif')

# NOW it's safe to set snap raster / extent, using nlcd_resample - already
# reprojected into bupl's CRS - as the reference instead of the original nlcd.
arcpy.env.snapRaster = nlcd_resample #https://pro.arcgis.com/en/pro-app/latest/tool-reference/environment-settings/snap-raster.htm
# Snap raster allows us to make sure extents of both NLCD and BUPL rasters are the same
arcpy.env.extent = nlcd_resample.extent

# Clip the BUPL data to the NLCD. This allows the user to just input
# a clip of the NLCD, and select a BUPL layer of their choice (for whole US).
# The BUPL is low enough resolution that this is still fairly efficient.
#
# sa.ExtractByRectangle(bupl, nlcd_resample) reliably crashed ArcGIS Pro's
# Python (STATUS_HEAP_CORRUPTION) here - root-caused by stepping through this
# script line by line in pdb, which pinned the crash to this exact call
# regardless of input raster size (ruling out the earlier CONUS-vs-state-size
# theory as the cause of THIS particular crash). arcpy.management.Clip is a
# different tool (Data Management, not Spatial Analyst) that produces the
# same clipped-to-BUPL's-own-grid result without crashing. MAINTAIN_EXTENT is
# required: NO_MAINTAIN_EXTENT (the default) let the output drift a couple of
# cells larger than nlcd_resample, breaking the NLCD/BUPL same-size invariant
# this pipeline depends on throughout.
arcpy.management.Clip(bupl, "#", "steps/BUPL_Clipped.tif", nlcd_resample, "", "NONE", "MAINTAIN_EXTENT")
bupl_clipped = sa.Raster("steps/BUPL_Clipped.tif")
arcpy.env.mask = bupl_clipped
#Use extract by mask to make sure they are the same size
nlcd_final = sa.ExtractByMask(nlcd_resample, bupl_clipped)
nlcd_final.save("steps/nlcd_final.tif")


#check NLCD and BUPL final size. They should be the same
print("NLCD final height:",nlcd_final.height)
print("NLCD final width:",nlcd_final.width)
print("BUPL final height:",bupl_clipped.height)
print("BUPL final width:",bupl_clipped.width)

# Convert to numpy arrays. nodata_to_value=0 is important: without it,
# NoData cells (e.g. where MAINTAIN_EXTENT padded the clip for a state whose
# NLCD and BUPL extents don't perfectly nest - seen with California) come
# through as a float sentinel like -3.4e38, which overflows the window-sum
# in wui_mapping_module.circleWindow ("overflow encountered in reduce").
# 0 is the right fill here: no land cover class / no buildings.
nlcd_numpy = arcpy.RasterToNumPyArray(nlcd_final, nodata_to_value=0)
bupl_numpy = arcpy.RasterToNumPyArray(bupl_clipped, nodata_to_value=0)

#check shapes
print("NLCD array shape:", nlcd_numpy.shape)
print("BUPL array shape:", bupl_numpy.shape)

# assign cell size, since height and width are the same
cellSize = bupl_clipped.meanCellHeight

# find the lower left point of the BUPL raster
lowLeftPnt = bupl_clipped.extent.lowerLeft

# Select wildland vegetation from the NLCD array, following the Radeloff/SILVIS
# definition: forest (41-43), shrub/scrub (51-52), grassland/herbaceous (71),
# and wetlands (90 woody, 95 emergent herbaceous). Agriculture (81, 82) is
# deliberately left out, as in SILVIS.
# Note: vegWUISelectNLCD() (the optional Q1 veg-class sub-mapping) still splits
# only forest vs shrubland and does not place wetlands in either bucket, so
# wetland-dominated WUI won't receive a forest/shrub tag in wui_veg output.
vegetation = np.where((nlcd_numpy==41)|(nlcd_numpy==42)|(nlcd_numpy==43)|(nlcd_numpy==51)|(nlcd_numpy==52)|(nlcd_numpy==71)|(nlcd_numpy==90)|(nlcd_numpy==95), 1, 0)
vegetation_save = arcpy.NumPyArrayToRaster(vegetation, lowLeftPnt,cellSize,cellSize)
vegetation_save.save('steps/vegetation.tif')

while True:
    print("---Question 1---")
    print('Would you like to map the WUI according to different \n'
          'types of vegetation cover? Type yes or no.')
    vegCheckQ1 = wui_mapping_module.promptYesNo("yes/no:")
    if vegCheckQ1 == 'yes':
        forest, shrubland = wui_mapping_module.vegWUISelectNLCD(nlcd_numpy, lowLeftPnt, cellSize)
        classList = [bupl_numpy, vegetation, forest, shrubland]
        classListNames = ["bupl_numpy", "vegetation","forest","shrubland"]
    else:
        classList = [bupl_numpy, vegetation]
        classListNames = ["bupl_numpy", "vegetation"]
        break
    break

#MOVING WINDOW OPERATIONS (Steps 1 and 2)
# get the spatial reference of the raster
spref = bupl.spatialReference

# Create an output list of arrays of same size with zeros
classListOut = [numpy.zeros(array.shape).astype(float) for array in classList]

# We ask a question for the user to define the size of the mask radius
print("---Question 2---")
print("Choose radius for circular moving window...\nRadius of 1 = 250m")
print("Whole numbers only.")
print("Standard radius: 2")
radius = wui_mapping_module.promptInt("Enter radius size:", default=2)

#run the moving window function (circleWindow)
result = wui_mapping_module.circleWindow(classList,classListOut,classListNames,radius)

#Select developed areas that meet a minimum built-up density.
# developed_win is the moving-window MEAN BUPL count per raster cell. To compare
# it against the Radeloff/SILVIS threshold (6.17 = ~1 housing unit per 40 acres),
# which is expressed per SQUARE KILOMETRE, we first divide by the cell area in
# km^2. Previously the per-cell mean was compared directly to 6.17, which for
# 250 m cells (0.0625 km^2) is ~16x too strict and badly under-mapped
# low-density / exurban WUI.
print("---Question 3---")
print("Choose minimum built-up density in buildings per square km.")
print("Standard threshold: 6.17  (Radeloff/SILVIS minimum, ~1 unit per 40 acres)")
print("Higher values restrict the map to denser development.")
building_threshold = wui_mapping_module.promptFloat("Enter threshold:", default=6.17)

developed_win = result[0]  # BUPL moving-window mean, in built-up locations per cell
cell_area_km2 = (cellSize / 1000.0) ** 2
developed_per_km2 = developed_win / cell_area_km2
developed_select = np.where((developed_per_km2 >= building_threshold), 1, 0)
developed_select_to_raster = arcpy.NumPyArrayToRaster(developed_select, lowLeftPnt,cellSize,cellSize)
developed_select_to_raster.save('steps/developed_select.tif')

#view vegetation result as raster for double checking
vegetation_win = result[1]
vegetation_win_raster = arcpy.NumPyArrayToRaster(vegetation_win, lowLeftPnt,cellSize,cellSize)
vegetation_win_raster.save('steps/vegetation_win.tif')

#Select vegetation areas with greater than x% vegetation cover
print("---Question 4---")
print("Choose vegetation areas greater than x percent for intermix criteria")
print("Standard percentage: 50")
veggie_percent_g = wui_mapping_module.promptFloat("Enter percent value:", default=50)
veggie_percent_convert_g = veggie_percent_g *0.01
# Intermix uses >= the threshold; interface (below) uses strictly < the
# threshold, so the two are mutually exclusive and a cell at exactly the cutoff
# is intermix only. SILVIS: intermix is >=50% wildland veg, interface is <50%.
vegetation_select_greater = np.where((vegetation_win >= veggie_percent_convert_g), 1, 0)
vegetation_select_to_raster_greater = arcpy.NumPyArrayToRaster(vegetation_select_greater, lowLeftPnt,cellSize,cellSize)
vegetation_select_to_raster_greater.save('steps/vegetation_greater.tif')
# Select areas strictly below the threshold (see note above)
vegetation_select_less = numpy.where((vegetation_win < veggie_percent_convert_g), 1, 0)
vegetation_select_to_raster_less = arcpy.NumPyArrayToRaster(vegetation_select_less, lowLeftPnt,cellSize,cellSize)
vegetation_select_to_raster_less.save('steps/vegetation_less.tif')
print("Selections completed \nEnd of steps 1 and 2")

#STEP 3
print("---Question 5---")
print("Choose large vegetation area size...")
print("Input units in square km:")
print("Standard size: 5")
sq_km = wui_mapping_module.promptFloat("Enter size:", default=5)
# Calculate number of 250x250m cells needed for x km^2
sq_meters = sq_km * 1000000
square_cell_area = 250*250
veggie_area = sq_meters / square_cell_area
print("Number of cells for",sq_km,"square km:", veggie_area)

# Select vegetation areas greater than 75% (or other threshold)
print("---Question 6---")
print("Select vegetation % coverage for 'large vegetation areas'")
print("Standard value: 75")
large_veg_percent = wui_mapping_module.promptFloat("Enter percent:", default=75)
large_veg_percent_convert = large_veg_percent * 0.01
#select >= this value from the vegetation moving window
vegetation_select_for_interface = np.where((vegetation_win >= large_veg_percent_convert), 1, 0)
#convert to raster so we can apply region group tool
vegetation_for_interface_r = arcpy.NumPyArrayToRaster(vegetation_select_for_interface, lowLeftPnt,cellSize,cellSize)
vegetation_for_interface_r.save('steps/vegetation_for_interface.tif')

#region group tool
region_group_veg = sa.RegionGroup(vegetation_for_interface_r, "EIGHT", "WITHIN", "", 0)
region_group_raster_veg = "steps/vegetation_group.tif"
region_group_veg.save(region_group_raster_veg)

#use search cursor to get the count of cells per group
region_dict = {} #dictionary containing sizes of all groups
with arcpy.da.SearchCursor(region_group_raster_veg, ['Value', 'Count']) as cursor:
    for val, count in cursor:
        if val != 0 and count > veggie_area:
            region_dict[val] = 1 # codes it as 1, or NoData

# RemapValue function allows us to code all areas greater than user input size to 1.
# Other pixels are NoData.
remap = sa.RemapValue([[val, bin_val] for val, bin_val in region_dict.items()])

# Reclassify and apply out remapping definition.
veggie_five_km = sa.Reclassify(region_group_raster_veg, "Value", remap, "NODATA")
veggie_five_km.save("steps/veggie_five_km.tif")
veggie_five_km = sa.Raster('steps/veggie_five_km.tif')
print("Step 3 complete")

#STEP 4
# convert the x km^2 veggie data to polygons to make for easier buffering
veggie_to_poly = arcpy.conversion.RasterToPolygon(veggie_five_km,"steps/veggie_five_km_poly.shp","NO_SIMPLIFY", "Value")

#ask question for user to define the buffer distance
print("---Question 7---")
print("Choose the buffer distance for vegetation areas \nof at least your input of",sq_km,"square km")
print("Input units in kilometers")
print("Standard buffer distance: 2.4")
buff_dist = wui_mapping_module.promptFloat("Enter size:", default=2.4)

buff_m = buff_dist * 1000 # convert km to m for buffer tool

veggie_buffer = arcpy.analysis.Buffer(veggie_to_poly,"steps/veggie_buffer.shp",buff_m,"FULL","ROUND","ALL",None)

#convert back to a raster
veggie_buff_raster = arcpy.conversion.PolygonToRaster(veggie_buffer,"FID", "steps/veggie_buff_raster.tif","CELL_CENTER","NONE",cellSize)

#Using extract by mask to clip buffered areas outside the study area
veggie_buff_extract = sa.ExtractByMask(veggie_buff_raster, bupl_clipped)
veggie_buff_extract.save("steps/veggie_buff_extract.tif")

#Converting back to Numpy array to select values easier
veggie_buff_numpy = arcpy.RasterToNumPyArray(veggie_buff_extract)
veggie_buff_recode = np.where((veggie_buff_numpy == 0), 1, 0)

#Converting back to raster
veggie_buff_recode_raster = arcpy.NumPyArrayToRaster(veggie_buff_recode, lowLeftPnt,cellSize,cellSize)
veggie_buff_recode_raster.save('steps/veggie_buff_recode_raster.tif')
print("Step 4 complete")

#STEP 5 (selecting WUI intermix)
wui_intermix = developed_select + vegetation_select_greater
wui_intermix_select = numpy.where((wui_intermix == 2), 1, 0)
wui_intermix_raster = arcpy.NumPyArrayToRaster(wui_intermix_select,lowLeftPnt,cellSize,cellSize)
wui_intermix_raster.save('steps/wui_intermix.tif')
print("WUI intermix map complete")

#STEP 6 (select WUI interface)
wui_interface = developed_select + veggie_buff_recode + vegetation_select_less
wui_interface_select = numpy.where((wui_interface == 3), 1, 0)
wui_interface_raster = arcpy.NumPyArrayToRaster(wui_interface_select, lowLeftPnt,cellSize,cellSize)
wui_interface_raster.save('steps/wui_interface.tif')
print("WUI interface map complete")

# Combine WUI intermix and interface into one raster:
# Class value 1 = interface
# Class value 2 = intermix
# Save to results folder
# Assign explicitly with intermix taking precedence, rather than adding the two
# (2 + 1 = 3 would be an undefined class). With the mutually exclusive veg split
# above this is belt-and-suspenders, but it stays correct if that changes.
wui_class_combine = numpy.where(wui_intermix_select == 1, 2,
                                numpy.where(wui_interface_select == 1, 1, 0))
wui_class_combine_r = arcpy.NumPyArrayToRaster(wui_class_combine, lowLeftPnt,cellSize,cellSize)
wui_class_combine_r.save(f'results/wui{RESULT_TAG}.tif')

print("***************************************")
print("***Summarizing User Input parameters***")
print("Moving window radius:",radius)
print("Minimum built-up density (buildings per square km):",building_threshold)
print("Vegetation cover selection greater than",veggie_percent_g,"percent")
print("Vegetation % coverage for 'large vegetation areas",large_veg_percent,"percent")
print("Vegetation region group selection of:",sq_km,"square km")
print("Buffer distance for region grouped vegetation:",buff_dist)
print("*******WUI MAP COMPLETE******* (Go check your results folder)")

#Vegetation mapping using moving window outputs
if vegCheckQ1 == 'yes':
    print("working on applying vegetation classes to WUI map...")
    wui_mapping_module.mapVegWUI(result,lowLeftPnt,cellSize,wui_interface_select,wui_intermix_select,RESULT_TAG)

#Comparison statistics to SILVIS WUI map and confusion matrix
while True:
    print("---Question 8---")
    print("Would you like to compare your output WUI map to \n"
          "a SILVIS Lab WUI map?")
    print("Prototype: statistics of Accuracy, Precision, Recall, and F1, will be calculated.")
    question8 = wui_mapping_module.promptYesNo("Enter yes/no:")
    if question8 == 'yes':
        print("Working on comparison statistics...")
        silvis_intermix, silvis_interface = wui_mapping_module.compareWUIMaps(cellSize, lowLeftPnt, wui_intermix_select, wui_interface_select,bupl,bupl_clipped,_result_state,_result_year)
        print("---Question 9---")
        print("Do you want to use SKLearn to recompute statistics and a \n"
              "confusion matrix to compare your WUI map to the SILVIS WUI map?")
        question9 = wui_mapping_module.promptYesNo("Enter yes/no:")
        if question9 =='yes':
            print("Working on confusion matrix...")
            cMatrix = wui_mapping_module.computeConfusionMatrixWUI(wui_intermix_select, wui_interface_select, silvis_intermix, silvis_interface)
            disp = ConfusionMatrixDisplay(confusion_matrix=cMatrix, display_labels=["Positive", "Negative"])
            disp_plot = disp.plot()
            print("confusion matrix completed (close the plot window to finish)")
            plt.show()
            print("ending script")
        break
    else:
        print("ending script")
        break